"""
views/caja.py — Terminal de Caja: cierre de mesas, medios de pago
múltiples, vuelto calculado, vista previa de ticket y descarga PDF/HTML.
"""
from __future__ import annotations

from html import escape

import streamlit as st
from database import get_connection_direct
from components.tickets import (
    imprimir_si_hay_impresora,
    mostrar_ticket_streamlit,
)
import config


@st.cache_data(ttl=10)
def _cargar_mesas_ocupadas() -> list:
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
                    return cur.fetchall()
finally:
        conn.close()


@st.cache_data(ttl=10)
def _cargar_items_mesa(id_mesa: int) -> list:
        conn = get_connection_direct()
        try:
                    cur = conn.execute("""
                                SELECT pm.nombre,
                                                   SUM(pd.cantidad)        AS cant,
                                                                      pm.precio_venta
                                                                                  FROM pedidos_cabecera pc
                                                                                              JOIN pedido_detalle pd  ON pd.id_pedido  = pc.id_pedido
                                                                                                          JOIN productos_menu pm  ON pm.id_producto = pd.id_producto
                                                                                                                      WHERE pc.id_mesa = ?
                                                                                                                                    AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
                                                                                                                                                GROUP BY pm.id_producto, pm.nombre, pm.precio_venta
                                                                                                                                                            ORDER BY pm.categoria, pm.nombre
                                                                                                                                                                    """, (id_mesa,))
                    return cur.fetchall()
finally:
        conn.close()


def _obtener_ultimo_pedido(id_mesa: int) -> int | None:
        """Obtiene el id_pedido más reciente de una mesa (cualquier estado)."""
        conn = get_connection_direct()
        try:
                    cur = conn.execute(
                                    "SELECT id_pedido FROM pedidos_cabecera"
                                    " WHERE id_mesa = ? ORDER BY id_pedido DESC LIMIT 1",
                                    (id_mesa,)
                    )
                    row = cur.fetchone()
                    return row["id_pedido"] if row else None
finally:
        conn.close()


def render() -> None:
        # Inicializar estados
        for key, default in [
                    ("caja_mesa", None),
                    ("caja_ticket_id", None),
                    ("caja_cobrado", False),
        ]:
                    if key not in st.session_state:
                                    st.session_state[key] = default

                # Si ya se cobró, mostrar pantalla de ticket
                if st.session_state.caja_cobrado and st.session_state.caja_ticket_id:
                            _mostrar_pantalla_ticket()
                            return

    if st.session_state.caja_mesa is None:
                _seleccionar()
else:
        _cuenta()


# ── Paso 1: Selección de mesa ─────────────────────────────────────────

def _seleccionar() -> None:
        st.markdown(
            "<h1 style='text-align:center'>&#x1F9FE; Terminal de Caja</h1>",
            unsafe_allow_html=True,
)

    mesas = _cargar_mesas_ocupadas()

    if not mesas:
                st.info("No hay mesas ocupadas en este momento.")
                return

    COLS = 3
    for i in range(0, len(mesas), COLS):
                cols = st.columns(COLS)
                for j, mesa in enumerate(mesas[i : i + COLS]):
                                with cols[j]:
                                                    st.markdown(
                                                                            f"<div style='background:#2e7d32;border-radius:16px;"
                                                                            f"padding:1.8rem;text-align:center;color:white;"
                                                                            f"font-size:2rem;font-weight:700'>"
                                                                            f"&#x1FA91; Mesa {mesa['numero_mesa']}</div>",
                                                                            unsafe_allow_html=True,
                                                    )
                                                    if st.button(
                                                                            "Ver cuenta",
                                                                            key=f"v_{mesa['id_mesa']}",
                                                                            use_container_width=True,
                                                    ):
                                                                            st.session_state.caja_mesa = mesa
                                                                            st.session_state.caja_cobrado = False
                                                                            st.session_state.caja_ticket_id = None
                                                                            st.rerun()


                    # ── Paso 2: Detalle + pago ────────────────────────────────────────────

        def _cuenta() -> None:
                mesa = st.session_state.caja_mesa
                st.markdown(
                    f"<h2>&#x1F9FE; Cuenta — Mesa #{mesa['numero_mesa']}</h2>",
                    unsafe_allow_html=True,
                )

    items = _cargar_items_mesa(mesa["id_mesa"])

    if not items:
                st.warning("Sin productos pendientes para esta mesa.")
                if st.button("&#x2190; Volver"):
                                st.session_state.caja_mesa = None
                                st.rerun()
                            return

    # ── Detalle de consumo ────────────────────────────────────────────
    with st.container():
                subtotal = 0
        for item in items:
                        importe = item["cant"] * item["precio_venta"]
                        subtotal += importe
                        nombre_safe = escape(str(item["nombre"]))
                        st.markdown(
                            f"<div style='display:flex;justify-content:space-between;"
                            f"padding:0.5rem 0.2rem;border-bottom:1px solid #eee'>"
                            f"<span><b>{item['cant']} ×</b> {nombre_safe}</span>"
                            f"<span><b>${importe:,.0f}</b></span></div>",
                            unsafe_allow_html=True,
                        )

    servicio = round(subtotal * config.SERVICIO_PORCENTAJE / 100)
    total = subtotal + servicio

    st.markdown("---")
    col_sub, col_srv, col_tot = st.columns(3)
    col_sub.metric("Subtotal", f"${subtotal:,.0f}")
    col_srv.metric(f"Servicio ({config.SERVICIO_PORCENTAJE}%)", f"${servicio:,.0f}")
    col_tot.metric("**TOTAL**", f"${total:,.0f}")

    # ── Medio de pago ─────────────────────────────────────────────────
    st.markdown("### &#x1F4B3; Medio de pago")
    metodo = st.radio(
                "Seleccionar",
                ["Efectivo", "Tarjeta", "Digital"],
                horizontal=True,
                label_visibility="collapsed",
    )

    monto_recibido = float(total)

    if metodo == "Efectivo":
                col_ef1, col_ef2 = st.columns([2, 1])
        with col_ef1:
                        monto_recibido = st.number_input(
                                            "Monto recibido ($)",
                                            min_value=0.0,
                                            value=float(total),
                                            step=100.0,
                                            format="%.0f",
                        )
                    with col_ef2:
                                    vuelto = monto_recibido - total
                                    if vuelto >= 0:
                                                        st.markdown(
                                                                                f"<div style='background:#388e3c;color:white;padding:1rem;"
                                                                                f"border-radius:10px;text-align:center;margin-top:1.6rem;"
                                                                                f"font-size:1.4rem;font-weight:700'>Vuelto<br>${vuelto:,.0f}</div>",
                                                                                unsafe_allow_html=True,
                                                        )
else:
                st.markdown(
                                        f"<div style='background:#c62828;color:white;padding:1rem;"
                                        f"border-radius:10px;text-align:center;margin-top:1.6rem;"
                                        f"font-size:1.2rem;font-weight:600'>Faltan<br>${abs(vuelto):,.0f}</div>",
                                        unsafe_allow_html=True,
                )
elif metodo == "Tarjeta":
        st.info("&#x1F4B3; Pago con tarjeta — procese el terminal y confirme.")
else:
        st.info("&#x1F4F1; Pago digital — verifique la transferencia y confirme.")

    puede_cobrar = (metodo == "Efectivo" and monto_recibido >= total) or \
                   metodo in ("Tarjeta", "Digital")

    st.markdown("---")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
                if st.button(
                    "&#x2705; COBRAR Y EMITIR TICKET",
                    type="primary",
                    use_container_width=True,
                    disabled=not puede_cobrar,
    ):
                    _ejecutar_cierre(mesa, total, metodo)
            with col_b2:
                        if st.button("&#x2190; Volver", use_container_width=True):
                                        st.session_state.caja_mesa = None
                                        st.rerun()


# ── Paso 3: Pantalla de ticket ────────────────────────────────────────

def _mostrar_pantalla_ticket() -> None:
        ticket_id = st.session_state.caja_ticket_id

    st.markdown(
                "<h2 style='text-align:center;color:#2e7d32'>&#x2705; Cobro exitoso</h2>",
                unsafe_allow_html=True,
    )
    st.markdown(
                "<p style='text-align:center;color:#555'>A continuación podés"
                " visualizar, imprimir o descargar el ticket.</p>",
                unsafe_allow_html=True,
    )

    # Impresión física (fallback a archivo)
    res = imprimir_si_hay_impresora(ticket_id)
    if res["ruta"] and "IMPRESORA" in str(res["ruta"]):
                st.success(f"&#x1F5A8; Ticket enviado a impresora: {res['ruta']}")
elif res["ruta"]:
        st.info(f"&#x1F4BE; Ticket guardado en: {res['ruta']}")

    if res.get("error") and "No se detect" not in str(res["error"]):
                st.warning(f"Aviso de impresora: {res['error']}")

    # Vista previa + botones de descarga (PDF / HTML)
    mostrar_ticket_streamlit(ticket_id)

    st.markdown("---")
    if st.button(
                "&#x1F3E0; Nueva operación",
                type="primary",
                use_container_width=True,
    ):
                st.session_state.caja_mesa = None
        st.session_state.caja_cobrado = False
        st.session_state.caja_ticket_id = None
        st.rerun()


# ── Cierre transaccional ──────────────────────────────────────────────

def _ejecutar_cierre(mesa: dict, total: float, metodo: str) -> None:
        """Marca todos los pedidos activos de la mesa como cobrados y libera la mesa."""

    # Capturar el id_pedido ANTES de cambiar estados (por si el filtro lo excluye)
    ultimo_id = _obtener_ultimo_pedido(mesa["id_mesa"])

    conn = get_connection_direct()
    try:
                conn.execute("BEGIN")
        conn.execute(
                        "UPDATE pedidos_cabecera SET estado_comanda = 'cobrado'"
                        " WHERE id_mesa = ? AND estado_comanda IN"
                        " ('pendiente','en_cocina','listo','entregado')",
                        (mesa["id_mesa"],),
        )
        conn.execute(
                        "UPDATE mesas SET estado = 'libre' WHERE id_mesa = ?",
                        (mesa["id_mesa"],),
        )
        conn.commit()
        _cargar_mesas_ocupadas.clear()
        _cargar_items_mesa.clear()
except Exception as e:
        conn.rollback()
        st.error(f"&#x274C; Error al cerrar la cuenta: {e}")
        return
finally:
        conn.close()

    if not ultimo_id:
                st.error("No se encontró el pedido para generar el ticket.")
        return

    # Guardar estado para pantalla de ticket
    st.session_state.caja_ticket_id = ultimo_id
    st.session_state.caja_cobrado = True
    st.session_state.caja_mesa = None

    st.balloons()
    st.rerun()
