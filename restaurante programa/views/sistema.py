"""
sistema.py — Diagnostico, configuracion, deploy y datos del sistema.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from database import DB_PATH, database_label, using_postgres
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

    tab_restaurante, tab_estado, tab_deploy, tab_datos = st.tabs(["Restaurante", "Estado", "Deploy", "Datos"])
    with tab_restaurante:
        cfg = restaurant_config()
        st.subheader("Datos comerciales y ticket")
        with st.form("config_restaurante"):
            c1, c2 = st.columns(2)
            nombre = c1.text_input("Nombre del restaurante", value=cfg["nombre"])
            identificacion = c2.text_input("CUIT/RUT/NIT", value=cfg["identificacion"])
            direccion = st.text_input("Direccion", value=cfg["direccion"])
            telefono = st.text_input("Telefono", value=cfg["telefono"])
            servicio_pct = st.number_input("Porcentaje de servicio", min_value=0.0, max_value=50.0, value=float(service_percentage()), step=0.5)
            footer = st.text_area("Texto final del ticket", value=cfg["ticket_footer"], height=80)
            if st.form_submit_button("Guardar configuracion", type="primary"):
                set_config("restaurante_nombre", nombre.strip() or APP_TITLE)
                set_config("restaurante_identificacion", identificacion.strip())
                set_config("restaurante_direccion", direccion.strip())
                set_config("restaurante_telefono", telefono.strip())
                set_config("servicio_porcentaje", str(float(servicio_pct)))
                set_config("ticket_footer", footer.strip() or "Gracias por su visita.")
                registrar_auditoria("sistema", "config_restaurante", nombre.strip() or APP_TITLE)
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
