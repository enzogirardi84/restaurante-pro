"""
Monitor de cocina (KDS).
Muestra comandas por estado y permite avanzar el flujo de preparacion.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

import streamlit as st
from components.css import inject_styles
from database import (
    avanzar_estado,
    init_db,
    obtener_pedidos_por_estado,
    seed_pedidos_demo,
)


st.set_page_config(
    page_title="KDS - Monitor de Cocina",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "db_initialized" not in st.session_state:
    init_db()
    seed_pedidos_demo()
    st.session_state.db_initialized = True


def formatear_tiempo(fecha_str: str) -> tuple[int, str]:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            fecha = datetime.strptime(fecha_str, fmt)
            break
        except ValueError:
            continue
    else:
        return 0, "sin hora"

    mins = max(0, int((datetime.now() - fecha).total_seconds() / 60))
    if mins < 60:
        return mins, f"{mins} min"
    return mins, f"{mins // 60} h {mins % 60} min"


def prioridad(mins: int) -> tuple[str, str, str]:
    # Retorna: (color_borde, etiqueta, clase_css)
    if mins >= 25:
        return "#c9342d", "Critico", "delay-critical"
    if mins >= 15:
        return "#d99018", "Demorado", "delay-warning"
    return "#2e7d50", "A tiempo", "delay-normal"


def render_columna(titulo: str, items: list[dict], estado_actual: str, color: str) -> None:
    st.markdown(
        f"""
        <div class="column-head" style="background:{color}">
            <span>{escape(titulo)}</span>
            <span>{len(items)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not items:
        st.markdown('<div class="empty">Sin pedidos en esta columna.</div>', unsafe_allow_html=True)
        return

    # Ordenar por prioridad: los mas criticos primero
    items_con_prioridad = []
    for item in items:
        mins, _ = formatear_tiempo(item["fecha"])
        items_con_prioridad.append((mins, item))
    items_con_prioridad.sort(key=lambda x: x[0], reverse=True)

    for mins, item in items_con_prioridad:
        _, etiqueta = formatear_tiempo(item["fecha"])
        border, label, css_class = prioridad(mins)
        puntaje_prioridad = int(mins * 1.5 + (20 if item.get("estado") == "esperando_cuenta" else 0))
        st.markdown(
            f"""
            <div class="ticket {css_class}" style="border-left-color:{border}">
                <div class="ticket-top">
                    <span>Mesa {item['mesa']} - Pedido #{item['id']}</span>
                    <span class="badge-{css_class}">{escape(label)} · {escape(etiqueta)}</span>
                </div>
                <div class="ticket-meta">Mozo: {escape(item['mozo'])} · Prioridad: {puntaje_prioridad}</div>
                <div class="ticket-detail">{escape(item['detalle'] or '')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        label_boton = {
            "pendiente": "Iniciar preparacion",
            "en_cocina": "Marcar listo",
        }.get(estado_actual)

        if label_boton and st.button(label_boton, key=f"kds_{item['id']}_{estado_actual}", use_container_width=True):
            resultado = avanzar_estado(item["id"], estado_actual)
            if not resultado.get("ok"):
                st.error(resultado.get("error", "Error desconocido"))
            else:
                st.toast(f"Pedido #{item['id']} actualizado")
                for advertencia in resultado.get("advertencias", []):
                    st.warning(advertencia)
                st.rerun()


st.markdown(
    """
    <style>
        .kds-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            border-bottom: 1px solid #ddd7ce;
            padding-bottom: 0.9rem;
            margin-bottom: 1rem;
        }
        .kds-title { font-size: 1.55rem; font-weight: 800; margin: 0; }
        .kds-sub { color: #6f685f; font-size: 0.92rem; }
        .column-head {
            border-radius: 8px;
            padding: 0.72rem 0.85rem;
            color: white;
            font-weight: 800;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .ticket {
            background: white;
            border: 1px solid #ded8cf;
            border-left: 6px solid #ded8cf;
            border-radius: 8px;
            padding: 0.85rem;
            margin: 0.7rem 0 0.4rem;
            box-shadow: 0 1px 3px rgba(20, 20, 20, 0.06);
        }
        .ticket-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 0.8rem;
            font-weight: 800;
        }
        .ticket-meta { color: #6f685f; font-size: 0.86rem; margin-top: 0.2rem; }
        .ticket-detail {
            white-space: pre-wrap;
            margin-top: 0.55rem;
            font-size: 0.94rem;
            line-height: 1.35;
        }
        .empty {
            border: 1px dashed #cfc7bd;
            border-radius: 8px;
            padding: 1rem;
            color: #6f685f;
            text-align: center;
            background: rgba(255,255,255,0.55);
            margin-top: 0.7rem;
        }
        @keyframes pulse-warning {
            0%, 100% { box-shadow: 0 0 0 0 rgba(217, 144, 24, 0); }
            50% { box-shadow: 0 0 0 4px rgba(217, 144, 24, 0.25); }
        }
        @keyframes pulse-critical {
            0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(201, 52, 45, 0); }
            50% { opacity: 0.92; box-shadow: 0 0 0 6px rgba(201, 52, 45, 0.2); }
        }
        .delay-warning {
            animation: pulse-warning 2s ease-in-out infinite;
            border-left-width: 6px !important;
        }
        .delay-critical {
            animation: pulse-critical 1.2s ease-in-out infinite;
            border-left-width: 8px !important;
            background: linear-gradient(135deg, #fff5f5 0%, #ffffff 100%) !important;
        }
        .badge-delay-critical {
            display: inline-block;
            background: #c9342d;
            color: white;
            padding: 0.1rem 0.5rem;
            border-radius: 4px;
            font-size: 0.78rem;
            font-weight: 700;
        }
        .badge-delay-warning {
            display: inline-block;
            background: #d99018;
            color: white;
            padding: 0.1rem 0.5rem;
            border-radius: 4px;
            font-size: 0.78rem;
            font-weight: 700;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

inject_styles()

st.markdown(
    """
    <div class="kds-header">
        <div>
            <div class="kds-title">Monitor de cocina</div>
            <div class="kds-sub">Comandas ordenadas por antiguedad. Rojo indica demora critica.</div>
        </div>
    </div>"""
,
    unsafe_allow_html=True,
)

grupos = obtener_pedidos_por_estado()
total_pedidos = sum(len(v) for v in grupos.values())
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric("Pendientes", len(grupos["pendiente"]))
col_m2.metric("En preparacion", len(grupos["en_cocina"]))
col_m3.metric("Listos", len(grupos["listo"]))
col_m4.metric("Total visible", total_pedidos)

st.divider()

col1, col2, col3 = st.columns(3, gap="medium")
with col1:
    render_columna("Pendientes", grupos["pendiente"], "pendiente", "#a95512")
with col2:
    render_columna("En preparacion", grupos["en_cocina"], "en_cocina", "#1d5f8f")
with col3:
    render_columna("Listos para servir", grupos["listo"], "listo", "#2f7d4f")
