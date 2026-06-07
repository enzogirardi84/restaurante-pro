"""
backups.py — Crear, descargar y restaurar copias de la base de datos.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from database import DB_PATH, using_postgres
from components.css import title
from components.helpers import BACKUP_DIR, registrar_auditoria, rows


def page_backups() -> None:
    title("Backups", "Crear, descargar y restaurar copias de la base de datos.")
    if using_postgres():
        st.info("La app esta usando Supabase/PostgreSQL. Los backups tecnicos se gestionan desde Supabase; aqui podes exportar datos operativos en CSV.")
        tables = [
            "usuarios", "mesas", "productos_menu", "insumos", "recetas_escandallo",
            "pedidos_cabecera", "pedido_detalle", "pagos_mesa", "pago_detalle",
            "cajas_diarias", "movimientos_caja", "movimientos_stock",
            "auditoria_eventos", "configuracion_sistema", "sistema_estado",
        ]
        for table in tables:
            try:
                data = pd.DataFrame(rows(f"SELECT * FROM {table}"))
                st.download_button(
                    f"Exportar {table}.csv",
                    data.to_csv(index=False).encode("utf-8"),
                    file_name=f"{table}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            except Exception as exc:
                st.warning(f"No se pudo exportar {table}: {type(exc).__name__}")
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    if st.button("Crear backup ahora", type="primary"):
        name = f"restaurante_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        target = BACKUP_DIR / name
        import shutil
        shutil.copy2(DB_PATH, target)
        registrar_auditoria("backups", "backup_creado", name)
        st.success(f"Backup creado: {name}")

    for file in sorted(BACKUP_DIR.glob("*.db"), reverse=True):
        cols = st.columns([3, 1])
        cols[0].write(file.name)
        cols[1].download_button("Descargar", file.read_bytes(), file_name=file.name, key=f"dl_{file.name}", use_container_width=True)

    st.divider()
    uploaded = st.file_uploader("Restaurar desde archivo .db", type=["db"])
    if uploaded and st.button("Restaurar backup cargado"):
        safety = BACKUP_DIR / f"antes_de_restaurar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        import shutil
        shutil.copy2(DB_PATH, safety)
        DB_PATH.write_bytes(uploaded.getvalue())
        registrar_auditoria("backups", "backup_restaurado", uploaded.name)
        st.success("Backup restaurado. Recarga la app para ver los datos restaurados.")
