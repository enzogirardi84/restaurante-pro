"""Facturacion electronica: emision, archivo fiscal y descarga directa PDF."""
from __future__ import annotations

import re
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from components.helpers import execute, money as fmt_money, one, rows

IVA_RATE = 0.21


def ultimo_numero_factura(punto_venta: int = 1, tipo: str = "B") -> int:
    row = one(
        """
        SELECT COALESCE(MAX(numero_comprobante), 0) AS ultimo
        FROM facturas_electronicas
        WHERE punto_venta = ? AND tipo_comprobante = ?
        """,
        (punto_venta, tipo),
    )
    return int(row["ultimo"]) if row else 0


def _calcular_neto_iva(total: float, aplica_iva: bool = True) -> tuple[float, float]:
    total = float(total or 0)
    if not aplica_iva:
        return total, 0.0
    neto = round(total / (1 + IVA_RATE), 2)
    return neto, round(total - neto, 2)


def registrar_factura(
    id_pago: int | None = None,
    tipo: str = "B",
    cuit: str = "",
    razon_social: str = "",
    domicilio: str = "",
    condicion_iva: str = "Consumidor Final",
    subtotal: float = 0,
    iva: float = 0,
    total: float = 0,
    medio_pago: str = "",
    observaciones: str = "",
) -> dict:
    try:
        pv = 1
        nro = ultimo_numero_factura(pv, tipo) + 1
        razon = razon_social.strip() or "Consumidor Final"
        execute(
            """
            INSERT INTO facturas_electronicas
                (id_pago, tipo_comprobante, punto_venta, numero_comprobante,
                 cuit_cliente, razon_social_cliente, domicilio_cliente,
                 condicion_iva, subtotal, iva, total, medio_pago,
                 fecha_emision, estado, observaciones)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'emitido', ?)
            """,
            (
                id_pago,
                tipo,
                pv,
                nro,
                cuit.strip(),
                razon,
                domicilio.strip(),
                condicion_iva,
                float(subtotal or 0),
                float(iva or 0),
                float(total or 0),
                medio_pago,
                date.today().isoformat(),
                observaciones.strip(),
            ),
        )
        creada = one(
            """
            SELECT id_factura
            FROM facturas_electronicas
            WHERE punto_venta = ? AND tipo_comprobante = ? AND numero_comprobante = ?
            ORDER BY id_factura DESC
            LIMIT 1
            """,
            (pv, tipo, nro),
        )
        return {
            "ok": True,
            "id_factura": creada["id_factura"] if creada else None,
            "numero": nro,
            "tipo": tipo,
            "pv": pv,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def anular_factura(id_factura: int) -> dict:
    try:
        execute(
            "UPDATE facturas_electronicas SET estado = 'anulado' WHERE id_factura = ?",
            (id_factura,),
        )
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def pagos_sin_factura() -> list[dict]:
    return rows(
        """
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
        """
    )


def listar_facturas(
    desde: str = "",
    hasta: str = "",
    busqueda: str = "",
    solo_activas: bool = False,
    limite: int = 200,
) -> pd.DataFrame:
    filtros = []
    params: list = []
    if solo_activas:
        filtros.append("fe.estado != 'anulado'")
    if desde:
        filtros.append("fe.fecha_emision >= ?")
        params.append(desde)
    if hasta:
        filtros.append("fe.fecha_emision <= ?")
        params.append(hasta)
    if busqueda.strip():
        term = f"%{busqueda.strip()}%"
        filtros.append(
            "(fe.cuit_cliente LIKE ? OR fe.razon_social_cliente LIKE ? OR "
            "CAST(fe.numero_comprobante AS TEXT) LIKE ? OR fe.medio_pago LIKE ?)"
        )
        params.extend([term, term, term, term])
    where = "WHERE " + " AND ".join(filtros) if filtros else ""

    df = pd.DataFrame(
        rows(
            f"""
            SELECT fe.id_factura,
                   fe.tipo_comprobante || ' ' || fe.punto_venta || '-' ||
                       SUBSTR('00000000' || fe.numero_comprobante, -8) AS comprobante,
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
            """,
            tuple(params) + (limite,),
        )
    )
    return df


def obtener_factura(id_factura: int) -> dict | None:
    return one("SELECT * FROM facturas_electronicas WHERE id_factura = ?", (id_factura,))


def _nombre_comprobante(f: dict) -> str:
    return f"{f['tipo_comprobante']}-{int(f['punto_venta']):04d}-{int(f['numero_comprobante']):08d}"


def _filename_factura(f: dict, suffix: str = "pdf") -> str:
    cliente = str(f.get("razon_social_cliente") or "Consumidor_Final")
    cliente = re.sub(r"[^A-Za-z0-9_-]+", "_", cliente).strip("_")[:40] or "cliente"
    return f"factura_{_nombre_comprobante(f)}_{cliente}.{suffix}"


def _fmt_pdf_money(value) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _items_factura(id_pago: int | None) -> list[dict]:
    if not id_pago:
        return []
    try:
        return rows(
            """
            SELECT pm.nombre,
                   pg.cantidad,
                   pg.precio_unitario AS precio,
                   (pg.cantidad * pg.precio_unitario) AS importe
            FROM pago_detalle pg
            JOIN pedido_detalle pd ON pd.id_detalle = pg.id_detalle
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pg.id_pago = ?
            ORDER BY pm.categoria, pm.nombre
            """,
            (id_pago,),
        )
    except Exception:
        return []


def _pdf_factura(f: dict) -> bytes:
    buf = BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Factura {_nombre_comprobante(f)}")

    comprobante = _nombre_comprobante(f)
    tipo_label = str(f.get("tipo_comprobante") or "B").upper()
    estado = str(f.get("estado") or "emitido").upper()

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, h - 50, "EL PATRON - Restaurante Pro")
    c.setFont("Helvetica", 9)
    c.drawString(50, h - 68, "Factura Electronica")
    c.setFont("Helvetica-Bold", 26)
    c.drawCentredString(w / 2, h - 50, tipo_label)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(w - 50, h - 50, comprobante)
    c.setFont("Helvetica", 8)
    c.drawRightString(w - 50, h - 66, f"Estado: {estado}")

    c.setStrokeColorRGB(0.29, 0.17, 0.10)
    c.setLineWidth(0.5)
    c.line(50, h - 80, w - 50, h - 80)

    y = h - 100
    c.setFont("Helvetica", 9)
    c.drawString(50, y, f"Fecha: {f.get('fecha_emision') or ''}")
    c.drawString(50, y - 14, f"CAE: {f.get('cae') or '-'}")
    c.drawString(50, y - 28, f"CAE Vto: {f.get('cae_vencimiento') or '-'}")
    if f.get("observaciones"):
        c.drawString(50, y - 42, f"Obs.: {str(f['observaciones'])[:58]}")

    c.setFont("Helvetica-Bold", 10)
    c.drawString(w - 300, y, "CLIENTE")
    c.setFont("Helvetica", 9)
    c.drawString(w - 300, y - 14, str(f.get("razon_social_cliente") or "Consumidor Final")[:48])
    c.drawString(w - 300, y - 28, f"CUIT: {f.get('cuit_cliente') or '-'}")
    c.drawString(w - 300, y - 42, f"Condicion IVA: {f.get('condicion_iva') or '-'}")
    c.drawString(w - 300, y - 56, f"Domicilio: {str(f.get('domicilio_cliente') or '-')[:42]}")

    y2 = y - 80
    c.line(50, y2, w - 50, y2)

    y3 = y2 - 30
    c.setFont("Helvetica-Bold", 9)
    c.drawString(60, y3, "Cant.")
    c.drawString(105, y3, "Concepto")
    c.drawRightString(w - 155, y3, "P. Unit.")
    c.drawRightString(w - 50, y3, "Importe")

    c.setFont("Helvetica", 9)
    items = _items_factura(f.get("id_pago"))
    if not items:
        items = [
            {
                "cantidad": 1,
                "nombre": "Venta segun detalle adjunto",
                "precio": float(f.get("subtotal") or 0),
                "importe": float(f.get("subtotal") or 0),
            }
        ]
    for item in items[:18]:
        y3 -= 16
        cantidad = float(item.get("cantidad") or 0)
        precio = float(item.get("precio") or 0)
        importe = float(item.get("importe") or cantidad * precio)
        c.drawString(60, y3, f"{cantidad:g}")
        c.drawString(105, y3, str(item.get("nombre") or "")[:42])
        c.drawRightString(w - 155, y3, _fmt_pdf_money(precio))
        c.drawRightString(w - 50, y3, _fmt_pdf_money(importe))
    if len(items) > 18:
        y3 -= 16
        c.drawString(105, y3, f"... y {len(items) - 18} item(s) mas")

    y3 -= 24
    c.setStrokeColorRGB(0.29, 0.17, 0.10)
    c.line(50, y3, w - 50, y3)

    y3 -= 20
    c.setFont("Helvetica", 10)
    c.drawRightString(w - 50, y3, f"Neto: {_fmt_pdf_money(f.get('subtotal'))}")
    y3 -= 15
    c.drawRightString(w - 50, y3, f"IVA: {_fmt_pdf_money(f.get('iva'))}")
    y3 -= 18
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y3, f"Medio de pago: {f.get('medio_pago') or '-'}")
    c.drawRightString(w - 50, y3, f"TOTAL: {_fmt_pdf_money(f.get('total'))}")

    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(w / 2, 40, "Documento generado por sistema - El Patron Restaurante Pro")
    c.drawCentredString(w / 2, 30, f"Pagina 1 de 1 - Emitido {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    c.save()
    return buf.getvalue()


def _render_descarga_pdf_factura(
    f: dict,
    label: str = "Descargar PDF",
    key: str | None = None,
    compact: bool = False,
) -> None:
    st.download_button(
        label,
        _pdf_factura(f),
        file_name=_filename_factura(f),
        mime="application/pdf",
        use_container_width=not compact,
        key=key or f"download_factura_{f['id_factura']}",
    )


def _render_ultima_factura() -> None:
    id_factura = st.session_state.get("ultima_factura_emitida")
    if not id_factura:
        return
    factura = obtener_factura(int(id_factura))
    if not factura:
        return
    with st.expander("Ultimo comprobante emitido - descargar", expanded=True):
        st.success(f"Comprobante {_nombre_comprobante(factura)} emitido correctamente.")
        _render_descarga_pdf_factura(factura, "Descargar comprobante PDF", key=f"ultima_factura_{id_factura}")
        if st.button("Ocultar comprobante emitido", use_container_width=True):
            st.session_state.ultima_factura_emitida = None
            st.rerun()


def page_facturacion_electronica():
    st.markdown("## Archivo Tributario de Facturas")
    st.caption("Emision, auditoria, descarga de comprobantes PDF y control de IVA.")
    _render_ultima_factura()
    tab_nueva, tab_desde_pago, tab_lista = st.tabs(
        ["Nuevo comprobante", "Desde pago / ticket", "Comprobantes emitidos"]
    )

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
            razon_social = st.text_input("Razon social", value="Consumidor Final")
        with col_b:
            condicion_iva = st.selectbox(
                "Condicion IVA",
                ["Consumidor Final", "Responsable Inscripto", "Monotributista", "Exento", "No Responsable"],
            )
            domicilio = st.text_input("Domicilio")
            medio_pago = st.selectbox("Medio de pago", ["Efectivo", "Tarjeta", "Transferencia", "Mercado Pago", "QR"])

        col_c, col_d, col_e = st.columns(3)
        with col_c:
            total_manual = st.number_input("Total final $", min_value=0.0, step=100.0, format="%.2f")
        with col_d:
            aplica_iva = st.checkbox("Calcular IVA 21% incluido", value=tipo in ("A", "B"))
        subtotal, iva = _calcular_neto_iva(total_manual, aplica_iva)
        with col_e:
            st.metric("Neto", fmt_money(subtotal))
            st.caption(f"IVA: {fmt_money(iva)}")

        observaciones = st.text_area("Observaciones", placeholder="Nro pedido, forma de pago detallada...")
        if st.form_submit_button("Emitir comprobante", type="primary", use_container_width=True):
            if total_manual <= 0:
                st.error("El total debe ser mayor a 0.")
            else:
                r = registrar_factura(
                    None,
                    tipo,
                    cuit,
                    razon_social,
                    domicilio,
                    condicion_iva,
                    subtotal,
                    iva,
                    total_manual,
                    medio_pago,
                    observaciones,
                )
                if r["ok"]:
                    st.session_state.ultima_factura_emitida = r.get("id_factura")
                    st.success(f"Comprobante {r['tipo']} {r['pv']}-{r['numero']:08d} emitido.")
                    st.rerun()
                else:
                    st.error(r["error"])


def _render_factura_desde_pago():
    st.markdown("**Generar comprobante o ticket desde un pago existente**")
    pagos = pagos_sin_factura()
    if not pagos:
        st.info("Todos los pagos ya tienen comprobante asociado.")
        return

    opts = {
        f"#{p['id_pago']} Mesa {p['numero_mesa']} {p['medio_pago']} {fmt_money(p['total'])} ({str(p['fecha_hora'])[:16]})": p
        for p in pagos
    }
    sel = st.selectbox("Seleccionar pago", list(opts.keys()))
    pago = opts[sel]

    subtotal_calc, iva_calc = _calcular_neto_iva(float(pago["total"] or 0), True)
    with st.expander("Detalle del pago", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mesa", pago["numero_mesa"])
        c2.metric("Medio", pago["medio_pago"])
        c3.metric("Neto", fmt_money(subtotal_calc))
        c4.metric("Total", fmt_money(pago["total"]))

    with st.form("form_factura_desde_pago"):
        tipo = st.selectbox("Tipo comprobante", ["ticket", "B", "A", "X"])
        cuit = st.text_input("CUIT cliente", placeholder="99-99999999-9")
        razon_social = st.text_input("Razon social", value="Consumidor Final")
        condicion_iva = st.selectbox(
            "Condicion IVA",
            ["Consumidor Final", "Responsable Inscripto", "Monotributista", "Exento", "No Responsable"],
        )
        aplica_iva = st.checkbox("Discriminar IVA 21% incluido", value=tipo in ("A", "B", "ticket"))
        subtotal, iva = _calcular_neto_iva(float(pago["total"] or 0), aplica_iva)
        st.caption(f"Neto {fmt_money(subtotal)} | IVA {fmt_money(iva)} | Total {fmt_money(pago['total'])}")
        if st.form_submit_button("Emitir y habilitar descarga PDF", type="primary", use_container_width=True):
            r = registrar_factura(
                pago["id_pago"],
                tipo,
                cuit,
                razon_social,
                "",
                condicion_iva,
                subtotal,
                iva,
                float(pago["total"]),
                pago["medio_pago"],
                f"Pago #{pago['id_pago']} Mesa {pago['numero_mesa']}",
            )
            if r["ok"]:
                st.session_state.ultima_factura_emitida = r.get("id_factura")
                st.success(f"Comprobante {r['tipo']} {r['pv']}-{r['numero']:08d} emitido.")
                st.rerun()
            else:
                st.error(r["error"])


def _render_listado():
    col_a, col_b, col_c, col_d = st.columns([1, 1, 2, 1])
    desde = col_a.date_input("Desde", value=date.today().replace(day=1), key="fe_desde")
    hasta = col_b.date_input("Hasta", value=date.today(), key="fe_hasta")
    busqueda = col_c.text_input("Buscar cliente, CUIT, ticket o medio", placeholder="Consumidor, 30-, 8321...")
    solo_activas = col_d.checkbox("Solo validos", value=False)

    df = listar_facturas(str(desde), str(hasta), busqueda, solo_activas=solo_activas)
    if df.empty:
        st.info("Sin comprobantes en el periodo.")
        return

    total = float(df["total"].sum())
    iva_total = float(df["iva"].sum())
    neto_total = float(df["subtotal"].sum())
    anulados = int((df["estado"] == "anulado").sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Facturado neto", fmt_money(neto_total))
    c2.metric("IVA debito fiscal", fmt_money(iva_total))
    c3.metric("Total bruto", fmt_money(total))
    c4.metric("Anulados", anulados)

    st.markdown("---")
    header = st.columns([1.3, 0.9, 2.2, 1, 1, 1, 0.8, 1.2])
    for col, label in zip(header, ["Nro", "Fecha", "Cliente / CUIT", "Neto", "IVA", "Total", "Estado", "Acciones"]):
        col.caption(label)

    for _, r in df.iterrows():
        factura = obtener_factura(int(r["id_factura"]))
        if not factura:
            continue
        cols = st.columns([1.3, 0.9, 2.2, 1, 1, 1, 0.8, 1.2])
        cols[0].markdown(f"**{r['comprobante']}**")
        cols[1].markdown(str(r["fecha_emision"])[:10])
        cols[2].markdown(f"**{r['razon_social_cliente'] or 'Consumidor Final'}**  \n`{r['cuit_cliente'] or '-'}`")
        cols[3].markdown(fmt_money(r["subtotal"]))
        cols[4].markdown(fmt_money(r["iva"]))
        cols[5].markdown(f"**{fmt_money(r['total'])}**")
        cols[6].markdown("VALIDO" if r["estado"] != "anulado" else "ANULADO")
        with cols[7]:
            _render_descarga_pdf_factura(
                factura,
                label="PDF",
                key=f"pdf_direct_{r['id_factura']}",
                compact=True,
            )
            if r["estado"] != "anulado":
                if st.button("Anular NC", key=f"del_{r['id_factura']}", use_container_width=True):
                    anular_factura(int(r["id_factura"]))
                    st.rerun()

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Descargar auditoria CSV",
        csv,
        file_name=f"comprobantes_{desde}_{hasta}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    with st.expander("Ultimos numeros fiscales"):
        for tipo in ("A", "B", "X", "ticket"):
            nro = ultimo_numero_factura(1, tipo)
            st.caption(f"Tipo {tipo}: ultimo Nro {nro:08d}")
