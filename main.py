"""
main.py — Enrutador maestro de COMANDAPRO ERP.
Soporta auto-pedido por QR (?mesa=X) y login por usuario/contraseña.
"""
from __future__ import annotations

import hashlib
import streamlit as st

from database import init_db, get_connection_direct
from components.estilos import inyectar_css_global

st.set_page_config(
    page_title="COMANDAPRO ERP",
    page_icon="🍽",
    layout="wide",
    initial_sidebar_state="expanded",
)

inyectar_css_global()

VIEWS = {
    "mozo":       {"label": "👨‍🍳  Mozo",             "module": "views.mozo"},
    "cocina":     {"label": "👨‍🍳  Cocina (KDS)",      "module": "views.cocina"},
    "caja":       {"label": "🧾  Caja",                "module": "views.caja"},
    "dashboard":  {"label": "📊  Dashboard",           "module": "views.dashboard"},
    "autopedido": {"label": "🍽  Auto-pedido QR",      "module": "views.autopedido"},
}


# ── Detectar QR ───────────────────────────────────────────────────────

def _detectar_qr() -> bool:
    params = st.query_params
    mesa_str = params.get("mesa")
    if mesa_str is None:
        return False
    try:
        mesa_id = int(mesa_str)
    except (ValueError, TypeError):
        return False
    st.session_state.role = "autopedido"
    st.session_state.mesa_auto = mesa_id
    st.session_state.qr_mode = True
    return True


# ── Login ─────────────────────────────────────────────────────────────

def login_screen() -> None:
    st.markdown(
        "<h1 style='text-align:center;padding-top:3rem'>🍽  COMANDAPRO ERP</h1>"
        "<p style='text-align:center;color:#666'>Sistema de Gestión Gastronómica</p>",
        unsafe_allow_html=True,
    )

    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        with st.container(border=True):
            st.markdown("### 🔐  Iniciar sesión")
            username = st.text_input("Usuario", placeholder="ej: admin", key="login_user")
            password = st.text_input("Contraseña", type="password", placeholder="••••", key="login_pass")

            if st.button("Entrar", type="primary", use_container_width=True):
                if not username or not password:
                    st.error("Completá ambos campos.")
                else:
                    _autenticar(username, password)


def _autenticar(username: str, password: str) -> None:
    ph = hashlib.sha256(password.encode()).hexdigest()
    conn = get_connection_direct()
    try:
        import config
        if config.DB_ENGINE == "postgresql":
            cur = conn.execute(
                "SELECT id_usuario, nombre, apellido, rol FROM usuarios WHERE username=%s AND password_hash=%s",
                (username, ph)
            )
        else:
            cur = conn.execute(
                "SELECT id_usuario, nombre, apellido, rol FROM usuarios WHERE username=? AND password_hash=?",
                (username, ph)
            )
        user = cur.fetchone()
    finally:
        conn.close()

    if not user:
        st.error("Usuario o contraseña incorrectos.")
        return

    role = user["rol"]
    if role == "cocina":
        role_key = "cocina"
    elif role == "administrador":
        role_key = "dashboard"
    else:
        role_key = role  # mozo

    st.session_state.role = role_key
    st.session_state.qr_mode = False
    st.session_state.user_name = f"{user['nombre']} {user['apellido']}"
    st.rerun()


def sidebar_nav() -> None:
    if st.session_state.get("qr_mode"):
        return

    with st.sidebar:
        role = st.session_state.role
        info = VIEWS.get(role, {})
        name = st.session_state.get("user_name", info.get("label", role))
        st.markdown(f"### 👤 {name}")
        st.markdown("---")

        if st.button("🔙  Cerrar sesión", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        st.markdown("---")
        st.caption("COMANDAPRO ERP")


# ── Arranque ──────────────────────────────────────────────────────────

# FIX: init_db solo se ejecuta una vez por sesión, no en cada rerun
if "db_ready" not in st.session_state:
    result = init_db()
    if not result.get("ok"):
        st.error(f"Error al iniciar la base de datos: {result.get('error')}")
        st.stop()
    st.session_state.db_ready = True

if _detectar_qr():
    pass
elif "role" not in st.session_state:
    login_screen()
    st.stop()

sidebar_nav()

role = st.session_state.role
info = VIEWS.get(role)
if info:
    import importlib
    try:
        mod = importlib.import_module(info["module"])
        mod.render()
    except ImportError as e:
        st.error(f"No se pudo cargar la vista '{info['module']}': {e}")
    except Exception as e:
        st.error(f"Error en la vista: {e}")
else:
    st.error(f"Rol desconocido: {role}")
