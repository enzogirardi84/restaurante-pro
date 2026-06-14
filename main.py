"""
main.py - Enrutador maestro de COMANDAPRO ERP.
Soporta auto-pedido por QR (?mesa=X), login y sidebar multi-rol.
"""
from __future__ import annotations

import hashlib
import importlib

import streamlit as st
from components.estilos import inyectar_css_global
from database import get_connection_direct, init_db

st.set_page_config(
    page_title="COMANDAPRO ERP",
    page_icon="🍽",
    layout="wide",
    initial_sidebar_state="expanded",
)

inyectar_css_global()

VIEWS = {
    "mozo": {"label": "Mozo", "module": "views.mozo"},
    "cocina": {"label": "Cocina (KDS)", "module": "views.cocina"},
    "caja": {"label": "Caja", "module": "views.caja"},
    "dashboard": {"label": "Dashboard", "module": "views.dashboard"},
    "autopedido": {"label": "Auto-pedido QR", "module": "views.autopedido"},
}

ROLE_DEFAULT_VIEW = {
    "administrador": "dashboard",
    "admin": "dashboard",
    "mozo": "mozo",
    "cocina": "cocina",
    "caja": "caja",
}

ROLE_VIEWS = {
    "administrador": ["dashboard", "mozo", "cocina", "caja"],
    "admin": ["dashboard", "mozo", "cocina", "caja"],
    "mozo": ["mozo"],
    "cocina": ["cocina"],
    "caja": ["caja"],
}


def _detectar_qr() -> bool:
    mesa_str = st.query_params.get("mesa")
    if mesa_str is None:
        return False
    try:
        mesa_id = int(mesa_str)
    except (ValueError, TypeError):
        return False

    st.session_state.auth_role = "autopedido"
    st.session_state.active_view = "autopedido"
    st.session_state.role = "autopedido"
    st.session_state.mesa_auto = mesa_id
    st.session_state.qr_mode = True
    return True


def login_screen() -> None:
    st.markdown(
        "<h1 style='text-align:center;padding-top:3rem'>COMANDAPRO ERP</h1>"
        "<p style='text-align:center;color:#666'>Sistema de Gestion Gastronomica</p>",
        unsafe_allow_html=True,
    )

    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        with st.container(border=True):
            st.markdown("### Iniciar sesion")
            username = st.text_input("Usuario", placeholder="ej: admin", key="login_user")
            password = st.text_input("Contrasena", type="password", placeholder="••••", key="login_pass")

            if st.button("Entrar", type="primary", use_container_width=True):
                if not username or not password:
                    st.error("Completa ambos campos.")
                else:
                    _autenticar(username, password)


def _autenticar(username: str, password: str) -> None:
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = get_connection_direct()
    try:
        import config

        if config.DB_ENGINE == "postgresql":
            cur = conn.execute(
                "SELECT id_usuario, nombre, apellido, rol FROM usuarios WHERE username=%s AND password_hash=%s",
                (username, password_hash),
            )
        else:
            cur = conn.execute(
                "SELECT id_usuario, nombre, apellido, rol FROM usuarios WHERE username=? AND password_hash=?",
                (username, password_hash),
            )
        user = cur.fetchone()
    finally:
        conn.close()

    if not user:
        st.error("Usuario o contrasena incorrectos.")
        return

    auth_role = str(user["rol"])
    default_view = ROLE_DEFAULT_VIEW.get(auth_role, auth_role)
    st.session_state.auth_role = auth_role
    st.session_state.active_view = default_view
    st.session_state.role = default_view
    st.session_state.qr_mode = False
    st.session_state.user_name = f"{user['nombre']} {user['apellido']}"
    st.rerun()


def _allowed_views() -> list[str]:
    auth_role = st.session_state.get("auth_role") or st.session_state.get("role")
    return ROLE_VIEWS.get(auth_role, [ROLE_DEFAULT_VIEW.get(auth_role, auth_role)])


def sidebar_nav() -> None:
    if st.session_state.get("qr_mode"):
        return

    allowed = [view for view in _allowed_views() if view in VIEWS]
    if not allowed:
        allowed = ["dashboard"]

    active = st.session_state.get("active_view") or st.session_state.get("role") or allowed[0]
    if active not in allowed:
        active = allowed[0]
        st.session_state.active_view = active
        st.session_state.role = active

    with st.sidebar:
        name = st.session_state.get("user_name", "Usuario")
        auth_role = st.session_state.get("auth_role", "")
        st.markdown(f"### {name}")
        if auth_role:
            st.caption(f"Rol: {auth_role}")
        st.markdown("---")

        if len(allowed) > 1:
            labels = {view: VIEWS[view]["label"] for view in allowed}
            selected_label = st.radio(
                "Modulo",
                [labels[view] for view in allowed],
                index=allowed.index(active),
                key="sidebar_view_label",
            )
            selected = next(view for view, label in labels.items() if label == selected_label)
            if selected != active:
                st.session_state.active_view = selected
                st.session_state.role = selected
                st.rerun()
        else:
            st.markdown(f"**Modulo:** {VIEWS[allowed[0]]['label']}")

        st.markdown("---")
        if st.button("Cerrar sesion", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        st.markdown("---")
        st.caption("COMANDAPRO ERP")


def _render_active_view() -> None:
    role = st.session_state.get("active_view") or st.session_state.get("role")
    st.session_state.role = role
    info = VIEWS.get(role)
    if not info:
        st.error(f"Rol desconocido: {role}")
        return

    try:
        mod = importlib.import_module(info["module"])
        mod.render()
    except ImportError as exc:
        st.error(f"No se pudo cargar la vista '{info['module']}': {exc}")
    except Exception as exc:
        st.error(f"Error en la vista: {exc}")


if "db_ready" not in st.session_state:
    result = init_db()
    if not result.get("ok"):
        st.error(f"Error al iniciar la base de datos: {result.get('error')}")
        st.stop()
    st.session_state.db_ready = True

if _detectar_qr():
    pass
elif "active_view" not in st.session_state and "role" not in st.session_state:
    login_screen()
    st.stop()

sidebar_nav()
_render_active_view()
