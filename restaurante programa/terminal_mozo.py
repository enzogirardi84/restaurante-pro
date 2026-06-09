"""
Terminal tactil para mozos.
Flujo: seleccionar mozo -> elegir mesa -> armar pedido -> enviar a cocina.
"""
from __future__ import annotations

from html import escape

import streamlit as st
import pandas as pd
from database import get_connection, init_db, rows as db_rows
from components.categorias import CATEGORIAS_MENU


COLOR_PRIMARY = "#b42318"
COLOR_SURFACE = "#ffffff"
COLOR_BG = "#f6f4ef"
COLOR_BORDER = "#ded8cf"
COLOR_TEXT = "#24211d"
COLOR_MUTED = "#6f685f"
COLOR_OK = "#247a3d"
COLOR_WARN = "#b86b00"
COLOR_DISABLED = "#8c8c8c"


st.set_page_config(
    page_title="Terminal Mozo",
    layout="wide",
    initial_sidebar_state="collapsed",
)

init_db()


def inject_styles() -> None:
    st.markdown(
        f"""
        <style>
            .stApp {{
                background: {COLOR_BG};
                color: {COLOR_TEXT};
            }}
            div[data-testid="stHeader"] {{
                background: rgba(246, 244, 239, 0.92);
            }}
            .block-container {{
                padding-top: 1.2rem;
                padding-bottom: 2rem;
                max-width: 1180px;
            }}
            .topbar {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                padding: 0.8rem 0 1rem;
                border-bottom: 1px solid {COLOR_BORDER};
                margin-bottom: 1rem;
            }}
            .title {{
                font-size: 1.55rem;
                font-weight: 750;
                margin: 0;
            }}
            .subtitle {{
                color: {COLOR_MUTED};
                font-size: 0.92rem;
            }}
            .pill {{
                display: inline-flex;
                align-items: center;
                border-radius: 999px;
                padding: 0.3rem 0.72rem;
                font-size: 0.82rem;
                font-weight: 700;
                color: white;
                white-space: nowrap;
            }}
            .mesa-card {{
                background: {COLOR_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 1rem;
                min-height: 128px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                box-shadow: 0 1px 2px rgba(20, 20, 20, 0.05);
            }}
            .mesa-numero {{
                font-size: 2rem;
                font-weight: 800;
                line-height: 1;
            }}
            .mesa-label {{
                color: {COLOR_MUTED};
                font-size: 0.86rem;
                margin-top: 0.25rem;
            }}
            .producto {{
                background: {COLOR_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 0.72rem 0.82rem;
                margin-bottom: 0.55rem;
            }}
            .producto-nombre {{
                font-weight: 750;
                font-size: 1rem;
            }}
            .producto-precio {{
                color: {COLOR_MUTED};
                font-size: 0.88rem;
                margin-top: 0.15rem;
            }}
            .cantidad {{
                text-align: center;
                font-size: 1.35rem;
                font-weight: 800;
                padding-top: 0.35rem;
            }}
            .cart-line {{
                display: flex;
                justify-content: space-between;
                gap: 0.8rem;
                border-bottom: 1px solid {COLOR_BORDER};
                padding: 0.62rem 0;
            }}
            .cart-name {{
                font-weight: 700;
            }}
            .cart-note {{
                color: {COLOR_MUTED};
                font-size: 0.86rem;
                margin-top: 0.12rem;
            }}
            .total-box {{
                background: {COLOR_TEXT};
                color: white;
                border-radius: 8px;
                padding: 0.9rem 1rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-top: 0.8rem;
            }}
            button[kind="primary"] {{
                background: {COLOR_PRIMARY};
                border-color: {COLOR_PRIMARY};
            }}
            .card-guia {{
                border-radius: 10px;
                padding: 1rem 1.2rem;
                margin: 0.5rem 0 0.8rem;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);
                transition: all 0.2s ease;
            }}
            .card-guia-nombre {{
                font-size: 1.2rem;
                font-weight: 800;
                line-height: 1.3;
            }}
            .card-guia-categoria {{
                font-size: 0.82rem;
                color: {COLOR_MUTED};
                text-transform: capitalize;
                margin-top: 0.15rem;
            }}
            .card-guia-badge {{
                display: inline-block;
                padding: 0.2rem 0.65rem;
                border-radius: 4px;
                font-size: 0.75rem;
                font-weight: 700;
                color: white;
            }}
            .card-guia-precio {{
                font-size: 1.5rem;
                font-weight: 800;
                line-height: 1;
            }}
            .card-guia-subtotal {{
                font-size: 0.85rem;
                color: {COLOR_MUTED};
                margin-top: 0.2rem;
            }}
            .producto-selected {{
                border-left: 4px solid {COLOR_OK};
                background: #f6fdf4;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def money(value: float) -> str:
    return f"${value:,.0f}".replace(",", ".")


def obtener_mozos() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id_usuario, nombre, apellido
              FROM usuarios
             WHERE rol = 'mozo'
             ORDER BY nombre, apellido
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def obtener_mesas() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id_mesa, numero_mesa, estado
              FROM mesas
             ORDER BY numero_mesa
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def obtener_menu() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id_producto, nombre, precio_venta, categoria
              FROM productos_menu
             WHERE activo = 1
             ORDER BY categoria, nombre
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def ocupar_mesa(id_mesa: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE mesas SET estado = 'ocupada' WHERE id_mesa = ?", (id_mesa,))
        conn.commit()
    finally:
        conn.close()


def crear_pedido(id_mesa: int, id_usuario: int, carrito: dict[int, dict]) -> int:
    items = [item for item in carrito.values() if int(item.get("cantidad", 0)) > 0]
    if not items:
        raise ValueError("El pedido no tiene productos.")

    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")

        cur = conn.execute("""
            INSERT INTO pedidos_cabecera (id_mesa, id_usuario, estado_comanda)
            VALUES (?, ?, 'pendiente')
        """, (id_mesa, id_usuario))
        id_pedido = cur.lastrowid

        for item in items:
            producto = conn.execute("""
                SELECT id_producto, precio_venta
                  FROM productos_menu
                 WHERE id_producto = ? AND activo = 1
            """, (item["id_producto"],)).fetchone()
            if producto is None:
                raise ValueError(f"Producto inexistente o inactivo: {item['id_producto']}")

            conn.execute("""
                INSERT INTO pedido_detalle
                    (id_pedido, id_producto, cantidad, observaciones, precio_unitario_facturado)
                VALUES (?, ?, ?, ?, ?)
            """, (
                id_pedido,
                producto["id_producto"],
                int(item["cantidad"]),
                item.get("observaciones", "").strip(),
                producto["precio_venta"],
            ))

        conn.execute("UPDATE mesas SET estado = 'ocupada' WHERE id_mesa = ?", (id_mesa,))
        conn.execute("COMMIT")
        return id_pedido
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def verificar_stock_insumos(id_producto: int) -> tuple[bool, list[str]]:
    """Verifica si hay stock suficiente de todos los insumos para un plato.
    Retorna (disponible, [lista_de_faltantes])."""
    receta = db_rows("""
        SELECT i.nombre, r.cantidad_a_descontar, i.stock_actual, i.unidad_medida
        FROM recetas_escandallo r
        JOIN insumos i ON i.id_insumo = r.id_insumo
        WHERE r.id_producto = ?
    """, (id_producto,))
    if not receta:
        return True, []
    faltantes = []
    for r in receta:
        if float(r["stock_actual"]) < float(r["cantidad_a_descontar"]):
            faltantes.append(f"{r['nombre']} (necesita {float(r['cantidad_a_descontar']):.0f} {r['unidad_medida']}, hay {float(r['stock_actual']):.0f})")
    return len(faltantes) == 0, faltantes


def render_card_confirmacion(producto: dict) -> None:
    """Card guia de confirmacion visual que se muestra al seleccionar un plato."""
    pid = int(producto["id_producto"])
    cart_item = st.session_state.cart.get(pid, {"cantidad": 0, "observaciones": ""})
    cantidad = int(cart_item.get("cantidad", 0))
    precio = float(producto["precio_venta"])
    tiene_seleccion = cantidad > 0

    disponible, faltantes = verificar_stock_insumos(pid)
    stockout = not disponible and tiene_seleccion

    border_color = "#b42318" if stockout else ("#247a3d" if tiene_seleccion else "#ded8cf")
    bg_color = "#fff5f5" if stockout else ("#f6fdf4" if tiene_seleccion else "#ffffff")
    label = "SIN STOCK" if stockout else ("CONFIRMADO" if tiene_seleccion else "SELECCIONAR")

    st.markdown(
        f"""
        <div class="card-guia" style="border-left: 6px solid {border_color}; background: {bg_color};">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; flex-wrap:wrap;">
                <div style="flex:2; min-width:200px;">
                    <div class="card-guia-nombre">{producto['nombre']}</div>
                    <div class="card-guia-categoria">{producto['categoria']}</div>
                    <div style="margin-top:0.5rem;">
                        <span class="card-guia-badge" style="background:{border_color};">{label}</span>
                    </div>
                </div>
                <div style="flex:1; min-width:120px; text-align:right;">
                    <div class="card-guia-precio">$ {precio:,.0f}</div>
                    <div class="card-guia-subtotal">Subtotal: $ {(cantidad * precio):,.0f}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if stockout:
        for f in faltantes:
            st.error(f"Insumo critico agotado: {f}")
        st.button("Plato no disponible", disabled=True, use_container_width=True)
    else:
        col_dec2, col_qty2, col_inc2, col_obs2 = st.columns([0.6, 0.7, 0.6, 4])
        with col_dec2:
            if st.button("-", key=f"card_dec_{pid}", use_container_width=True, disabled=cantidad == 0):
                cart_set_producto(producto, delta=-1)
                st.rerun()
        with col_qty2:
            st.markdown(f'<div class="cantidad">{cantidad}</div>', unsafe_allow_html=True)
        with col_inc2:
            if st.button("+", key=f"card_inc_{pid}", use_container_width=True):
                cart_set_producto(producto, delta=1)
                st.rerun()
        with col_obs2:
            nota = st.text_input(
                "Obs", value=cart_item.get("observaciones", ""),
                key=f"card_obs_{pid}", label_visibility="collapsed",
                placeholder="Aclaracion para cocina...",
            )
            if tiene_seleccion:
                st.session_state.cart[pid]["observaciones"] = nota

    st.markdown("<hr style='margin:0.8rem 0;border-color:#e0d8ce;'>", unsafe_allow_html=True)


def init_session() -> None:
    defaults = {
        "mozo": None,
        "mesa": None,
        "step": "mozo",
        "cart": {},
        "success_msg": None,
        "menu_search": "",
        "selected_product": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_all() -> None:
    for key in ("mozo", "mesa", "cart", "step", "success_msg", "menu_search"):
        st.session_state.pop(key, None)
    init_session()


def volver_a_mesas(limpiar_carrito: bool = True) -> None:
    st.session_state.mesa = None
    if limpiar_carrito:
        st.session_state.cart = {}
    st.session_state.step = "mesa"


def seleccionar_mesa(mesa: dict) -> None:
    st.session_state.mesa = mesa
    st.session_state.cart = {}
    st.session_state.step = "pedido"


def cart_set_producto(producto: dict, cantidad: int | None = None, delta: int = 0) -> None:
    pid = int(producto["id_producto"])
    cart = st.session_state.cart
    current = cart.get(pid, {
        "id_producto": pid,
        "nombre": producto["nombre"],
        "precio": float(producto["precio_venta"]),
        "categoria": producto["categoria"],
        "cantidad": 0,
        "observaciones": "",
    })
    nueva_cantidad = int(cantidad if cantidad is not None else current["cantidad"] + delta)
    nueva_cantidad = max(0, min(nueva_cantidad, 99))
    if nueva_cantidad == 0:
        cart.pop(pid, None)
        return
    current["cantidad"] = nueva_cantidad
    current["nombre"] = producto["nombre"]
    current["precio"] = float(producto["precio_venta"])
    current["categoria"] = producto["categoria"]
    cart[pid] = current


def header(titulo: str, subtitulo: str = "") -> None:
    mozo = st.session_state.get("mozo")
    mesa = st.session_state.get("mesa")
    contexto = []
    if mozo:
        contexto.append(escape(mozo["nombre"]))
    if mesa:
        contexto.append(f"Mesa {mesa['numero_mesa']}")
    badge = " / ".join(contexto) if contexto else "Restaurante"
    st.markdown(
        f"""
        <div class="topbar">
            <div>
                <div class="title">{escape(titulo)}</div>
                <div class="subtitle">{escape(subtitulo)}</div>
            </div>
            <span class="pill" style="background:{COLOR_PRIMARY}">{badge}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def pantalla_mozo() -> None:
    header("Terminal de mozo", "Identificate para tomar pedidos.")
    mozos = obtener_mozos()
    if not mozos:
        st.error("No hay mozos registrados.")
        return

    opciones = {f"{m['nombre']} {m['apellido']}": m["id_usuario"] for m in mozos}
    seleccion = st.selectbox("Mozo", [""] + list(opciones), index=0)

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("Ingresar", type="primary", use_container_width=True, disabled=not seleccion):
            st.session_state.mozo = {"id": opciones[seleccion], "nombre": seleccion}
            st.session_state.step = "mesa"
            st.rerun()


def pantalla_mesas() -> None:
    header("Seleccionar mesa", "Las mesas ocupadas tambien permiten agregar otro pedido.")

    if st.session_state.success_msg:
        st.success(st.session_state.success_msg)
        st.session_state.success_msg = None

    mesas = obtener_mesas()
    if not mesas:
        st.warning("No hay mesas cargadas.")
        return

    cols_por_fila = 4
    for i in range(0, len(mesas), cols_por_fila):
        cols = st.columns(cols_por_fila)
        for col, mesa in zip(cols, mesas[i:i + cols_por_fila]):
            estado = mesa["estado"]
            if estado == "libre":
                color = COLOR_OK
                accion = "Abrir pedido"
                disabled = False
            elif estado == "ocupada":
                color = COLOR_WARN
                accion = "Agregar pedido"
                disabled = False
            else:
                color = COLOR_DISABLED
                accion = "Esperando cuenta"
                disabled = True

            with col:
                st.markdown(
                    f"""
                    <div class="mesa-card">
                        <div>
                            <div class="mesa-numero">Mesa {mesa['numero_mesa']}</div>
                            <div class="mesa-label">{escape(estado.replace("_", " ").title())}</div>
                        </div>
                        <span class="pill" style="background:{color}; width: fit-content;">
                            {escape(accion)}
                        </span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(accion, key=f"mesa_{mesa['id_mesa']}", use_container_width=True, disabled=disabled):
                    seleccionar_mesa(mesa)
                    st.rerun()

    st.divider()
    if st.button("Cambiar mozo", use_container_width=True):
        reset_all()
        st.rerun()


def render_producto(producto: dict) -> None:
    pid = int(producto["id_producto"])
    cart_item = st.session_state.cart.get(pid, {"cantidad": 0, "observaciones": ""})
    cantidad = int(cart_item.get("cantidad", 0))
    is_selected = (st.session_state.get("selected_product") == pid)

    st.markdown(
        f"""
        <div class="producto {'producto-selected' if is_selected else ''}"
             style="{'border-left:4px solid #247a3d;background:#f6fdf4;' if is_selected else ''}">
            <div class="producto-nombre">{escape(producto['nombre'])}</div>
            <div class="producto-precio">{money(producto['precio_venta'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_sel, col_dec, col_qty, col_inc, col_note = st.columns([1.3, 0.65, 0.7, 0.65, 4])
    with col_sel:
        label_btn = "Seleccionado" if is_selected else "Seleccionar"
        tipo_btn = "primary" if is_selected else "secondary"
        if st.button(label_btn, key=f"sel_{pid}", type=tipo_btn, use_container_width=True):
            st.session_state.selected_product = pid if not is_selected else None
            st.rerun()
    with col_dec:
        if st.button("-", key=f"dec_{pid}", use_container_width=True, disabled=cantidad == 0):
            cart_set_producto(producto, delta=-1)
            st.rerun()
    with col_qty:
        st.markdown(f'<div class="cantidad">{cantidad}</div>', unsafe_allow_html=True)
    with col_inc:
        if st.button("+", key=f"inc_{pid}", use_container_width=True):
            cart_set_producto(producto, delta=1)
            st.rerun()
    with col_note:
        nota = st.text_input(
            "Obs", value=cart_item.get("observaciones", ""),
            key=f"obs_{pid}", label_visibility="collapsed",
            placeholder="Aclaracion para cocina...",
        )
        if cantidad > 0:
            st.session_state.cart[pid]["observaciones"] = nota

    if is_selected:
        render_card_confirmacion(producto)


def render_carrito(menu: list[dict]) -> tuple[int, float]:
    cart = st.session_state.cart
    total_items = sum(int(item["cantidad"]) for item in cart.values())
    total = sum(int(item["cantidad"]) * float(item["precio"]) for item in cart.values())

    st.markdown("### Pedido actual")
    if total_items == 0:
        st.info("Agrega platos o bebidas con el boton +.")
    else:
        for pid, item in list(cart.items()):
            cantidad = int(item["cantidad"])
            importe = cantidad * float(item["precio"])
            obs = item.get("observaciones", "").strip()
            st.markdown(
                f"""
                <div class="cart-line">
                    <div>
                        <div class="cart-name">{cantidad}x {escape(item['nombre'])}</div>
                        <div class="cart-note">{escape(obs) if obs else "Sin observaciones"}</div>
                    </div>
                    <div><b>{money(importe)}</b></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            cols = st.columns([1, 1, 3])
            producto = next((p for p in menu if int(p["id_producto"]) == int(pid)), None)
            if producto:
                with cols[0]:
                    if st.button("Quitar", key=f"remove_{pid}", use_container_width=True):
                        cart.pop(pid, None)
                        st.rerun()
                with cols[1]:
                    if st.button("+1", key=f"quick_add_{pid}", use_container_width=True):
                        cart_set_producto(producto, delta=1)
                        st.rerun()

        st.markdown(
            f"""
            <div class="total-box">
                <span>{total_items} item(s)</span>
                <strong>{money(total)}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return total_items, total


def pantalla_pedido() -> None:
    mesa = st.session_state.mesa
    header(
        f"Pedido mesa {mesa['numero_mesa']}",
        "Elegir platos, ajustar cantidades y cargar observaciones para cocina.",
    )

    menu = obtener_menu()
    if not menu:
        st.error("No hay productos activos en el menu.")
        return

    left, right = st.columns([1.7, 1], gap="large")

    with left:
        busqueda = st.text_input(
            "Buscar plato o bebida",
            key="menu_search",
            placeholder="Ej: milanesa, vino, postre...",
        ).strip().lower()

        categorias = [(c, c) for c in CATEGORIAS_MENU + ["cocina", "bebidas"]]
        tabs = st.tabs([label for _, label in categorias])
        for tab, (cat_key, _cat_label) in zip(tabs, categorias):
            with tab:
                productos = [p for p in menu if p["categoria"] == cat_key]
                if busqueda:
                    productos = [p for p in productos if busqueda in p["nombre"].lower()]
                if not productos:
                    st.caption("Sin productos para este filtro.")
                    continue
                for producto in productos:
                    render_producto(producto)

    with right:
        total_items, total = render_carrito(menu)
        st.divider()
        if st.button(
            "Enviar pedido a cocina",
            type="primary",
            use_container_width=True,
            disabled=total_items == 0,
        ):
            try:
                id_pedido = crear_pedido(
                    mesa["id_mesa"],
                    st.session_state.mozo["id"],
                    st.session_state.cart,
                )
                st.session_state.success_msg = (
                    f"Pedido #{id_pedido} enviado a cocina. "
                    f"Mesa {mesa['numero_mesa']} - total {money(total)}."
                )
                volver_a_mesas()
                st.rerun()
            except Exception as exc:
                st.error(f"No se pudo crear el pedido: {exc}")

        if st.button("Vaciar pedido", use_container_width=True, disabled=total_items == 0):
            st.session_state.cart = {}
            st.rerun()
        if st.button("Volver a mesas", use_container_width=True):
            volver_a_mesas()
            st.rerun()


inject_styles()
init_session()

if st.session_state.step == "mozo":
    pantalla_mozo()
elif st.session_state.step == "mesa":
    pantalla_mesas()
elif st.session_state.step == "pedido":
    pantalla_pedido()
else:
    reset_all()
    st.rerun()
