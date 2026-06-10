"""Facturación electrónica — emisión, vinculación con pagos, PDF y listado."""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from components.helpers import rows, one, execute, money as fmt_money


# ── API ────────────────────────────────────────────────────────────────────

def ultimo_numero_factura(punto_venta: int = 1, tipo: str = "B") -> int:
    row = one("""
        SELECT COALESCE(MAX(numero_comprobante), 0) AS ultimo
        FROM facturas_electronicas
        WHERE punto_venta = ? AND tipo_comprobante = ?
    """, (punto_venta, tipo))
    return row["ultimo"] if row else 0


def registrar_factura(id_pago: int | None = None,
                      tipo: str = "B",
                      cuit: str = "", razon_social: str = "",
                      domicilio: str = "",
                      condicion_iva: str = "Consumidor Final",
                      subtotal: float = 0, iva: float = 0,
                      total: float = 0, medio_pago: str = "",
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


def pagos_sin_factura() -> list[dict]:
    return rows("""
        SELECT pm.id_pago, pm.fecha_hora, pm.medio_pago, pm.total, pm.subtotal,
               pm.servicio, m.numero_mesa,
               u.nombre || ' ' || u.apellido AS cajero
        FROM pagos_mesa pm
        JOIN mesas m ON m.id_mesa = pm.id_mesa
        JOIN usuarios u ON u.id_usuario = pm.id_usuario
        WHERE pm.id_pago NOT IN (
            SELECT id_pago FROM facturas_electronicas WHERE id_pago IS NOT NULL
        )
        ORDER BY pm.fecha_hora DESC
        LIMIT 50
    """)


def listar_facturas(desde: str = "", hasta: str = "",
                    cuit: str = "", solo_activas: bool = True,
                    limite: int = 200) -> pd.DataFrame:
    filtros = []
    params = []
    if solo_activas:
        filtros.append("fe.estado != 'anulado'")
    if desde:
        filtros.append("fe.fecha_emision >= ?")
        params.append(desde)
    if hasta:
        filtros.append("fe.fecha_emision <= ?")
        params.append(hasta)
    if cuit.strip():
        filtros.append("fe.cuit_cliente LIKE ?")
        params.append(f"%{cuit.strip()}%")
    where = "WHERE " + " AND ".join(filtros) if filtros else ""

    df = pd.DataFrame(rows(f"""
        SELECT fe.id_factura,
               fe.tipo_comprobante || ' ' || fe.punto_venta || '-' ||
                   SUBSTR('00000' || fe.numero_comprobante, -5) AS comprobante,
               fe.fecha_emision, fe.razon_social_cliente, fe.cuit_cliente,
               fe.subtotal, fe.iva, fe.total, fe.medio_pago, fe.estado
        FROM facturas_electronicas fe
        {where}
        ORDER BY fe.fecha_emision DESC, fe.id_factura DESC
        LIMIT ?
    """, tuple(params) + (limite,)))
    return df


# ── PDF de factura ────────────────────────────────────────────────────────

def _pdf_factura(f: dict) -> bytes:
    buf = BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Factura {f['tipo_comprobante']} {f['punto_venta']}-{f['numero_comprobante']:05d}")

    # Encabezado
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, h - 50, "EL PATRON — Restaurante Pro")
    c.setFont("Helvetica", 9)
    c.drawString(50, h - 68, "Factura Electronica")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(w - 50, h - 50, f"{f['tipo_comprobante']} {f['punto_venta']}-{f['numero_comprobante']:05d}")

    c.setStrokeColorRGB(0.29, 0.17, 0.10)
    c.setLineWidth(0.5)
    c.line(50, h - 80, w - 50, h - 80)

    # Fecha / CAE
    y = h - 100
    c.setFont("Helvetica", 9)
    c.drawString(50, y, f"Fecha: {f['fecha_emision']}")
    c.drawString(50, y - 14, f"CAE: {f.get('cae', '—')}")
    c.drawString(50, y - 28, f"CAE Vto: {f.get('cae_vencimiento', '—')}")

    # Cliente
    c.setFont("Helvetica-Bold", 10)
    c.drawString(w - 300, y, "CLIENTE")
    c.setFont("Helvetica", 9)
    c.drawString(w - 300, y - 14, f"{f['razon_social_cliente']}")
    c.drawString(w - 300, y - 28, f"CUIT: {f['cuit_cliente'] or '—'}")
    c.drawString(w - 300, y - 42, f"Condicion IVA: {f['condicion_iva']}")
    c.drawString(w - 300, y - 56, f"Domicilio: {f['domicilio_cliente'] or '—'}")

    y2 = y - 80
    c.line(50, y2, w - 50, y2)

    # Detalle — intentar obtener items del pago asociado
    items_str = "Venta segun detalle adjunto"
    _id_pago = f.get("id_pago")
    if _id_pago:
        try:
            from components.helpers import rows as _r
            _det = _r("""
                SELECT pm.nombre, pd.cantidad,
                       COALESCE(pd.precio_unitario_facturado, pm.precio_venta) AS precio
                FROM pago_detalle pg
                JOIN pedido_detalle pd ON pd.id_detalle = pg.id_detalle
                JOIN productos_menu pm ON pm.id_producto = pd.id_producto
                WHERE pg.id_pago = ?
            """, (_id_pago,))
            if _det:
                items_str = "\n".join(f"{d['cantidad']}x {d['nombre']} (${float(d['precio']):.2f} c/u)" for d in _det)
        except Exception:
            pass

    y3 = y2 - 30
    c.setFont("Helvetica-Bold", 9)
    c.drawString(60, y3, "Concepto")
    c.drawString(60, y3, "Concepto")
    c.drawRightString(w - 200, y3, "Subtotal")
    c.drawRightString(w - 120, y3, "IVA")
    c.drawRightString(w - 50, y3, "Total")

    c.setFont("Helvetica", 9)
    y3 -= 16
    c.drawString(60, y3, "Venta segun detalle adjunto")
    c.drawRightString(w - 200, y3, f"${f['subtotal']:,.2f}".replace(",", "."))
    c.drawRightString(w - 120, y3, f"${f['iva']:,.2f}".replace(",", "."))
    c.drawRightString(w - 50, y3, f"${f['total']:,.2f}".replace(",", "."))

    y3 -= 24
    c.setStrokeColorRGB(0.29, 0.17, 0.10)
    c.line(50, y3, w - 50, y3)

    # Totales
    y3 -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawString(60, y3, f"Medio de pago: {f['medio_pago']}")
    c.drawRightString(w - 50, y3, f"TOTAL: ${f['total']:,.2f}".replace(",", "."))

    # Pie
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(w / 2, 40, "Documento generado por sistema — El Patron Restaurante Pro")
    c.drawCentredString(w / 2, 30, f"Pagina 1 de 1 — Emitido {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    c.save()
    return buf.getvalue()


# ── UI ────────────────────────────────────────────────────────────────────

def page_facturacion_electronica():
    st.subheader("Facturación electrónica")
    tab_nueva, tab_desde_pago, tab_lista = st.tabs(
        ["Nuevo comprobante", "Desde pago", "Comprobantes emitidos"])

    with tab_nueva:
        _render_nueva_factura()
    with tab_desde_pago:
        _render_factura_desde_pago()
    with tab_lista:
        _render_listado()


def _render_nueva_factura():
    with st.form("form_factura"):
        col_a, col_b = st.columns(2)
        with col_a:
            tipo = st.selectbox("Tipo", ["B", "A", "X", "ticket"])
            cuit = st.text_input("CUIT cliente", placeholder="30-12345678-9")
            razon_social = st.text_input("Razon social")
        with col_b:
            condicion_iva = st.selectbox(
                "Condicion IVA",
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
            st.metric("Total $", fmt_money(total))
        observaciones = st.text_area("Observaciones", placeholder="Nro pedido, forma de pago detallada...")
        if st.form_submit_button("Emitir comprobante", type="primary", use_container_width=True):
            if total <= 0:
                st.error("El total debe ser mayor a 0.")
            else:
                r = registrar_factura(None, tipo, cuit, razon_social,
                                      domicilio, condicion_iva,
                                      subtotal, iva, total, medio_pago, observaciones)
                if r["ok"]:
                    st.success(f"Comprobante {r['tipo']} {r['pv']}-{r['numero']:05d} emitido.")
                    st.rerun()
                else:
                    st.error(r["error"])


def _render_factura_desde_pago():
    st.markdown("**Generar comprobante desde un pago existente**")
    pagos = pagos_sin_factura()
    if not pagos:
        st.info("Todos los pagos ya tienen comprobante asociado.")
        return

    opts = {f"#{p['id_pago']} Mesa {p['numero_mesa']} {p['medio_pago']} ${p['total']:,.0f} ({p['fecha_hora'][:16]})": p
            for p in pagos}
    sel = st.selectbox("Seleccionar pago", list(opts.keys()))
    pago = opts[sel]

    with st.expander("Detalle del pago", expanded=True):
        st.write(f"**Mesa:** {pago['numero_mesa']}")
        st.write(f"**Cajero:** {pago['cajero']}")
        st.write(f"**Medio:** {pago['medio_pago']}")
        st.write(f"**Subtotal:** ${pago['subtotal']:,.2f}")
        st.write(f"**Servicio:** ${pago['servicio']:,.2f}")
        st.write(f"**Total:** ${pago['total']:,.2f}")

    with st.form("form_factura_desde_pago"):
        tipo = st.selectbox("Tipo comprobante", ["B", "A", "X", "ticket"])
        cuit = st.text_input("CUIT cliente", placeholder="30-12345678-9")
        razon_social = st.text_input("Razon social")
        condicion_iva = st.selectbox("Condicion IVA",
                                     ["Consumidor Final", "Responsable Inscripto",
                                      "Monotributista", "Exento", "No Responsable"])
        if st.form_submit_button("Emitir comprobante", type="primary", use_container_width=True):
            r = registrar_factura(pago["id_pago"], tipo, cuit, razon_social,
                                  "", condicion_iva,
                                  float(pago["subtotal"]), 0.0,
                                  float(pago["total"]), pago["medio_pago"],
                                  f"Pago #{pago['id_pago']} Mesa {pago['numero_mesa']}")
            if r["ok"]:
                st.success(f"Comprobante {r['tipo']} {r['pv']}-{r['numero']:05d} emitido.")
                st.rerun()
            else:
                st.error(r["error"])


def _render_listado():
    col_a, col_b, col_c = st.columns(3)
    desde = col_a.date_input("Desde", value=date.today().replace(day=1), key="fe_desde")
    hasta = col_b.date_input("Hasta", value=date.today(), key="fe_hasta")
    cuit_filtro = col_c.text_input("CUIT (opcional)", placeholder="Filtrar...")

    df = listar_facturas(str(desde), str(hasta), cuit_filtro)
    if df.empty:
        st.info("Sin comprobantes en el periodo.")
    else:
        total = float(df["total"].sum())
        iva_total = float(df["iva"].sum())
        cantidad = len(df)
        anulados = len(df[df["estado"] == "anulado"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Comprobantes", cantidad)
        c2.metric("Total emitido", fmt_money(total))
        c3.metric("IVA total", fmt_money(iva_total))
        c4.metric("Anulados", anulados)

        for _, r in df.iterrows():
            cols = st.columns([2, 1.5, 1, 0.6, 0.6, 0.6])
            cols[0].markdown(f"**{r['comprobante']}**")
            cols[1].markdown(f"{r['razon_social_cliente'][:25]}")
            cols[2].markdown(fmt_money(r['total']))
            estado = r['estado']
            if estado == "anulado":
                cols[3].markdown("❌ Anulado")
            else:
                cols[3].markdown("✅ Emitido")
            f_dict = one("SELECT * FROM facturas_electronicas WHERE id_factura = ?", (int(r["id_factura"]),))
            if f_dict:
                if cols[4].button("PDF", key=f"pdf_{r['id_factura']}"):
                    pdf_bytes = _pdf_factura(f_dict)
                    st.download_button("Descargar PDF", pdf_bytes,
                                       file_name=f"factura_{r['comprobante'].replace(' ', '_')}.pdf",
                                       mime="application/pdf")
                if estado != "anulado":
                    if cols[5].button("Anular", key=f"del_{r['id_factura']}"):
                        anular_factura(int(r["id_factura"]))
                        st.rerun()

        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Descargar comprobantes.csv", csv,
                           file_name=f"comprobantes_{desde}_{hasta}.csv",
                           mime="text/csv", use_container_width=True)

    st.subheader("Ultimos numeros")
    for tipo in ("A", "B", "X"):
        nro = ultimo_numero_factura(1, tipo)
        st.caption(f"Tipo {tipo}: ultimo N\xb0 {nro:05d}")
