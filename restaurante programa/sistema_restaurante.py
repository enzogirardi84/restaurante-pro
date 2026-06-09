# -*- coding: utf-8 -*-
"""
Sistema principal de gestion gastronomica.

Incluye: login por PIN, terminal de mozo, cocina, caja, reportes,
administracion de menu, mesas, inventario y backups.
"""
from __future__ import annotations

import os
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import streamlit as st

from access_utils import (
    DEFAULT_SYSTEM_ACCESSES,
    access_password_error,
    default_system_access_rows,
    normalize_access_username,
    recovery_system_access,
    validate_default_system_access,
)
from cash_utils import (
    can_charge_table,
    cash_change_due,
    cash_close_requires_note,
    cash_difference,
    cash_difference_label,
    cash_expected,
)
from database import (
    DB_PATH,
    avanzar_estado,
    get_connection,
    init_db,
    marcar_pedido_entregado,
    obtener_pedidos_por_estado,
    procesar_cola_sincronizacion,
    registrar_auditoria,
    using_postgres,
)
from cloud_config import app_name, cloud_status, database_url_warnings, default_service_percentage, masked_status_table, normalized_database_url
from components.css import inject_styles, offline_banner, terminal_mode_styles, title, stat_card, auto_refresh
from kitchen_utils import kitchen_auto_refresh_seconds
from order_utils import normalize_order_cart
from permission_utils import modules_for_role
from security import hash_password, is_password_hash, login_logo_tag, verify_password

# Nuevos módulos
from components.proveedores_utils import page_gestion_proveedores
from components.promociones_utils import page_promociones
from components.turnos_utils import page_gestion_turnos, widget_check_in_out
from components.facturacion_electronica import page_facturacion_electronica
from views.backups import page_backups, hacer_backup_ahora
from views.mesas import page_mesas
from views.sistema import page_sistema
from utils.pdf_generator import data_table, date_fmt, generate_pdf, money as pdf_money


APP_TITLE = app_name("Restaurante Pro")
APP_VERSION = "2026.06.08"
SERVICIO_PORCENTAJE = default_service_percentage(10)
BACKUP_DIR = Path(__file__).parent / "backups"
SYSTEM_USERNAME = "anahigilardi"
SYSTEM_PASSWORD = "1999"
LEGACY_SYSTEM_USERNAME = "sistema"
LEGACY_SYSTEM_PASSWORD = "restaurante"
LEGACY_ADMIN_USERNAME = "admin"
LEGACY_ADMIN_PASSWORD = "admin"
AUTO_TERMINALS = {
    "mozo": "Mozo",
    "cocina": "Cocina",
    "caja": "Caja",
    "panel": "Panel",
}


st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="expanded")


@st.cache_resource(show_spinner=False)
def bootstrap_database_once() -> str:
    init_db()
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def bootstrap_database() -> None:
    try:
        bootstrap_database_once()
    except Exception as exc:
        import warnings as _w
        _w.warn(f"Supabase no disponible ({type(exc).__name__}). Usando SQLite local.")
        st.warning(
            "Supabase no disponible. La app opera en modo local SQLite. "
            "Los datos se sincronizaran cuando la conexion se restablezca."
        )
        with st.expander("Detalle tecnico", expanded=False):
            st.caption(f"Error: {type(exc).__name__}")
            if str(exc):
                st.caption(str(exc)[:200])

def app_build_label() -> str:
    sha = os.environ.get("GITHUB_SHA", "").strip()
    return sha[:7] if sha else APP_VERSION


def set_system_state(clave: str, valor: str) -> None:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO sistema_estado (clave, valor, actualizado_en)
            VALUES (?, ?, datetime('now','localtime'))
            ON CONFLICT(clave) DO UPDATE
            SET valor = excluded.valor,
                actualizado_en = datetime('now','localtime')
        """, (clave, valor))
        conn.commit()
    finally:
        conn.close()


@st.cache_resource(show_spinner=False)
def register_app_boot_once() -> str:
    try:
        boot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_connection()
        try:
            for clave, valor in [
                ("app_name", APP_TITLE),
                ("app_version", app_build_label()),
                ("db_mode", "supabase" if using_postgres() else "sqlite"),
                ("last_boot", boot_time),
            ]:
                conn.execute("""
                    INSERT INTO sistema_estado (clave, valor, actualizado_en)
                    VALUES (?, ?, datetime('now','localtime'))
                    ON CONFLICT(clave) DO UPDATE
                    SET valor = excluded.valor,
                        actualizado_en = datetime('now','localtime')
                """, (clave, valor))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return ""
    return boot_time


# ── Bloque anti-contenedor efimero ─────────────────────────────────────
def _asegurar_sqlite_local():
    """Si el .db local esta vacio o no existe, lo clona desde Supabase.
    Resuelve la perdida total de datos en Streamlit Cloud cuando el
    contenedor se reinicia tras inactividad o commit."""
    pg_url = normalized_database_url()
    if not pg_url:
        return
    if not DB_PATH.exists() or DB_PATH.stat().st_size < 4096:
        necesita = True
    else:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cur = conn.execute("SELECT COUNT(*) AS cnt FROM usuarios")
            necesita = cur.fetchone()[0] == 0
            conn.close()
        except Exception:
            necesita = True
    if not necesita:
        return
    import warnings as _w
    _w.warn("SQLite local vacio. Restaurando desde Supabase...")
    try:
        import psycopg2
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        pg_conn = psycopg2.connect(pg_url)
        pg_cur = pg_conn.cursor()
        pg_cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
        tablas = [r[0] for r in pg_cur.fetchall()]
        sl_conn = sqlite3.connect(str(DB_PATH))
        sl_conn.execute("PRAGMA foreign_keys=OFF")
        for tabla in tablas:
            if tabla.startswith("_"):
                continue
            try:
                pg_cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (tabla,))
                cols = [r[0] for r in pg_cur.fetchall()]
                if not cols:
                    continue
                pg_cur.execute(f'SELECT * FROM "{tabla}"')
                filas = pg_cur.fetchall()
                if not filas:
                    continue
                sl_conn.execute(f'DROP TABLE IF EXISTS "{tabla}"')
                sl_conn.execute(f'CREATE TABLE "{tabla}" ({", ".join(f'"{c}"' for c in cols)})')
                ph = ", ".join("?" for _ in cols)
                cn = ", ".join(f'"{c}"' for c in cols)
                for fila in filas:
                    try:
                        sl_conn.execute(f'INSERT INTO "{tabla}" ({cn}) VALUES ({ph})', fila)
                    except Exception:
                        pass
                sl_conn.commit()
            except Exception:
                continue
        sl_conn.execute("PRAGMA foreign_keys=ON")
        sl_conn.close()
        pg_conn.close()
        _w.warn(f"SQLite restaurado desde Supabase ({len(tablas)} tablas).")
    except Exception as exc:
        _w.warn(f"No se pudo restaurar SQLite: {exc}")

# ── Arranque de bases de datos ─────────────────────────────────────────
# _asegurar_sqlite_local se movio a database.py: se ejecuta dentro de init_db()
# para evitar pantalla en blanco por restore bloqueante a nivel modulo.
bootstrap_database()
register_app_boot_once()




def keep_sidebar_open() -> None:
    st.markdown(
        """
        <script>
        (function sidebarInit() {
            var doc = window.parent.document;
            if (!doc.getElementById('_rmCollapseStyle')) {
                var s = doc.createElement('style');
                s.id = '_rmCollapseStyle';
                s.textContent = '[data-testid="collapsedControl"],' +
                    '[data-testid="collapsedControl"] [data-testid="stIconMaterial"] {' +
                    'display:none !important;visibility:hidden !important;' +
                    'width:0 !important;height:0 !important;overflow:hidden !important;' +
                    'pointer-events:none !important;opacity:0 !important;}';
                doc.head.appendChild(s);
            }
            function hideCollapseBtn() {
                var btn = doc.querySelector('[data-testid="collapsedControl"]');
                if (btn) btn.style.display = 'none';
            }
            hideCollapseBtn();
            new MutationObserver(hideCollapseBtn).observe(doc.body, { childList: true, subtree: true });
            if (!window._sidebarInitialized) {
                window._sidebarInitialized = true;
                var isMobile = window.innerWidth < 768;
                var url = new URL(window.location);
                if (isMobile && !url.searchParams.has('mobile')) {
                    url.searchParams.set('mobile', '1');
                    window.location.replace(url.toString());
                } else if (!isMobile && !url.searchParams.has('mobile')) {
                    url.searchParams.set('mobile', '0');
                    window.location.replace(url.toString());
                }
            }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


def money(value: float | int | None) -> str:
    value = value or 0
    return f"${value:,.0f}".replace(",", ".")


def precio_producto_html(producto: dict) -> str:
    precio_final = float(producto.get("precio_final", producto["precio_venta"]))
    precio_original = float(producto["precio_venta"])
    if producto.get("descuento_aplicado", 0):
        return f"{money(precio_final)} <span class='muted'><s>{money(precio_original)}</s></span>"
    return money(precio_final)


def query_value(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value or default


def system_user() -> dict:
    user = one("""
        SELECT id_usuario, nombre, apellido, rol, pin
        FROM usuarios
        WHERE rol IN ('dueno', 'administrador')
        ORDER BY id_usuario
        LIMIT 1
    """)
    if user:
        return user
    return {"id_usuario": 1, "nombre": "Sistema", "apellido": "General", "rol": "administrador", "pin": ""}


def apply_terminal_autologin() -> None:
    terminal = query_value("terminal").lower().strip()
    if terminal in AUTO_TERMINALS and st.session_state.get("usuario") is None:
        st.session_state.usuario = system_user()
        st.session_state.modulo = AUTO_TERMINALS[terminal]
        st.session_state.terminal_lock = AUTO_TERMINALS[terminal]
        registrar_auditoria("login", "terminal_auto", terminal)




def rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception as _ex:
        st.error(f"Error BD: {type(_ex).__name__}: {_ex}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def one(sql: str, params: tuple = ()) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def execute(sql: str, params: tuple = ()) -> None:
    conn = get_connection()
    try:
        conn.execute(sql, params)
        try:
            conn.commit()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


@st.cache_data(ttl=120, show_spinner=False)
def config_values() -> dict[str, str]:
    try:
        return {
            str(row["clave"]): str(row["valor"])
            for row in rows("SELECT clave, valor FROM configuracion_sistema")
        }
    except Exception:
        return {}


def get_config(clave: str, default: str = "") -> str:
    return config_values().get(clave, default)


def set_config(clave: str, valor: str) -> None:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO configuracion_sistema (clave, valor)
            VALUES (?, ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor
        """, (clave, valor))
        conn.commit()
        config_values.clear()
    finally:
        conn.close()


def upsert_system_access(usuario: str, password_hash: str, rol: str = "administrador") -> None:
    ensure_system_access_schema()
    clean_user = normalize_access_username(usuario)
    if not clean_user:
        return
    conn = get_connection()
    try:
        try:
            conn.execute("""
                INSERT INTO accesos_sistema (usuario, password_hash, activo, rol)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(usuario) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    rol = excluded.rol,
                    activo = 1
            """, (clean_user, password_hash, rol))
        except Exception:
            conn.execute("""
                INSERT OR REPLACE INTO accesos_sistema (usuario, password_hash, activo, rol)
                VALUES (?, ?, 1, ?)
            """, (clean_user, password_hash, rol))
        conn.commit()
    finally:
        conn.close()


def ensure_system_access_schema() -> None:
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accesos_sistema (
                usuario TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1,
                rol TEXT NOT NULL DEFAULT 'administrador',
                creado_en TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                actualizado_en TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        for column_sql in [
            "ALTER TABLE accesos_sistema ADD COLUMN activo INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE accesos_sistema ADD COLUMN rol TEXT NOT NULL DEFAULT 'administrador'",
            "ALTER TABLE accesos_sistema ADD COLUMN creado_en TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))",
            "ALTER TABLE accesos_sistema ADD COLUMN actualizado_en TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))",
        ]:
            try:
                conn.execute(column_sql)
            except Exception:
                pass
        for usuario, password_hash in DEFAULT_SYSTEM_ACCESSES.items():
            try:
                conn.execute("""
                    INSERT INTO accesos_sistema (usuario, password_hash, activo, rol)
                    VALUES (?, ?, 1, 'administrador')
                    ON CONFLICT(usuario) DO NOTHING
                """, (usuario, password_hash))
            except Exception:
                conn.execute("""
                    INSERT OR IGNORE INTO accesos_sistema (usuario, password_hash, activo, rol)
                    VALUES (?, ?, 1, 'administrador')
                """, (usuario, password_hash))
        configured_user = normalize_access_username(get_config("usuario_sistema", SYSTEM_USERNAME))
        configured_password = get_config("password_sistema", SYSTEM_PASSWORD)
        if configured_user and configured_password:
            try:
                conn.execute("""
                    INSERT INTO accesos_sistema (usuario, password_hash, activo, rol)
                    VALUES (?, ?, 1, 'administrador')
                    ON CONFLICT(usuario) DO NOTHING
                """, (configured_user, configured_password))
            except Exception:
                conn.execute("""
                    INSERT OR IGNORE INTO accesos_sistema (usuario, password_hash, activo, rol)
                    VALUES (?, ?, 1, 'administrador')
                """, (configured_user, configured_password))
        conn.commit()
    finally:
        conn.close()


def system_access_rows() -> list[dict]:
    ensure_system_access_schema()
    return rows("""
        SELECT usuario,
               COALESCE(activo, 1) AS activo,
               rol,
               creado_en,
               actualizado_en
        FROM accesos_sistema
        ORDER BY usuario
    """)


def set_system_access_active(usuario: str, activo: bool) -> None:
    clean_user = normalize_access_username(usuario)
    if not clean_user:
        return
    ensure_system_access_schema()
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE accesos_sistema
               SET activo = ?,
                   actualizado_en = datetime('now','localtime')
             WHERE LOWER(usuario) = LOWER(?)
        """, (1 if activo else 0, clean_user))
        conn.commit()
    finally:
        conn.close()


def active_system_accesses() -> list[dict]:
    try:
        ensure_system_access_schema()
        return rows("""
            SELECT usuario
            FROM accesos_sistema
            WHERE activo = 1
            ORDER BY usuario
        """)
    except Exception:
        return default_system_access_rows()


def authenticate_system_access(usuario: str, password: str) -> str | None:
    clean_user = normalize_access_username(usuario)
    if not clean_user:
        return None

    default_access = validate_default_system_access(clean_user, password)
    if default_access:
        return default_access

    try:
        ensure_system_access_schema()
        access = one("""
            SELECT usuario, password_hash
            FROM accesos_sistema
            WHERE LOWER(usuario) = LOWER(?)
              AND activo = 1
            LIMIT 1
        """, (clean_user,))
        if access and verify_password(password, access["password_hash"]):
            return access["usuario"]
    except Exception:
        pass

    try:
        user_access = one("""
            SELECT mail, contrasena
            FROM usuarios
            WHERE LOWER(mail) = LOWER(?)
              AND COALESCE(activo, 1) = 1
            LIMIT 1
        """, (clean_user,))
        if user_access and verify_password(password, user_access["contrasena"]):
            return user_access["mail"]
    except Exception:
        pass

    usuario_sistema = get_config("usuario_sistema", SYSTEM_USERNAME)
    password_sistema = get_config("password_sistema", SYSTEM_PASSWORD)
    if clean_user == usuario_sistema.strip().lower() and verify_password(password, password_sistema):
        return usuario_sistema
    return None


def set_system_password(password: str) -> None:
    password_hash = hash_password(password)
    set_config("password_sistema", password_hash)
    upsert_system_access(get_config("usuario_sistema", SYSTEM_USERNAME), password_hash)


def system_password_is_default() -> bool:
    usuario = get_config("usuario_sistema", SYSTEM_USERNAME).strip().lower()
    stored = get_config("password_sistema", SYSTEM_PASSWORD)
    return (
        (usuario == LEGACY_SYSTEM_USERNAME and verify_password(LEGACY_SYSTEM_PASSWORD, stored))
        or (usuario == LEGACY_ADMIN_USERNAME and verify_password(LEGACY_ADMIN_PASSWORD, stored))
    )


def system_password_is_hashed() -> bool:
    return is_password_hash(get_config("password_sistema", SYSTEM_PASSWORD))


def restaurant_config() -> dict[str, str]:
    return {
        "nombre": get_config("restaurante_nombre", APP_TITLE),
        "direccion": get_config("restaurante_direccion", ""),
        "telefono": get_config("restaurante_telefono", ""),
        "identificacion": get_config("restaurante_identificacion", ""),
        "ticket_footer": get_config("ticket_footer", "Gracias por su visita."),
    }


def service_percentage() -> float:
    try:
        return max(float(get_config("servicio_porcentaje", str(SERVICIO_PORCENTAJE)) or 0), 0)
    except ValueError:
        return float(SERVICIO_PORCENTAJE)


def service_amount(subtotal: float) -> float:
    return round(float(subtotal) * service_percentage() / 100)


@st.cache_data(ttl=60, show_spinner=False)
def init_session() -> None:
    # Mobile detection via query param (set by JS on first load)
    mobile = st.query_params.get("mobile")
    if mobile is not None:
        st.query_params.clear()
    defaults = {
        "usuario": None,
        "modulo": "Mozo",
        "mesa_actual": None,
        "cart": {},
        "terminal_lock": None,
        "mozo_operativo_id": None,
        "ultimo_despachado": None,
        "mesa_caja_id": None,
        "medio_pago_caja": "Efectivo",
        "efectivo_recibido": 0.0,
        "force_password_change": False,
        "sidebar_collapsed": mobile == "1",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def start_recovery_admin_session(access_user: str = "anahigilardi") -> None:
    try:
        user = system_user()
    except Exception:
        user = {
            "id_usuario": 1,
            "nombre": "Anahi",
            "apellido": "Gilardi",
            "rol": "administrador",
            "pin": "",
        }
    user["rol"] = "administrador"
    st.session_state.usuario = user
    st.session_state.modulo = "Panel"
    st.session_state.terminal_lock = None
    try:
        st.session_state.force_password_change = system_password_is_default()
    except Exception:
        st.session_state.force_password_change = False
    try:
        registrar_auditoria("login", "recuperacion_admin", access_user)
    except Exception:
        pass
    st.rerun()


def login() -> None:
    usuario_sistema = get_config("usuario_sistema", SYSTEM_USERNAME)
    accesos = active_system_accesses()
    st.markdown(
        """
        <style>
            [data-testid="stAppViewContainer"] > .main {
                background: var(--color-pergamino) !important;
                font-family: 'Libre Caslon Text', serif !important;
            }
            [data-testid="stAppViewContainer"] > .main > .block-container {
                max-width: 420px !important;
                margin: 60px auto 0 !important;
                padding-top: 0 !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="login-header">
            <div class="login-badge">SISTEMA</div>
            <div class="login-title">Restaurante Pro</div>
            <div class="login-separator">\u2666</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("""<label class="login-label">USUARIO</label>""", unsafe_allow_html=True)
    usuario = st.text_input("", value="", placeholder="Ingrese su usuario", label_visibility="collapsed")
    st.markdown("""<label class="login-label">CONTRASEÑA</label>""", unsafe_allow_html=True)
    password = st.text_input("", type="password", placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022", label_visibility="collapsed")
    clean_login_user = normalize_access_username(usuario)
    clean_login_password = str(password or "").strip()
    recovery_user = recovery_system_access(clean_login_user, clean_login_password)
    login_pressed = st.button("INGRESAR \u2794", type="primary", use_container_width=True)
    recovery_pressed = st.button("ACCESO ADMINISTRADOR", use_container_width=True)
    if recovery_user or recovery_pressed:
        start_recovery_admin_session(recovery_user or "anahigilardi")
    if login_pressed:
        access_user = authenticate_system_access(usuario, password)
        if access_user:
            access_rol = "administrador"
            try:
                row = one("SELECT rol FROM accesos_sistema WHERE LOWER(usuario)=LOWER(?)", (access_user,))
                if row and row.get("rol"):
                    access_rol = row["rol"]
            except Exception:
                pass
            st.session_state.usuario = system_user()
            st.session_state.usuario["rol"] = access_rol
            st.session_state.modulo = "Panel"
            st.session_state.terminal_lock = None
            st.session_state.force_password_change = system_password_is_default()
            registrar_auditoria("login", "ingreso_sistema", access_user)
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")
    if system_password_is_default():
        st.warning("Hay un acceso anterior activo. Al ingresar, el sistema pedirá actualizarlo.")
    mostrar = ", ".join(str(a["usuario"]) for a in accesos) or usuario_sistema if accesos else "\u2014"
    st.markdown(
        f"""
        <div class="login-footer">
            <div class="footer-links">
                <a href="?terminal=mozo">Mozo</a> |
                <a href="?terminal=cocina">Cocina</a> |
                <a href="?terminal=caja">Caja</a>
            </div>
            <div class="active-users">
                \u25cf Usuarios activos: <strong>{mostrar}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def force_password_change_page() -> None:
    title("Cambiar acceso inicial", "Por seguridad, cambia la contrasena predeterminada antes de continuar.")
    st.warning("No uses accesos viejos como `sistema/restaurante` o `admin/admin` en una app publicada.")
    with st.form("cambio_obligatorio_password"):
        nueva = st.text_input("Nueva contrasena", type="password")
        confirmar = st.text_input("Confirmar nueva contrasena", type="password")
        if st.form_submit_button("Guardar y continuar", type="primary"):
            if len(nueva) < 8:
                st.error("La contrasena debe tener al menos 8 caracteres.")
            elif nueva != confirmar:
                st.error("Las contrasenas no coinciden.")
            elif nueva in {LEGACY_SYSTEM_PASSWORD, LEGACY_ADMIN_PASSWORD}:
                st.error("Elegi una contrasena diferente a la anterior.")
            else:
                set_system_password(nueva)
                st.session_state.force_password_change = False
                registrar_auditoria("seguridad", "password_inicial_cambiada", "sistema")
                st.success("Contrasena actualizada.")
                st.rerun()


def allowed_modules(user: dict) -> list[str]:
    return modules_for_role(user.get("rol", ""), st.session_state.get("terminal_lock"))


def sidebar() -> None:
    user = st.session_state.usuario
    # Botón colapsar — dentro del sidebar, alineado a la derecha
    col_spacer, col_btn = st.sidebar.columns([4, 1])
    with col_btn:
        if st.button("◀", key="btn_collapse", help="Ocultar panel"):
            st.session_state.sidebar_collapsed = True
            st.rerun()
    st.sidebar.markdown(
        f"""
        <div style="padding:0.4rem 0 0.9rem;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:0.7rem">
            <div style="font-size:1.05rem;font-weight:850;color:white;letter-spacing:-0.02em">{APP_TITLE}</div>
            <div style="margin-top:0.5rem;padding:0.55rem 0.6rem;border:1px solid rgba(255,255,255,0.1);border-radius:8px;background:rgba(255,255,255,0.03)">
                <div style="font-weight:700;color:#f0ece4;font-size:0.92rem">{escape(user['nombre'])} {escape(user['apellido'])}</div>
                <div style="font-size:0.78rem;color:#b8b0a4;text-transform:capitalize;margin-top:0.1rem">{escape(user['rol'])}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    opciones = allowed_modules(user)
    if not opciones:
        st.sidebar.error("Rol sin permisos configurados.")
        return
    if st.session_state.modulo not in opciones:
        st.session_state.modulo = opciones[0]
    for opt in opciones:
        activo = opt == st.session_state.modulo
        clase = "primary" if activo else "secondary"
        if st.sidebar.button(opt, key=f"nav_{opt}", type=clase, use_container_width=True):
            st.session_state.modulo = opt
            st.session_state.sidebar_collapsed = True
            st.rerun()
    st.sidebar.divider()
    widget_check_in_out()
    st.sidebar.divider()
    if st.session_state.get("terminal_lock"):
        st.sidebar.caption("Terminal automatico")
    elif st.sidebar.button("Cerrar sesion", use_container_width=True):
        registrar_auditoria("login", "salida", str(user["id_usuario"]))
        st.session_state.clear()
        st.rerun()


def get_menu(active_only: bool = True) -> list[dict]:
    where = "WHERE activo = 1" if active_only else ""
    productos = rows(f"""
        SELECT id_producto, nombre, precio_venta, categoria, activo
        FROM productos_menu
        {where}
        ORDER BY categoria, nombre
    """)
    if not productos:
        from database import seed_menu_premium
        _antes = rows("SELECT COUNT(*) AS cnt FROM productos_menu")
        seed_menu_premium()
        _despues = rows("SELECT COUNT(*) AS cnt FROM productos_menu")
        productos = rows(f"""
            SELECT id_producto, nombre, precio_venta, categoria, activo
            FROM productos_menu
            {where}
            ORDER BY categoria, nombre
        """)
        _total = _despues[0]["cnt"] if _despues else 0
        if not productos:
            st.warning(f"No se pudieron cargar los platos. Total en DB: {_total} (antes: {_antes[0]['cnt'] if _antes else 0})", icon="⚠")
    for producto in productos:
        precio_original = float(producto["precio_venta"])
        precio_final = calcular_precio_promocion(producto["categoria"], precio_original)
        producto["precio_original"] = precio_original
        producto["precio_final"] = precio_final
        producto["descuento_aplicado"] = max(precio_original - precio_final, 0)
    return productos


def promo_config() -> dict:
    categoria = get_config("promo_categoria", "cocina")
    try:
        umbral = float(get_config("promo_umbral", "0") or 0)
    except ValueError:
        umbral = 0.0
    try:
        descuento = float(get_config("promo_descuento", "0") or 0)
    except ValueError:
        descuento = 0.0
    activa = get_config("promo_activa", "0") == "1"
    return {
        "activa": activa,
        "categoria": categoria,
        "umbral": max(umbral, 0),
        "descuento": min(max(descuento, 0), 0.95),
    }


def metodos_pago_config() -> list[str]:
    raw = get_config("metodos_pago", "Efectivo,Tarjeta,Transferencia")
    metodos = [m.strip() for m in raw.replace("\n", ",").split(",") if m.strip()]
    seen = set()
    unicos = []
    for metodo in metodos:
        key = metodo.lower()
        if key not in seen:
            seen.add(key)
            unicos.append(metodo)
    return unicos or ["Efectivo", "Tarjeta", "Transferencia"]


def set_metodos_pago(metodos: list[str]) -> None:
    limpios = [m.strip() for m in metodos if m.strip()]
    set_config("metodos_pago", ",".join(limpios or ["Efectivo", "Tarjeta", "Transferencia"]))


def calcular_precio_promocion(categoria: str, precio: float) -> float:
    promo = promo_config()
    if promo["activa"] and categoria == promo["categoria"] and float(precio) > promo["umbral"]:
        return round(float(precio) * (1 - promo["descuento"]))
    return float(precio)


def get_mesas() -> list[dict]:
    return rows("SELECT id_mesa, numero_mesa, estado FROM mesas ORDER BY numero_mesa")


def get_mozos() -> list[dict]:
    return rows("""
        SELECT id_usuario, nombre, apellido, rol, pin
        FROM usuarios
        WHERE rol = 'mozo'
          AND COALESCE(activo, 1) = 1
        ORDER BY nombre, apellido
    """)


def get_personal(rol: str | None = None, active_only: bool = False) -> list[dict]:
    filtros = []
    params: list = []
    if rol:
        filtros.append("rol = ?")
        params.append(rol)
    if active_only:
        filtros.append("COALESCE(activo, 1) = 1")
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    return rows(f"""
        SELECT id_usuario, nombre, apellido, rol, pin, COALESCE(activo, 1) AS activo
        FROM usuarios
        {where}
        ORDER BY
            CASE rol
                WHEN 'dueno' THEN 1
                WHEN 'administrador' THEN 2
                WHEN 'caja' THEN 3
                WHEN 'mozo' THEN 4
                WHEN 'cocina' THEN 5
                ELSE 6
            END,
            nombre,
            apellido
    """, tuple(params))


def role_label(rol: str) -> str:
    return {
        "mozo": "Mozo",
        "cocina": "Cocina",
        "caja": "Caja",
        "administrador": "Administrador",
        "dueno": "Dueño",
    }.get(rol, rol.title())


def mozo_operativo() -> dict:
    mozos = get_mozos()
    if not mozos:
        return st.session_state.usuario
    if st.session_state.mozo_operativo_id is None:
        st.session_state.mozo_operativo_id = mozos[0]["id_usuario"]
    seleccionado = next((m for m in mozos if m["id_usuario"] == st.session_state.mozo_operativo_id), mozos[0])
    st.session_state.mozo_operativo_id = seleccionado["id_usuario"]
    return seleccionado


def crear_pedido(id_mesa: int, id_usuario: int, cart: dict[int, dict]) -> int:
    items = normalize_order_cart(cart)
    if not items:
        raise ValueError("El pedido esta vacio.")
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        cur = conn.execute("""
            INSERT INTO pedidos_cabecera (id_mesa, id_usuario, estado_comanda)
            VALUES (?, ?, 'pendiente')
        """, (id_mesa, id_usuario))
        id_pedido = cur.lastrowid
        product_ids = tuple(item["id_producto"] for item in items)
        placeholders = ",".join("?" for _ in product_ids)
        productos = {
            int(row["id_producto"]): row
            for row in conn.execute(f"""
                SELECT id_producto, precio_venta, categoria
                FROM productos_menu
                WHERE id_producto IN ({placeholders})
                  AND activo = 1
            """, product_ids).fetchall()
        }
        for item in items:
            producto = productos.get(int(item["id_producto"]))
            if not producto:
                raise ValueError("Producto inactivo o inexistente.")
            precio_facturado = calcular_precio_promocion(producto["categoria"], float(producto["precio_venta"]))
            conn.execute("""
                INSERT INTO pedido_detalle
                    (id_pedido, id_producto, cantidad, observaciones, precio_unitario_facturado)
                VALUES (?, ?, ?, ?, ?)
            """, (
                id_pedido,
                producto["id_producto"],
                int(item["cantidad"]),
                item["observaciones"],
                precio_facturado,
            ))
        conn.execute("UPDATE mesas SET estado = 'ocupada' WHERE id_mesa = ?", (id_mesa,))
        conn.execute("COMMIT")
        return int(id_pedido)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def cart_add(producto: dict, delta: int) -> None:
    pid = int(producto["id_producto"])
    precio_final = float(producto.get("precio_final", calcular_precio_promocion(producto["categoria"], float(producto["precio_venta"]))))
    item = st.session_state.cart.get(pid, {
        "id_producto": pid,
        "nombre": producto["nombre"],
        "precio": precio_final,
        "precio_original": float(producto["precio_venta"]),
        "cantidad": 0,
        "observaciones": "",
    })
    item["cantidad"] = max(0, int(item["cantidad"]) + delta)
    if item["cantidad"] == 0:
        st.session_state.cart.pop(pid, None)
    else:
        item["nombre"] = producto["nombre"]
        item["precio"] = precio_final
        item["precio_original"] = float(producto["precio_venta"])
        st.session_state.cart[pid] = item




def parse_db_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    text = str(value).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now()


def elapsed_minutes(value: str | None) -> int:
    minutes = int((datetime.now() - parse_db_datetime(value)).total_seconds() // 60)
    return max(minutes, 0)


def elapsed_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    rest = minutes % 60
    return f"{hours}h {rest:02d}"


def kds_status_class(minutes: int) -> str:
    if minutes > 20:
        return "critical"
    if minutes > 10:
        return "warn"
    return "normal"


def pedidos_cocina_detallados() -> list[dict]:
    pedidos = rows("""
        SELECT pc.id_pedido,
               pc.fecha_hora,
               pc.estado_comanda,
               m.numero_mesa,
               u.nombre || ' ' || u.apellido AS mozo
        FROM pedidos_cabecera pc
        JOIN mesas m ON m.id_mesa = pc.id_mesa
        JOIN usuarios u ON u.id_usuario = pc.id_usuario
        WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo')
        ORDER BY pc.fecha_hora ASC
    """)
    if not pedidos:
        return []
    ids = tuple(int(p["id_pedido"]) for p in pedidos)
    placeholders = ",".join("?" for _ in ids)
    detalles = rows(f"""
        SELECT pd.id_pedido,
               pm.nombre,
               pm.categoria,
               SUM(pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) AS cantidad,
               TRIM(COALESCE(pd.observaciones, '')) AS observaciones
        FROM pedido_detalle pd
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pd.id_pedido IN ({placeholders})
          AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pd.id_pedido, pm.nombre, pm.categoria, TRIM(COALESCE(pd.observaciones, ''))
        ORDER BY pm.categoria, pm.nombre
    """, ids)
    por_pedido: dict[int, list[dict]] = {}
    for item in detalles:
        por_pedido.setdefault(int(item["id_pedido"]), []).append(item)
    armados = []
    for pedido in pedidos:
        pedido["items"] = por_pedido.get(int(pedido["id_pedido"]), [])
        if pedido["items"]:
            armados.append(pedido)
    return armados


def resumen_chef() -> list[dict]:
    return rows("""
        SELECT pm.nombre,
               SUM(pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) AS cantidad
        FROM pedidos_cabecera pc
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pc.estado_comanda IN ('pendiente', 'en_cocina')
          AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pm.id_producto, pm.nombre
        ORDER BY cantidad DESC, pm.nombre
        LIMIT 12
    """)


def deshacer_ultimo_despacho() -> dict:
    ultimo = st.session_state.get("ultimo_despachado")
    if not ultimo:
        return {"ok": False, "error": "No hay accion para deshacer."}
    pedido = one("SELECT estado_comanda FROM pedidos_cabecera WHERE id_pedido = ?", (ultimo["id_pedido"],))
    if not pedido:
        return {"ok": False, "error": "El pedido ya no existe."}
    execute(
        "UPDATE pedidos_cabecera SET estado_comanda = ? WHERE id_pedido = ?",
        (ultimo["estado_anterior"], ultimo["id_pedido"]),
    )
    registrar_auditoria("cocina", "deshacer_estado", f"Pedido {ultimo['id_pedido']} a {ultimo['estado_anterior']}")
    st.session_state.ultimo_despachado = None
    return {"ok": True}




def detalle_mesa(id_mesa: int) -> list[dict]:
    return rows("""
        SELECT MIN(pd.id_detalle) AS id_detalle,
               pm.id_producto,
               pm.nombre,
               pm.categoria,
               COALESCE(pd.precio_unitario_facturado, pm.precio_venta) AS precio,
               SUM(pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) AS cantidad,
               SUM((pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)) AS importe
        FROM pedidos_cabecera pc
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pc.id_mesa = ?
          AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
          AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pm.id_producto, pm.nombre, pm.categoria, COALESCE(pd.precio_unitario_facturado, pm.precio_venta)
        ORDER BY pm.categoria, pm.nombre
    """, (id_mesa,))


def detalle_mesa_renglones(id_mesa: int) -> list[dict]:
    return rows("""
        SELECT pd.id_detalle,
               pc.id_pedido,
               pm.nombre,
               pm.categoria,
               COALESCE(pd.precio_unitario_facturado, pm.precio_venta) AS precio,
               (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) AS pendiente,
               COALESCE(pd.observaciones, '') AS observaciones
        FROM pedidos_cabecera pc
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pc.id_mesa = ?
          AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
          AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
        ORDER BY pc.fecha_hora, pd.id_detalle
    """, (id_mesa,))


def generar_ticket(mesa: dict, detalle: list[dict], medio_pago: str, subtotal: float, servicio: float, total: float) -> str:
    cfg = restaurant_config()
    lineas = [
        cfg["nombre"],
        f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Mesa: {mesa['numero_mesa']}",
        "-" * 34,
    ]
    if cfg["identificacion"]:
        lineas.insert(1, cfg["identificacion"])
    if cfg["telefono"]:
        lineas.insert(1, f"Tel: {cfg['telefono']}")
    if cfg["direccion"]:
        lineas.insert(1, cfg["direccion"])
    for item in detalle:
        lineas.append(f"{int(item['cantidad'])}x {item['nombre'][:20]:20} {money(item['importe'])}")
    lineas += [
        "-" * 34,
        f"Subtotal: {money(subtotal)}",
        f"Servicio {service_percentage():.0f}%: {money(servicio)}",
        f"TOTAL: {money(total)}",
        f"Medio de pago: {medio_pago}",
        "",
        cfg["ticket_footer"],
    ]
    return "\n".join(lineas)


def caja_abierta() -> dict | None:
    return one("""
        SELECT cd.*, u.nombre || ' ' || u.apellido AS cajero
        FROM cajas_diarias cd
        JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
        WHERE cd.estado_caja = 'abierta'
        ORDER BY cd.id_caja DESC
        LIMIT 1
    """)


def registrar_movimiento_caja(conn, monto: float, descripcion: str, tipo: str = "ingreso_venta") -> None:
    caja = conn.execute("""
        SELECT id_caja FROM cajas_diarias
        WHERE estado_caja = 'abierta'
        ORDER BY id_caja DESC LIMIT 1
    """).fetchone()
    if not caja:
        raise ValueError("No hay caja abierta.")
    if tipo == "ingreso_venta":
        conn.execute("UPDATE cajas_diarias SET monto_ventas = monto_ventas + ? WHERE id_caja = ?", (monto, caja["id_caja"]))
    conn.execute("""
        INSERT INTO movimientos_caja (id_caja, tipo_movimiento, monto, descripcion)
        VALUES (?, ?, ?, ?)
    """, (caja["id_caja"], tipo, monto, descripcion))


def actualizar_pedidos_cobrados(conn, id_mesa: int) -> None:
    pedidos = conn.execute("""
        SELECT DISTINCT pc.id_pedido
        FROM pedidos_cabecera pc
        WHERE pc.id_mesa = ?
          AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
    """, (id_mesa,)).fetchall()
    for pedido in pedidos:
        pendiente = conn.execute("""
            SELECT COUNT(*) AS cnt
            FROM pedido_detalle
            WHERE id_pedido = ?
              AND (cantidad - COALESCE(cantidad_cobrada, 0) - COALESCE(cantidad_anulada, 0)) > 0
        """, (pedido["id_pedido"],)).fetchone()["cnt"]
        if pendiente == 0:
            total = conn.execute("""
                SELECT COALESCE(SUM(cantidad_cobrada * precio_unitario_facturado), 0) AS total
                FROM pedido_detalle
                WHERE id_pedido = ?
            """, (pedido["id_pedido"],)).fetchone()["total"]
            conn.execute("""
                UPDATE pedidos_cabecera
                   SET estado_comanda = 'cobrado',
                       total_cobrado = ?,
                       fecha_cobro = COALESCE(fecha_cobro, datetime('now','localtime'))
                 WHERE id_pedido = ?
            """, (float(total) * (1 + service_percentage() / 100), pedido["id_pedido"]))

    quedan = conn.execute("""
        SELECT COUNT(*) AS cnt
        FROM pedidos_cabecera pc
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        WHERE pc.id_mesa = ?
          AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
          AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
    """, (id_mesa,)).fetchone()["cnt"]
    conn.execute("UPDATE mesas SET estado = ? WHERE id_mesa = ?", ("ocupada" if quedan else "libre", id_mesa))


def cobrar_mesa(id_mesa: int, total: float, medio_pago: str) -> dict:
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        activos = conn.execute("""
            SELECT pc.id_pedido,
                   SUM((pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)) AS subtotal
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.id_mesa = ?
              AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
              AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
            GROUP BY pc.id_pedido
        """, (id_mesa,)).fetchall()
        if not activos:
            conn.execute("ROLLBACK")
            return {"ok": False, "error": "La mesa no tiene consumos activos."}

        subtotal = sum(float(p["subtotal"]) for p in activos)
        servicio = service_amount(subtotal)
        cur = conn.execute("""
            INSERT INTO pagos_mesa (id_mesa, id_usuario, medio_pago, subtotal, servicio, total, tipo)
            VALUES (?, ?, ?, ?, ?, ?, 'total')
        """, (id_mesa, st.session_state.usuario["id_usuario"], medio_pago, subtotal, servicio, subtotal + servicio))
        id_pago = cur.lastrowid

        detalles = conn.execute("""
            SELECT pd.id_detalle,
                   (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) AS pendiente,
                   COALESCE(pd.precio_unitario_facturado, pm.precio_venta) AS precio
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.id_mesa = ?
              AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
              AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
        """, (id_mesa,)).fetchall()
        for d in detalles:
            conn.execute("UPDATE pedido_detalle SET cantidad_cobrada = COALESCE(cantidad_cobrada, 0) + ? WHERE id_detalle = ?", (d["pendiente"], d["id_detalle"]))
            conn.execute("INSERT INTO pago_detalle (id_pago, id_detalle, cantidad, precio_unitario) VALUES (?, ?, ?, ?)", (id_pago, d["id_detalle"], d["pendiente"], d["precio"]))

        for pedido in activos:
            conn.execute("""
                UPDATE pedidos_cabecera
                   SET estado_comanda = 'cobrado',
                       medio_pago = ?,
                       total_cobrado = COALESCE(total_cobrado, 0) + ?,
                       fecha_cobro = datetime('now','localtime')
                 WHERE id_pedido = ?
            """, (medio_pago, float(pedido["subtotal"]) * (1 + service_percentage() / 100), pedido["id_pedido"]))

        conn.execute("UPDATE mesas SET estado = 'libre' WHERE id_mesa = ?", (id_mesa,))
        registrar_movimiento_caja(conn, total, f"Mesa {id_mesa} - {medio_pago}", "ingreso_venta")
        conn.execute("COMMIT")
        return {"ok": True, "pedidos": len(activos)}
    except Exception as exc:
        conn.execute("ROLLBACK")
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def cobrar_parcial(id_mesa: int, cantidades: dict[int, int], medio_pago: str) -> dict:
    seleccion = {k: v for k, v in cantidades.items() if v > 0}
    if not seleccion:
        return {"ok": False, "error": "No seleccionaste productos para cobrar."}
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        subtotal = 0.0
        detalles = []
        for id_detalle, cantidad in seleccion.items():
            row = conn.execute("""
                SELECT pd.id_detalle,
                       pm.nombre,
                       COALESCE(pd.precio_unitario_facturado, pm.precio_venta) AS precio,
                       (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) AS pendiente
                FROM pedido_detalle pd
                JOIN pedidos_cabecera pc ON pc.id_pedido = pd.id_pedido
                JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                WHERE pd.id_detalle = ? AND pc.id_mesa = ?
            """, (id_detalle, id_mesa)).fetchone()
            if not row or cantidad > int(row["pendiente"]):
                raise ValueError("Cantidad parcial invalida.")
            subtotal += cantidad * float(row["precio"])
            detalles.append((row, cantidad))

        servicio = service_amount(subtotal)
        total = subtotal + servicio
        cur = conn.execute("""
            INSERT INTO pagos_mesa (id_mesa, id_usuario, medio_pago, subtotal, servicio, total, tipo)
            VALUES (?, ?, ?, ?, ?, ?, 'parcial')
        """, (id_mesa, st.session_state.usuario["id_usuario"], medio_pago, subtotal, servicio, total))
        id_pago = cur.lastrowid
        for row, cantidad in detalles:
            conn.execute("UPDATE pedido_detalle SET cantidad_cobrada = COALESCE(cantidad_cobrada, 0) + ? WHERE id_detalle = ?", (cantidad, row["id_detalle"]))
            conn.execute("INSERT INTO pago_detalle (id_pago, id_detalle, cantidad, precio_unitario) VALUES (?, ?, ?, ?)", (id_pago, row["id_detalle"], cantidad, row["precio"]))

        registrar_movimiento_caja(conn, total, f"Pago parcial mesa {id_mesa} - {medio_pago}", "ingreso_venta")
        actualizar_pedidos_cobrados(conn, id_mesa)
        conn.execute("COMMIT")
        return {"ok": True, "total": total}
    except Exception as exc:
        conn.execute("ROLLBACK")
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def anular_detalle(id_detalle: int, cantidad: int, motivo: str) -> dict:
    if cantidad <= 0:
        return {"ok": False, "error": "La cantidad debe ser mayor a cero."}
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        row = conn.execute("""
            SELECT pd.id_detalle,
                   pc.id_mesa,
                   pm.nombre,
                   (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) AS pendiente
            FROM pedido_detalle pd
            JOIN pedidos_cabecera pc ON pc.id_pedido = pd.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pd.id_detalle = ?
        """, (id_detalle,)).fetchone()
        if not row:
            raise ValueError("Renglon inexistente.")
        if cantidad > int(row["pendiente"]):
            raise ValueError("No se puede anular mas de lo pendiente.")
        conn.execute("""
            UPDATE pedido_detalle
               SET cantidad_anulada = COALESCE(cantidad_anulada, 0) + ?,
                   motivo_anulacion = TRIM(COALESCE(motivo_anulacion, '') || ' ' || ?)
             WHERE id_detalle = ?
        """, (cantidad, motivo, id_detalle))
        actualizar_pedidos_cobrados(conn, row["id_mesa"])
        conn.execute("COMMIT")
        return {"ok": True, "producto": row["nombre"]}
    except Exception as exc:
        conn.execute("ROLLBACK")
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()




def mesas_para_caja() -> list[dict]:
    mesas = get_mesas()
    totales = rows("""
        SELECT pc.id_mesa,
               COUNT(DISTINCT pc.id_pedido) AS pedidos,
               COALESCE(SUM((pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)), 0) AS subtotal
        FROM pedidos_cabecera pc
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
          AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pc.id_mesa
    """)
    por_mesa = {int(t["id_mesa"]): t for t in totales}
    for mesa in mesas:
        total = por_mesa.get(int(mesa["id_mesa"]), {})
        subtotal = float(total.get("subtotal") or 0)
        mesa["pedidos"] = int(total.get("pedidos") or 0)
        mesa["subtotal"] = subtotal
        mesa["total"] = subtotal + service_amount(subtotal)
    return mesas


def historial_ventas(limit: int = 5) -> list[dict]:
    return rows("""
        SELECT p.fecha_hora,
               m.numero_mesa,
               p.medio_pago,
               p.total,
               p.tipo
        FROM pagos_mesa p
        JOIN mesas m ON m.id_mesa = p.id_mesa
        ORDER BY p.fecha_hora DESC
        LIMIT ?
    """, (limit,))


def anulaciones_recientes(limit: int = 10) -> list[dict]:
    return rows("""
        SELECT pc.fecha_hora,
               m.numero_mesa,
               pc.id_pedido,
               pm.nombre AS producto,
               COALESCE(pd.cantidad_anulada, 0) AS cantidad_anulada,
               COALESCE(pd.motivo_anulacion, '') AS motivo,
               u.nombre || ' ' || u.apellido AS mozo
        FROM pedido_detalle pd
        JOIN pedidos_cabecera pc ON pc.id_pedido = pd.id_pedido
        JOIN mesas m ON m.id_mesa = pc.id_mesa
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        LEFT JOIN usuarios u ON u.id_usuario = pc.id_usuario
        WHERE COALESCE(pd.cantidad_anulada, 0) > 0
        ORDER BY pc.fecha_hora DESC, pd.id_detalle DESC
        LIMIT ?
    """, (limit,))


def generar_corte_caja(caja: dict) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    cfg = restaurant_config()
    movimientos = pd.DataFrame(rows("""
        SELECT fecha_hora, tipo_movimiento, monto, descripcion
        FROM movimientos_caja
        WHERE id_caja = ?
        ORDER BY fecha_hora
    """, (caja["id_caja"],)))
    if caja.get("fecha_cierre"):
        medios = pd.DataFrame(rows("""
            SELECT medio_pago,
                   COUNT(*) AS pagos,
                   SUM(subtotal) AS subtotal,
                   SUM(servicio) AS servicio,
                   SUM(total) AS total
            FROM pagos_mesa
            WHERE fecha_hora >= ?
              AND fecha_hora <= ?
            GROUP BY medio_pago
            ORDER BY total DESC
        """, (caja["fecha_apertura"], caja["fecha_cierre"])))
    else:
        medios = pd.DataFrame(rows("""
            SELECT medio_pago,
                   COUNT(*) AS pagos,
                   SUM(subtotal) AS subtotal,
                   SUM(servicio) AS servicio,
                   SUM(total) AS total
            FROM pagos_mesa
            WHERE fecha_hora >= ?
            GROUP BY medio_pago
            ORDER BY total DESC
        """, (caja["fecha_apertura"],)))
    ingresos = float(movimientos[movimientos["tipo_movimiento"] == "ingreso_venta"]["monto"].sum()) if not movimientos.empty else 0
    egresos = float(movimientos[movimientos["tipo_movimiento"] != "ingreso_venta"]["monto"].sum()) if not movimientos.empty else 0
    esperado = cash_expected(caja["monto_apertura"], ingresos, egresos)
    real = caja.get("monto_cierre_real")
    diferencia = cash_difference(real, esperado) if real is not None else 0
    lineas = [
        cfg["nombre"],
        "CORTE DE CAJA",
        f"Caja: #{caja['id_caja']}",
        f"Cajero: {caja['cajero']}",
        f"Apertura: {caja['fecha_apertura']}",
        f"Cierre: {caja.get('fecha_cierre') or 'abierta'}",
        "-" * 36,
        f"Monto apertura: {money(caja['monto_apertura'])}",
        f"Ingresos venta: {money(ingresos)}",
        f"Egresos/retiros: {money(egresos)}",
        f"Esperado: {money(esperado)}",
    ]
    if real is not None:
        lineas.append(f"Real contado: {money(real)}")
        lineas.append(f"Diferencia: {money(diferencia)}")
        if caja.get("observacion_cierre"):
            lineas.append(f"Observacion: {caja['observacion_cierre']}")
    lineas.append("-" * 36)
    lineas.append("MEDIOS DE PAGO")
    if medios.empty:
        lineas.append("Sin pagos registrados")
    else:
        for _, row in medios.iterrows():
            lineas.append(f"{row['medio_pago']}: {money(row['total'])} ({int(row['pagos'])})")
    lineas.append("-" * 36)
    lineas.append("MOVIMIENTOS")
    if movimientos.empty:
        lineas.append("Sin movimientos")
    else:
        for _, row in movimientos.iterrows():
            lineas.append(f"{row['tipo_movimiento']} {money(row['monto'])} - {row['descripcion']}")
    return "\n".join(lineas), movimientos, medios


def liberar_mesa_sin_cobro(id_mesa: int, motivo: str = "") -> None:
    execute("UPDATE mesas SET estado = 'libre' WHERE id_mesa = ?", (id_mesa,))
    registrar_auditoria("caja", "liberar_mesa_manual", f"{id_mesa} {motivo}".strip())


def cash_focus_script() -> None:
    st.markdown(
        """
        <script>
        setTimeout(() => {
            const inputs = Array.from(window.parent.document.querySelectorAll('input'));
            const cash = inputs.find(i => (i.getAttribute('aria-label') || '').includes('Efectivo recibido'));
            if (cash) cash.focus();
        }, 350);
        </script>
        """,
        unsafe_allow_html=True,
    )


def page_cocina() -> None:
    procesar_cola_sincronizacion()
    offline_banner()
    title("Terminal de cocina", "Comandas vivas, tiempos y despacho tactil.")
    cocina_form_open = st.session_state.get("cocina_form_open", False)
    refresh_seconds = kitchen_auto_refresh_seconds(cocina_form_open)
    if refresh_seconds:
        auto_refresh(refresh_seconds)

    pedidos = pedidos_cocina_detallados()
    pendientes = [p for p in pedidos if p["estado_comanda"] == "pendiente"]
    en_cocina  = [p for p in pedidos if p["estado_comanda"] == "en_cocina"]
    listos     = [p for p in pedidos if p["estado_comanda"] == "listo"]

    # ── Métricas ──────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pendientes",      len(pendientes))
    m2.metric("En preparación",  len(en_cocina))
    m3.metric("Listos",          len(listos))
    m4.metric("Platos activos",  sum(int(i["cantidad"]) for p in pendientes + en_cocina for i in p["items"]))

    # ── Chef view + controles ─────────────────────────────────────
    top_left, top_right = st.columns([2.2, 1])
    with top_left:
        resumen = resumen_chef()
        st.markdown("<div class='kds-summary'><div class='kds-summary-title'>Chef view - ” total pendiente</div>", unsafe_allow_html=True)
        if resumen:
            for item in resumen:
                st.markdown(
                    f"<div class='kds-summary-line'><span>{escape(item['nombre'])}</span><b>{int(item['cantidad'])}</b></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown("<span class='muted'>Sin platos pendientes.</span>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with top_right:
        btn_c1, btn_c2 = st.columns(2)
        with btn_c1:
            form_open = cocina_form_open
            if st.button("✨ Nuevo Pedido", type="primary", use_container_width=True):
                st.session_state["cocina_form_open"] = not form_open
                if not form_open:
                    st.session_state["cocina_kart"] = {}
                st.rerun()
        with btn_c2:
            if st.button("🔄 Actualizar", use_container_width=True):
                st.rerun()
        ultimo = st.session_state.get("ultimo_despachado")
        if ultimo:
            st.caption(f"Último: pedido #{ultimo['id_pedido']} mesa {ultimo['mesa']}")
            if st.button("↩ Deshacer último despacho", use_container_width=True):
                res = deshacer_ultimo_despacho()
                if res["ok"]:
                    st.success("Despacho deshecho.")
                    st.rerun()
                st.error(res["error"])

    # ── Formulario: Nuevo Pedido Manual ──────────────────────────────
    if st.session_state.get("cocina_form_open", False):
        st.markdown("<div class='card' style='margin-bottom:1rem'>", unsafe_allow_html=True)
        st.subheader("Nuevo Pedido Manual")
        mesas_all = get_mesas()
        menu_all  = get_menu()
        ckart     = st.session_state.get("cocina_kart", {})

        form_l, form_r = st.columns([1.55, 1], gap="large")

        with form_l:
            mesa_opts = {
                m["id_mesa"]: f"Mesa {m['numero_mesa']}  ({m['estado'].replace('_', ' ')})"
                for m in mesas_all
            }
            mesa_id = st.selectbox(
                "Mesa",
                options=list(mesa_opts.keys()),
                format_func=lambda x: mesa_opts[x],
                key="cocina_mesa_sel",
            )
            categorias = [("cocina", "Cocina"), ("bebidas", "Bebidas"), ("postres", "Postres")]
            cat_tabs = st.tabs([lbl for _, lbl in categorias])
            for ctab, (cat, _) in zip(cat_tabs, categorias):
                with ctab:
                    prods = [p for p in menu_all if p["categoria"] == cat]
                    if not prods:
                        st.caption("Sin productos en esta categoría.")
                        continue
                    for p in prods:
                        pid = int(p["id_producto"])
                        qty = ckart.get(pid, {}).get("cantidad", 0)
                        prow = st.columns([3.5, .65, .72, .65], gap="small")
                        with prow[0]:
                            st.markdown(
                                f"<div class='product-tile'>"
                                f"<div class='product-name'>{escape(p['nombre'])}</div>"
                                f"<div class='product-price'>{money(float(p['precio_final']))}</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                        with prow[1]:
                            if st.button("âˆ’", key=f"ck_minus_{pid}", disabled=qty == 0, use_container_width=True):
                                if qty > 1:
                                    ckart[pid]["cantidad"] = qty - 1
                                else:
                                    ckart.pop(pid, None)
                                st.session_state["cocina_kart"] = ckart
                                st.rerun()
                        with prow[2]:
                            st.markdown(f"<div class='qty-badge'>{qty}</div>", unsafe_allow_html=True)
                        with prow[3]:
                            if st.button("+", key=f"ck_plus_{pid}", use_container_width=True):
                                if pid not in ckart:
                                    ckart[pid] = {
                                        "id_producto": pid,
                                        "nombre": p["nombre"],
                                        "precio": float(p["precio_final"]),
                                        "cantidad": 0,
                                        "observaciones": "",
                                    }
                                ckart[pid]["cantidad"] += 1
                                st.session_state["cocina_kart"] = ckart
                                st.rerun()

        with form_r:
            st.markdown("<div class='cart-title'>Resumen</div>", unsafe_allow_html=True)
            if not ckart:
                st.info("Agregá productos con +")
            else:
                total_form = 0.0
                for pid, item in list(ckart.items()):
                    importe = int(item["cantidad"]) * float(item["precio"])
                    total_form += importe
                    st.markdown(
                        f"<div class='line'>"
                        f"<span><b>{item['cantidad']} ×</b> {escape(item['nombre'])}</span>"
                        f"<b>{money(importe)}</b>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    nota_val = st.text_input(
                        "Nota",
                        value=ckart[pid].get("observaciones", ""),
                        key=f"ck_nota_{pid}",
                        label_visibility="collapsed",
                        placeholder="Nota para cocina",
                    )
                    ckart[pid]["observaciones"] = nota_val
                st.session_state["cocina_kart"] = ckart
                st.markdown(
                    f"<div class='total'><span>Total</span><span>{money(total_form)}</span></div>",
                    unsafe_allow_html=True,
                )

            personal_cocina = (
                get_personal(rol="cocina", active_only=True)
                or get_personal(rol="administrador", active_only=True)
                or get_personal(active_only=True)
            )
            id_usr_cocina = personal_cocina[0]["id_usuario"] if personal_cocina else 1

            if st.button("✅ Crear Pedido", type="primary", disabled=not ckart, use_container_width=True):
                try:
                    nuevo_id = crear_pedido(mesa_id, id_usr_cocina, ckart)
                    registrar_auditoria("cocina", "pedido_manual", f"Pedido {nuevo_id} mesa {mesa_id}")
                    st.success(f"Pedido #{nuevo_id} creado.")
                    st.session_state["cocina_kart"] = {}
                    st.session_state["cocina_form_open"] = False
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            if st.button("âœ• Cancelar", use_container_width=True):
                st.session_state["cocina_form_open"] = False
                st.session_state["cocina_kart"] = {}
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    # ── Tablero Kanban ────────────────────────────────────────────
    st.markdown("---")

    st.markdown("""
    <style>
    .kb-col { border-radius:12px; padding:.65rem .7rem 1rem; min-height:120px; }
    .kb-col.col-pend { background:#f0ece5; border-top:4px solid #9a8a78; }
    .kb-col.col-coci { background:#fff8e6; border-top:4px solid #f4a800; }
    .kb-col.col-list { background:#eaf6ee; border-top:4px solid #28a745; }
    .kb-col-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:.7rem; }
    .kb-col-title { font-size:.82rem; font-weight:880; text-transform:uppercase; letter-spacing:.06em; }
    .kb-badge { border-radius:999px; padding:.15rem .55rem; font-size:.8rem; font-weight:800; color:white; }
    .col-pend .kb-badge { background:#9a8a78; }
    .col-coci .kb-badge { background:#f4a800; }
    .col-list .kb-badge { background:#28a745; }
    .kb-card { background:white; border-radius:10px; padding:.72rem .78rem; margin-bottom:.65rem;
               box-shadow:0 1px 4px rgba(0,0,0,.08); border-left:4px solid #ccc; }
    .kb-card.t-ok   { border-left-color:#28a745; }
    .kb-card.t-warn { border-left-color:#f4a800; }
    .kb-card.t-crit { border-left-color:#dc3545; animation:critPulse 1.5s ease-in-out infinite; }
    @keyframes critPulse {
        0%,100% { box-shadow:0 1px 4px rgba(0,0,0,.08); }
        50%      { box-shadow:0 0 0 3px rgba(220,53,69,.18); }
    }
    .kb-card-head { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:.45rem; }
    .kb-card-id   { font-size:1rem; font-weight:900; }
    .kb-card-mesa { font-size:.82rem; color:#6b5e4e; font-weight:700; }
    .kb-timer { font-size:.78rem; font-weight:800; border-radius:999px; padding:.18rem .5rem; white-space:nowrap; }
    .t-ok   .kb-timer { background:#d4edda; color:#155724; }
    .t-warn .kb-timer { background:#fff3cd; color:#7a5200; }
    .t-crit .kb-timer { background:#f8d7da; color:#721c24; }
    .kb-dish { font-size:.88rem; line-height:1.6; }
    .kb-dish b { font-size:.95rem; }
    .kb-note { display:inline-block; background:#fff0d6; border-left:2px solid #f4a800;
               border-radius:4px; padding:.1rem .4rem; font-size:.78rem; color:#7a5200; margin-left:.3rem; }
    .kb-mozo { font-size:.75rem; color:#a09887; margin-top:.4rem; }
    .kb-empty { text-align:center; color:#b0a898; font-size:.88rem;
                padding:1.8rem .5rem; border:2px dashed #d8d0c6; border-radius:8px; }
    </style>
    """, unsafe_allow_html=True)

    def _timer_class(minutes: int) -> str:
        if minutes >= 20: return "t-crit"
        if minutes >= 10: return "t-warn"
        return "t-ok"

    def _card_html(pedido: dict) -> str:
        minutes = elapsed_minutes(pedido["fecha_hora"])
        tc = _timer_class(minutes)
        dishes = ""
        for it in pedido["items"]:
            nota = escape(it.get("observaciones") or "")
            nota_html = f"<span class='kb-note'>{nota}</span>" if nota else ""
            dishes += f"<div class='kb-dish'><b>{int(it['cantidad'])}Ã—</b> {escape(it['nombre'])}{nota_html}</div>"
        return (
            f"<div class='kb-card {tc}'>"
            f"<div class='kb-card-head'>"
            f"<div><div class='kb-card-id'>#{pedido['id_pedido']}</div>"
            f"<div class='kb-card-mesa'>Mesa {pedido['numero_mesa']}</div></div>"
            f"<span class='kb-timer'>{elapsed_label(minutes)}</span>"
            f"</div>"
            f"{dishes}"
            f"<div class='kb-mozo'> 👤  {escape(pedido['mozo'])}</div>"
            f"</div>"
        )

    col_pend, col_coci, col_list = st.columns(3)

    # ── Columna PENDIENTE ─────────────────────────────────────────
    with col_pend:
        cards_html = "".join(_card_html(p) for p in pendientes) if pendientes else "<div class='kb-empty'>Sin comandas</div>"
        st.markdown(
            f"<div class='kb-col col-pend'>"
            f"<div class='kb-col-head'><span class='kb-col-title'>⏳ Pendiente</span>"
            f"<span class='kb-badge'>{len(pendientes)}</span></div>"
            f"{cards_html}</div>",
            unsafe_allow_html=True,
        )
        for pedido in pendientes:
            if st.button(f"▶ Iniciar  #{pedido['id_pedido']} · Mesa {pedido['numero_mesa']}",
                         key=f"kb_ini_{pedido['id_pedido']}", type="primary", use_container_width=True):
                res = avanzar_estado(pedido["id_pedido"], "pendiente")
                if res["ok"]:
                    st.session_state.ultimo_despachado = {"id_pedido": pedido["id_pedido"],
                        "estado_anterior": "pendiente", "mesa": pedido["numero_mesa"]}
                    registrar_auditoria("cocina", "avance_estado", f"{pedido['id_pedido']} pendiente")
                    st.rerun()
                else:
                    st.error(res["error"])

    # ── Columna EN COCINA ─────────────────────────────────────────
    with col_coci:
        cards_html = "".join(_card_html(p) for p in en_cocina) if en_cocina else "<div class='kb-empty'>Nada en preparación</div>"
        st.markdown(
            f"<div class='kb-col col-coci'>"
            f"<div class='kb-col-head'><span class='kb-col-title'>🔥 En preparación</span>"
            f"<span class='kb-badge'>{len(en_cocina)}</span></div>"
            f"{cards_html}</div>",
            unsafe_allow_html=True,
        )
        for pedido in en_cocina:
            if st.button(f"🚀 Listo  #{pedido['id_pedido']} · Mesa {pedido['numero_mesa']}",
                         key=f"kb_list_{pedido['id_pedido']}", type="primary", use_container_width=True):
                res = avanzar_estado(pedido["id_pedido"], "en_cocina")
                if res["ok"]:
                    st.session_state.ultimo_despachado = {"id_pedido": pedido["id_pedido"],
                        "estado_anterior": "en_cocina", "mesa": pedido["numero_mesa"]}
                    registrar_auditoria("cocina", "avance_estado", f"{pedido['id_pedido']} en_cocina")
                    for warn in res.get("advertencias", []):
                        st.warning(warn)
                    st.rerun()
                else:
                    st.error(res["error"])

    # ── Columna LISTO ─────────────────────────────────────────────
    with col_list:
        cards_html = "".join(_card_html(p) for p in listos) if listos else "<div class='kb-empty'>Nada listo todavía</div>"
        st.markdown(
            f"<div class='kb-col col-list'>"
            f"<div class='kb-col-head'><span class='kb-col-title'>✅ Listo para servir</span>"
            f"<span class='kb-badge'>{len(listos)}</span></div>"
            f"{cards_html}</div>",
            unsafe_allow_html=True,
        )
        for pedido in listos:
            st.caption(f"#{pedido['id_pedido']} · Mesa {pedido['numero_mesa']}")


def page_caja() -> None:
    procesar_cola_sincronizacion()
    offline_banner()
    title("Terminal de caja", "Cobro rapido, cuenta dividida, tickets e historial.")
    caja = caja_abierta()
    if caja:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Caja", f"#{caja['id_caja']}")
        c2.metric("Cajero", caja["cajero"])
        c3.metric("Apertura", money(caja["monto_apertura"]))
        c4.metric("Ventas", money(caja["monto_ventas"]))
    else:
        st.warning("No hay caja abierta. Abrila antes de cobrar.")
        monto = st.number_input("Monto de apertura", min_value=0.0, step=100.0)
        if st.button("Abrir caja", type="primary", use_container_width=True):
            execute("""
                INSERT INTO cajas_diarias (id_usuario_cajero, monto_apertura, estado_caja)
                VALUES (?, ?, 'abierta')
            """, (st.session_state.usuario["id_usuario"], monto))
            registrar_auditoria("caja", "apertura", money(monto))
            st.rerun()
        return

    with st.expander("Movimientos y cierre"):
        col_mov, col_cierre, col_hist = st.columns([1, 1, 1])
        with col_mov:
            tipo_egreso = st.selectbox("Tipo", ["retiro_efectivo", "egreso_proveedor"], format_func=lambda x: "Retiro efectivo" if x == "retiro_efectivo" else "Gasto / proveedor")
            monto_egreso = st.number_input("Monto egreso", min_value=0.0, step=100.0)
            desc_egreso = st.text_input("Descripcion", placeholder="Compra, retiro, ajuste")
            if st.button("Registrar egreso", use_container_width=True, disabled=monto_egreso <= 0):
                conn = get_connection()
                try:
                    conn.execute("BEGIN TRANSACTION")
                    registrar_movimiento_caja(conn, monto_egreso, desc_egreso or tipo_egreso, tipo_egreso)
                    conn.execute("COMMIT")
                    registrar_auditoria("caja", "egreso", f"{tipo_egreso} {money(monto_egreso)}")
                    st.rerun()
                except Exception as exc:
                    conn.execute("ROLLBACK")
                    st.error(str(exc))
                finally:
                    conn.close()
        with col_cierre:
            real = st.number_input("Monto contado real", min_value=0.0, step=100.0)
            mov = (one("""
                SELECT
                    COALESCE(SUM(CASE WHEN tipo_movimiento = 'ingreso_venta' THEN monto ELSE 0 END), 0) AS ingresos,
                    COALESCE(SUM(CASE WHEN tipo_movimiento != 'ingreso_venta' THEN monto ELSE 0 END), 0) AS egresos
                FROM movimientos_caja
                WHERE id_caja = ?
            """, (caja["id_caja"],)) or {"ingresos": 0, "egresos": 0})
            ingresos = float(mov["ingresos"] or 0)
            egresos = float(mov["egresos"] or 0)
            esperado = cash_expected(caja["monto_apertura"], ingresos, egresos)
            diferencia = cash_difference(real, esperado)
            diff_label = cash_difference_label(diferencia)
            cierre_cols = st.columns(2)
            cierre_cols[0].metric("Esperado", money(esperado))
            cierre_cols[1].metric(diff_label.title(), money(abs(diferencia)))
            observacion_cierre = st.text_input(
                "Observacion de cierre",
                placeholder="Motivo del faltante/sobrante o cierre exacto",
            )
            requiere_observacion = cash_close_requires_note(diferencia)
            if requiere_observacion:
                st.warning("Hay diferencia de caja. Escribi una observacion antes de cerrar.")
            if st.button("Cerrar caja", use_container_width=True, disabled=requiere_observacion and not observacion_cierre.strip()):
                # Backup automatico antes de cerrar
                _bak = hacer_backup_ahora()
                if _bak:
                    st.toast(f"Backup pre-cierre: {_bak}")
                execute("""
                    UPDATE cajas_diarias
                       SET fecha_cierre = datetime('now','localtime'),
                           monto_cierre_real = ?,
                           diferencia_cierre = ?,
                           observacion_cierre = ?,
                           estado_caja = 'cerrada'
                     WHERE id_caja = ?
                """, (real, diferencia, observacion_cierre.strip(), caja["id_caja"]))
                registrar_auditoria(
                    "caja",
                    "cierre",
                    f"Real {money(real)} esperado {money(esperado)} diferencia {money(diferencia)} {observacion_cierre.strip()}",
                )
                st.rerun()
        with col_hist:
            st.caption("Ultimas ventas")
            for venta in historial_ventas(5):
                st.markdown(
                    f"<div class='history-row'><span>Mesa {venta['numero_mesa']}<br><span class='muted'>{escape(venta['medio_pago'])}</span></span><b>{money(venta['total'])}</b></div>",
                    unsafe_allow_html=True,
                )
            corte_txt, movimientos_corte, medios_corte = generar_corte_caja(caja)
            st.download_button(
                "Descargar corte.txt",
                corte_txt,
                file_name=f"corte_caja_{caja['id_caja']}.txt",
                use_container_width=True,
            )

    with st.expander("Metodos de pago"):
        metodos_actuales = metodos_pago_config()
        texto_metodos = st.text_area(
            "Un metodo por linea o separados por coma",
            value="\n".join(metodos_actuales),
            height=110,
            help="Ejemplos: Efectivo, Tarjeta, Transferencia, QR, Mercado Pago, Cuenta corriente.",
        )
        if st.button("Guardar metodos de pago", use_container_width=True):
            nuevos = [m.strip() for chunk in texto_metodos.splitlines() for m in chunk.split(",") if m.strip()]
            set_metodos_pago(nuevos)
            if st.session_state.medio_pago_caja not in nuevos:
                st.session_state.medio_pago_caja = (nuevos or ["Efectivo"])[0]
            registrar_auditoria("caja", "metodos_pago_actualizados", ", ".join(nuevos))
            st.rerun()

    mesas = mesas_para_caja()
    if not mesas:
        st.info("No hay mesas cargadas.")
        return
    ids_mesas = [int(m["id_mesa"]) for m in mesas]
    mesas_con_cuenta = [m for m in mesas if float(m["total"]) > 0]
    if st.session_state.mesa_caja_id not in ids_mesas:
        st.session_state.mesa_caja_id = int((mesas_con_cuenta[0] if mesas_con_cuenta else mesas[0])["id_mesa"])

    left, center, right = st.columns([0.9, 1.35, 1.05], gap="medium")
    with left:
        st.subheader("Salon")
        for mesa_item in mesas:
            estado = mesa_item["estado"]
            clase = "free" if estado == "libre" else "bill" if estado == "esperando_cuenta" else "eating"
            selected = " | seleccionada" if int(mesa_item["id_mesa"]) == int(st.session_state.mesa_caja_id) else ""
            st.markdown(
                f"""
                <div class="cash-table {clase}">
                    <div class="cash-table-num">Mesa {mesa_item['numero_mesa']}{selected}</div>
                    <div class="cash-table-meta">{escape(estado.replace('_', ' '))} | {money(mesa_item['total'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Seleccionar", key=f"cash_mesa_{mesa_item['id_mesa']}", use_container_width=True):
                st.session_state.mesa_caja_id = int(mesa_item["id_mesa"])
                st.rerun()

    mesa = next(m for m in mesas if int(m["id_mesa"]) == int(st.session_state.mesa_caja_id))
    detalle = detalle_mesa(mesa["id_mesa"])
    subtotal = sum(float(i["importe"]) for i in detalle)
    servicio = service_amount(subtotal)
    total = subtotal + servicio
    medio = st.session_state.medio_pago_caja

    with center:
        st.subheader(f"Cuenta mesa {mesa['numero_mesa']}")
        if detalle:
            for item in detalle:
                st.markdown(
                    f"<div class='line'><span><b>{int(item['cantidad'])}x</b> {escape(item['nombre'])}<br><span class='muted'>{escape(item['categoria'])}</span></span><b>{money(item['importe'])}</b></div>",
                    unsafe_allow_html=True,
                )
            st.markdown(f"<div class='total'><span>Total con servicio</span><span>{money(total)}</span></div>", unsafe_allow_html=True)
        else:
            st.info("La mesa no tiene consumos pendientes.")

        partes = st.number_input("Dividir en partes iguales", min_value=1, max_value=20, value=1, step=1)
        st.caption(f"Cada parte: {money(total / partes if partes else total)}")
        with st.expander("Dividir por productos"):
            renglones = detalle_mesa_renglones(mesa["id_mesa"])
            cantidades = {}
            for renglon in renglones:
                cols = st.columns([3.4, 0.8, 1])
                cols[0].write(f"{renglon['nombre']} | Pedido #{renglon['id_pedido']}")
                cols[1].caption(f"Pend.: {renglon['pendiente']}")
                cantidades[renglon["id_detalle"]] = int(cols[2].number_input(
                    "Cobrar",
                    min_value=0,
                    max_value=int(renglon["pendiente"]),
                    value=0,
                    key=f"parcial_new_{renglon['id_detalle']}",
                    label_visibility="collapsed",
                ))
            parcial_subtotal = sum(cantidades[r["id_detalle"]] * float(r["precio"]) for r in renglones)
            parcial_servicio = service_amount(parcial_subtotal)
            parcial_total = parcial_subtotal + parcial_servicio
            st.markdown(f"<div class='total'><span>Parcial seleccionado</span><span>{money(parcial_total)}</span></div>", unsafe_allow_html=True)
            if st.button("Cobrar parcial", use_container_width=True, disabled=parcial_total <= 0):
                res = cobrar_parcial(mesa["id_mesa"], cantidades, medio)
                if res["ok"]:
                    registrar_auditoria("caja", "cobro_parcial", f"Mesa {mesa['numero_mesa']} {money(res['total'])}")
                    st.success("Cobro parcial registrado.")
                    st.rerun()
                st.error(res["error"])

        with st.expander("Anular producto con motivo"):
            anulables = detalle_mesa_renglones(mesa["id_mesa"])
            if not anulables:
                st.info("No hay productos pendientes para anular.")
            else:
                renglon_anular = st.selectbox(
                    "Producto a anular",
                    anulables,
                    format_func=lambda r: f"Pedido #{r['id_pedido']} | {r['nombre']} | pendiente {r['pendiente']}",
                    key=f"caja_anular_producto_{mesa['id_mesa']}",
                )
                col_anul_1, col_anul_2 = st.columns([0.8, 2])
                cantidad_anular = col_anul_1.number_input(
                    "Cantidad",
                    min_value=1,
                    max_value=int(renglon_anular["pendiente"]),
                    value=1,
                    key=f"caja_anular_cantidad_{renglon_anular['id_detalle']}",
                )
                motivo_anular = col_anul_2.text_input(
                    "Motivo obligatorio",
                    placeholder="Cliente cancela, error de carga, cortesia...",
                    key=f"caja_anular_motivo_{renglon_anular['id_detalle']}",
                )
                if st.button("Anular producto", type="primary", use_container_width=True, disabled=not motivo_anular.strip()):
                    res = anular_detalle(renglon_anular["id_detalle"], int(cantidad_anular), motivo_anular.strip())
                    if res["ok"]:
                        registrar_auditoria(
                            "caja",
                            "anulacion_producto",
                            f"Mesa {mesa['numero_mesa']} pedido {renglon_anular['id_pedido']} {res['producto']} x{cantidad_anular} motivo: {motivo_anular.strip()}",
                        )
                        st.success("Producto anulado y auditado.")
                        st.rerun()
                    st.error(res["error"])

        with st.expander("Auditoria de anulaciones"):
            anulaciones = pd.DataFrame(anulaciones_recientes(20))
            if anulaciones.empty:
                st.info("Sin anulaciones registradas.")
            else:
                st.dataframe(anulaciones, hide_index=True, use_container_width=True)
                st.download_button(
                    "Descargar anulaciones.csv",
                    anulaciones.to_csv(index=False).encode("utf-8-sig"),
                    file_name="anulaciones_recientes.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

        ticket = generar_ticket(mesa, detalle, medio, subtotal, servicio, total)
        st.markdown(f"<div class='ticket'>{escape(ticket)}</div>", unsafe_allow_html=True)
        print_html = f"<html><body><pre>{escape(ticket)}</pre><script>window.print()</script></body></html>"
        st.markdown(
            f'<a href="data:text/html;charset=utf-8,{quote(print_html)}" target="_blank">Abrir ticket para imprimir</a>',
            unsafe_allow_html=True,
        )
        st.download_button("Reimprimir / descargar ticket", ticket, file_name=f"ticket_mesa_{mesa['numero_mesa']}.txt", use_container_width=True)
        corte_txt, _, _ = generar_corte_caja(caja)
        corte_html = f"<html><body><pre>{escape(corte_txt)}</pre><script>window.print()</script></body></html>"
        st.markdown(
            f'<a href="data:text/html;charset=utf-8,{quote(corte_html)}" target="_blank">Abrir corte de caja para imprimir</a>',
            unsafe_allow_html=True,
        )

    with right:
        st.markdown(
            "<div class='pay-panel'><div class='pay-title'>Facturacion rapida</div><span class='muted'>Metodo, recibido, vuelto y cierre de mesa.</span></div>",
            unsafe_allow_html=True,
        )
        metodos = metodos_pago_config()
        if st.session_state.medio_pago_caja not in metodos:
            st.session_state.medio_pago_caja = metodos[0]
        for i in range(0, len(metodos), 3):
            metodo_cols = st.columns(3)
            for col, value in zip(metodo_cols, metodos[i:i + 3]):
                if col.button(value, key=f"medio_{value}_{i}", use_container_width=True, type="primary" if medio == value else "secondary"):
                    st.session_state.medio_pago_caja = value
                    st.rerun()
        medio = st.session_state.medio_pago_caja
        st.caption(f"Medio seleccionado: {medio}")

        recibido = st.number_input(
            "Efectivo recibido",
            min_value=0.0,
            value=float(st.session_state.efectivo_recibido or 0),
            step=500.0,
            disabled=medio != "Efectivo",
        )
        st.session_state.efectivo_recibido = recibido
        quick = st.columns(3)
        for idx, (col, amount) in enumerate(zip(quick, [total, 10000, 20000])):
            if col.button(money(amount), key=f"cash_quick_a_{idx}_{amount}", disabled=medio != "Efectivo", use_container_width=True):
                st.session_state.efectivo_recibido = float(amount)
                st.rerun()
        quick2 = st.columns(3)
        for idx, (col, amount) in enumerate(zip(quick2, [50000, 100000, 200000])):
            if col.button(money(amount), key=f"cash_quick_b_{idx}_{amount}", disabled=medio != "Efectivo", use_container_width=True):
                st.session_state.efectivo_recibido = float(amount)
                st.rerun()
        vuelto = cash_change_due(total, float(st.session_state.efectivo_recibido or 0), medio)
        st.markdown(
            f"<div class='change-box'><div class='change-label'>Vuelto</div><div class='change-value'>{money(vuelto)}</div></div>",
            unsafe_allow_html=True,
        )
        puede_cobrar = can_charge_table(total, medio, float(st.session_state.efectivo_recibido or 0))
        if medio == "Efectivo" and total > 0 and not puede_cobrar:
            st.warning("El efectivo recibido debe cubrir el total antes de cobrar.")
        if st.button("Cobrar y liberar", type="primary", use_container_width=True, disabled=not puede_cobrar):
            res = cobrar_mesa(mesa["id_mesa"], total, medio)
            if res["ok"]:
                registrar_auditoria("caja", "mesa_cobrada", f"Mesa {mesa['numero_mesa']} {money(total)}")
                st.session_state.efectivo_recibido = 0.0
                st.success("Mesa cobrada y liberada.")
                st.rerun()
            st.error(res["error"])
        with st.expander("Liberacion manual auditada"):
            motivo_liberar = st.text_input("Motivo para liberar sin cobrar", placeholder="Mesa cargada por error, cambio operativo...")
            if st.button("Liberar mesa manual", use_container_width=True, disabled=not motivo_liberar.strip()):
                liberar_mesa_sin_cobro(mesa["id_mesa"], f"Mesa {mesa['numero_mesa']} motivo: {motivo_liberar.strip()}")
                st.rerun()
        cash_focus_script()


def page_menu() -> None:
    title("Administracion de menu", "Crear productos, cambiar precios y activar o pausar platos.")
    with st.expander("Promocion automatica por categoria", expanded=False):
        promo = promo_config()
        with st.form("promo_automatica"):
            col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
            activa = col1.checkbox("Activa", value=promo["activa"])
            categoria = col2.selectbox(
                "Categoria",
                ["cocina", "bebidas", "postres"],
                index=["cocina", "bebidas", "postres"].index(promo["categoria"]) if promo["categoria"] in ["cocina", "bebidas", "postres"] else 0,
            )
            umbral = col3.number_input("Umbral", min_value=0.0, value=float(promo["umbral"]), step=500.0)
            descuento_pct = col4.number_input("Descuento %", min_value=0.0, max_value=95.0, value=float(promo["descuento"] * 100), step=1.0)
            ejemplo_base = umbral + 1000
            ejemplo = round(ejemplo_base * (1 - descuento_pct / 100)) if activa and ejemplo_base > umbral else ejemplo_base
            st.caption(f"Ejemplo: producto de {money(umbral + 1000)} queda en {money(ejemplo)} si supera el umbral.")
            if st.form_submit_button("Guardar promocion", type="primary"):
                set_config("promo_activa", "1" if activa else "0")
                set_config("promo_categoria", categoria)
                set_config("promo_umbral", str(float(umbral)))
                set_config("promo_descuento", str(float(descuento_pct) / 100))
                registrar_auditoria("menu", "promo_actualizada", f"{categoria} > {money(umbral)} - {descuento_pct}%")
                st.success("Promocion actualizada.")
                st.rerun()

    with st.expander("Nuevo producto", expanded=False):
        with st.form("nuevo_producto"):
            nombre = st.text_input("Nombre")
            precio = st.number_input("Precio", min_value=0.0, step=100.0)
            categoria = st.selectbox("Categoria", ["cocina", "bebidas", "postres"])
            activo = st.checkbox("Activo", value=True)
            if st.form_submit_button("Guardar", type="primary"):
                execute("""
                    INSERT INTO productos_menu (nombre, precio_venta, categoria, activo)
                    VALUES (?, ?, ?, ?)
                """, (nombre.strip(), precio, categoria, 1 if activo else 0))
                registrar_auditoria("menu", "producto_creado", nombre)
                st.toast("Producto guardado correctamente")
                st.rerun()

    df = pd.DataFrame(get_menu(active_only=False))
    edited = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        disabled=["id_producto"],
        column_config={
            "activo": st.column_config.CheckboxColumn("Activo"),
            "precio_venta": st.column_config.NumberColumn("Precio", min_value=0, step=100),
            "categoria": st.column_config.SelectboxColumn("Categoria", options=["cocina", "bebidas", "postres"]),
        },
    )
    if st.button("Guardar cambios de menu", type="primary"):
        conn = get_connection()
        try:
            for _, row in edited.iterrows():
                conn.execute("""
                    UPDATE productos_menu
                       SET nombre = ?, precio_venta = ?, categoria = ?, activo = ?
                     WHERE id_producto = ?
                """, (row["nombre"], float(row["precio_venta"]), row["categoria"], int(row["activo"]), int(row["id_producto"])))
            conn.commit()
            registrar_auditoria("menu", "productos_actualizados", str(len(edited)))
            st.toast("Menu actualizado correctamente")
        finally:
            conn.close()




def page_usuarios() -> None:
    title("Personal y accesos", "Alta de mozos, cocina, caja y administradores.")
    # Override icon types for password fields in column layouts (Form 2)
    st.markdown(
        """
        <style>
        /* "Crear acceso" form: password fields in columns need lock icon */
        form[data-testid="stForm"]:nth-of-type(2)
            [data-testid="stHorizontalBlock"]:nth-of-type(2)
            [data-testid="stTextInput"]
            div[data-baseweb="input"]::before {
            content: "\\U0001F512" !important;
        }
        form[data-testid="stForm"]:nth-of-type(2)
            [data-testid="stHorizontalBlock"]:nth-of-type(1)
            [data-testid="stTextInput"]
            div[data-baseweb="input"]::before {
            content: "\\U0001F464" !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    roles = ["mozo", "cocina", "caja", "administrador", "dueno"]
    personal = get_personal()

    resumen_cols = st.columns(len(roles))
    for col, rol in zip(resumen_cols, roles):
        activos = [p for p in personal if p["rol"] == rol and int(p["activo"]) == 1]
        with col:
            stat_card(role_label(rol), len(activos), {
                "mozo": "#285f83",
                "cocina": "#b87419",
                "caja": "#2e7d50",
                "administrador": "#9f2f24",
                "dueno": "#5b3f9f",
            }[rol])

    tab_acceso, tab_alta, tab_lista = st.tabs(["Acceso general", "Crear personal", "Listado"])
    with tab_acceso:
        st.markdown(
            """
            <div class="card">
                <b>Ingreso unico al sistema</b><br>
                <span class="muted">Este usuario y contrasena abren el panel administrador. Las terminales de mozo, cocina y caja entran automaticas por URL.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("config_acceso_general"):
            usuario_actual = get_config("usuario_sistema", SYSTEM_USERNAME)
            nuevo_usuario = st.text_input("Usuario general", value=usuario_actual)
            nueva_password = st.text_input("Nueva contrasena general", value="", type="password", placeholder="Dejar vacia para no cambiar")
            confirmar = st.text_input("Confirmar nueva contrasena", value="", type="password")
            if st.form_submit_button("Guardar acceso general", type="primary"):
                if not nuevo_usuario.strip():
                    st.error("El usuario general no puede estar vacio.")
                elif nueva_password != confirmar:
                    st.error("Las contrasenas no coinciden.")
                elif nueva_password and access_password_error(nueva_password, minimum=8):
                    st.error(access_password_error(nueva_password, minimum=8))
                else:
                    set_config("usuario_sistema", normalize_access_username(nuevo_usuario))
                    if nueva_password:
                        set_system_password(nueva_password)
                    else:
                        upsert_system_access(nuevo_usuario.strip(), get_config("password_sistema", SYSTEM_PASSWORD))
                    registrar_auditoria("usuarios", "acceso_general_actualizado", nuevo_usuario.strip())
                    st.success("Acceso general actualizado.")

        st.subheader("Accesos administradores")
        try:
            accesos_df = pd.DataFrame(system_access_rows())
        except Exception:
            accesos_df = pd.DataFrame(active_system_accesses())
            accesos_df["activo"] = True
        if not accesos_df.empty:
            accesos_df["activo"] = accesos_df["activo"].astype(bool)
            edited_accesses = st.data_editor(
                accesos_df,
                hide_index=True,
                use_container_width=True,
                disabled=[col for col in accesos_df.columns if col not in ("activo", "rol")],
                column_config={
                    "usuario": st.column_config.TextColumn("Usuario"),
                    "rol": st.column_config.SelectboxColumn("Rol", options=roles),
                    "activo": st.column_config.CheckboxColumn("Activo"),
                    "creado_en": st.column_config.TextColumn("Creado"),
                    "actualizado_en": st.column_config.TextColumn("Actualizado"),
                },
                key="editor_accesos_sistema",
            )
            if st.button("Guardar estado de accesos", type="primary"):
                if int(edited_accesses["activo"].sum()) < 1:
                    st.error("Debe quedar al menos un acceso activo.")
                else:
                    for _, row in edited_accesses.iterrows():
                        set_system_access_active(str(row["usuario"]), bool(row["activo"]))
                        # Actualizar rol
                        if "rol" in row and row["rol"]:
                            conn2 = get_connection()
                            try:
                                conn2.execute("UPDATE accesos_sistema SET rol = ? WHERE LOWER(usuario) = LOWER(?)",
                                             (row["rol"], str(row["usuario"])))
                                conn2.commit()
                            finally:
                                conn2.close()
                    registrar_auditoria("usuarios", "accesos_estado_actualizado", str(len(edited_accesses)))
                    st.success("Estado de accesos actualizado.")
                    st.rerun()
        else:
            st.info("Todavia no hay accesos configurados.")

        with st.form("nuevo_acceso_sistema"):
            st.markdown("**Crear acceso con rol**")
            col_user, col_rol = st.columns(2)
            usuario_acceso = col_user.text_input("Usuario", placeholder="usuario")
            rol_acceso = col_rol.selectbox("Rol", roles, format_func=role_label, key="rol_acceso")
            col_pass, col_confirm = st.columns(2)
            password_acceso = col_pass.text_input("Contrasena", type="password")
            confirmar_acceso = col_confirm.text_input("Confirmar contrasena", type="password")
            if st.form_submit_button("Guardar acceso"):
                clean_user = normalize_access_username(usuario_acceso)
                password_error = access_password_error(password_acceso, minimum=4)
                if not clean_user:
                    st.error("El usuario no puede estar vacio.")
                elif password_acceso != confirmar_acceso:
                    st.error("Las contrasenas no coinciden.")
                elif password_error:
                    st.error(password_error)
                else:
                    upsert_system_access(clean_user, hash_password(password_acceso), rol_acceso)
                    set_system_access_active(clean_user, True)
                    registrar_auditoria("usuarios", "acceso_sistema_guardado", f"{clean_user} ({rol_acceso})")
                    st.success(f"Acceso {clean_user} creado como {rol_acceso}.")
                    st.rerun()

        st.markdown(
            """
            <div class="card">
                <b>Terminales automaticas</b><br>
                <span class="muted">Mozo: http://localhost:8520/?terminal=mozo</span><br>
                <span class="muted">Cocina: http://localhost:8520/?terminal=cocina</span><br>
                <span class="muted">Caja: http://localhost:8520/?terminal=caja</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with tab_alta:
        st.markdown(
            """
            <div class="card">
                <b>Nuevo empleado</b><br>
                <span class="muted">El rol define donde aparece: mozos en pedidos, cocina en monitor, caja en cobros y administrador en gestion.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("nuevo_personal"):
            col_a, col_b = st.columns(2)
            nombre = col_a.text_input("Nombre")
            apellido = col_b.text_input("Apellido")
            col_c, col_d = st.columns(2)
            rol = col_c.selectbox("Rol", roles, format_func=role_label)
            pin = col_d.text_input("PIN interno", type="password", placeholder="Opcional")
            activo = st.checkbox("Activo", value=True)
            if st.form_submit_button("Crear personal", type="primary"):
                if not nombre.strip() or not apellido.strip():
                    st.error("Nombre y apellido son obligatorios.")
                else:
                    from database import encolar_sync, get_connection as _gc
                    execute("""
                        INSERT INTO usuarios (nombre, apellido, rol, pin, activo)
                        VALUES (?, ?, ?, ?, ?)
                    """, (nombre.strip(), apellido.strip(), rol, pin.strip() or "0000", 1 if activo else 0))
                    _conn = _gc()
                    try:
                        row = _conn.execute("SELECT MAX(id_usuario) AS max_id FROM usuarios").fetchone()
                        new_id = row["max_id"] if row and row["max_id"] else 0
                    finally:
                        _conn.close()
                    encolar_sync("usuarios", "INSERT", str(new_id), {
                        "nombre": nombre.strip(), "apellido": apellido.strip(),
                        "rol": rol, "pin": pin.strip() or "0000", "activo": 1,
                    })
                    registrar_auditoria("usuarios", "personal_creado", f"{nombre} {apellido} {rol}")
                    st.success("Personal creado.")
                    st.rerun()

    with tab_lista:
        st.caption("Desactivar un empleado lo oculta de las terminales sin borrar su historial.")
        df = pd.DataFrame(personal)
        if df.empty:
            st.info("Todavia no hay personal cargado.")
            return
        df["activo"] = df["activo"].astype(bool)
        edited = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            disabled=["id_usuario"],
            column_config={
                "id_usuario": st.column_config.NumberColumn("ID"),
                "nombre": st.column_config.TextColumn("Nombre"),
                "apellido": st.column_config.TextColumn("Apellido"),
                "rol": st.column_config.SelectboxColumn("Rol", options=roles),
                "pin": st.column_config.TextColumn("PIN"),
                "activo": st.column_config.CheckboxColumn("Activo"),
            },
        )
        if st.button("Guardar personal", type="primary"):
            from database import encolar_sync
            conn = get_connection()
            try:
                for _, row in edited.iterrows():
                    conn.execute("""
                        UPDATE usuarios
                           SET nombre = ?, apellido = ?, rol = ?, pin = ?, activo = ?
                         WHERE id_usuario = ?
                    """, (
                        str(row["nombre"]).strip(),
                        str(row["apellido"]).strip(),
                        row["rol"],
                        str(row["pin"]) if str(row["pin"]).strip() else "0000",
                        1 if bool(row["activo"]) else 0,
                        int(row["id_usuario"]),
                    ))
                    encolar_sync("usuarios", "UPDATE", str(int(row["id_usuario"])), {
                        "nombre": str(row["nombre"]).strip(),
                        "apellido": str(row["apellido"]).strip(),
                        "rol": row["rol"],
                        "pin": str(row["pin"]) if str(row["pin"]).strip() else "0000",
                        "activo": 1 if bool(row["activo"]) else 0,
                    })
                conn.commit()
                registrar_auditoria("usuarios", "personal_actualizado", str(len(edited)))
                st.success("Personal actualizado.")
                st.rerun()
            finally:
                conn.close()


def pedidos_listos_mozo() -> list[dict]:
    return rows("""
        SELECT pc.id_pedido,
               m.numero_mesa,
               pc.fecha_hora,
               GROUP_CONCAT(pd.cantidad || 'x ' || pm.nombre, ', ') AS detalle
        FROM pedidos_cabecera pc
        JOIN mesas m ON m.id_mesa = pc.id_mesa
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pc.estado_comanda = 'listo'
          AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pc.id_pedido, m.numero_mesa, pc.fecha_hora
        ORDER BY pc.fecha_hora
    """)


def pedidos_mesa_resumen(id_mesa: int) -> list[dict]:
    return rows("""
        SELECT pc.id_pedido,
               pc.estado_comanda,
               pc.fecha_hora,
               GROUP_CONCAT((pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) || 'x ' || pm.nombre, ', ') AS detalle
        FROM pedidos_cabecera pc
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pc.id_mesa = ?
          AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
          AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pc.id_pedido, pc.estado_comanda, pc.fecha_hora
        ORDER BY pc.fecha_hora DESC
        LIMIT 5
    """, (id_mesa,))


def render_waiter_summary(mesas: list[dict], listos: list[dict], operativo: dict) -> None:
    libres = sum(1 for m in mesas if m["estado"] == "libre")
    ocupadas = sum(1 for m in mesas if m["estado"] == "ocupada")
    cuenta = sum(1 for m in mesas if m["estado"] == "esperando_cuenta")
    st.markdown(
        f"""
        <div class="waiter-strip">
            <div class="waiter-chip"><div class="waiter-chip-label">Mozo</div><div class="waiter-chip-value">{escape(operativo['nombre'])}</div></div>
            <div class="waiter-chip"><div class="waiter-chip-label">Ocupadas</div><div class="waiter-chip-value">{ocupadas}</div></div>
            <div class="waiter-chip"><div class="waiter-chip-label">En cuenta</div><div class="waiter-chip-value">{cuenta}</div></div>
            <div class="waiter-chip"><div class="waiter-chip-label">Listos</div><div class="waiter-chip-value">{len(listos)}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if libres == len(mesas):
        st.caption("Salon libre.")


def page_mozo() -> None:
    # ── Notificacion push: pedidos listos desde cocina ────────────────
    _sql_listos = "SELECT COUNT(*) AS cnt FROM pedidos_cabecera WHERE estado_comanda = 'listo'"
    if using_postgres():
        _sql_listos += " AND fecha_hora >= now() - interval '2 hours'"
    else:
        from datetime import datetime as _dt, timedelta as _td
        _corte = (_dt.now() - _td(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        _sql_listos += " AND fecha_hora >= ?"
        _listos_hoy = rows(_sql_listos, (_corte,))
    _cant_listos = _listos_hoy[0]["cnt"] if _listos_hoy else 0
    _prev = st.session_state.get("mozo_listos_prev", -1)
    if _prev != -1 and _cant_listos > _prev:
        st.toast(f"🍽  {_cant_listos - _prev} pedido(s) listo(s) para servir!", icon="🔥")
    st.session_state.mozo_listos_prev = _cant_listos

    mozos = get_mozos()
    operativo = mozo_operativo()
    if not mozos:
        title("Terminal de mozo", "Primero carga personal con rol mozo.")
        st.warning("No hay mozos activos. Crealos desde Personal y accesos.")
        return

    if st.session_state.mesa_actual is None:
        title("Terminal de mozo", "Mesas, pedidos, entrega y cuenta en modo tactil.")
        if len(mozos) > 1:
            ids = [m["id_usuario"] for m in mozos]
            current_index = ids.index(operativo["id_usuario"]) if operativo["id_usuario"] in ids else 0
            elegido = st.selectbox(
                "Mozo operativo",
                mozos,
                index=current_index,
                format_func=lambda m: f"{m['nombre']} {m['apellido']}",
                help="Identifica quien toma el pedido.",
            )
            st.session_state.mozo_operativo_id = elegido["id_usuario"]
            operativo = elegido

        mesas = mesas_para_caja()
        listos = pedidos_listos_mozo()
        render_waiter_summary(mesas, listos, operativo)

        if listos:
            st.subheader("Pedidos listos")
            ready_cols = st.columns(2)
            for idx, pedido in enumerate(listos):
                with ready_cols[idx % 2]:
                    minutes = elapsed_minutes(pedido["fecha_hora"])
                    st.markdown(
                        f"""
                        <div class="ready-order">
                            <b>Mesa {pedido['numero_mesa']} | Pedido #{pedido['id_pedido']} | {elapsed_label(minutes)}</b><br>
                            <span class="muted">{escape(pedido['detalle'] or '')}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button("Marcar entregado", key=f"mozo2_entregar_{pedido['id_pedido']}", use_container_width=True):
                        res = marcar_pedido_entregado(pedido["id_pedido"])
                        if res["ok"]:
                            registrar_auditoria("mozo", "pedido_entregado", str(pedido["id_pedido"]))
                            st.rerun()
                        st.error(res["error"])

        filtro_estado = st.radio(
            "Filtro de mesas",
            ["Todas", "Libres", "Ocupadas", "En cuenta"],
            index=0,
            horizontal=True,
            label_visibility="collapsed",
        )
        mapa_filtro = {
            "Libres": "libre",
            "Ocupadas": "ocupada",
            "En cuenta": "esperando_cuenta",
        }
        if filtro_estado != "Todas":
            mesas = [m for m in mesas if m["estado"] == mapa_filtro[filtro_estado]]

        st.subheader("Salon")
        for i in range(0, len(mesas), 4):
            cols = st.columns(4)
            for col, mesa in zip(cols, mesas[i:i + 4]):
                estado = mesa["estado"]
                clase = "free" if estado == "libre" else "bill" if estado == "esperando_cuenta" else "busy"
                accion = "Abrir pedido" if estado == "libre" else "Agregar pedido"
                disabled = estado == "esperando_cuenta"
                with col:
                    st.markdown(
                        f"""
                        <div class="table-card {clase}">
                            <div class="table-card-num">Mesa {mesa['numero_mesa']}</div>
                            <div class="table-card-meta"><span>{escape(estado.replace('_', ' '))}</span><b>{money(mesa['total'])}</b></div>
                            <div class="muted">{mesa['pedidos']} pedidos activos</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button(accion, key=f"mozo2_abrir_{mesa['id_mesa']}", disabled=disabled, use_container_width=True):
                        st.session_state.mesa_actual = mesa
                        st.session_state.cart = {}
                        st.rerun()
                    if estado == "ocupada" and st.button("Pedir cuenta", key=f"mozo2_cuenta_{mesa['id_mesa']}", use_container_width=True):
                        execute("UPDATE mesas SET estado = 'esperando_cuenta' WHERE id_mesa = ?", (mesa["id_mesa"],))
                        registrar_auditoria("mozo", "mesa_esperando_cuenta", str(mesa["numero_mesa"]))
                        st.rerun()
        return

    mesa = st.session_state.mesa_actual
    title(f"Pedido mesa {mesa['numero_mesa']}", "Productos, cantidades y notas para cocina.")
    pedidos_previos = pedidos_mesa_resumen(mesa["id_mesa"])
    if pedidos_previos:
        with st.expander("Pedidos activos de esta mesa", expanded=False):
            for pedido in pedidos_previos:
                st.markdown(
                    f"<div class='line'><span><b>#{pedido['id_pedido']}</b> {escape(pedido['estado_comanda'])}<br><span class='muted'>{escape(pedido['detalle'] or '')}</span></span><span>{elapsed_label(elapsed_minutes(pedido['fecha_hora']))}</span></div>",
                    unsafe_allow_html=True,
                )

    left, right = st.columns([1.62, 0.88], gap="large")
    menu = get_menu()
    with left:
        from components.categorias import CATEGORIAS_MENU
        filtro = st.text_input("Buscar producto", placeholder="Escribi nombre del plato...").strip().lower()
        if filtro:
            _resultados = [p for p in menu if filtro in p["nombre"].lower()]
            if len(_resultados) > 0:
                st.caption(f"{len(_resultados)} resultado(s) para '{filtro}'")
        tabs = st.tabs(CATEGORIAS_MENU)
        for tab, cat in zip(tabs, CATEGORIAS_MENU):
            with tab:
                productos = [p for p in menu if p["categoria"] == cat and (not filtro or filtro in p["nombre"].lower())]
                if not productos:
                    st.info("Sin productos para este filtro.")
                for p in productos:
                    pid = int(p["id_producto"])
                    qty = st.session_state.cart.get(pid, {}).get("cantidad", 0)
                    row = st.columns([4.1, .7, .72, .7, 2.8], gap="small")
                    with row[0]:
                        st.markdown(
                            f"<div class='product-tile'><div class='product-name'>{escape(p['nombre'])}</div><div class='product-price'>{precio_producto_html(p)}</div></div>",
                            unsafe_allow_html=True,
                        )
                    with row[1]:
                        if st.button("-", key=f"mozo2_minus_{pid}", disabled=qty == 0, use_container_width=True):
                            cart_add(p, -1)
                            st.rerun()
                    with row[2]:
                        st.markdown(f"<div class='qty-badge'>{qty}</div>", unsafe_allow_html=True)
                    with row[3]:
                        if st.button("+", key=f"mozo2_plus_{pid}", use_container_width=True):
                            cart_add(p, 1)
                            st.rerun()
                    with row[4]:
                        if qty > 0:
                            note = st.text_input(
                                "Nota",
                                value=st.session_state.cart[pid].get("observaciones", ""),
                                key=f"mozo2_note_{pid}",
                                label_visibility="collapsed",
                                placeholder="Nota para cocina",
                            )
                            st.session_state.cart[pid]["observaciones"] = note
                        else:
                            st.markdown("<div class='muted' style='padding-top:.8rem'>Sin nota</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='cart-title'>Pedido actual</div>", unsafe_allow_html=True)
        total = 0.0
        if not st.session_state.cart:
            st.info("Agrega productos con el boton +.")
        for pid, item in list(st.session_state.cart.items()):
            importe = int(item["cantidad"]) * float(item["precio"])
            total += importe
            st.markdown(
                f"<div class='line'><span><b>{item['cantidad']}x</b> {escape(item['nombre'])}<br><span class='muted'>{escape(item.get('observaciones') or 'Sin observaciones')}</span></span><b>{money(importe)}</b></div>",
                unsafe_allow_html=True,
            )
            note_cols = st.columns(2)
            for label in ["Sin cebolla", "Sin sal", "Bien cocido", "Para llevar"]:
                idx = ["Sin cebolla", "Sin sal", "Bien cocido", "Para llevar"].index(label)
                if note_cols[idx % 2].button(label, key=f"mozo2_note_preset_{pid}_{idx}", use_container_width=True):
                    current = st.session_state.cart[pid].get("observaciones", "").strip()
                    st.session_state.cart[pid]["observaciones"] = f"{current}; {label}".strip("; ")
                    st.rerun()
            if st.button("Quitar producto", key=f"mozo2_remove_{pid}", use_container_width=True):
                st.session_state.cart.pop(pid, None)
                st.rerun()
        st.markdown(f"<div class='total'><span>Total pedido</span><span>{money(total)}</span></div>", unsafe_allow_html=True)
        if st.button("Enviar a cocina", type="primary", disabled=not st.session_state.cart, use_container_width=True):
            try:
                pedido = crear_pedido(mesa["id_mesa"], operativo["id_usuario"], st.session_state.cart)
                registrar_auditoria("mozo", "pedido_creado", f"Pedido {pedido}, mesa {mesa['numero_mesa']}")
                st.success(f"Pedido #{pedido} enviado a cocina.")
                st.session_state.mesa_actual = None
                st.session_state.cart = {}
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if st.button("Vaciar pedido", disabled=not st.session_state.cart, use_container_width=True):
            st.session_state.cart = {}
            st.rerun()
        if st.button("Volver al salon", use_container_width=True):
            st.session_state.mesa_actual = None
            st.session_state.cart = {}
            st.rerun()




def excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes | None:
    buffer = BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            for name, df in sheets.items():
                safe_name = name[:31] or "Hoja"
                df.to_excel(writer, sheet_name=safe_name, index=False)
        return buffer.getvalue()
    except Exception:
        return None


def resumen_recetas_productos() -> list[dict]:
    return rows("""
        SELECT pm.id_producto,
               pm.nombre,
               pm.categoria,
               pm.activo,
               COUNT(r.id_receta) AS insumos,
               COALESCE(SUM(r.cantidad_a_descontar), 0) AS cantidad_total
        FROM productos_menu pm
        LEFT JOIN recetas_escandallo r ON r.id_producto = pm.id_producto
        GROUP BY pm.id_producto, pm.nombre, pm.categoria, pm.activo
        ORDER BY pm.categoria, pm.nombre
    """)


def matriz_recetas() -> list[dict]:
    return rows("""
        SELECT pm.nombre AS producto,
               pm.categoria,
               i.nombre AS insumo,
               r.cantidad_a_descontar,
               i.unidad_medida,
               i.stock_actual,
               i.stock_minimo
        FROM recetas_escandallo r
        JOIN productos_menu pm ON pm.id_producto = r.id_producto
        JOIN insumos i ON i.id_insumo = r.id_insumo
        ORDER BY pm.categoria, pm.nombre, i.nombre
    """)


def receta_producto(id_producto: int) -> list[dict]:
    return rows("""
        SELECT r.id_receta,
               r.id_producto,
               r.id_insumo,
               i.nombre AS insumo,
               r.cantidad_a_descontar,
               i.unidad_medida,
               i.stock_actual,
               i.stock_minimo
        FROM recetas_escandallo r
        JOIN insumos i ON i.id_insumo = r.id_insumo
        WHERE r.id_producto = ?
        ORDER BY i.nombre
    """, (id_producto,))


def page_recetas() -> None:
    title("Recetas por plato", "Escandallo, cobertura de stock y productos pendientes.")
    productos = get_menu(active_only=False)
    insumos = rows("SELECT id_insumo, nombre, unidad_medida, stock_actual, stock_minimo FROM insumos ORDER BY nombre")
    if not productos:
        st.warning("Primero carga productos en Menu.")
        return
    if not insumos:
        st.warning("Primero carga insumos en Inventario.")
        return

    resumen = resumen_recetas_productos()
    sin_receta = [p for p in resumen if int(p["insumos"] or 0) == 0]
    activos_sin = [p for p in sin_receta if int(p["activo"]) == 1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Productos", len(resumen))
    c2.metric("Con receta", len(resumen) - len(sin_receta))
    c3.metric("Sin receta", len(sin_receta))
    c4.metric("Activos sin receta", len(activos_sin))

    tab_editor, tab_pendientes, tab_matriz = st.tabs(["Editor", "Pendientes", "Matriz"])
    with tab_editor:
        producto = st.selectbox(
            "Producto",
            productos,
            format_func=lambda p: f"{p['nombre']} | {p['categoria']} | {'activo' if p['activo'] else 'pausado'}",
        )
        receta = receta_producto(int(producto["id_producto"]))
        st.subheader("Receta actual")
        if receta:
            df = pd.DataFrame(receta)
            df["eliminar"] = False
            edited = st.data_editor(
                df,
                hide_index=True,
                use_container_width=True,
                disabled=["id_receta", "id_producto", "id_insumo", "insumo", "unidad_medida", "stock_actual", "stock_minimo"],
                column_config={
                    "cantidad_a_descontar": st.column_config.NumberColumn("Cantidad por unidad", min_value=0.01, step=0.5),
                    "eliminar": st.column_config.CheckboxColumn("Eliminar"),
                },
            )
            if st.button("Guardar receta", type="primary", use_container_width=True):
                conn = get_connection()
                try:
                    for _, row in edited.iterrows():
                        if bool(row["eliminar"]):
                            conn.execute("DELETE FROM recetas_escandallo WHERE id_receta = ?", (int(row["id_receta"]),))
                        else:
                            conn.execute(
                                "UPDATE recetas_escandallo SET cantidad_a_descontar = ? WHERE id_receta = ?",
                                (float(row["cantidad_a_descontar"]), int(row["id_receta"])),
                            )
                    conn.commit()
                    registrar_auditoria("recetas", "receta_guardada", producto["nombre"])
                    st.success("Receta guardada.")
                    st.rerun()
                finally:
                    conn.close()

            cobertura = []
            for item in receta:
                cantidad = float(item["cantidad_a_descontar"] or 0)
                posibles = int(float(item["stock_actual"] or 0) // cantidad) if cantidad > 0 else 0
                cobertura.append({
                    "insumo": item["insumo"],
                    "stock": item["stock_actual"],
                    "unidad": item["unidad_medida"],
                    "cantidad_por_plato": cantidad,
                    "platos_posibles": posibles,
                })
            if cobertura:
                st.subheader("Cobertura estimada por stock")
                st.dataframe(pd.DataFrame(cobertura), hide_index=True, use_container_width=True)
        else:
            st.info("Este producto todavia no tiene receta. Cocina no podra descontar stock al despacharlo.")

        with st.form("agregar_insumo_receta_profesional"):
            st.subheader("Agregar insumo")
            insumo = st.selectbox("Insumo", insumos, format_func=lambda i: f"{i['nombre']} ({i['unidad_medida']})")
            cantidad = st.number_input("Cantidad a descontar por unidad vendida", min_value=0.01, step=0.5)
            if st.form_submit_button("Agregar / actualizar insumo", type="primary"):
                existente = one("""
                    SELECT id_receta
                    FROM recetas_escandallo
                    WHERE id_producto = ? AND id_insumo = ?
                """, (producto["id_producto"], insumo["id_insumo"]))
                if existente:
                    execute(
                        "UPDATE recetas_escandallo SET cantidad_a_descontar = ? WHERE id_receta = ?",
                        (cantidad, existente["id_receta"]),
                    )
                else:
                    execute("""
                        INSERT INTO recetas_escandallo (id_producto, id_insumo, cantidad_a_descontar)
                        VALUES (?, ?, ?)
                    """, (producto["id_producto"], insumo["id_insumo"], cantidad))
                registrar_auditoria("recetas", "receta_actualizada", producto["nombre"])
                st.rerun()

    with tab_pendientes:
        st.subheader("Productos sin receta")
        if sin_receta:
            pendientes_df = pd.DataFrame(sin_receta)
            st.dataframe(pendientes_df, hide_index=True, use_container_width=True)
            st.download_button(
                "Descargar pendientes.csv",
                pendientes_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="productos_sin_receta.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.success("Todos los productos tienen receta.")

    with tab_matriz:
        matriz_df = pd.DataFrame(matriz_recetas())
        st.subheader("Matriz completa")
        if matriz_df.empty:
            st.info("Todavia no hay recetas cargadas.")
        else:
            st.dataframe(matriz_df, hide_index=True, use_container_width=True)
            st.download_button(
                "Descargar matriz_recetas.csv",
                matriz_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="matriz_recetas.csv",
                mime="text/csv",
                use_container_width=True,
            )
            xlsx = excel_bytes({"matriz_recetas": matriz_df, "productos": pd.DataFrame(resumen)})
            if xlsx:
                st.download_button(
                    "Descargar recetas.xlsx",
                    xlsx,
                    file_name="recetas.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )


def page_mesas() -> None:
    title("Gestion de mesas", "Agregar, cambiar, unir, liberar y marcar mesas.")
    mesas = get_mesas()
    st.dataframe(pd.DataFrame(mesas), hide_index=True, use_container_width=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        nueva = st.number_input("Nueva mesa numero", min_value=1, step=1)
        if st.button("Agregar mesa", use_container_width=True):
            try:
                execute("INSERT INTO mesas (numero_mesa, estado) VALUES (?, 'libre')", (int(nueva),))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with c2:
        origen = st.selectbox("Mesa origen", mesas, format_func=lambda m: f"Mesa {m['numero_mesa']}", key="mesa_origen")
        destino = st.selectbox("Mesa destino", mesas, format_func=lambda m: f"Mesa {m['numero_mesa']}", key="mesa_destino")
        same_table = (origen is not None and destino is not None and origen["id_mesa"] == destino["id_mesa"])
        if st.button("Mover / unir consumos", use_container_width=True, disabled=same_table):
            if origen is not None and destino is not None:
                execute("UPDATE pedidos_cabecera SET id_mesa = ? WHERE id_mesa = ? AND estado_comanda IN ('pendiente','en_cocina','listo','entregado')", (destino["id_mesa"], origen["id_mesa"]))
                execute("UPDATE mesas SET estado = 'libre' WHERE id_mesa = ?", (origen["id_mesa"],))
                execute("UPDATE mesas SET estado = 'ocupada' WHERE id_mesa = ?", (destino["id_mesa"],))
                registrar_auditoria("mesas", "mover_unir", f"{origen['numero_mesa']} -> {destino['numero_mesa']}")
                st.rerun()
    with c3:
        mesa_accion = st.selectbox("Accion sobre mesa", mesas, format_func=lambda m: f"Mesa {m['numero_mesa']}", key="mesa_accion")
        estado = st.selectbox("Nuevo estado", ["libre", "ocupada", "esperando_cuenta"])
        if st.button("Cambiar estado", use_container_width=True):
            if mesa_accion is not None:
                execute("UPDATE mesas SET estado = ? WHERE id_mesa = ?", (estado, mesa_accion["id_mesa"]))
                registrar_auditoria("mesas", "cambio_estado", f"{mesa_accion['numero_mesa']} {estado}")
                st.rerun()

    st.divider()
    st.subheader("Historial y anulaciones")
    mesa_hist = st.selectbox("Mesa para revisar", mesas, format_func=lambda m: f"Mesa {m['numero_mesa']}", key="mesa_historial")
    historial = pd.DataFrame()
    if mesa_hist is not None:
        historial = pd.DataFrame(rows("""
            SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda,
                   u.nombre || ' ' || u.apellido AS mozo,
                   pm.nombre AS producto,
                   pd.cantidad,
                   COALESCE(pd.cantidad_cobrada, 0) AS cobrada,
                   COALESCE(pd.cantidad_anulada, 0) AS anulada,
                   COALESCE(pd.motivo_anulacion, '') AS motivo
            FROM pedidos_cabecera pc
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.id_mesa = ?
            ORDER BY pc.fecha_hora DESC, pd.id_detalle
            LIMIT 80
        """, (mesa_hist["id_mesa"],)))
    if not historial.empty:
        st.dataframe(historial, hide_index=True, use_container_width=True)
    else:
        st.info("Sin historial para esta mesa.")

    pendientes = []
    if mesa_hist is not None:
        pendientes = detalle_mesa_renglones(mesa_hist["id_mesa"])
    if pendientes:
        st.subheader("Anular producto pendiente")
        renglon = st.selectbox(
            "Producto",
            pendientes,
            format_func=lambda r: f"Pedido #{r['id_pedido']} · {r['nombre']} · pendiente {r['pendiente']}",
        )
        cantidad = st.number_input("Cantidad a anular", min_value=1, max_value=int(renglon["pendiente"]), value=1)
        motivo = st.text_input("Motivo de anulacion", placeholder="Error de carga, cliente cancela, cortesia...")
        if st.button("Anular seleccionado", type="primary", use_container_width=True):
            if mesa_hist is not None and renglon is not None:
                res = anular_detalle(renglon["id_detalle"], int(cantidad), motivo.strip() or "Sin motivo")
                if res["ok"]:
                    registrar_auditoria("mesas", "anulacion", f"{res['producto']} x{cantidad} mesa {mesa_hist['numero_mesa']}")
                    st.success("Producto anulado.")
                    st.rerun()
                st.error(res["error"])


def _page_inventario_legacy_unused() -> None:
    title("Inventario", "Stock, compras, ajustes y alertas.")
    insumos = rows("SELECT id_insumo, nombre, stock_actual, stock_minimo, unidad_medida FROM insumos ORDER BY nombre")
    bajos = [i for i in insumos if float(i["stock_actual"]) <= float(i["stock_minimo"])]
    if bajos:
        for item in bajos:
            st.warning(f"Stock bajo: {item['nombre']} · {item['stock_actual']:.0f} / {item['stock_minimo']:.0f} {item['unidad_medida']}")
    else:
        st.success("Sin alertas de stock.")

    with st.expander("Nuevo insumo"):
        with st.form("nuevo_insumo"):
            nombre = st.text_input("Nombre")
            unidad = st.selectbox("Unidad", ["unidad", "gramos", "mililitros", "kilos", "litros"])
            stock = st.number_input("Stock inicial", min_value=0.0, step=1.0)
            minimo = st.number_input("Stock minimo", min_value=0.0, step=1.0)
            if st.form_submit_button("Crear"):
                execute("""
                    INSERT INTO insumos (nombre, stock_actual, stock_minimo, unidad_medida)
                    VALUES (?, ?, ?, ?)
                """, (nombre.strip(), stock, minimo, unidad))
                st.rerun()

    df = pd.DataFrame(insumos)
    edited = st.data_editor(df, hide_index=True, use_container_width=True, disabled=["id_insumo"])
    if st.button("Guardar inventario", type="primary"):
        conn = get_connection()
        try:
            for _, row in edited.iterrows():
                conn.execute("""
                    UPDATE insumos
                       SET nombre = ?, stock_actual = ?, stock_minimo = ?, unidad_medida = ?
                     WHERE id_insumo = ?
                """, (row["nombre"], float(row["stock_actual"]), float(row["stock_minimo"]), row["unidad_medida"], int(row["id_insumo"])))
            conn.commit()
            registrar_auditoria("inventario", "stock_actualizado", str(len(edited)))
            st.success("Inventario actualizado.")
        finally:
            conn.close()

    st.subheader("Carga rapida de compra o ajuste")
    opciones = {f"{i['nombre']} ({i['unidad_medida']})": i for i in insumos}
    elegido = st.selectbox("Insumo", list(opciones))
    cantidad = st.number_input("Cantidad a sumar", min_value=0.0, step=1.0)
    if st.button("Sumar al stock"):
        ins = opciones[elegido]
        execute("UPDATE insumos SET stock_actual = stock_actual + ? WHERE id_insumo = ?", (cantidad, ins["id_insumo"]))
        execute("""
            UPDATE stock_deposito
               SET cantidad_disponible = cantidad_disponible + ?
             WHERE id_insumo = ?
        """, (cantidad, ins["id_insumo"]))
        registrar_auditoria("inventario", "compra_ajuste", f"{ins['nombre']} +{cantidad}")
        st.rerun()


def proveedores_activos() -> list[dict]:
    return rows("""
        SELECT id_proveedor, nombre, telefono, email, notas, cuit_rut, direccion, activo
        FROM proveedores
        WHERE COALESCE(activo, 1) = 1
        ORDER BY nombre
    """)


def registrar_movimiento_stock(
    id_insumo: int,
    tipo: str,
    cantidad: float,
    descripcion: str,
    id_proveedor: int | None = None,
) -> dict:
    if cantidad <= 0:
        return {"ok": False, "error": "La cantidad debe ser mayor a cero."}
    signo = 1 if tipo in ("compra", "ajuste_entrada") else -1
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        insumo = conn.execute("""
            SELECT id_insumo, nombre, stock_actual
            FROM insumos
            WHERE id_insumo = ?
        """, (id_insumo,)).fetchone()
        if not insumo:
            raise ValueError("Insumo inexistente.")
        stock_anterior = float(insumo["stock_actual"] or 0)
        stock_nuevo = stock_anterior + signo * float(cantidad)
        if stock_nuevo < 0:
            raise ValueError("El movimiento deja stock negativo.")
        conn.execute("UPDATE insumos SET stock_actual = ? WHERE id_insumo = ?", (stock_nuevo, id_insumo))
        conn.execute("""
            INSERT OR IGNORE INTO stock_deposito (id_insumo, id_deposito, cantidad_disponible)
            VALUES (?, 1, 0)
        """, (id_insumo,))
        conn.execute("""
            UPDATE stock_deposito
               SET cantidad_disponible = ?
             WHERE id_insumo = ? AND id_deposito = 1
        """, (stock_nuevo, id_insumo))
        conn.execute("""
            INSERT INTO movimientos_stock
                (id_insumo, id_usuario, id_proveedor, tipo_movimiento, cantidad, stock_anterior, stock_nuevo, descripcion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            id_insumo,
            st.session_state.usuario["id_usuario"] if st.session_state.get("usuario") else None,
            id_proveedor,
            tipo,
            float(cantidad),
            stock_anterior,
            stock_nuevo,
            descripcion,
        ))
        conn.execute("COMMIT")
        return {"ok": True, "insumo": insumo["nombre"], "stock_nuevo": stock_nuevo}
    except Exception as exc:
        conn.execute("ROLLBACK")
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def historial_stock(limit: int = 100) -> list[dict]:
    return rows("""
        SELECT ms.fecha_hora,
               i.nombre AS insumo,
               ms.tipo_movimiento,
               ms.cantidad,
               ms.stock_anterior,
               ms.stock_nuevo,
               COALESCE(p.nombre, '') AS proveedor,
               COALESCE(u.nombre || ' ' || u.apellido, '') AS usuario,
               ms.descripcion
        FROM movimientos_stock ms
        JOIN insumos i ON i.id_insumo = ms.id_insumo
        LEFT JOIN proveedores p ON p.id_proveedor = ms.id_proveedor
        LEFT JOIN usuarios u ON u.id_usuario = ms.id_usuario
        ORDER BY ms.fecha_hora DESC, ms.id_movimiento_stock DESC
        LIMIT ?
    """, (limit,))


def page_inventario() -> None:
    title("Inventario", "Stock, compras, ajustes, mermas, proveedores e historial.")
    insumos = rows("SELECT id_insumo, nombre, stock_actual, stock_minimo, unidad_medida FROM insumos ORDER BY nombre")
    bajos = [i for i in insumos if float(i["stock_actual"]) <= float(i["stock_minimo"])]
    total_stock = sum(float(i["stock_actual"] or 0) for i in insumos)
    c1, c2, c3 = st.columns(3)
    c1.metric("Insumos", len(insumos))
    c2.metric("Stock bajo", len(bajos))
    c3.metric("Unidades totales", f"{total_stock:.0f}")

    if bajos:
        for item in bajos:
            st.warning(f"Stock bajo: {item['nombre']} | {item['stock_actual']:.0f} / {item['stock_minimo']:.0f} {item['unidad_medida']}")

    tab_stock, tab_mov, tab_prov, tab_hist = st.tabs(["Stock", "Movimientos", "Proveedores", "Historial"])
    with tab_stock:
        with st.expander("Nuevo insumo"):
            with st.form("nuevo_insumo_profesional"):
                nombre = st.text_input("Nombre")
                unidad = st.selectbox("Unidad", ["unidad", "gramos", "mililitros", "kilos", "litros"])
                stock = st.number_input("Stock inicial", min_value=0.0, step=1.0)
                minimo = st.number_input("Stock minimo", min_value=0.0, step=1.0)
                if st.form_submit_button("Crear insumo", type="primary"):
                    if not nombre.strip():
                        st.error("El nombre es obligatorio.")
                    else:
                        conn = get_connection()
                        try:
                            conn.execute("BEGIN TRANSACTION")
                            cur = conn.execute("""
                                INSERT INTO insumos (nombre, stock_actual, stock_minimo, unidad_medida)
                                VALUES (?, ?, ?, ?)
                            """, (nombre.strip(), stock, minimo, unidad))
                            id_insumo = cur.lastrowid
                            conn.execute("""
                                INSERT OR IGNORE INTO stock_deposito (id_insumo, id_deposito, cantidad_disponible)
                                VALUES (?, 1, ?)
                            """, (id_insumo, stock))
                            conn.execute("""
                                INSERT INTO movimientos_stock
                                    (id_insumo, id_usuario, tipo_movimiento, cantidad, stock_anterior, stock_nuevo, descripcion)
                                VALUES (?, ?, 'ajuste_entrada', ?, 0, ?, 'Stock inicial')
                            """, (id_insumo, st.session_state.usuario["id_usuario"], stock, stock))
                            conn.execute("COMMIT")
                            registrar_auditoria("inventario", "insumo_creado", nombre.strip())
                            st.rerun()
                        except Exception as exc:
                            conn.execute("ROLLBACK")
                            st.error(str(exc))
                        finally:
                            conn.close()

        df = pd.DataFrame(insumos)
        edited = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            disabled=["id_insumo", "stock_actual"],
            column_config={
                "stock_minimo": st.column_config.NumberColumn("Stock minimo", min_value=0, step=1),
                "unidad_medida": st.column_config.SelectboxColumn("Unidad", options=["unidad", "gramos", "mililitros", "kilos", "litros"]),
            },
        )
        if st.button("Guardar datos de insumos", type="primary", use_container_width=True):
            conn = get_connection()
            try:
                for _, row in edited.iterrows():
                    conn.execute("""
                        UPDATE insumos
                           SET nombre = ?, stock_minimo = ?, unidad_medida = ?
                         WHERE id_insumo = ?
                    """, (row["nombre"], float(row["stock_minimo"]), row["unidad_medida"], int(row["id_insumo"])))
                conn.commit()
                registrar_auditoria("inventario", "datos_insumos_actualizados", str(len(edited)))
                st.success("Inventario actualizado.")
            finally:
                conn.close()

    with tab_mov:
        if not insumos:
            st.info("Primero carga insumos.")
        else:
            proveedores = proveedores_activos()
            opciones = {f"{i['nombre']} ({i['unidad_medida']})": i for i in insumos}
            with st.form("movimiento_stock"):
                ins = opciones[st.selectbox("Insumo", list(opciones))]
                tipo = st.selectbox("Tipo de movimiento", ["compra", "ajuste_entrada", "ajuste_salida", "merma"])
                cantidad = st.number_input("Cantidad", min_value=0.01, step=1.0)
                proveedor = None
                if tipo == "compra" and proveedores:
                    proveedor = st.selectbox("Proveedor", proveedores, format_func=lambda p: p["nombre"])
                descripcion = st.text_input("Descripcion / comprobante", placeholder="Factura, motivo de ajuste o merma")
                if st.form_submit_button("Registrar movimiento", type="primary"):
                    res = registrar_movimiento_stock(
                        int(ins["id_insumo"]),
                        tipo,
                        float(cantidad),
                        descripcion.strip() or tipo,
                        int(proveedor["id_proveedor"]) if proveedor else None,
                    )
                    if res["ok"]:
                        registrar_auditoria("inventario", "movimiento_stock", f"{tipo} {res['insumo']} {cantidad}")
                        st.success(f"Movimiento registrado. Nuevo stock: {res['stock_nuevo']:.0f}")
                        st.rerun()
                    st.error(res["error"])

    with tab_prov:
        st.info("La gestion completa de proveedores esta disponible en el modulo **Proveedores** (menu lateral).")
        proveedores_todos = rows("""
            SELECT id_proveedor, nombre, telefono, email, notas, cuit_rut, direccion, activo
            FROM proveedores ORDER BY nombre
        """)

        with st.expander("Nuevo proveedor (basico)"):
            with st.form("nuevo_proveedor_rapido"):
                nombre = st.text_input("Nombre proveedor")
                telefono = st.text_input("Telefono")
                email = st.text_input("Email")
                if st.form_submit_button("Crear proveedor", type="primary"):
                    if not nombre.strip():
                        st.error("El nombre es obligatorio.")
                    else:
                        try:
                            execute("""
                                INSERT INTO proveedores (nombre, telefono, email, notas, cuit_rut, direccion, activo)
                                VALUES (?, ?, ?, '', '', '', 1)
                            """, (nombre.strip(), telefono.strip(), email.strip()))
                            registrar_auditoria("inventario", "proveedor_creado", nombre.strip())
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

        if proveedores_todos:
            df_prov = pd.DataFrame(proveedores_todos)
            df_prov["activo"] = df_prov["activo"].astype(bool)
            edited_prov = st.data_editor(df_prov, hide_index=True, use_container_width=True, disabled=["id_proveedor"])
            if st.button("Guardar proveedores", type="primary", use_container_width=True):
                conn = get_connection()
                try:
                    for _, row in edited_prov.iterrows():
                        conn.execute("""
                            UPDATE proveedores
                               SET nombre = ?, telefono = ?, email = ?, notas = ?,
                                   cuit_rut = ?, direccion = ?, activo = ?
                             WHERE id_proveedor = ?
                        """, (row["nombre"], row["telefono"], row["email"], row["notas"],
                              row.get("cuit_rut", ""), row.get("direccion", ""),
                              1 if bool(row["activo"]) else 0, int(row["id_proveedor"])))
                    conn.commit()
                    registrar_auditoria("inventario", "proveedores_actualizados", str(len(edited_prov)))
                    st.success("Proveedores actualizados.")
                finally:
                    conn.close()
        else:
            st.info("Todavia no hay proveedores.")

    with tab_hist:
        hist = pd.DataFrame(historial_stock(150))
        if hist.empty:
            st.info("Sin movimientos de stock.")
        else:
            st.dataframe(hist, hide_index=True, use_container_width=True)
            st.download_button(
                "Descargar movimientos_stock.csv",
                hist.to_csv(index=False).encode("utf-8-sig"),
                file_name="movimientos_stock.csv",
                mime="text/csv",
                use_container_width=True,
            )


def page_reportes() -> None:
    title("Reportes", "Ventas, productos, mozos, medios de pago y caja.")

    tab_analisis, tab_comparativa = st.tabs(["Analisis", "Comparativa periodos"])

    with tab_analisis:
        _render_reporte_analisis()

    with tab_comparativa:
        _render_reporte_comparativa()


def _report_params() -> tuple[str, str]:
    c1, c2 = st.columns(2)
    desde = c1.date_input("Desde", value=datetime.now().date().replace(day=1), key="rep_desde")
    hasta = c2.date_input("Hasta", value=datetime.now().date(), key="rep_hasta")
    return str(desde), str(hasta)


def _render_reporte_analisis():
    desde, hasta = _report_params()
    params = (desde, hasta)

    ventas = pd.DataFrame(rows("""
        SELECT DATE(fecha_hora) AS dia,
               SUM(subtotal) AS subtotal,
               SUM(total) AS total_cobrado
        FROM pagos_mesa
        WHERE DATE(fecha_hora) BETWEEN ? AND ?
        GROUP BY DATE(fecha_hora)
        ORDER BY dia
    """, params))
    total = float(ventas["subtotal"].sum()) if not ventas.empty else 0
    pedidos = (one("""
        SELECT COUNT(*) AS cnt FROM pagos_mesa
        WHERE DATE(fecha_hora) BETWEEN ? AND ?
    """, params) or {"cnt": 0})["cnt"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ventas subtotal", money(total))
    c2.metric("Pedidos cobrados", int(pedidos))
    c3.metric("Ticket promedio", money(total / pedidos if pedidos else 0))
    dias_con_ventas = len(ventas)
    c4.metric("Dias con ventas", dias_con_ventas)

    if not ventas.empty:
        st.plotly_chart(px.bar(ventas, x="dia", y="subtotal", title="Ventas diarias"), use_container_width=True)

    col1, col2 = st.columns(2)
    productos = pd.DataFrame(rows("""
        SELECT pm.nombre AS producto,
               SUM(pgd.cantidad) AS cantidad,
               SUM(pgd.cantidad * pgd.precio_unitario) AS ingreso
        FROM pago_detalle pgd
        JOIN pedido_detalle pd ON pd.id_detalle = pgd.id_detalle
        JOIN pagos_mesa pg ON pg.id_pago = pgd.id_pago
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE DATE(pg.fecha_hora) BETWEEN ? AND ?
        GROUP BY pm.id_producto, pm.nombre
        ORDER BY cantidad DESC
        LIMIT 10
    """, params))
    mozos = pd.DataFrame(rows("""
        SELECT u.nombre || ' ' || u.apellido AS mozo,
               COUNT(DISTINCT pg.id_pago) AS pedidos,
               SUM(pg.total) AS ventas
        FROM pagos_mesa pg
        LEFT JOIN usuarios u ON u.id_usuario = pg.id_usuario
        WHERE DATE(pg.fecha_hora) BETWEEN ? AND ?
        GROUP BY u.id_usuario
        ORDER BY ventas DESC
    """, params))

    with col1:
        st.subheader("Top productos")
        if productos.empty:
            st.info("Sin ventas en el período.")
        else:
            st.dataframe(productos, hide_index=True, use_container_width=True)
            if not mozos.empty:
                st.plotly_chart(px.bar(mozos, x="mozo", y="ventas",
                    title="Ventas por mozo", color="mozo"), use_container_width=True)
    with col2:
        st.subheader("Ventas por mozo")
        if mozos.empty:
            st.info("Sin ventas en el período.")
        else:
            st.dataframe(mozos, hide_index=True, use_container_width=True)

    medios = pd.DataFrame(rows("""
        SELECT COALESCE(NULLIF(medio_pago, ''), 'Sin dato') AS medio_pago,
               COUNT(*) AS pagos,
               SUM(total) AS total
        FROM pagos_mesa
        WHERE DATE(fecha_hora) BETWEEN ? AND ?
        GROUP BY COALESCE(NULLIF(medio_pago, ''), 'Sin dato')
    """, params))

    col_m1, col_m2 = st.columns([1, 1])
    with col_m1:
        st.subheader("Medios de pago")
        if medios.empty:
            st.info("Sin registros.")
        else:
            st.dataframe(medios, hide_index=True, use_container_width=True)
    with col_m2:
        if not medios.empty:
            st.subheader("Distribucion")
            st.plotly_chart(px.pie(medios, values="total", names="medio_pago",
                title="Distribucion por medio de pago", hole=0.4), use_container_width=True)

    _render_export_section(desde, hasta, ventas, productos, mozos, medios, total, pedidos)


def _render_export_section(desde: str, hasta: str,
                           ventas: pd.DataFrame, productos: pd.DataFrame,
                           mozos: pd.DataFrame, medios: pd.DataFrame,
                           total: float = 0, pedidos: int = 0):
    st.subheader("Exportar")
    resumen = {
        "ventas_diarias": ventas,
        "top_productos": productos,
        "ventas_mozo": mozos,
        "medios_pago": medios,
        "stock": pd.DataFrame(rows("SELECT nombre, stock_actual, stock_minimo, unidad_medida FROM insumos ORDER BY nombre")),
        "movimientos_stock": pd.DataFrame(historial_stock(1000)),
        "proveedores": pd.DataFrame(rows("SELECT nombre, telefono, email, notas, cuit_rut, activo FROM proveedores ORDER BY nombre")),
        "caja": pd.DataFrame(rows("SELECT * FROM cajas_diarias ORDER BY fecha_apertura DESC")),
    }

    pdf = _pdf_reporte_analisis(desde, hasta, ventas, productos, mozos, medios, total, pedidos, resumen)
    st.download_button("📄 Descargar reporte analisis PDF", pdf,
                       file_name=f"reporte_analisis_{desde}_{hasta}.pdf",
                       mime="application/pdf", use_container_width=True)
    xlsx = excel_bytes(resumen)
    if xlsx:
        st.download_button(
            "Descargar reporte_completo.xlsx",
            xlsx,
            file_name=f"reporte_completo_{desde}_{hasta}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    for nombre, df in resumen.items():
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            f"Descargar {nombre}.csv",
            csv,
            file_name=f"{nombre}_{desde}_{hasta}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # Print-friendly HTML report
    html_parts = [f"""<html><head><meta charset="utf-8"><style>
        body {{ font-family: sans-serif; padding: 20px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
        th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
        th {{ background: #f0f0f0; }}
        .kpi {{ font-size: 1.4em; margin: 10px 0; }}
    </style></head><body>
    <h1>Reporte {desde} a {hasta}</h1>
    <div class="kpi">Ventas: {money(total)} | Pedidos: {int(pedidos)}</div>
    """]
    for nombre, df in resumen.items():
        if not df.empty:
            html_parts.append(f"<h2>{nombre.replace('_',' ').title()}</h2>{df.head(50).to_html(index=False)}")
    html_parts.append("</body></html>")
    html_str = "\n".join(html_parts)
    st.download_button(" 🖨️ Reporte HTML (imprimible)", html_str.encode("utf-8"),
                       file_name=f"reporte_{desde}_{hasta}.html",
                       mime="text/html", use_container_width=True)


def _pdf_reporte_analisis(desde, hasta, ventas, productos, mozos, medios, total, pedidos, resumen):
    ticket_prom = total / pedidos if pedidos else 0
    sections = []

    if not ventas.empty:
        rows_tbl = [[str(r["dia"]), money(r["subtotal"]), money(r["total_cobrado"])]
                     for _, r in ventas.iterrows()]
        sections.append(("Ventas diarias",
                         data_table(["Fecha", "Subtotal", "Total cobrado"], rows_tbl, right_align_cols={1, 2})))

    if not productos.empty:
        rows_tbl = [[r["producto"], str(int(r["cantidad"])), money(r["ingreso"])]
                     for _, r in productos.iterrows()]
        sections.append(("Top 10 productos",
                         data_table(["Producto", "Cantidad", "Ingreso"], rows_tbl, right_align_cols={1, 2})))

    if not mozos.empty:
        rows_tbl = [[r["mozo"], str(r["pedidos"]), money(r["ventas"])]
                     for _, r in mozos.iterrows()]
        sections.append(("Ventas por mozo",
                         data_table(["Mozo", "Pedidos", "Ventas"], rows_tbl, right_align_cols={1, 2})))

    if not medios.empty:
        rows_tbl = [[r["medio_pago"], str(r["pagos"]), money(r["total"])]
                     for _, r in medios.iterrows()]
        sections.append(("Medios de pago",
                         data_table(["Medio", "Pagos", "Total"], rows_tbl, right_align_cols={1, 2})))

    for key in ["stock", "movimientos_stock", "proveedores", "caja"]:
        df = resumen.get(key)
        if df is not None and not df.empty:
            rows_tbl = [[str(v) for v in r] for r in df.head(50).to_numpy()]
            headers = [str(c) for c in df.columns]
            sections.append((key.replace("_", " ").title(),
                             data_table(headers, rows_tbl, right_align_cols=set())))

    usuario = st.session_state.get("usuario", {})
    nombre = f"{usuario.get('nombre', '')} {usuario.get('apellido', '')}".strip() or "sistema"

    return generate_pdf(
        title="Reporte de analisis",
        subtitle=f"Periodo: {desde} a {hasta}",
        kpis=[
            ("Ventas totales", money(total)),
            ("Pedidos", str(int(pedidos))),
            ("Ticket promedio", money(ticket_prom)),
            ("Dias con ventas", str(len(ventas))),
        ],
        sections=sections,
        usuario=nombre,
        auditoria=True,
    )


def _render_reporte_comparativa():
    st.markdown("**Comparar dos periodos**")
    c1, c2 = st.columns(2)
    p1_desde = c1.date_input("Periodo 1 desde", value=datetime.now().date().replace(day=1), key="cp1_d")
    p1_hasta = c1.date_input("Periodo 1 hasta", value=datetime.now().date(), key="cp1_h")
    p2_desde = c2.date_input("Periodo 2 desde", key="cp2_d")
    p2_hasta = c2.date_input("Periodo 2 hasta", key="cp2_h")

    def _periodo(d, h):
        row = one("""
            SELECT COUNT(*) AS pedidos,
                   COALESCE(SUM(subtotal), 0) AS ventas,
                   COALESCE(SUM(servicio), 0) AS servicio
            FROM pagos_mesa
            WHERE DATE(fecha_hora) BETWEEN ? AND ?
        """, (str(d), str(h)))
        return row or {"pedidos": 0, "ventas": 0, "servicio": 0}

    p1 = _periodo(p1_desde, p1_hasta)
    p2 = _periodo(p2_desde, p2_hasta)

    diff_ventas = float(p1["ventas"]) - float(p2["ventas"])
    diff_pct = (diff_ventas / float(p2["ventas"]) * 100) if float(p2["ventas"]) else 0

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Periodo 1 ventas", money(p1["ventas"]))
    col_b.metric("Periodo 2 ventas", money(p2["ventas"]),
                 delta=f"{diff_pct:+.1f}%" if diff_pct else None)
    col_c.metric("Diferencia", money(diff_ventas))

    comp = pd.DataFrame({
        "Metrica": ["Pedidos", "Ventas", "Servicio", "Ticket prom."],
        "Periodo 1": [int(p1["pedidos"]), money(p1["ventas"]), money(p1["servicio"]),
                      money(float(p1["ventas"]) / int(p1["pedidos"]) if int(p1["pedidos"]) else 0)],
        "Periodo 2": [int(p2["pedidos"]), money(p2["ventas"]), money(p2["servicio"]),
                      money(float(p2["ventas"]) / int(p2["pedidos"]) if int(p2["pedidos"]) else 0)],
    })
    st.dataframe(comp, hide_index=True, use_container_width=True)




def page_panel() -> None:
    procesar_cola_sincronizacion()
    offline_banner()
    title("Panel administrador", "Control general de salon, cocina, caja, stock y personal.")
    auto_refresh(15)

    estados = one("""
        SELECT
            SUM(CASE WHEN estado='libre' THEN 1 ELSE 0 END) AS libres,
            SUM(CASE WHEN estado='ocupada' THEN 1 ELSE 0 END) AS ocupadas,
            SUM(CASE WHEN estado='esperando_cuenta' THEN 1 ELSE 0 END) AS cuenta
        FROM mesas
    """) or {"libres": 0, "ocupadas": 0, "cuenta": 0}
    pedidos = one("""
        SELECT
            SUM(CASE WHEN estado_comanda='pendiente' THEN 1 ELSE 0 END) AS pendientes,
            SUM(CASE WHEN estado_comanda='en_cocina' THEN 1 ELSE 0 END) AS cocina,
            SUM(CASE WHEN estado_comanda='listo' THEN 1 ELSE 0 END) AS listos
        FROM pedidos_cabecera
        WHERE estado_comanda IN ('pendiente','en_cocina','listo')
    """) or {"pendientes": 0, "cocina": 0, "listos": 0}
    caja = caja_abierta()
    stock_bajo = (one("""
        SELECT COUNT(*) AS total
        FROM insumos
        WHERE stock_actual <= stock_minimo
    """) or {"total": 0})["total"]

    hoy = datetime.now().date().isoformat()
    ventas_hoy = (one("""
        SELECT COALESCE(SUM(total), 0) AS total
        FROM pagos_mesa
        WHERE DATE(fecha_hora) = ?
    """, (hoy,)) or {"total": 0})["total"]
    turnos_activos = (one("""
        SELECT COUNT(*) AS total FROM turnos_personal
        WHERE fecha = ? AND estado = 'activo'
    """, (hoy,)) or {"total": 0})["total"]

    top = st.columns(8)
    with top[0]:
        stat_card("Libres", estados["libres"] or 0, "#2e7d50")
    with top[1]:
        stat_card("Ocupadas", estados["ocupadas"] or 0, "#285f83")
    with top[2]:
        stat_card("En cuenta", estados["cuenta"] or 0, "#b87419")
    with top[3]:
        stat_card("Cocina", (pedidos["pendientes"] or 0) + (pedidos["cocina"] or 0), "#9f2f24")
    with top[4]:
        stat_card("Listos", pedidos["listos"] or 0, "#2e7d50")
    with top[5]:
        stat_card("Stock bajo", stock_bajo or 0, "#b33a34")
    with top[6]:
        stat_card("Ventas hoy", money(ventas_hoy), "#1565c0")
    with top[7]:
        stat_card("En turno", turnos_activos or 0, "#2e7d32")

    staff = pd.DataFrame(rows("""
        SELECT rol, COUNT(*) AS activos
        FROM usuarios
        WHERE COALESCE(activo, 1) = 1
        GROUP BY rol
        ORDER BY rol
    """))
    caja_texto = "Cerrada"
    if caja:
        caja_texto = f"Abierta #{caja['id_caja']} | ventas {money(caja['monto_ventas'])}"

    col_a, col_b, col_c = st.columns([1.15, 1.15, 1])
    with col_a:
        st.subheader("Personal activo")
        if staff.empty:
            st.info("Sin personal activo.")
        else:
            st.dataframe(staff, hide_index=True, use_container_width=True)
    with col_b:
        st.subheader("Caja")
        st.markdown(
            f"<div class='card'><b>{escape(caja_texto)}</b><br><span class='muted'>Apertura, egresos y cierres se gestionan desde Caja.</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="card">
                <b>Terminales</b><br>
                <span class="muted">/ ?terminal=mozo</span><br>
                <span class="muted">/ ?terminal=cocina</span><br>
                <span class="muted">/ ?terminal=caja</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_c:
        st.subheader("Cocina")
        st.markdown(
            f"""
            <div class="card">
                <div class="line"><span>Pendientes</span><b>{pedidos['pendientes'] or 0}</b></div>
                <div class="line"><span>En preparacion</span><b>{pedidos['cocina'] or 0}</b></div>
                <div class="line"><span>Listos</span><b>{pedidos['listos'] or 0}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    mesas_activas = pd.DataFrame(rows("""
        SELECT m.numero_mesa AS mesa,
               m.estado,
               COUNT(DISTINCT pc.id_pedido) AS pedidos,
               COALESCE(SUM((pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)), 0) AS subtotal
        FROM mesas m
        JOIN pedidos_cabecera pc ON pc.id_mesa = m.id_mesa
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
          AND (pd.cantidad - COALESCE(pd.cantidad_cobrada, 0) - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY m.id_mesa, m.numero_mesa, m.estado
        ORDER BY m.numero_mesa
    """))
    if not mesas_activas.empty:
        mesas_activas["total_estimado"] = mesas_activas["subtotal"].apply(lambda v: float(v) + service_amount(float(v)))
        st.subheader("Mesas activas")
        st.dataframe(mesas_activas, hide_index=True, use_container_width=True)

    eventos = pd.DataFrame(rows("""
        SELECT fecha_hora, modulo, accion, detalle
        FROM auditoria_eventos
        ORDER BY fecha_hora DESC
        LIMIT 20
    """))
    st.subheader("Ultimos eventos")
    st.dataframe(eventos, hide_index=True, use_container_width=True)

    pdf = _pdf_panel(estados, pedidos, caja, stock_bajo, ventas_hoy, turnos_activos, staff, mesas_activas, eventos)
    st.download_button("📄 Descargar resumen PDF", pdf,
                       file_name=f"panel_{datetime.now():%Y%m%d_%H%M}.pdf",
                       mime="application/pdf", use_container_width=True)


def _pdf_panel(estados, pedidos, caja, stock_bajo, ventas_hoy, turnos_activos, staff, mesas_activas, eventos):
    today = datetime.now().date().isoformat()
    sections = []

    rows_tbl = [
        ["Libres", str(estados.get("libres", 0))],
        ["Ocupadas", str(estados.get("ocupadas", 0))],
        ["En cuenta", str(estados.get("cuenta", 0))],
        ["Pendientes cocina", str(pedidos.get("pendientes", 0))],
        ["En cocina", str(pedidos.get("cocina", 0))],
        ["Listos", str(pedidos.get("listos", 0))],
        ["Stock bajo", str(stock_bajo)],
        ["Ventas hoy", money(ventas_hoy)],
        ["Turnos activos", str(turnos_activos)],
    ]
    sections.append(("Resumen de indicadores",
                     data_table(["Indicador", "Valor"], rows_tbl, right_align_cols={1})))

    if caja:
        rows_caja = [
            ["Caja Nro", str(caja.get("id_caja", ""))],
            ["Cajero", caja.get("cajero", "-")],
            ["Monto apertura", money(caja.get("monto_apertura", 0))],
            ["Ventas acumuladas", money(caja.get("monto_ventas", 0))],
        ]
        sections.append(("Caja", data_table(["Campo", "Valor"], rows_caja, right_align_cols={1})))

    if not staff.empty:
        rows_staff = [[r["rol"], str(r["activos"])] for _, r in staff.iterrows()]
        sections.append(("Personal activo", data_table(["Rol", "Activos"], rows_staff, right_align_cols={1})))

    if not mesas_activas.empty:
        rows_mesas = [
            [str(r["mesa"]), r["estado"], str(r["pedidos"]), money(r["subtotal"])]
            for _, r in mesas_activas.head(20).iterrows()
        ]
        sections.append(("Mesas activas",
                         data_table(["Mesa", "Estado", "Pedidos", "Subtotal"], rows_mesas, right_align_cols={2, 3})))

    if not eventos.empty:
        rows_ev = [
            [str(r["fecha_hora"])[:19], r["modulo"], r["accion"]]
            for _, r in eventos.iterrows()
        ]
        sections.append(("Ultimos eventos del sistema",
                         data_table(["Fecha", "Modulo", "Accion"], rows_ev, right_align_cols=set())))

    usuario = st.session_state.get("usuario", {})
    nombre = f"{usuario.get('nombre', '')} {usuario.get('apellido', '')}".strip() or "sistema"

    return generate_pdf(
        title="Panel de control - Resumen ejecutivo",
        subtitle=f"Fecha: {today}",
        kpis=[
            ("Ventas hoy", money(ventas_hoy)),
            ("Stock bajo", str(stock_bajo)),
            ("Turnos activos", str(turnos_activos)),
            ("Mesas ocupadas", str(estados.get("ocupadas", 0))),
        ],
        sections=sections,
        usuario=nombre,
        auditoria=True,
    )


def public_status_page() -> None:
    inject_styles()
    title("Estado publico", "Disponibilidad basica del sistema.")
    cloud = cloud_status()
    try:
        conteos = system_counts()
        usuarios = conteos.get("usuarios", 0)
        mesas = conteos.get("mesas", 0)
        productos = conteos.get("productos", 0)
        estado = rows("SELECT clave, valor, actualizado_en FROM sistema_estado ORDER BY clave")
        db_ok = True
    except Exception:
        estado = []
        usuarios = mesas = productos = 0
        db_ok = False

    cols = st.columns(4)
    with cols[0]:
        stat_card("App", "Online", "#2e7d50")
    with cols[1]:
        stat_card("Base", "OK" if db_ok else "Error", "#2e7d50" if db_ok else "#b33a34")
    with cols[2]:
        stat_card("Modo", "Supabase" if using_postgres() else "Local", "#285f83")
    with cols[3]:
        stat_card("Version", app_build_label(), "#9f2f24")

    st.markdown(
        f"""
        <div class="card">
            <div class="line"><span>DATABASE_URL</span><b>{'Configurado' if cloud.ready_for_postgres else 'No configurado'}</b></div>
            <div class="line"><span>Usuarios</span><b>{usuarios}</b></div>
            <div class="line"><span>Mesas</span><b>{mesas}</b></div>
            <div class="line"><span>Productos</span><b>{productos}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if estado:
        st.subheader("Estado guardado")
        st.dataframe(pd.DataFrame(estado), hide_index=True, use_container_width=True)


def main() -> None:
    inject_styles()
    keep_sidebar_open()
    init_session()
    apply_terminal_autologin()
    terminal_mode_styles()

    # Botón expandir flotante (se muestra solo cuando está colapsado)
    if st.session_state.get("sidebar_collapsed"):
        st.markdown("""
        <style>
        div[data-testid="stButton"].expand-btn > button {
            position: fixed !important;
            left: 0 !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
            z-index: 9999 !important;
            width: 34px !important;
            height: 52px !important;
            border-radius: 0 8px 8px 0 !important;
            border-left: none !important;
            padding: 0 !important;
            font-size: 16px !important;
        }
        </style>
        """, unsafe_allow_html=True)
        expand_container = st.container()
        with expand_container:
            st.markdown('<div class="expand-btn">', unsafe_allow_html=True)
            if st.button("▶", key="btn_expand", help="Mostrar panel"):
                st.session_state.sidebar_collapsed = False
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    # CSS para ocultar/mostrar el sidebar
    if st.session_state.get("sidebar_collapsed"):
        st.markdown("""
        <style>
        section[data-testid="stSidebar"] {
            transform: translateX(-100%) !important;
            width: 0 !important;
            min-width: 0 !important;
            transition: all 0.3s ease !important;
        }
        .main .block-container {
            margin-left: 0 !important;
            padding-left: 0.5rem !important;
        }
        </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <style>
        section[data-testid="stSidebar"] {
            transition: all 0.3s ease !important;
        }
        </style>
        """, unsafe_allow_html=True)

    if st.query_params.get("status") == "public":
        public_status_page()
        st.stop()

    if st.session_state.get("usuario") is None:
        login()
        st.stop()

    if st.session_state.get("force_password_change") and not st.session_state.get("terminal_lock"):
        force_password_change_page()
        st.stop()

    sidebar()
    module = st.session_state.modulo

    if module == "Panel":
        page_panel()
    elif module == "Mozo":
        page_mozo()
    elif module == "Cocina":
        page_cocina()
    elif module == "Caja":
        page_caja()
    elif module == "Reportes":
        page_reportes()
    elif module == "Usuarios":
        page_usuarios()
    elif module == "Menu":
        page_menu()
    elif module == "Recetas":
        page_recetas()
    elif module == "Mesas":
        page_mesas()
    elif module == "Inventario":
        page_inventario()
    elif module == "Proveedores":
        page_gestion_proveedores()
    elif module == "Promociones":
        page_promociones()
    elif module == "Turnos":
        page_gestion_turnos()
    elif module == "Facturación":
        page_facturacion_electronica()
    elif module == "Sistema":
        page_sistema()
    elif module == "Backups":
        page_backups()


if __name__ == "__main__":
    main()

