"""
components/tickets.py — Impresión ESC/POS con auto-detección de
impresora, fallback a archivo y exportación a HTML.
"""
from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from pathlib import Path
from database import get_connection_direct
import config

ANCHO_TICKET = 32
SEP = "=" * ANCHO_TICKET
LIN = "-" * ANCHO_TICKET


# ── Formateo ──────────────────────────────────────────────────────────

def formatear_comprobante(id_pedido: int) -> str:
    """Genera el texto plano del ticket ESC/POS."""
    conn = get_connection_direct()
    try:
        cur = conn.execute("""
            SELECT pc.id_pedido, pc.fecha_hora,
                   m.numero_mesa,
                   u.nombre || ' ' || u.apellido AS mozo
            FROM pedidos_cabecera pc
            JOIN mesas m  ON m.id_mesa    = pc.id_mesa
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
        lines.append(f"Mesa:    {pedido['numero_mesa']}")
        lines.append(f"Mozo:    {pedido['mozo']}")
        fecha = (pedido["fecha_hora"] or "")[:19]
        lines.append(f"Fecha:   {fecha}")
        lines.append(f"Comp.:   P-{pedido['id_pedido']:06d}")
        lines.append(SEP)
        lines.append(f"{'Cant':>4}  {'Producto':<16}  {'Precio':>7}")
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
            lines.append(f"{item['cantidad']:>4}  {item['nombre']:<16}  ${importe:>6,.0f}")

        servicio = round(subtotal * config.SERVICIO_PORCENTAJE / 100)
        total = subtotal + servicio
        lines.append(LIN)
        lines.append(f"{'SUBTOTAL':>22}  ${subtotal:>6,.0f}")
        lines.append(f"{'SERVICIO':>22}  ${servicio:>6,.0f}")
        lines.append(SEP)
        lines.append(f"{'TOTAL':>22}  ${total:>6,.0f}")
        lines.append(SEP)
        lines.append(f"{'¡Gracias!':^{ANCHO_TICKET}}")
        lines += ["", "", ""]
        return "\n".join(lines)
    finally:
        conn.close()


# ── Auto-detección de impresoras ──────────────────────────────────────

def _detectar_puerto() -> str | None:
    """
    Escanea puertos comunes según el SO.
    Windows: prueba COM1..COM9.
    Linux:   busca /dev/usb/lp* y /dev/lp*.
    macOS:   busca /dev/usb* y /dev/cu.usb*.
    """
    sistema = platform.system()

    if sistema == "Windows":
        for com in range(1, 10):
            puerto = f"COM{com}"
            try:
                #  Verificar si el puerto existe
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
        #  Intentar con lpinfo (CUPS)
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

    # 1. Intentar impresión real
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

    # 2. Fallback: guardar a archivo
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


# ── Exportar a HTML (vista previa con estilo vintage) ─────────────────

def ticket_a_html(id_pedido: int) -> str:
    """Genera un HTML con estilo vintage para vista previa del ticket."""
    texto = formatear_comprobante(id_pedido)
    html_lines = texto.replace("\n", "<br>").replace(" ", "&nbsp;")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{
    background: #F4EAE1; font-family: 'Courier New', monospace;
    font-size: 14px; color: #2C221E; max-width: 300px; margin: auto;
    padding: 20px;
  }}
  .ticket {{
    background: white; padding: 20px; border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  }}
</style></head><body>
<div class="ticket">{html_lines}</div>
</body></html>"""
