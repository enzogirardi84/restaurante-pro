"""
views/reservas.py — Sistema integral de reservas telefonicas.
Alta rapida, validacion de disponibilidad, gestion y vinculacion con mesas.
"""
from __future__ import annotations

from datetime import datetime, date, time, timedelta

import pandas as pd
import streamlit as st

from components.helpers import rows, one, execute, registrar_auditoria
from components.css import title, stat_card


def _mesas_disponibles(fecha: str, hora: str, personas: int) -> list[dict]:
    """Retorna mesas sin reserva confirmada en ±2hs alrededor de la hora dada."""
    try:
        h = int(hora.split(":")[0])
        m = int(hora.split(":")[1])
        desde = f"{h-2:02d}:{m:02d}"
        hasta = f"{h+2:02d}:{m:02d}"
    except Exception:
        desde = "00:00"
        hasta = "23:59"

    ocupadas = {
        r["id_mesa"]
        for r in rows("""
            SELECT DISTINCT id_mesa FROM reservas
            WHERE fecha_reserva = ?
              AND estado = 'confirmada'
              AND hora_reserva >= ?
              AND hora_reserva <= ?
        """, (fecha, desde, hasta))
    }

    try:
        todas = rows("SELECT id_mesa, numero_mesa, COALESCE(capacidad, 4) AS capacidad FROM mesas ORDER BY numero_mesa")
    except Exception:
        todas = rows("SELECT id_mesa, numero_mesa FROM mesas ORDER BY numero_mesa")
        for m in todas:
            m["capacidad"] = 4
    libres = [m for m in todas if m["id_mesa"] not in ocupadas
              and int(m.get("capacidad", 4)) >= personas]
    return libres


def _reservas_del_dia(fecha: str | None = None) -> list[dict]:
    if fecha is None:
        fecha = date.today().isoformat()
    return rows("""
        SELECT r.*, m.numero_mesa
        FROM reservas r
        JOIN mesas m ON m.id_mesa = r.id_mesa
        WHERE r.fecha_reserva = ?
        ORDER BY r.hora_reserva
    """, (fecha,))


def crear_reserva(nombre: str, apellido: str, telefono: str,
                  id_mesa: int, fecha: str, hora: str,
                  personas: int = 1, observaciones: str = "") -> dict:
    try:
        execute("""
            INSERT INTO reservas (nombre_cliente, apellido_cliente, telefono,
                                  id_mesa, fecha_reserva, hora_reserva,
                                  cantidad_personas, observaciones, estado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmada')
        """, (nombre.strip(), apellido.strip(), telefono.strip(),
              id_mesa, fecha, hora, personas, observaciones.strip()))
        registrar_auditoria("reservas", "reserva_creada",
                            f"{nombre} {apellido} - Mesa {id_mesa} {fecha} {hora}")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def cancelar_reserva(id_reserva: int) -> dict:
    try:
        execute("UPDATE reservas SET estado = 'cancelada' WHERE id_reserva = ?", (id_reserva,))
        registrar_auditoria("reservas", "reserva_cancelada", str(id_reserva))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def asistir_reserva(id_reserva: int) -> dict:
    try:
        execute("UPDATE reservas SET estado = 'asistida' WHERE id_reserva = ?", (id_reserva,))
        registrar_auditoria("reservas", "reserva_asistida", str(id_reserva))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def page_reservas():
    title("Reservas", "Registro telefónico rápido y gestión de reservas de salón.")

    tab_nueva, tab_dia, tab_gestion = st.tabs(["Nueva reserva", "Reservas del día", "Todas las reservas"])

    with tab_nueva:
        _tab_nueva_reserva()

    with tab_dia:
        _tab_reservas_dia()

    with tab_gestion:
        _tab_gestion_reservas()


def _tab_nueva_reserva():
    st.markdown("### Atención telefónica — alta rápida")

    with st.form("form_nueva_reserva", clear_on_submit=True):
        st.markdown("**Datos del cliente**")
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre *", placeholder="Obligatorio")
        apellido = c2.text_input("Apellido", placeholder="Opcional")
        telefono = st.text_input("Teléfono / WhatsApp", placeholder="+54 11 1234-5678")

        st.markdown("**Detalle de la reserva**")
        c3, c4, c5 = st.columns(3)
        hoy = date.today()
        fecha_res = c3.date_input("Fecha", value=hoy, min_value=hoy)
        hora_res = c4.time_input("Hora", value=time(20, 0), step=timedelta(minutes=15))
        personas = c5.number_input("Comensales", min_value=1, max_value=50, value=2)

        fecha_str = fecha_res.isoformat()
        hora_str = hora_res.strftime("%H:%M")

        mesas_libres = _mesas_disponibles(fecha_str, hora_str, personas)
        if mesas_libres:
            mesa_opts = {f"Mesa {m['numero_mesa']} (Cap. {m.get('capacidad', '?')})": m["id_mesa"] for m in mesas_libres}
            mesa_sel = st.selectbox("Mesa disponible", list(mesa_opts.keys()))
            id_mesa = mesa_opts[mesa_sel]
            st.caption(f"✅ {len(mesas_libres)} mesa(s) disponible(s) en esa franja horaria")
        else:
            st.error("No hay mesas disponibles en esa franja horaria.")
            id_mesa = None

        observaciones = st.text_area("Observaciones", placeholder="Ej: Mesa cerca ventana, cumpleaños, silla de bebé...",
                                     max_chars=200)

        enviar = st.form_submit_button("Confirmar reserva", type="primary", use_container_width=True)

        if enviar:
            if not nombre.strip():
                st.error("El nombre del cliente es obligatorio.")
            elif id_mesa is None:
                st.error("No hay mesas disponibles para esa fecha/hora.")
            else:
                r = crear_reserva(nombre, apellido, telefono, id_mesa,
                                  fecha_str, hora_str, personas, observaciones)
                if r["ok"]:
                    st.success(f"""
                    ### ✅ Reserva confirmada
                    **{nombre.strip()} {apellido.strip()}** — Mesa {id_mesa}
                    {fecha_str} a las {hora_str} — {personas} comensal(es)
                    Tel: {telefono or "—"}
                    """)
                    st.balloons()
                else:
                    st.error(f"Error al crear reserva: {r['error']}")


def _tab_reservas_dia():
    hoy = date.today().isoformat()
    reservas = _reservas_del_dia(hoy)

    total = len(reservas)
    confirmadas = sum(1 for r in reservas if r["estado"] == "confirmada")
    asistidas = sum(1 for r in reservas if r["estado"] == "asistida")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total hoy", total)
    c2.metric("Pendientes", confirmadas, delta_color="off")
    c3.metric("Asistidas", asistidas)

    if not reservas:
        st.info("No hay reservas para hoy.")
        return

    df = pd.DataFrame(reservas)
    df["hora"] = df["hora_reserva"].apply(lambda x: str(x)[:5])
    df["cliente"] = df.apply(lambda r: f"{r['nombre_cliente']} {r['apellido_cliente']}".strip(), axis=1)
    df["estado"] = df["estado"].astype(str)

    for r in reservas:
        with st.container(border=True):
            cols = st.columns([2, 1, 1, 1, 1])
            cliente = f"{r['nombre_cliente']} {r['apellido_cliente']}".strip()
            cols[0].markdown(f"**{r['hora_reserva'][:5]}** {cliente}")
            cols[1].markdown(f"Mesa {r['numero_mesa']} · {r['cantidad_personas']}p")
            cols[2].markdown(f"📞 {r['telefono'] or '—'}")
            estado = r["estado"]
            if estado == "confirmada":
                cols[3].markdown("🟡 Pendiente")
                if st.button("Asistió", key=f"asistir_{r['id_reserva']}"):
                    asistir_reserva(r["id_reserva"])
                    st.rerun()
            elif estado == "asistida":
                cols[3].markdown("✅ Asistida")
            else:
                cols[3].markdown("❌ Cancelada")

    st.caption(f"Mostrando {len(reservas)} reserva(s) para hoy.")


def _tab_gestion_reservas():
    c1, c2 = st.columns(2)
    desde = c1.date_input("Desde", value=date.today())
    hasta = c2.date_input("Hasta", value=date.today() + timedelta(days=7))

    reservas = rows("""
        SELECT r.*, m.numero_mesa
        FROM reservas r
        JOIN mesas m ON m.id_mesa = r.id_mesa
        WHERE r.fecha_reserva BETWEEN ? AND ?
        ORDER BY r.fecha_reserva, r.hora_reserva
    """, (desde.isoformat(), hasta.isoformat()))

    if not reservas:
        st.info("Sin reservas en el período seleccionado.")
        return

    df = pd.DataFrame(reservas)
    df["fecha_hora"] = df.apply(lambda r: f"{r['fecha_reserva']} {str(r['hora_reserva'])[:5]}", axis=1)
    df["cliente"] = df.apply(lambda r: f"{r['nombre_cliente']} {r['apellido_cliente']}".strip(), axis=1)

    for r in reservas:
        with st.expander(f"{r['fecha_reserva']} {str(r['hora_reserva'])[:5]} — "
                         f"{r['nombre_cliente']} {r['apellido_cliente']} — Mesa {r['numero_mesa']}"):
            st.write(f"**Teléfono:** {r['telefono'] or '—'}")
            st.write(f"**Personas:** {r['cantidad_personas']}")
            st.write(f"**Estado:** {r['estado']}")
            if r.get("observaciones"):
                st.write(f"**Obs:** {r['observaciones']}")
            c1, c2 = st.columns(2)
            if r["estado"] == "confirmada":
                if c1.button("✅ Asistió", key=f"gasistir_{r['id_reserva']}"):
                    asistir_reserva(r["id_reserva"])
                    st.rerun()
                if c2.button("❌ Cancelar", key=f"gcancel_{r['id_reserva']}"):
                    cancelar_reserva(r["id_reserva"])
                    st.rerun()
