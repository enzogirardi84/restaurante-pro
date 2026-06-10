"""
sistema.py — Diagnostico, configuracion, monitoreo y datos del sistema.
"""
from __future__ import annotations

import os
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from database import (
    DB_PATH, database_label, logs_operaciones_recientes,
    procesar_cola_sincronizacion, using_postgres, get_connection,
)
from cloud_config import cloud_status, masked_status_table
from components.css import stat_card, title
from components.helpers import (
    APP_TITLE, caja_abierta, generar_ticket, promo_config,
    registrar_auditoria, restaurant_config, rows, service_amount, service_percentage,
    set_config, system_counts, system_password_is_default, system_password_is_hashed, money,
)


def page_sistema() -> None:
    title("Sistema", "Diagnostico, monitoreo y configuracion tecnica.")

    # ── Metricas de cabecera ──────────────────────────────────
    postgres_mode = using_postgres()
    conteos = system_counts()
    productos_sin_receta = conteos.get("productos_sin_receta", 0)
    stock_bajo = conteos.get("stock_bajo", 0)
    db_size = _db_tamano()
    pendientes = 0
    try:
        pendientes = len(rows("SELECT 1 FROM cola_sincronizacion WHERE sincronizado = 0 LIMIT 1") or [])
    except Exception:
        pass

    cols = st.columns(5)
    cols[0].metric("DB local", f"{db_size:.1f} MB", help="Tamaño del archivo SQLite")
    cols[1].metric("Stock bajo", stock_bajo or 0)
    cols[2].metric("Sin receta", productos_sin_receta)
    cols[3].metric("Sync pend.", pendientes)
    cols[4].metric("Modo", "Supabase" if postgres_mode else "SQLite")

    tab_config, tab_monitor, tab_sync, tab_logs, tab_agente = st.tabs(
        ["Configuracion", "Monitoreo", "Sincronizacion", "Auditoria", "Agente IA"]
    )

    with tab_config:
        _tab_configuracion()
    with tab_monitor:
        _tab_monitoreo()
    with tab_sync:
        _tab_sincronizacion()
    with tab_logs:
        _tab_auditoria()
    with tab_agente:
        _tab_agente_ia()


# ── Utilidades internas ────────────────────────────────────────────────────

def _db_tamano() -> float:
    try:
        return DB_PATH.stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0


def _clear_cache():
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()


# ── Pestana 1: Configuracion ──────────────────────────────────────────────

def _tab_configuracion():
    cfg = restaurant_config()
    st.subheader("Datos comerciales y ticket")
    with st.form("config_restaurante"):
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre del restaurante", value=cfg.get("nombre", ""))
        identificacion = c2.text_input("CUIT/RUT/NIT", value=cfg.get("identificacion", ""))
        direccion = st.text_input("Direccion", value=cfg.get("direccion", ""))
        telefono = st.text_input("Telefono", value=cfg.get("telefono", ""))
        try:
            _pct_default = float(service_percentage())
        except (ValueError, TypeError):
            _pct_default = 10.0
        servicio_pct = st.number_input("Porcentaje de servicio", min_value=0.0, max_value=50.0, value=_pct_default, step=0.5)
        footer = st.text_area("Texto final del ticket", value=cfg.get("ticket_footer", ""), height=80)
        if st.form_submit_button("Guardar configuracion", type="primary"):
            for k, v in [("restaurante_nombre", (nombre or "").strip() or APP_TITLE),
                         ("restaurante_identificacion", (identificacion or "").strip()),
                         ("restaurante_direccion", (direccion or "").strip()),
                         ("restaurante_telefono", (telefono or "").strip()),
                         ("servicio_porcentaje", str(max(0.0, min(50.0, float(servicio_pct or 0))))),
                         ("ticket_footer", (footer or "").strip() or "Gracias por su visita.")]:
                set_config(k, v)
            registrar_auditoria("sistema", "config_restaurante", (nombre or "").strip() or APP_TITLE)
            st.success("Configuracion guardada.")
            st.rerun()

    st.subheader("Vista previa de ticket")
    demo = generar_ticket({"numero_mesa": 1}, [{"cantidad": 1, "nombre": "Producto ejemplo", "importe": 1000}],
                          "Efectivo", 1000, service_amount(1000), 1000 + service_amount(1000))
    st.markdown(f"<div class='ticket'>{escape(demo)}</div>", unsafe_allow_html=True)


# ── Pestana 2: Monitoreo ──────────────────────────────────────────────────

def _tab_monitoreo():
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Archivos del proyecto")
        chk = lambda p, lb: (lb, "OK" if Path(p).exists() else "Falta")
        df = pd.DataFrame([
            chk("README.md", "README.md"),
            chk("requirements.txt", "requirements.txt"),
            chk(".gitignore", ".gitignore"),
            chk(".env.example", ".env.example"),
            chk("supabase/schema.sql", "SQL Supabase"),
        ], columns=["Archivo", "Estado"])
        st.dataframe(df, hide_index=True, use_container_width=True)

        st.subheader("Secretos cloud")
        st.dataframe(pd.DataFrame(masked_status_table()), hide_index=True, use_container_width=True)

    with col_b:
        st.subheader("Resumen de tablas")
        conteos = system_counts()
        tablas = [
            ("usuarios", conteos.get("usuarios", 0)),
            ("mesas", conteos.get("mesas", 0)),
            ("productos_menu", conteos.get("productos", 0)),
            ("insumos", conteos.get("insumos", 0)),
            ("recetas_escandallo", conteos.get("recetas", 0)),
            ("proveedores", conteos.get("proveedores", 0)),
            ("pedidos activos", conteos.get("pedidos_activos", 0)),
            ("movimientos_stock", conteos.get("movimientos_stock", 0)),
        ]
        st.dataframe(pd.DataFrame(tablas, columns=["Tabla", "Registros"]), hide_index=True, use_container_width=True)

        st.subheader("Mantenimiento")
        col_x, col_y = st.columns(2)
        with col_x:
            if st.button("Limpiar cache", use_container_width=True):
                _clear_cache()
                st.toast("Cache limpiado")
                st.rerun()
        with col_y:
            if st.button("Diagnostico.txt", use_container_width=True):
                txt = "\n".join(f"{k}: {v}" for k, v in tablas)
                st.download_button("Descargar", txt, file_name=f"diagnostico_{datetime.now():%Y%m%d_%H%M}.txt")

    st.subheader("Operacion")
    caja = caja_abierta()
    prom = promo_config()
    col_q, col_w, col_e = st.columns(3)
    col_q.metric("Caja", f"Abierta #{caja['id_caja']}" if caja else "Cerrada")
    col_w.metric("Promocion", "Activa" if prom["activa"] else "Inactiva")
    col_e.metric("Base datos", database_label())

    st.subheader("Estado persistido")
    st.dataframe(pd.DataFrame(rows("SELECT clave, valor, actualizado_en FROM sistema_estado ORDER BY clave")),
                 hide_index=True, use_container_width=True)


# ── Pestana 3: Sincronizacion ─────────────────────────────────────────────

def _tab_sincronizacion():
    st.subheader("Cola de sincronizacion")
    postgres_mode = using_postgres()

    try:
        pendientes = rows("""
            SELECT id_sync, tabla, operacion, clave_primaria, creado_en, intentos
            FROM cola_sincronizacion WHERE sincronizado = 0
            ORDER BY creado_en ASC LIMIT 100
        """)
    except Exception:
        pendientes = []
    total_pendientes = len(pendientes)

    c1, c2, c3 = st.columns(3)
    c1.metric("Pendientes", total_pendientes)
    c2.metric("Conectado", "Si" if postgres_mode else "No",
              delta_color="off" if postgres_mode else "inverse")
    c3.metric("Ultima descarga", "N/A")

    if pendientes:
        st.warning(f"{total_pendientes} operaciones pendientes.")
        st.dataframe(pd.DataFrame(pendientes), hide_index=True, use_container_width=True)
        if st.button("Forzar sincronizacion", type="primary", use_container_width=True):
            with st.spinner("Sincronizando..."):
                r = procesar_cola_sincronizacion(max_items=50)
            ok_c = r.get("procesados", 0)
            if ok_c:
                st.toast(f"{ok_c} sincronizados")
            for err in (r.get("errores") or [])[:3]:
                st.error(err)
            st.rerun()
    else:
        if postgres_mode:
            st.success("Todo sincronizado.")
        else:
            st.info("Modo local SQLite activo.")

    st.divider()
    if not postgres_mode:
        if st.button("Subir todo a Supabase", type="secondary", use_container_width=True):
            ok, msg = _subir_todo_supabase()
            st.toast(msg, icon="✅" if ok else "❌")
            st.rerun()
        st.caption("Requiere SERVICE_ROLE_KEY en secrets")


# ── Pestana 4: Auditoria ──────────────────────────────────────────────────

def _tab_auditoria():
    st.subheader("Logs de auditoria operativa")
    _accion_filtro = st.selectbox("Filtrar por accion", ["Todas", "caja", "usuarios", "inventario", "sistema", "cocina", "menu", "reservas"], key="log_filtro")

    logs = logs_operaciones_recientes(500)
    if not logs:
        st.info("Sin registros aun.")
        return

    df = pd.DataFrame(logs)
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df = df.rename(columns={"id_log": "ID", "usuario": "Usuario", "accion": "Accion",
                            "detalle": "Detalle", "created_at": "Fecha"})

    if _accion_filtro != "Todas":
        df = df[df["Accion"].str.contains(_accion_filtro, case=False, na=False)]

    st.caption(f"{len(df)} registro(s)")
    st.dataframe(df, hide_index=True, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("Descargar logs.csv", csv,
                       file_name=f"logs_{datetime.now():%Y%m%d}.csv",
                       mime="text/csv", use_container_width=False)


# ── Pestana 5: Agente IA ─────────────────────────────────────────────────

def _tab_agente_ia():
    st.subheader("Agente de calidad")
    reporte_path = Path(__file__).parent.parent.parent / "data" / "reporte_agente_qa.log"
    if reporte_path.exists():
        contenido = reporte_path.read_text(encoding="utf-8")
        ultimo = [l for l in contenido.split("\n") if "Resumen:" in l]
        if ultimo:
            st.success(f"Ultimo: {ultimo[-1]}")
        st.text_area("Log", contenido, height=200, disabled=True)
    else:
        st.info("Ejecuta `python agente_qa.py` para generar el primer reporte.")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Ejecutar ahora", type="primary", use_container_width=True):
            import subprocess, sys
            with st.spinner("Escaneando..."):
                r = subprocess.run([sys.executable, "agente_qa.py", "--once"],
                                   capture_output=True, text=True, timeout=120,
                                   cwd=Path(__file__).parent.parent.parent)
            st.toast("OK" if r.returncode == 0 else r.stderr[:200])
            st.rerun()
    with c2:
        stats = _estadisticas_agente()
        st.metric("Escaneados", stats.get("archivos_escaneados", 0))
    with c3:
        st.metric("Corregidos", stats.get("corregidos", 0))


def _estadisticas_agente() -> dict:
    rp = Path(__file__).parent.parent.parent / "data" / "reporte_agente_qa.log"
    s = {"archivos_escaneados": 0, "corregidos": 0, "saludables": 0, "errores_log": 0}
    if not rp.exists():
        return s
    for linea in rp.read_text(encoding="utf-8").split("\n"):
        if "Archivos Python encontrados:" in linea:
            try: s["archivos_escaneados"] = int(linea.split(":")[-1].strip())
            except ValueError: pass
        if "corregidos:" in linea:
            for p in linea.split(","):
                if "saludables" in p:
                    try: s["saludables"] = int(p.split(":")[-1].strip().split()[0])
                    except ValueError: pass
                if "corregidos" in p:
                    try: s["corregidos"] = int(p.split(":")[-1].strip().split()[0])
                    except ValueError: pass
    return s


# ── Subir a Supabase ──────────────────────────────────────────────────────

def _subir_todo_supabase():
    import sqlite3, json, urllib.request, urllib.error, time, os
    _db = Path(__file__).parent.parent / "data" / "restaurante.db"
    if not _db.exists():
        return False, f"No existe: {_db}"
    _supa_url = st.secrets.get("SUPABASE_URL", "") or os.environ.get("SUPABASE_URL", "")
    _svc_key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not _supa_url or not _svc_key:
        return False, "Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY"
    _base = _supa_url.rstrip("/") + "/rest/v1"
    _headers = {"apikey": _svc_key, "Authorization": f"Bearer {_svc_key}",
                "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
    _tablas = ["usuarios", "productos_menu", "mesas", "configuracion_sistema",
               "categorias", "insumos", "recetas_escandallo", "pedidos_cabecera",
               "pedido_detalle", "turnos_personal", "cajas_diarias",
               "movimientos_caja", "proveedores", "movimientos_stock",
               "depositos", "stock_deposito", "promociones", "reservas"]
    _conn = sqlite3.connect(str(_db))
    _conn.row_factory = sqlite3.Row
    _total, _errores = 0, 0
    for _t in _tablas:
        try:
            _filas = [dict(r) for r in _conn.execute(f'SELECT * FROM "{_t}"').fetchall()]
        except Exception:
            continue
        if not _filas:
            continue
        try:
            with urllib.request.urlopen(urllib.request.Request(
                f"{_base}/{_t}", data=json.dumps(_filas).encode("utf-8"),
                headers=_headers, method="POST"), timeout=30):
                pass
            _total += len(_filas)
        except Exception:
            _errores += 1
        time.sleep(0.3)
    _conn.close()
    msg = f"Subidas {_total} filas" + (f" ({_errores} errores)" if _errores else "")
    return _errores == 0, msg
