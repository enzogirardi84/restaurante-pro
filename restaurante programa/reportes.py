"""
reportes.py — Dashboard gerencial con metricas y graficos BI + exportacion PDF corporativa.
Genera PDFs profesionales con marca, paginacion, zebra striping y bloques de auditoria.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from components.helpers import money
from database import get_connection, init_db
from utils.pdf_generator import (
    auditoria_block,
    cell,
    cell_money,
    data_table,
    date_fmt,
    generate_pdf,
)

st.set_page_config(page_title="Dashboard Gerencial", layout="wide",
                   initial_sidebar_state="collapsed")
init_db()

# ── CONFIG VISUAL ─────────────────────────────────────────────────────
COLOR_POSITIVO = "#4caf50"
COLOR_NEGATIVO = "#e53935"
COLOR_PRIMARY  = "#1e88e5"


# ── CONSULTAS SQL ─────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def query_metricas() -> dict:
    """Metricas principales del tablero."""
    conn = get_connection()
    try:
        data = conn.execute("""
            WITH tickets AS (
                SELECT pc.id_pedido,
                       pc.id_mesa,
                       SUM(pd.cantidad * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)) AS total
                  FROM pedidos_cabecera pc
                  JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
                  JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                 WHERE pc.estado_comanda = 'cobrado'
                 GROUP BY pc.id_pedido, pc.id_mesa
            )
            SELECT COUNT(*) AS total_pedidos,
                   COALESCE(SUM(total), 0) AS ingreso_total,
                   COUNT(DISTINCT id_mesa) AS mesas_atendidas,
                   COALESCE(ROUND(AVG(total), 0), 0) AS ticket_promedio
              FROM tickets
        """).fetchone()

        bajos = conn.execute("""
            SELECT COUNT(*) AS cnt
            FROM stock_deposito sd
            JOIN insumos i ON i.id_insumo = sd.id_insumo
            WHERE sd.cantidad_disponible <= i.stock_minimo
        """).fetchone()["cnt"]

        result = {k: v or 0 for k, v in dict(data).items()}
        result["alertas_stock"] = bajos
        return result
    finally:
        conn.close()


@st.cache_data(ttl=30)
def query_ventas_diarias() -> pd.DataFrame:
    """Recaudacion diaria."""
    conn = get_connection()
    try:
        return pd.read_sql_query("""
            SELECT DATE(pc.fecha_hora) AS dia,
                   ROUND(SUM(pd.cantidad * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)), 0) AS total
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda = 'cobrado'
            GROUP BY DATE(pc.fecha_hora)
            ORDER BY dia
        """, conn)
    finally:
        conn.close()


@st.cache_data(ttl=30)
def query_cajas() -> pd.DataFrame:
    """Auditoria de cajas con diferencia calculada."""
    conn = get_connection()
    try:
        df = pd.read_sql_query("""
            SELECT cd.id_caja,
                   u.nombre || ' ' || u.apellido AS cajero,
                   cd.fecha_apertura,
                   cd.fecha_cierre,
                   cd.monto_apertura,
                   cd.monto_ventas,
                   cd.monto_cierre_real
            FROM cajas_diarias cd
            JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
            ORDER BY cd.fecha_apertura DESC
        """, conn)
        if not df.empty:
            df["diferencia"] = df["monto_cierre_real"] - df["monto_ventas"]
        return df
    finally:
        conn.close()


@st.cache_data(ttl=30)
def query_alertas_stock() -> pd.DataFrame:
    """Insumos por debajo del minimo, por deposito."""
    conn = get_connection()
    try:
        return pd.read_sql_query("""
            SELECT d.nombre_deposito      AS deposito,
                   i.nombre               AS insumo,
                   sd.cantidad_disponible AS stock_actual,
                   i.stock_minimo,
                   i.unidad_medida
            FROM stock_deposito sd
            JOIN insumos   i ON i.id_insumo   = sd.id_insumo
            JOIN depositos d ON d.id_deposito  = sd.id_deposito
            WHERE sd.cantidad_disponible <= i.stock_minimo
            ORDER BY d.nombre_deposito, i.nombre
        """, conn)
    finally:
        conn.close()


@st.cache_data(ttl=30)
def query_top5() -> pd.DataFrame:
    """Ranking de productos mas vendidos."""
    conn = get_connection()
    try:
        return pd.read_sql_query("""
            SELECT pm.nombre          AS producto,
                   SUM(pd.cantidad)   AS total_vendido,
                   ROUND(SUM(pd.cantidad * COALESCE(pd.precio_unitario_facturado, pm.precio_venta)), 0) AS ingreso
            FROM pedido_detalle pd
            JOIN pedidos_cabecera pc  ON pc.id_pedido   = pd.id_pedido
            JOIN productos_menu pm    ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda = 'cobrado'
            GROUP BY pm.id_producto, pm.nombre
            ORDER BY total_vendido DESC
            LIMIT 5
        """, conn)
    finally:
        conn.close()


# ── GENERACION PDF ──────────────────────────────────────────────────────

def _pdf_reporte_general(m: dict, df_ventas: pd.DataFrame, df_cajas: pd.DataFrame,
                         df_top: pd.DataFrame, df_alertas: pd.DataFrame) -> bytes:
    """Genera PDF completo del dashboard gerencial."""
    sections = []

    # 1. Ventas diarias
    if not df_ventas.empty:
        rows_tbl = [
            [str(r["dia"]), money(r["total"])]
            for _, r in df_ventas.iterrows()
        ]
        sections.append((
            "Ventas diarias",
            data_table(["Fecha", "Total"], rows_tbl, right_align_cols={1}),
        ))

    # 2. Top 5 productos
    if not df_top.empty:
        rows_tbl = [
            [r["producto"], str(int(r["total_vendido"])), money(r["ingreso"])]
            for _, r in df_top.iterrows()
        ]
        sections.append((
            "Top 5 productos mas vendidos",
            data_table(["Producto", "Cantidad", "Ingreso"], rows_tbl, right_align_cols={1, 2}),
        ))

    # 3. Auditoria de cajas
    if not df_cajas.empty:
        rows_tbl = [
            [
                str(r["id_caja"]),
                r["cajero"],
                str(r["fecha_apertura"])[:10] if r["fecha_apertura"] else "-",
                money(r["monto_apertura"]),
                money(r["monto_ventas"]),
                money(r["monto_cierre_real"]) if pd.notna(r["monto_cierre_real"]) else "-",
                money(r["diferencia"]) if pd.notna(r.get("diferencia")) else "-",
            ]
            for _, r in df_cajas.head(20).iterrows()
        ]
        sections.append((
            "Auditoria de cajas (ultimos 20 movimientos)",
            data_table(
                ["Nro", "Cajero", "Apertura", "Apertura $", "Ventas $", "Real $", "Dif. $"],
                rows_tbl,
                right_align_cols={3, 4, 5, 6},
            ),
        ))

    # 4. Alertas de stock
    if not df_alertas.empty:
        rows_tbl = [
            [r["deposito"], r["insumo"],
             f"{r['stock_actual']:.0f} {r['unidad_medida']}",
             f"{r['stock_minimo']:.0f} {r['unidad_medida']}"]
            for _, r in df_alertas.iterrows()
        ]
        sections.append((
            "Alertas de inventario",
            data_table(["Deposito", "Insumo", "Stock actual", "Minimo requerido"],
                       rows_tbl, right_align_cols={2, 3}),
        ))

    kpis = [
        ("Ingreso total", money(m["ingreso_total"])),
        ("Pedidos", str(m["total_pedidos"])),
        ("Mesas atendidas", str(m["mesas_atendidas"])),
        ("Ticket promedio", money(m["ticket_promedio"])),
        ("Alertas stock", str(m["alertas_stock"])),
    ]

    return generate_pdf(
        title="Reporte General - Dashboard Gerencial",
        kpis=kpis,
        sections=sections,
        usuario=st.session_state.get("usuario", {}).get("nombre", "sistema"),
        auditoria=True,
    )


# ── RENDER ────────────────────────────────────────────────────────────

st.markdown("<h1 style='text-align:center'>📊  Dashboard Gerencial</h1>",
            unsafe_allow_html=True)
st.caption("Datos alimentados desde el sistema transaccional · "
           "Actualizacion automatica cada 30 segundos")

# ── Fila de metricas ──────────────────────────────────────────────────
m = query_metricas()

col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
with col_m1:
    st.metric("💰 Ingreso total",  f"${m['ingreso_total']:,.0f}")
with col_m2:
    st.metric("🧾 Pedidos",         str(m["total_pedidos"]))
with col_m3:
    st.metric("🪑 Mesas atendidas",  str(m["mesas_atendidas"]))
with col_m4:
    st.metric("🎫 Ticket promedio", f"${m['ticket_promedio']:,.0f}")
with col_m5:
    delta_color = "off" if m["alertas_stock"] == 0 else "inverse"
    st.metric("⚠️ Alertas de stock", str(m["alertas_stock"]),
              delta=f"{m['alertas_stock']} insumos criticos",
              delta_color=delta_color)

st.divider()

# ── Grafico de ventas diarias ─────────────────────────────────────────
df_ventas = query_ventas_diarias()
if not df_ventas.empty:
    st.markdown("### 📈  Ventas diarias (historico)")
    fig = px.bar(df_ventas, x="dia", y="total",
                 labels={"dia": "", "total": "$"},
                 color_discrete_sequence=[COLOR_PRIMARY])
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Aun no hay ventas cobradas registradas.")

# ── Segunda fila: Top 5 + Auditoria de cajas ──────────────────────────
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("### 🏆  Top 5 productos mas vendidos")
    df_top = query_top5()
    if not df_top.empty:
        fig = px.pie(df_top, names="producto", values="total_vendido",
                     hole=0.4, color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(textinfo="label+value", textposition="outside")
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0),
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos de ventas.")

with col_right:
    st.markdown("### 🧾  Auditoria de arqueo de caja")
    df_cajas = query_cajas()
    if not df_cajas.empty:
        def _color_diferencia(val):
            if pd.isna(val):
                return ""
            bg = COLOR_POSITIVO if val >= 0 else COLOR_NEGATIVO
            return f"background-color: {bg}; color: white; font-weight: 700"

        display = df_cajas.copy()
        display.columns = ["#", "Cajero", "Apertura", "Cierre",
                           "Apertura $", "Ventas $", "Real $", "Dif. $"]
        for c in ["Apertura $", "Ventas $", "Real $", "Dif. $"]:
            if c in display.columns:
                display[c] = display[c].apply(
                    lambda x: "-" if pd.isna(x) else f"${x:,.0f}"
                )

        st.dataframe(display, use_container_width=True, height=350,
                     hide_index=True)
    else:
        st.info("No hay registros de caja.")

st.divider()

# ── Alertas de inventario ─────────────────────────────────────────────
st.markdown("### ⚠️  Alertas de inventario por deposito")
df_alertas = query_alertas_stock()
if not df_alertas.empty:
    for _, row in df_alertas.iterrows():
        st.warning(
            f"**{row['deposito']}** — "
            f"*{row['insumo']}*: solo **{row['stock_actual']:.0f} {row['unidad_medida']}** "
            f"(minimo requerido: {row['stock_minimo']:.0f} {row['unidad_medida']})",
            icon=":material/warning:",
        )
else:
    st.success("✅  Todos los depositos tienen stock suficiente por encima del minimo.")

st.divider()

# ── Exportacion PDF ───────────────────────────────────────────────────
st.markdown("### Exportar datos")

col_e1, col_e2, col_e3 = st.columns(3)

pdf_bytes = _pdf_reporte_general(m, df_ventas, df_cajas, df_top, df_alertas)
col_e1.download_button(
    "📄 Descargar reporte PDF",
    pdf_bytes,
    file_name=f"reporte_gerencial_{datetime.now():%Y%m%d_%H%M}.pdf",
    mime="application/pdf",
    use_container_width=True,
)

if not df_ventas.empty:
    csv = df_ventas.to_csv(index=False).encode("utf-8-sig")
    col_e2.download_button("Descargar ventas_diarias.csv", csv,
                           file_name="ventas_diarias.csv", mime="text/csv",
                           use_container_width=True)
if not df_cajas.empty:
    csv = df_cajas.to_csv(index=False).encode("utf-8-sig")
    col_e3.download_button("Descargar auditoria_cajas.csv", csv,
                           file_name="auditoria_cajas.csv", mime="text/csv",
                           use_container_width=True)
