"""Promociones — motor de descuentos múltiples, por horario y por medio de pago."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from components.helpers import rows, one, execute, get_config, set_config, money, metodos_pago_config


TABLA_SQL = """
CREATE TABLE IF NOT EXISTS promociones (
    id_promocion INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('porcentaje', 'fijo', 'medio_pago', 'combo')),
    valor REAL NOT NULL CHECK (valor >= 0),
    categoria TEXT NOT NULL DEFAULT '',
    medio_pago TEXT NOT NULL DEFAULT '',
    hora_desde TEXT NOT NULL DEFAULT '',
    hora_hasta TEXT NOT NULL DEFAULT '',
    dias_semana TEXT NOT NULL DEFAULT '',
    activa INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

TABLA_PG = """
create table if not exists promociones (
    id_promocion bigserial primary key,
    nombre text not null,
    tipo text not null check (tipo in ('porcentaje', 'fijo', 'medio_pago', 'combo')),
    valor numeric not null check (valor >= 0),
    categoria text not null default '',
    medio_pago text not null default '',
    hora_desde text not null default '',
    hora_hasta text not null default '',
    dias_semana text not null default '',
    activa integer not null default 1,
    creado timestamp not null default now()
);
"""


def _en_horario(promo: dict) -> bool:
    if promo.get("hora_desde") and promo.get("hora_hasta"):
        ahora = datetime.now().strftime("%H:%M")
        if not (promo["hora_desde"] <= ahora <= promo["hora_hasta"]):
            return False
    if promo.get("dias_semana"):
        hoy = str(datetime.now().weekday())  # 0=lunes
        if hoy not in promo["dias_semana"].split(","):
            return False
    return True


def promociones_activas(medio_pago: str = "", categoria: str = "") -> list[dict]:
    todas = rows("""
        SELECT * FROM promociones
        WHERE activa = 1
        ORDER BY tipo, nombre
    """)
    return [
        p for p in todas
        if _en_horario(p)
        and (not p["medio_pago"] or p["medio_pago"] == medio_pago)
        and (not p["categoria"] or p["categoria"] == categoria)
    ]


def calcular_descuento(subtotal: float, categoria: str = "",
                      medio_pago: str = "") -> tuple[float, list[str]]:
    descuento_total = 0.0
    aplicadas = []
    for promo in promociones_activas(medio_pago, categoria):
        if promo["tipo"] == "medio_pago" and promo["medio_pago"] == medio_pago:
            dcto = round(subtotal * promo["valor"] / 100)
            descuento_total += dcto
            aplicadas.append(f"{promo['nombre']}: -{money(dcto)}")
        elif promo["tipo"] == "porcentaje" and (not promo["categoria"] or promo["categoria"] == categoria):
            dcto = round(subtotal * promo["valor"] / 100)
            descuento_total += dcto
            aplicadas.append(f"{promo['nombre']}: -{money(dcto)}")
        elif promo["tipo"] == "fijo":
            descuento_total += promo["valor"]
            aplicadas.append(f"{promo['nombre']}: -{money(promo['valor'])}")
    return round(descuento_total, 2), aplicadas


# ── CRUD ──────────────────────────────────────────────

def crear_promocion(nombre: str, tipo: str, valor: float,
                    categoria: str = "", medio_pago: str = "",
                    hora_desde: str = "", hora_hasta: str = "",
                    dias_semana: str = "") -> dict:
    try:
        execute("""
            INSERT INTO promociones
                (nombre, tipo, valor, categoria, medio_pago,
                 hora_desde, hora_hasta, dias_semana)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (nombre.strip(), tipo, valor, categoria, medio_pago,
              hora_desde, hora_hasta, dias_semana))
        return {"ok": True, "nombre": nombre.strip()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def toggle_promocion(id_promocion: int, activa: bool) -> dict:
    try:
        execute("UPDATE promociones SET activa = ? WHERE id_promocion = ?",
                (1 if activa else 0, id_promocion))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def eliminar_promocion(id_promocion: int) -> dict:
    try:
        execute("DELETE FROM promociones WHERE id_promocion = ?", (id_promocion,))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── UI ────────────────────────────────────────────────

def page_promociones():
    st.subheader("Promociones y descuentos")

    tab_lista, tab_nueva = st.tabs(["Promociones activas", "Nueva promocion"])

    with tab_nueva:
        _render_nueva()

    with tab_lista:
        _render_lista()


def _render_nueva():
    with st.form("nueva_promocion", clear_on_submit=True):
        nombre = st.text_input("Nombre de la promocion*", placeholder="Ej: 2x1 en bebidas")
        tipo = st.selectbox("Tipo de descuento*", [
            "porcentaje", "fijo", "medio_pago", "combo"
        ], format_func=lambda t: {
            "porcentaje": "Porcentaje sobre total",
            "fijo": "Monto fijo de descuento",
            "medio_pago": "Descuento por medio de pago",
            "combo": "Combo (descuento por categoria)",
        }.get(t, t))

        col_a, col_b = st.columns(2)
        with col_a:
            valor = st.number_input(
                "Valor del descuento*",
                min_value=0.0, step=1.0,
                help="% si es porcentaje, $ si es monto fijo",
            )
        with col_b:
            if tipo in ("porcentaje", "combo"):
                categoria = st.selectbox(
                    "Categoria (opcional)",
                    ["", "cocina", "bebidas", "postres"],
                    help="Dejar vacio para aplicar a todas",
                )
            else:
                categoria = ""
            if tipo == "medio_pago":
                medio_pago = st.selectbox(
                    "Medio de pago*",
                    metodos_pago_config() or ["Efectivo", "Tarjeta", "Transferencia"],
                )
            else:
                medio_pago = ""

        col_c, col_d = st.columns(2)
        with col_c:
            hora_desde = st.text_input("Hora desde (HH:MM)", placeholder="18:00")
        with col_d:
            hora_hasta = st.text_input("Hora hasta (HH:MM)", placeholder="23:00")

        dias = st.multiselect(
            "Dias de la semana (vacio = todos)",
            ["0", "1", "2", "3", "4", "5", "6"],
            format_func=lambda d: ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"][int(d)],
        )

        if st.form_submit_button("Crear promocion", type="primary", use_container_width=True):
            if not nombre.strip():
                st.error("El nombre es obligatorio.")
            elif valor <= 0:
                st.error("El valor debe ser mayor a 0.")
            else:
                r = crear_promocion(nombre, tipo, valor, categoria, medio_pago,
                                   hora_desde, hora_hasta, ",".join(dias))
                if r["ok"]:
                    st.success(f"Promocion '{r['nombre']}' creada.")
                    st.rerun()
                else:
                    st.error(r["error"])


def _render_lista():
    todas = rows("SELECT * FROM promociones ORDER BY activa DESC, tipo, nombre")
    if not todas:
        st.info("No hay promociones cargadas. Crea una desde la pestana anterior.")
        return

    for p in todas:
        with st.container(border=True):
            cols = st.columns([4, 2, 2, 1, 1])
            tipo_label = {
                "porcentaje": f"{p['valor']:.0f}%",
                "fijo": money(p["valor"]),
                "medio_pago": f"{p['valor']:.0f}% ({p['medio_pago']})",
                "combo": f"{p['valor']:.0f}% ({p['categoria']})",
            }.get(p["tipo"], str(p["valor"]))

            with cols[0]:
                estado = "🟢" if p["activa"] else "🔴"
                st.markdown(f"**{estado} {p['nombre']}**")
                st.caption(tipo_label)
            with cols[1]:
                if p.get("hora_desde") or p.get("hora_hasta"):
                    st.caption(f"{p['hora_desde']}-{p['hora_hasta']}")
            with cols[2]:
                if p.get("dias_semana"):
                    dias = [["Lun","Mar","Mie","Jue","Vie","Sab","Dom"][int(d)] for d in p["dias_semana"].split(",")]
                    st.caption(",".join(dias))
            with cols[3]:
                if st.button("🔄" if p["activa"] else "🔄", key=f"tog_{p['id_promocion']}"):
                    toggle_promocion(p["id_promocion"], not p["activa"])
                    st.rerun()
            with cols[4]:
                if st.button("🗑", key=f"del_{p['id_promocion']}"):
                    eliminar_promocion(p["id_promocion"])
                    st.rerun()
