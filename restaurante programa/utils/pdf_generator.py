"""
Motor de generacion de reportes PDF corporativos para "El Patron - Restaurante Pro".
Usa reportlab con diseño de marca, paginacion automatica, zebra striping y bloques de auditoria.
"""

from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ── Paleta corporativa ──────────────────────────────────────────────────
COLOR_PRIMARY = colors.HexColor("#4A2C1A")      # marron oscuro
COLOR_SECONDARY = colors.HexColor("#8B5E3C")     # marron medio
COLOR_ACCENT = colors.HexColor("#C49A6C")        # dorado suave
COLOR_BG_HEADER = colors.HexColor("#F5EDE3")     # crema
COLOR_BG_ODD = colors.HexColor("#FAF6F0")        # fila impar
COLOR_BG_EVEN = colors.HexColor("#F0E8D8")       # fila par
COLOR_TEXT = colors.HexColor("#2C1810")           # texto principal
COLOR_MUTED = colors.HexColor("#888888")          # gris
COLOR_BORDER = colors.HexColor("#D4C5A9")         # borde de tabla
COLOR_WHITE = colors.white
COLOR_KPI_BG = colors.HexColor("#4A2C1A")
COLOR_KPI_TEXT = colors.white
COLOR_AUDIT_BG = colors.HexColor("#F9F3EB")


# ── Estilos de texto ────────────────────────────────────────────────────
_styles = getSampleStyleSheet()

STYLE_TITLE = ParagraphStyle("Titulo", parent=_styles["Title"],
    fontName="Helvetica-Bold", fontSize=18, textColor=COLOR_PRIMARY,
    spaceAfter=4, alignment=TA_CENTER)

STYLE_SUBTITLE = ParagraphStyle("Subtitulo", parent=_styles["Normal"],
    fontName="Helvetica", fontSize=9, textColor=COLOR_MUTED,
    spaceAfter=12, alignment=TA_CENTER)

STYLE_H1 = ParagraphStyle("H1", parent=_styles["Heading1"],
    fontName="Helvetica-Bold", fontSize=14, textColor=COLOR_PRIMARY,
    spaceBefore=12, spaceAfter=6, borderWidth=0)

STYLE_H2 = ParagraphStyle("H2", parent=_styles["Heading2"],
    fontName="Helvetica-Bold", fontSize=11, textColor=COLOR_SECONDARY,
    spaceBefore=10, spaceAfter=4)

STYLE_BODY = ParagraphStyle("Body", parent=_styles["Normal"],
    fontName="Helvetica", fontSize=9, textColor=COLOR_TEXT,
    spaceAfter=4, leading=13)

STYLE_BODY_RIGHT = ParagraphStyle("BodyRight", parent=STYLE_BODY,
    alignment=TA_RIGHT)

STYLE_CELL = ParagraphStyle("Cell", fontName="Helvetica", fontSize=8,
    textColor=COLOR_TEXT, leading=10)

STYLE_CELL_RIGHT = ParagraphStyle("CellRight", parent=STYLE_CELL,
    alignment=TA_RIGHT)

STYLE_AUDIT = ParagraphStyle("Audit", fontName="Helvetica", fontSize=8,
    textColor=COLOR_MUTED, spaceBefore=6)

STYLE_KPI_LABEL = ParagraphStyle("KPILabel", fontName="Helvetica",
    fontSize=7, textColor=COLOR_KPI_TEXT, alignment=TA_CENTER)

STYLE_KPI_VALUE = ParagraphStyle("KPIValue", fontName="Helvetica-Bold",
    fontSize=13, textColor=COLOR_KPI_TEXT, alignment=TA_CENTER, spaceBefore=2)


# ── Utilities ────────────────────────────────────────────────────────────
def money(value: float | int | None) -> str:
    value = value or 0
    return f"${value:,.0f}".replace(",", ".")


def date_fmt(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%d/%m/%Y %H:%M")


def cell(text: str, right: bool = False) -> Paragraph:
    style = STYLE_CELL_RIGHT if right else STYLE_CELL
    return Paragraph(str(text), style)


def cell_money(val: float | int | None) -> Paragraph:
    return cell(money(val), right=True)


# ── Canvas con numeración de páginas ────────────────────────────────────
class NumberedCanvas(canvas.Canvas):
    """Canvas de dos pasadas para 'Pagina X de Y'."""
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header_footer(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_header_footer(self, page_count: int):
        self.saveState()
        # ── Encabezado ──
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(COLOR_PRIMARY)
        self.drawString(54, 758, "El Patron — Restaurante Pro")
        self.setFont("Helvetica", 7)
        self.setFillColor(COLOR_MUTED)
        self.drawRightString(558, 758, date_fmt())
        self.setStrokeColor(COLOR_BORDER)
        self.setLineWidth(0.5)
        self.line(54, 752, 558, 752)

        # ── Pie de pagina ──
        self.setFont("Helvetica", 8)
        self.setFillColor(COLOR_MUTED)
        page_text = f"Pagina {self._pageNumber} de {page_count}"
        self.drawRightString(558, 38, page_text)
        self.drawString(54, 38, "Documento generado por sistema — El Patron")
        self.restoreState()


# ── Constructores de documento ──────────────────────────────────────────
def _build_doc(buf: io.BytesIO, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=42,
        bottomMargin=42,
        leftMargin=54,
        rightMargin=54,
        title=title,
        author="El Patron - Restaurante Pro",
    )


def _build_story(
    title: str,
    subtitle: str | None = None,
    kpis: list[tuple[str, str]] | None = None,
) -> list:
    """Construye la lista inicial de flowables (titulo + opcional KPI row)."""
    story: list = []
    story.append(Paragraph(title, STYLE_TITLE))
    story.append(Paragraph(subtitle or date_fmt(), STYLE_SUBTITLE))
    if kpis:
        story.append(Spacer(1, 4))
        story.append(_kpi_table(kpis))
    story.append(Spacer(1, 6))
    return story


# ── Tabla de KPIs ───────────────────────────────────────────────────────
def _kpi_table(kpis: list[tuple[str, str]]) -> Table:
    """kpis = [(label, value), ...]"""
    cols = 4
    data = []
    row: list[Paragraph] = []
    for i, (label, value) in enumerate(kpis):
        row.append(Paragraph(label, STYLE_KPI_LABEL))
        if (i + 1) % cols == 0 or i == len(kpis) - 1:
            while len(row) < cols * 2:
                row.append(Paragraph("", STYLE_KPI_LABEL))
            data.append(row)
            row = []
    for i, (label, value) in enumerate(kpis):
        if i % cols == 0:
            row = []
        row.append(Paragraph(value, STYLE_KPI_VALUE))
        if (i + 1) % cols == 0 or i == len(kpis) - 1:
            while len(row) < cols:
                row.append(Paragraph("", STYLE_KPI_VALUE))
            data.append(row)

    tbl = Table(data, colWidths=[558 / cols] * cols)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_KPI_BG),
        ("BACKGROUND", (0, 1), (-1, -1), COLOR_KPI_BG),
        ("TEXTCOLOR", (0, 0), (-1, -1), COLOR_KPI_TEXT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_ACCENT),
    ]))
    return tbl


# ── Tabla de datos con zebra ────────────────────────────────────────────
def data_table(
    headers: list[str],
    rows_data: list[list[str]],
    col_widths: list[float] | None = None,
    right_align_cols: set[int] | None = None,
) -> Table:
    """Tabla con encabezados, zebra striping y formato."""
    right_align_cols = right_align_cols or set()
    # Encabezados
    header_cells = [Paragraph(h, ParagraphStyle("Hcell",
        fontName="Helvetica-Bold", fontSize=8, textColor=COLOR_WHITE,
        alignment=TA_CENTER)) for h in headers]
    table_data: list[list[Paragraph]] = [header_cells]

    for r_idx, row in enumerate(rows_data):
        cells = []
        for c_idx, val in enumerate(row):
            align_right = c_idx in right_align_cols
            style = STYLE_CELL_RIGHT if align_right else STYLE_CELL
            p = Paragraph(str(val) if val else "", style)
            cells.append(p)
        table_data.append(cells)

    col_count = len(headers)
    if col_widths is None:
        col_widths = [495 / col_count] * col_count

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)

    cmds: list = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]

    for r in range(1, len(table_data)):
        bg = COLOR_BG_ODD if r % 2 == 1 else COLOR_BG_EVEN
        cmds.append(("BACKGROUND", (0, r), (-1, r), bg))

    tbl.setStyle(TableStyle(cmds))
    return tbl


# ── Bloque de auditoria ─────────────────────────────────────────────────
def auditoria_block(
    usuario: str,
    rol: str | None = None,
    extra_lines: list[str] | None = None,
) -> Table:
    """Lineas de firma para reportes críticos."""
    lines = [
        f"Usuario emisor: {usuario}",
        f"Fecha de emision: {date_fmt()}",
    ]
    if rol:
        lines.append(f"Rol: {rol}")
    if extra_lines:
        lines.extend(extra_lines)
    lines.append("")
    lines.append("Firma del Administrador: ______________________________")
    lines.append("Firma del Cajero:        ______________________________")

    data = [[Paragraph(line, STYLE_AUDIT)] for line in lines]
    tbl = Table(data, colWidths=[495])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, len(lines) - 3), COLOR_AUDIT_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("BOX", (0, 0), (0, len(lines) - 1), 0.5, COLOR_BORDER),
    ]))
    return tbl


# ── API principal ───────────────────────────────────────────────────────
def generate_pdf(
    title: str,
    subtitle: str | None = None,
    kpis: list[tuple[str, str]] | None = None,
    sections: list[tuple[str, Table | list]] | None = None,
    usuario: str = "sistema",
    auditoria: bool = False,
) -> bytes:
    """
    Genera un PDF completo y devuelve los bytes.

    Parametros:
        title: titulo del reporte.
        subtitle: subtitulo opcional.
        kpis: lista de (label, valor) para el bloque resumen.
        sections: contenido del reporte. Cada tupla = (heading, flowable|lista).
        usuario: quien genera el reporte.
        auditoria: si True, agrega bloque de firmas al final.
    """
    buf = io.BytesIO()
    doc = _build_doc(buf, title)
    story = _build_story(title, subtitle, kpis)

    if sections:
        for heading, content in sections:
            story.append(Paragraph(heading, STYLE_H2))
            if isinstance(content, list):
                story.extend(content)
            else:
                story.append(content)
            story.append(Spacer(1, 6))

    if auditoria:
        story.append(Spacer(1, 10))
        story.append(auditoria_block(usuario))

    doc.build(story, canvasmaker=lambda *a, **kw: NumberedCanvas(*a, **kw))
    return buf.getvalue()
