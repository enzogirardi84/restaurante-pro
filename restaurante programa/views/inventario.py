"""
views/inventario.py — Gestion de inventario con pestañas funcionales,
data editor reactivo, formularios protegidos y metricas seguras.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from database import execute, execute_query, get_connection, get_db_type, registrar_auditoria, historial_stock
from components.helpers import money as fmt_money, rows


def page_inventario() -> None:
    from components.css import title

    title("Inventario", "Stock, compras, ajustes, mermas, proveedores e historial.")

    # ── KPIs seguros con COALESCE ──────────────────────────────────────
    _kpi_row()

    tab_stock, tab_registrar, tab_mermas, tab_historial = st.tabs([
        "Stock actual",
        "Registrar insumo / compra",
        "Mermas y movimientos",
        "Historial",
    ])

    with tab_stock:
        _tab_stock_actual()
    with tab_registrar:
        _tab_registrar_insumo()
    with tab_mermas:
        _tab_mermas()
    with tab_historial:
        _tab_historial()


def _kpi_row():
    row = execute_query("""
        SELECT COUNT(*) AS total_insumos,
               COALESCE(SUM(CASE WHEN stock_actual <= stock_minimo THEN 1 ELSE 0 END), 0) AS stock_bajo,
               COALESCE(SUM(stock_actual), 0) AS unidades_totales
        FROM insumos
    """, fetch=True)
    data = row[0] if row else {"total_insumos": 0, "stock_bajo": 0, "unidades_totales": 0}
    c1, c2, c3 = st.columns(3)
    c1.metric("Insumos", int(data["total_insumos"]))
    c2.metric("Stock bajo", int(data["stock_bajo"]), delta_color="inverse")
    c3.metric("Unidades totales", f"{float(data['unidades_totales']):.0f}")


def _tab_stock_actual():
    insumos = execute_query("""
        SELECT id_insumo, nombre, stock_actual, stock_minimo, unidad_medida
        FROM insumos ORDER BY nombre
    """, fetch=True) or []

    if not insumos:
        st.info("No hay insumos registrados.")
        return

    df = pd.DataFrame(insumos)

    def _bg_rojo(val):
        return "background-color:#fde8e8;color:#b33a34" if val else ""

    styled = df.style.apply(
        lambda r: [_bg_rojo(r["stock_actual"] <= r["stock_minimo"])] * len(r),
        axis=1,
    )

    edited = st.data_editor(
        styled,
        hide_index=True,
        use_container_width=True,
        disabled=["id_insumo", "nombre", "unidad_medida"],
        column_config={
            "id_insumo": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "nombre": st.column_config.TextColumn("Insumo", disabled=True),
            "stock_actual": st.column_config.NumberColumn("Stock actual", min_value=0, step=1),
            "stock_minimo": st.column_config.NumberColumn("Stock minimo", min_value=0, step=1),
            "unidad_medida": st.column_config.TextColumn("Unidad", disabled=True, width="small"),
        },
    )

    if st.button("Guardar ajustes de stock", type="primary", use_container_width=True):
        conn = get_connection()
        try:
            for _, r in edited.iterrows():
                conn.execute("""
                    UPDATE insumos SET stock_actual = ?, stock_minimo = ?
                    WHERE id_insumo = ?
                """, (float(r["stock_actual"]), float(r["stock_minimo"]), int(r["id_insumo"])))
            conn.commit()
            registrar_auditoria("inventario", "ajuste_masivo", f"{len(edited)} insumos")
            st.toast("Inventario actualizado")
            st.rerun()
        except Exception as e:
            st.error(str(e))
        finally:
            conn.close()


def _tab_registrar_insumo():
    with st.form("form_nuevo_insumo", clear_on_submit=True):
        st.subheader("Nuevo insumo")
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre del insumo*")
        unidad = c2.selectbox("Unidad de medida", ["unidad", "kg", "litro", "gramo", "cc", "mililitro", "paquete"])
        c3, c4 = st.columns(2)
        stock_inicial = c3.number_input("Stock actual", min_value=0.0, step=1.0)
        stock_min = c4.number_input("Stock minimo", min_value=0.0, step=1.0)

        proveedores = execute_query("SELECT id_proveedor, nombre FROM proveedores WHERE activo = 1 ORDER BY nombre", fetch=True) or []
        proveedor_id = None
        if proveedores:
            proveedor_opts = {p["nombre"]: p["id_proveedor"] for p in proveedores}
            prov_sel = st.selectbox("Proveedor asociado (opcional)", ["Ninguno"] + list(proveedor_opts.keys()))
            if prov_sel != "Ninguno":
                proveedor_id = proveedor_opts[prov_sel]

        if st.form_submit_button("Guardar insumo", type="primary", use_container_width=True):
            if not nombre or not nombre.strip():
                st.error("El nombre es obligatorio.")
            else:
                _insertar_insumo(nombre.strip(), stock_inicial, stock_min, unidad, proveedor_id)
                st.toast("Insumo registrado correctamente")
                st.rerun()


def _insertar_insumo(nombre: str, stock: float, stock_min: float, unidad: str, id_proveedor: int | None):
    ph = "%s" if get_db_type() == "postgres" else "?"
    execute_query(f"""
        INSERT INTO insumos (nombre, stock_actual, stock_minimo, unidad_medida)
        VALUES ({ph}, {ph}, {ph}, {ph})
    """, (nombre, stock, stock_min, unidad))
    registrar_auditoria("inventario", "insumo_creado", nombre)


def _tab_mermas():
    insumos = execute_query("SELECT id_insumo, nombre, stock_actual, unidad_medida FROM insumos ORDER BY nombre", fetch=True) or []
    if not insumos:
        st.info("No hay insumos para registrar movimientos.")
        return

    with st.form("form_merma", clear_on_submit=True):
        st.subheader("Registrar merma o movimiento")
        insumo_opts = {f"{i['nombre']} ({i['stock_actual']:.0f} {i['unidad_medida']})": i["id_insumo"] for i in insumos}
        insumo_sel = st.selectbox("Insumo", list(insumo_opts.keys()))
        c1, c2 = st.columns(2)
        tipo = c1.selectbox("Tipo de movimiento", ["ajuste_salida", "merma", "ajuste_entrada", "compra"])
        cantidad = c2.number_input("Cantidad", min_value=0.01, step=1.0)
        motivo = st.selectbox("Motivo",
                              ["Vencimiento", "Rotura", "Consumo interno", "Ajuste de inventario", "Compra", "Otro"])
        descripcion = st.text_input("Descripcion (opcional)", placeholder="Detalle del movimiento")

        if st.form_submit_button("Registrar movimiento", type="primary", use_container_width=True):
            id_insumo = insumo_opts[insumo_sel]
            es_salida = tipo in ("ajuste_salida", "merma")
            texto = descripcion.strip() or f"{motivo} - {tipo}"
            ok, msg = _registrar_movimiento(id_insumo, tipo, cantidad, texto)
            if ok:
                st.toast("Movimiento registrado correctamente")
                st.rerun()
            else:
                st.error(msg)


def _registrar_movimiento(id_insumo: int, tipo: str, cantidad: float, descripcion: str) -> tuple:
    ph = "%s" if get_db_type() == "postgres" else "?"
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        insumo = conn.execute(f"SELECT id_insumo, nombre, stock_actual, unidad_medida FROM insumos WHERE id_insumo = {ph}", (id_insumo,)).fetchone()
        if not insumo:
            conn.execute("ROLLBACK")
            return False, "El insumo no existe."

        es_salida = tipo in ("ajuste_salida", "merma", "descuento_receta")
        stock_anterior = float(insumo["stock_actual"])
        if es_salida and stock_anterior < cantidad:
            conn.execute("ROLLBACK")
            return False, f"Stock insuficiente en '{insumo['nombre']}'. Tiene {stock_anterior:.0f} {insumo['unidad_medida']}, necesita {cantidad:.0f}."

        stock_nuevo = stock_anterior - cantidad if es_salida else stock_anterior + cantidad
        conn.execute(f"UPDATE insumos SET stock_actual = stock_actual {'-' if es_salida else '+'} {ph} WHERE id_insumo = {ph}", (cantidad, id_insumo))
        conn.execute(f"""INSERT INTO movimientos_stock (id_insumo, tipo_movimiento, cantidad, stock_anterior, stock_nuevo, descripcion)
                        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})""",
                     (id_insumo, tipo, cantidad, stock_anterior, stock_nuevo, descripcion))
        conn.execute("COMMIT")
        registrar_auditoria("inventario", f"movimiento_{tipo}", f"{insumo['nombre']}: {stock_anterior:.0f} -> {stock_nuevo:.0f}")
        return True, f"{insumo['nombre']}: {stock_anterior:.0f} -> {stock_nuevo:.0f}"
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"Error en movimiento: {e}")
        return False, "Error interno al registrar movimiento."


def _tab_historial():
    hist = pd.DataFrame(historial_stock(200))
    if hist.empty:
        st.info("Sin movimientos de stock.")
    else:
        st.dataframe(hist, hide_index=True, use_container_width=True)
        csv = hist.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Descargar movimientos.csv", csv, file_name="movimientos_stock.csv",
                           mime="text/csv", use_container_width=True)
