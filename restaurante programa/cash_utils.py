"""Utilidades puras para caja, arqueo y comprobantes de contingencia."""
from __future__ import annotations

from datetime import datetime


# ── Utilerías de efectivo ──────────────────────────────────────────────

def cash_change_due(total: float, received: float, payment_method: str) -> float:
    if str(payment_method or "").strip().lower() != "efectivo":
        return 0.0
    return max(float(received or 0) - float(total or 0), 0.0)


def can_charge_table(total: float, payment_method: str, received: float = 0.0) -> bool:
    if float(total or 0) <= 0:
        return False
    if str(payment_method or "").strip().lower() != "efectivo":
        return True
    return float(received or 0) >= float(total or 0)


def cash_expected(opening: float, sales: float, expenses: float) -> float:
    return float(opening or 0) + float(sales or 0) - float(expenses or 0)


def cash_difference(real: float, expected: float) -> float:
    return float(real or 0) - float(expected or 0)


def cash_difference_label(difference: float) -> str:
    amount = float(difference or 0)
    if amount > 0:
        return "sobrante"
    if amount < 0:
        return "faltante"
    return "exacta"


def cash_close_requires_note(difference: float) -> bool:
    return abs(float(difference or 0)) >= 1


# ── Arqueo de caja (X / Y) ────────────────────────────────────────────

def arqueo_x(caja: dict, ventas: list[dict]) -> dict:
    """Corte X: lectura de ventas sin cerrar la caja."""
    total_efectivo = 0.0
    total_tarjeta = 0.0
    total_otros = 0.0
    conteo_por_medio: dict[str, float] = {}

    for v in ventas:
        medio = str(v.get("medio_pago") or "Sin dato")
        monto = float(v.get("total") or 0)
        conteo_por_medio[medio] = conteo_por_medio.get(medio, 0) + monto
        if medio.lower() == "efectivo":
            total_efectivo += monto
        elif medio.lower() in ("tarjeta", "credito", "debito", "mercado pago"):
            total_tarjeta += monto
        else:
            total_otros += monto

    return {
        "total_ventas": sum(float(v.get("subtotal", 0)) for v in ventas),
        "total_cobrado": sum(float(v.get("total", 0)) for v in ventas),
        "desglose": conteo_por_medio,
        "efectivo": total_efectivo,
        "tarjeta": total_tarjeta,
        "otros": total_otros,
        "transacciones": len(ventas),
    }


def arqueo_y(caja: dict, ventas: list[dict], real_contado: float) -> dict:
    """Corte Y: cierre definitivo con validación de diferencia."""
    x = arqueo_x(caja, ventas)
    esperado = cash_expected(
        float(caja.get("monto_apertura", 0)),
        x["total_cobrado"],
        sum(float(v.get("monto", 0)) for v in ventas if v.get("tipo", "") != "ingreso_venta"),
    )
    diferencia = cash_difference(real_contado, esperado)
    return {
        **x,
        "esperado": esperado,
        "real_contado": real_contado,
        "diferencia": diferencia,
        "label": cash_difference_label(diferencia),
        "requiere_nota": cash_close_requires_note(diferencia),
    }


# ── Comprobante de contingencia (offline) ──────────────────────────────

def generar_comprobante_contingencia(mesa_num: int, items: list[dict],
                                     subtotal: float, servicio: float,
                                     total: float, medio_pago: str,
                                     ultimo_numero: int = 0) -> dict:
    """Genera un comprobante de contingencia con numeración correlativa local."""
    numero = ultimo_numero + 1
    ahora = datetime.now()

    lineas = [
        "--- COMPROBANTE DE CONTINGENCIA ---",
        f"Fecha: {ahora.strftime('%Y-%m-%d %H:%M')}",
        f"Numero: C-{ahora.strftime('%y%m%d')}-{numero:04d}",
        f"Mesa: {mesa_num}",
        "-" * 34,
    ]
    for item in items:
        lineas.append(f"{int(item['cantidad'])}x {item['nombre'][:20]:20} ${float(item['importe']):.0f}")
    lineas += [
        "-" * 34,
        f"Subtotal: ${subtotal:.0f}",
        f"Servicio: ${servicio:.0f}",
        f"TOTAL: ${total:.0f}",
        f"Medio: {medio_pago}",
        "",
        "Este comprobante se emitio sin conexion.",
        "Sera sincronizado automaticamente al recuperar la red.",
    ]

    return {
        "numero": numero,
        "texto": "\n".join(lineas),
        "emitido_en_modo_offline": True,
    }


def ultimo_numero_contingencia() -> int:
    """Lee el ultimo numero de contingencia desde configuracion_sistema."""
    try:
        from components.helpers import get_config
        raw = get_config("ultimo_comprobante_contingencia", "0")
        return int(raw)
    except Exception:
        return 0


def guardar_numero_contingencia(numero: int) -> None:
    """Persiste el ultimo numero de contingencia."""
    try:
        from components.helpers import set_config
        set_config("ultimo_comprobante_contingencia", str(numero))
    except Exception:
        pass
