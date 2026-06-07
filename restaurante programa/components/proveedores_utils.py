"""Proveedores — CRUD completo, compras, pagos e historial."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.helpers import rows, one, execute, money, escape


def proveedores_activos() -> list[dict]:
    return rows("""
        SELECT id_proveedor, nombre, telefono, email, notas,
               cuit_rut, direccion, activo
        FROM proveedores
        WHERE activo = 1
        ORDER BY nombre
    """)


def todos_los_proveedores() -> list[dict]:
    return rows("""
        SELECT id_proveedor, nombre, telefono, email, notas,
               cuit_rut, direccion, activo
        FROM proveedores
        ORDER BY nombre
    """)


def buscar_proveedores(q: str) -> list[dict]:
    return rows("""
        SELECT id_proveedor, nombre, telefono, email, notas,
               cuit_rut, direccion, activo
        FROM proveedores
        WHERE nombre LIKE ? OR cuit_rut LIKE ? OR telefono LIKE ?
        ORDER BY nombre
    """, (f"%{q}%", f"%{q}%", f"%{q}%"))


def crear_proveedor(nombre: str, telefono: str = "", email: str = "",
                    notas: str = "", cuit_rut: str = "", direccion: str = "") -> dict:
    try:
        execute("""
            INSERT INTO proveedores (nombre, telefono, email, notas, cuit_rut, direccion)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (nombre.strip(), telefono.strip(), email.strip(), notas.strip(),
              cuit_rut.strip(), direccion.strip()))
        return {"ok": True, "nombre": nombre.strip()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def actualizar_proveedor(id_proveedor: int, **campos) -> dict:
    parts = []
    params = []
    for col, val in campos.items():
        if col in ("nombre", "telefono", "email", "notas", "cuit_rut", "direccion"):
            parts.append(f"{col} = ?")
            params.append(str(val).strip())
        elif col == "activo":
            parts.append("activo = ?")
            params.append(1 if val else 0)
    if not parts:
        return {"ok": False, "error": "sin_campos"}
    params.append(id_proveedor)
    try:
        execute(f"UPDATE proveedores SET {', '.join(parts)} WHERE id_proveedor = ?", tuple(params))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def eliminar_proveedor(id_proveedor: int) -> dict:
    try:
        execute("DELETE FROM proveedores WHERE id_proveedor = ?", (id_proveedor,))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Compras / historial ──────────────────────────────────────────────

def compras_por_proveedor(id_proveedor: int, limite: int = 200) -> pd.DataFrame:
    df = pd.DataFrame(rows("""
        SELECT ms.fecha_hora, i.nombre AS insumo,
               ms.cantidad, ms.stock_anterior, ms.stock_nuevo,
               ms.descripcion, u.nombre_usuario AS usuario
        FROM movimientos_stock ms
        JOIN insumos i ON i.id_insumo = ms.id_insumo
        LEFT JOIN usuarios u ON u.id_usuario = ms.id_usuario
        WHERE ms.id_proveedor = ?
          AND ms.tipo_movimiento = 'compra'
        ORDER BY ms.fecha_hora DESC
        LIMIT ?
    """, (id_proveedor, limite)))
    return df


def resumen_compras_por_proveedor() -> pd.DataFrame:
    df = pd.DataFrame(rows("""
        SELECT p.id_proveedor, p.nombre,
               COUNT(ms.id_movimiento_stock) AS compras,
               COALESCE(SUM(ms.cantidad * i.precio_compra), 0) AS total_gastado
        FROM proveedores p
        LEFT JOIN movimientos_stock ms ON ms.id_proveedor = p.id_proveedor
            AND ms.tipo_movimiento = 'compra'
        LEFT JOIN insumos i ON i.id_insumo = ms.id_insumo
        WHERE p.activo = 1
        GROUP BY p.id_proveedor, p.nombre
        ORDER BY total_gastado DESC
    """))
    return df


# ── Pagos a proveedores ────────────────────────────────────────────

def registrar_pago_proveedor(id_proveedor: int, monto: float,
                             descripcion: str = "") -> dict:
    try:
        execute("""
            INSERT INTO movimientos_caja
                (id_caja, tipo_movimiento, monto, descripcion)
            VALUES (?, 'egreso_proveedor', ?, ?)
        """, (_caja_activa_id(), monto, descripcion or f"Pago a proveedor #{id_proveedor}"))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _caja_activa_id() -> int | None:
    row = one("""
        SELECT id_caja FROM cajas_diarias
        WHERE fecha_cierre IS NULL
        ORDER BY fecha_apertura DESC LIMIT 1
    """)
    return row["id_caja"] if row else None


# ── UI ─────────────────────────────────────────────────────────────

def page_gestion_proveedores():
    st.subheader("Proveedores")

    tab_lista, tab_nuevo, tab_compras, tab_pagos = st.tabs(
        ["Lista", "Nuevo proveedor", "Compras por proveedor", "Pagos"]
    )

    with tab_lista:
        _render_lista()

    with tab_nuevo:
        _render_nuevo()

    with tab_compras:
        _render_compras()

    with tab_pagos:
        _render_pagos()


def _render_lista():
    proveedores = todos_los_proveedores()
    if not proveedores:
        st.info("No hay proveedores cargados.")
        return

    df = pd.DataFrame(proveedores)
    df["activo"] = df["activo"].astype(bool)

    editados = st.data_editor(
        df,
        column_config={
            "id_proveedor": st.column_config.NumberColumn("ID", disabled=True),
            "nombre": "Nombre",
            "cuit_rut": "CUIT/RUT",
            "telefono": "Teléfono",
            "email": "Email",
            "direccion": "Dirección",
            "notas": "Notas",
            "activo": st.column_config.CheckboxColumn("Activo"),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="editor_proveedores",
    )

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("Guardar cambios", type="primary", use_container_width=True):
            cambios = 0
            for _, row in editados.iterrows():
                orig = next(p for p in proveedores if p["id_proveedor"] == row["id_proveedor"])
                if any(str(orig.get(k)) != str(v) for k, v in row.items()):
                    r = actualizar_proveedor(
                        int(row["id_proveedor"]),
                        nombre=row["nombre"],
                        cuit_rut=row.get("cuit_rut", ""),
                        telefono=row.get("telefono", ""),
                        email=row.get("email", ""),
                        direccion=row.get("direccion", ""),
                        notas=row.get("notas", ""),
                        activo=row["activo"],
                    )
                    if r["ok"]:
                        cambios += 1
            if cambios:
                st.success(f"{cambios} proveedor(es) actualizado(s).")
                st.rerun()
            else:
                st.info("Sin cambios.")

    with col2:
        q = st.text_input("Buscar proveedor", placeholder="nombre, CUIT o teléfono...")
        if q:
            resultados = buscar_proveedores(q)
            if resultados:
                st.dataframe(pd.DataFrame(resultados), use_container_width=True, hide_index=True)
            else:
                st.info("Sin resultados.")


def _render_nuevo():
    with st.form("form_nuevo_proveedor", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        with col_a:
            nombre = st.text_input("Nombre*", placeholder="Razón social")
            cuit = st.text_input("CUIT/RUT", placeholder="30-12345678-9")
            telefono = st.text_input("Teléfono")
        with col_b:
            email = st.text_input("Email")
            direccion = st.text_input("Dirección")
            notas = st.text_area("Notas")

        if st.form_submit_button("Crear proveedor", type="primary", use_container_width=True):
            if not nombre.strip():
                st.error("El nombre es obligatorio.")
            else:
                r = crear_proveedor(nombre, telefono, email, notas, cuit, direccion)
                if r["ok"]:
                    st.success(f"Proveedor '{r['nombre']}' creado.")
                    st.rerun()
                else:
                    st.error(r["error"])


def _render_compras():
    proveedores = proveedores_activos()
    if not proveedores:
        st.info("No hay proveedores activos.")
        return

    opciones = {f"{p['nombre']}": p["id_proveedor"] for p in proveedores}
    seleccion = st.selectbox("Seleccionar proveedor", list(opciones.keys()), key="sel_comp_prov")
    id_prov = opciones[seleccion]

    compras = compras_por_proveedor(id_prov)
    if compras.empty:
        st.info("Sin compras registradas para este proveedor.")
    else:
        st.dataframe(compras, use_container_width=True, hide_index=True)
        total = compras["cantidad"].sum()
        st.caption(f"Total: {total:.2f} unidades registradas.")

    # Resumen general
    with st.expander("Resumen de compras por proveedor"):
        resumen = resumen_compras_por_proveedor()
        if not resumen.empty:
            resumen["total_gastado"] = resumen["total_gastado"].apply(money)
            st.dataframe(resumen, use_container_width=True, hide_index=True)


def _render_pagos():
    proveedores = proveedores_activos()
    if not proveedores:
        st.info("No hay proveedores activos.")
        return

    with st.form("form_pago_proveedor"):
        opciones = {f"{p['nombre']}": p["id_proveedor"] for p in proveedores}
        seleccion = st.selectbox("Proveedor", list(opciones.keys()))
        monto = st.number_input("Monto $", min_value=0.01, format="%.2f")
        descripcion = st.text_input("Descripción (opcional)", placeholder="Pago factura...")

        if st.form_submit_button("Registrar pago", type="primary", use_container_width=True):
            r = registrar_pago_proveedor(opciones[seleccion], monto, descripcion)
            if r["ok"]:
                st.success("Pago registrado en movimientos de caja.")
                st.rerun()
            else:
                st.error(r["error"])
