"""
components/estilos.py — Identidad visual vintage COMANDAPRO ERP v2.1.
CSS global mejorado, animaciones, modo oscuro para KDS, responsive.
"""
from __future__ import annotations
import streamlit as st

# ── Paleta Vintage ────────────────────────────────────────────────────────
BORDO     = "#8B2635"
ARENA     = "#F4EAE1"
KRAFT     = "#EADCC9"
CARBON    = "#2C221E"
OLIVA     = "#7A8450"
MOSTAZA   = "#D4A373"
TERRACOTA = "#A64B2A"
BEIGE     = "#B58A63"
PALETTA_TIERRA = [BORDO, BEIGE, OLIVA, MOSTAZA, TERRACOTA]

def inyectar_css_global() -> None:
    """Inyecta CSS global vintage en la app. Llamar una vez al inicio."""
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Lora:ital,wght@0,400;0,600;1,400&display=swap');

@keyframes fadeIn {
  from { opacity:0; transform:translateY(8px); }
  to   { opacity:1; transform:translateY(0); }
}
@keyframes pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(139,38,53,0.4); }
  70%     { box-shadow: 0 0 0 8px rgba(139,38,53,0); }
}
@keyframes slideIn {
  from { transform:translateX(-10px); opacity:0; }
  to   { transform:translateX(0); opacity:1; }
}

* { font-family: "Lora", Georgia, "Times New Roman", serif !important; }

h1, h2, h3, h4, h5, h6 {
  font-family: "Playfair Display", Georgia, serif !important;
  color: {CARBON} !important;
}

.stApp { background-color: {KRAFT}; }
.stApp > header { background-color: {KRAFT} !important; }

.main .block-container {
  animation: fadeIn 0.3s ease-out;
  padding-top: 1.5rem !important;
}

.stButton button {
  background-color: {BORDO} !important;
  color: #fafafa !important;
  border: none !important;
  border-radius: 8px !important;
  font-family: "Playfair Display", serif !important;
  font-weight: 700 !important;
  letter-spacing: 0.5px;
  transition: all 0.2s ease !important;
}
.stButton button:hover {
  background-color: #a12f41 !important;
  box-shadow: 0 4px 12px rgba(139,38,53,0.3) !important;
  transform: translateY(-1px) !important;
}
.stButton button:active { transform: translateY(0) !important; }

div.stDownloadButton button {
  background-color: {OLIVA} !important;
}

.stTextInput input, .stTextArea textarea, .stSelectbox select {
  border: 1.5px solid {BEIGE} !important;
  background-color: {ARENA} !important;
  color: {CARBON} !important;
  border-radius: 8px !important;
  transition: border-color 0.2s;
}
.stTextInput input:focus, .stTextArea textarea:focus {
  border-color: {BORDO} !important;
  box-shadow: 0 0 0 2px rgba(139,38,53,0.15) !important;
}

section[data-testid="stSidebar"] {
  background-color: {ARENA} !important;
  border-right: 2px solid {BEIGE};
}
section[data-testid="stSidebar"] .stButton button {
  background-color: {BEIGE} !important;
  color: {CARBON} !important;
}
section[data-testid="stSidebar"] .stButton button:hover {
  background-color: {BORDO} !important;
  color: white !important;
}

.stDataFrame { font-size: 0.9rem; border-radius: 10px; overflow: hidden; }
.stDataFrame thead tr th {
  background-color: {BORDO} !important;
  color: #fafafa !important;
  font-family: "Playfair Display", serif !important;
}

div[data-testid="stMetric"] {
  background-color: {ARENA};
  border: 1px solid {BEIGE};
  border-radius: 12px;
  padding: 1rem;
  transition: transform 0.15s;
}
div[data-testid="stMetric"]:hover { transform: translateY(-2px); }
div[data-testid="stMetric"] label { color: {CARBON} !important; }

button[data-baseweb="tab"] {
  font-family: "Playfair Display", serif !important;
  font-weight: 600 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
  color: {BORDO} !important;
  border-bottom-color: {BORDO} !important;
}

div[data-testid="stContainer"] {
  border-radius: 12px !important;
}

details > summary { font-weight: 600 !important; }

.stSpinner > div { border-top-color: {BORDO} !important; }

div[data-testid="stAlert"] { border-radius: 10px !important; }

hr { border-color: {BEIGE} !important; }

.alerta-bordo {
  background-color: {BORDO}; color: #fafafa;
  padding: 0.8rem 1rem; border-radius: 10px;
  font-size: 0.95rem; margin: 0.5rem 0;
  border-left: 5px solid {TERRACOTA};
  animation: slideIn 0.2s ease;
}
.alerta-oliva {
  background-color: {OLIVA}; color: #fafafa;
  padding: 0.8rem 1rem; border-radius: 10px;
  font-size: 0.95rem; margin: 0.5rem 0;
  animation: slideIn 0.2s ease;
}

@media (max-width: 768px) {
  .stButton button { min-height: 48px !important; font-size: 1rem !important; }
  div[data-testid="stMetric"] { padding: 0.6rem !important; }
  .main .block-container { padding: 0.5rem 0.8rem !important; }
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: {KRAFT}; }
::-webkit-scrollbar-thumb { background: {BEIGE}; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: {BORDO}; }
</style>
""", unsafe_allow_html=True)


def alerta_vintage(
    mensaje: str,
    icono: str = "🍷",
    critico: bool | None = None,
    tipo: str = "informativo",
) -> None:
    """Alerta con estilo vintage. critico=True usa fondo Bordo, False usa Oliva."""
    es_critico = critico if critico is not None else (tipo == "critico")
    css_class = "alerta-bordo" if es_critico else "alerta-oliva"
    st.markdown(f"<div class='{css_class}'>{icono} {mensaje}</div>", unsafe_allow_html=True)


def color_kds(mins: int) -> tuple[str, str]:
    """Retorna (background_hex, label) según el tiempo transcurrido."""
    if mins >= 19: return TERRACOTA, "⚠️ Crítica"
    if mins >= 10: return MOSTAZA, "⏳ Alerta"
    return OLIVA, "✅ Óptimo"


def borde_kds(mins: int) -> str:
    if mins >= 19: return f"3px solid {TERRACOTA}"
    if mins >= 10: return f"3px solid {MOSTAZA}"
    return f"1px solid {OLIVA}"
