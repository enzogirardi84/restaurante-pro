"""
views/menu.py — ABM de productos del menu con formulario protegido,
data editor reactivo y retroalimentacion limpia via st.toart.
Sin dependencia directa de la logica de negocio.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from database import execute_query, get_connection, registrar_auditoria
from components.helpers import money as fmt_money


def get_menu(active_only: bool = True) -> list[dict]:
    where = "WHERE activo = 1" if active_only else ""
    return execute_query(f"""
        SELECT id_producto, nombre, precio_venta, categoria, activo
        FROM productos_menu
        {where}
        ORDER BY categoria, nombre
    """, fetch=True) or []


def page_menu() -> None:
    from components.css import title

    title("Administracion de menu", "Crear productos, cambiar precios y activar o pausar platos.")

    # ── Promocion automatica ──────────────────────────────────────────
    _seccion_promocion()

    tab_nuevo, tab_existentes = st.tabs(["Nuevo producto", "Productos existentes"])

    with tab_nuevo:
        _formulario_nuevo_producto()

    with tab_existentes:
        _editor_productos()


def _seccion_promocion():
    with st.expander("Promocion automatica por categoria", expanded=False):
        promo = _promo_config()
        with st.form("promo_automatica"):
            c1, c2, c3, c4 = st.columns(4)
            activa = c1.checkbox("Activa", value=promo["activa"])
            categoria = c2.selectbox(
                "Categoria",
                ["cocina", "bebidas", "postres"],
                index=["cocina", "bebidas", "postres"].index(promo["categoria"])
                if promo["categoria"] in ["cocina", "bebidas", "postres"] else 0,
            )
            umbral = c3.number_input("Umbral", min_value=0.0, value=float(promo["umbral"]), step=500.0)
            descuento_pct = c4.number_input("Descuento %", min_value=0.0, max_value=95.0,
                                            value=float(promo["descuento"] * 100), step=1.0)
            ejemplo = _calcular_ejemplo_promo(activa, umbral, descuento_pct)
            st.caption(f"Ejemplo: producto de {fmt_money(umbral + 1000)} queda en {fmt_money(ejemplo)} si supera el umbral.")
            if st.form_submit_button("Guardar promocion", type="primary"):
                _guardar_promo(activa, categoria, umbral, descuento_pct)
                st.toast("Promocion actualizada")
                st.rerun()


def _promo_config() -> dict:
    from components.helpers import get_config
    return {
        "activa": get_config("promo_activa") == "1",
        "categoria": get_config("promo_categoria") or "cocina",
        "umbral": float(get_config("promo_umbral") or 0),
        "descuento": float(get_config("promo_descuento") or 0),
    }


def _calcular_ejemplo_promo(activa: bool, umbral: float, pct: float) -> float:
    base = umbral + 1000
    if activa and base > umbral:
        return round(base * (1 - pct / 100))
    return base


def _guardar_promo(activa: bool, categoria: str, umbral: float, pct: float):
    from components.helpers import set_config
    set_config("promo_activa", "1" if activa else "0")
    set_config("promo_categoria", categoria)
    set_config("promo_umbral", str(umbral))
    set_config("promo_descuento", str(pct / 100))
    registrar_auditoria("menu", "promo_actualizada", f"{categoria} > {fmt_money(umbral)} - {pct}%")


def _formulario_nuevo_producto():
    with st.form(key="form_alta_menu_patron", clear_on_submit=True):
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre del plato / bebida")
        precio = c1.number_input("Precio de venta", min_value=0.0, step=100.0, format="%.2f")
        categoria = c2.selectbox("Categoria", ["cocina", "bebidas", "postres"])
        activo = c2.checkbox("Activo", value=True)
        guardado = st.form_submit_button("Guardar producto", type="primary", use_container_width=True)
        if guardado:
            nombre = (nombre or "").strip()
            if not nombre:
                st.error("El nombre es obligatorio.")
            elif precio <= 0:
                st.error("El precio debe ser mayor a cero.")
            else:
                _insertar_producto(nombre, precio, categoria, activo)
                st.toast("Producto guardado correctamente")
                st.rerun()


def _insertar_producto(nombre: str, precio: float, categoria: str, activo: bool):
    from database import execute
    execute("""
        INSERT INTO productos_menu (nombre, precio_venta, categoria, activo)
        VALUES (?, ?, ?, ?)
    """, (nombre, precio, categoria, 1 if activo else 0))
    registrar_auditoria("menu", "producto_creado", nombre)


def _editor_productos():
    df = pd.DataFrame(get_menu(active_only=False))
    if df.empty:
        st.info("No hay productos cargados.")
        return

    edited = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        disabled=["id_producto"],
        column_config={
            "id_producto": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "nombre": st.column_config.TextColumn("Nombre", required=True, width="large"),
            "precio_venta": st.column_config.NumberColumn("Precio $", min_value=0, step=100, format="$%.0f"),
            "categoria": st.column_config.SelectboxColumn("Categoria", options=["cocina", "bebidas", "postres"]),
            "activo": st.column_config.CheckboxColumn("Activo"),
        },
    )

    col_save, col_status = st.columns([1, 3])
    with col_save:
        if st.button("Guardar cambios", type="primary", use_container_width=True):
            _actualizar_productos(edited)
            st.toast("Menu actualizado correctamente")
            st.rerun()
    with col_status:
        activos = df["activo"].sum() if "activo" in df.columns else len(df)
        st.caption(f"{len(df)} productos ({int(activos)} activos, {len(df) - int(activos)} pausados)")


def _actualizar_productos(df: pd.DataFrame):
    conn = get_connection()
    try:
        for _, row in df.iterrows():
            conn.execute("""
                UPDATE productos_menu
                   SET nombre = ?, precio_venta = ?, categoria = ?, activo = ?
                 WHERE id_producto = ?
            """, (row["nombre"], float(row["precio_venta"]), row["categoria"],
                  int(row["activo"]), int(row["id_producto"])))
        conn.commit()
        registrar_auditoria("menu", "productos_actualizados", str(len(df)))
    except Exception as e:
        st.error(f"Error al guardar: {e}")
    finally:
        conn.close()
