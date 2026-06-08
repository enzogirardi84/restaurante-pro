"""
services/inventario.py — Servicio de inventario para COMANDAPRO ERP v2.0.
Gestiona descuento automatico de insumos, alertas de stock minimo,
movimientos de entrada/salida con trazabilidad, y ajustes manuales.

Arquitectura:
- Sin dependencia de Streamlit. UI-agnostico.
- Descuento batch optimizado (evita N+1 cuando es posible).
- Validacion de stock suficiente ANTES de descontar.
- Cada movimiento queda registrado en movimientos_stock con trazabilidad.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from database import execute_query, get_connection, get_db_type, registrar_auditoria


TIPOS_MOVIMIENTO_VALIDOS = {"compra", "ajuste_entrada", "ajuste_salida", "descuento_receta", "merma"}


class InventarioService:

    # ── Lectura ──────────────────────────────────────────────────────

    @staticmethod
    def listar_insumos(con_stock_bajo: bool = False) -> List[Dict]:
        """
        Lista todos los insumos. Si con_stock_bajo=True, solo los que
        tienen stock_actual <= stock_minimo.
        """
        ph = "%s" if get_db_type() == "postgres" else "?"
        if con_stock_bajo:
            return execute_query(f"""
                SELECT i.*,
                       (CASE WHEN i.stock_actual <= i.stock_minimo THEN 1 ELSE 0 END) AS alerta
                FROM insumos i
                WHERE i.stock_actual <= i.stock_minimo
                ORDER BY (i.stock_actual * 1.0 / NULLIF(i.stock_minimo, 0)) ASC, i.nombre
            """, fetch=True) or []
        return execute_query("""
            SELECT i.*,
                   (CASE WHEN i.stock_actual <= i.stock_minimo THEN 1 ELSE 0 END) AS alerta
            FROM insumos i
            ORDER BY i.nombre
        """, fetch=True) or []

    @staticmethod
    def obtener_insumo(id_insumo: int) -> Dict:
        """Retorna un insumo con su historial de movimientos."""
        ph = "%s" if get_db_type() == "postgres" else "?"
        insumo = execute_query(f"""
            SELECT * FROM insumos WHERE id_insumo = {ph}
        """, (id_insumo,), fetch=True)
        if not insumo:
            return {}
        movimientos = execute_query(f"""
            SELECT ms.*, u.nombre || ' ' || u.apellido AS usuario
            FROM movimientos_stock ms
            LEFT JOIN usuarios u ON u.id_usuario = ms.id_usuario
            WHERE ms.id_insumo = {ph}
            ORDER BY ms.fecha_hora DESC
            LIMIT 100
        """, (id_insumo,), fetch=True) or []
        insumo[0]["movimientos"] = movimientos
        return insumo[0]

    @staticmethod
    def alertas_stock() -> List[Dict]:
        """
        Retorna todos los insumos con stock por debajo del minimo,
        ordenados por criticidad (menor stock relativo primero).
        """
        return execute_query("""
            SELECT i.id_insumo, i.nombre, i.stock_actual, i.stock_minimo, i.unidad_medida,
                   ROUND(i.stock_actual * 1.0 / NULLIF(i.stock_minimo, 0) * 100, 0) AS porcentaje,
                   (CASE
                       WHEN i.stock_actual <= 0 THEN 'critico'
                       WHEN i.stock_actual <= i.stock_minimo * 0.5 THEN 'urgente'
                       ELSE 'bajo'
                   END) AS nivel
            FROM insumos i
            WHERE i.stock_actual <= i.stock_minimo
            ORDER BY porcentaje ASC, i.nombre
        """, fetch=True) or []

    @staticmethod
    def movimientos_por_periodo(desde: str, hasta: str,
                                id_insumo: int | None = None) -> List[Dict]:
        """Movimientos de stock filtrados por fecha (e insumo opcional)."""
        ph = "%s" if get_db_type() == "postgres" else "?"
        params: list = [desde, hasta]
        clause = ""
        if id_insumo:
            clause = f" AND ms.id_insumo = {ph}"
            params.append(id_insumo)
        return execute_query(f"""
            SELECT ms.*, i.nombre AS insumo, i.unidad_medida,
                   u.nombre || ' ' || u.apellido AS usuario
            FROM movimientos_stock ms
            JOIN insumos i ON i.id_insumo = ms.id_insumo
            LEFT JOIN usuarios u ON u.id_usuario = ms.id_usuario
            WHERE DATE(ms.fecha_hora) BETWEEN {ph} AND {ph}{clause}
            ORDER BY ms.fecha_hora DESC
        """, tuple(params), fetch=True) or []

    # ── Escritura: descuento automatico ──────────────────────────────

    @staticmethod
    def descontar_insumos(id_pedido: int, id_usuario: int) -> Tuple[bool, str]:
        """
        Descuenta insumos segun escandallo de cada producto en el pedido.
        Transaccion atomica: si falla un insumo, no descuenta ninguno.

        Retorna (ok, mensaje). En ok=True, el mensaje incluye
        los items descontados.
        """
        ph = "%s" if get_db_type() == "postgres" else "?"
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")

            detalle = conn.execute(f"""
                SELECT pd.id_producto, pd.cantidad, pm.nombre
                FROM pedido_detalle pd
                JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                WHERE pd.id_pedido = {ph}
                  AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
            """, (id_pedido,)).fetchall()

            if not detalle:
                conn.execute("ROLLBACK")
                return False, "El pedido no tiene productos activos para descontar."

            descontados: list[str] = []
            for item in detalle:
                producto_id = item["id_producto"]
                cantidad_pedido = float(item["cantidad"])

                recetas = conn.execute(f"""
                    SELECT r.id_insumo, r.cantidad_a_descontar, i.nombre,
                           i.stock_actual, i.unidad_medida
                    FROM recetas_escandallo r
                    JOIN insumos i ON i.id_insumo = r.id_insumo
                    WHERE r.id_producto = {ph}
                """, (producto_id,)).fetchall()

                if not recetas:
                    conn.execute("ROLLBACK")
                    return False, f"'{item['nombre']}' no tiene receta de escandallo."

                for receta in recetas:
                    cantidad_total = float(receta["cantidad_a_descontar"]) * cantidad_pedido
                    if float(receta["stock_actual"]) < cantidad_total:
                        conn.execute("ROLLBACK")
                        return False, (
                            f"Stock insuficiente para '{receta['nombre']}'. "
                            f"Necesita {cantidad_total:.0f} {receta['unidad_medida']}, "
                            f"hay {receta['stock_actual']:.0f}."
                        )

                    stock_anterior = float(receta["stock_actual"])
                    stock_nuevo = stock_anterior - cantidad_total

                    conn.execute(f"""
                        UPDATE insumos
                        SET stock_actual = stock_actual - {ph}
                        WHERE id_insumo = {ph}
                    """, (cantidad_total, receta["id_insumo"]))

                    conn.execute(f"""
                        INSERT INTO movimientos_stock
                            (id_insumo, id_usuario, tipo_movimiento, cantidad,
                             stock_anterior, stock_nuevo, descripcion)
                        VALUES ({ph}, {ph}, 'descuento_receta', {ph}, {ph}, {ph}, {ph})
                    """, (
                        receta["id_insumo"], id_usuario,
                        cantidad_total, stock_anterior, stock_nuevo,
                        f"Pedido {id_pedido} - {item['nombre']}",
                    ))

                    descontados.append(
                        f"{receta['nombre']}: -{cantidad_total:.0f} {receta['unidad_medida']}"
                    )

            conn.execute(f"""
                UPDATE pedidos_cabecera
                SET estado_comanda = 'listo'
                WHERE id_pedido = {ph}
            """, (id_pedido,))

            conn.execute("COMMIT")
            registrar_auditoria("inventario", "descuento_receta",
                                f"Pedido {id_pedido}: {len(descontados)} insumos descontados")
            return True, f"Stock descontado. Items: {'; '.join(descontados)}"

        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            print(f"Error descontando stock del pedido {id_pedido}: {e}")
            return False, "Error interno al descontar insumos."

    # ── Escritura: movimiento manual ─────────────────────────────────

    @staticmethod
    def registrar_movimiento(
        id_insumo: int,
        tipo: str,
        cantidad: float,
        id_usuario: int,
        descripcion: str = "",
        id_proveedor: int | None = None,
    ) -> Tuple[bool, str]:
        """
        Registra un movimiento de entrada o salida manual con auditoria.
        - 'compra' y 'ajuste_entrada': incrementan stock.
        - 'ajuste_salida', 'merma': decrementan (validan stock suficiente).
        """
        if tipo not in TIPOS_MOVIMIENTO_VALIDOS:
            return False, f"Tipo de movimiento invalido: {tipo}"

        if cantidad <= 0:
            return False, "La cantidad debe ser mayor a cero."

        ph = "%s" if get_db_type() == "postgres" else "?"
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")

            insumo = conn.execute(f"""
                SELECT id_insumo, nombre, stock_actual, unidad_medida
                FROM insumos WHERE id_insumo = {ph}
            """, (id_insumo,)).fetchone()

            if not insumo:
                conn.execute("ROLLBACK")
                return False, "El insumo no existe."

            es_salida = tipo in ("ajuste_salida", "merma", "descuento_receta")
            stock_anterior = float(insumo["stock_actual"])

            if es_salida and stock_anterior < cantidad:
                conn.execute("ROLLBACK")
                return False, (
                    f"Stock insuficiente en '{insumo['nombre']}'. "
                    f"Tiene {stock_anterior:.0f} {insumo['unidad_medida']}, "
                    f"necesita {cantidad:.0f}."
                )

            stock_nuevo = stock_anterior - cantidad if es_salida else stock_anterior + cantidad

            conn.execute(f"""
                UPDATE insumos
                SET stock_actual = stock_actual {'-' if es_salida else '+'} {ph}
                WHERE id_insumo = {ph}
            """, (cantidad, id_insumo))

            conn.execute(f"""
                INSERT INTO movimientos_stock
                    (id_insumo, id_usuario, id_proveedor, tipo_movimiento, cantidad,
                     stock_anterior, stock_nuevo, descripcion)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """, (id_insumo, id_usuario, id_proveedor, tipo, cantidad,
                  stock_anterior, stock_nuevo, descripcion or f"Ajuste manual ({tipo})"))

            conn.execute("COMMIT")
            registrar_auditoria("inventario", f"movimiento_{tipo}",
                                f"{insumo['nombre']}: {stock_anterior:.0f} -> {stock_nuevo:.0f}")
            return True, (
                f"{insumo['nombre']}: {stock_anterior:.0f} -> {stock_nuevo:.0f} "
                f"{insumo['unidad_medida']} ({tipo})"
            )

        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            print(f"Error registrando movimiento de insumo {id_insumo}: {e}")
            return False, "Error interno al registrar movimiento."

    @staticmethod
    def verificar_stock_suficiente(id_producto: int, cantidad: int = 1) -> Tuple[bool, str]:
        """
        Verifica si hay stock suficiente para producir 'cantidad' unidades
        de un producto segun su escandallo. Retorna (ok, mensaje).
        Si ok=False, el mensaje detalla el primer insumo faltante.
        """
        ph = "%s" if get_db_type() == "postgres" else "?"
        recetas = execute_query(f"""
            SELECT r.cantidad_a_descontar, i.nombre, i.stock_actual, i.unidad_medida
            FROM recetas_escandallo r
            JOIN insumos i ON i.id_insumo = r.id_insumo
            WHERE r.id_producto = {ph}
        """, (id_producto,), fetch=True) or []

        if not recetas:
            return False, "El producto no tiene receta de escandallo."

        for r in recetas:
            necesario = float(r["cantidad_a_descontar"]) * cantidad
            disponible = float(r["stock_actual"])
            if disponible < necesario:
                return False, (
                    f"Stock insuficiente para '{r['nombre']}': "
                    f"necesita {necesario:.0f} {r['unidad_medida']}, "
                    f"hay {disponible:.0f}."
                )
        return True, "Stock suficiente."

    @staticmethod
    def ajustar_stock_minimo(id_insumo: int, nuevo_minimo: float) -> Tuple[bool, str]:
        """Ajusta el stock minimo de un insumo (no genera movimiento)."""
        if nuevo_minimo < 0:
            return False, "El stock minimo no puede ser negativo."
        ph = "%s" if get_db_type() == "postgres" else "?"
        execute_query(f"""
            UPDATE insumos SET stock_minimo = {ph} WHERE id_insumo = {ph}
        """, (nuevo_minimo, id_insumo))
        return True, f"Stock minimo actualizado a {nuevo_minimo:.0f}."
