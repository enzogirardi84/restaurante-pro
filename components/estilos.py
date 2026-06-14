"""
components/estilos.py - Identidad visual vintage COMANDAPRO ERP.
CSS global mejorado, animaciones, responsive y helpers visuales.
"""
from __future__ import annotations

import streamlit as st

BORDO = "#8B2635"
ARENA = "#F4EAE1"
KRAFT = "#EADCC9"
CARBON = "#2C221E"
OLIVA = "#7A8450"
MOSTAZA = "#D4A373"
TERRACOTA = "#A64B2A"
BEIGE = "#B58A63"

PALETTA_TIERRA = [BORDO, BEIGE, OLIVA, MOSTAZA, TERRACOTA]


def inyectar_css_global() -> None:
    """Inyecta CSS global vintage en la app."""
    st.markdown(
        f"""
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Lora:ital,wght@0,400;0,600;1,400&display=swap');

          @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
          }}
          @keyframes pulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.015); }}
          }}
          @keyframes slideIn {{
            from {{ opacity: 0; transform: translateX(-8px); }}
            to {{ opacity: 1; transform: translateX(0); }}
          }}

          * {{ font-family: 'Lora', Georgia, 'Times New Roman', serif !important; }}

          h1, h2, h3, h4, h5, h6 {{
            font-family: 'Playfair Display', Georgia, serif !important;
            color: {CARBON} !important;
            letter-spacing: 0;
          }}

          .stApp {{
            background-color: {KRAFT};
            animation: fadeIn 0.3s ease-out;
          }}

          .stButton button {{
            background-color: {BORDO} !important;
            color: #fafafa !important;
            border: none !important;
            border-radius: 8px !important;
            font-family: 'Playfair Display', serif !important;
            font-weight: 700 !important;
            letter-spacing: 0;
            transition: transform 0.18s ease, box-shadow 0.18s ease, background-color 0.18s ease;
          }}
          .stButton button:hover {{
            background-color: #a12f41 !important;
            box-shadow: 0 4px 12px rgba(139, 38, 53, 0.3);
            transform: translateY(-1px);
          }}
          .stButton button:active {{
            transform: translateY(0);
          }}

          div.stDownloadButton button {{
            background-color: {OLIVA} !important;
            color: #fafafa !important;
            border-radius: 8px !important;
          }}

          .stTextInput input, .stTextArea textarea, .stNumberInput input {{
            border: 1px solid {BEIGE} !important;
            background-color: {ARENA} !important;
            color: {CARBON} !important;
            border-radius: 6px !important;
          }}

          section[data-testid="stSidebar"] {{
            background-color: {ARENA} !important;
            border-right: 2px solid {BEIGE};
          }}
          section[data-testid="stSidebar"] .stButton button {{
            background-color: {BEIGE} !important;
            color: {CARBON} !important;
          }}
          section[data-testid="stSidebar"] .stButton button:hover {{
            background-color: {MOSTAZA} !important;
          }}

          .stDataFrame {{
            font-size: 0.9rem;
          }}
          .stDataFrame thead tr th {{
            background-color: {BORDO} !important;
            color: #fafafa !important;
            font-family: 'Playfair Display', serif !important;
          }}

          div[data-testid="stMetric"] {{
            background-color: {ARENA};
            border: 1px solid {BEIGE};
            border-radius: 8px;
            padding: 0.8rem;
            transition: transform 0.18s ease, box-shadow 0.18s ease;
          }}
          div[data-testid="stMetric"]:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(44, 34, 30, 0.12);
          }}
          div[data-testid="stMetric"] label {{
            color: {CARBON} !important;
          }}

          hr {{
            border-color: {BEIGE} !important;
          }}

          .alerta-bordo, .alerta-oliva {{
            color: #fafafa;
            padding: 0.8rem 1rem;
            border-radius: 8px;
            font-family: 'Lora', serif;
            font-size: 0.95rem;
            margin: 0.5rem 0;
            animation: slideIn 0.2s ease;
          }}
          .alerta-bordo {{
            background-color: {BORDO};
            border-left: 5px solid {TERRACOTA};
          }}
          .alerta-oliva {{
            background-color: {OLIVA};
            border-left: 5px solid {MOSTAZA};
          }}

          .kds-card {{
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
            font-family: 'Lora', serif;
            animation: fadeIn 0.25s ease-out;
          }}
          .kds-card-tiempo {{
            display: flex;
            justify-content: space-between;
            font-weight: 700;
          }}

          ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
          ::-webkit-scrollbar-track {{ background: {KRAFT}; }}
          ::-webkit-scrollbar-thumb {{ background: {BEIGE}; border-radius: 3px; }}
          ::-webkit-scrollbar-thumb:hover {{ background: {BORDO}; }}

          @media (max-width: 768px) {{
            h1 {{ font-size: 1.8rem !important; }}
            h2 {{ font-size: 1.4rem !important; }}
            div[data-testid="stMetric"] {{ padding: 0.6rem; }}
            .stButton button {{ min-height: 44px; }}
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def alerta_vintage(
    mensaje: str,
    icono: str = "i",
    critico: bool | None = None,
    tipo: str = "informativo",
) -> None:
    """Renderiza una alerta con estilo vintage."""
    es_critico = critico if critico is not None else tipo == "critico"
    css_class = "alerta-bordo" if es_critico else "alerta-oliva"
    st.markdown(
        f"<div class='{css_class}'>{icono} &nbsp; {mensaje}</div>",
        unsafe_allow_html=True,
    )


def color_kds(mins: int) -> tuple[str, str]:
    """Retorna (background_hex, label) segun el tiempo transcurrido."""
    if mins >= 19:
        return TERRACOTA, "Critica"
    if mins >= 10:
        return MOSTAZA, "Alerta"
    return OLIVA, "Optimo"


def borde_kds(mins: int) -> str:
    if mins >= 19:
        return f"3px solid {TERRACOTA}"
    if mins >= 10:
        return f"3px solid {MOSTAZA}"
    return f"1px solid {OLIVA}"
