"""
views/mozo.py — Terminal táctil del camarero con imágenes y carta visual.
Mejoras: resumen de pedidos activos por mesa, agregar items a pedido
existente, cancelar items, indicador de estado de cada mesa.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st
from database import get_connection_direct, avanzar_estado
from components.imagenes import obtener_imagen


# ── Queries cacheadas ─────────────────────────────────────────────────

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


@st.cache_data(ttl=8)
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


@st.cache_data(ttl=8)
def _pedidos_activos_por_mesa() -> dict:
        """Retorna {id_mesa: {"items": [...], "estados": set, "total": float}}."""
        conn = get_connection_direct()
        try:
                    rows = conn.execute("""
                                SELECT pc.id_mesa, pc.estado_comanda,
                                                   pm.nombre, pd.cantidad, pd.precio_unitario_facturado,
                                                                      pd.observaciones
                                                                                  FROM pedidos_cabecera pc
                                                                                              JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
                                                                                                          JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                                                                                                                      WHERE pc.estado_comanda IN ('pendiente','en_cocina','listo','entregado')
                                                                                                                                    AND (pd.cantidad - COALESCE(pd.cantidad_anulada,0)) > 0
                                                                                                                                            """).fetchall()
finally:
        conn.close()

    resultado: dict = {}
    for r in rows:
                mid = r["id_mesa"]
                if mid not in resultado:
                                resultado[mid] = {"items": [], "estados": set(), "total": 0.0}
                            resultado[mid]["items"].append({
                                            "nombre": r["nombre"],
                                            "cantidad": r["cantidad"],
                                            "precio": r["precio_unitario_facturado"],
                                            "obs": r["observaciones"] or "",
                            })
        resultado[mid]["estados"].add(r["estado_comanda"])
        resultado[mid]["total"] += r["cantidad"] * (r["precio_unitario_facturado"] or 0)
    return resultado


def _limpiar_cache() -> None:
        _cargar_mesas.clear()
    _pedidos_activos_por_mesa.clear()


# ── Render principal ──────────────────────────────────────────────────

def render() -> None:
        for key, default in [
                    ("mozo_step", "mozo"),
                    ("mozo_id", None),
                    ("mozo_nombre", None),
                    ("mesa_id", None),
                    ("mesa_numero", None),
                    ("cart", {}),
                    ("mozo_tab", "carta"),
        ]:
                    if key not in st.session_state:
                                    st.session_state[key] = default

                step = st.session_state.mozo_step
    if step == "mozo":
                _seleccionar_mozo()
elif step == "mesa":
        _seleccionar_mesa()
elif step == "pedido":
        _tomar_pedido()


# ── Paso 1: Selección de mozo ─────────────────────────────────────────

def _seleccionar_mozo() -> None:
        st.markdown(
                    "<h1 style='text-align:center'>&#x1F468;&#x200D;&#x1F373; Terminal Mozo</h1>",
                    unsafe_allow_html=True,
        )
    mozos = _cargar_mozos()
    opts = {f"{m['nombre']} {m['apellido']}": m["id_usuario"] for m in mozos}

    with st.container():
                col_l, col_m, col_r = st.columns([1, 2, 1])
        with col_m:
                        with st.container(border=True):
                                            st.markdown("### &#x1F464; ¿Quién sos?")
                                            seleccion = st.selectbox(
                                                "Seleccioná tu nombre", [""] + list(opts.keys()),
                                                label_visibility="collapsed",
                                            )
                                            if st.button(
                                                                    "Ingresar",
                                                                    disabled=not seleccion,
                                                                    type="primary",
                                                                    use_container_width=True,
                                            ):
                                                                    st.session_state.mozo_id = opts[seleccion]
                                                                    st.session_state.mozo_nombre = seleccion
                                                                    st.session_state.mozo_step = "mesa"
                                                                    st.rerun()


# ── Paso 2: Selección de mesa ─────────────────────────────────────────

def _seleccionar_mesa() -> None:
        st.markdown(
                    f"<p style='color:#8B2635;font-weight:700;font-size:1rem;margin:0'>"
                    f"&#x1F464; {st.session_state.mozo_nombre}</p>",
                    unsafe_allow_html=True,
        )
    st.markdown(
                "<h2 style='text-align:center;margin-bottom:1rem'>&#x1F4CD; Mesas</h2>",
                unsafe_allow_html=True,
    )

    mesas = _cargar_mesas()
    pedidos_map = _pedidos_activos_por_mesa()

    COLS = 3
    for i in range(0, len(mesas), COLS):
                cols = st.columns(COLS)
        for j, mesa in enumerate(mesas[i : i + COLS]):
                        mid = mesa["id_mesa"]
                        libre = mesa["estado"] == "libre"
                        info_pedido = pedidos_map.get(mid)

            with cols[j]:
                                # Color según estado
                                if libre:
                                                        color_bg = "#388e3c"
                                                        icono_estado = "&#x2705;"
                                                        label_estado = "LIBRE"
elif info_pedido:
                    estados = info_pedido["estados"]
                    if "pendiente" in estados:
                                                color_bg = "#e65100"
                                                icono_estado = "&#x23F3;"
                                                label_estado = "PENDIENTE"
elif "en_cocina" in estados:
                        color_bg = "#f57c00"
                        icono_estado = "&#x1F373;"
                        label_estado = "EN COCINA"
elif "listo" in estados:
                        color_bg = "#1565c0"
                        icono_estado = "&#x1F514;"
                        label_estado = "LISTO"
else:
                        color_bg = "#6a1520"
                            icono_estado = "&#x1FA91;"
                        label_estado = "OCUPADA"
else:
                    color_bg = "#6a1520"
                    icono_estado = "&#x1FA91;"
                    label_estado = "OCUPADA"

                total_str = ""
                if info_pedido:
                                        total_str = (
                                                                    f"<div style='font-size:0.85rem;margin-top:4px;opacity:0.9'>"
                                                                    f"${info_pedido['total']:,.0f}</div>"
                                        )

                st.markdown(
                                        f"<div style='background:{color_bg};border-radius:14px;"
                                        f"padding:1.4rem 1rem;text-align:center;color:white;"
                                        f"font-size:1.8rem;font-weight:700;margin-bottom:6px'>"
                                        f"&#x1FA91; {mesa['numero_mesa']}<br>"
                                        f"<span style='font-size:0.75rem;font-weight:600;opacity:0.9'>"
                                        f"{icono_estado} {label_estado}</span>"
                                        f"{total_str}</div>",
                                        unsafe_allow_html=True,
                )

                if libre:
                                        if st.button(
                                                                    "&#x2795; Abrir mesa",
                                                                    key=f"abrir_{mid}",
                                                                    use_container_width=True,
                                                                    type="primary",
                                        ):
                                                                    conn = get_connection_direct()
                                                                    try:
                                                                                                    conn.execute(
                                                                                                                                        "UPDATE mesas SET estado='ocupada' WHERE id_mesa=?",
                                                                                                                                        (mid,),
                                                                                                        )
                                                                                                    conn.commit()
                                            finally:
                            conn.close()
                        _limpiar_cache()
                        st.session_state.mesa_id = mid
                        st.session_state.mesa_numero = mesa["numero_mesa"]
                        st.session_state.cart = {}
                        st.session_state.mozo_step = "pedido"
                        st.rerun()
else:
                    col_a, col_b = st.columns(2)
                    with col_a:
                                                if st.button(
                                                                                "&#x2795; Agregar",
                                                                                key=f"agregar_{mid}",
                                                                                use_container_width=True,
                                                ):
                                                                                st.session_state.mesa_id = mid
                                                                                st.session_state.mesa_numero = mesa["numero_mesa"]
                                                                                st.session_state.cart = {}
                                                                                st.session_state.mozo_step = "pedido"
                                                                                st.rerun()
                                                                        with col_b:
                                                if st.button(
                                                                                                        "&#x1F4CB; Ver",
                                                                                                        key=f"ver_{mid}",
                                                                                                        use_container_width=True,
                                                                            ):
                                                                                                            st.session_state.mesa_id = mid
                                                                                                            st.session_state.mesa_numero = mesa["numero_mesa"]
                                                                                                            st.session_state.cart = {}
                                                                                                            st.session_state.mozo_step = "pedido"
                                                                                                            st.session_state.mozo_tab = "cuenta"
                                                                                                            st.rerun()

    st.markdown("---")
    if st.button("&#x1F504; Cambiar mozo", use_container_width=True):
                st.session_state.mozo_step = "mozo"
        st.rerun()


# ── Paso 3: Carta + cuenta ────────────────────────────────────────────

def _tomar_pedido() -> None:
        mesa_id = st.session_state.mesa_id
    mesa_num = st.session_state.get("mesa_numero", "?")

    # Barra superior
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
                st.markdown(
                                f"<div style='font-size:1.1rem;font-weight:700;color:#8B2635'>"
                                f"&#x1FA91; Mesa {mesa_num} &nbsp;|&nbsp; "
                                f"&#x1F464; {st.session_state.mozo_nombre}</div>",
                                unsafe_allow_html=True,
                )
    with col_h2:
                if st.button("&#x2190; Mesas", use_container_width=True):
                                st.session_state.mozo_step = "mesa"
            st.session_state.mozo_tab = "carta"
            st.rerun()

    # Tabs
    tab_carta, tab_cuenta = st.tabs(["&#x1F4CB; Nueva comanda", "&#x1F9FE; Cuenta actual"])

    with tab_carta:
                _tab_carta(mesa_id)

    with tab_cuenta:
                _tab_cuenta(mesa_id, mesa_num)


def _tab_carta(mesa_id: int) -> None:
        """Carta visual con imágenes para tomar nuevos pedidos."""
    menu = _cargar_menu()
    CART = st.session_state.cart

    cat_labels = {
                "Entradas": "&#x1F957; Entradas",
                "Pastas": "&#x1F35D; Pastas",
                "Carnes": "&#x1F969; Carnes",
                "Pescados": "&#x1F41F; Pescados",
                "Comidas Criollas": "&#x1F333; Criollas",
                "cocina": "&#x1F373; Cocina",
                "bebidas": "&#x1F964; Bebidas",
                "postres": "&#x1F370; Postres",
                "Postres": "&#x1F370; Postres",
    }

    categorias_presentes = []
    seen = set()
    for p in menu:
                c = p["categoria"]
        if c not in seen:
                        categorias_presentes.append(c)
            seen.add(c)

    for cat_key in categorias_presentes:
                items = [p for p in menu if p["categoria"] == cat_key]
        if not items:
                        continue
        label = cat_labels.get(cat_key, cat_key)
        st.markdown(
                        f"<h3 style='margin:1.2rem 0 0.6rem 0;color:#2C221E'>{label}</h3>",
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
                                c1, c2, c3 = st.columns([1, 1, 1])
                with c1:
                                        if st.button("&#x2212;", key=f"d_{pid}", use_container_width=True):
                                                                    if ci["cantidad"] > 0:
                                                                                                    ci["cantidad"] -= 1
                                                                                                    if ci["cantidad"] == 0:
                                                                                                                                        CART.pop(pid, None)
                                                                        else:
                                CART[pid] = ci
                            st.rerun()
                with c2:
                                        st.markdown(
                                                                    f"<div style='text-align:center;font-size:1.4rem;"
                                                                    f"font-weight:700;padding-top:4px'>{ci['cantidad']}</div>",
                                                                    unsafe_allow_html=True,
                                        )
                with c3:
                                        if st.button("+", key=f"i_{pid}", use_container_width=True):
                                                                    ci["cantidad"] = ci.get("cantidad", 0) + 1
                        CART[pid] = ci
                        st.rerun()

            if ci["cantidad"] > 0:
                                obs_val = st.text_input(
                                                        "Observación",
                                                        value=ci.get("obs", ""),
                                                        key=f"o_{pid}",
                                                        label_visibility="collapsed",
                                                        placeholder="&#x1F4DD; Nota para cocina...",
                                )
                ci["obs"] = obs_val
                CART[pid] = ci

            st.markdown(
                                "<div style='border-top:1px dashed #B58A63;margin:0.5rem 0'></div>",
                                unsafe_allow_html=True,
            )

    # ── Resumen del carrito ───────────────────────────────────────────
    st.divider()
    menu_map = {p["id_producto"]: p for p in menu}
    items_cart = [(pid, ci) for pid, ci in CART.items() if ci and ci["cantidad"] > 0]
    total = sum(
                ci["cantidad"] * menu_map.get(pid, {}).get("precio_venta", 0)
                for pid, ci in items_cart
    )
    qty = sum(ci["cantidad"] for _, ci in items_cart)

    if qty == 0:
                st.info("&#x1F6D2; Carrito vacío. Agregá productos de la carta.")
else:
        with st.expander(f"&#x1F6D2; {qty} items · **${total:,.0f}** — Ver resumen", expanded=False):
                        for pid, ci in items_cart:
                                            prod = menu_map.get(pid, {})
                importe = ci["cantidad"] * prod.get("precio_venta", 0)
                st.markdown(
                                        f"- **{ci['cantidad']}x** {prod.get('nombre','?')} — ${importe:,.0f}"
                                        + (f" _(nota: {ci['obs']})_" if ci.get("obs") else ""),
                )

        col_env, col_can = st.columns(2)
        with col_env:
                        if st.button(
                                            "&#x2705; ENVIAR COMANDA",
                                            use_container_width=True,
                                            type="primary",
                        ):
                                            _enviar_comanda(mesa_id, items_cart, menu_map)
        with col_can:
                        if st.button("&#x1F5D1; Limpiar carrito", use_container_width=True):
                                            st.session_state.cart = {}
                st.rerun()


def _tab_cuenta(mesa_id: int, mesa_num) -> None:
        """Muestra los pedidos activos de la mesa con estado en tiempo real."""
    pedidos_map = _pedidos_activos_por_mesa()
    info = pedidos_map.get(mesa_id)

    if not info or not info["items"]:
                st.info("No hay pedidos activos para esta mesa.")
        return

    st.markdown(
                f"<h4>Consumo actual — Mesa {mesa_num}</h4>",
                unsafe_allow_html=True,
    )

    total = 0.0
    for item in info["items"]:
                importe = item["cantidad"] * (item["precio"] or 0)
        total += importe
        obs_html = f" <em style='color:#888;font-size:0.85rem'>({item['obs']})</em>" if item["obs"] else ""
        st.markdown(
                        f"<div style='display:flex;justify-content:space-between;"
                        f"padding:0.4rem 0;border-bottom:1px dotted #ddd'>"
                        f"<span><b>{item['cantidad']}×</b> {item['nombre']}{obs_html}</span>"
                        f"<span>${importe:,.0f}</span></div>",
                        unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown(f"**Total consumido: ${total:,.0f}**")

    estados = info["estados"]
    if "listo" in estados:
                st.success("&#x1F514; Hay platos listos para entregar.")
elif "en_cocina" in estados:
        st.info("&#x1F373; Pedidos en cocina.")
elif "pendiente" in estados:
        st.warning("&#x23F3; Pendiente de tomar en cocina.")

    st.caption("Para cobrar esta mesa, ir al módulo Caja.")

    if st.button("&#x1F504; Actualizar", use_container_width=True):
                _limpiar_cache()
        st.rerun()


# ── Enviar comanda ────────────────────────────────────────────────────

def _enviar_comanda(mesa_id: int, items_cart: list, menu_map: dict) -> None:
        conn = get_connection_direct()
    try:
                conn.execute("BEGIN")
        cur = conn.execute(
                        "INSERT INTO pedidos_cabecera (id_mesa, id_usuario) VALUES (?,?)",
                        (mesa_id, st.session_state.mozo_id),
        )
        id_pedido = cur.lastrowid

        for pid, ci in items_cart:
                        precio = menu_map.get(pid, {}).get("precio_venta", 0)
            conn.execute(
                                "INSERT INTO pedido_detalle "
                                "(id_pedido, id_producto, cantidad, precio_unitario_facturado, observaciones)"
                                " VALUES (?,?,?,?,?)",
                                (id_pedido, pid, ci["cantidad"], precio, ci.get("obs", "")),
            )
        conn.commit()
        _limpiar_cache()
        st.success(
                        f"&#x2705; Comanda #{id_pedido} enviada a cocina — "
                        f"{sum(c['cantidad'] for _, c in items_cart)} items"
        )
        st.session_state.cart = {}
        st.session_state.mozo_tab = "cuenta"
        st.rerun()
except Exception as e:
        conn.rollback()
        st.error(f"&#x274C; Error al enviar: {e}")
finally:
        conn.close()
