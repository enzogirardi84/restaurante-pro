"""
views/cocina.py — KDS: Monitor de Cocina con notificaciones, sonidos
y temporizador vintage.
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
                  sample_rate: int = 22050) -> str:
    """Genera un archivo WAV temporal con un tono senoidal."""
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
        cur = conn.execute("""
            SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda,
                   m.numero_mesa,
                   u.nombre || ' ' || u.apellido AS mozo,
                   GROUP_CONCAT(
                       '(' || pd.cantidad || 'x) ' || pm.nombre ||
                       CASE WHEN pd.observaciones != '' THEN ' [' || pd.observaciones || ']' ELSE '' END,
                       '\n'
                   ) AS detalle
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo')
            GROUP BY pc.id_pedido
            ORDER BY pc.fecha_hora
        """)
        filas = cur.fetchall()
    finally:
        conn.close()

    grupos = {"pendiente": [], "en_cocina": [], "listo": []}
    for f in filas:
        grupos[f["estado_comanda"]].append(f)

    # ── Notificación de nuevos pedidos ─────────────────────────────────
    pendientes_actuales = len(grupos["pendiente"])
    prev = st.session_state.get("kds_pendientes_prev", -1)

    if prev != -1 and pendientes_actuales > prev:
        diff = pendientes_actuales - prev
        st.toast(f"🔔  {diff} nuevo(s) pedido(s) recibido(s)!", icon="🍽")
        # Reproducir tono
        wav_path = _generar_tono(660, 0.25)
        with open(wav_path, "rb") as f:
            st.audio(f.read(), format="audio/wav", autoplay=True)
    st.session_state.kds_pendientes_prev = pendientes_actuales

    # ── Badge en título de página ──────────────────────────────────────
    total_activos = pendientes_actuales + len(grupos["en_cocina"])
    if total_activos > 0:
        js = f"""
        <script>
        document.title = "({total_activos}) KDS — COMANDAPRO";
        </script>
        """
        st.markdown(js, unsafe_allow_html=True)

    # ── Columnas ───────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3, gap="medium")
    configs = [
        ("PENDIENTES",  "pendiente", "#8B2635", "👨‍🍳 Iniciar"),
        ("EN PREPARACIÓN", "en_cocina", "#7A8450", "✅ Marcar listo"),
        ("LISTOS PARA SERVIR", "listo", "#B58A63", None),
    ]

    for col, (titulo, estado, color_hdr, btn_txt) in zip(
            [col1, col2, col3], configs):
        with col:
            st.markdown(
                f"<h3 style='text-align:center;background:{color_hdr};padding:10px;"
                f"border-radius:8px;color:#fafafa;font-family:Playfair Display,serif'>"
                f"{titulo} ({len(grupos[estado])})</h3>",
                unsafe_allow_html=True,
            )

            for item in grupos[estado]:
                ahora = datetime.now()
                fh = (item["fecha_hora"] or "")[:19]
                mins = 0
                try:
                    mins = int(
                        (ahora - datetime.strptime(fh, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
                    )
                except ValueError:
                    pass

                bg, etiqueta = color_kds(mins)
                bdr = borde_kds(mins)

                st.markdown(f"""
                    <div class='kds-card' style='background:{bg}22;border:{bdr}'>
                        <div class='kds-card-tiempo'>
                            <span>🍽 Mesa #{item['numero_mesa']}</span>
                            <span>{etiqueta} · {mins} min</span>
                        </div>
                        <div style='margin:4px 0;opacity:0.8'>{item['mozo']}</div>
                        <pre style='white-space:pre-wrap;margin:4px 0;font-size:0.9em'>{item['detalle']}</pre>
                    </div>
                """, unsafe_allow_html=True)

                if btn_txt:
                    if st.button(btn_txt, key=f"k_{item['id_pedido']}_{estado}",
                                 use_container_width=True):
                        if estado == "pendiente":
                            conn2 = get_connection_direct()
                            try:
                                conn2.execute(
                                    "UPDATE pedidos_cabecera SET estado_comanda='en_cocina'"
                                    " WHERE id_pedido=?",
                                    (item["id_pedido"],)
                                )
                                conn2.commit()
                            finally:
                                conn2.close()
                        elif estado == "en_cocina":
                            result = confirmar_pedido_cocina(item["id_pedido"])
                            if result.get("advertencias"):
                                for w in result["advertencias"]:
                                    st.toast(w, icon="🥕")
                        # Tono de confirmación
                        wav_path = _generar_tono(440, 0.15)
                        with open(wav_path, "rb") as f:
                            st.audio(f.read(), format="audio/wav", autoplay=True)
                        st.rerun()

    time.sleep(10)
    st.rerun()
