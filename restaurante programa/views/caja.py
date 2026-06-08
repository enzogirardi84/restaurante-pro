"""
views/caja.py — Servicio de caja para COMANDAPRO ERP v2.0.
Gestiona cobro de pedidos, cierre de mesas, arqueo de caja,
descuentos, propinas y resumen financiero por turno/usuario.

Arquitectura:
- Metodos estaticos que retornan Tuple[bool, str] (escritura) o list[Dict]/Dict (lectura).
- Sin dependencia de Streamlit. UI-agnostico.
- Transacciones atomicas para operaciones criticas (cobrar + liberar mesa).
- Queries parametrizadas con placeholder dinamico para SQLite/PG.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from database import execute_query, get_connection, get_db_type, registrar_auditoria


# ── Constantes de dominio ──────────────────────────────────────────────
MEDIOS_PAGO_VALIDOS = {"efectivo", "tarjeta", "transferencia", "cuenta_dni", "otro"}
ESTADOS_COBRABLES = {"listo", "entregado"}
ESTADO_PEDIDO_MESA = {"cobrado": "libre", "pendiente": "ocupada"}


# ── Servicio ──────────────────────────────────────────────────────────

class CajaService:

    # ── Lectura: pedidos listos para cobrar ─────────────────────────

    @staticmethod
    def pedidos_para_cobrar() -> List[Dict]:
        """
        Retorna pedidos en estado 'listo' o 'entregado' con resumen
        de productos, mozo, mesa y total estimado.
        """
        ph = "%s" if get_db_type() == "postgres" else "?"
        return execute_query(f"""
            SELECT pc.id_pedido,
                   pc.id_mesa,
                   m.numero_mesa,
                   u.nombre || ' ' || u.apellido AS mozo,
                   pc.estado_comanda,
                   pc.fecha_hora,
                   SUM(pd.cantidad * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)) AS subtotal,
                   GROUP_CONCAT(DISTINCT pm.nombre, ', ') AS productos
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda IN ('listo', 'entregado')
              AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
            GROUP BY pc.id_pedido
            ORDER BY pc.fecha_hora ASC
        """, fetch=True) or []

    @staticmethod
    def detalle_pedido(id_pedido: int) -> Dict:
        """Retorna detalle completo de un pedido con sus lineas."""
        ph = "%s" if get_db_type() == "postgres" else "?"
        cabecera = execute_query(f"""
            SELECT pc.*, m.numero_mesa,
                   u.nombre || ' ' || u.apellido AS mozo
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            WHERE pc.id_pedido = {ph}
        """, (id_pedido,), fetch=True)

        if not cabecera:
            return {}

        lineas = execute_query(f"""
            SELECT pd.id_detalle,
                   pm.nombre AS producto,
                   pd.cantidad,
                   COALESCE(pd.precio_unitario_facturado, pm.precio_venta) AS precio_unitario,
                   (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) AS pendiente,
                   pd.observaciones
            FROM pedido_detalle pd
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pd.id_pedido = {ph}
              AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
            ORDER BY pd.id_detalle
        """, (id_pedido,), fetch=True)

        cabecera[0]["lineas"] = lineas
        cabecera[0]["subtotal"] = sum(
            float(l["pendiente"] * l["precio_unitario"]) for l in lineas
        )
        return cabecera[0]

    # ── Escritura: procesar pago ─────────────────────────────────────

    @staticmethod
    def procesar_pago(
        id_pedido: int,
        id_usuario: int,
        medio_pago: str,
        monto_recibido: float,
        descuento: float = 0,
        propina: float = 0,
        cobro_parcial: bool = False,
    ) -> Tuple[bool, str]:
        """
        Procesa el pago de un pedido de forma atomica:
        1. Valida estado y monto
        2. Registra el pago en pagos_mesa y pago_detalle
        3. Actualiza cantidades cobradas en pedido_detalle
        4. Si es cobro total: cierra pedido y libera mesa
        """
        if medio_pago not in MEDIOS_PAGO_VALIDOS:
            return False, f"Medio de pago invalido: {medio_pago}"

        if monto_recibido <= 0:
            return False, "El monto debe ser mayor a cero."

        ph = "%s" if get_db_type() == "postgres" else "?"
        conn = get_connection()

        try:
            conn.execute("BEGIN IMMEDIATE")

            # 1. Validar pedido
            pedido = conn.execute(f"""
                SELECT pc.*, m.numero_mesa
                FROM pedidos_cabecera pc
                JOIN mesas m ON m.id_mesa = pc.id_mesa
                WHERE pc.id_pedido = {ph}
            """, (id_pedido,)).fetchone()

            if not pedido:
                conn.execute("ROLLBACK")
                return False, "El pedido no existe."

            if pedido["estado_comanda"] not in ESTADOS_COBRABLES:
                conn.execute("ROLLBACK")
                return False, f"Estado invalido: '{pedido['estado_comanda']}'. Debe estar 'listo' o 'entregado'."

            # 2. Obtener lineas pendientes
            lineas = conn.execute(f"""
                SELECT id_detalle, id_producto, cantidad,
                       COALESCE(precio_unitario_facturado, (SELECT precio_venta FROM productos_menu WHERE id_producto = pd.id_producto)) AS precio_unitario,
                       (cantidad - COALESCE(cantidad_cobrada, 0) - COALESCE(cantidad_anulada, 0)) AS pendiente
                FROM pedido_detalle pd
                WHERE pd.id_pedido = {ph}
                  AND (cantidad - COALESCE(cantidad_cobrada, 0) - COALESCE(cantidad_anulada, 0)) > 0
            """, (id_pedido,)).fetchall()

            if not lineas:
                conn.execute("ROLLBACK")
                return False, "El pedido no tiene lineas pendientes de cobro."

            # 3. Calcular montos
            subtotal = sum(float(l["pendiente"] * l["precio_unitario"]) for l in lineas)
            descuento_aplicado = min(descuento, subtotal)
            base_imponible = subtotal - descuento_aplicado
            servicio = round(base_imponible * 0.10, 2)  # 10% servicio
            total = round(base_imponible + servicio + propina, 2)

            if monto_recibido < total and not cobro_parcial:
                conn.execute("ROLLBACK")
                return False, (
                    f"Monto insuficiente. Total: ${total:,.0f}, "
                    f"recibido: ${monto_recibido:,.0f}."
                )

            # 4. Insertar pago
            tipo_pago = "parcial" if cobro_parcial else "total"
            conn.execute(f"""
                INSERT INTO pagos_mesa
                    (id_mesa, id_usuario, fecha_hora, medio_pago, subtotal, servicio, total, tipo)
                VALUES ({ph}, {ph}, datetime('now','localtime'), {ph}, {ph}, {ph}, {ph}, {ph})
            """, (pedido["id_mesa"], id_usuario, medio_pago, base_imponible, servicio, total, tipo_pago))

            if get_db_type() == "postgres":
                id_pago = conn.execute("SELECT LASTVAL() AS id").fetchone()["id"]
            else:
                id_pago = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

            # 5. Insertar pago_detalle y actualizar cantidades cobradas
            for linea in lineas:
                pendiente = float(linea["pendiente"])
                precio = float(linea["precio_unitario"])
                conn.execute(f"""
                    INSERT INTO pago_detalle (id_pago, id_detalle, cantidad, precio_unitario)
                    VALUES ({ph}, {ph}, {ph}, {ph})
                """, (id_pago, linea["id_detalle"], pendiente, precio))
                conn.execute(f"""
                    UPDATE pedido_detalle
                    SET cantidad_cobrada = COALESCE(cantidad_cobrada, 0) + {ph}
                    WHERE id_detalle = {ph}
                """, (pendiente, linea["id_detalle"]))

            # 6. Si es cobro total, cerrar pedido y liberar mesa
            if not cobro_parcial:
                conn.execute(f"""
                    UPDATE pedidos_cabecera
                    SET estado_comanda = 'cobrado',
                        medio_pago = {ph},
                        total_cobrado = {ph},
                        fecha_cobro = datetime('now','localtime')
                    WHERE id_pedido = {ph}
                """, (medio_pago, total, id_pedido))

                conn.execute(f"""
                    UPDATE mesas
                    SET estado = 'libre'
                    WHERE id_mesa = {ph}
                """, (pedido["id_mesa"],))

            conn.execute("COMMIT")
            registrar_auditoria("caja", "pago_procesado",
                                f"Pedido {id_pedido} - {medio_pago} - ${total:,.0f}")
            return True, f"Cobro exitoso. Total: ${total:,.0f}"

        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            print(f"Error procesando pago pedido {id_pedido}: {e}")
            return False, "Error interno al procesar el pago."

    # ── Arqueo de caja ───────────────────────────────────────────────

    @staticmethod
    def arqueo_caja(usuario_id: int | None = None, fecha: str | None = None) -> Dict:
        """
        Genera resumen de arqueo de caja.
        Filtra por usuario y/o fecha opcionalmente.
        """
        ph = "%s" if get_db_type() == "postgres" else "?"
        where_clauses = []
        params: list = []

        if usuario_id:
            where_clauses.append(f"pg.id_usuario = {ph}")
            params.append(usuario_id)
        if fecha:
            where_clauses.append(f"DATE(pg.fecha_hora) = {ph}")
            params.append(fecha)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        resumen = execute_query(f"""
            SELECT COALESCE(COUNT(*), 0) AS total_pagos,
                   COALESCE(SUM(pg.total), 0) AS total_ingresos,
                   COALESCE(AVG(pg.total), 0) AS ticket_promedio,
                   COALESCE(SUM(CASE WHEN pg.medio_pago = 'efectivo' THEN pg.total ELSE 0 END), 0) AS efectivo,
                   COALESCE(SUM(CASE WHEN pg.medio_pago = 'tarjeta' THEN pg.total ELSE 0 END), 0) AS tarjeta,
                   COALESCE(SUM(CASE WHEN pg.medio_pago NOT IN ('efectivo', 'tarjeta') THEN pg.total ELSE 0 END), 0) AS otros
            FROM pagos_mesa pg
            {where_sql}
        """, tuple(params), fetch=True)

        detalle = execute_query(f"""
            SELECT pg.id_pago, pg.fecha_hora, m.numero_mesa,
                   u.nombre || ' ' || u.apellido AS mozo,
                   pg.medio_pago, pg.subtotal, pg.servicio, pg.total
            FROM pagos_mesa pg
            JOIN mesas m ON m.id_mesa = pg.id_mesa
            JOIN usuarios u ON u.id_usuario = pg.id_usuario
            {where_sql}
            ORDER BY pg.fecha_hora DESC
        """, tuple(params), fetch=True)

        return {
            "resumen": resumen[0] if resumen else {},
            "detalle": detalle or [],
            "filtros": {
                "usuario_id": usuario_id,
                "fecha": fecha or datetime.now().strftime("%Y-%m-%d"),
            },
        }

    @staticmethod
    def resumen_turno(id_usuario: int, fecha: str) -> Dict:
        """Resumen financiero del turno de un usuario en una fecha especifica."""
        ph = "%s" if get_db_type() == "postgres" else "?"
        return execute_query(f"""
            SELECT u.nombre || ' ' || u.apellido AS mozo,
                   COUNT(DISTINCT pg.id_pago) AS cobros_realizados,
                   COUNT(DISTINCT pg.id_mesa) AS mesas_atendidas,
                   COALESCE(SUM(pg.total), 0) AS total_facturado,
                   COALESCE(SUM(pg.servicio), 0) AS total_servicio,
                   ROUND(AVG(pg.total), 0) AS ticket_promedio
            FROM pagos_mesa pg
            JOIN usuarios u ON u.id_usuario = pg.id_usuario
            WHERE pg.id_usuario = {ph}
              AND DATE(pg.fecha_hora) = {ph}
            GROUP BY u.id_usuario
        """, (id_usuario, fecha), fetch=True)

    @staticmethod
    def anular_ultimo_pago(id_pedido: int) -> Tuple[bool, str]:
        """
        Anula el ultimo pago registrado para un pedido.
        Reversa cantidades cobradas en pedido_detalle.
        """
        ph = "%s" if get_db_type() == "postgres" else "?"
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")

            pago = conn.execute(f"""
                SELECT id_pago, id_mesa, tipo FROM pagos_mesa
                WHERE id_pago = (
                    SELECT MAX(id_pago) FROM pagos_mesa
                    WHERE id_pago IN (
                        SELECT id_pago FROM pago_detalle pd2
                        JOIN pedido_detalle pd ON pd.id_detalle = pd2.id_detalle
                        WHERE pd.id_pedido = {ph}
                    )
                )
            """, (id_pedido,)).fetchone()

            if not pago:
                conn.execute("ROLLBACK")
                return False, "No hay pagos para anular en este pedido."

            detalle_pagos = conn.execute(f"""
                SELECT id_detalle, cantidad FROM pago_detalle WHERE id_pago = {ph}
            """, (pago["id_pago"],)).fetchall()

            for dp in detalle_pagos:
                conn.execute(f"""
                    UPDATE pedido_detalle
                    SET cantidad_cobrada = COALESCE(cantidad_cobrada, 0) - {ph}
                    WHERE id_detalle = {ph}
                """, (float(dp["cantidad"]), dp["id_detalle"]))

            conn.execute(f"DELETE FROM pago_detalle WHERE id_pago = {ph}", (pago["id_pago"],))
            conn.execute(f"DELETE FROM pagos_mesa WHERE id_pago = {ph}", (pago["id_pago"],))

            if pago["tipo"] == "total":
                conn.execute(f"""
                    UPDATE pedidos_cabecera
                    SET estado_comanda = 'entregado', medio_pago = '', total_cobrado = 0, fecha_cobro = NULL
                    WHERE id_pedido = {ph}
                """, (id_pedido,))
                conn.execute(f"""
                    UPDATE mesas SET estado = 'ocupada' WHERE id_mesa = {ph}
                """, (pago["id_mesa"],))

            conn.execute("COMMIT")
            registrar_auditoria("caja", "pago_anulado", f"Pedido {id_pedido}, id_pago {pago['id_pago']}")
            return True, "Pago anulado correctamente."

        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            print(f"Error anulando pago de pedido {id_pedido}: {e}")
            return False, "Error interno al anular el pago."

    @staticmethod
    def service_percentage() -> float:
        """Porcentaje de servicio vigente (10% por defecto)."""
        ph = "%s" if get_db_type() == "postgres" else "?"
        row = execute_query(f"""
            SELECT valor FROM configuracion_sistema WHERE clave = 'porcentaje_servicio'
        """, fetch=True)
        if row:
            try:
                return float(row[0]["valor"])
            except (ValueError, TypeError):
                pass
        return 10.0
