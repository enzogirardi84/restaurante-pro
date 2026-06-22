"""
Helper/utility/data functions extracted from sistema_restaurante.py.
Does NOT include page_*() view functions, CSS functions, or Streamlit page setup.
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import streamlit as st

from database import (
    DB_PATH, active_order_cutoff, avanzar_estado, database_label, get_connection, init_db,
    marcar_pedido_entregado, obtener_pedidos_por_estado, registrar_auditoria, using_postgres,
)
from cloud_config import app_name, cloud_status, database_url_warnings, default_service_percentage, masked_status_table
from security import hash_password, is_password_hash, login_logo_path, login_logo_tag, verify_password
from access_utils import recovery_system_access, validate_default_system_access
from order_utils import normalize_order_cart
from permission_utils import modules_for_role

APP_TITLE = app_name("Restaurante Pro")
APP_VERSION = "2026.06.08"
SERVICIO_PORCENTAJE = default_service_percentage(10)
BACKUP_DIR = Path(__file__).parent.parent / "backups"
SYSTEM_USERNAME = "anahigilardi"
SYSTEM_PASSWORD = "1999"
LEGACY_SYSTEM_USERNAME = "sistema"
LEGACY_SYSTEM_PASSWORD = "restaurante"
LEGACY_ADMIN_USERNAME = "admin"
LEGACY_ADMIN_PASSWORD = "admin"


def app_build_label() -> str:
    sha = os.environ.get("GITHUB_SHA", "").strip()
    return sha[:7] if sha else APP_VERSION


AUTO_TERMINALS = {
    "mozo": "Mozo",
    "cocina": "Cocina",
    "caja": "Caja",
    "panel": "Panel",
}

PRESET_NOTES = [
    "Sin cebolla", "Sin sal", "Sin azúcar", "Sin TACC", "Sin lactosa",
    "Vegetariano", "Vegano", "Bien cocido", "Poco cocido", "Sin picante",
    "Con extra de queso", "A punto", "Sin hielo", "Con hielo", "Sin gas",
]


def money(value: float | int | str | Decimal | None) -> str:
    if value in (None, ""):
        amount = Decimal("0")
    else:
        try:
            if isinstance(value, str):
                clean = value.strip().replace("$", "").replace(" ", "")
                if "," in clean and "." in clean:
                    clean = clean.replace(".", "").replace(",", ".")
                else:
                    clean = clean.replace(",", ".")
                amount = Decimal(clean or "0")
            else:
                amount = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            amount = Decimal("0")
    return f"${amount:,.0f}".replace(",", ".")


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
    finally:
        conn.close()


def one(sql: str, params: tuple = ()) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> None:
    conn = get_connection()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


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
            """, (usuario.strip().lower(), password_hash, rol))
        except Exception:
            conn.execute("""
                INSERT OR REPLACE INTO accesos_sistema (usuario, password_hash, activo, rol)
                VALUES (?, ?, 1, ?)
            """, (usuario.strip().lower(), password_hash, rol))
        conn.commit()
    finally:
        conn.close()


def active_system_accesses() -> list[dict]:
    return rows("""
        SELECT usuario
        FROM accesos_sistema
        WHERE activo = 1
        ORDER BY usuario
    """)


def authenticate_system_access(usuario: str, password: str) -> str | None:
    clean_user = usuario.strip().lower()
    if not clean_user:
        return None

    default_access = validate_default_system_access(clean_user, password)
    if default_access:
        return default_access

    try:
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


def init_session() -> None:
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
    logo_path = login_logo_path()
    logo_html = login_logo_tag()
    st.markdown(
        """
        <style>
            [data-testid="stAppViewContainer"] > .main {
                background: var(--color-pergamino) !important;
                font-family: 'Libre Caslon Text', serif !important;
            }
            [data-testid="stAppViewContainer"] > .main > .block-container {
                max-width: 420px !important;
                margin: 42px auto 0 !important;
                padding-top: 0 !important;
            }
            .login-header {
                text-align: center;
                margin: 0 auto 22px;
            }
            .login-header .login-logo-img {
                width: 118px;
                height: 118px;
                object-fit: cover;
                display: block;
                margin: 0 auto 12px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if not logo_path.exists():
        logo_html = ""
    st.markdown(
        f'<div class="login-header">{logo_html}<div class="login-badge">SISTEMA</div>'
        '<div class="login-title">Restaurante Pro</div><div class="login-separator">\u2666</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("""<label class="login-label">USUARIO</label>""", unsafe_allow_html=True)
    usuario = st.text_input("", value="", placeholder="Ingrese su usuario", label_visibility="collapsed")
    st.markdown("""<label class="login-label">CONTRASEÑA</label>""", unsafe_allow_html=True)
    password = st.text_input("", type="password", placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022", label_visibility="collapsed")
    clean_login_user = str(usuario or "").strip().lower()
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
    st.markdown(
        f"""
        <div class="app-header">
            <div class="page-title">Cambiar acceso inicial</div>
            <div class="page-subtitle">Por seguridad, cambia la contrasena predeterminada antes de continuar.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
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
    logo_path = login_logo_path()
    logo_html = login_logo_tag()
    if logo_path.exists() and logo_html:
        st.sidebar.markdown(
            f'<div class="sidebar-logo-top">{logo_html}</div>',
            unsafe_allow_html=True,
        )
    st.sidebar.markdown(
        f"""
        <div style="padding:0.35rem 0 0.8rem;border-bottom:1px solid rgba(255,255,255,0.12);margin-bottom:0.9rem">
            <div style="font-size:1.08rem;font-weight:850;color:white">{APP_TITLE}</div>
            <div style="margin-top:0.55rem;padding:0.62rem;border:1px solid rgba(255,255,255,0.12);border-radius:8px;background:rgba(255,255,255,0.04)">
                <div style="font-weight:800;color:white">{escape(user['nombre'])} {escape(user['apellido'])}</div>
                <div style="font-size:0.82rem;color:#d8d2c8;text-transform:capitalize">{escape(user['rol'])}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.title(APP_TITLE)
    st.sidebar.caption(f"{user['nombre']} {user['apellido']} · {user['rol']}")
    opciones = allowed_modules(user)
    if st.session_state.modulo not in opciones:
        st.session_state.modulo = opciones[0]
    for opt in opciones:
        activo = opt == st.session_state.modulo
        clase = "primary" if activo else "secondary"
        if st.sidebar.button(opt, key=f"nav_{opt}", type=clase, use_container_width=True):
            st.session_state.modulo = opt
            st.rerun()
    st.sidebar.divider()
    from components.turnos_utils import widget_check_in_out as _widget
    _widget()
    st.sidebar.divider()
    if st.session_state.get("terminal_lock"):
        st.sidebar.caption("Terminal automatico")
    elif st.sidebar.button("Cerrar sesion", use_container_width=True):
        registrar_auditoria("login", "salida", str(user["id_usuario"]))
        st.session_state.clear()
        st.rerun()


def get_menu(active_only: bool = True) -> list[dict]:
    try:
        from supabase import create_client
        from cloud_config import supabase_url, get_secret
        url = supabase_url()
        key = get_secret("SUPABASE_ANON_KEY") or get_secret("SUPABASE_SERVICE_ROLE_KEY")
        if url and key:
            sb = create_client(url, key)
            query = sb.table("productos_menu").select(
                "id_producto, nombre, precio_venta, categoria, activo"
            )
            if active_only:
                query = query.eq("activo", 1)
            resp = query.order("categoria").order("nombre").execute()
            if resp.data:
                productos = [dict(p) for p in resp.data]
                for producto in productos:
                    precio_original = float(producto["precio_venta"] or 0)
                    precio_final = calcular_precio_promocion(producto["categoria"], precio_original)
                    producto["precio_original"] = precio_original
                    producto["precio_final"] = precio_final
                    producto["descuento_aplicado"] = max(precio_original - precio_final, 0)
                return productos
    except Exception:
        pass

    where = "WHERE activo = 1" if active_only else ""
    productos = rows(f"""
        SELECT id_producto, nombre, precio_venta, categoria, activo
        FROM productos_menu
        {where}
        ORDER BY categoria, nombre
    """)
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
        WHERE TRIM(LOWER(rol)) = 'mozo'
          AND COALESCE(activo, 1) = 1
        ORDER BY nombre, apellido
    """)


def get_personal(rol: str | None = None, active_only: bool = False) -> list[dict]:
    filtros = []
    params: list = []
    if rol:
        filtros.append("TRIM(LOWER(rol)) = TRIM(LOWER(?))")
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
                WHEN 'administrador' THEN 1
                WHEN 'caja' THEN 2
                WHEN 'mozo' THEN 3
                WHEN 'cocina' THEN 4
                ELSE 5
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
        for item in items:
            producto = conn.execute("""
                SELECT id_producto, precio_venta, categoria
                FROM productos_menu
                WHERE id_producto = ? AND activo = 1
            """, (item["id_producto"],)).fetchone()
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


def kds_priority_score(minutes: int, estado: str = "pendiente") -> float:
    """Prioridad = (tiempo_espera_min × 1.5) + urgencia_base.
       Urgencia base: pendiente=5, en_cocina=3, listo=1.
    """
    urgencia = {"pendiente": 5, "en_cocina": 3, "listo": 1}.get(estado, 0)
    return float(minutes) * 1.5 + urgencia


def pedidos_cocina_detallados() -> list[dict]:
    cutoff = active_order_cutoff()
    pedidos = rows("""
        SELECT pc.id_pedido,
               pc.fecha_hora,
               pc.estado_comanda,
               m.numero_mesa,
                u.nombre || ' ' || u.apellido AS mozo
         FROM pedidos_cabecera pc
         JOIN mesas m ON m.id_mesa = pc.id_mesa
         JOIN usuarios u ON u.id_usuario = pc.id_usuario
         WHERE TRIM(LOWER(pc.estado_comanda)) IN ('pendiente', 'en_cocina', 'listo')
           AND pc.fecha_hora >= ?
         ORDER BY pc.fecha_hora ASC
    """, (cutoff,))
    if not pedidos:
        return []
    ids = tuple(int(p["id_pedido"]) for p in pedidos)
    placeholders = ",".join("?" for _ in ids)
    detalles = rows(f"""
        SELECT pd.id_pedido,
               pm.nombre,
               SUM(pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) AS cantidad,
               TRIM(COALESCE(pd.observaciones, '')) AS observaciones
        FROM pedido_detalle pd
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pd.id_pedido IN ({placeholders})
          AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pd.id_pedido, pm.nombre, TRIM(COALESCE(pd.observaciones, ''))
        ORDER BY pm.categoria, pm.nombre
    """, ids)
    por_pedido: dict[int, list[dict]] = {}
    for item in detalles:
        por_pedido.setdefault(int(item["id_pedido"]), []).append(item)
    armados = []
    for pedido in pedidos:
        pedido["items"] = por_pedido.get(int(pedido["id_pedido"]), [])
        if not pedido["items"]:
            pedido["items"] = [{
                "nombre": "Pedido sin detalle cargado",
                "cantidad": 1,
                "observaciones": "Revisar sincronizacion",
            }]
        mins = elapsed_minutes(pedido["fecha_hora"])
        pedido["prioridad"] = kds_priority_score(mins, pedido["estado_comanda"])
        armados.append(pedido)
    armados.sort(key=lambda p: p["prioridad"], reverse=True)
    return armados


def resumen_chef() -> list[dict]:
    cutoff = active_order_cutoff()
    return rows("""
        SELECT pm.nombre,
               SUM(pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) AS cantidad
        FROM pedidos_cabecera pc
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE pc.estado_comanda IN ('pendiente', 'en_cocina')
          AND pc.fecha_hora >= ?
          AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pm.id_producto, pm.nombre
        ORDER BY cantidad DESC, pm.nombre
        LIMIT 12
    """, (cutoff,))


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
    try:
        return one("""
            SELECT cd.*, u.nombre || ' ' || u.apellido AS cajero
            FROM cajas_diarias cd
            JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
            WHERE TRIM(LOWER(cd.estado_caja)) = 'abierta'
            ORDER BY cd.id_caja DESC
            LIMIT 1
        """)
    except Exception:
        return None


def registrar_movimiento_caja(conn, monto: float, descripcion: str, tipo: str = "ingreso_venta") -> None:
    caja = conn.execute("""
        SELECT id_caja FROM cajas_diarias
        WHERE TRIM(LOWER(estado_caja)) = 'abierta'
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


def cobrar_mesa(id_mesa: int, total: float, medio_pago: str, descuento: float = 0) -> dict:
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
        descuento = min(float(descuento or 0), subtotal)
        subtotal_con_descuento = subtotal - descuento
        servicio = service_amount(subtotal_con_descuento)
        total_real = subtotal_con_descuento + servicio
        cur = conn.execute("""
            INSERT INTO pagos_mesa (id_mesa, id_usuario, medio_pago, subtotal, descuento, servicio, total, tipo)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'total')
        """, (id_mesa, st.session_state.usuario["id_usuario"], medio_pago, subtotal, descuento, servicio, total_real))
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
            """, (medio_pago, total_real / len(activos), pedido["id_pedido"]))

        conn.execute("UPDATE mesas SET estado = 'libre' WHERE id_mesa = ?", (id_mesa,))
        registrar_movimiento_caja(conn, total_real, f"Mesa {id_mesa} - {medio_pago}", "ingreso_venta")
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
    try:
        movimientos = pd.DataFrame(rows("""
            SELECT fecha_hora, tipo_movimiento, monto, descripcion
            FROM movimientos_caja
            WHERE id_caja = ?
            ORDER BY fecha_hora
        """, (caja["id_caja"],)))
    except Exception:
        movimientos = pd.DataFrame(columns=["fecha_hora", "tipo_movimiento", "monto", "descripcion"])
    try:
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
    except Exception:
        medios = pd.DataFrame(columns=["medio_pago", "pagos", "subtotal", "servicio", "total"])
    ingresos = float(movimientos[movimientos["tipo_movimiento"] == "ingreso_venta"]["monto"].sum()) if not movimientos.empty else 0
    egresos = float(movimientos[movimientos["tipo_movimiento"] != "ingreso_venta"]["monto"].sum()) if not movimientos.empty else 0
    esperado = float(caja["monto_apertura"] or 0) + ingresos - egresos
    real = caja.get("monto_cierre_real")
    diferencia = (float(real) - esperado) if real is not None else 0
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


def liberar_mesa_sin_cobro(id_mesa: int, motivo: str = "") -> dict:
    """Cierra operativamente una mesa sin registrar venta.

    Se usa para correcciones auditadas: consumos cargados por error, cambio de
    mesa ya resuelto o liberacion administrativa. No deja pedidos activos.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        pedidos = conn.execute("""
            SELECT id_pedido
            FROM pedidos_cabecera
            WHERE id_mesa = ?
              AND estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
        """, (id_mesa,)).fetchall()

        for pedido in pedidos:
            conn.execute("""
                UPDATE pedido_detalle
                   SET cantidad_anulada = cantidad,
                       motivo_anulacion = TRIM(
                           COALESCE(motivo_anulacion, '') || ' ' || ?
                       )
                 WHERE id_pedido = ?
                   AND (cantidad - COALESCE(cantidad_cobrada, 0) - COALESCE(cantidad_anulada, 0)) > 0
            """, (motivo or "Liberacion manual sin cobro", pedido["id_pedido"]))
            conn.execute("""
                UPDATE pedidos_cabecera
                   SET estado_comanda = 'cobrado',
                       medio_pago = 'sin_cobro',
                       total_cobrado = 0,
                       fecha_cobro = datetime('now','localtime')
                 WHERE id_pedido = ?
            """, (pedido["id_pedido"],))

        conn.execute("UPDATE mesas SET estado = 'libre' WHERE id_mesa = ?", (id_mesa,))
        conn.execute("COMMIT")
        registrar_auditoria("caja", "liberar_mesa_manual", f"{id_mesa} {motivo}".strip())
        return {"ok": True, "pedidos_cerrados": len(pedidos)}
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


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


def pedidos_listos_mozo() -> list[dict]:
    cutoff = active_order_cutoff()
    return rows("""
        SELECT pc.id_pedido,
               m.numero_mesa,
               pc.fecha_hora,
               GROUP_CONCAT(pd.cantidad || 'x ' || pm.nombre, ', ') AS detalle
        FROM pedidos_cabecera pc
        JOIN mesas m ON m.id_mesa = pc.id_mesa
        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
        JOIN productos_menu pm ON pm.id_producto = pd.id_producto
        WHERE TRIM(LOWER(pc.estado_comanda)) = 'listo'
          AND pc.fecha_hora >= ?
          AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pc.id_pedido, m.numero_mesa, pc.fecha_hora
        ORDER BY pc.fecha_hora
    """, (cutoff,))


def pedidos_mesa_resumen(id_mesa: int) -> list[dict]:
    cutoff = active_order_cutoff()
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
          AND pc.fecha_hora >= ?
          AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
        GROUP BY pc.id_pedido, pc.estado_comanda, pc.fecha_hora
        ORDER BY pc.fecha_hora DESC
        LIMIT 5
    """, (id_mesa, cutoff))


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


@st.cache_data(ttl=60, show_spinner=False)
def system_counts() -> dict[str, int]:
    data = rows("""
        SELECT 'usuarios' AS tabla, COUNT(*) AS total FROM usuarios
        UNION ALL SELECT 'mesas', COUNT(*) FROM mesas
        UNION ALL SELECT 'productos', COUNT(*) FROM productos_menu
        UNION ALL SELECT 'insumos', COUNT(*) FROM insumos
        UNION ALL SELECT 'recetas', COUNT(*) FROM recetas_escandallo
        UNION ALL SELECT 'proveedores', COUNT(*) FROM proveedores
        UNION ALL SELECT 'movimientos_stock', COUNT(*) FROM movimientos_stock
        UNION ALL SELECT 'stock_bajo', COUNT(*) FROM insumos WHERE stock_actual <= stock_minimo
        UNION ALL SELECT 'pedidos_activos', COUNT(*) FROM pedidos_cabecera WHERE estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
        UNION ALL SELECT 'productos_sin_receta', COUNT(*) FROM (
            SELECT pm.id_producto
            FROM productos_menu pm
            LEFT JOIN recetas_escandallo r ON r.id_producto = pm.id_producto
            WHERE pm.activo = 1
            GROUP BY pm.id_producto
            HAVING COUNT(r.id_receta) = 0
        ) productos_activos_sin_receta
    """)
    return {str(row["tabla"]): int(row["total"] or 0) for row in data}


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


def proveedores_activos() -> list[dict]:
    return rows("""
        SELECT id_proveedor, nombre, telefono, email, notas, activo
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

