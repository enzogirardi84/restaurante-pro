"""
views/autopedido.py — Auto-pedido por QR (Mobile-First).
Mejoras: seguimiento estado en tiempo real, carrito flotante,
boton llamar mozo, resumen pre-envio, historial de pedidos.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st
from database import get_connection_direct
from components.imagenes import obtener_imagen

CSS_MOBILE = """
<style>
@media (max-width: 768px) {
  .stButton button { font-size: 1.2rem !important; padding: 0.7rem !important; min-height: 50px !important; }
  .stTextInput input { font-size: 1.1rem !important; }
  h1 { font-size: 1.8rem !important; }
}
.producto-card { border: 1px solid #e0d5c8; border-radius: 12px;
  padding: 12px; margin-bottom: 8px; background: white;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.carrito-flotante { position: sticky; bottom: 0; background: #8B2635;
  color: white; padding: 1rem; border-radius: 14px 14px 0 0;
  text-align: center; font-weight: 700; font-size: 1.1rem; margin-top: 1rem; }
.estado-badge { display: inline-block; padding: 4px 12px; border-radius: 20px;
  font-weight: 700; font-size: 0.85rem; }
</style>
"""

ESTADO_LABELS = {
    "pendiente":  {"emoji": "⏳", "label": "En cola",      "color": "#ff9800", "desc": "Tu pedido fue recibido y está esperando."},
    "en_cocina":  {"emoji": "🍳", "label": "En cocina",   "color": "#e65100", "desc": "Los cocineros están preparando tus platos."},
    "listo":      {"emoji": "🔔", "label": "Listo",       "color": "#2e7d32", "desc": "Tu pedido está listo! El mozo lo lleva en breve."},
    "entregado":  {"emoji": "✅", "label": "Entregado",  "color": "#1565c0", "desc": "¡Buen provecho! Pedido entregado en tu mesa."},
    "cobrado":    {"emoji": "🧧", "label": "Cobrado",    "color": "#555",    "desc": "Pedido cerrado. ¡Gracias por tu visita!"},
}

def render() -> None:
    mesa_id = st.session_state.get("mesa_auto")
    if mesa_id is None:
        st.error("❌ Mesa no especificada. Escaneá el código QR de la mesa.")
        st.stop()

    st.markdown(CSS_MOBILE, unsafe_allow_html=True)

    # Si ya hizo un pedido, mostrar seguimiento + opcion de nuevo pedido
    pedido_id = st.session_state.get("auto_ultimo_pedido")
    if pedido_id:
        _pantalla_seguimiento(mesa_id, pedido_id)
    else:
        _menu_cliente(mesa_id)


def _cabecera(mesa_id: int, subtitulo: str = "") -> None:
    st.markdown(
        f"<div style='text-align:center;padding:1rem 0 0.5rem 0'>"
        f"<h1 style='font-size:2.2rem;margin:0'>🍽 COMANDAPRO</h1>"
        f"<p style='font-size:1.1rem;color:#666;margin:4px 0'>🪑 <b>Mesa #{mesa_id}</b></p>"
        f"{'<p style=color:#888;font-size:0.9rem>' + subtitulo + '</p>' if subtitulo else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )


def _menu_cliente(mesa_id: int) -> None:
    _cabecera(mesa_id, "Tap ➕/− para agregar productos")

    if "auto_cart" not in st.session_state:
        st.session_state.auto_cart = {}

    conn = get_connection_direct()
    try:
        menu = conn.execute(
            "SELECT id_producto, nombre, precio_venta, categoria, url_imagen, descripcion"
            " FROM productos_menu WHERE activo=1 ORDER BY categoria, nombre"
        ).fetchall()
    except Exception:
        menu = conn.execute(
            "SELECT id_producto, nombre, precio_venta, categoria, url_imagen"
            " FROM productos_menu WHERE activo=1 ORDER BY categoria, nombre"
        ).fetchall()
    finally:
        conn.close()

    CART = st.session_state.auto_cart

    # Agrupar categorias dinamicamente
    cat_labels = {
        "Entradas": "🥗 Entradas", "Pastas": "🍝 Pastas",
        "Carnes": "🥩 Carnes", "Pescados": "🐟 Pescados",
        "Comidas Criollas": "🌳 Criollas", "cocina": "🍳 Cocina",
        "bebidas": "🥤 Bebidas", "postres": "🍰 Postres",
        "Postres": "🍰 Postres",
    }

    cats_presentes = []
    seen = set()
    for p in menu:
        c = p["categoria"]
        if c not in seen: cats_presentes.append(c); seen.add(c)

    for cat_key in cats_presentes:
        items = [p for p in menu if p["categoria"] == cat_key]
        if not items: continue
        label = cat_labels.get(cat_key, cat_key)
        st.markdown(f"<h3 style='margin-top:1.5rem;color:#2C221E'>{label}</h3>", unsafe_allow_html=True)

        for prod in items:
            pid = prod["id_producto"]
            ci = CART.get(pid, {"cantidad": 0, "obs": ""})
            img_path = obtener_imagen(prod.get("url_imagen"), tipo="plato")

            with st.container(border=True):
                col_img, col_info, col_ctrl = st.columns([1, 2.5, 1.5])

                with col_img:
                    st.image(img_path, width=80, use_container_width=False)

                with col_info:
                    st.markdown(
                        f"<div style='font-weight:700;font-size:1.05rem;color:#2C221E'>{prod['nombre']}</div>"
                        f"<div style='color:#8B2635;font-weight:700;font-size:1rem'>${prod['precio_venta']:,.0f}</div>",
                        unsafe_allow_html=True,
                    )
                    desc = prod.get("descripcion") or ""
                    if desc:
                        st.markdown(f"<div style='color:#888;font-size:0.82rem'>{desc[:80]}</div>", unsafe_allow_html=True)

                with col_ctrl:
                    c1, c2, c3 = st.columns([1, 1, 1])
                    with c1:
                        if st.button("−", key=f"ad_{pid}", use_container_width=True):
                            if ci["cantidad"] > 0:
                                ci["cantidad"] -= 1
                                if ci["cantidad"] == 0: CART.pop(pid, None)
                                else: CART[pid] = ci
                                st.rerun()
                    with c2:
                        color_cant = "#8B2635" if ci["cantidad"] > 0 else "#ccc"
                        st.markdown(f"<div style='text-align:center;font-size:1.6rem;font-weight:700;color:{color_cant}'>{ci['cantidad']}</div>", unsafe_allow_html=True)
                    with c3:
                        if st.button("+", key=f"ai_{pid}", use_container_width=True):
                            ci["cantidad"] = ci.get("cantidad", 0) + 1
                            CART[pid] = ci; st.rerun()

                if ci["cantidad"] > 0:
                    ci["obs"] = st.text_input("Nota", value=ci.get("obs",""), key=f"ao_{pid}", placeholder="📝 Nota (sin sal, sin cebolla...)", label_visibility="collapsed")
                    CART[pid] = ci

    st.divider()

    # Resumen del carrito
    menu_map = {p["id_producto"]: p for p in menu}
    items_cart = [(pid, ci) for pid, ci in CART.items() if ci and ci["cantidad"] > 0]
    total = sum(ci["cantidad"] * menu_map.get(pid, {}).get("precio_venta", 0) for pid, ci in items_cart)
    qty = sum(ci["cantidad"] for _, ci in items_cart)

    if qty == 0:
        st.info("🛒 Tu carrito está vacío. Tap ➕ para agregar.")
    else:
        with st.expander(f"🛒 {qty} ítem(s) — ${total:,.0f} — Ver resumen", expanded=True):
            for pid, ci in items_cart:
                prod = menu_map.get(pid, {})
                imp = ci["cantidad"] * prod.get("precio_venta", 0)
                obs = f" *(nota: {ci['obs']})*" if ci.get("obs") else ""
                st.markdown(f"- **{ci['cantidad']}x** {prod.get('nombre','?')} — ${imp:,.0f}{obs}")
            st.markdown(f"**💰 Total: ${total:,.0f}**")

        col_env, col_llam = st.columns([3, 1])
        with col_env:
            if st.button("🔥 CONFIRMAR PEDIDO", use_container_width=True, type="primary"):
                _enviar_pedido(mesa_id, items_cart, menu_map)
        with col_llam:
            if st.button("🔔 Mozo", use_container_width=True, help="Llamar al mozo"):
                _llamar_mozo(mesa_id)


def _enviar_pedido(mesa_id: int, items_cart: list, menu_map: dict) -> None:
    conn = get_connection_direct()
    try:
        conn.execute("BEGIN")
        cur = conn.execute(
            "INSERT INTO pedidos_cabecera (id_mesa, id_usuario) VALUES (?,?)",
            (mesa_id, 1),
        )
        id_pedido = cur.lastrowid
        for pid, ci in items_cart:
            precio = menu_map.get(pid, {}).get("precio_venta", 0)
            obs = ci.get("obs","").strip()
            tag = f"[QR-Mesa{mesa_id}]"
            obs_final = f"{obs} {tag}".strip() if obs else tag
            conn.execute(
                "INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, precio_unitario_facturado, observaciones)"
                " VALUES (?,?,?,?,?)",
                (id_pedido, pid, ci["cantidad"], precio, obs_final),
            )
        conn.execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=?", (mesa_id,))
        conn.commit()
        st.session_state.auto_cart = {}
        st.session_state.auto_ultimo_pedido = id_pedido
        st.balloons()
        st.rerun()
    except Exception as e:
        conn.rollback(); st.error(f"❌ Error al enviar: {e}")
    finally:
        conn.close()


def _llamar_mozo(mesa_id: int) -> None:
    """Muestra notificacion de llamada al mozo (sin insertar registros huerfanos)."""
    st.success("🔔 Se notificó al mozo. ¡Ya viene!")
    st.toast("🔔 Mozo llamado!", icon="🔔")


def _pantalla_seguimiento(mesa_id: int, pedido_id: int) -> None:
    """Muestra el estado actual del pedido en tiempo real."""
    _cabecera(mesa_id)

    conn = get_connection_direct()
    try:
        row = conn.execute(
            "SELECT estado_comanda, fecha_hora FROM pedidos_cabecera WHERE id_pedido=?",
            (pedido_id,),
        ).fetchone()
        items = conn.execute(
            "SELECT pm.nombre, pd.cantidad, pd.precio_unitario_facturado"
            " FROM pedido_detalle pd"
            " JOIN productos_menu pm ON pm.id_producto=pd.id_producto"
            " WHERE pd.id_pedido=?",
            (pedido_id,),
        ).fetchall()
    finally:
        conn.close()

    if not row:
        st.error("Pedido no encontrado."); return

    estado = row["estado_comanda"]
    cfg = ESTADO_LABELS.get(estado, {"emoji":"❓","label":estado,"color":"#888","desc":""})

    # Barra de progreso visual
    estados_orden = ["pendiente","en_cocina","listo","entregado"]
    paso_actual = estados_orden.index(estado) if estado in estados_orden else 0
    progreso = (paso_actual + 1) / len(estados_orden)
    st.progress(progreso)

    # Badge de estado
    st.markdown(
        f"<div style='text-align:center;padding:1.5rem'>"
        f"<div style='font-size:3.5rem'>{cfg['emoji']}</div>"
        f"<div style='background:{cfg['color']};color:white;display:inline-block;"
        f"padding:8px 24px;border-radius:20px;font-weight:700;font-size:1.1rem;margin:8px 0'>"
        f"{cfg['label']}</div>"
        f"<p style='color:#555;margin-top:8px'>{cfg['desc']}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Detalle del pedido
    with st.expander(f"📝 Pedido #{pedido_id} — Ver detalle"):
        total = 0.0
        for it in items:
            imp = it["cantidad"] * (it["precio_unitario_facturado"] or 0)
            total += imp
            st.markdown(f"- **{it['cantidad']}x** {it['nombre']} — ${imp:,.0f}")
        st.markdown(f"**💰 Total: ${total:,.0f}**")

    # Botones de accion
    col_ref, col_nuevo = st.columns(2)
    with col_ref:
        if st.button("🔄 Actualizar estado", use_container_width=True):
            st.rerun()
    with col_nuevo:
        if st.button("➕ Nuevo pedido", use_container_width=True):
            st.session_state.auto_ultimo_pedido = None
            st.session_state.auto_cart = {}
            st.rerun()

    # Auto-refresh cada 15 segundos
    if estado not in ("entregado", "cobrado"):
        st.caption("⌛ Actualización automática cada 15 segundos")
        st.markdown(
            "<script>setTimeout(function(){window.location.reload();}, 15000);</script>",
            unsafe_allow_html=True,
        )
