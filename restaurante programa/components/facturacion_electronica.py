"""Facturación electrónica — registro de comprobantes y exportación."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from components.helpers import rows, one, execute, money


TABLA_SQL = """
CREATE TABLE IF NOT EXISTS facturas_electronicas (
    id_factura INTEGER PRIMARY KEY AUTOINCREMENT,
    id_pago INTEGER,
    tipo_comprobante TEXT NOT NULL DEFAULT 'B' CHECK (tipo_comprobante IN ('A', 'B', 'X', 'ticket')),
    punto_venta INTEGER NOT NULL DEFAULT 1,
    numero_comprobante INTEGER NOT NULL DEFAULT 0,
    cuit_cliente TEXT NOT NULL DEFAULT '',
    razon_social_cliente TEXT NOT NULL DEFAULT '',
    domicilio_cliente TEXT NOT NULL DEFAULT '',
    condicion_iva TEXT NOT NULL DEFAULT 'Consumidor Final',
    subtotal REAL NOT NULL DEFAULT 0,
    iva REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    medio_pago TEXT NOT NULL DEFAULT '',
    fecha_emision TEXT NOT NULL,
    cae TEXT NOT NULL DEFAULT '',
    cae_vencimiento TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'emitido' CHECK (estado IN ('pendiente', 'emitido', 'anulado')),
    observaciones TEXT NOT NULL DEFAULT ''
);
"""

TABLA_PG = """
create table if not exists facturas_electronicas (
    id_factura bigserial primary key,
    id_pago bigint references pagos_mesa(id_pago),
    tipo_comprobante text not null default 'B' check (tipo_comprobante in ('A', 'B', 'X', 'ticket')),
    punto_venta integer not null default 1,
    numero_comprobante integer not null default 0,
    cuit_cliente text not null default '',
    razon_social_cliente text not null default '',
    domicilio_cliente text not null default '',
    condicion_iva text not null default 'Consumidor Final',
    subtotal numeric not null default 0,
    iva numeric not null default 0,
    total numeric not null default 0,
    medio_pago text not null default '',
    fecha_emision date not null,
    cae text not null default '',
    cae_vencimiento text not null default '',
    estado text not null default 'emitido' check (estado in ('pendiente', 'emitido', 'anulado')),
    observaciones text not null default ''
);
"""


def ultimo_numero_factura(punto_venta: int = 1,
                          tipo: str = "B") -> int:
    row = one("""
        SELECT COALESCE(MAX(numero_comprobante), 0) AS ultimo
        FROM facturas_electronicas
        WHERE punto_venta = ? AND tipo_comprobante = ?
    """, (punto_venta, tipo))
    return row["ultimo"] if row else 0


def registrar_factura(id_pago: int | None = None,
                      tipo: str = "B",
                      cuit: str = "",
                      razon_social: str = "",
                      domicilio: str = "",
                      condicion_iva: str = "Consumidor Final",
                      subtotal: float = 0,
                      iva: float = 0,
                      total: float = 0,
                      medio_pago: str = "",
                      observaciones: str = "") -> dict:
    try:
        pv = 1
        nro = ultimo_numero_factura(pv, tipo) + 1
        execute("""
            INSERT INTO facturas_electronicas
                (id_pago, tipo_comprobante, punto_venta, numero_comprobante,
                 cuit_cliente, razon_social_cliente, domicilio_cliente,
                 condicion_iva, subtotal, iva, total, medio_pago,
                 fecha_emision, estado, observaciones)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'emitido', ?)
        """, (id_pago, tipo, pv, nro, cuit.strip(), razon_social.strip(),
              domicilio.strip(), condicion_iva, subtotal, iva, total,
              medio_pago, date.today().isoformat(), observaciones.strip()))
        return {"ok": True, "numero": nro, "tipo": tipo, "pv": pv}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def anular_factura(id_factura: int) -> dict:
    try:
        execute("UPDATE facturas_electronicas SET estado = 'anulado' WHERE id_factura = ?",
                (id_factura,))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def listar_facturas(desde: str = "", hasta: str = "",
                    limite: int = 100) -> pd.DataFrame:
    filtros = ["fe.estado != 'anulado'"]
    params = []
    if desde:
        filtros.append("fe.fecha_emision >= ?")
        params.append(desde)
    if hasta:
        filtros.append("fe.fecha_emision <= ?")
        params.append(hasta)
    where = "WHERE " + " AND ".join(filtros) if filtros else ""

    df = pd.DataFrame(rows(f"""
        SELECT fe.id_factura,
               fe.tipo_comprobante || ' ' || fe.punto_venta || '-' || fe.numero_comprobante AS comprobante,
               fe.fecha_emision,
               fe.razon_social_cliente,
               fe.cuit_cliente,
               fe.subtotal,
               fe.iva,
               fe.total,
               fe.medio_pago,
               fe.estado
        FROM facturas_electronicas fe
        {where}
        ORDER BY fe.fecha_emision DESC, fe.id_factura DESC
        LIMIT ?
    """, tuple(params) + (limite,)))
    return df


# ── UI ───────────────────────────────────────────────────

def page_facturacion_electronica():
    st.subheader("Facturación electrónica")

    tab_nueva, tab_lista = st.tabs(["Nuevo comprobante", "Comprobantes emitidos"])

    with tab_nueva:
        _render_nueva_factura()

    with tab_lista:
        _render_listado()


def _render_nueva_factura():
    with st.form("form_factura"):
        col_a, col_b = st.columns(2)
        with col_a:
            tipo = st.selectbox("Tipo", ["B", "A", "X", "ticket"])
            cuit = st.text_input("CUIT cliente", placeholder="30-12345678-9")
            razon_social = st.text_input("Razón social")
        with col_b:
            condicion_iva = st.selectbox(
                "Condición IVA",
                ["Consumidor Final", "Responsable Inscripto",
                 "Monotributista", "Exento", "No Responsable"])
            domicilio = st.text_input("Domicilio")
            medio_pago = st.selectbox("Medio de pago",
                                      ["Efectivo", "Tarjeta", "Transferencia", "Mercado Pago"])

        col_c, col_d, col_e = st.columns(3)
        with col_c:
            subtotal = st.number_input("Subtotal $", min_value=0.0, step=100.0, format="%.2f")
        with col_d:
            iva = st.number_input("IVA $", min_value=0.0, step=10.0, format="%.2f")
        with col_e:
            total = subtotal + iva
            st.metric("Total $", money(total))

        observaciones = st.text_area("Observaciones", placeholder="Nro pedido, forma de pago detallada...")

        if st.form_submit_button("Emitir comprobante", type="primary",
                                 use_container_width=True):
            if total <= 0:
                st.error("El total debe ser mayor a 0.")
            else:
                r = registrar_factura(None, tipo, cuit, razon_social,
                                     domicilio, condicion_iva,
                                     subtotal, iva, total, medio_pago,
                                     observaciones)
                if r["ok"]:
                    st.success(
                        f"Comprobante {r['tipo']} {r['pv']}-{r['numero']:05d} emitido.")
                    st.rerun()
                else:
                    st.error(r["error"])


def _render_listado():
    col_a, col_b = st.columns(2)
    desde = col_a.date_input("Desde", value=date.today().replace(day=1),
                             key="fe_desde")
    hasta = col_b.date_input("Hasta", value=date.today(), key="fe_hasta")

    df = listar_facturas(str(desde), str(hasta))
    if df.empty:
        st.info("Sin comprobantes en el período.")
    else:
        st.dataframe(df, hide_index=True, use_container_width=True)

        total = df["total"].sum()
        st.caption(f"Total emitido: {money(total)}")

        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Descargar comprobantes.csv", csv,
                          file_name=f"comprobantes_{desde}_{hasta}.csv",
                          mime="text/csv", use_container_width=True)

    # Últimos números
    st.subheader("Últimos números")
    for tipo in ("A", "B", "X"):
        nro = ultimo_numero_factura(1, tipo)
        st.caption(f"Tipo {tipo}: último N° {nro:05d}")
