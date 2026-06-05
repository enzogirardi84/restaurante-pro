"""
components/estilos.py — Identidad visual vintage COMANDAPRO ERP.
CSS unificado, helpers de alertas HTML, constantes de color y paletas.
"""
from __future__ import annotations

import streamlit as st

# ── Paleta Vintage ─────────────────────────────────────────────────────
BORDO       = "#8B2635"
ARENA       = "#F4EAE1"
KRAFT       = "#EADCC9"
CARBON      = "#2C221E"
OLIVA       = "#7A8450"
MOSTAZA     = "#D4A373"
TERRACOTA   = "#A64B2A"
BEIGE       = "#B58A63"

# Paleta para gráficos de torta (Top 5)
PALETTA_TIERRA = [BORDO, BEIGE, OLIVA, MOSTAZA, TERRACOTA]


def inyectar_css_global() -> None:
    """Inyecta CSS global vintage en la app. Llamar una vez al inicio desde main.py."""
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Lora:ital,wght@0,400;0,600;1,400&display=swap');

        * {{ font-family: 'Lora', Georgia, 'Times New Roman', serif !important; }}

        h1, h2, h3, h4, h5, h6 {{
            font-family: 'Playfair Display', Georgia, serif !important;
            color: {CARBON} !important;
        }}

        .stApp {{
            background-color: {KRAFT};
        }}

        .stButton button {{
            background-color: {BORDO} !important;
            color: #fafafa !important;
            border: none !important;
            border-radius: 8px !important;
            font-family: 'Playfair Display', serif !important;
            font-weight: 700 !important;
            letter-spacing: 0.5px;
            transition: all 0.2s ease;
        }}
        .stButton button:hover {{
            background-color: #a12f41 !important;
            box-shadow: 0 4px 12px rgba(139,38,53,0.3);
        }}

        div.stDownloadButton button {{
            background-color: {OLIVA} !important;
        }}

        .stTextInput input, .stTextArea textarea {{
            border: 1px solid {BEIGE} !important;
            background-color: {ARENA} !important;
            color: {CARBON} !important;
            border-radius: 6px !important;
        }}

        /* Sidebar */
        section[data-testid="stSidebar"] {{
            background-color: {ARENA} !important;
            border-right: 2px solid {BEIGE};
        }}
        section[data-testid="stSidebar"] .stButton button {{
            background-color: {BEIGE} !important;
            color: {CARBON} !important;
        }}

        /* DataFrames */
        .stDataFrame {{
            font-size: 0.9rem;
        }}
        .stDataFrame thead tr th {{
            background-color: {BORDO} !important;
            color: #fafafa !important;
            font-family: 'Playfair Display', serif !important;
        }}

        /* Métricas */
        div[data-testid="stMetric"] {{
            background-color: {ARENA};
            border: 1px solid {BEIGE};
            border-radius: 10px;
            padding: 0.8rem;
        }}
        div[data-testid="stMetric"] label {{
            color: {CARBON} !important;
        }}

        hr {{
            border-color: {BEIGE} !important;
        }}

        /* Tarjetas de alerta vintage personalizadas */
        .alerta-bordo {{
            background-color: {BORDO};
            color: #fafafa;
            padding: 0.8rem 1rem;
            border-radius: 10px;
            font-family: 'Lora', serif;
            font-size: 0.95rem;
            margin: 0.5rem 0;
            border-left: 5px solid {TERRACOTA};
        }}
        .alerta-oliva {{
            background-color: {OLIVA};
            color: #fafafa;
            padding: 0.8rem 1rem;
            border-radius: 10px;
            font-family: 'Lora', serif;
            font-size: 0.95rem;
            margin: 0.5rem 0;
        }}

        /* KDS card */
        .kds-card {{
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            font-family: 'Lora', serif;
        }}
        .kds-card-tiempo {{
            display: flex;
            justify-content: space-between;
            font-weight: 700;
        }}
    </style>
    """, unsafe_allow_html=True)


def alerta_vintage(
    mensaje: str,
    icono: str = "🍷",
    critico: bool | None = None,
    tipo: str = "informativo",
) -> None:
    """
    Renderiza una alerta con estilo vintage (reemplaza st.error/st.warning).

    Parámetros:
        mensaje : Texto de la alerta (soporta **markdown**).
        icono   : Emoji o icono a mostrar (default: 🍷).
        critico | tipo : Si `critico=True` o `tipo="critico"` usa fondo Bordó;
                         caso contrario fondo Oliva.
    """
    es_critico = critico if critico is not None else (tipo == "critico")
    css_class = "alerta-bordo" if es_critico else "alerta-oliva"
    st.markdown(
        f"<div class='{css_class}'>{icono}  {mensaje}</div>",
        unsafe_allow_html=True,
    )


# ── Helpers para KDS ──────────────────────────────────────────────────

def color_kds(mins: int) -> tuple[str, str]:
    """Retorna (background_hex, label) según el tiempo transcurrido."""
    if mins >= 19:
        return TERRACOTA, "⚠️ Crítica"
    if mins >= 10:
        return MOSTAZA, "⏳ Alerta"
    return OLIVA, "✅ Óptimo"


def borde_kds(mins: int) -> str:
    if mins >= 19:
        return f"3px solid {TERRACOTA}"
    if mins >= 10:
        return f"3px solid {MOSTAZA}"
    return f"1px solid {OLIVA}"
