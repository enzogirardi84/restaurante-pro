"""
views/mozo.py — Terminal táctil del camarero con imágenes y carta visual.
"""
from __future__ import annotations

import streamlit as st
from database import get_connection_direct
from components.imagenes import obtener_imagen


@st.cache_data(ttl=120)
def _cargar_menu() -> list:
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            "SELECT id_producto, nombre, precio_venta, categoria, url_imagen "
            "FROM productos_menu WHERE activo=1 ORDER BY categoria, nombre"
        )
        return cur.fetchall()
    finally:
        conn.close()


@st.cache_data(ttl=10)
def _cargar_mesas() -> list:
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            "SELECT id_mesa, numero_mesa, estado FROM mesas ORDER BY numero_mesa"
        )
        return cur.fetchall()
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _cargar_mozos() -> list:
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            "SELECT id_usuario, nombre, apellido FROM usuarios WHERE rol = 'mozo'"
        )
        return cur.fetchall()
    finally:
        conn.close()


def render() -> None:
    if "mozo_step" not in st.session_state:
        st.session_state.mozo_step = "mozo"
    if "mozo_id" not in st.session_state:
        st.session_state.mozo_id = None
    if "mozo_nombre" not in st.session_state:
        st.session_state.mozo_nombre = None
    if "mesa_id" not in st.session_state:
        st.session_state.mesa_id = None
    if "cart" not in st.session_state:
        st.session_state.cart = {}

    step = st.session_state.mozo_step
    if step == "mozo":
        _seleccionar_mozo()
    elif step == "mesa":
        _seleccionar_mesa()
    elif step == "pedido":
        _tomar_pedido()


# ── Paso 1 ────────────────────────────────────────────────────────────

def _seleccionar_mozo() -> None:
    st.markdown("<h1 style='text-align:center'>&#x1F468;&#x200D;&#x1F373; Mozo</h1>",
                unsafe_allow_html=True)
    mozos = _cargar_mozos()
    opts = {f"{m['nombre']} {m['apellido']}": m["id_usuario"] for m in mozos}
    seleccion = st.selectbox("Seleccioná tu nombre", [""] + list(opts.keys()))
    if st.button("Ingresar", disabled=not seleccion):
        st.session_state.mozo_id = opts[seleccion]
        st.session_state.mozo_nombre = seleccion
        st.session_state.mozo_step = "mesa"
        st.rerun()


# ── Paso 2 ────────────────────────────────────────────────────────────

def _seleccionar_mesa() -> None:
    st.markdown(f"&#x1F464; {st.session_state.mozo_nombre}", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center'>&#x1F4CD; Mesas</h2>",
                unsafe_allow_html=True)

    mesas = _cargar_mesas()

    COLS = 3
    for i in range(0, len(mesas), COLS):
        cols = st.columns(COLS)
        for j, mesa in enumerate(mesas[i:i + COLS]):
            with cols[j]:
                libre = mesa["estado"] == "libre"
                color = "#4caf50" if libre else "#ff9800"
                st.markdown(
                    f"<div style='background:{color};border-radius:12px;padding:1.5rem;"
                    f"text-align:center;color:white;font-size:1.8rem;font-weight:700'>"
                    f"&#x1FA91; {mesa['numero_mesa']}<br>"
                    f"<span style='font-size:0.8rem'>{mesa['estado'].upper()}</span></div>",
                    unsafe_allow_html=True,
                )
                if libre and st.button("Abrir", key=f"m_{mesa['id_mesa']}",
                                       use_container_width=True):
                    conn2 = get_connection_direct()
                    try:
                        conn2.execute(
                            "UPDATE mesas SET estado='ocupada' WHERE id_mesa=?",
                            (mesa["id_mesa"],)
                        )
                        conn2.commit()
                        _cargar_mesas.clear()
                    finally:
                        conn2.close()
                    st.session_state.mesa_id = mesa["id_mesa"]
                    st.session_state.cart = {}
                    st.session_state.mozo_step = "pedido"
                    st.rerun()

    if st.button("Cambiar mozo"):
        st.session_state.mozo_step = "mozo"
        st.rerun()


# ── Paso 3: Carta visual con imágenes ─────────────────────────────────

def _tomar_pedido() -> None:
    st.markdown(f"Mesa activa &middot; {st.session_state.mozo_nombre}",
                unsafe_allow_html=True)
    st.markdown("---")

    menu = _cargar_menu()

    cat_labels = {"cocina": "&#x1F373; Cocina", "bebidas": "&#x1F964; Bebidas", "postres": "&#x1F370; Postres"}
    CART = st.session_state.cart

    for cat_key, cat_label in cat_labels.items():
        items = [p for p in menu if p["categoria"] == cat_key]
        if not items:
            continue
        st.markdown(
            f"<h3 style='margin:1.2rem 0 0.6rem 0;color:#2C221E'>{cat_label}</h3>",
            unsafe_allow_html=True,
        )

        for prod in items:
            pid = prod["id_producto"]
            ci = CART.get(pid, {"cantidad": 0, "obs": ""})
            img_path = obtener_imagen(prod.get("url_imagen"), tipo="plato")

            col_img, col_info, col_ctrl = st.columns([1, 2, 2])

            with col_img:
                st.image(img_path, width=90, use_container_width=False)

            with col_info:
                st.markdown(
                    f"<div style='font-weight:700;font-size:1.05rem;color:#2C221E'>"
                    f"{prod['nombre']}</div>"
                    f"<div style='font-size:1rem;color:#8B2635;font-weight:700;margin-top:4px'>"
                    f"${prod['precio_venta']:,.0f}</div>",
                    unsafe_allow_html=True,
                )

            with col_ctrl:
                col_b1, col_b2, col_b3 = st.columns([1, 1, 1])
                with col_b1:
                    if st.button("&minus;", key=f"d_{pid}", use_container_width=True):
                        if ci["cantidad"] > 0:
                            ci["cantidad"] -= 1
                            if ci["cantidad"] == 0:
                                CART.pop(pid, None)
                            else:
                                CART[pid] = ci
                        st.rerun()
                with col_b2:
                    st.markdown(
                        f"<div style='text-align:center;font-size:1.4rem;font-weight:700'>"
                        f"{ci['cantidad']}</div>",
                        unsafe_allow_html=True,
                    )
                with col_b3:
                    if st.button("+", key=f"i_{pid}", use_container_width=True):
                        ci["cantidad"] += 1
                        CART[pid] = ci
                        st.rerun()

                ci["obs"] = st.text_input(
                    "Obs.", value=ci.get("obs", ""), key=f"o_{pid}",
                    label_visibility="collapsed", placeholder="nota",
                )

            st.markdown(
                "<div style='border-top:1px dashed #B58A63;margin:0.5rem 0'></div>",
                unsafe_allow_html=True,
            )

    st.divider()
    total = sum(
        ci["cantidad"] * next(
            (p["precio_venta"] for p in menu if p["id_producto"] == pid), 0
        )
        for pid, ci in CART.items() if ci
    )
    qty = sum(ci["cantidad"] for ci in CART.values() if ci)

    if qty == 0:
        st.warning("Carrito vacio.")
    else:
        st.markdown(f"### {qty} items &middot; **${total:,.0f}**", unsafe_allow_html=True)

    if st.button("ENVIAR PEDIDO", use_container_width=True, disabled=qty == 0, type="primary"):
        conn = get_connection_direct()
        try:
            conn.execute("BEGIN")
            cur = conn.execute(
                "INSERT INTO pedidos_cabecera (id_mesa, id_usuario) VALUES (?,?)",
                (st.session_state.mesa_id, st.session_state.mozo_id)
            )
            id_pedido = cur.lastrowid

            for pid, ci in CART.items():
                if ci and ci["cantidad"] > 0:
                    conn.execute(
                        "INSERT INTO pedido_detalle "
                        "(id_pedido, id_producto, cantidad, observaciones)"
                        " VALUES (?,?,?,?)",
                        (id_pedido, pid, ci["cantidad"], ci.get("obs", ""))
                    )
            conn.commit()
            st.success(f"Pedido #{id_pedido} enviado a cocina.")
            st.session_state.cart = {}
            st.session_state.mozo_step = "mesa"
            _cargar_mesas.clear()
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Error: {e}")
        finally:
            conn.close()

    if st.button("Cancelar"):
        st.session_state.mozo_step = "mesa"
        st.rerun()
