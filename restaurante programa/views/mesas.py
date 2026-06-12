"""
mesas.py — Gestion de mesas con grid visual interactivo.
Cards con estados, alertas pulsantes y acciones rapidas.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components.css import title
from components.helpers import (
    anular_detalle, detalle_mesa_renglones, execute, get_mesas, money,
    liberar_mesa_sin_cobro, registrar_auditoria, rows,
)


def _render_mesa_grid(mesas: list[dict]) -> None:
    """Renderiza mesas en grid responsivo con cards con estado."""
    cols_per_row = 6
    for i in range(0, len(mesas), cols_per_row):
        cols = st.columns(cols_per_row, gap="small")
        for col, mesa in zip(cols, mesas[i:i + cols_per_row]):
            estado = mesa["estado"]
            estado_label = {"libre": "Libre", "ocupada": "Ocupada", "esperando_cuenta": "En cuenta"}.get(estado, estado)
            urgente_class = " table-urgent" if estado == "esperando_cuenta" else ""
            accent = {"libre": "#8f8a82", "ocupada": "#2563a0", "esperando_cuenta": "#c47f1a"}.get(estado, "#8f8a82")

            with col:
                st.markdown(
                    f"""
                    <div class="table-card{urgente_class}" style="border-left-color:{accent}">
                        <div class="table-card-num">Mesa {mesa['numero_mesa']}</div>
                        <div class="table-card-meta">
                            <span>{estado_label}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if estado == "libre":
                    if st.button("Ocupar", key=f"occ_{mesa['id_mesa']}", use_container_width=True):
                        execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=?", (mesa["id_mesa"],))
                        registrar_auditoria("mesas", "ocupar", str(mesa["numero_mesa"]))
                        st.rerun()
                elif estado == "ocupada":
                    if st.button("Pedir cuenta", key=f"bill_{mesa['id_mesa']}", use_container_width=True):
                        execute("UPDATE mesas SET estado='esperando_cuenta' WHERE id_mesa=?", (mesa["id_mesa"],))
                        registrar_auditoria("mesas", "cuenta", str(mesa["numero_mesa"]))
                        st.rerun()
                else:
                    if st.button("Liberar", key=f"free_{mesa['id_mesa']}", type="primary", use_container_width=True):
                        res = liberar_mesa_sin_cobro(mesa["id_mesa"], f"Mesa {mesa['numero_mesa']} liberada desde modulo Mesas")
                        if res["ok"]:
                            registrar_auditoria("mesas", "liberar", str(mesa["numero_mesa"]))
                            st.rerun()
                        st.error(res["error"])


def page_mesas() -> None:
    title("Gestion de mesas",
          "Grid visual del salon. Las cards en \"En cuenta\" pulsen para alertar.")

    mesas = get_mesas()
    if not mesas:
        st.info("No hay mesas cargadas. Agregalas abajo.")
    else:
        libres = sum(1 for m in mesas if m["estado"] == "libre")
        ocupadas = sum(1 for m in mesas if m["estado"] == "ocupada")
        en_cuenta = sum(1 for m in mesas if m["estado"] == "esperando_cuenta")

        kpi_cols = st.columns(4)
        kpi_cols[0].metric("Totales", len(mesas))
        kpi_cols[1].metric("Libres", libres)
        kpi_cols[2].metric("Ocupadas", ocupadas)
        kpi_cols[3].metric("En cuenta", en_cuenta)

        with st.expander("Filtrar por estado", expanded=False):
            filtro = st.radio("Estado", ["Todas", "Libres", "Ocupadas", "En cuenta"],
                              horizontal=True, label_visibility="collapsed")
            if filtro == "Libres":
                mesas = [m for m in mesas if m["estado"] == "libre"]
            elif filtro == "Ocupadas":
                mesas = [m for m in mesas if m["estado"] == "ocupada"]
            elif filtro == "En cuenta":
                mesas = [m for m in mesas if m["estado"] == "esperando_cuenta"]

        st.subheader("Salon")
        _render_mesa_grid(mesas)

    st.divider()
    st.subheader("Administracion")

    with st.expander("Agregar / mover / cambiar estado", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            nueva = st.number_input("Nueva mesa numero", min_value=1, step=1, key="nueva_mesa")
            if st.button("Agregar mesa", use_container_width=True):
                try:
                    execute("INSERT INTO mesas (numero_mesa, estado) VALUES (?, 'libre')", (int(nueva),))
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        with c2:
            origen = st.selectbox("Mesa origen", mesas, format_func=lambda m: f"Mesa {m['numero_mesa']}", key="mesa_origen")
            destino = st.selectbox("Mesa destino", mesas, format_func=lambda m: f"Mesa {m['numero_mesa']}", key="mesa_destino")
            origen_valido = isinstance(origen, dict) and "id_mesa" in origen
            destino_valido = isinstance(destino, dict) and "id_mesa" in destino
            btn_deshabilitado = not (origen_valido and destino_valido) or (origen_valido and destino_valido and origen["id_mesa"] == destino["id_mesa"])
            if st.button("Mover / unir consumos", use_container_width=True, disabled=btn_deshabilitado):
                execute("UPDATE pedidos_cabecera SET id_mesa=? WHERE id_mesa=? AND estado_comanda IN ('pendiente','en_cocina','listo','entregado')",
                        (destino["id_mesa"], origen["id_mesa"]))
                execute("UPDATE mesas SET estado='libre' WHERE id_mesa=?", (origen["id_mesa"],))
                execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=?", (destino["id_mesa"],))
                registrar_auditoria("mesas", "mover_unir", f"{origen['numero_mesa']} -> {destino['numero_mesa']}")
                st.toast("Consumos movidos correctamente")
                st.rerun()
        with c3:
            mesa_accion = st.selectbox("Accion sobre mesa", mesas, format_func=lambda m: f"Mesa {m['numero_mesa']}", key="mesa_accion")
            estado = st.selectbox("Nuevo estado", ["libre", "ocupada", "esperando_cuenta"])
            if st.button("Cambiar estado", use_container_width=True):
                if estado == "libre":
                    res = liberar_mesa_sin_cobro(mesa_accion["id_mesa"], f"Mesa {mesa_accion['numero_mesa']} cambio manual a libre")
                    if not res["ok"]:
                        st.error(res["error"])
                        return
                else:
                    execute("UPDATE mesas SET estado=? WHERE id_mesa=?", (estado, mesa_accion["id_mesa"]))
                registrar_auditoria("mesas", "cambio_estado", f"{mesa_accion['numero_mesa']} {estado}")
                st.rerun()

    st.divider()
    st.subheader("Historial y anulaciones")

    with st.expander("Historial por mesa"):
        mesa_hist = st.selectbox("Mesa", mesas, format_func=lambda m: f"Mesa {m['numero_mesa']}", key="mesa_historial")
        historial = pd.DataFrame(rows("""
            SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda,
                   u.nombre || ' ' || u.apellido AS mozo,
                   pm.nombre AS producto, pd.cantidad,
                   COALESCE(pd.cantidad_cobrada,0) AS cobrada,
                   COALESCE(pd.cantidad_anulada,0) AS anulada,
                   COALESCE(pd.motivo_anulacion,'') AS motivo
            FROM pedidos_cabecera pc
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.id_mesa = ?
            ORDER BY pc.fecha_hora DESC, pd.id_detalle
            LIMIT 80
        """, (mesa_hist["id_mesa"],)))
        if not historial.empty:
            st.dataframe(historial, hide_index=True, use_container_width=True)
        else:
            st.info("Sin historial para esta mesa.")

    with st.expander("Anular producto pendiente"):
        pendientes = detalle_mesa_renglones(mesa_hist["id_mesa"])
        if pendientes:
            renglon = st.selectbox("Producto", pendientes,
                                   format_func=lambda r: f"Pedido #{r['id_pedido']} - {r['nombre']} - pendiente {r['pendiente']}")
            cantidad = st.number_input("Cantidad", min_value=1, max_value=int(renglon["pendiente"]), value=1)
            motivo = st.text_input("Motivo", placeholder="Error de carga, cliente cancela...")
            if st.button("Anular", type="primary", use_container_width=True):
                res = anular_detalle(renglon["id_detalle"], int(cantidad), motivo.strip() or "Sin motivo")
                if res["ok"]:
                    registrar_auditoria("mesas", "anulacion", f"{res['producto']} x{cantidad} mesa {mesa_hist['numero_mesa']}")
                    st.success("Anulado.")
                    st.rerun()
                st.error(res["error"])
        else:
            st.info("Sin pendientes para anular.")
