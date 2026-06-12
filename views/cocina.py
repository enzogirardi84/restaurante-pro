"""
views/cocina.py — KDS pasivo de visualización pura.
Sin botones, sin interacciones. Solo lectura a distancia.
Auto-refresh cada 10s con @st.fragment.
"""
from __future__ import annotations

from datetime import datetime
import io
import json
import math
import wave

import streamlit as st
from database import get_connection_direct


CSS_KDS = """
<style>
    .kds-grid { display: flex; flex-wrap: wrap; gap: 1rem; justify-content: center; }
    .kds-card {
        background: #1a1816; border: 1px solid #3a3530; border-radius: 14px;
        width: 340px; min-height: 200px;
        display: flex; flex-direction: column;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        overflow: hidden;
    }
    .kds-header {
        background: #2d2822; padding: 0.7rem 1rem;
        display: flex; justify-content: space-between; align-items: center;
        border-bottom: 2px solid #c93a2b;
    }
    .kds-mesa {
        font-size: 2rem; font-weight: 900; color: #f0ece4;
        letter-spacing: -0.03em; line-height: 1;
    }
    .kds-tiempo {
        font-size: 1rem; font-weight: 700; color: #b8b0a4;
        text-align: right; line-height: 1.2;
    }
    .kds-body { padding: 0.8rem 1rem; flex: 1; }
    .kds-item {
        padding: 0.4rem 0; border-bottom: 1px solid #2a2622;
        font-size: 1.1rem; color: #e8e4dc; line-height: 1.4;
    }
    .kds-item:last-child { border-bottom: none; }
    .kds-cantidad {
        font-weight: 900; color: #e8a84c; font-size: 1.2rem;
        margin-right: 0.4rem;
    }
    .kds-nombre { font-weight: 600; }
    .kds-obs {
        background: #3a3020; color: #f0d890; font-style: italic;
        padding: 0.25rem 0.5rem; border-radius: 4px;
        font-size: 0.85rem; margin-top: 0.2rem;
        display: inline-block;
    }
    .kds-alerta-tiempo {
        background: #5a2020; color: #f0a090; font-weight: 700;
        padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.85rem;
    }
    .kds-meta {
        font-size: 0.8rem; color: #8a847a; margin-top: 0.5rem;
        padding-top: 0.5rem; border-top: 1px solid #2a2622;
    }
    .kds-empty {
        color: #6a645a; font-size: 1.2rem; text-align: center;
        padding: 3rem 1rem;
    }
    @media (max-width: 768px) {
        .kds-card { width: 100%; }
        .kds-mesa { font-size: 1.6rem; }
        .kds-item { font-size: 0.95rem; }
    }
</style>
"""


def _demora_minutos(fecha_hora_str: str | None) -> tuple[int, str]:
    if not fecha_hora_str:
        return 0, ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(fecha_hora_str[:19], fmt)
            break
        except ValueError:
            continue
    else:
        return 0, ""
    mins = max(0, int((datetime.now() - dt).total_seconds() / 60))
    return mins, dt.strftime("%H:%M")


def _clase_demora(mins: int) -> str:
    if mins >= 20:
        return "kds-alerta-tiempo"
    return ""


def _kds_beep_wav() -> bytes:
    """Genera un beep WAV breve para alertar pedidos nuevos sin depender de assets."""
    sample_rate = 8000
    duration = 0.16
    frequency = 880
    frames = bytearray()
    for index in range(int(sample_rate * duration)):
        sample = int(18000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(sample.to_bytes(2, "little", signed=True))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def _notificar_estado_kds(total_pedidos: int) -> None:
    titulo = f"({total_pedidos}) KDS Cocina" if total_pedidos else "KDS Cocina"
    st.markdown(
        f"<script>document.title = {json.dumps(titulo)};</script>",
        unsafe_allow_html=True,
    )

    prev = st.session_state.get("kds_prev_total_pedidos")
    st.session_state.kds_prev_total_pedidos = total_pedidos
    if prev is not None and total_pedidos > int(prev):
        nuevos = total_pedidos - int(prev)
        st.toast(f"{nuevos} pedido(s) nuevo(s) en cocina")
        st.audio(_kds_beep_wav(), format="audio/wav")


@st.fragment(run_every=10)
def renderizar_monitor_cocina_pasivo():
    conn = get_connection_direct()
    try:
        rows = conn.execute("""
            SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda,
                   m.numero_mesa, u.nombre || ' ' || u.apellido AS mozo,
                   pd.cantidad, pd.observaciones, pm.nombre AS producto
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina')
              AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
            ORDER BY pc.fecha_hora ASC, pd.id_detalle ASC
        """).fetchall()
    finally:
        conn.close()

    # Agrupar por pedido
    pedidos: dict[int, dict] = {}
    for r in rows:
        pid = r["id_pedido"]
        if pid not in pedidos:
            pedidos[pid] = {
                "id": pid,
                "mesa": r["numero_mesa"],
                "mozo": r["mozo"],
                "fecha": r["fecha_hora"],
                "estado": r["estado_comanda"],
                "items": [],
            }
        pedidos[pid]["items"].append({
            "cantidad": int(r["cantidad"]),
            "producto": r["producto"],
            "obs": (r["observaciones"] or "").strip(),
        })

    total_pedidos = len(pedidos)
    total_items = sum(len(p["items"]) for p in pedidos.values())
    _notificar_estado_kds(total_pedidos)

    # Cabecera
    c_logo, c_metric = st.columns([1, 3])
    with c_logo:
        st.markdown("## 🍳 KDS")
    with c_metric:
        st.markdown(
            f"<span style='font-size:1.2rem;color:#b8b0a4;'>"
            f"{total_pedidos} pedidos · {total_items} platos · "
            f"<span style='color:#e8a84c;font-weight:700;'>{datetime.now():%H:%M}</span></span>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    if not pedidos:
        st.markdown(
            "<div class='kds-empty'>⏳ Sin pedidos activos. La cocina esta al dia.</div>",
            unsafe_allow_html=True,
        )
        return

    # Grid de tarjetas
    cards = list(pedidos.values())
    cards.sort(key=lambda p: p["fecha"] or "")

    cols_per_row = 4
    for i in range(0, len(cards), cols_per_row):
        cols = st.columns(cols_per_row, gap="small")
        for col, ped in zip(cols, cards[i:i + cols_per_row]):
            mins, hora = _demora_minutos(ped["fecha"])
            demora_class = _clase_demora(mins)

            badge_estado = "⏳" if ped["estado"] == "pendiente" else "👨‍🍳"
            estado_label = "PENDIENTE" if ped["estado"] == "pendiente" else "EN COCINA"

            with col:
                html_items = ""
                for item in ped["items"]:
                    obs_html = ""
                    if item["obs"]:
                        obs_html = f'<div class="kds-obs">📝 {item["obs"]}</div>'
                    html_items += (
                        f'<div class="kds-item">'
                        f'<span class="kds-cantidad">{item["cantidad"]}x</span>'
                        f'<span class="kds-nombre">{item["producto"]}</span>'
                        f'{obs_html}</div>'
                    )

                demora_html = ""
                if mins >= 20:
                    demora_html = f'<span class="kds-alerta-tiempo">🔴 {mins} min</span>'
                elif mins >= 12:
                    demora_html = f'<span style="color:#e8a84c;font-weight:700;">⚠️ {mins} min</span>'
                else:
                    demora_html = f'<span style="color:#8a847a;">{mins} min</span>'

                st.markdown(f"""
                <div class="kds-card">
                    <div class="kds-header">
                        <div class="kds-mesa">{badge_estado} MESA {ped['mesa']}</div>
                        <div class="kds-tiempo">{hora}<br>{demora_html}</div>
                    </div>
                    <div class="kds-body">
                        {html_items}
                        <div class="kds-meta">{ped['mozo']} · {estado_label}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)


def render() -> None:
    if "kds_css_injected" not in st.session_state:
        st.markdown(CSS_KDS, unsafe_allow_html=True)
        st.session_state.kds_css_injected = True

    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;'>"
        "<span style='font-size:1.5rem;font-weight:800;'>MONITOR DE COCINA</span>"
        "<span style='color:#8a847a;font-size:0.85rem;'>Actualizacion automatica cada 10s · Visualizacion pasiva</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    renderizar_monitor_cocina_pasivo()

    # Refresh controller (fallback por si fragment falla)
    st.markdown("""<div style="text-align:center;color:#4a4440;font-size:0.75rem;margin-top:0.5rem;">
        KDS pasivo — sin botones. Las comandas desaparecen al ser cobradas desde Caja.</div>""",
        unsafe_allow_html=True)
