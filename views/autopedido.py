"""
views/autopedido.py — Auto-pedido por QR (Mobile-First).
Menú con imágenes, carrito táctil y envío transaccional.
"""
from __future__ import annotations

import streamlit as st
from database import get_connection_direct
from components.imagenes import obtener_imagen

PEDIDO_TAG = "[Pedido Autónomo Web - Mesa {}]"


def render() -> None:
    mesa_id = st.session_state.get("mesa_auto")
    if mesa_id is None:
        st.error("Mesa no especificada. Escaneá el código QR de la mesa.")
        st.stop()

    st.markdown(
        "<style>"
        ".stButton button { font-size: 1.4rem !important; padding: 0.8rem !important; }"
        ".stTextInput input { font-size: 1.1rem !important; }"
        "img { border-radius: 8px; object-fit: cover; }"
        "</style>",
        unsafe_allow_html=True,
    )
    _menu_cliente(mesa_id)


def _menu_cliente(mesa_id: int) -> None:
    st.markdown(f"""
        <div style='text-align:center;padding:0.5rem 0'>
            <h1 style='font-size:2rem'>🍽  COMANDAPRO</h1>
            <p style='font-size:1.2rem;color:#666'>Mesa <b>#{mesa_id}</b></p>
        </div>
    """, unsafe_allow_html=True)

    if "auto_cart" not in st.session_state:
        st.session_state.auto_cart = {}

    conn = get_connection_direct()
    try:
        cur = conn.execute(
            "SELECT id_producto, nombre, precio_venta, categoria, url_imagen "
            "FROM productos_menu WHERE activo=1 ORDER BY categoria, nombre"
        )
        menu = cur.fetchall()
    finally:
        conn.close()

    categorias = {"cocina": "🍳 Cocina", "bebidas": "🥤 Bebidas", "postres": "🍰 Postres"}
    CART = st.session_state.auto_cart

    for cat_key, cat_label in categorias.items():
        items = [p for p in menu if p["categoria"] == cat_key]
        if not items:
            continue
        st.markdown(f"<h3 style='margin-top:1.5rem;color:#2C221E'>{cat_label}</h3>",
                    unsafe_allow_html=True)

        for prod in items:
            pid = prod["id_producto"]
            ci = CART.get(pid, {"cantidad": 0, "obs": ""})
            img_path = obtener_imagen(prod.get("url_imagen"), tipo="plato")

            with st.container(border=True):
                cols = st.columns([1, 2, 1, 1, 1])

                # Imagen thumbnail
                with cols[0]:
                    st.image(img_path, width=80, use_container_width=False)

                # Nombre + precio
                with cols[1]:
                    st.markdown(
                        f"<div style='font-weight:700;font-size:1.1rem;color:#2C221E'>"
                        f"{prod['nombre']}</div>"
                        f"<div style='color:#8B2635;font-weight:700;font-size:1rem'>"
                        f"${prod['precio_venta']:,.0f}</div>",
                        unsafe_allow_html=True,
                    )

                # −
                with cols[2]:
                    if st.button("−", key=f"ad_{pid}", use_container_width=True):
                        if ci["cantidad"] > 0:
                            ci["cantidad"] -= 1
                            CART[pid] = ci if ci["cantidad"] > 0 else None
                            if ci["cantidad"] == 0:
                                CART.pop(pid, None)
                        st.rerun()

                # Cantidad
                with cols[3]:
                    st.markdown(
                        f"<div style='text-align:center;font-size:1.8rem;font-weight:700;"
                        f"padding:0.3rem 0'>{ci['cantidad']}</div>",
                        unsafe_allow_html=True,
                    )

                # +
                with cols[4]:
                    if st.button("+", key=f"ai_{pid}", use_container_width=True):
                        ci["cantidad"] += 1
                        CART[pid] = ci
                        st.rerun()

                # Observaciones (ocupa todo el ancho debajo del producto)
                ci["obs"] = st.text_input(
                    "Observaciones", value=ci.get("obs", ""),
                    key=f"ao_{pid}", placeholder="ej: sin sal",
                    label_visibility="collapsed",
                )

            # Separador de carta
            st.markdown(
                "<div style='border-top:1px dashed #B58A63;margin:0 0 0.3rem 0'></div>",
                unsafe_allow_html=True,
            )

    st.divider()

    total = 0
    qty = 0
    for pid, ci in list(CART.items()):
        if not ci or ci["cantidad"] <= 0:
            CART.pop(pid, None)
            continue
        precio = next(
            (p["precio_venta"] for p in menu if p["id_producto"] == pid),
            0
        )
        total += ci["cantidad"] * precio
        qty += ci["cantidad"]

    if qty == 0:
        st.info("🛒  Tu carrito está vacío. Agregá productos con el botón **+**.")
    else:
        st.markdown(
            f"<h3>🛒  {qty} ítem(s) — <span style='color:#8B2635'>${total:,.0f}</span></h3>",
            unsafe_allow_html=True,
        )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔥  CONFIRMAR Y ENVIAR PEDIDO",
                     use_container_width=True, type="primary", disabled=qty == 0):
            _enviar_pedido(mesa_id)
            st.rerun()


def _enviar_pedido(mesa_id: int) -> None:
    conn = get_connection_direct()
    try:
        conn.execute("BEGIN")

        cur = conn.execute(
            "INSERT INTO pedidos_cabecera (id_mesa, id_usuario) VALUES (?,?)",
            (mesa_id, 1)
        )
        id_pedido = cur.lastrowid

        for pid, ci in st.session_state.auto_cart.items():
            if ci and ci["cantidad"] > 0:
                obs = ci.get("obs", "").strip()
                obs = f"{obs} | {PEDIDO_TAG.format(mesa_id)}" if obs else PEDIDO_TAG.format(mesa_id)
                conn.execute(
                    "INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, observaciones)"
                    " VALUES (?,?,?,?)",
                    (id_pedido, pid, ci["cantidad"], obs)
                )

        conn.execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=?", (mesa_id,))
        conn.commit()

        st.session_state.auto_cart = {}
        st.balloons()
        st.success(f"✅  Pedido **#{id_pedido}** confirmado. La cocina ya prepara tus platos.")

    except Exception as e:
        conn.rollback()
        st.error(f"Error al enviar pedido: {e}")
    finally:
        conn.close()
