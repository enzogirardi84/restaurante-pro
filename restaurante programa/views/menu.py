"""
views/menu.py — ABM de productos del menu con soporte Supabase.
Lee y escribe en Supabase (productos_menu) cuando las credenciales
están disponibles; cae a SQLite si no hay conexión cloud.
"""
from __future__ import annotations

import os
import pandas as pd
import streamlit as st

from database import execute_query, get_connection, registrar_auditoria
from components.helpers import money as fmt_money, receta_producto, rows
from components.categorias import CATEGORIAS_TOTAL, CATEGORIAS_MENU


# ── Cliente Supabase (opcional) ───────────────────────────────────────

def _get_supabase():
    """Retorna cliente supabase-py o None si no está configurado."""
    try:
        from supabase import create_client
        from cloud_config import supabase_url, get_secret
        url = supabase_url()
        key = get_secret("SUPABASE_SERVICE_ROLE_KEY") or get_secret("SUPABASE_ANON_KEY")
        if url and key:
            return create_client(url, key)
    except Exception:
        pass
    return None


def _usando_supabase() -> bool:
    return _get_supabase() is not None


# ── Lectura del menú ───────────────────────────────────────────────────

def get_menu(active_only: bool = True) -> list[dict]:
    """
    Trae productos_menu desde Supabase si está disponible,
    sino desde SQLite local.
    """
    sb = _get_supabase()
    if sb:
        try:
            query = sb.table("productos_menu").select(
                "id_producto, nombre, precio_venta, categoria, activo, precio_original, precio_final, descuento_aplicado"
            )
            if active_only:
                query = query.eq("activo", True)
            resp = query.order("categoria").order("nombre").execute()
            return resp.data or []
        except Exception as e:
            st.warning(f"\u26a0\ufe0f Supabase no disponible, usando datos locales. ({e})")

    # Fallback SQLite
    where = "WHERE activo = 1" if active_only else ""
    return execute_query(f"""
        SELECT id_producto, nombre, precio_venta, categoria, activo
        FROM productos_menu
        {where}
        ORDER BY categoria, nombre
    """, fetch=True) or []


# ── Insertar producto ──────────────────────────────────────────────────

def _insertar_producto(nombre: str, precio: float, categoria: str, activo: bool):
    sb = _get_supabase()
    if sb:
        try:
            sb.table("productos_menu").insert({
                "nombre": nombre,
                "precio_venta": precio,
                "categoria": categoria,
                "activo": activo,
                "precio_original": precio,
                "precio_final": precio,
                "descuento_aplicado": 0,
            }).execute()
            registrar_auditoria("menu", "producto_creado_supabase", nombre)
            return
        except Exception as e:
            st.error(f"Error al insertar en Supabase: {e}")
            return

    # Fallback SQLite
    from database import execute
    execute("""
        INSERT INTO productos_menu (nombre, precio_venta, categoria, activo)
        VALUES (?, ?, ?, ?)
    """, (nombre, precio, categoria, 1 if activo else 0))
    registrar_auditoria("menu", "producto_creado", nombre)


# ── Actualizar productos ───────────────────────────────────────────────

def _actualizar_productos(df: pd.DataFrame):
    sb = _get_supabase()
    if sb:
        errores = []
        for _, row in df.iterrows():
            try:
                sb.table("productos_menu").update({
                    "nombre": row["nombre"],
                    "precio_venta": float(row["precio_venta"]),
                    "categoria": row["categoria"],
                    "activo": bool(row["activo"]),
                    "precio_original": float(row.get("precio_original", row["precio_venta"])),
                    "precio_final": float(row.get("precio_final", row["precio_venta"])),
                    "descuento_aplicado": int(row.get("descuento_aplicado", 0)),
                }).eq("id_producto", int(row["id_producto"])).execute()
            except Exception as e:
                errores.append(str(e))
        if errores:
            st.error(f"Errores al guardar en Supabase: {'; '.join(errores)}")
        else:
            registrar_auditoria("menu", "productos_actualizados_supabase", str(len(df)))
        return

    # Fallback SQLite
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


# ── Página principal ───────────────────────────────────────────────────

def page_menu() -> None:
    from components.css import title

    title("Administracion de menu", "Crear productos, cambiar precios y activar o pausar platos.")

    if _usando_supabase():
        st.success("\U0001f7e2 Conectado a Supabase — los cambios se reflejan en la nube", icon="\u2601\ufe0f")
    else:
        st.info("\U0001f7e1 Modo local (SQLite) — configur\u00e1 SUPABASE_URL y SUPABASE_ANON_KEY para sincronizar", icon="\U0001f4be")

    _seccion_promocion()

    tab_nuevo, tab_existentes = st.tabs(["Nuevo producto", "Productos existentes"])

    with tab_nuevo:
        _formulario_nuevo_producto()

    with tab_existentes:
        _editor_productos()


# ── Formulario nuevo producto ──────────────────────────────────────────

def _formulario_nuevo_producto():
    with st.form(key="form_alta_menu_patron", clear_on_submit=True):
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre del plato / bebida")
        precio = c1.number_input("Precio de venta", min_value=0.0, step=100.0, format="%.2f")
        categoria = c2.selectbox("Categoria", CATEGORIAS_TOTAL)
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


# ── Editor de productos existentes ────────────────────────────────────

def _editor_productos():
    col_refresh, _ = st.columns([1, 5])
    with col_refresh:
        if st.button("Sincronizar / Refrescar tabla", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    productos = get_menu(active_only=False)
    df = pd.DataFrame(productos)
    if df.empty:
        st.info("No hay productos cargados.")
        return

    cols_base = ["id_producto", "nombre", "precio_venta", "categoria", "activo"]
    cols_extra = ["precio_original", "precio_final", "descuento_aplicado"]
    cols_show = cols_base + [c for c in cols_extra if c in df.columns]
    df = df[cols_show]

    column_config = {
        "id_producto":        st.column_config.NumberColumn("ID", disabled=True, width="small"),
        "nombre":             st.column_config.TextColumn("Nombre", required=True, width="large"),
        "precio_venta":       st.column_config.NumberColumn("Precio $", min_value=0, step=100, format="$%.0f"),
        "categoria":          st.column_config.SelectboxColumn("Categoria", options=CATEGORIAS_TOTAL),
        "activo":             st.column_config.CheckboxColumn("Activo"),
        "precio_original":    st.column_config.NumberColumn("Precio original", format="$%.0f"),
        "precio_final":       st.column_config.NumberColumn("Precio final", format="$%.0f"),
        "descuento_aplicado": st.column_config.NumberColumn("Descuento %", format="%.0f%%"),
    }

    edited = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        disabled=["id_producto", "precio_original", "precio_final", "descuento_aplicado"],
        column_config=column_config,
    )

    col_save, col_status = st.columns([1, 3])
    with col_save:
        if st.button("Guardar cambios de menu", type="primary", use_container_width=True):
            _actualizar_productos(edited)
            st.toast("Menu actualizado correctamente")
            st.rerun()
    with col_status:
        activos = df["activo"].sum() if "activo" in df.columns else len(df)
        st.caption(f"{len(df)} productos ({int(activos)} activos, {len(df) - int(activos)} pausados)")

    st.divider()
    _panel_recetas()


# ── Promoción automática ───────────────────────────────────────────────

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


# ── Panel de recetas ───────────────────────────────────────────────────

def _panel_recetas():
    productos = get_menu(active_only=False)
    if not productos:
        return

    prod_opts = {f"{p['nombre']} (${p['precio_venta']:,.0f})": p["id_producto"] for p in productos}
    sel = st.selectbox("Seleccionar producto para ver su receta", list(prod_opts.keys()), key="prod_receta")
    if not sel:
        return

    id_prod = prod_opts[sel]
    receta = receta_producto(id_prod)

    with st.expander("Receta e insumos asociados", expanded=True):
        if receta:
            df_rec = pd.DataFrame(receta)
            df_rec["costo_total"] = 0.0
            st.dataframe(
                df_rec[["insumo", "cantidad_a_descontar", "unidad_medida", "stock_actual", "stock_minimo"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "insumo": "Insumo",
                    "cantidad_a_descontar": st.column_config.NumberColumn("Cantidad", format="%.1f"),
                    "unidad_medida": "Unidad",
                    "stock_actual": st.column_config.NumberColumn("Stock actual", format="%.0f"),
                    "stock_minimo": st.column_config.NumberColumn("Stock minimo", format="%.0f"),
                },
            )
            stock_bajo = [r for r in receta if float(r["stock_actual"]) <= float(r["stock_minimo"])]
            if stock_bajo:
                for r in stock_bajo:
                    st.warning(f"Stock bajo: {r['insumo']} ({float(r['stock_actual']):.0f} / {float(r['stock_minimo']):.0f})")
        else:
            st.info("Este producto no tiene insumos vinculados en su receta.")
            from components.helpers import rows as _rows
            insumos_disponibles = _rows("SELECT id_insumo, nombre, unidad_medida FROM insumos ORDER BY nombre")
            if insumos_disponibles:
                with st.form(key="vincular_insumo_receta", clear_on_submit=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    insumo_sel = c1.selectbox(
                        "Insumo", insumos_disponibles,
                        format_func=lambda i: f"{i['nombre']} ({i['unidad_medida']})",
                        key="insumo_receta_sel",
                    )
                    cantidad = c2.number_input("Cantidad a descontar", min_value=0.01, step=1.0, format="%.1f")
                    if c3.form_submit_button("Vincular", type="primary", use_container_width=True):
                        conn = get_connection()
                        try:
                            conn.execute("""
                                INSERT INTO recetas_escandallo (id_producto, id_insumo, cantidad_a_descontar)
                                VALUES (?, ?, ?)
                                ON CONFLICT(id_producto, id_insumo) DO UPDATE SET cantidad_a_descontar = ?
                            """, (id_prod, insumo_sel["id_insumo"], cantidad, cantidad))
                            conn.commit()
                            st.toast("Insumo vinculado a la receta")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                        finally:
                            conn.close()
            else:
                st.caption("No hay insumos en el inventario para vincular. Agrega insumos primero.")
