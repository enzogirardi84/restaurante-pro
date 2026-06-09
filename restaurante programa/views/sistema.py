"""
sistema.py — Diagnostico, configuracion, deploy y datos del sistema.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from database import (
    DB_PATH, database_label, logs_operaciones_recientes,
    procesar_cola_sincronizacion, using_postgres,
)
from cloud_config import cloud_status, masked_status_table
from components.css import stat_card, title
from components.helpers import (
    APP_TITLE, caja_abierta, generar_ticket, promo_config,
    registrar_auditoria, restaurant_config, rows, service_amount, service_percentage,
    set_config, system_counts, system_password_is_default, system_password_is_hashed,
)


def page_sistema() -> None:
    title("Sistema", "Diagnostico, preparacion para deploy y estado tecnico.")
    postgres_mode = using_postgres()
    db_exists = DB_PATH.exists() or postgres_mode
    supabase_schema = Path("supabase/schema.sql").exists()
    requirements = Path("requirements.txt").exists()
    readme = Path("README.md").exists()
    gitignore = Path(".gitignore").exists()
    env_example = Path(".env.example").exists()

    conteos = system_counts()
    tablas = {
        "usuarios": conteos.get("usuarios", 0),
        "mesas": conteos.get("mesas", 0),
        "productos": conteos.get("productos", 0),
        "insumos": conteos.get("insumos", 0),
        "recetas": conteos.get("recetas", 0),
        "proveedores": conteos.get("proveedores", 0),
        "movimientos_stock": conteos.get("movimientos_stock", 0),
        "pedidos_activos": conteos.get("pedidos_activos", 0),
    }
    productos_sin_receta = conteos.get("productos_sin_receta", 0)
    stock_bajo = conteos.get("stock_bajo", 0)
    caja = caja_abierta()

    cols = st.columns(4)
    with cols[0]:
        stat_card("Base local", "OK" if db_exists else "Falta", "#2e7d50" if db_exists else "#b33a34")
    with cols[1]:
        stat_card("Supabase SQL", "OK" if supabase_schema else "Falta", "#2e7d50" if supabase_schema else "#b33a34")
    with cols[2]:
        stat_card("Stock bajo", stock_bajo or 0, "#b33a34" if stock_bajo else "#2e7d50")
    with cols[3]:
        stat_card("Sin receta", productos_sin_receta, "#b33a34" if productos_sin_receta else "#2e7d50")

    tab_restaurante, tab_estado, tab_deploy, tab_datos, tab_sync, tab_agente = st.tabs(
        ["Restaurante", "Estado", "Deploy", "Datos", "Sincronizacion", "Agente IA"]
    )
    with tab_restaurante:
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
                _nombre = (nombre or "").strip() or APP_TITLE
                _id = (identificacion or "").strip() or ""
                _dir = (direccion or "").strip() or ""
                _tel = (telefono or "").strip() or ""
                _pct = str(max(0.0, min(50.0, float(servicio_pct or 0))))
                _footer = (footer or "").strip() or "Gracias por su visita."
                set_config("restaurante_nombre", _nombre)
                set_config("restaurante_identificacion", _id)
                set_config("restaurante_direccion", _dir)
                set_config("restaurante_telefono", _tel)
                set_config("servicio_porcentaje", _pct)
                set_config("ticket_footer", _footer)
                registrar_auditoria("sistema", "config_restaurante", _nombre)
                st.success("Configuracion guardada.")
                st.rerun()

        demo_mesa = {"numero_mesa": 1}
        demo_detalle = [{"cantidad": 1, "nombre": "Producto ejemplo", "importe": 1000}]
        demo_servicio = service_amount(1000)
        demo_ticket = generar_ticket(demo_mesa, demo_detalle, "Efectivo", 1000, demo_servicio, 1000 + demo_servicio)
        st.subheader("Vista previa de ticket")
        st.markdown(f"<div class='ticket'>{escape(demo_ticket)}</div>", unsafe_allow_html=True)

    with tab_estado:
        st.subheader("Archivos clave")
        archivos = pd.DataFrame([
            {"archivo": "README.md", "estado": "OK" if readme else "Falta"},
            {"archivo": "requirements.txt", "estado": "OK" if requirements else "Falta"},
            {"archivo": ".gitignore", "estado": "OK" if gitignore else "Falta"},
            {"archivo": ".env.example", "estado": "OK" if env_example else "Falta"},
            {"archivo": "supabase/schema.sql", "estado": "OK" if supabase_schema else "Falta"},
            {"archivo": str(DB_PATH), "estado": "OK" if db_exists else "Falta"},
        ])
        st.dataframe(archivos, hide_index=True, use_container_width=True)
        st.subheader("Estado persistido")
        st.dataframe(pd.DataFrame(rows("SELECT clave, valor, actualizado_en FROM sistema_estado ORDER BY clave")), hide_index=True, use_container_width=True)
        st.subheader("Operacion")
        st.markdown(
            f"""
            <div class="card">
                <div class="line"><span>Caja</span><b>{'Abierta #' + str(caja['id_caja']) if caja else 'Cerrada'}</b></div>
                <div class="line"><span>Promocion activa</span><b>{'Si' if promo_config()['activa'] else 'No'}</b></div>
                <div class="line"><span>Base</span><b>{escape(database_label())}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with tab_deploy:
        st.subheader("Checklist antes de dejarlo funcionando")
        cloud = cloud_status()
        checklist = [
            ("Codigo en GitHub", gitignore and readme and requirements),
            ("Datos locales fuera del repo", gitignore),
            ("SQL de Supabase preparado", supabase_schema),
            ("DATABASE_URL configurado", cloud.ready_for_postgres),
            ("Personal cargado", tablas["usuarios"] >= 4),
            ("Mesas cargadas", tablas["mesas"] > 0),
            ("Menu cargado", tablas["productos"] > 0),
            ("Inventario cargado", tablas["insumos"] > 0),
            ("Proveedores cargados", tablas["proveedores"] > 0),
            ("Recetas completas", productos_sin_receta == 0),
            ("Contrasena inicial cambiada", not system_password_is_default()),
            ("Contrasena guardada con hash", system_password_is_hashed()),
        ]
        for label, ok in checklist:
            st.markdown(
                f"<div class='line'><span>{escape(label)}</span><b style='color:{'#2e7d50' if ok else '#b33a34'}'>{'OK' if ok else 'Pendiente'}</b></div>",
                unsafe_allow_html=True,
            )
        st.subheader("Secretos cloud")
        st.dataframe(pd.DataFrame(masked_status_table()), hide_index=True, use_container_width=True)
        st.warning(
            "No pegues claves secretas dentro del codigo ni en GitHub. "
            "Si una clave secreta se compartio por error, rotala desde Supabase."
        )
        st.info("Supabase esta preparado. Con DATABASE_URL configurado, la app opera sobre PostgreSQL; sin ese secreto usa SQLite local.")

    with tab_datos:
        st.subheader("Resumen de datos")
        st.dataframe(pd.DataFrame([{"tabla": k, "registros": v} for k, v in tablas.items()]), hide_index=True, use_container_width=True)
        resumen_txt = "\n".join(f"{k}: {v}" for k, v in tablas.items())
        st.download_button(
            "Descargar diagnostico.txt",
            resumen_txt,
            file_name=f"diagnostico_restaurante_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            use_container_width=True,
        )

    with tab_sync:
        _tab_sincronizacion()
    with tab_agente:
        _tab_agente_ia()


def _tab_sincronizacion():
    st.subheader("Cola de sincronizacion offline-first")
    st.caption("Registros pendientes de replicar a Supabase. Si la cola se acumula, revisa la conexion.")
    postgres_mode = using_postgres()

    pendientes = rows("""
        SELECT id_sync, tabla, operacion, clave_primaria, creado_en, intentos
        FROM cola_sincronizacion
        WHERE sincronizado = 0
        ORDER BY creado_en ASC
        LIMIT 100
    """)

    total_pendientes = len(pendientes)
    c1, c2, c3 = st.columns(3)
    c1.metric("Pendientes", total_pendientes)
    c2.metric("Conectado a nube", "Si" if postgres_mode else "No",
              delta_color="off" if postgres_mode else "inverse")
    c3.metric("Ultima descarga", "N/A")

    if pendientes:
        st.warning(f"Hay {total_pendientes} operaciones esperando sincronizacion.")
        df_cola = pd.DataFrame(pendientes)
        st.dataframe(df_cola, hide_index=True, use_container_width=True)

        col_btn, col_status = st.columns([1, 3])
        with col_btn:
            if st.button("Forzar sincronizacion ahora", type="primary", use_container_width=True):
                with st.spinner("Sincronizando..."):
                    resultado = procesar_cola_sincronizacion(max_items=50)
                ok_count = resultado.get("procesados", 0)
                fail_count = resultado.get("fallaron", 0)
                if ok_count > 0:
                    st.toast(f"{ok_count} registros sincronizados con exito")
                if fail_count > 0:
                    errores = resultado.get("errores", [])
                    for err in errores[:3]:
                        st.error(err)
                    if len(errores) > 3:
                        st.caption(f"... y {len(errores) - 3} errores mas.")
                if not ok_count and not fail_count:
                    st.info("No habia registros pendientes por procesar.")
                st.rerun()
        with col_status:
            st.caption("La sincronizacion procesa hasta 50 registros por lote.")
    else:
        if postgres_mode:
            st.success("No hay operaciones pendientes. La cola esta al dia.")
        else:
            st.info("Modo local SQLite activo. Los datos se guardan localmente.")
            st.caption("Configura DATABASE_URL en Streamlit Secrets para activar la sincronizacion.")

    st.divider()
    if not postgres_mode:
        _col1, _col2 = st.columns([1, 3])
        with _col1:
            if st.button("Subir todo a Supabase", type="secondary", use_container_width=True):
                _ok, _msg = _subir_todo_supabase()
                if _ok:
                    st.toast(_msg, icon="✅")
                else:
                    st.error(_msg)
                st.rerun()
        with _col2:
            st.caption("Vuelca todas las tablas locales a Supabase via REST API (requiere SERVICE_ROLE_KEY en secrets)")

    st.divider()
    st.subheader("Logs de auditoria operativa")
    st.caption("Acciones criticas registradas: cambios de precio, anulaciones, aperturas de caja, etc.")

    logs = logs_operaciones_recientes(200)
    if logs:
        df_logs = pd.DataFrame(logs)
        if not df_logs.empty:
            df_logs["created_at"] = pd.to_datetime(df_logs["created_at"], errors="coerce")
            df_logs = df_logs.rename(columns={
                "id_log": "ID", "usuario": "Usuario", "accion": "Accion",
                "detalle": "Detalle", "created_at": "Fecha",
            })
            st.dataframe(df_logs, hide_index=True, use_container_width=True)

            csv_logs = df_logs.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Descargar logs de auditoria.csv", csv_logs,
                file_name=f"logs_auditoria_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv", use_container_width=False,
            )
    else:
        st.info("Aun no hay registros de auditoria operativa.")


def _tab_agente_ia():
    st.subheader("Telemetria y Agente IA")
    reporte_path = Path(__file__).parent.parent.parent / "data" / "reporte_agente_qa.log"
    if reporte_path.exists():
        contenido = reporte_path.read_text(encoding="utf-8")
        lineas = contenido.strip().split("\n")
        ultimo = [l for l in lineas if "Resumen:" in l]
        if ultimo:
            st.success(f"Ultimo escaneo: {ultimo[-1]}")
        st.text_area("Log completo del agente", contenido, height=200, disabled=True)
    else:
        st.info("El agente QA no se ha ejecutado aun. Ejecuta `python agente_qa.py` desde la terminal.")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Ejecutar agente ahora", type="primary", use_container_width=True):
            import subprocess, sys
            with st.spinner("Agente escaneando y reparando..."):
                result = subprocess.run(
                    [sys.executable, "agente_qa.py", "--once"],
                    capture_output=True, text=True, timeout=120,
                    cwd=Path(__file__).parent.parent.parent,
                )
            if result.returncode == 0:
                st.toast("Agente ejecutado correctamente")
            else:
                st.error(result.stderr[:500])
            st.rerun()
    with c2:
        stats = _estadisticas_agente()
        st.metric("Archivos escaneados", stats.get("archivos_escaneados", 0))
    with c3:
        st.metric("Corregidos", stats.get("corregidos", 0))

    st.caption(
        "El agente opera en 4 fases: Escaneo AST → Analisis de logs → "
        "Correccion con backup → Validacion y rollback. "
        "Para ejecucion automatica cada 5 min: `python agente_qa.py --watch`"
    )


def _estadisticas_agente() -> dict:
    reporte_path = Path(__file__).parent.parent.parent / "data" / "reporte_agente_qa.log"
    stats = {"archivos_escaneados": 0, "corregidos": 0, "saludables": 0, "errores_log": 0}
    if not reporte_path.exists():
    return stats


def _subir_todo_supabase():
    """Sube todas las tablas locales a Supabase via REST API."""
    import sqlite3, json, urllib.request, urllib.error, time, os

    _db = Path(__file__).parent.parent / "data" / "restaurante.db"
    if not _db.exists():
        return False, f"No existe la base local: {_db}"

    _supa_url = (st.secrets.get("SUPABASE_URL", "") or
                 os.environ.get("SUPABASE_URL", ""))
    _svc_key = (st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "") or
                os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))

    if not _supa_url or not _svc_key:
        return False, "Falta SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en secrets/env"

    _base = _supa_url.rstrip("/") + "/rest/v1"
    _headers = {
        "apikey": _svc_key, "Authorization": f"Bearer {_svc_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    _tablas = [
        "usuarios", "productos_menu", "mesas", "configuracion_sistema",
        "categorias", "insumos", "recetas_escandallo", "pedidos_cabecera",
        "pedido_detalle", "turnos_personal", "cajas_diarias",
        "movimientos_caja", "proveedores", "movimientos_stock",
        "depositos", "stock_deposito", "promociones",
    ]
    _conn = sqlite3.connect(str(_db))
    _conn.row_factory = sqlite3.Row
    _total, _errores = 0, 0

    for _t in _tablas:
        try:
            _filas = [dict(r) for r in _conn.execute(f'SELECT * FROM "{_t}"').fetchall()]
        except Exception as e:
            st.caption(f"  ⏭  {_t}: {e}")
            continue
        if not _filas:
            continue
        _body = json.dumps(_filas).encode("utf-8")
        try:
            with urllib.request.urlopen(
                urllib.request.Request(f"{_base}/{_t}", data=_body, headers=_headers, method="POST"),
                timeout=30,
            ) as _resp:
                pass
            _total += len(_filas)
        except urllib.error.HTTPError as e:
            _errores += 1
            st.caption(f"  ❌ {_t} HTTP {e.code}")
        except Exception as e:
            _errores += 1
            st.caption(f"  ❌ {_t}: {e}")
        time.sleep(0.3)

    _conn.close()
    _msg = f"Subidas {_total} filas a Supabase"
    if _errores:
        _msg += f" ({_errores} errores)"
    return _errores == 0, _msg
    for linea in reporte_path.read_text(encoding="utf-8").split("\n"):
        if "Archivos Python encontrados:" in linea:
            try:
                stats["archivos_escaneados"] = int(linea.split(":")[-1].strip())
            except ValueError:
                pass
        if "corregidos:" in linea:
            # Parsear "Resumen: X saludables, Y corregidos, Z fallaron, W rollbacks"
            partes = linea.split(",")
            for p in partes:
                if "saludables" in p:
                    try:
                        stats["saludables"] = int(p.split(":")[-1].strip().split()[0])
                    except ValueError:
                        pass
                if "corregidos" in p:
                    try:
                        stats["corregidos"] = int(p.split(":")[-1].strip().split()[0])
                    except ValueError:
                        pass
    return stats
