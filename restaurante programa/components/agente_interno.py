"""Agente interno de inteligencia para el sistema gastronomico."""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from components.helpers import rows, caja_abierta


def estado_general() -> dict:
    """Retorna un dict con indicadores clave del sistema."""
    r = {}
    try:
        c = caja_abierta()
        r["caja_abierta"] = c is not None
        r["caja_id"] = c["id_caja"] if c else None
        r["caja_monto_ventas"] = c["monto_ventas"] if c else 0
        r["caja_apertura"] = c["fecha_apertura"] if c else ""
    except Exception:
        r["caja_abierta"] = False
    try:
        r["mesas_ocupadas"] = len(rows("SELECT 1 FROM mesas WHERE estado='ocupada'") or [])
        r["mesas_totales"] = rows("SELECT COUNT(*) c FROM mesas")[0]["c"]
    except Exception:
        r["mesas_ocupadas"] = r["mesas_totales"] = 0
    try:
        r["pedidos_pendientes"] = rows("SELECT COUNT(*) c FROM pedidos_cabecera WHERE estado_comanda IN ('pendiente','en_cocina')")[0]["c"]
        r["pedidos_hoy"] = rows("SELECT COUNT(*) c FROM pedidos_cabecera WHERE date(fecha_hora)=date('now','localtime')")[0]["c"]
    except Exception:
        r["pedidos_pendientes"] = r["pedidos_hoy"] = 0
    try:
        r["stock_bajo"] = len(rows("SELECT 1 FROM insumos WHERE stock_actual <= stock_minimo") or [])
    except Exception:
        r["stock_bajo"] = 0
    try:
        r["usuario_count"] = rows("SELECT COUNT(*) c FROM usuarios")[0]["c"]
    except Exception:
        r["usuario_count"] = 0
    try:
        r["productos_count"] = rows("SELECT COUNT(*) c FROM productos_menu WHERE activo=1")[0]["c"]
    except Exception:
        r["productos_count"] = 0
    try:
        r["ventas_hoy"] = rows("""
            SELECT COALESCE(SUM(total),0) total
            FROM pagos_mesa
            WHERE date(fecha_hora)=date('now','localtime')
        """)[0]["total"]
    except Exception:
        r["ventas_hoy"] = 0
    try:
        r["reservas_hoy"] = rows("SELECT COUNT(*) c FROM reservas WHERE date(fecha_reserva)=date('now','localtime') AND estado='confirmada'")[0]["c"]
    except Exception:
        r["reservas_hoy"] = 0
    try:
        r["facturas_hoy"] = rows("SELECT COUNT(*) c FROM facturas_electronicas WHERE date(fecha_emision)=date('now','localtime')")[0]["c"]
    except Exception:
        r["facturas_hoy"] = 0
    return r


def alertas_activas() -> list[dict]:
    """Retorna lista de alertas detectadas."""
    alertas = []
    try:
        bajos = rows("SELECT nombre, stock_actual, stock_minimo FROM insumos WHERE stock_actual <= stock_minimo ORDER BY stock_actual ASC LIMIT 10") or []
        for i in bajos:
            alertas.append({"tipo": "stock_bajo", "mensaje": f"Stock bajo: {i['nombre']} ({i['stock_actual']}/{i['stock_minimo']})", "severidad": "alta"})
    except Exception:
        pass
    try:
        demorados = rows("""
            SELECT COUNT(*) c FROM pedidos_cabecera
            WHERE estado_comanda='en_cocina' AND (julianday('now','localtime')-julianday(fecha_hora))*24*60 > 15
        """) or [{"c": 0}]
        if demorados[0]["c"] > 0:
            alertas.append({"tipo": "pedidos_demorados", "mensaje": f"{demorados[0]['c']} pedidos en cocina con mas de 15 min", "severidad": "media"})
    except Exception:
        pass
    try:
        no_receta = rows("""
            SELECT COUNT(*) c FROM productos_menu pm
            WHERE pm.activo=1 AND NOT EXISTS (SELECT 1 FROM recetas_escandallo re WHERE re.id_producto=pm.id_producto)
        """) or [{"c": 0}]
        if no_receta[0]["c"] > 0:
            alertas.append({"tipo": "sin_receta", "mensaje": f"{no_receta[0]['c']} productos activos sin receta de escandallo", "severidad": "media"})
    except Exception:
        pass
    try:
        c = caja_abierta()
        if c:
            apertura = c.get("fecha_apertura", "")
            if apertura:
                try:
                    dt_apertura = datetime.strptime(apertura[:19], "%Y-%m-%d %H:%M:%S")
                    horas = (datetime.now() - dt_apertura).total_seconds() / 3600
                    if horas > 12:
                        alertas.append({"tipo": "caja_larga", "mensaje": f"Caja abierta hace {horas:.0f} horas", "severidad": "baja"})
                except Exception:
                    pass
    except Exception:
        pass
    try:
        pend = rows("SELECT COUNT(*) c FROM cola_sincronizacion WHERE sincronizado=0") or [{"c": 0}]
        if pend[0]["c"] > 10:
            alertas.append({"tipo": "sync_pendiente", "mensaje": f"{pend[0]['c']} sincronizaciones pendientes", "severidad": "baja"})
    except Exception:
        pass
    return alertas


def pedidos_activos() -> list[dict]:
    """Retorna los pedidos activos (pendiente, en_cocina, listo) para diagnostico."""
    try:
        return rows("""
            SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda,
                   m.numero_mesa, u.nombre || ' ' || u.apellido AS mozo
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo')
            ORDER BY pc.fecha_hora ASC
        """) or []
    except Exception:
        return []


def sugerencias() -> list[str]:
    """Sugerencias basadas en el estado del sistema."""
    sugs = []
    e = estado_general()
    if not e.get("caja_abierta"):
        sugs.append("No hay caja abierta. Recorda abrir caja al iniciar el dia.")
    if e.get("stock_bajo", 0) > 0:
        sugs.append(f"Hay {e['stock_bajo']} insumos con stock bajo. Revisa la seccion Inventario.")
    if e.get("reservas_hoy", 0) > 0:
        sugs.append(f"Tenés {e['reservas_hoy']} reserva(s) para hoy. Revisa la seccion Reservas.")
    if e.get("ventas_hoy", 0) == 0 and e.get("caja_abierta"):
        sugs.append("Todavia no se registro ninguna venta hoy.")
    return sugs


def consultar_llm(prompt: str, api_key: str = "", contexto: str = "") -> str:
    """Consulta un LLM via OpenRouter con contexto del sistema."""
    if not api_key:
        return "API key de OpenRouter no configurada."
    data = json.dumps({
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": f" Sos un asistente experto en gestion gastronomica. Contexto del sistema:\n{contexto[:2000]}"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 600,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://restaurante-pro.app",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"Error al consultar LLM: {exc}"
