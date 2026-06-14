"""
views/dashboard.py — Dashboard gerencial con estética vintage.
Mejoras: filtro de fechas, métricas hoy vs ayer, exportación Excel,
gráfico de ventas por hora, ranking de mozos, panel de mesas.
"""
from __future__ import annotations

from datetime import date, timedelta

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


# ── Queries ────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def _query_metricas(fecha_ini: str, fecha_fin: str) -> dict:
        conn = get_connection_direct()
        try:
                    cur = conn.execute("""
                                SELECT
                                                COUNT(DISTINCT pc.id_pedido)                               AS pedidos,
                                                                COALESCE(SUM(pd.cantidad * pd.precio_unitario_facturado),0) AS ingresos,
                                                                                COALESCE(AVG(sub.subtotal),0)                              AS ticket_prom
                                                                                            FROM pedidos_cabecera pc
                                                                                                        JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
                                                                                                                    JOIN (
                                                                                                                                    SELECT id_pedido, SUM(cantidad * precio_unitario_facturado) AS subtotal
                                                                                                                                                    FROM pedido_detalle GROUP BY id_pedido
                                                                                                                                                                ) sub ON sub.id_pedido = pc.id_pedido
                                                                                                                                                                            WHERE pc.estado_comanda = 'cobrado'
                                                                                                                                                                                          AND DATE(pc.fecha_hora) BETWEEN ? AND ?
                                                                                                                                                                                                  """, (fecha_ini, fecha_fin))
                    row = cur.fetchone() or {"pedidos": 0, "ingresos": 0, "ticket_prom": 0}

            # Mesas activas ahora
                    cur2 = conn.execute(
                        "SELECT COUNT(*) AS cnt FROM mesas WHERE estado='ocupada'"
                    )
                    mesas_activas = (cur2.fetchone() or {}).get("cnt", 0)

            # Alertas stock
                    cur3 = conn.execute("""
                        SELECT COUNT(*) AS cnt FROM stock_deposito sd
                        JOIN insumos i ON i.id_insumo = sd.id_insumo
                        WHERE sd.cantidad_disponible <= i.stock_minimo
                    """)
                    alertas_cnt = (cur3.fetchone() or {}).get("cnt", 0)

            return {"m": dict(row), "alertas_cnt": alertas_cnt, "mesas_activas": mesas_activas}
finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_ventas_diarias(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
        conn = get_connection_direct()
    try:
                return pd.read_sql_query("""
                            SELECT DATE(pc.fecha_hora) AS dia,
                                               ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total,
                                                                  COUNT(DISTINCT pc.id_pedido) AS pedidos
                                                                              FROM pedidos_cabecera pc
                                                                                          JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
                                                                                                      WHERE pc.estado_comanda = 'cobrado'
                                                                                                                    AND DATE(pc.fecha_hora) BETWEEN ? AND ?
                                                                                                                                GROUP BY dia ORDER BY dia
                                                                                                                                        """, conn, params=(fecha_ini, fecha_fin))
finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_ventas_por_hora(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
        conn = get_connection_direct()
    try:
                return pd.read_sql_query("""
                            SELECT CAST(strftime('%H', pc.fecha_hora) AS INTEGER) AS hora,
                                               ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total
                                                           FROM pedidos_cabecera pc
                                                                       JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
                                                                                   WHERE pc.estado_comanda = 'cobrado'
                                                                                                 AND DATE(pc.fecha_hora) BETWEEN ? AND ?
                                                                                                             GROUP BY hora ORDER BY hora
                                                                                                                     """, conn, params=(fecha_ini, fecha_fin))
finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_top_productos(fecha_ini: str, fecha_fin: str, n: int = 10) -> pd.DataFrame:
        conn = get_connection_direct()
    try:
                return pd.read_sql_query(f"""
                            SELECT pm.nombre, SUM(pd.cantidad) AS total_vendido,
                                               ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS ingresos
                                                           FROM pedido_detalle pd
                                                                       JOIN pedidos_cabecera pc ON pc.id_pedido = pd.id_pedido
                                                                                   JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                                                                                               WHERE pc.estado_comanda = 'cobrado'
                                                                                                             AND DATE(pc.fecha_hora) BETWEEN ? AND ?
                                                                                                                         GROUP BY pm.id_producto, pm.nombre
                                                                                                                                     ORDER BY total_vendido DESC LIMIT {n}
                                                                                                                                             """, conn, params=(fecha_ini, fecha_fin))
finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_ranking_mozos(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
        conn = get_connection_direct()
    try:
                return pd.read_sql_query("""
                            SELECT u.nombre || ' ' || u.apellido AS mozo,
                                               COUNT(DISTINCT pc.id_pedido)                              AS pedidos,
                                                                  ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS ventas
                                                                              FROM pedidos_cabecera pc
                                                                                          JOIN usuarios u ON u.id_usuario = pc.id_usuario
                                                                                                      JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
                                                                                                                  WHERE pc.estado_comanda = 'cobrado'
                                                                                                                                AND DATE(pc.fecha_hora) BETWEEN ? AND ?
                                                                                                                                            GROUP BY u.id_usuario, mozo
                                                                                                                                                        ORDER BY ventas DESC
                                                                                                                                                                """, conn, params=(fecha_ini, fecha_fin))
finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_estado_mesas() -> pd.DataFrame:
        conn = get_connection_direct()
    try:
                return pd.read_sql_query("""
                            SELECT m.numero_mesa, m.estado,
                                               COALESCE(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS consumo
                                                           FROM mesas m
                                                                       LEFT JOIN pedidos_cabecera pc ON pc.id_mesa = m.id_mesa
                                                                                       AND pc.estado_comanda IN ('pendiente','en_cocina','listo','entregado')
                                                                                                   LEFT JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
                                                                                                               GROUP BY m.id_mesa, m.numero_mesa, m.estado
                                                                                                                           ORDER BY m.numero_mesa
                                                                                                                                   """, conn)
finally:
        conn.close()


@st.cache_data(ttl=60)
def _query_arqueo() -> pd.DataFrame:
        conn = get_connection_direct()
    try:
                return pd.read_sql_query("""
                            SELECT cd.id_caja, u.nombre || ' ' || u.apellido AS cajero,
                                               cd.fecha_apertura, cd.monto_apertura,
                                                                  cd.monto_ventas, cd.monto_cierre_real, cd.estado_caja
                                                                              FROM cajas_diarias cd
                                                                                          JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
                                                                                                      ORDER BY cd.fecha_apertura DESC
                                                                                                              """, conn)
finally:
        conn.close()


@st.cache_data(ttl=60)
def _query_alertas_inventario() -> list:
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
                return cur.fetchall()
finally:
        conn.close()


@st.cache_data(ttl=60)
def _query_caja_activa() -> dict | None:
        conn = get_connection_direct()
    try:
                cur = conn.execute("""
                            SELECT cd.id_caja, cd.fecha_apertura, cd.monto_apertura,
                                               cd.monto_ventas, cd.monto_cierre_real, cd.estado_caja,
                                                                  u.nombre || ' ' || u.apellido AS cajero
                                                                              FROM cajas_diarias cd
                                                                                          JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
                                                                                                      WHERE cd.estado_caja = 'abierta'
                                                                                                                  ORDER BY cd.fecha_apertura DESC LIMIT 1
                                                                                                                          """)
                return cur.fetchone()
finally:
        conn.close()


@st.cache_data(ttl=300)
def _query_predicciones() -> pd.DataFrame:
        from components.ia_predictiva import generar_sugerencia_compra_tres_dias
    return generar_sugerencia_compra_tres_dias()


# ── Helpers de exportación ─────────────────────────────────────────────

def _df_to_excel_bytes(*dfs_labels: tuple) -> bytes:
        """Genera un Excel con múltiples hojas."""
    import io as _io
    buf = _io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                for df, label in dfs_labels:
                                if not df.empty:
                                                    df.to_excel(writer, sheet_name=label[:31], index=False)
                                        return buf.getvalue()


# ── Render ─────────────────────────────────────────────────────────────

def render() -> None:
        st.markdown(
            "<h1 style='text-align:center'>📊 Dashboard Gerencial</h1>",
            unsafe_allow_html=True,
)

    # ── Tabs principales ──────────────────────────────────────────────
    tab_general, tab_mesas, tab_inventario, tab_caja, tab_ia = st.tabs([
                "📈 Ventas & Análisis",
                "🪑 Mesas en vivo",
                "⚠️ Inventario",
                "🧮 Caja",
                "🔮 IA Predicciones",
    ])

    # ── Filtro de fechas (sidebar) ────────────────────────────────────
    with st.sidebar:
                st.markdown("### 📅 Período de análisis")
                hoy = date.today()
                rango = st.selectbox(
                    "Período",
                    ["Hoy", "Ayer", "Últimos 7 días", "Últimos 30 días", "Este mes", "Personalizado"],
                    key="dash_rango",
                )
                if rango == "Hoy":
                                f_ini = f_fin = str(hoy)
elif rango == "Ayer":
            ayer = hoy - timedelta(days=1)
            f_ini = f_fin = str(ayer)
elif rango == "Últimos 7 días":
            f_ini = str(hoy - timedelta(days=6))
            f_fin = str(hoy)
elif rango == "Últimos 30 días":
            f_ini = str(hoy - timedelta(days=29))
            f_fin = str(hoy)
elif rango == "Este mes":
            f_ini = str(hoy.replace(day=1))
            f_fin = str(hoy)
else:
            f_ini = str(st.date_input("Desde", value=hoy - timedelta(days=6), key="d_ini"))
                f_fin = str(st.date_input("Hasta", value=hoy, key="d_fin"))

        st.caption(f"📅 {f_ini} → {f_fin}")
        st.divider()

        if st.button("🔄 Refrescar datos", use_container_width=True):
                        st.cache_data.clear()
                        st.rerun()

    # ── Tab 1: Ventas & Análisis ──────────────────────────────────────
    with tab_general:
                data = _query_metricas(f_ini, f_fin)
                m = data["m"]
                alertas_cnt = data["alertas_cnt"]
                mesas_activas = data["mesas_activas"]

        # Métricas con delta vs día anterior
                data_ayer = _query_metricas(
                    str(date.fromisoformat(f_ini) - timedelta(days=1)),
                    str(date.fromisoformat(f_fin) - timedelta(days=1)),
                )
                m_ant = data_ayer["m"]

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
                        delta_ing = m["ingresos"] - m_ant["ingresos"]
                        st.metric("💰 Ingresos", f"${m['ingresos']:,.0f}",
                                  delta=f"${delta_ing:+,.0f}" if delta_ing else None)
                    with c2:
                                    delta_ped = int(m["pedidos"]) - int(m_ant["pedidos"])
                                    st.metric("🧾 Pedidos", str(int(m["pedidos"])),
                                              delta=f"{delta_ped:+d}" if delta_ped else None)
                                with c3:
                                                st.metric("🎫 Ticket prom.", f"${m['ticket_prom']:,.0f}")
                                            with c4:
                                                            st.metric("🪑 Mesas activas", str(mesas_activas))
                                                        with c5:
                                                                        st.metric("⚠️ Alertas stock", str(alertas_cnt),
                                                                                                        delta=None if alertas_cnt == 0 else f"{alertas_cnt} alertas",
                                                                                                        delta_color="inverse")

        st.divider()

        # Ventas diarias
        df_ventas = _query_ventas_diarias(f_ini, f_fin)
        if not df_ventas.empty:
                        col_bar, col_hora = st.columns(2)

            with col_bar:
                                st.markdown("### 📈 Ventas por día")
                                fig = px.bar(
                                    df_ventas, x="dia", y="total",
                                    labels={"dia": "", "total": "$"},
                                    color_discrete_sequence=[BORDO],
                                    text="total",
                                )
                                fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside")
                                fig = _layout_vintage(fig)
                                fig.update_layout(height=300)
                                st.plotly_chart(fig, use_container_width=True)

            with col_hora:
                                st.markdown("### 🕐 Ventas por hora")
                                df_hora = _query_ventas_por_hora(f_ini, f_fin)
                                if not df_hora.empty:
                                                        fig2 = px.area(
                                                                                    df_hora, x="hora", y="total",
                                                                                    labels={"hora": "Hora", "total": "$"},
                                                                                    color_discrete_sequence=[MOSTAZA],
                                                        )
                                                        fig2 = _layout_vintage(fig2)
                                                        fig2.update_layout(height=300)
                                                        st.plotly_chart(fig2, use_container_width=True)
else:
                    st.info("Sin datos de ventas por hora en el período.")
else:
            alerta_vintage("Sin ventas en el período seleccionado.", icono="ℹ️")

        st.divider()

        # Top productos + Ranking mozos
        col_top, col_mozos = st.columns(2)

        with col_top:
                        st.markdown("### 🏆 Top productos")
                        df_top = _query_top_productos(f_ini, f_fin)
                        if not df_top.empty:
                                            fig = px.bar(
                                                                    df_top.head(8), x="total_vendido", y="nombre",
                                                                    orientation="h",
                                                                    labels={"total_vendido": "Unidades", "nombre": ""},
                                                                    color_discrete_sequence=[TERRACOTA],
                                                                    text="total_vendido",
                                            )
                                            fig.update_traces(textposition="outside")
                                            fig = _layout_vintage(fig)
                                            fig.update_layout(height=350, yaxis={"categoryorder": "total ascending"})
                                            st.plotly_chart(fig, use_container_width=True)
else:
                st.info("Sin datos de productos en el período.")

        with col_mozos:
                        st.markdown("### 👨‍🍳 Ranking de mozos")
                        df_mozos = _query_ranking_mozos(f_ini, f_fin)
                        if not df_mozos.empty:
                                            fig = px.bar(
                                                                    df_mozos, x="ventas", y="mozo",
                                                                    orientation="h",
                                                                    labels={"ventas": "$", "mozo": ""},
                                                                    color_discrete_sequence=[OLIVA],
                                                                    text="ventas",
                                            )
                                            fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside")
                                            fig = _layout_vintage(fig)
                                            fig.update_layout(height=350, yaxis={"categoryorder": "total ascending"})
                                            st.plotly_chart(fig, use_container_width=True)
else:
                st.info("Sin datos de mozos en el período.")

        # Exportación
            st.divider()
        st.markdown("### 📥 Exportar datos")
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
                        if not df_ventas.empty:
                                            excel_bytes = _df_to_excel_bytes(
                                                                    (df_ventas, "Ventas diarias"),
                                                                    (_query_top_productos(f_ini, f_fin), "Top productos"),
                                                                    (_query_ranking_mozos(f_ini, f_fin), "Mozos"),
                                            )
                                            st.download_button(
                                                "⬇ Descargar Excel completo",
                                                data=excel_bytes,
                                                file_name=f"dashboard_{f_ini}_{f_fin}.xlsx",
                                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                                use_container_width=True,
                                                type="primary",
                                            )
                                    with col_exp2:
                        if not df_ventas.empty:
                                            csv = df_ventas.to_csv(index=False).encode("utf-8")
                                            st.download_button(
                                                "⬇ Descargar CSV ventas",
                                                data=csv,
                                                file_name=f"ventas_{f_ini}_{f_fin}.csv",
                                                mime="text/csv",
                                                use_container_width=True,
                                            )

    # ── Tab 2: Mesas en vivo ──────────────────────────────────────────
    with tab_mesas:
                st.markdown("### 🪑 Estado de mesas en tiempo real")
        df_mesas = _query_estado_mesas()

        if df_mesas.empty:
                        st.info("No hay mesas configuradas.")
else:
            libres = (df_mesas["estado"] == "libre").sum()
            ocupadas = (df_mesas["estado"] == "ocupada").sum()
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("🪑 Total mesas", len(df_mesas))
            col_m2.metric("✅ Libres", int(libres))
            col_m3.metric("🔴 Ocupadas", int(ocupadas))

            st.markdown("---")
            COLS = 4
            mesas_list = df_mesas.to_dict("records")
            for i in range(0, len(mesas_list), COLS):
                                cols = st.columns(COLS)
                                for j, mesa in enumerate(mesas_list[i : i + COLS]):
                                                        libre = mesa["estado"] == "libre"
                                                        color = "#388e3c" if libre else "#8B2635"
                                                        consumo_str = (
                                                            f"<div style='font-size:0.85rem;margin-top:4px'>"
                                                            f"${mesa['consumo']:,.0f}</div>"
                                                            if not libre and mesa["consumo"] > 0 else ""
                                                        )
                                                        with cols[j]:
                                                                                    st.markdown(
                                                                                                                    f"<div style='background:{color};border-radius:12px;"
                                                                                                                    f"padding:1.2rem;text-align:center;color:white;"
                                                                                                                    f"font-size:1.6rem;font-weight:700;margin-bottom:8px'>"
                                                                                                                    f"🪑 {mesa['numero_mesa']}<br>"
                                                                                                                    f"<span style='font-size:0.75rem;opacity:0.9'>"
                                                                                                                    f"{'LIBRE' if libre else 'OCUPADA'}</span>"
                                                                                                                    f"{consumo_str}</div>",
                                                                                                                    unsafe_allow_html=True,
                                                                                        )

                                            if st.button("🔄 Actualizar mesas", use_container_width=True):
                                                            _query_estado_mesas.clear()
                                                            st.rerun()

    # ── Tab 3: Inventario ─────────────────────────────────────────────
    with tab_inventario:
                st.markdown("### ⚠️ Alertas de inventario")
        alertas = _query_alertas_inventario()

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
        st.markdown("### 🔮 Predicciones de compra (IA)")
        df_ia = _query_predicciones()
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
                                "Stock actual": "{:.0f}", "Consumo estimado 3 días": "{:.0f}",
                                "Déficit": "{:.0f}", "Stock mínimo": "{:.0f}",
            }).background_gradient(subset=["Déficit"], cmap="Reds")
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.download_button(
                                "📥 Descargar sugerencia CSV",
                                data=df_ia.to_csv(index=False).encode("utf-8"),
                                file_name="sugerencia_compras_ia.csv",
                                mime="text/csv",
            )

    # ── Tab 4: Caja ───────────────────────────────────────────────────
    with tab_caja:
                st.markdown("### 🧮 Arqueo y cierre de caja diario")

        # Arqueo histórico
        df_caj = _query_arqueo()
        if not df_caj.empty:
                        df_caj["diferencia"] = df_caj["monto_cierre_real"] - df_caj["monto_ventas"]
            cols_rename = {
                                "id_caja": "#", "cajero": "Cajero", "fecha_apertura": "Apertura",
                                "estado_caja": "Estado", "monto_apertura": "Apertura $",
                                "monto_ventas": "Ventas $", "monto_cierre_real": "Real $",
                                "diferencia": "Dif. $",
            }
            disp = df_caj.rename(columns=cols_rename)[list(cols_rename.values())]

            def _color_diff(val):
                                if not isinstance(val, (int, float)):
                                                        return ""
                                                    return f"background-color:{OLIVA};color:#fafafa;font-weight:700" \
                    if val >= 0 else f"background-color:{TERRACOTA};color:#fafafa;font-weight:700"

            styled = disp.style.map(_color_diff, subset=["Dif. $"])
            st.dataframe(styled, use_container_width=True, height=300, hide_index=True)

            excel_caja = _df_to_excel_bytes((df_caj, "Arqueo caja"))
            st.download_button(
                                "⬇ Exportar arqueo Excel",
                                data=excel_caja,
                                file_name="arqueo_caja.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        st.divider()
        st.markdown("### 🔒 Cierre de caja")
        caja_activa = _query_caja_activa()

        if caja_activa:
                        st.info(
                                            f"**Caja #{caja_activa['id_caja']}** — "
                                            f"Apertura: {str(caja_activa['fecha_apertura'])[:19]} | "
                                            f"Cajero: {caja_activa['cajero']}"
                        )
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                                st.metric("💰 Monto apertura", f"${caja_activa['monto_apertura']:,.0f}")
                st.metric("💵 Ventas registradas", f"${caja_activa['monto_ventas']:,.0f}")
            with col_c2:
                                monto_real = st.number_input(
                                                        "🧾 Dinero físico contado ($)",
                                                        min_value=0.0,
                                                        value=float(caja_activa["monto_ventas"] or 0),
                                                        step=100.0, format="%.0f",
                                )
                diferencia = monto_real - (caja_activa["monto_ventas"] or 0)
                color_diff = "#388e3c" if diferencia >= 0 else "#c62828"
                st.markdown(
                                        f"<div style='background:{color_diff};color:white;padding:1rem;"
                                        f"border-radius:10px;text-align:center;font-size:1.3rem;font-weight:700'>"
                                        f"{'✅' if diferencia >= 0 else '❌'} "
                                        f"Diferencia: ${diferencia:+,.0f}</div>",
                                        unsafe_allow_html=True,
                )

            if st.button("🔒 CERRAR CAJA", type="primary", use_container_width=True):
                                conn = get_connection_direct()
                try:
                                        conn.execute("""
                                                                UPDATE cajas_diarias
                                                                                        SET fecha_cierre = datetime('now','localtime'),
                                                                                                                    monto_cierre_real = ?, estado_caja = 'cerrada'
                                                                                                                                            WHERE id_caja = ?
                                                                                                                                                                """, (monto_real, caja_activa["id_caja"]))
                    conn.commit()
                    _query_caja_activa.clear()
                    _query_arqueo.clear()
                    _query_metricas.cache_clear() if hasattr(_query_metricas, "cache_clear") else None
                    st.balloons()
                    st.success(
                                                f"✅ Caja #{caja_activa['id_caja']} cerrada. "
                                                f"Diferencia: ${diferencia:+,.0f}"
                    )
                    st.rerun()
except Exception as e:
                    conn.rollback()
                    st.error(f"Error al cerrar caja: {e}")
finally:
                    conn.close()
else:
            st.success("✅ No hay cajas abiertas.")
            with st.form("abrir_caja_form"):
                                monto_ini = st.number_input(
                                                        "💰 Monto de apertura ($)", min_value=0.0,
                                                        value=0.0, step=100.0, format="%.0f",
                                )
                if st.form_submit_button("➕ Abrir nueva caja", use_container_width=True):
                                        conn = get_connection_direct()
                    try:
                                                conn.execute(
                                                                                "INSERT INTO cajas_diarias (id_usuario_cajero, monto_apertura) VALUES (?,?)",
                                                                                (1, monto_ini),
                                                )
                                                conn.commit()
                                                _query_caja_activa.clear()
                                                st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
finally:
                        conn.close()

    # ── Tab 5: IA Predicciones ────────────────────────────────────────
    with tab_ia:
                st.markdown("## 🔮 Predicciones de Compra con IA")
        st.markdown(
                        "<p style='font-style:italic;color:#555'>"
                        "Proyección para los próximos 3 días · "
                        "Promedio móvil ponderado + ajuste estacional por día de semana</p>",
                        unsafe_allow_html=True,
        )
        df_ia2 = _query_predicciones()
        if df_ia2.empty:
                        alerta_vintage("Stock suficiente. No se requieren compras urgentes.", icono="✅")
else:
            # Gráfico de déficits
                fig_ia = px.bar(
                                    df_ia2.head(15), x="Insumo", y="Déficit",
                                    labels={"Déficit": "Unidades faltantes"},
                                    color_discrete_sequence=[BORDO],
                                    title="Déficit proyectado (próximos 3 días)",
                )
            fig_ia = _layout_vintage(fig_ia)
            st.plotly_chart(fig_ia, use_container_width=True)

            styled2 = df_ia2.style.format({
                                "Stock actual": "{:.0f}", "Consumo estimado 3 días": "{:.0f}",
                                "Déficit": "{:.0f}", "Stock mínimo": "{:.0f}",
            }).background_gradient(subset=["Déficit"], cmap="Reds")
            st.dataframe(styled2, use_container_width=True, hide_index=True)
            st.download_button(
                                "📥 Descargar sugerencia CSV",
                                data=df_ia2.to_csv(index=False).encode("utf-8"),
                                file_name="sugerencia_compras_ia.csv",
                                mime="text/csv",
            )
