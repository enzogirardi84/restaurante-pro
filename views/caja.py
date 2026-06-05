"""
views/caja.py — Terminal de Caja: cierre de mesas, medios de pago
múltiples, vuelto calculado e impresión real con auto-detección.
"""
from __future__ import annotations

import streamlit as st
from database import get_connection_direct
from components.tickets import (
    formatear_comprobante,
    imprimir_si_hay_impresora,
    ticket_a_html,
)
import config


def render() -> None:
    if "caja_mesa" not in st.session_state:
        st.session_state.caja_mesa = None

    if st.session_state.caja_mesa is None:
        _seleccionar()
    else:
        _cuenta()


# ── Paso 1: Selección de mesa ─────────────────────────────────────────

def _seleccionar() -> None:
    st.markdown("<h1 style='text-align:center'>🧾  Terminal de Caja</h1>",
                unsafe_allow_html=True)

    conn = get_connection_direct()
    try:
        cur = conn.execute("""
            SELECT DISTINCT m.id_mesa, m.numero_mesa
            FROM mesas m
            JOIN pedidos_cabecera pc ON pc.id_mesa = m.id_mesa
            WHERE m.estado = 'ocupada'
              AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
            ORDER BY m.numero_mesa
        """)
        mesas = cur.fetchall()
    finally:
        conn.close()

    if not mesas:
        st.info("✅  No hay mesas ocupadas.")
        return

    COLS = 3
    for i in range(0, len(mesas), COLS):
        cols = st.columns(COLS)
        for j, mesa in enumerate(mesas[i:i + COLS]):
            with cols[j]:
                st.markdown(
                    f"<div style='background:#2e7d32;border-radius:16px;padding:1.8rem;"
                    f"text-align:center;color:white;font-size:2rem;font-weight:700'>"
                    f"🪑 {mesa['numero_mesa']}</div>",
                    unsafe_allow_html=True,
                )
                if st.button("📋  Ver cuenta", key=f"v_{mesa['id_mesa']}",
                             use_container_width=True):
                    st.session_state.caja_mesa = mesa
                    st.rerun()


# ── Paso 2: Detalle + pago ────────────────────────────────────────────

def _cuenta() -> None:
    mesa = st.session_state.caja_mesa
    st.markdown(f"<h2>🧾  Mesa #{mesa['numero_mesa']}</h2>",
                unsafe_allow_html=True)

    conn = get_connection_direct()
    try:
        cur = conn.execute("""
            SELECT pm.nombre, SUM(pd.cantidad) AS cant, pm.precio_venta
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.id_mesa = ?
              AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
            GROUP BY pm.id_producto, pm.nombre, pm.precio_venta
            ORDER BY pm.categoria, pm.nombre
        """, (mesa["id_mesa"],))
        items = cur.fetchall()
    finally:
        conn.close()

    if not items:
        st.warning("Sin productos pendientes.")
        if st.button("🔙  Volver"):
            st.session_state.caja_mesa = None
            st.rerun()
        return

    subtotal = 0
    for item in items:
        importe = item["cant"] * item["precio_venta"]
        subtotal += importe
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;"
            f"padding:0.5rem;border-bottom:1px solid #eee'>"
            f"<span><b>{item['cant']}x</b> {item['nombre']}</span>"
            f"<span>${importe:,.0f}</span></div>",
            unsafe_allow_html=True,
        )

    servicio = round(subtotal * config.SERVICIO_PORCENTAJE / 100)
    total = subtotal + servicio

    # ── Totales ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"**Subtotal:** ${subtotal:,.0f}")
    st.markdown(f"**Servicio ({config.SERVICIO_PORCENTAJE}%):** ${servicio:,.0f}")
    st.markdown(f"<h3 style='color:#8B2635'>TOTAL: ${total:,.0f}</h3>",
                unsafe_allow_html=True)

    # ── Medio de pago ──────────────────────────────────────────────────
    st.markdown("### 💳  Medio de pago")
    metodo = st.radio(
        "Seleccionar", ["Efectivo", "Tarjeta", "Digital"],
        horizontal=True, label_visibility="collapsed",
    )

    monto_recibido = 0.0
    if metodo == "Efectivo":
        col_ef1, col_ef2 = st.columns([2, 1])
        with col_ef1:
            monto_recibido = st.number_input(
                "💰 Monto recibido",
                min_value=0.0, value=float(total), step=100.0,
                format="%.0f",
            )
        with col_ef2:
            vuelto = monto_recibido - total
            if vuelto >= 0:
                st.markdown(
                    f"<div style='background:#7A8450;color:white;padding:1rem;"
                    f"border-radius:10px;text-align:center;font-size:1.5rem;"
                    f"font-weight:700'>🔄 Vuelto: ${vuelto:,.0f}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='background:#A64B2A;color:white;padding:1rem;"
                    f"border-radius:10px;text-align:center;font-size:1.2rem;"
                    f"font-weight:600'>Faltan ${abs(vuelto):,.0f}</div>",
                    unsafe_allow_html=True,
                )
    elif metodo == "Tarjeta":
        st.info("💳  Pago con tarjeta procesado (simulación).")
        monto_recibido = total
    else:
        st.info("📱  Pago digital procesado (simulación).")
        monto_recibido = total

    # ── Botones de cierre ──────────────────────────────────────────────
    puede_cobrar = (metodo == "Efectivo" and monto_recibido >= total) or \
                   metodo in ("Tarjeta", "Digital")

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button("💳  COBRAR Y EMITIR TICKET", type="primary",
                     use_container_width=True, disabled=not puede_cobrar):
            _ejecutar_cierre(mesa, total, metodo)
    with col_b2:
        if st.button("🔙  Volver", use_container_width=True):
            st.session_state.caja_mesa = None
            st.rerun()


# ── Cierre transaccional + impresión ──────────────────────────────────

def _ejecutar_cierre(mesa: dict, total: float, metodo: str) -> None:
    """Cierra la mesa, imprime ticket y muestra resultado."""
    conn = get_connection_direct()
    ultimo_id = None
    try:
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE pedidos_cabecera SET estado_comanda='cobrado'"
            " WHERE id_mesa=? AND estado_comanda IN "
            "('pendiente','en_cocina','listo','entregado')",
            (mesa["id_mesa"],)
        )
        conn.execute("UPDATE mesas SET estado='libre' WHERE id_mesa=?",
                     (mesa["id_mesa"],))
        conn.commit()
    except Exception as e:
        conn.rollback()
        st.error(f"Error al cerrar: {e}")
        return
    finally:
        conn.close()

    # Recuperar último pedido
    conn2 = get_connection_direct()
    try:
        cur = conn2.execute(
            "SELECT id_pedido FROM pedidos_cabecera"
            " WHERE id_mesa=? ORDER BY id_pedido DESC LIMIT 1",
            (mesa["id_mesa"],)
        )
        row = cur.fetchone()
        ultimo_id = row["id_pedido"] if row else None
    finally:
        conn2.close()

    # Impresión con auto-detección
    if ultimo_id:
        res = imprimir_si_hay_impresora(ultimo_id)
        if res["ruta"] and "IMPRESORA" in str(res["ruta"]):
            st.success(f"🖨️  Ticket impreso en {res['ruta']}")
        elif res["ruta"]:
            with open(res["ruta"], "r", encoding="utf-8") as f:
                st.text_area("🧾  Ticket", f.read(), height=250)
            st.info(f"📁  Guardado en: {res['ruta']}")
        if res["error"] and "No se detectó" in str(res["error"]):
            st.info(res["error"])

        # Vista previa HTML
        html = ticket_a_html(ultimo_id)
        with tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(html)
            st.markdown(f"[📄 Abrir ticket en HTML](file:///{f.name})",
                        unsafe_allow_html=True)

    st.balloons()
    st.success(f"✅ Mesa #{mesa['numero_mesa']} cobrada — "
               f"${total:,.0f} — {metodo}")
    st.session_state.caja_mesa = None
    st.rerun()
