"""
components/tickets.py — Impresión ESC/POS con auto-detección de
impresora, fallback a archivo, exportación a HTML y descarga de PDF.
"""
from __future__ import annotations

import base64
import io
import os
import platform
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
from database import get_connection_direct
import config

ANCHO_TICKET = 32
SEP = "=" * ANCHO_TICKET
LIN = "-" * ANCHO_TICKET


# ── Formateo texto plano ──────────────────────────────────────────────

def formatear_comprobante(id_pedido: int) -> str:
        """Genera el texto plano del ticket ESC/POS."""
        conn = get_connection_direct()
        try:
                    cur = conn.execute("""
                                SELECT pc.id_pedido, pc.fecha_hora,
                                                   m.numero_mesa,
                                                                      u.nombre || ' ' || u.apellido AS mozo
                                                                                  FROM pedidos_cabecera pc
                                                                                              JOIN mesas m ON m.id_mesa = pc.id_mesa
                                                                                                          JOIN usuarios u ON u.id_usuario = pc.id_usuario
                                                                                                                      WHERE pc.id_pedido = ?
                                                                                                                              """, (id_pedido,))
                    pedido = cur.fetchone()
                    if not pedido:
                                    return "ERROR: Pedido no encontrado."

                    lines = [""]
                    lines.append(f"{config.NOMBRE_LOCAL:^{ANCHO_TICKET}}")
                    lines.append(f"{config.DIRECCION_LOCAL:^{ANCHO_TICKET}}")
                    lines.append(f"CUIT: {config.CUIT_LOCAL:^{ANCHO_TICKET - 5}}")
                    lines.append(SEP)
                    lines.append(f"Mesa: {pedido['numero_mesa']}")
                    lines.append(f"Mozo: {pedido['mozo']}")
                    fecha = (pedido["fecha_hora"] or "")[:19]
                    lines.append(f"Fecha: {fecha}")
                    lines.append(f"Comp.: P-{pedido['id_pedido']:06d}")
                    lines.append(SEP)
                    lines.append(f"{'Cant':>4} {'Producto':<16} {'Precio':>7}")
                    lines.append(LIN)

            cur = conn.execute("""
                        SELECT pm.nombre, pd.cantidad, pd.precio_unitario_facturado
                                    FROM pedido_detalle pd
                                                JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                                                            WHERE pd.id_pedido = ?
                                                                        ORDER BY pm.categoria, pm.nombre
                                                                                """, (id_pedido,))
        subtotal = 0
        for item in cur.fetchall():
                        importe = item["cantidad"] * item["precio_unitario_facturado"]
                        subtotal += importe
                        nombre_corto = str(item["nombre"])[:16]
                        lines.append(f"{item['cantidad']:>4} {nombre_corto:<16} ${importe:>6,.0f}")

        servicio = round(subtotal * config.SERVICIO_PORCENTAJE / 100)
        total = subtotal + servicio
        lines.append(LIN)
        lines.append(f"{'SUBTOTAL':>22} ${subtotal:>6,.0f}")
        lines.append(f"{'SERVICIO':>22} ${servicio:>6,.0f}")
        lines.append(SEP)
        lines.append(f"{'TOTAL':>22} ${total:>6,.0f}")
        lines.append(SEP)
        lines.append(f"{'¡Gracias!':^{ANCHO_TICKET}}")
        lines += ["", "", ""]
        return "\n".join(lines)
finally:
        conn.close()


def _get_datos_pedido(id_pedido: int) -> dict | None:
        """Retorna cabecera + items del pedido para renderizado."""
    conn = get_connection_direct()
    try:
                cur = conn.execute("""
                            SELECT pc.id_pedido, pc.fecha_hora,
                                               m.numero_mesa,
                                                                  u.nombre || ' ' || u.apellido AS mozo
                                                                              FROM pedidos_cabecera pc
                                                                                          JOIN mesas m ON m.id_mesa = pc.id_mesa
                                                                                                      JOIN usuarios u ON u.id_usuario = pc.id_usuario
                                                                                                                  WHERE pc.id_pedido = ?
                                                                                                                          """, (id_pedido,))
                cabecera = cur.fetchone()
                if not cabecera:
                                return None

                cur2 = conn.execute("""
                    SELECT pm.nombre, pd.cantidad, pd.precio_unitario_facturado,
                           (pd.cantidad * pd.precio_unitario_facturado) AS importe
                    FROM pedido_detalle pd
                    JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                    WHERE pd.id_pedido = ?
                    ORDER BY pm.categoria, pm.nombre
                """, (id_pedido,))
                items = cur2.fetchall()
                subtotal = sum(r["importe"] for r in items)
                servicio = round(subtotal * config.SERVICIO_PORCENTAJE / 100)
                total = subtotal + servicio

        return {
                        "cabecera": dict(cabecera),
                        "items": [dict(r) for r in items],
                        "subtotal": subtotal,
                        "servicio": servicio,
                        "total": total,
        }
finally:
        conn.close()


# ── Exportar a HTML ───────────────────────────────────────────────────

def ticket_a_html(id_pedido: int) -> str:
        """Genera HTML con estilo ticket para vista previa y descarga."""
    datos = _get_datos_pedido(id_pedido)
    if not datos:
                return "<html><body><p>Error: pedido no encontrado.</p></body></html>"

    cab = datos["cabecera"]
    items = datos["items"]
    fecha = (cab.get("fecha_hora") or "")[:19]

    filas_html = ""
    for it in items:
                filas_html += f"""
                        <tr>
                                  <td style="text-align:center">{it['cantidad']}</td>
                                            <td>{it['nombre']}</td>
                                                      <td style="text-align:right">${it['importe']:,.0f}</td>
                                                              </tr>"""

    return f"""<!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
          <title>Ticket P-{cab['id_pedido']:06d}</title>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                    body {{
                          background: #F4EAE1;
                                font-family: 'Courier New', Courier, monospace;
                                      font-size: 13px;
                                            color: #2C221E;
                                                  display: flex;
                                                        justify-content: center;
                                                              padding: 30px 10px;
                                                                  }}
                                                                      .ticket {{
                                                                            background: white;
                                                                                  width: 300px;
                                                                                        padding: 24px 20px;
                                                                                              border-radius: 10px;
                                                                                                    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
                                                                                                          border-top: 4px solid #8B2635;
                                                                                                              }}
                                                                                                                  .local {{ text-align: center; margin-bottom: 4px; }}
                                                                                                                      .local h2 {{ font-size: 16px; font-weight: 700; letter-spacing: 1px; }}
                                                                                                                          .local p {{ font-size: 11px; color: #555; }}
                                                                                                                              hr {{ border: none; border-top: 1px dashed #ccc; margin: 10px 0; }}
                                                                                                                                  hr.double {{ border-top: 2px solid #2C221E; }}
                                                                                                                                      .meta {{ font-size: 11px; margin-bottom: 6px; }}
                                                                                                                                          .meta span {{ display: block; }}
                                                                                                                                              table {{ width: 100%; border-collapse: collapse; margin: 6px 0; }}
                                                                                                                                                  th {{ font-size: 11px; border-bottom: 1px solid #999; padding: 3px 0; text-align: left; }}
                                                                                                                                                      th:last-child {{ text-align: right; }}
                                                                                                                                                          td {{ font-size: 12px; padding: 3px 0; vertical-align: top; }}
                                                                                                                                                              .totales {{ margin-top: 6px; font-size: 12px; }}
                                                                                                                                                                  .totales tr td:last-child {{ text-align: right; font-weight: 600; }}
                                                                                                                                                                      .total-final {{ font-size: 15px; font-weight: 800; color: #8B2635; }}
                                                                                                                                                                          .gracias {{ text-align: center; margin-top: 14px; font-size: 13px;
                                                                                                                                                                                          font-style: italic; color: #555; }}
                                                                                                                                                                                              @media print {{
                                                                                                                                                                                                    body {{ background: white; padding: 0; }}
                                                                                                                                                                                                          .ticket {{ box-shadow: none; border: none; width: 100%; }}
                                                                                                                                                                                                                .no-print {{ display: none; }}
                                                                                                                                                                                                                    }}
                                                                                                                                                                                                                      </style>
                                                                                                                                                                                                                      </head>
                                                                                                                                                                                                                      <body>
                                                                                                                                                                                                                      <div class="ticket">
                                                                                                                                                                                                                        <div class="local">
                                                                                                                                                                                                                            <h2>{config.NOMBRE_LOCAL}</h2>
                                                                                                                                                                                                                                <p>{config.DIRECCION_LOCAL}</p>
                                                                                                                                                                                                                                    <p>CUIT: {config.CUIT_LOCAL}</p>
                                                                                                                                                                                                                                      </div>
                                                                                                                                                                                                                                        <hr class="double">
                                                                                                                                                                                                                                          <div class="meta">
                                                                                                                                                                                                                                              <span><b>Mesa:</b> {cab['numero_mesa']}</span>
                                                                                                                                                                                                                                                  <span><b>Mozo:</b> {cab['mozo']}</span>
                                                                                                                                                                                                                                                      <span><b>Fecha:</b> {fecha}</span>
                                                                                                                                                                                                                                                          <span><b>Comp.:</b> P-{cab['id_pedido']:06d}</span>
                                                                                                                                                                                                                                                            </div>
                                                                                                                                                                                                                                                              <hr>
                                                                                                                                                                                                                                                                <table>
                                                                                                                                                                                                                                                                    <thead>
                                                                                                                                                                                                                                                                          <tr>
                                                                                                                                                                                                                                                                                  <th style="text-align:center">Cant</th>
                                                                                                                                                                                                                                                                                          <th>Producto</th>
                                                                                                                                                                                                                                                                                                  <th style="text-align:right">Precio</th>
                                                                                                                                                                                                                                                                                                        </tr>
                                                                                                                                                                                                                                                                                                            </thead>
                                                                                                                                                                                                                                                                                                                <tbody>{filas_html}
                                                                                                                                                                                                                                                                                                                    </tbody>
                                                                                                                                                                                                                                                                                                                      </table>
                                                                                                                                                                                                                                                                                                                        <hr class="double">
                                                                                                                                                                                                                                                                                                                          <table class="totales">
                                                                                                                                                                                                                                                                                                                              <tr><td>Subtotal</td><td>${datos['subtotal']:,.0f}</td></tr>
                                                                                                                                                                                                                                                                                                                                  <tr><td>Servicio ({config.SERVICIO_PORCENTAJE}%)</td><td>${datos['servicio']:,.0f}</td></tr>
                                                                                                                                                                                                                                                                                                                                      <tr class="total-final"><td>TOTAL</td><td>${datos['total']:,.0f}</td></tr>
                                                                                                                                                                                                                                                                                                                                        </table>
                                                                                                                                                                                                                                                                                                                                          <hr>
                                                                                                                                                                                                                                                                                                                                            <p class="gracias">¡Gracias por su visita!</p>
                                                                                                                                                                                                                                                                                                                                              <br>
                                                                                                                                                                                                                                                                                                                                                <div class="no-print" style="text-align:center;margin-top:12px">
                                                                                                                                                                                                                                                                                                                                                    <button onclick="window.print()"
      style="background:#8B2635;color:white;border:none;padding:8px 20px;
                   border-radius:6px;cursor:pointer;font-size:13px">
                         🖨 Imprimir
                             </button>
                               </div>
                               </div>
                               </body>
                               </html>"""


# ── Generar PDF con reportlab (fallback a HTML base64) ────────────────

def ticket_a_pdf_bytes(id_pedido: int) -> bytes | None:
        """
            Genera un PDF del ticket usando reportlab.
                Retorna bytes del PDF o None si reportlab no está disponible.
                    """
    try:
                from reportlab.lib.pagesizes import A7
                from reportlab.lib import colors
                from reportlab.lib.units import mm
                from reportlab.platypus import (
                    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
except ImportError:
        return None

    datos = _get_datos_pedido(id_pedido)
    if not datos:
                return None

    cab = datos["cabecera"]
    items = datos["items"]
    fecha = (cab.get("fecha_hora") or "")[:19]

    buf = io.BytesIO()
    ancho = 80 * mm
    alto = 200 * mm
    doc = SimpleDocTemplate(
                buf,
                pagesize=(ancho, alto),
                leftMargin=5 * mm, rightMargin=5 * mm,
                topMargin=5 * mm, bottomMargin=5 * mm,
    )

    styles = getSampleStyleSheet()
    estilo_center = ParagraphStyle("center", parent=styles["Normal"],
                                                                      alignment=TA_CENTER, fontSize=9)
    estilo_titulo = ParagraphStyle("titulo", parent=styles["Normal"],
                                                                      alignment=TA_CENTER, fontSize=11,
                                                                      fontName="Helvetica-Bold")
    estilo_normal = ParagraphStyle("normal", parent=styles["Normal"],
                                                                      fontSize=8, leading=11)
    estilo_total = ParagraphStyle("total", parent=styles["Normal"],
                                                                    fontSize=10, fontName="Helvetica-Bold",
                                                                    alignment=TA_RIGHT)

    story = []
    story.append(Paragraph(config.NOMBRE_LOCAL, estilo_titulo))
    if config.DIRECCION_LOCAL:
                story.append(Paragraph(config.DIRECCION_LOCAL, estilo_center))
            if config.CUIT_LOCAL:
                        story.append(Paragraph(f"CUIT: {config.CUIT_LOCAL}", estilo_center))
                    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.black))
    story.append(Spacer(1, 2 * mm))

    meta = [
                f"Mesa: {cab['numero_mesa']}",
                f"Mozo: {cab['mozo']}",
                f"Fecha: {fecha}",
                f"Comp.: P-{cab['id_pedido']:06d}",
    ]
    for m in meta:
                story.append(Paragraph(m, estilo_normal))

    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 1 * mm))

    # Tabla de items
    tabla_data = [["Cant", "Producto", "Precio"]]
    for it in items:
                tabla_data.append([
                                str(it["cantidad"]),
                                str(it["nombre"]),
                                f"${it['importe']:,.0f}",
                ])

    tabla = Table(tabla_data, colWidths=[8 * mm, 45 * mm, 17 * mm])
    tabla.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9F5F2")]),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(tabla)

    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.black))
    story.append(Spacer(1, 1 * mm))

    # Totales
    totales_data = [
                ["Subtotal", f"${datos['subtotal']:,.0f}"],
                [f"Servicio ({config.SERVICIO_PORCENTAJE}%)", f"${datos['servicio']:,.0f}"],
                ["TOTAL", f"${datos['total']:,.0f}"],
    ]
    tabla_totales = Table(totales_data, colWidths=[45 * mm, 25 * mm])
    tabla_totales.setStyle(TableStyle([
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 1), 8),
                ("FONTSIZE", (0, 2), (-1, 2), 10),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, 2), (-1, 2), 1, colors.black),
                ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#8B2635")),
    ]))
    story.append(tabla_totales)

    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("¡Gracias por su visita!", estilo_center))

    doc.build(story)
    return buf.getvalue()


# ── Botones Streamlit para visualizar / descargar ticket ──────────────

def mostrar_ticket_streamlit(id_pedido: int) -> None:
        """
            Renderiza el ticket dentro de Streamlit con:
                - Vista previa visual en pantalla
                    - Botón de descarga PDF
                        - Botón de descarga HTML (fallback)
                            """
    datos = _get_datos_pedido(id_pedido)
    if not datos:
                st.error("No se encontró el pedido para generar el ticket.")
                return

    cab = datos["cabecera"]
    items = datos["items"]
    fecha = (cab.get("fecha_hora") or "")[:19]

    # ── Vista previa visual ───────────────────────────────────────────
    with st.container():
                st.markdown(
                                """
                                            <style>
                                                        .ticket-box {
                                                                        background: white;
                                                                                        border-radius: 12px;
                                                                                                        padding: 24px 20px;
                                                                                                                        max-width: 340px;
                                                                                                                                        margin: auto;
                                                                                                                                                        box-shadow: 0 4px 20px rgba(0,0,0,0.12);
                                                                                                                                                                        font-family: 'Courier New', monospace;
                                                                                                                                                                                        border-top: 5px solid #8B2635;
                                                                                                                                                                                                    }
                                                                                                                                                                                                                .ticket-header { text-align: center; margin-bottom: 8px; }
                                                                                                                                                                                                                            .ticket-header h3 { font-size: 15px; margin: 0; color: #2C221E; }
                                                                                                                                                                                                                                        .ticket-header p { font-size: 11px; color: #777; margin: 2px 0; }
                                                                                                                                                                                                                                                    .ticket-sep { border: none; border-top: 1px dashed #ccc; margin: 8px 0; }
                                                                                                                                                                                                                                                                .ticket-sep-bold { border: none; border-top: 2px solid #2C221E; margin: 8px 0; }
                                                                                                                                                                                                                                                                            .ticket-meta { font-size: 12px; margin: 6px 0; }
                                                                                                                                                                                                                                                                                        .ticket-item { display: flex; justify-content: space-between;
                                                                                                                                                                                                                                                                                                                   font-size: 12px; padding: 3px 0; border-bottom: 1px dotted #eee; }
                                                                                                                                                                                                                                                                                                                               .ticket-totals { font-size: 12px; margin-top: 6px; }
                                                                                                                                                                                                                                                                                                                                           .ticket-totals .row { display: flex; justify-content: space-between; padding: 2px 0; }
                                                                                                                                                                                                                                                                                                                                                       .ticket-totals .total { font-weight: 800; font-size: 15px; color: #8B2635; }
                                                                                                                                                                                                                                                                                                                                                                   .ticket-footer { text-align: center; margin-top: 12px;
                                                                                                                                                                                                                                                                                                                                                                                                font-style: italic; color: #777; font-size: 12px; }
                                                                                                                                                                                                                                                                                                                                                                                                            </style>
                                                                                                                                                                                                                                                                                                                                                                                                                        """,
                                unsafe_allow_html=True,
                )

        filas = "".join(
                        f"<div class='ticket-item'>"
                        f"<span><b>{it['cantidad']}x</b> {it['nombre']}</span>"
                        f"<span>${it['importe']:,.0f}</span></div>"
                        for it in items
        )

        st.markdown(
                        f"""
                                    <div class="ticket-box">
                                                  <div class="ticket-header">
                                                                  <h3>{config.NOMBRE_LOCAL}</h3>
                                                                                  <p>{config.DIRECCION_LOCAL}</p>
                                                                                                  <p>CUIT: {config.CUIT_LOCAL}</p>
                                                                                                                </div>
                                                                                                                              <hr class="ticket-sep-bold">
                                                                                                                                            <div class="ticket-meta">
                                                                                                                                                            <b>Mesa:</b> {cab['numero_mesa']}<br>
                                                                                                                                                                            <b>Mozo:</b> {cab['mozo']}<br>
                                                                                                                                                                                            <b>Fecha:</b> {fecha}<br>
                                                                                                                                                                                                            <b>Comp.:</b> P-{cab['id_pedido']:06d}
                                                                                                                                                                                                                          </div>
                                                                                                                                                                                                                                        <hr class="ticket-sep">
                                                                                                                                                                                                                                                      <div style="font-size:11px;display:flex;justify-content:space-between;
                                                                                                                                                                                                                                                                                font-weight:bold;padding-bottom:4px">
                                                                                                                                                                                                                                                                                                <span>Cant · Producto</span><span>Precio</span>
                                                                                                                                                                                                                                                                                                              </div>
                                                                                                                                                                                                                                                                                                                            {filas}
                                                                                                                                                                                                                                                                                                                                          <hr class="ticket-sep-bold">
                                                                                                                                                                                                                                                                                                                                                        <div class="ticket-totals">
                                                                                                                                                                                                                                                                                                                                                                        <div class="row"><span>Subtotal</span><span>${datos['subtotal']:,.0f}</span></div>
                                                                                                                                                                                                                                                                                                                                                                                        <div class="row"><span>Servicio ({config.SERVICIO_PORCENTAJE}%)</span>
                                                                                                                                                                                                                                                                                                                                                                                                             <span>${datos['servicio']:,.0f}</span></div>
                                                                                                                                                                                                                                                                                                                                                                                                                             <div class="row total"><span>TOTAL</span><span>${datos['total']:,.0f}</span></div>
                                                                                                                                                                                                                                                                                                                                                                                                                                           </div>
                                                                                                                                                                                                                                                                                                                                                                                                                                                         <hr class="ticket-sep">
                                                                                                                                                                                                                                                                                                                                                                                                                                                                       <p class="ticket-footer">¡Gracias por su visita!</p>
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   </div>
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               """,
                        unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Botones de descarga ───────────────────────────────────────────
    col_pdf, col_html = st.columns(2)

    with col_pdf:
                pdf_bytes = ticket_a_pdf_bytes(id_pedido)
                if pdf_bytes:
                                st.download_button(
                                                    label="⬇ Descargar PDF",
                                                    data=pdf_bytes,
                                                    file_name=f"ticket_P{id_pedido:06d}.pdf",
                                                    mime="application/pdf",
                                                    use_container_width=True,
                                                    type="primary",
                                )
else:
            st.info("Instala `reportlab` para habilitar descarga PDF.")

    with col_html:
                html_content = ticket_a_html(id_pedido)
                st.download_button(
                    label="⬇ Descargar HTML",
                    data=html_content.encode("utf-8"),
                    file_name=f"ticket_P{id_pedido:06d}.html",
                    mime="text/html",
                    use_container_width=True,
                )


# ── Auto-detección de impresoras ──────────────────────────────────────

def _detectar_puerto() -> str | None:
        sistema = platform.system()

    if sistema == "Windows":
                for com in range(1, 10):
                                puerto = f"COM{com}"
                                try:
                                                    with open(f"\\\\.\\{puerto}", "wb"):
                                                                            return puerto
                                except OSError:
                                                    continue
                                            return None

    if sistema == "Linux":
                for p in sorted(Path("/dev/usb").glob("lp*")):
                                return str(p)
                            for p in sorted(Path("/dev").glob("lp*")):
                                            return str(p)
                                        try:
                                                        out = subprocess.check_output(["lpinfo", "-v"], text=True)
                                                        for line in out.splitlines():
                                                                            if "usb" in line.lower():
                                                                                                    parts = line.split()
                                                                                                    if len(parts) >= 2:
                                                                                                                                return parts[-1]
                                                                                except (FileNotFoundError, subprocess.CalledProcessError):
                                                                        pass
        return None

    if sistema == "Darwin":
                for p in sorted(Path("/dev").glob("cu.usb*")):
                                return str(p)
        for p in sorted(Path("/dev").glob("usb*")):
                        return str(p)
        return None

    return None


# ── Impresión real con fallback ───────────────────────────────────────

def imprimir_si_hay_impresora(id_pedido: int) -> dict:
        """
            Intenta imprimir en impresora detectada automáticamente.
                Si no hay impresora, guarda el ticket como .txt en data/tickets/.
                    Retorna {"ok":bool, "texto":str, "ruta":str|None, "error":str|None}.
                        """
    texto = formatear_comprobante(id_pedido)
    resultado: dict = {"ok": False, "texto": texto, "ruta": None, "error": None}

    puerto = _detectar_puerto()
    if puerto:
                try:
                                import escpos.printer as printer
                                if puerto.upper().startswith("COM") or puerto.startswith("/dev/"):
                                                    p = printer.Serial(puerto)
    elif "://" in puerto:
                p = printer.Network(puerto)
else:
                p = printer.Serial(puerto)
                p.text(texto)
                p.cut()
                p.close()
                resultado["ok"] = True
                resultado["ruta"] = f"IMPRESORA:{puerto}"
                return resultado
except ImportError:
                resultado["error"] = "python-escpos no instalado."
except Exception as e:
                resultado["error"] = str(e)

    # Fallback: guardar en disco
        ticket_dir = Path(config.DATA_DIR) / "tickets"
    ticket_dir.mkdir(parents=True, exist_ok=True)
    ruta_txt = ticket_dir / f"ticket_{id_pedido:06d}.txt"
    ruta_txt.write_text(texto, encoding="utf-8")

    resultado["ok"] = True
    resultado["ruta"] = str(ruta_txt)
    resultado["error"] = resultado.get("error") or (
                "No se detectó impresora. Ticket guardado en:\n" + str(ruta_txt)
    )
    return resultado
