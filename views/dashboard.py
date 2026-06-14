"""
views/dashboard.py - Dashboard gerencial con filtros, tabs y exportacion.
"""
from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from components.estilos import BORDO, CARBON, OLIVA, PALETTA_TIERRA, TERRACOTA, alerta_vintage
from components.imagenes import obtener_imagen
from database import get_connection_direct


def _layout_vintage(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Lora, Georgia, serif", color=CARBON, size=13),
        title_font=dict(family="Playfair Display, Georgia, serif", color=CARBON),
        margin=dict(l=10, r=10, t=25, b=10),
    )
    fig.update_xaxes(gridcolor="#EADCC9", showgrid=True)
    fig.update_yaxes(gridcolor="#EADCC9", showgrid=True)
    return fig


@st.cache_data(ttl=30)
def _query_metricas(fecha_ini: str, fecha_fin: str) -> dict:
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            """
            SELECT COUNT(DISTINCT pc.id_pedido) AS pedidos,
                   COALESCE(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS ingresos
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            WHERE pc.estado_comanda = 'cobrado'
              AND DATE(pc.fecha_hora) BETWEEN ? AND ?
            """,
            (fecha_ini, fecha_fin),
        )
        ventas = dict(cur.fetchone() or {"pedidos": 0, "ingresos": 0})

        cur = conn.execute("SELECT COUNT(*) AS cnt FROM mesas WHERE estado='ocupada'")
        mesas_activas = (cur.fetchone() or {}).get("cnt", 0)

        cur = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM stock_deposito sd
            JOIN insumos i ON i.id_insumo = sd.id_insumo
            WHERE sd.cantidad_disponible <= i.stock_minimo
            """
        )
        alertas_cnt = (cur.fetchone() or {}).get("cnt", 0)
    finally:
        conn.close()

    ingresos = float(ventas.get("ingresos") or 0)
    pedidos = int(ventas.get("pedidos") or 0)
    ticket_prom = ingresos / pedidos if pedidos else 0
    return {
        "pedidos": pedidos,
        "ingresos": ingresos,
        "ticket_prom": ticket_prom,
        "mesas_activas": mesas_activas,
        "alertas_cnt": alertas_cnt,
    }


@st.cache_data(ttl=30)
def _query_ventas_diarias(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    conn = get_connection_direct()
    try:
        return pd.read_sql_query(
            """
            SELECT DATE(pc.fecha_hora) AS dia,
                   ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total,
                   COUNT(DISTINCT pc.id_pedido) AS pedidos
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            WHERE pc.estado_comanda = 'cobrado'
              AND DATE(pc.fecha_hora) BETWEEN ? AND ?
            GROUP BY dia
            ORDER BY dia
            """,
            conn,
            params=(fecha_ini, fecha_fin),
        )
    finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_ventas_por_hora(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    conn = get_connection_direct()
    try:
        return pd.read_sql_query(
            """
            SELECT CAST(strftime('%H', pc.fecha_hora) AS INTEGER) AS hora,
                   ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            WHERE pc.estado_comanda = 'cobrado'
              AND DATE(pc.fecha_hora) BETWEEN ? AND ?
            GROUP BY hora
            ORDER BY hora
            """,
            conn,
            params=(fecha_ini, fecha_fin),
        )
    finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_top_productos(fecha_ini: str, fecha_fin: str, n: int = 10) -> pd.DataFrame:
    conn = get_connection_direct()
    try:
        return pd.read_sql_query(
            f"""
            SELECT pm.nombre,
                   SUM(pd.cantidad) AS total_vendido,
                   ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS ingresos
            FROM pedido_detalle pd
            JOIN pedidos_cabecera pc ON pc.id_pedido = pd.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda = 'cobrado'
              AND DATE(pc.fecha_hora) BETWEEN ? AND ?
            GROUP BY pm.id_producto, pm.nombre
            ORDER BY total_vendido DESC
            LIMIT {int(n)}
            """,
            conn,
            params=(fecha_ini, fecha_fin),
        )
    finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_ranking_mozos(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    conn = get_connection_direct()
    try:
        return pd.read_sql_query(
            """
            SELECT u.nombre || ' ' || u.apellido AS mozo,
                   COUNT(DISTINCT pc.id_pedido) AS pedidos,
                   ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS ventas
            FROM pedidos_cabecera pc
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            WHERE pc.estado_comanda = 'cobrado'
              AND DATE(pc.fecha_hora) BETWEEN ? AND ?
            GROUP BY u.id_usuario, mozo
            ORDER BY ventas DESC
            """,
            conn,
            params=(fecha_ini, fecha_fin),
        )
    finally:
        conn.close()


@st.cache_data(ttl=30)
def _query_estado_mesas() -> pd.DataFrame:
    conn = get_connection_direct()
    try:
        return pd.read_sql_query(
            """
            SELECT m.numero_mesa,
                   m.estado,
                   COALESCE(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS consumo
            FROM mesas m
            LEFT JOIN pedidos_cabecera pc ON pc.id_mesa = m.id_mesa
              AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
            LEFT JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            GROUP BY m.id_mesa, m.numero_mesa, m.estado
            ORDER BY m.numero_mesa
            """,
            conn,
        )
    finally:
        conn.close()


@st.cache_data(ttl=60)
def _query_alertas_inventario() -> list:
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            """
            SELECT d.nombre_deposito AS dep,
                   i.nombre AS ins,
                   sd.cantidad_disponible AS stock,
                   i.stock_minimo,
                   i.unidad_medida,
                   i.url_imagen
            FROM stock_deposito sd
            JOIN insumos i ON i.id_insumo = sd.id_insumo
            JOIN depositos d ON d.id_deposito = sd.id_deposito
            WHERE sd.cantidad_disponible <= i.stock_minimo
            ORDER BY d.nombre_deposito, i.nombre
            """
        )
        return cur.fetchall()
    finally:
        conn.close()


@st.cache_data(ttl=60)
def _query_arqueo() -> pd.DataFrame:
    conn = get_connection_direct()
    try:
        return pd.read_sql_query(
            """
            SELECT cd.id_caja,
                   u.nombre || ' ' || u.apellido AS cajero,
                   cd.fecha_apertura,
                   cd.monto_apertura,
                   cd.monto_ventas,
                   cd.monto_cierre_real,
                   cd.estado_caja
            FROM cajas_diarias cd
            JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
            ORDER BY cd.fecha_apertura DESC
            """,
            conn,
        )
    finally:
        conn.close()


@st.cache_data(ttl=60)
def _query_caja_activa() -> dict | None:
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            """
            SELECT cd.id_caja,
                   cd.fecha_apertura,
                   cd.monto_apertura,
                   cd.monto_ventas,
                   cd.monto_cierre_real,
                   cd.estado_caja,
                   u.nombre || ' ' || u.apellido AS cajero
            FROM cajas_diarias cd
            JOIN usuarios u ON u.id_usuario = cd.id_usuario_cajero
            WHERE cd.estado_caja = 'abierta'
            ORDER BY cd.fecha_apertura DESC
            LIMIT 1
            """
        )
        return cur.fetchone()
    finally:
        conn.close()


@st.cache_data(ttl=300)
def _query_predicciones() -> pd.DataFrame:
    from components.ia_predictiva import generar_sugerencia_compra_tres_dias

    return generar_sugerencia_compra_tres_dias()


def _df_to_excel_bytes(*dfs_labels: tuple[pd.DataFrame, str]) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for df, label in dfs_labels:
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=label[:31], index=False)
    return buf.getvalue()


def _periodo_sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.markdown("### Periodo de analisis")
        hoy = date.today()
        rango = st.selectbox(
            "Periodo",
            ["Hoy", "Ayer", "Ultimos 7 dias", "Ultimos 30 dias", "Este mes", "Personalizado"],
            key="dash_rango",
        )
        if rango == "Hoy":
            f_ini = f_fin = hoy
        elif rango == "Ayer":
            f_ini = f_fin = hoy - timedelta(days=1)
        elif rango == "Ultimos 7 dias":
            f_ini, f_fin = hoy - timedelta(days=6), hoy
        elif rango == "Ultimos 30 dias":
            f_ini, f_fin = hoy - timedelta(days=29), hoy
        elif rango == "Este mes":
            f_ini, f_fin = hoy.replace(day=1), hoy
        else:
            f_ini = st.date_input("Desde", value=hoy - timedelta(days=6), key="d_ini")
            f_fin = st.date_input("Hasta", value=hoy, key="d_fin")

        st.caption(f"{f_ini} -> {f_fin}")
        if st.button("Refrescar datos", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    return str(f_ini), str(f_fin)


def render() -> None:
    st.markdown("<h1 style='text-align:center'>Dashboard Gerencial</h1>", unsafe_allow_html=True)
    f_ini, f_fin = _periodo_sidebar()

    tab_general, tab_mesas, tab_inventario, tab_caja, tab_ia = st.tabs(
        ["Ventas & Analisis", "Mesas en vivo", "Inventario", "Caja", "IA Predicciones"]
    )

    with tab_general:
        _tab_general(f_ini, f_fin)
    with tab_mesas:
        _tab_mesas()
    with tab_inventario:
        _tab_inventario()
    with tab_caja:
        _tab_caja()
    with tab_ia:
        _tab_ia()


def _tab_general(f_ini: str, f_fin: str) -> None:
    data = _query_metricas(f_ini, f_fin)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Ingresos", f"${data['ingresos']:,.0f}")
    c2.metric("Pedidos", str(data["pedidos"]))
    c3.metric("Ticket prom.", f"${data['ticket_prom']:,.0f}")
    c4.metric("Mesas activas", str(data["mesas_activas"]))
    c5.metric("Alertas stock", str(data["alertas_cnt"]))

    st.divider()
    df_ventas = _query_ventas_diarias(f_ini, f_fin)
    df_hora = _query_ventas_por_hora(f_ini, f_fin)

    col_bar, col_hora = st.columns(2)
    with col_bar:
        st.markdown("### Ventas diarias")
        if df_ventas.empty:
            st.info("Sin ventas en el periodo.")
        else:
            fig = px.bar(df_ventas, x="dia", y="total", labels={"dia": "", "total": "$"}, color_discrete_sequence=[BORDO])
            st.plotly_chart(_layout_vintage(fig), use_container_width=True)

    with col_hora:
        st.markdown("### Ventas por hora")
        if df_hora.empty:
            st.info("Sin datos por hora en el periodo.")
        else:
            fig = px.line(df_hora, x="hora", y="total", markers=True, labels={"hora": "Hora", "total": "$"})
            fig.update_traces(line_color=OLIVA)
            st.plotly_chart(_layout_vintage(fig), use_container_width=True)

    col_prod, col_mozos = st.columns(2)
    with col_prod:
        st.markdown("### Top productos")
        df_top = _query_top_productos(f_ini, f_fin)
        if df_top.empty:
            st.info("Sin productos vendidos.")
        else:
            fig = px.pie(df_top.head(10), names="nombre", values="total_vendido", hole=0.4, color_discrete_sequence=PALETTA_TIERRA)
            st.plotly_chart(_layout_vintage(fig), use_container_width=True)

    with col_mozos:
        st.markdown("### Ranking de mozos")
        df_mozos = _query_ranking_mozos(f_ini, f_fin)
        if df_mozos.empty:
            st.info("Sin datos de mozos.")
        else:
            fig = px.bar(df_mozos, x="ventas", y="mozo", orientation="h", color_discrete_sequence=[OLIVA], text="ventas")
            fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside")
            st.plotly_chart(_layout_vintage(fig), use_container_width=True)

    st.divider()
    st.markdown("### Exportar datos")
    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        excel = _df_to_excel_bytes(
            (df_ventas, "Ventas diarias"),
            (_query_top_productos(f_ini, f_fin), "Top productos"),
            (_query_ranking_mozos(f_ini, f_fin), "Mozos"),
        )
        st.download_button(
            "Descargar Excel completo",
            data=excel,
            file_name=f"dashboard_{f_ini}_{f_fin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with col_exp2:
        st.download_button(
            "Descargar CSV ventas",
            data=df_ventas.to_csv(index=False).encode("utf-8"),
            file_name=f"ventas_{f_ini}_{f_fin}.csv",
            mime="text/csv",
            use_container_width=True,
            disabled=df_ventas.empty,
        )


def _tab_mesas() -> None:
    st.markdown("### Estado de mesas en tiempo real")
    df = _query_estado_mesas()
    if df.empty:
        st.info("No hay mesas configuradas.")
        return

    libres = int((df["estado"] == "libre").sum())
    ocupadas = int((df["estado"] == "ocupada").sum())
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Total mesas", len(df))
    col_m2.metric("Libres", libres)
    col_m3.metric("Ocupadas", ocupadas)

    st.markdown("---")
    cols_por_fila = 4
    mesas = df.to_dict("records")
    for i in range(0, len(mesas), cols_por_fila):
        cols = st.columns(cols_por_fila)
        for j, mesa in enumerate(mesas[i : i + cols_por_fila]):
            libre = mesa["estado"] == "libre"
            color = "#388e3c" if libre else "#8B2635"
            consumo = float(mesa.get("consumo") or 0)
            with cols[j]:
                st.markdown(
                    f"<div style='background:{color};border-radius:8px;padding:1rem;"
                    f"text-align:center;color:white;font-size:1.35rem;font-weight:700;margin-bottom:8px'>"
                    f"Mesa {mesa['numero_mesa']}<br>"
                    f"<span style='font-size:0.75rem'>{'LIBRE' if libre else 'OCUPADA'}</span>"
                    f"{f'<div style=\"font-size:0.85rem;margin-top:4px\">${consumo:,.0f}</div>' if not libre else ''}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    if st.button("Actualizar mesas", use_container_width=True):
        _query_estado_mesas.clear()
        st.rerun()


def _tab_inventario() -> None:
    st.markdown("### Alertas de inventario")
    alertas = _query_alertas_inventario()
    if not alertas:
        alerta_vintage("Todos los depositos en nivel seguro.", icono="OK")
        return

    for alerta in alertas:
        col_icon, col_msg = st.columns([1, 8])
        with col_icon:
            st.image(obtener_imagen(alerta.get("url_imagen"), tipo="insumo"), width=50)
        with col_msg:
            alerta_vintage(
                f"**{alerta['dep']}** - *{alerta['ins']}*: solo "
                f"**{float(alerta['stock'] or 0):.0f} {alerta['unidad_medida']}** "
                f"(min: {float(alerta['stock_minimo'] or 0):.0f})",
                critico=True,
            )


def _tab_caja() -> None:
    st.markdown("### Arqueo y cierre de caja diario")
    df_caja = _query_arqueo()
    if not df_caja.empty:
        df_caja["diferencia"] = df_caja["monto_cierre_real"].fillna(0) - df_caja["monto_ventas"].fillna(0)
        st.dataframe(df_caja, use_container_width=True, hide_index=True)
        st.download_button(
            "Exportar arqueo Excel",
            data=_df_to_excel_bytes((df_caja, "Arqueo caja")),
            file_name="arqueo_caja.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.divider()
    caja_activa = _query_caja_activa()
    if caja_activa:
        st.info(
            f"Caja #{caja_activa['id_caja']} - Apertura: {str(caja_activa['fecha_apertura'])[:19]} - "
            f"Cajero: {caja_activa['cajero']}"
        )
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.metric("Monto apertura", f"${float(caja_activa['monto_apertura'] or 0):,.0f}")
            st.metric("Ventas registradas", f"${float(caja_activa['monto_ventas'] or 0):,.0f}")
        with col_c2:
            ventas = float(caja_activa["monto_ventas"] or 0)
            monto_real = st.number_input("Dinero fisico contado ($)", min_value=0.0, value=ventas, step=100.0, format="%.0f")
            diferencia = monto_real - ventas
            color = "#388e3c" if diferencia >= 0 else "#c62828"
            st.markdown(
                f"<div style='background:{color};color:white;padding:1rem;border-radius:8px;"
                f"text-align:center;font-size:1.2rem;font-weight:700'>Diferencia: ${diferencia:+,.0f}</div>",
                unsafe_allow_html=True,
            )

        if st.button("CERRAR CAJA", type="primary", use_container_width=True):
            _cerrar_caja(caja_activa["id_caja"], monto_real)
    else:
        st.success("No hay cajas abiertas.")
        with st.form("abrir_caja_form"):
            monto_ini = st.number_input("Monto de apertura ($)", min_value=0.0, value=0.0, step=100.0, format="%.0f")
            if st.form_submit_button("Abrir nueva caja", use_container_width=True):
                _abrir_caja(monto_ini)


def _abrir_caja(monto_ini: float) -> None:
    conn = get_connection_direct()
    try:
        conn.execute("INSERT INTO cajas_diarias (id_usuario_cajero, monto_apertura) VALUES (?, ?)", (1, monto_ini))
        conn.commit()
        _query_caja_activa.clear()
        _query_arqueo.clear()
        st.rerun()
    except Exception as exc:
        conn.rollback()
        st.error(f"Error: {exc}")
    finally:
        conn.close()


def _cerrar_caja(id_caja: int, monto_real: float) -> None:
    conn = get_connection_direct()
    try:
        conn.execute(
            """
            UPDATE cajas_diarias
            SET fecha_cierre = datetime('now', 'localtime'),
                monto_cierre_real = ?,
                estado_caja = 'cerrada'
            WHERE id_caja = ?
            """,
            (monto_real, id_caja),
        )
        conn.commit()
        _query_caja_activa.clear()
        _query_arqueo.clear()
        _query_metricas.clear()
        st.success(f"Caja #{id_caja} cerrada.")
        st.rerun()
    except Exception as exc:
        conn.rollback()
        st.error(f"Error al cerrar caja: {exc}")
    finally:
        conn.close()


def _tab_ia() -> None:
    st.markdown("## Predicciones de Compra con IA")
    df_ia = _query_predicciones()
    if df_ia.empty:
        alerta_vintage("Stock suficiente. No se requieren compras urgentes.", icono="OK")
        return

    if "Déficit" in df_ia.columns and "Stock mínimo" in df_ia.columns:
        criticos = df_ia[df_ia["Déficit"] > df_ia["Stock mínimo"] * 2]
        for _, row in criticos.iterrows():
            alerta_vintage(
                f"**{row['Insumo']}**: deficit de **{row['Déficit']:.0f} {row['Unidad']}** - "
                f"sugerido: {row['Proveedor sugerido']}",
                icono="!",
                critico=True,
            )

    st.dataframe(df_ia, use_container_width=True, hide_index=True)
    st.download_button(
        "Descargar sugerencia CSV",
        data=df_ia.to_csv(index=False).encode("utf-8"),
        file_name="sugerencia_compras_ia.csv",
        mime="text/csv",
    )
