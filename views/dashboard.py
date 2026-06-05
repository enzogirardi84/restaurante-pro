"""
views/dashboard.py — Dashboard gerencial con estética vintage.
Gráficos Plotly con paleta de tierra, alertas HTML personalizadas.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from database import get_connection_direct
from components.estilos import (
    BORDO, OLIVA, MOSTAZA, TERRACOTA, BEIGE, PALETTA_TIERRA, CARBON,
    alerta_vintage,
)
from components.imagenes import obtener_imagen


def _layout_vintage(fig: go.Figure) -> go.Figure:
    """Aplica fondo transparente, tipografía serif y color carbón."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Lora, Georgia, serif", color=CARBON, size=13),
        title_font=dict(family="Playfair Display, Georgia, serif", color=CARBON),
        margin=dict(l=10, r=10, t=20, b=10),
    )
    fig.update_xaxes(gridcolor="#EADCC9", showgrid=True)
    fig.update_yaxes(gridcolor="#EADCC9", showgrid=True)
    return fig


def render() -> None:
    st.markdown("<h1 style='text-align:center'>📊  Dashboard Gerencial</h1>",
                unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center;font-style:italic;color:#2C221E'>"
        "Analítica · Inventario · Predicciones</p>",
        unsafe_allow_html=True,
    )

    conn = get_connection_direct()
    try:
        cur = conn.execute("""
            SELECT
                COUNT(DISTINCT pc.id_pedido) AS pedidos,
                COALESCE(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS ingresos,
                ROUND(AVG(pd.cantidad * pd.precio_unitario_facturado), 0) AS ticket_prom
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            WHERE pc.estado_comanda = 'cobrado'
        """)
        row = cur.fetchone()
        if row is None:
            row = {"pedidos": 0, "ingresos": 0, "ticket_prom": 0}
        m = row

        cur = conn.execute("""
            SELECT COUNT(*) AS cnt FROM stock_deposito sd
            JOIN insumos i ON i.id_insumo = sd.id_insumo
            WHERE sd.cantidad_disponible <= i.stock_minimo
        """)
        row2 = cur.fetchone()
        alertas_cnt = row2["cnt"] if row2 else 0
    finally:
        conn.close()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("💰 Ingresos", f"${m['ingresos']:,.0f}")
    with c2:
        st.metric("🧾 Pedidos", str(m["pedidos"]))
    with c3:
        st.metric("🎫 Ticket prom.", f"${m['ticket_prom']:,.0f}")
    with c4:
        st.metric("⚠️ Alertas stock", str(alertas_cnt))

    st.divider()

    # ── Ventas diarias (Bordó vintage) ──
    conn = get_connection_direct()
    try:
        df = pd.read_sql_query("""
            SELECT DATE(pc.fecha_hora) AS dia,
                   ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            WHERE pc.estado_comanda = 'cobrado'
            GROUP BY dia ORDER BY dia
        """, conn)
    finally:
        conn.close()

    if not df.empty:
        st.markdown("### 📈  Ventas diarias")
        fig = px.bar(df, x="dia", y="total",
                     labels={"dia": "", "total": "$"},
                     color_discrete_sequence=[BORDO])
        fig = _layout_vintage(fig)
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)

    # ── Top 5 + Auditoría ──
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### 🏆  Top 5 productos")
        conn = get_connection_direct()
        try:
            df_top = pd.read_sql_query("""
                SELECT pm.nombre, SUM(pd.cantidad) AS total_vendido
                FROM pedido_detalle pd
                JOIN pedidos_cabecera pc ON pc.id_pedido = pd.id_pedido
                JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                WHERE pc.estado_comanda = 'cobrado'
                GROUP BY pm.id_producto, pm.nombre
                ORDER BY total_vendido DESC LIMIT 5
            """, conn)
        finally:
            conn.close()

        if not df_top.empty:
            fig = px.pie(df_top, names="nombre", values="total_vendido",
                         hole=0.4, color_discrete_sequence=PALETTA_TIERRA)
            fig.update_traces(textinfo="label+value", textposition="outside",
                              marker=dict(line=dict(color="#EADCC9", width=2)))
            fig = _layout_vintage(fig)
            fig.update_layout(height=350, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.markdown("### 🧾  Arqueo de caja")
        conn = get_connection_direct()
        try:
            df_caj = pd.read_sql_query("""
                SELECT cd.id_caja,
                       u.nombre || ' ' || u.apellido AS cajero,
                       cd.fecha_apertura, cd.monto_apertura,
                       cd.monto_ventas, cd.monto_cierre_real
                FROM cajas_diarias cd
                JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
                ORDER BY cd.fecha_apertura DESC
            """, conn)
        finally:
            conn.close()

        if not df_caj.empty:
            df_caj["diferencia"] = df_caj["monto_cierre_real"] - df_caj["monto_ventas"]
            cols = {"id_caja": "#", "cajero": "Cajero", "fecha_apertura": "Apertura",
                    "monto_apertura": "Apertura $", "monto_ventas": "Ventas $",
                    "monto_cierre_real": "Real $", "diferencia": "Dif. $"}
            disp = df_caj.rename(columns=cols)[list(cols.values())]

            def _color_diff(val):
                if val is None or not isinstance(val, (int, float)):
                    return ""
                bg = OLIVA if val >= 0 else TERRACOTA
                return f"background-color:{bg};color:#fafafa;font-weight:700"

            styled = disp.style.map(_color_diff, subset=["Dif. $"])
            st.dataframe(styled, use_container_width=True, height=350,
                         hide_index=True)

    st.divider()

    # ── Alertas de inventario ──
    st.markdown("### ⚠️  Alertas de inventario")
    conn = get_connection_direct()
    try:
        cur = conn.execute("""
            SELECT d.nombre_deposito AS dep, i.nombre AS ins,
                   sd.cantidad_disponible AS stock, i.stock_minimo,
                   i.unidad_medida, i.url_imagen
            FROM stock_deposito sd
            JOIN insumos i ON i.id_insumo = sd.id_insumo
            JOIN depositos d ON d.id_deposito = sd.id_deposito
            WHERE sd.cantidad_disponible <= i.stock_minimo
            ORDER BY d.nombre_deposito, i.nombre
        """)
        alertas = cur.fetchall()
    finally:
        conn.close()

    if alertas:
        for a in alertas:
            col_icon, col_msg = st.columns([1, 8])
            with col_icon:
                img_path = obtener_imagen(a.get("url_imagen"), tipo="insumo")
                st.image(img_path, width=50)
            with col_msg:
                alerta_vintage(
                    f"**{a['dep']}** — *{a['ins']}*: "
                    f"solo **{a['stock']:.0f} {a['unidad_medida']}** "
                    f"(mín: {a['stock_minimo']:.0f})",
                    critico=True,
                )
    else:
        alerta_vintage("Todos los depósitos en nivel seguro.", icono="✅")

    st.divider()

    # ── Predicciones IA ────────────────────────────────────────────────
    st.markdown("## 🔮  Predicciones de Compra con IA")
    st.markdown(
        "<p style='font-style:italic;color:#2C221E'>"
        "Proyección para los próximos 3 días · "
        "Promedio móvil ponderado + ajuste estacional por día de la semana</p>",
        unsafe_allow_html=True,
    )

    from components.ia_predictiva import generar_sugerencia_compra_tres_dias

    df_ia = generar_sugerencia_compra_tres_dias()

    if df_ia.empty:
        alerta_vintage("Stock suficiente. No se requieren compras urgentes.", icono="✅")
    else:
        criticos = df_ia[df_ia["Déficit"] > df_ia["Stock mínimo"] * 2]
        for _, row in criticos.iterrows():
            alerta_vintage(
                f"**{row['Insumo']}**: déficit de **{row['Déficit']:.0f} {row['Unidad']}** "
                f"— sugerido: {row['Proveedor sugerido']}",
                icono="🔥", critico=True,
            )

        styled = df_ia.style.format({
            "Stock actual": "{:.0f}",
            "Consumo estimado 3 días": "{:.0f}",
            "Déficit": "{:.0f}",
            "Stock mínimo": "{:.0f}",
        }).background_gradient(subset=["Déficit"], cmap="Reds")

        st.dataframe(styled, use_container_width=True, hide_index=True)

        st.download_button(
            label="📥  Descargar sugerencia CSV",
            data=df_ia.to_csv(index=False).encode("utf-8"),
            file_name="sugerencia_compras_ia.csv",
            mime="text/csv",
        )

    st.divider()

    # ── Cierre de caja diario ──────────────────────────────────────────
    st.markdown("## 🧮  Cierre de caja diario")
    st.caption("Arqueo: compare las ventas registradas con el dinero físico.")

    conn = get_connection_direct()
    try:
        cur = conn.execute("""
            SELECT cd.id_caja, cd.fecha_apertura, cd.fecha_cierre,
                   cd.monto_apertura, cd.monto_ventas, cd.monto_cierre_real,
                   cd.estado_caja,
                   u.nombre || ' ' || u.apellido AS cajero
            FROM cajas_diarias cd
            JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
            WHERE cd.estado_caja = 'abierta'
            ORDER BY cd.fecha_apertura DESC LIMIT 1
        """)
        caja_activa = cur.fetchone()
    finally:
        conn.close()

    if caja_activa:
        st.info(f"**Caja #{caja_activa['id_caja']}** — "
                f"Apertura: {caja_activa['fecha_apertura'][:19]} | "
                f"Cajero: {caja_activa['cajero']}")

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.metric("💰 Monto apertura",
                      f"${caja_activa['monto_apertura']:,.0f}")
            st.metric("💵 Ventas registradas",
                      f"${caja_activa['monto_ventas']:,.0f}")

        with col_c2:
            monto_real = st.number_input(
                "🧾  Dinero físico contado",
                min_value=0.0,
                value=float(caja_activa["monto_ventas"]),
                step=100.0,
                format="%.0f",
            )
            diferencia = monto_real - caja_activa["monto_ventas"]
            color_diff = "#7A8450" if diferencia >= 0 else "#A64B2A"
            st.markdown(
                f"<div style='background:{color_diff};color:white;padding:1rem;"
                f"border-radius:10px;text-align:center;font-size:1.3rem;font-weight:700'>"
                f"{'✅' if diferencia >= 0 else '❌'} Diferencia: ${diferencia:+,.0f}</div>",
                unsafe_allow_html=True,
            )

        if st.button("🔒  CERRAR CAJA", type="primary", use_container_width=True):
            conn = get_connection_direct()
            try:
                conn.execute("""
                    UPDATE cajas_diarias
                    SET fecha_cierre = datetime('now','localtime'),
                        monto_cierre_real = ?,
                        estado_caja = 'cerrada'
                    WHERE id_caja = ?
                """, (monto_real, caja_activa["id_caja"]))
                conn.commit()
                st.balloons()
                st.success(f"✅ Caja #{caja_activa['id_caja']} cerrada. "
                           f"Diferencia: ${diferencia:+,.0f}")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Error al cerrar caja: {e}")
            finally:
                conn.close()
    else:
        st.success("✅  No hay cajas abiertas. Todo cerrado.")
        with st.form("abrir_caja_form"):
            monto_ini = st.number_input(
                "💰 Monto de apertura", min_value=0.0, value=0.0, step=100.0, format="%.0f"
            )
            if st.form_submit_button("➕ Abrir nueva caja", use_container_width=True):
                conn = get_connection_direct()
                try:
                    conn.execute(
                        "INSERT INTO cajas_diarias (id_usuario_cajero, monto_apertura) VALUES (?,?)",
                        (1, monto_ini)
                    )
                    conn.commit()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    conn.close()
