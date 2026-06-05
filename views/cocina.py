"""
views/cocina.py — KDS: Monitor de Cocina con estética vintage.
Semáforo: Verde Oliva (<10 min), Mostaza (10-18 min), Terracota (>=19 min).
Corrige: PostgreSQL compat, time.sleep bloqueante, KeyError estado.
"""
from __future__ import annotations

import math
import struct
import tempfile
import time
import wave
from datetime import datetime

import streamlit as st
from database import get_connection_direct, confirmar_pedido_cocina
from components.estilos import color_kds, borde_kds


def _generar_tono(frecuencia: float = 880, duracion: float = 0.3,
                  sample_rate: int = 22050) -> str | None:
    """Genera un archivo WAV temporal con un tono senoidal."""
    try:
        n_samples = int(sample_rate * duracion)
        samples = []
        for i in range(n_samples):
            t = i / sample_rate
            v = int(16000 * math.sin(2 * math.pi * frecuencia * t))
            samples.append(struct.pack("<h", v))
        path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        with wave.open(path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"".join(samples))
        return path
    except Exception:
        return None


def render() -> None:
    st.markdown("<h1 style='text-align:center'>👨‍🍳  KDS — Monitor de Cocina</h1>",
                unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center;font-style:italic;color:#2C221E'>"
        "🟢 Óptimo  ·  🟡 Alerta (>10 min)  ·  🔴 Crítica (>19 min)</p>",
        unsafe_allow_html=True,
    )

    conn = get_connection_direct()
    try:
        cur = conn.execute(f"""
            SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda,
                   m.numero_mesa,
                   u.nombre || ' ' || u.apellido AS mozo
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo')
            ORDER BY pc.fecha_hora
        """)
        filas = cur.fetchall()
    finally:
        conn.close()

    # Agrupar por estado — tolera estados inesperados
    estados_validos = {"pendiente", "en_cocina", "listo"}
    grupos = {e: [] for e in estados_validos}
    for f in filas:
        key = f.get("estado_comanda", "")
        if key in grupos:
            grupos[key].append(f)
        # ignorar estados no manejados

    # Notificación de nuevos pedidos
    pendientes_actuales = len(grupos["pendiente"])
    prev = st.session_state.get("kds_pendientes_prev", -1)
    if prev != -1 and pendientes_actuales > prev:
        diff = pendientes_actuales - prev
        st.toast(f"🔔  {diff} nuevo(s) pedido(s) recibido(s)!", icon="🍽")
        wav_path = _generar_tono(660, 0.25)
        if wav_path:
            with open(wav_path, "rb") as f:
                st.audio(f.read(), format="audio/wav", autoplay=True)
    st.session_state.kds_pendientes_prev = pendientes_actuales

    # Badge en título
    total_activos = pendientes_actuales + len(grupos["en_cocina"])
    if total_activos > 0:
        js = f"<script>document.title = '({total_activos}) KDS — COMANDAPRO';</script>"
        st.markdown(js, unsafe_allow_html=True)

    # Columnas
    col1, col2, col3 = st.columns(3, gap="medium")
    configs = [
        ("PENDIENTES",  "pendiente", "#8B2635", "👨‍🍳 Iniciar"),
        ("EN PREPARACIÓN", "en_cocina", "#7A8450", "✅ Marcar listo"),
        ("LISTOS PARA SERVIR", "listo", "#B58A63", None),
    ]

    for col, (titulo, estado, color_hdr, btn_txt) in zip(
            [col1, col2, col3], configs):
        with col:
            items = grupos.get(estado, [])
            st.markdown(
                f"<h3 style='text-align:center;background:{color_hdr};padding:10px;"
                f"border-radius:8px;color:#fafafa;font-family:Playfair Display,serif'>"
                f"{titulo} ({len(items)})</h3>",
                unsafe_allow_html=True,
            )

            for item in items:
                ahora = datetime.now()
                fh = (item.get("fecha_hora") or "")[:19]
                mins = 0
                try:
                    mins = int(
                        (ahora - datetime.strptime(fh, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
                    )
                except (ValueError, TypeError):
                    pass

                bg, etiqueta = color_kds(mins)
                bdr = borde_kds(mins)

                st.markdown(f"""
                    <div class='kds-card' style='background:{bg}22;border:{bdr}'>
                        <div class='kds-card-tiempo'>
                            <span>🍽 Mesa #{item.get('numero_mesa', '?')}</span>
                            <span>{etiqueta} · {mins} min</span>
                        </div>
                        <div style='margin:4px 0;opacity:0.8'>{item.get('mozo', '')}</div>
                    </div>
                """, unsafe_allow_html=True)

                if btn_txt:
                    if st.button(btn_txt, key=f"k_{item.get('id_pedido')}_{estado}",
                                 use_container_width=True):
                        if estado == "pendiente":
                            conn2 = get_connection_direct()
                            try:
                                conn2.execute(
                                    "UPDATE pedidos_cabecera SET estado_comanda='en_cocina'"
                                    " WHERE id_pedido=?",
                                    (item.get("id_pedido"),)
                                )
                                conn2.commit()
                            except Exception as e:
                                st.error(f"Error: {e}")
                            finally:
                                conn2.close()
                        elif estado == "en_cocina":
                            result = confirmar_pedido_cocina(item.get("id_pedido"))
                            if result.get("advertencias"):
                                for w in result["advertencias"]:
                                    st.toast(w, icon="🥕")
                        wav_path = _generar_tono(440, 0.15)
                        if wav_path:
                            with open(wav_path, "rb") as f:
                                st.audio(f.read(), format="audio/wav", autoplay=True)
                        st.rerun()

    # Auto-refresh no bloqueante
    REFRESH_SECONDS = 10
    last = st.session_state.get("kds_last_refresh", 0)
    now = time.time()
    if now - last >= REFRESH_SECONDS:
        st.session_state.kds_last_refresh = now
        st.rerun()
