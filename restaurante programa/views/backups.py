"""
backups.py — Crear, descargar, restaurar y gestionar copias de seguridad.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from database import DB_PATH, using_postgres
from components.css import title, stat_card
from components.helpers import BACKUP_DIR, registrar_auditoria, rows, money


def _tamano(p: Path) -> str:
    s = p.stat().st_size
    if s < 1024:
        return f"{s} B"
    elif s < 1024 * 1024:
        return f"{s / 1024:.1f} KB"
    return f"{s / (1024 * 1024):.1f} MB"


def _fecha_legible(p: Path) -> str:
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    edad = (datetime.now() - mtime).days
    return f"{mtime.strftime('%d/%m/%Y %H:%M')} ({'hoy' if edad == 0 else f'{edad}d'})"


def hacer_backup_ahora(nota: str = "") -> str | None:
    BACKUP_DIR.mkdir(exist_ok=True)
    if using_postgres():
        return None
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        sufijo = f"_{nota.strip().replace(' ', '_')[:20]}" if nota.strip() else ""
        name = f"restaurante_{ts}{sufijo}.db"
        shutil.copy2(DB_PATH, BACKUP_DIR / name)
        registrar_auditoria("backups", "backup_creado", name)
        return name
    except Exception:
        return None


def page_backups() -> None:
    title("Backups", "Crear, descargar y restaurar copias de la base de datos.")

    if using_postgres():
        st.info("Modo Supabase/PostgreSQL activo. Los backups nativos se gestionan desde Supabase. "
                "Aca podes exportar tablas operativas a CSV.")
        for table in ["usuarios", "mesas", "productos_menu", "insumos",
                      "recetas_escandallo", "pedidos_cabecera", "pedido_detalle",
                      "pagos_mesa", "cajas_diarias", "movimientos_caja",
                      "configuracion_sistema"]:
            try:
                df = pd.DataFrame(rows(f"SELECT * FROM {table} LIMIT 5000"))
                st.download_button(f"Exportar {table}.csv",
                                   df.to_csv(index=False).encode("utf-8"),
                                   file_name=f"{table}_{datetime.now():%Y%m%d}.csv",
                                   mime="text/csv", use_container_width=True)
            except Exception:
                pass
        return

    BACKUP_DIR.mkdir(exist_ok=True)
    archivos = sorted(BACKUP_DIR.glob("*.db"), reverse=True)
    total_size = sum(f.stat().st_size for f in archivos) / (1024 * 1024) if archivos else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Backups", len(archivos))
    col2.metric("Espacio total", f"{total_size:.1f} MB")
    ultimo = archivos[0] if archivos else None
    col3.metric("Ultimo backup", _tamano(ultimo) if ultimo else "—")

    # Crear backup
    with st.expander("Crear nuevo backup", expanded=True):
        nota = st.text_input("Nota opcional", placeholder="Ej: antes de migracion, fin de mes...",
                             key="backup_nota")
        if st.button("Crear backup ahora", type="primary", use_container_width=True):
            n = hacer_backup_ahora(nota)
            if n:
                st.success(f"Backup creado: {n}")
                st.rerun()
            else:
                st.error("No se pudo crear el backup. ¿La DB existe?")

    # Listado de backups
    if not archivos:
        st.info("Todavia no hay backups. Crea el primero arriba.")
        return

    st.subheader("Backups existentes")

    # Control de rotacion
    col_rot, _ = st.columns([1, 3])
    with col_rot:
        if len(archivos) > 5 and st.button("Limpiar viejos (solo ultimos 5)", use_container_width=True):
            for f in archivos[5:]:
                f.unlink(missing_ok=True)
            registrar_auditoria("backups", "backups_rotados", f"{len(archivos[5:])} eliminados")
            st.rerun()

    for i, f in enumerate(archivos):
        edad = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).days
        with st.container(border=True):
            cols = st.columns([2.5, 1, 0.8, 0.8, 0.6])
            nombre = f.name
            # Extraer nota del nombre si existe
            partes = nombre.replace(".db", "").split("_", 3)
            label = nombre
            if len(partes) >= 4:
                label = f"{partes[0]}_{partes[1]} — {partes[3]}"

            cols[0].markdown(f"**{f.stem}**  ")
            cols[0].caption(_fecha_legible(f))

            cols[1].markdown(f"`{_tamano(f)}`")

            # Color segun antiguedad
            if edad == 0:
                cols[2].markdown("🟢 Hoy")
            elif edad < 3:
                cols[2].markdown(f"🟡 {edad}d")
            else:
                cols[2].markdown(f"🔴 {edad}d")

            cols[3].download_button("⬇", f.read_bytes(),
                                    file_name=f.name, key=f"dl_{f.name}",
                                    use_container_width=True)

            if i > 0:
                if cols[4].button("🗑", key=f"del_{f.name}", use_container_width=True):
                    f.unlink(missing_ok=True)
                    registrar_auditoria("backups", "backup_eliminado", f.name)
                    st.rerun()

    # Restaurar
    st.divider()
    st.subheader("Restaurar backup")
    uploaded = st.file_uploader("Subir archivo .db para restaurar", type=["db"])
    if uploaded:
        st.warning("⚠️  La restauracion reemplaza la base de datos actual. "
                   "Se creara un backup automatico del estado actual antes de restaurar.")
        confirm = st.checkbox("Confirmo que quiero restaurar este backup")
        if confirm and st.button("Restaurar ahora", type="primary"):
            safety = BACKUP_DIR / f"pre_restore_{datetime.now():%Y%m%d_%H%M%S}.db"
            shutil.copy2(DB_PATH, safety)
            DB_PATH.write_bytes(uploaded.getvalue())
            registrar_auditoria("backups", "backup_restaurado",
                                f"{uploaded.name} (pre: {safety.name})")
            st.success(f"Backup restaurado. Backup previo: {safety.name}")
            st.rerun()
