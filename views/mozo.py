"""
views/mozo.py - Terminal tactil del camarero con carta visual y estado de mesas.
"""
from __future__ import annotations

from html import escape
import unicodedata

import streamlit as st
from components.imagenes import obtener_imagen
from database import get_connection_direct


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
        cur = conn.execute("SELECT id_mesa, numero_mesa, estado FROM mesas ORDER BY numero_mesa")
        return cur.fetchall()
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _cargar_mozos() -> list:
    conn = get_connection_direct()
    try:
        cur = conn.execute("SELECT id_usuario, nombre, apellido FROM usuarios WHERE rol = 'mozo'")
        return cur.fetchall()
    finally:
        conn.close()


@st.cache_data(ttl=8)
def _pedidos_activos_por_mesa() -> dict:
    """Retorna resumen de pedidos activos agrupado por mesa."""
    conn = get_connection_direct()
    try:
        rows = conn.execute(
            """
            SELECT pc.id_mesa, pc.estado_comanda,
                   pm.nombre, pd.cantidad, pd.precio_unitario_facturado,
                   COALESCE(pd.observaciones, '') AS observaciones
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
              AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
            """
        ).fetchall()
    finally:
        conn.close()

    resultado: dict = {}
    for row in rows:
        mid = row["id_mesa"]
        resultado.setdefault(mid, {"items": [], "estados": set(), "total": 0.0})
        cantidad = float(row["cantidad"] or 0)
        precio = float(row["precio_unitario_facturado"] or 0)
        resultado[mid]["items"].append(
            {
                "nombre": row["nombre"],
                "cantidad": cantidad,
                "precio": precio,
                "obs": row["observaciones"] or "",
            }
        )
        resultado[mid]["estados"].add(row["estado_comanda"])
        resultado[mid]["total"] += cantidad * precio
    return resultado


def _limpiar_cache() -> None:
    _cargar_mesas.clear()
    _pedidos_activos_por_mesa.clear()


def _categoria_key(value: object) -> str:
    raw = " ".join(str(value or "").strip().split())
    sin_tildes = unicodedata.normalize("NFKD", raw)
    return "".join(ch for ch in sin_tildes if not unicodedata.combining(ch)).casefold()


def _categoria_matches(actual: object, esperada: object) -> bool:
    return _categoria_key(actual) == _categoria_key(esperada)


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


def _seleccionar_mozo() -> None:
    st.markdown(
        "<h1 style='text-align:center'>&#x1F468;&#x200D;&#x1F373; Terminal Mozo</h1>",
        unsafe_allow_html=True,
    )
    mozos = _cargar_mozos()
    opts = {f"{m['nombre']} {m['apellido']}": m["id_usuario"] for m in mozos}

    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        with st.container(border=True):
            st.markdown("### &#x1F464; Quien sos?")
            seleccion = st.selectbox(
                "Selecciona tu nombre",
                [""] + list(opts.keys()),
                label_visibility="collapsed",
            )
            if st.button("Ingresar", disabled=not seleccion, type="primary", use_container_width=True):
                st.session_state.mozo_id = opts[seleccion]
                st.session_state.mozo_nombre = seleccion
                st.session_state.mozo_step = "mesa"
                st.rerun()


def _estado_visual(mesa: dict, info_pedido: dict | None) -> tuple[str, str, str]:
    if mesa["estado"] == "libre":
        return "#388e3c", "&#x2705;", "LIBRE"
    if not info_pedido:
        return "#6a1520", "&#x1FA91;", "OCUPADA"

    estados = info_pedido["estados"]
    if "pendiente" in estados:
        return "#e65100", "&#x23F3;", "PENDIENTE"
    if "en_cocina" in estados:
        return "#f57c00", "&#x1F373;", "EN COCINA"
    if "listo" in estados:
        return "#1565c0", "&#x1F514;", "LISTO"
    return "#6a1520", "&#x1FA91;", "OCUPADA"


def _seleccionar_mesa() -> None:
    st.markdown(
        f"<p style='color:#8B2635;font-weight:700;font-size:1rem;margin:0'>"
        f"&#x1F464; {escape(str(st.session_state.mozo_nombre))}</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<h2 style='text-align:center;margin-bottom:1rem'>&#x1F4CD; Mesas</h2>", unsafe_allow_html=True)

    mesas = _cargar_mesas()
    pedidos_map = _pedidos_activos_por_mesa()

    cols_por_fila = 3
    for i in range(0, len(mesas), cols_por_fila):
        cols = st.columns(cols_por_fila)
        for j, mesa in enumerate(mesas[i : i + cols_por_fila]):
            mid = mesa["id_mesa"]
            libre = mesa["estado"] == "libre"
            info_pedido = pedidos_map.get(mid)
            color_bg, icono_estado, label_estado = _estado_visual(mesa, info_pedido)
            total_str = (
                f"<div style='font-size:0.85rem;margin-top:4px;opacity:0.9'>"
                f"${info_pedido['total']:,.0f}</div>"
                if info_pedido
                else ""
            )

            with cols[j]:
                st.markdown(
                    f"<div style='background:{color_bg};border-radius:8px;"
                    f"padding:1.1rem 0.8rem;text-align:center;color:white;"
                    f"font-size:1.55rem;font-weight:700;margin-bottom:6px'>"
                    f"&#x1FA91; {mesa['numero_mesa']}<br>"
                    f"<span style='font-size:0.72rem;font-weight:600;opacity:0.95'>"
                    f"{icono_estado} {label_estado}</span>"
                    f"{total_str}</div>",
                    unsafe_allow_html=True,
                )

                if libre:
                    if st.button("Abrir mesa", key=f"abrir_{mid}", use_container_width=True, type="primary"):
                        _abrir_mesa(mesa)
                else:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("Agregar", key=f"agregar_{mid}", use_container_width=True):
                            _entrar_a_mesa(mesa, tab="carta")
                    with col_b:
                        if st.button("Ver", key=f"ver_{mid}", use_container_width=True):
                            _entrar_a_mesa(mesa, tab="cuenta")

    st.markdown("---")
    if st.button("Cambiar mozo", use_container_width=True):
        st.session_state.mozo_step = "mozo"
        st.rerun()


def _abrir_mesa(mesa: dict) -> None:
    conn = get_connection_direct()
    try:
        conn.execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=?", (mesa["id_mesa"],))
        conn.commit()
    finally:
        conn.close()
    _limpiar_cache()
    _entrar_a_mesa(mesa, tab="carta")


def _entrar_a_mesa(mesa: dict, tab: str) -> None:
    st.session_state.mesa_id = mesa["id_mesa"]
    st.session_state.mesa_numero = mesa["numero_mesa"]
    st.session_state.cart = {}
    st.session_state.mozo_tab = tab
    st.session_state.mozo_step = "pedido"
    st.rerun()


def _tomar_pedido() -> None:
    mesa_id = st.session_state.mesa_id
    mesa_num = st.session_state.get("mesa_numero", "?")

    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.markdown(
            f"<div style='font-size:1.1rem;font-weight:700;color:#8B2635'>"
            f"&#x1FA91; Mesa {mesa_num} &nbsp;|&nbsp; "
            f"&#x1F464; {escape(str(st.session_state.mozo_nombre))}</div>",
            unsafe_allow_html=True,
        )
    with col_h2:
        if st.button("Mesas", use_container_width=True):
            st.session_state.mozo_step = "mesa"
            st.session_state.mozo_tab = "carta"
            st.rerun()

    tab_carta, tab_cuenta = st.tabs(["Nueva comanda", "Cuenta actual"])
    with tab_carta:
        _tab_carta(mesa_id)
    with tab_cuenta:
        _tab_cuenta(mesa_id, mesa_num)


def _tab_carta(mesa_id: int) -> None:
    menu = _cargar_menu()
    cart = st.session_state.cart

    categorias_presentes = []
    vistos = set()
    for prod in menu:
        categoria = str(prod["categoria"] or "").strip()
        cat_key = _categoria_key(categoria)
        if cat_key and cat_key not in vistos:
            categorias_presentes.append(categoria)
            vistos.add(cat_key)

    cat_labels = {
        "Entradas": "Entradas",
        "Pastas": "Pastas",
        "Carnes": "Carnes",
        "Pescados": "Pescados",
        "Comidas Criollas": "Criollas",
        "cocina": "Cocina",
        "bebidas": "Bebidas",
        "postres": "Postres",
        "Postres": "Postres",
    }

    for cat_key in categorias_presentes:
        items = [p for p in menu if _categoria_matches(p["categoria"], cat_key)]
        if not items:
            continue

        st.markdown(
            f"<h3 style='margin:1.2rem 0 0.6rem 0;color:#2C221E'>{escape(cat_labels.get(cat_key, cat_key))}</h3>",
            unsafe_allow_html=True,
        )
        for prod in items:
            _producto_row(prod, cart)

    st.divider()
    _resumen_carrito(mesa_id, menu)


def _producto_row(prod: dict, cart: dict) -> None:
    pid = prod["id_producto"]
    ci = cart.get(pid, {"cantidad": 0, "obs": ""})
    img_path = obtener_imagen(prod.get("url_imagen"), tipo="plato")

    col_img, col_info, col_ctrl = st.columns([1, 2, 2])
    with col_img:
        st.image(img_path, width=90, use_container_width=False)

    with col_info:
        st.markdown(
            f"<div style='font-weight:700;font-size:1.05rem;color:#2C221E'>{escape(str(prod['nombre']))}</div>"
            f"<div style='font-size:1rem;color:#8B2635;font-weight:700;margin-top:4px'>"
            f"${float(prod['precio_venta'] or 0):,.0f}</div>",
            unsafe_allow_html=True,
        )

    with col_ctrl:
        col_b1, col_b2, col_b3 = st.columns([1, 1, 1])
        with col_b1:
            if st.button("-", key=f"d_{pid}", use_container_width=True):
                if ci["cantidad"] > 0:
                    ci["cantidad"] -= 1
                    if ci["cantidad"] == 0:
                        cart.pop(pid, None)
                    else:
                        cart[pid] = ci
                st.rerun()
        with col_b2:
            st.markdown(
                f"<div style='text-align:center;font-size:1.4rem;font-weight:700;padding-top:4px'>"
                f"{ci['cantidad']}</div>",
                unsafe_allow_html=True,
            )
        with col_b3:
            if st.button("+", key=f"i_{pid}", use_container_width=True):
                ci["cantidad"] = ci.get("cantidad", 0) + 1
                cart[pid] = ci
                st.rerun()

    if ci["cantidad"] > 0:
        ci["obs"] = st.text_input(
            "Observacion",
            value=ci.get("obs", ""),
            key=f"o_{pid}",
            label_visibility="collapsed",
            placeholder="Nota para cocina...",
        )
        cart[pid] = ci

    st.markdown("<div style='border-top:1px dashed #B58A63;margin:0.5rem 0'></div>", unsafe_allow_html=True)


def _resumen_carrito(mesa_id: int, menu: list) -> None:
    menu_map = {p["id_producto"]: p for p in menu}
    items_cart = [(pid, ci) for pid, ci in st.session_state.cart.items() if ci and ci["cantidad"] > 0]
    total = sum(ci["cantidad"] * float(menu_map.get(pid, {}).get("precio_venta") or 0) for pid, ci in items_cart)
    qty = sum(ci["cantidad"] for _, ci in items_cart)

    if qty == 0:
        st.info("Carrito vacio. Agrega productos de la carta.")
        return

    with st.expander(f"{qty} items - ${total:,.0f} - Ver resumen", expanded=False):
        for pid, ci in items_cart:
            prod = menu_map.get(pid, {})
            importe = ci["cantidad"] * float(prod.get("precio_venta") or 0)
            obs = f" _(nota: {ci['obs']})_" if ci.get("obs") else ""
            st.markdown(f"- **{ci['cantidad']}x** {prod.get('nombre', '?')} - ${importe:,.0f}{obs}")

    col_env, col_can = st.columns(2)
    with col_env:
        if st.button("ENVIAR COMANDA", use_container_width=True, type="primary"):
            _enviar_comanda(mesa_id, items_cart, menu_map)
    with col_can:
        if st.button("Limpiar carrito", use_container_width=True):
            st.session_state.cart = {}
            st.rerun()


def _tab_cuenta(mesa_id: int, mesa_num) -> None:
    info = _pedidos_activos_por_mesa().get(mesa_id)

    if not info or not info["items"]:
        st.info("No hay pedidos activos para esta mesa.")
        return

    st.markdown(f"<h4>Consumo actual - Mesa {mesa_num}</h4>", unsafe_allow_html=True)

    total = 0.0
    for item in info["items"]:
        importe = item["cantidad"] * (item["precio"] or 0)
        total += importe
        obs_html = f" <em style='color:#888;font-size:0.85rem'>({escape(item['obs'])})</em>" if item["obs"] else ""
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;"
            f"padding:0.4rem 0;border-bottom:1px dotted #ddd'>"
            f"<span><b>{item['cantidad']:g}x</b> {escape(str(item['nombre']))}{obs_html}</span>"
            f"<span>${importe:,.0f}</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown(f"**Total consumido: ${total:,.0f}**")

    estados = info["estados"]
    if "listo" in estados:
        st.success("Hay platos listos para entregar.")
    elif "en_cocina" in estados:
        st.info("Pedidos en cocina.")
    elif "pendiente" in estados:
        st.warning("Pendiente de tomar en cocina.")

    st.caption("Para cobrar esta mesa, ir al modulo Caja.")
    if st.button("Actualizar", use_container_width=True):
        _limpiar_cache()
        st.rerun()


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
            precio = float(menu_map.get(pid, {}).get("precio_venta") or 0)
            conn.execute(
                "INSERT INTO pedido_detalle "
                "(id_pedido, id_producto, cantidad, precio_unitario_facturado, observaciones)"
                " VALUES (?,?,?,?,?)",
                (id_pedido, pid, ci["cantidad"], precio, ci.get("obs", "")),
            )
        conn.commit()
        _limpiar_cache()
        st.success(f"Comanda #{id_pedido} enviada a cocina - {sum(c['cantidad'] for _, c in items_cart)} items")
        st.session_state.cart = {}
        st.session_state.mozo_tab = "cuenta"
        st.rerun()
    except Exception as exc:
        conn.rollback()
        st.error(f"Error al enviar: {exc}")
    finally:
        conn.close()
