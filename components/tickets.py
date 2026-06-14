"""
components/tickets.py - Tickets ESC/POS, vista previa HTML y descarga PDF/HTML.
"""
from __future__ import annotations

import html
import platform
import subprocess
from pathlib import Path

import config
from database import get_connection_direct

ANCHO_TICKET = 32
SEP = "=" * ANCHO_TICKET
LIN = "-" * ANCHO_TICKET


def _money(value: float | int | None) -> str:
    return f"${float(value or 0):,.0f}"


def _get_datos_pedido(id_pedido: int) -> dict | None:
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            """
            SELECT pc.id_pedido, pc.fecha_hora, m.numero_mesa,
                   u.nombre || ' ' || u.apellido AS mozo
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            WHERE pc.id_pedido = ?
            """,
            (id_pedido,),
        )
        cab = cur.fetchone()
        if not cab:
            return None

        cur = conn.execute(
            """
            SELECT pm.nombre, pd.cantidad, pd.precio_unitario_facturado,
                   COALESCE(pd.observaciones, '') AS observaciones
            FROM pedido_detalle pd
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pd.id_pedido = ?
            ORDER BY pm.categoria, pm.nombre
            """,
            (id_pedido,),
        )
        items = cur.fetchall()
    finally:
        conn.close()

    subtotal = sum(
        float(item["cantidad"] or 0) * float(item["precio_unitario_facturado"] or 0)
        for item in items
    )
    servicio = round(subtotal * config.SERVICIO_PORCENTAJE / 100)
    total = subtotal + servicio
    return {
        "cab": dict(cab),
        "items": [dict(item) for item in items],
        "subtotal": subtotal,
        "servicio": servicio,
        "total": total,
    }


def formatear_comprobante(id_pedido: int) -> str:
    """Genera el texto plano del ticket ESC/POS."""
    datos = _get_datos_pedido(id_pedido)
    if not datos:
        return "ERROR: Pedido no encontrado."

    cab = datos["cab"]
    lines = [""]
    lines.append(f"{config.NOMBRE_LOCAL:^{ANCHO_TICKET}}")
    if config.DIRECCION_LOCAL:
        lines.append(f"{config.DIRECCION_LOCAL:^{ANCHO_TICKET}}")
    if config.CUIT_LOCAL:
        lines.append(f"CUIT: {config.CUIT_LOCAL:^{ANCHO_TICKET - 5}}")
    lines.append(SEP)
    lines.append(f"Mesa:    {cab['numero_mesa']}")
    lines.append(f"Mozo:    {cab['mozo']}")
    fecha = str(cab.get("fecha_hora") or "")[:19]
    lines.append(f"Fecha:   {fecha}")
    lines.append(f"Comp.:   P-{cab['id_pedido']:06d}")
    lines.append(SEP)
    lines.append(f"{'Cant':>4}  {'Producto':<16}  {'Precio':>7}")
    lines.append(LIN)

    for item in datos["items"]:
        importe = float(item["cantidad"] or 0) * float(item["precio_unitario_facturado"] or 0)
        nombre = str(item["nombre"])[:16]
        lines.append(f"{item['cantidad']:>4}  {nombre:<16}  ${importe:>6,.0f}")
        if item.get("observaciones"):
            lines.append(f"      {str(item['observaciones'])[:24]}")

    lines.append(LIN)
    lines.append(f"{'SUBTOTAL':>22}  ${datos['subtotal']:>6,.0f}")
    lines.append(f"{'SERVICIO':>22}  ${datos['servicio']:>6,.0f}")
    lines.append(SEP)
    lines.append(f"{'TOTAL':>22}  ${datos['total']:>6,.0f}")
    lines.append(SEP)
    lines.append(f"{'Gracias por su visita':^{ANCHO_TICKET}}")
    lines += ["", "", ""]
    return "\n".join(lines)


def ticket_a_html(id_pedido: int) -> str:
    """Genera HTML con estilo ticket para vista previa y descarga."""
    datos = _get_datos_pedido(id_pedido)
    if not datos:
        return "<html><body><p>Error: pedido no encontrado.</p></body></html>"

    cab = datos["cab"]
    filas = []
    for item in datos["items"]:
        cantidad = float(item["cantidad"] or 0)
        precio = float(item["precio_unitario_facturado"] or 0)
        importe = cantidad * precio
        obs = f"<small>{html.escape(str(item['observaciones']))}</small>" if item.get("observaciones") else ""
        filas.append(
            "<tr>"
            f"<td>{cantidad:g}</td>"
            f"<td>{html.escape(str(item['nombre']))}{obs}</td>"
            f"<td class='num'>{_money(importe)}</td>"
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Ticket P-{cab['id_pedido']:06d}</title>
  <style>
    body {{
      background: #F4EAE1;
      color: #2C221E;
      font-family: "Courier New", monospace;
      margin: 0;
      padding: 20px;
    }}
    .ticket {{
      background: #fffdf9;
      border: 1px solid #B58A63;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.12);
      margin: auto;
      max-width: 340px;
      padding: 18px;
    }}
    h1 {{ font-size: 18px; margin: 0 0 4px; text-align: center; }}
    .muted {{ color: #6b625d; font-size: 12px; text-align: center; }}
    .meta {{ border-bottom: 1px dashed #B58A63; border-top: 1px dashed #B58A63; margin: 12px 0; padding: 8px 0; }}
    table {{ border-collapse: collapse; width: 100%; }}
    td, th {{ border-bottom: 1px dotted #ddd; font-size: 12px; padding: 5px 2px; text-align: left; }}
    .num {{ text-align: right; white-space: nowrap; }}
    small {{ color: #777; display: block; font-size: 10px; }}
    .totales {{ margin-top: 10px; }}
    .row {{ display: flex; justify-content: space-between; padding: 3px 0; }}
    .total {{ border-top: 2px solid #2C221E; color: #8B2635; font-size: 16px; font-weight: 800; margin-top: 4px; padding-top: 6px; }}
    .footer {{ color: #6b625d; font-size: 12px; margin-top: 14px; text-align: center; }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .ticket {{ border: none; box-shadow: none; max-width: none; }}
    }}
  </style>
</head>
<body>
  <div class="ticket">
    <h1>{html.escape(config.NOMBRE_LOCAL)}</h1>
    <div class="muted">{html.escape(config.DIRECCION_LOCAL or "")}</div>
    <div class="muted">CUIT: {html.escape(config.CUIT_LOCAL or "-")}</div>
    <div class="meta">
      Mesa: {cab['numero_mesa']}<br>
      Mozo: {html.escape(str(cab['mozo']))}<br>
      Fecha: {html.escape(str(cab.get('fecha_hora') or '')[:19])}<br>
      Comp.: P-{cab['id_pedido']:06d}
    </div>
    <table>
      <thead><tr><th>Cant</th><th>Producto</th><th class="num">Importe</th></tr></thead>
      <tbody>{''.join(filas)}</tbody>
    </table>
    <div class="totales">
      <div class="row"><span>Subtotal</span><span>{_money(datos['subtotal'])}</span></div>
      <div class="row"><span>Servicio</span><span>{_money(datos['servicio'])}</span></div>
      <div class="row total"><span>Total</span><span>{_money(datos['total'])}</span></div>
    </div>
    <div class="footer">Gracias por su visita</div>
  </div>
</body>
</html>"""


def ticket_a_pdf_bytes(id_pedido: int) -> bytes | None:
    """Genera un PDF del ticket usando reportlab; retorna None si no esta disponible."""
    datos = _get_datos_pedido(id_pedido)
    if not datos:
        return None

    try:
        from io import BytesIO

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A7
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        return None

    cab = datos["cab"]
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A7,
        rightMargin=5 * mm,
        leftMargin=5 * mm,
        topMargin=5 * mm,
        bottomMargin=5 * mm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TicketTitle",
        parent=styles["Heading3"],
        alignment=TA_CENTER,
        fontSize=10,
        leading=12,
        spaceAfter=4,
    )
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=6.5, leading=8)
    total_style = ParagraphStyle(
        "Total",
        parent=styles["Normal"],
        alignment=TA_RIGHT,
        fontSize=8,
        leading=10,
    )

    story = [
        Paragraph(html.escape(config.NOMBRE_LOCAL), title),
        Paragraph(html.escape(config.DIRECCION_LOCAL or ""), small),
        Paragraph(f"CUIT: {html.escape(config.CUIT_LOCAL or '-')}", small),
        Spacer(1, 3),
        Paragraph(f"Mesa: {cab['numero_mesa']}", small),
        Paragraph(f"Mozo: {html.escape(str(cab['mozo']))}", small),
        Paragraph(f"Fecha: {html.escape(str(cab.get('fecha_hora') or '')[:19])}", small),
        Paragraph(f"Comp.: P-{cab['id_pedido']:06d}", small),
        Spacer(1, 4),
    ]

    rows = [["Cant", "Producto", "Importe"]]
    for item in datos["items"]:
        cantidad = float(item["cantidad"] or 0)
        precio = float(item["precio_unitario_facturado"] or 0)
        rows.append([f"{cantidad:g}", str(item["nombre"])[:18], _money(cantidad * precio)])

    table = Table(rows, colWidths=[12 * mm, 35 * mm, 20 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 6),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 6),
                ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.lightgrey),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    story.extend(
        [
            Spacer(1, 5),
            Paragraph(f"Subtotal: {_money(datos['subtotal'])}", total_style),
            Paragraph(f"Servicio: {_money(datos['servicio'])}", total_style),
            Paragraph(f"<b>Total: {_money(datos['total'])}</b>", total_style),
            Spacer(1, 5),
            Paragraph("Gracias por su visita", title),
        ]
    )

    doc.build(story)
    return buf.getvalue()


def mostrar_ticket_streamlit(id_pedido: int) -> None:
    """Renderiza vista previa del ticket y botones de descarga en Streamlit."""
    import streamlit as st

    datos = _get_datos_pedido(id_pedido)
    if not datos:
        st.error("No se encontro el pedido para generar el ticket.")
        return

    cab = datos["cab"]
    items_html = ""
    for item in datos["items"]:
        cantidad = float(item["cantidad"] or 0)
        precio = float(item["precio_unitario_facturado"] or 0)
        importe = cantidad * precio
        obs = (
            f"<div style='color:#777;font-size:0.75rem'>{html.escape(str(item['observaciones']))}</div>"
            if item.get("observaciones")
            else ""
        )
        items_html += (
            "<div class='ticket-item'>"
            f"<span><b>{cantidad:g}x</b> {html.escape(str(item['nombre']))}{obs}</span>"
            f"<span>{_money(importe)}</span>"
            "</div>"
        )

    st.markdown(
        f"""
        <style>
          .ticket-box {{
            background: #fffdf9;
            border: 1px solid #B58A63;
            border-radius: 8px;
            color: #2C221E;
            font-family: "Courier New", monospace;
            margin: 0 auto;
            max-width: 360px;
            padding: 18px;
          }}
          .ticket-header {{ text-align: center; margin-bottom: 8px; }}
          .ticket-header h3 {{ font-size: 15px; margin: 0; color: #2C221E; }}
          .ticket-header p {{ font-size: 11px; color: #777; margin: 2px 0; }}
          .ticket-sep {{ border: none; border-top: 1px dashed #ccc; margin: 8px 0; }}
          .ticket-sep-bold {{ border: none; border-top: 2px solid #2C221E; margin: 8px 0; }}
          .ticket-meta {{ font-size: 12px; margin: 6px 0; }}
          .ticket-item {{ display: flex; justify-content: space-between; gap: 8px; padding: 4px 0; font-size: 12px; }}
          .ticket-totals {{ font-size: 12px; margin-top: 6px; }}
          .ticket-totals .row {{ display: flex; justify-content: space-between; padding: 2px 0; }}
          .ticket-totals .total {{ color: #8B2635; font-size: 15px; font-weight: 800; }}
          .ticket-footer {{ color: #777; font-size: 12px; margin-top: 12px; text-align: center; }}
        </style>
        <div class="ticket-box">
          <div class="ticket-header">
            <h3>{html.escape(config.NOMBRE_LOCAL)}</h3>
            <p>{html.escape(config.DIRECCION_LOCAL or "")}</p>
            <p>CUIT: {html.escape(config.CUIT_LOCAL or "-")}</p>
          </div>
          <hr class="ticket-sep-bold">
          <div class="ticket-meta">
            Mesa: {cab['numero_mesa']}<br>
            Mozo: {html.escape(str(cab['mozo']))}<br>
            Fecha: {html.escape(str(cab.get('fecha_hora') or '')[:19])}<br>
            Comp.: P-{cab['id_pedido']:06d}
          </div>
          <hr class="ticket-sep">
          {items_html}
          <hr class="ticket-sep-bold">
          <div class="ticket-totals">
            <div class="row"><span>Subtotal</span><span>{_money(datos['subtotal'])}</span></div>
            <div class="row"><span>Servicio</span><span>{_money(datos['servicio'])}</span></div>
            <div class="row total"><span>Total</span><span>{_money(datos['total'])}</span></div>
          </div>
          <hr class="ticket-sep">
          <p class="ticket-footer">Gracias por su visita</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    col_pdf, col_html = st.columns(2)
    with col_pdf:
        pdf_bytes = ticket_a_pdf_bytes(id_pedido)
        if pdf_bytes:
            st.download_button(
                "Descargar PDF",
                data=pdf_bytes,
                file_name=f"ticket_P{id_pedido:06d}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.info("Instala reportlab para habilitar descarga PDF.")

    with col_html:
        html_content = ticket_a_html(id_pedido)
        st.download_button(
            "Descargar HTML",
            data=html_content.encode("utf-8"),
            file_name=f"ticket_P{id_pedido:06d}.html",
            mime="text/html",
            use_container_width=True,
        )


def _detectar_puerto() -> str | None:
    """Escanea puertos comunes segun el sistema operativo."""
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
        for base in (Path("/dev/usb"), Path("/dev")):
            if base.exists():
                for p in sorted(base.glob("lp*")):
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
        for pattern in ("cu.usb*", "usb*"):
            for p in sorted(Path("/dev").glob(pattern)):
                return str(p)
        return None

    return None


def imprimir_si_hay_impresora(id_pedido: int) -> dict:
    """
    Intenta imprimir en impresora detectada automaticamente.
    Si no hay impresora, guarda el ticket como .txt en data/tickets/.
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
        except Exception as exc:
            resultado["error"] = str(exc)

    ticket_dir = Path(config.DATA_DIR) / "tickets"
    ticket_dir.mkdir(parents=True, exist_ok=True)
    ruta_txt = ticket_dir / f"ticket_{id_pedido:06d}.txt"
    ruta_txt.write_text(texto, encoding="utf-8")

    resultado["ok"] = True
    resultado["ruta"] = str(ruta_txt)
    resultado["error"] = resultado.get("error") or (
        "No se detecto impresora. Ticket guardado en:\n" + str(ruta_txt)
    )
    return resultado
