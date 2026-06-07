"""Turnos del personal — check-in/check-out, horas trabajadas."""

from __future__ import annotations

from datetime import datetime, date

import pandas as pd
import streamlit as st

from components.helpers import rows, one, execute, money, registrar_auditoria


TABLA_SQL = """
CREATE TABLE IF NOT EXISTS turnos_personal (
    id_turno INTEGER PRIMARY KEY AUTOINCREMENT,
    id_usuario INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    hora_entrada TEXT NOT NULL,
    hora_salida TEXT,
    minutos_trabajados INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'cerrado')),
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
);
"""

TABLA_PG = """
create table if not exists turnos_personal (
    id_turno bigserial primary key,
    id_usuario bigint not null references usuarios(id_usuario),
    fecha date not null,
    hora_entrada time not null,
    hora_salida time,
    minutos_trabajados integer not null default 0,
    estado text not null default 'activo' check (estado in ('activo', 'cerrado'))
);
"""


def turno_activo(id_usuario: int) -> dict | None:
    return one("""
        SELECT * FROM turnos_personal
        WHERE id_usuario = ? AND estado = 'activo'
        ORDER BY id_turno DESC LIMIT 1
    """, (id_usuario,))


def iniciar_turno(id_usuario: int) -> dict:
    if turno_activo(id_usuario):
        return {"ok": False, "error": "El usuario ya tiene un turno activo"}
    try:
        hoy = date.today().isoformat()
        ahora = datetime.now().strftime("%H:%M")
        execute("""
            INSERT INTO turnos_personal (id_usuario, fecha, hora_entrada, estado)
            VALUES (?, ?, ?, 'activo')
        """, (id_usuario, hoy, ahora))
        registrar_auditoria("turnos", "inicio_turno", f"usuario #{id_usuario} a las {ahora}")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def cerrar_turno(id_usuario: int) -> dict:
    activo = turno_activo(id_usuario)
    if not activo:
        return {"ok": False, "error": "No hay turno activo"}
    try:
        ahora = datetime.now()
        entrada = datetime.strptime(activo["hora_entrada"], "%H:%M").replace(
            year=ahora.year, month=ahora.month, day=ahora.day)
        minutos = int((ahora - entrada).total_seconds() / 60)
        hora_salida = ahora.strftime("%H:%M")
        execute("""
            UPDATE turnos_personal
            SET hora_salida = ?, minutos_trabajados = ?, estado = 'cerrado'
            WHERE id_turno = ?
        """, (hora_salida, minutos, activo["id_turno"]))
        registrar_auditoria("turnos", "cierre_turno",
                           f"usuario #{id_usuario}, {minutos} min")
        return {"ok": True, "minutos": minutos}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def historial_turnos(id_usuario: int | None = None,
                     limite: int = 50) -> pd.DataFrame:
    if id_usuario:
        df = pd.DataFrame(rows("""
            SELECT t.*, u.nombre || ' ' || u.apellido AS usuario
            FROM turnos_personal t
            JOIN usuarios u ON u.id_usuario = t.id_usuario
            WHERE t.id_usuario = ?
            ORDER BY t.fecha DESC, t.id_turno DESC
            LIMIT ?
        """, (id_usuario, limite)))
    else:
        df = pd.DataFrame(rows("""
            SELECT t.*, u.nombre || ' ' || u.apellido AS usuario
            FROM turnos_personal t
            JOIN usuarios u ON u.id_usuario = t.id_usuario
            ORDER BY t.fecha DESC, t.id_turno DESC
            LIMIT ?
        """, (limite,)))
    return df


def resumen_turnos(desde: str = "", hasta: str = "") -> pd.DataFrame:
    filtros = []
    params = []
    if desde:
        filtros.append("t.fecha >= ?")
        params.append(desde)
    if hasta:
        filtros.append("t.fecha <= ?")
        params.append(hasta)
    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    df = pd.DataFrame(rows(f"""
        SELECT u.nombre || ' ' || u.apellido AS usuario,
               COUNT(t.id_turno) AS turnos,
               SUM(t.minutos_trabajados) AS minutos_total,
               ROUND(AVG(t.minutos_trabajados), 0) AS promedio_minutos
        FROM turnos_personal t
        JOIN usuarios u ON u.id_usuario = t.id_usuario
        {where}
        GROUP BY u.id_usuario
        ORDER BY minutos_total DESC
    """, tuple(params)))
    return df


# ── UI ───────────────────────────────────────────────────

def widget_check_in_out():
    """Widget para la barra lateral: muestra estado del turno."""
    user = st.session_state.get("usuario")
    if not user:
        return

    activo = turno_activo(user["id_usuario"])
    if activo:
        st.sidebar.success(f"Turno activo desde {activo['hora_entrada']}")
        if st.sidebar.button("Cerrar turno", type="primary", use_container_width=True):
            r = cerrar_turno(user["id_usuario"])
            if r["ok"]:
                st.sidebar.success(f"Turno cerrado ({r['minutos']} min)")
                st.rerun()
            else:
                st.sidebar.error(r["error"])
    else:
        if st.sidebar.button("Iniciar turno", type="primary", use_container_width=True):
            r = iniciar_turno(user["id_usuario"])
            if r["ok"]:
                st.sidebar.success("Turno iniciado")
                st.rerun()
            else:
                st.sidebar.error(r["error"])


def page_gestion_turnos():
    st.subheader("Turnos del personal")

    tab_hoy, tab_historial, tab_resumen = st.tabs(
        ["Turno actual", "Historial", "Resumen"])

    with tab_hoy:
        _render_turno_hoy()

    with tab_historial:
        _render_historial()

    with tab_resumen:
        _render_resumen()


def _render_turno_hoy():
    user = st.session_state.get("usuario")
    if not user:
        st.warning("Sin sesion activa.")
        return

    activo = turno_activo(user["id_usuario"])
    if activo:
        st.success(f"Turno activo desde las {activo['hora_entrada']}")
        if st.button("Cerrar turno", type="primary"):
            r = cerrar_turno(user["id_usuario"])
            if r["ok"]:
                st.success(f"Turno cerrado. Duración: {r['minutos']} minutos.")
                st.rerun()
            else:
                st.error(r["error"])
    else:
        st.info("No hay turno activo.")
        if st.button("Iniciar turno", type="primary"):
            r = iniciar_turno(user["id_usuario"])
            if r["ok"]:
                st.success("Turno iniciado.")
                st.rerun()
            else:
                st.error(r["error"])

    with st.expander("Personal en turno ahora"):
        ahora = datetime.now().strftime("%H:%M")
        hoy = date.today().isoformat()
        activos = pd.DataFrame(rows("""
            SELECT u.nombre || ' ' || u.apellido AS usuario,
                   u.rol, t.hora_entrada
            FROM turnos_personal t
            JOIN usuarios u ON u.id_usuario = t.id_usuario
            WHERE t.fecha = ? AND t.estado = 'activo'
            ORDER BY t.hora_entrada
        """, (hoy,)))
        if activos.empty:
            st.caption("Nadie en turno actualmente.")
        else:
            st.dataframe(activos, hide_index=True, use_container_width=True)


def _render_historial():
    user = st.session_state.get("usuario")
    if not user:
        return
    df = historial_turnos(user["id_usuario"], 100)
    if df.empty:
        st.info("Sin historial de turnos.")
    else:
        df["minutos_trabajados"] = df["minutos_trabajados"].apply(
            lambda m: f"{m // 60}h {m % 60}m" if m else "-")
        st.dataframe(df[["fecha", "hora_entrada", "hora_salida",
                         "minutos_trabajados", "estado"]],
                     hide_index=True, use_container_width=True)


def _render_resumen():
    col_a, col_b = st.columns(2)
    desde = col_a.date_input("Desde", value=date.today().replace(day=1),
                             key="turnos_desde")
    hasta = col_b.date_input("Hasta", value=date.today(),
                             key="turnos_hasta")

    df = resumen_turnos(str(desde), str(hasta))
    if df.empty:
        st.info("Sin registros en el período.")
    else:
        df["minutos_total"] = df["minutos_total"].apply(
            lambda m: f"{int(m) // 60}h {int(m) % 60}m")
        df["promedio_minutos"] = df["promedio_minutos"].apply(
            lambda m: f"{int(m) // 60}h {int(m) % 60}m")
        st.dataframe(df, hide_index=True, use_container_width=True)

        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Descargar resumen.csv", csv,
                           file_name=f"resumen_turnos_{desde}_{hasta}.csv",
                           mime="text/csv", use_container_width=True)
