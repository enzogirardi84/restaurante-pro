"""
facturacion.py — Terminal de Caja (TPV).
Calcula cuentas por mesa, aplica servicio y libera el salón.
"""
from __future__ import annotations

import streamlit as st
from database import get_connection, init_db
from cloud_config import default_service_percentage

# ── CONSTANTES ────────────────────────────────────────────────────────
SERVICIO_PORCENTAJE = default_service_percentage(10)
COLOR_PRIMARY       = "#2e7d32"
COLOR_CTA           = "#1565c0"


# ── ACCESO A DATOS ────────────────────────────────────────────────────

def obtener_mesas_ocupadas() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT DISTINCT m.id_mesa, m.numero_mesa
            FROM mesas m
            JOIN pedidos_cabecera pc ON pc.id_mesa = m.id_mesa
            WHERE m.estado = 'ocupada'
              AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
            ORDER BY m.numero_mesa
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def obtener_detalle_cuenta(id_mesa: int) -> list[dict]:
    """Retorna el detalle consolidado de todos los pedidos activos de una mesa."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT pm.nombre,
                   COALESCE(pd.precio_unitario_facturado, pm.precio_venta) AS precio_venta,
                   SUM(pd.cantidad) AS cantidad_total
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd   ON pd.id_pedido   = pc.id_pedido
            JOIN productos_menu pm   ON pm.id_producto = pd.id_producto
            WHERE pc.id_mesa = ?
              AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
            GROUP BY pm.id_producto, pm.nombre, COALESCE(pd.precio_unitario_facturado, pm.precio_venta)
            ORDER BY pm.categoria, pm.nombre
        """, (id_mesa,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def cerrar_mesa(id_mesa: int, total: float, medio_pago: str) -> dict:
    """
    Transacción que:
      1. Pasa todos los pedidos activos de la mesa a 'cobrado'.
      2. Libera la mesa (estado → 'libre').
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")

        cur = conn.execute("""
            UPDATE pedidos_cabecera
            SET estado_comanda = 'cobrado'
            WHERE id_mesa = ?
              AND estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
        """, (id_mesa,))
        pedidos_cerrados = cur.rowcount

        conn.execute("""
            UPDATE mesas SET estado = 'libre' WHERE id_mesa = ?
        """, (id_mesa,))

        caja = conn.execute("""
            SELECT id_caja
              FROM cajas_diarias
             WHERE estado_caja = 'abierta'
             ORDER BY id_caja DESC
             LIMIT 1
        """).fetchone()
        if caja and total > 0:
            conn.execute("""
                UPDATE cajas_diarias
                   SET monto_ventas = monto_ventas + ?
                 WHERE id_caja = ?
            """, (total, caja["id_caja"]))
            conn.execute("""
                INSERT INTO movimientos_caja
                    (id_caja, tipo_movimiento, monto, descripcion)
                VALUES (?, 'ingreso_venta', ?, ?)
            """, (
                caja["id_caja"],
                total,
                f"Cobro mesa {id_mesa} - {medio_pago}",
            ))

        conn.execute("COMMIT")
        return {"ok": True, "pedidos_cerrados": pedidos_cerrados}
    except Exception as e:
        conn.execute("ROLLBACK")
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


# ── SESIÓN ────────────────────────────────────────────────────────────

def init_session() -> None:
    for k, v in {
        "mesa_seleccionada": None,
        "success_msg": None,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── PANTALLA: SELECCIÓN DE MESA ───────────────────────────────────────

def pantalla_seleccion():
    st.markdown("<h1 style='text-align:center'>🧾  Terminal de Caja</h1>",
                unsafe_allow_html=True)

    if st.session_state.success_msg:
        st.success(st.session_state.success_msg)
        st.session_state.success_msg = None

    mesas = obtener_mesas_ocupadas()
    if not mesas:
        st.info("✅  No hay mesas ocupadas en este momento.")
        st.markdown("---")
        _footer()
        return

    st.markdown("<h3 style='text-align:center'>📍  Seleccioná una mesa para cobrar</h3>",
                unsafe_allow_html=True)

    # Grid 3 columnas — táctil amigable
    COLS = 3
    for i in range(0, len(mesas), COLS):
        cols = st.columns(COLS)
        for j, mesa in enumerate(mesas[i:i + COLS]):
            with cols[j]:
                st.markdown(f"""
                    <div style='
                        background:#2e7d32; border-radius:16px; text-align:center;
                        padding:1.8rem 0.5rem; margin:0.25rem 0;
                        box-shadow:0 4px 12px rgba(0,0,0,0.18);
                    '>
                        <div style='font-size:2.4rem;font-weight:700;color:white'>
                            🪑 {mesa['numero_mesa']}
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                if st.button("📋  Ver cuenta",
                             key=f"ver_{mesa['id_mesa']}",
                             use_container_width=True):
                    st.session_state.mesa_seleccionada = mesa
                    st.rerun()

    st.markdown("---")
    _footer()


# ── PANTALLA: DETALLE DE CUENTA ───────────────────────────────────────

def pantalla_cuenta():
    mesa = st.session_state.mesa_seleccionada
    st.markdown(f"""
        <div style='display:flex;justify-content:space-between;align-items:center'>
            <h2>🧾  Mesa #{mesa['numero_mesa']}</h2>
            <span style='background:#2e7d32;color:white;padding:0.3rem 1.2rem;
                  border-radius:20px;font-weight:600'>ACTIVA</span>
        </div>
    """, unsafe_allow_html=True)

    detalle = obtener_detalle_cuenta(mesa["id_mesa"])
    if not detalle:
        st.warning("Esta mesa no tiene productos pendientes de cobro.")
        if st.button("🔙  Volver", use_container_width=True):
            st.session_state.mesa_seleccionada = None
            st.rerun()
        return

    # ── Tabla de productos ──
    st.markdown("### 📋  Productos consumidos")
    subtotal = 0
    for item in detalle:
        importe = item["cantidad_total"] * item["precio_venta"]
        subtotal += importe
        st.markdown(f"""
            <div style='
                display:flex;justify-content:space-between;
                padding:0.6rem 0.8rem; border-bottom:1px solid #eee;
                font-size:1.05rem;
            '>
                <span><b>{item['cantidad_total']}x</b>  {item['nombre']}</span>
                <span style='font-weight:600;color:#333'>
                    ${importe:,.0f}
                </span>
            </div>
        """, unsafe_allow_html=True)

    # ── Totales ──
    servicio = round(subtotal * SERVICIO_PORCENTAJE / 100)
    total    = subtotal + servicio
    medio_pago = st.selectbox(
        "Medio de pago",
        ["Efectivo", "Tarjeta", "Transferencia", "Mercado Pago"],
        index=0,
    )

    st.markdown("<div style='margin-top:1rem'>", unsafe_allow_html=True)

    fila_total = lambda label, valor, bold=False: \
        f"""
        <div style='display:flex;justify-content:space-between;
                    padding:0.5rem 0.8rem; font-size:{"1.2rem" if bold else "1rem"};
                    font-weight:{"700" if bold else "400"};
                    border-top:{"2px solid #333" if bold else "none"}'>
            <span>{label}</span>
            <span>${valor:,.0f}</span>
        </div>
        """
    st.markdown(fila_total("Subtotal", subtotal), unsafe_allow_html=True)
    st.markdown(fila_total(f"Servicio ({SERVICIO_PORCENTAJE}%)", servicio),
                unsafe_allow_html=True)
    st.markdown(fila_total("TOTAL", total, bold=True), unsafe_allow_html=True)

    # ── Botones de acción ──
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("💳  COBRAR Y EMITIR TICKET",
                     use_container_width=True, type="primary"):
            resultado = cerrar_mesa(mesa["id_mesa"], total, medio_pago)
            if resultado["ok"]:
                st.session_state.success_msg = (
                    f"✅  Mesa #{mesa['numero_mesa']} cobrada — "
                    f"${total:,.0f} "
                    f"({resultado['pedidos_cerrados']} pedido(s) cerrado(s)). "
                    f"¡Mesa liberada!"
                )
                st.session_state.mesa_seleccionada = None
                st.balloons()
                st.rerun()
            else:
                st.error(f"Error al cerrar la mesa: {resultado['error']}")

    if st.button("🔙  Cancelar y volver", use_container_width=True):
        st.session_state.mesa_seleccionada = None
        st.rerun()


# ── FOOTER ────────────────────────────────────────────────────────────

def _footer() -> None:
    st.caption(
        "Sistema de Gestión Gastronómica · "
        f"Servicio: {SERVICIO_PORCENTAJE}% · "
        "Módulo de Caja"
    )


# ── ENTRADA PRINCIPAL ─────────────────────────────────────────────────

st.set_page_config(page_title="Terminal de Caja", layout="centered",
                   initial_sidebar_state="collapsed")
init_db()
init_session()

if st.session_state.mesa_seleccionada is None:
    pantalla_seleccion()
else:
    pantalla_cuenta()
