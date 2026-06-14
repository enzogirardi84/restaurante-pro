"""
views/cocina.py — KDS interactivo con botones de avance de estado.
Auto-refresh cada 10s. Los cocineros pueden avanzar pedidos:
  pendiente -> en_cocina -> listo -> entregado
"""
from __future__ import annotations

from datetime import datetime
import io
import json
import math
import wave

import streamlit as st
from database import get_connection_direct, avanzar_estado

CSS_KDS = """
<style>
.kds-card {
    background: #1a1816; border: 1px solid #3a3530; border-radius: 14px;
    display: flex; flex-direction: column;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    overflow: hidden; margin-bottom: 0.5rem;
}
.kds-header {
    background: #2d2822; padding: 0.7rem 1rem;
    display: flex; justify-content: space-between; align-items: center;
    border-bottom: 2px solid #c93a2b;
}
.kds-mesa { font-size: 1.8rem; font-weight: 900; color: #f0ece4; line-height: 1; }
.kds-tiempo { font-size: 0.95rem; font-weight: 700; color: #b8b0a4; text-align: right; line-height: 1.3; }
.kds-body { padding: 0.8rem 1rem; flex: 1; }
.kds-item {
    padding: 0.4rem 0; border-bottom: 1px solid #2a2622;
    font-size: 1.05rem; color: #e8e4dc; line-height: 1.4;
}
.kds-item:last-child { border-bottom: none; }
.kds-cantidad { font-weight: 900; color: #e8a84c; font-size: 1.15rem; margin-right: 0.4rem; }
.kds-obs {
    background: #3a3020; color: #f0d890; font-style: italic;
    padding: 0.2rem 0.5rem; border-radius: 4px;
    font-size: 0.82rem; margin-top: 0.2rem; display: inline-block;
}
.kds-alerta { background: #5a2020; color: #f0a090; font-weight: 700;
    padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.82rem; }
.kds-meta { font-size: 0.78rem; color: #8a847a; margin-top: 0.5rem;
    padding-top: 0.4rem; border-top: 1px solid #2a2622; }
.kds-empty { color: #6a645a; font-size: 1.2rem; text-align: center; padding: 3rem 1rem; }
@media (max-width: 768px) { .kds-mesa { font-size: 1.4rem; } .kds-item { font-size: 0.92rem; } }
</style>
"""

ESTADO_CONFIG = {
    "pendiente": {"color": "#c93a2b", "emoji": "⏳", "label": "PENDIENTE"},
    "en_cocina": {"color": "#e8a84c", "emoji": "👨‍🍳", "label": "EN COCINA"},
    "listo":     {"color": "#4caf50", "emoji": "🔔", "label": "LISTO"},
}


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


def _kds_beep_wav() -> bytes:
    sample_rate = 8000
    duration = 0.16
    frequency = 880
    frames = bytearray()
    for index in range(int(sample_rate * duration)):
        sample = int(18000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(sample.to_bytes(2, "little", signed=True))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return buf.getvalue()


def _notificar_estado_kds(total_pedidos: int) -> None:
    titulo = f"({total_pedidos}) KDS Cocina" if total_pedidos else "KDS Cocina"
    st.markdown(
        f"<script>document.title = {json.dumps(titulo)};</script>",
        unsafe_allow_html=True,
    )
    prev = st.session_state.get("kds_prev_total")
    st.session_state.kds_prev_total = total_pedidos
    if prev is not None and total_pedidos > int(prev):
        nuevos = total_pedidos - int(prev)
        st.toast(f"🍽 {nuevos} pedido(s) nuevo(s) en cocina!")
        st.audio(_kds_beep_wav(), format="audio/wav")


def _avanzar_pedido(id_pedido: int, estado_actual: str) -> None:
    result = avanzar_estado(id_pedido, estado_actual)
    if result["ok"]:
        for w in result.get("advertencias", []):
            st.toast(w, icon="⚠️")
    else:
        st.error(f"Error: {result['error']}")


def _marcar_entregado(id_pedido: int) -> None:
    conn = get_connection_direct()
    try:
        conn.execute(
            "UPDATE pedidos_cabecera SET estado_comanda='entregado' WHERE id_pedido=?",
            (id_pedido,),
        )
        conn.commit()
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        conn.close()


@st.fragment(run_every=10)
def _monitor_kds() -> None:
    conn = get_connection_direct()
    try:
        rows = conn.execute("""
            SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda,
                   m.numero_mesa, u.nombre || ' ' || u.apellido AS mozo,
                   pd.cantidad, pd.observaciones, pm.nombre AS producto,
                   pd.id_detalle
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo')
              AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
            ORDER BY pc.fecha_hora ASC, pd.id_detalle ASC
        """).fetchall()
    finally:
        conn.close()

    pedidos: dict[int, dict] = {}
    for r in rows:
        pid = r["id_pedido"]
        if pid not in pedidos:
            pedidos[pid] = {
                "id": pid, "mesa": r["numero_mesa"], "mozo": r["mozo"],
                "fecha": r["fecha_hora"], "estado": r["estado_comanda"], "items": [],
            }
        pedidos[pid]["items"].append({
            "cantidad": int(r["cantidad"]),
            "producto": r["producto"],
            "obs": (r["observaciones"] or "").strip(),
        })

    orden_estados = {"pendiente": 0, "en_cocina": 1, "listo": 2}
    cards = sorted(
        pedidos.values(),
        key=lambda p: (orden_estados.get(p["estado"], 9), p["fecha"] or ""),
    )

    total_pedidos = len(cards)
    _notificar_estado_kds(total_pedidos)

    # Cabecera con contadores y filtro
    c_logo, c_stats, c_filtro = st.columns([1, 3, 2])
    with c_logo:
        st.markdown("## 🍳 KDS")
    with c_stats:
        pendientes = sum(1 for p in cards if p["estado"] == "pendiente")
        en_cocina  = sum(1 for p in cards if p["estado"] == "en_cocina")
        listos     = sum(1 for p in cards if p["estado"] == "listo")
        st.markdown(
            f"<span style='font-size:1rem;color:#b8b0a4'>"
            f"⏳ <b style='color:#c93a2b'>{pendientes}</b> pend. &nbsp;"
            f"👨‍🍳 <b style='color:#e8a84c'>{en_cocina}</b> cocina &nbsp;"
            f"🔔 <b style='color:#4caf50'>{listos}</b> listos &nbsp;·&nbsp;"
            f"<span style='color:#e8a84c'>{datetime.now():%H:%M}</span></span>",
            unsafe_allow_html=True,
        )
    with c_filtro:
        filtro = st.selectbox(
            "Filtrar", ["Todos", "⏳ Pendientes", "👨‍🍳 En cocina", "🔔 Listos"],
            label_visibility="collapsed", key="kds_filtro",
        )

    st.markdown("---")

    mapa_filtro = {"⏳ Pendientes": "pendiente", "👨‍🍳 En cocina": "en_cocina", "🔔 Listos": "listo"}
    if filtro in mapa_filtro:
        cards = [p for p in cards if p["estado"] == mapa_filtro[filtro]]

    if not cards:
        st.markdown("<div class='kds-empty'>✅ Sin pedidos activos. La cocina está al día.</div>",
                    unsafe_allow_html=True)
        return

    COLS = 4
    for i in range(0, len(cards), COLS):
        cols = st.columns(COLS, gap="small")
        for col, ped in zip(cols, cards[i : i + COLS]):
            mins, hora = _demora_minutos(ped["fecha"])
            cfg = ESTADO_CONFIG.get(ped["estado"], ESTADO_CONFIG["pendiente"])

            if mins >= 20:
                demora_html = f'<span class="kds-alerta">🔴 {mins} min</span>'
            elif mins >= 12:
                demora_html = f'<span style="color:#e8a84c;font-weight:700">⚠️ {mins} min</span>'
            else:
                demora_html = f'<span style="color:#8a847a">{mins} min</span>'

            html_items = ""
            for item in ped["items"]:
                obs_html = f'<div class="kds-obs">📝 {item["obs"]}</div>' if item["obs"] else ""
                html_items += (
                    f'<div class="kds-item">'
                    f'<span class="kds-cantidad">{item["cantidad"]}x</span>'
                    f'<span>{item["producto"]}</span>{obs_html}</div>'
                )

            with col:
                st.markdown(
                    f"""<div class="kds-card" style="border-top:3px solid {cfg['color']}">
                    <div class="kds-header">
                        <div class="kds-mesa">{cfg['emoji']} MESA {ped['mesa']}</div>
                        <div class="kds-tiempo">{hora}<br>{demora_html}</div>
                    </div>
                    <div class="kds-body">
                        {html_items}
                        <div class="kds-meta">{ped['mozo']} · {cfg['label']}</div>
                    </div></div>""",
                    unsafe_allow_html=True,
                )
                # Botones de accion
                if ped["estado"] == "pendiente":
                    if st.button("🍳 Tomar", key=f"btn_{ped['id']}_tomar",
                                 use_container_width=True, type="primary"):
                        _avanzar_pedido(ped["id"], "pendiente")
                        st.rerun()
                elif ped["estado"] == "en_cocina":
                    if st.button("✅ Listo", key=f"btn_{ped['id']}_listo",
                                 use_container_width=True, type="primary"):
                        _avanzar_pedido(ped["id"], "en_cocina")
                        st.rerun()
                elif ped["estado"] == "listo":
                    if st.button("🚀 Entregar", key=f"btn_{ped['id']}_entregar",
                                 use_container_width=True):
                        _marcar_entregado(ped["id"])
                        st.rerun()


def render() -> None:
    if "kds_css_injected" not in st.session_state:
        st.markdown(CSS_KDS, unsafe_allow_html=True)
        st.session_state.kds_css_injected = True

    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "margin-bottom:0.5rem'>"
        "<span style='font-size:1.5rem;font-weight:800'>MONITOR DE COCINA</span>"
        "<span style='color:#8a847a;font-size:0.82rem'>"
        "Auto-refresh 10s · Botones de accion activos</span></div>",
        unsafe_allow_html=True,
    )
    _monitor_kds()
