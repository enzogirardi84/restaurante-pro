"""
components/ia_predictiva.py — Motor de predicción de stock.
Usa promedios móviles ponderados con ajuste estacional por día de la
semana para proyectar demanda y generar sugerencias de compra.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import pandas as pd
from database import get_connection_direct


def _cargar_historial_ventas(dias: int = 30) -> pd.DataFrame:
    """
    Consulta ventas reales de los últimos N días.
    Retorna DataFrame con columnas: id_producto, nombre, fecha, cantidad, dia_semana.
    """
    conn = get_connection_direct()
    try:
        df = pd.read_sql_query(f"""
            SELECT pd.id_producto,
                   pm.nombre              AS producto,
                   DATE(pc.fecha_hora)    AS fecha,
                   SUM(pd.cantidad)       AS cantidad
            FROM pedido_detalle pd
            JOIN pedidos_cabecera pc  ON pc.id_pedido = pd.id_pedido
            JOIN productos_menu pm    ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda = 'cobrado'
              AND pc.fecha_hora >= date('now', '-{dias} days', 'localtime')
            GROUP BY pd.id_producto, pm.nombre, DATE(pc.fecha_hora)
            ORDER BY fecha
        """, conn)
    finally:
        conn.close()

    if df.empty:
        return df

    df["fecha"] = pd.to_datetime(df["fecha"])
    # dia_semana: 0=lunes … 6=domingo (Python)
    df["dia_semana"] = df["fecha"].dt.dayofweek
    return df


def _coeficientes_dia(hist: pd.DataFrame) -> dict[int, float]:
    """
    Calcula coeficientes estacionales por día de la semana.
    Retorna dict: {0: 0.85, 1: 0.90, …, 5: 1.40, 6: 1.20}
    (lunes=0, domingo=6)
    """
    if hist.empty:
        return {i: 1.0 for i in range(7)}

    diario = hist.groupby("fecha")["cantidad"].sum()
    avg_daily = diario.mean()
    if avg_daily == 0:
        return {i: 1.0 for i in range(7)}

    promo_dia = hist.groupby("dia_semana")["cantidad"].mean()
    coef = {}
    for d in range(7):
        if d in promo_dia.index and promo_dia[d] > 0:
            coef[d] = round(promo_dia[d] / avg_daily, 2)
        else:
            coef[d] = 1.0
    return coef


def _promedio_ponderado_por_producto(hist: pd.DataFrame) -> dict[int, float]:
    """
    Calcula la demanda base diaria de cada producto usando
    promedio ponderado (más peso a días recientes).
    """
    if hist.empty:
        return {}

    hoy = hist["fecha"].max()
    hist["antiguedad"] = (hoy - hist["fecha"]).dt.days
    # Peso: lineal decreciente. El día más reciente pesa `dias`, el más viejo pesa 1.
    max_dias = hist["antiguedad"].max() + 1
    hist["peso"] = (max_dias - hist["antiguedad"]).clip(lower=1)

    base = {}
    for pid, grupo in hist.groupby("id_producto"):
        peso_total = grupo["peso"].sum()
        if peso_total == 0:
            continue
        media_pond = (grupo["cantidad"] * grupo["peso"]).sum() / peso_total
        base[pid] = round(media_pond, 1)
    return base


def _predecir_3_dias(
    base: dict[int, float],
    coef: dict[int, float],
) -> pd.DataFrame:
    """
    Proyecta la demanda de los próximos 3 días.
    Retorna DataFrame con columnas: id_producto, producto, prediccion_total.
    """
    hoy = datetime.now()
    predicciones: list[dict] = []

    conn = get_connection_direct()
    try:
        cur = conn.execute(
            "SELECT id_producto, nombre FROM productos_menu WHERE activo=1"
        )
        productos = {r["id_producto"]: r["nombre"] for r in cur.fetchall()}
    finally:
        conn.close()

    for pid, nombre in productos.items():
        demanda_base = base.get(pid, 0)
        total = 0.0
        for delta in range(1, 4):
            dia = (hoy + timedelta(days=delta)).weekday()
            factor = coef.get(dia, 1.0)
            total += demanda_base * factor

        predicciones.append({
            "id_producto": pid,
            "producto": nombre,
            "prediccion_total": round(total, 0),
        })

    return pd.DataFrame(predicciones)


# ── API pública ───────────────────────────────────────────────────────

def generar_sugerencia_compra_tres_dias() -> pd.DataFrame:
    """
    Genera la lista de compras sugerida para los próximos 3 días.

    Flujo:
      1. Carga historial de ventas (30 días).
      2. Calcula coeficientes estacionales por día de la semana.
      3. Calcula demanda base ponderada por producto.
      4. Proyecta ventas para los próximos 3 días.
      5. Descompone en materia prima vía recetas_escandallo.
      6. Compara con stock_actual → calcula déficit.
      7. Asocia proveedor sugerido.

    Retorna DataFrame listo para renderizar en Streamlit.
    """
    hist = _cargar_historial_ventas(30)
    coef = _coeficientes_dia(hist)
    base = _promedio_ponderado_por_producto(hist)
    df_pred = _predecir_3_dias(base, coef)

    conn = get_connection_direct()
    try:
        # ── Descomponer en insumos ──
        cur = conn.execute("""
            SELECT re.id_producto, re.id_insumo, re.cantidad_a_descontar,
                   i.nombre AS insumo, i.stock_actual, i.stock_minimo, i.unidad_medida
            FROM recetas_escandallo re
            JOIN insumos i ON i.id_insumo = re.id_insumo
        """)
        recetas = cur.fetchall()

        # ── Proveedores ──
        cur2 = conn.execute(
            "SELECT id_proveedor, razon_social FROM proveedores ORDER BY id_proveedor"
        )
        proveedores = cur2.fetchall()
    finally:
        conn.close()

    # Mapear predicción por producto
    pred_map = dict(zip(df_pred["id_producto"], df_pred["prediccion_total"]))

    # Descomponer: insumo → cantidad total proyectada
    consumo: dict[int, dict] = {}
    for rec in recetas:
        pid = rec["id_producto"]
        iid = rec["id_insumo"]
        cantidad_predicha = pred_map.get(pid, 0)
        consumo_total = cantidad_predicha * rec["cantidad_a_descontar"]

        if iid not in consumo:
            consumo[iid] = {
                "insumo": rec["insumo"],
                "stock": rec["stock_actual"],
                "minimo": rec["stock_minimo"],
                "unidad": rec["unidad_medida"],
                "consumo_estimado": 0.0,
            }
        consumo[iid]["consumo_estimado"] += consumo_total

    # Construir DataFrame de sugerencias
    sugerencias = []
    for iid, datos in consumo.items():
        deficit = datos["stock"] - datos["consumo_estimado"]
        if deficit >= 0:
            continue  # stock suficiente

        # Asignar proveedor (cíclico según id_insumo)
        prov_idx = (iid - 1) % len(proveedores) if proveedores else 0
        prov_nombre = proveedores[prov_idx]["razon_social"] if proveedores else "—"

        sugerencias.append({
            "Insumo": datos["insumo"],
            "Unidad": datos["unidad"],
            "Stock actual": int(datos["stock"]),
            "Consumo estimado 3 días": int(datos["consumo_estimado"]),
            "Déficit": int(abs(deficit)),
            "Stock mínimo": datos["minimo"],
            "Proveedor sugerido": prov_nombre,
        })

    df_result = pd.DataFrame(sugerencias)
    if not df_result.empty:
        df_result = df_result.sort_values("Déficit", ascending=False).reset_index(drop=True)

    return df_result
