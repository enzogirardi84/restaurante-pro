"""
api.py — API REST ligera para COMANDAPRO ERP.
Corre en un proceso separado del Streamlit (puerto 8000).
Instalación: pip install fastapi uvicorn
Ejecución:   uvicorn api:app --reload --port 8000
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from database import get_connection_direct, sql_date, ph, last_id

app = FastAPI(title="COMANDAPRO ERP API", version="2.0")


# ── Modelos ───────────────────────────────────────────────────────────

class PedidoCreate(BaseModel):
    id_mesa: int
    id_usuario: int = 1
    items: list[dict]  # [{"id_producto": 1, "cantidad": 2, "observaciones": ""}]


# ── Endpoints ─────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"app": "COMANDAPRO ERP API", "version": "2.0"}


@app.get("/api/mesas")
def listar_mesas(estado: Optional[str] = None):
    """Lista mesas. Filtro opcional: ?estado=libre|ocupada|esperando_cuenta"""
    conn = get_connection_direct()
    try:
        if estado:
            cur = conn.execute(
                "SELECT id_mesa, numero_mesa, estado FROM mesas WHERE estado=? ORDER BY numero_mesa",
                (estado,)
            )
        else:
            cur = conn.execute(
                "SELECT id_mesa, numero_mesa, estado FROM mesas ORDER BY numero_mesa"
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/productos")
def listar_productos(categoria: Optional[str] = None):
    """Lista productos del menú. Filtro opcional: ?categoria=cocina|bebidas|postres"""
    conn = get_connection_direct()
    try:
        if categoria:
            cur = conn.execute(
                "SELECT id_producto, nombre, precio_venta, categoria, activo, url_imagen"
                " FROM productos_menu WHERE categoria=? AND activo=1 ORDER BY nombre",
                (categoria,)
            )
        else:
            cur = conn.execute(
                "SELECT id_producto, nombre, precio_venta, categoria, activo, url_imagen"
                " FROM productos_menu WHERE activo=1 ORDER BY categoria, nombre"
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/pedidos")
def listar_pedidos(estado: Optional[str] = None, mesa: Optional[int] = None):
    """Lista pedidos. Filtros: ?estado=pendiente|cobrado&mesa=3"""
    conn = get_connection_direct()
    try:
        sql = """
            SELECT pc.id_pedido, pc.id_mesa, m.numero_mesa,
                   pc.fecha_hora, pc.estado_comanda,
                   u.nombre || ' ' || u.apellido AS mozo
            FROM pedidos_cabecera pc
            JOIN mesas m ON m.id_mesa = pc.id_mesa
            JOIN usuarios u ON u.id_usuario = pc.id_usuario
            WHERE 1=1
        """
        params = []
        if estado:
            sql += " AND pc.estado_comanda=?"
            params.append(estado)
        if mesa:
            sql += " AND pc.id_mesa=?"
            params.append(mesa)
        sql += " ORDER BY pc.fecha_hora DESC"

        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/pedidos/{id_pedido}")
def detalle_pedido(id_pedido: int):
    """Detalle completo de un pedido con sus renglones."""
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            "SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda,"
            " m.numero_mesa, u.nombre || ' ' || u.apellido AS mozo"
            " FROM pedidos_cabecera pc"
            " JOIN mesas m ON m.id_mesa = pc.id_mesa"
            " JOIN usuarios u ON u.id_usuario = pc.id_usuario"
            " WHERE pc.id_pedido=?",
            (id_pedido,)
        )
        cabecera = cur.fetchone()
        if not cabecera:
            raise HTTPException(404, "Pedido no encontrado")

        cur = conn.execute(
            "SELECT pd.id_detalle, pm.nombre AS producto, pd.cantidad,"
            " pd.precio_unitario_facturado, pd.observaciones"
            " FROM pedido_detalle pd"
            " JOIN productos_menu pm ON pm.id_producto = pd.id_producto"
            " WHERE pd.id_pedido=?",
            (id_pedido,)
        )
        return {"pedido": dict(cabecera), "detalle": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()


@app.get("/api/ventas/hoy")
def ventas_hoy():
    """Resumen de ventas del día actual."""
    conn = get_connection_direct()
    try:
        cur = conn.execute(f"""
            SELECT COUNT(DISTINCT pc.id_pedido) AS pedidos,
                   COALESCE(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total,
                   COUNT(DISTINCT pc.id_mesa) AS mesas
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            WHERE pc.estado_comanda = 'cobrado'
              AND {sql_date('pc.fecha_hora')} = {sql_date("'now', 'localtime'")}
        """)
        row = cur.fetchone()
        return dict(row) if row else {"pedidos": 0, "total": 0, "mesas": 0}
    finally:
        conn.close()


@app.get("/api/ventas/semana")
def ventas_semana():
    """Ventas diarias de los últimos 7 días."""
    conn = get_connection_direct()
    try:
        cur = conn.execute(f"""
            SELECT {sql_date('pc.fecha_hora')} AS dia,
                   ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total
            FROM pedidos_cabecera pc
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            WHERE pc.estado_comanda = 'cobrado'
              AND pc.fecha_hora >= {sql_date("'now', '-7 days', 'localtime'")}
            GROUP BY dia
            ORDER BY dia
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/insumos/criticos")
def insumos_criticos():
    """Insumos con stock por debajo del mínimo."""
    conn = get_connection_direct()
    try:
        cur = conn.execute("""
            SELECT i.nombre, i.stock_actual, i.stock_minimo, i.unidad_medida,
                   d.nombre_deposito AS deposito
            FROM stock_deposito sd
            JOIN insumos i ON i.id_insumo = sd.id_insumo
            JOIN depositos d ON d.id_deposito = sd.id_deposito
            WHERE sd.cantidad_disponible <= i.stock_minimo
            ORDER BY (i.stock_minimo - sd.cantidad_disponible) DESC
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.post("/api/pedidos")
def crear_pedido(pedido: PedidoCreate):
    """Crea un pedido completo (cabecera + detalle)."""
    conn = get_connection_direct()
    try:
        conn.execute("BEGIN")
        cur = conn.execute(
            f"INSERT INTO pedidos_cabecera (id_mesa, id_usuario) VALUES ({ph()},{ph()})"
            + (" RETURNING id_pedido" if "postgresql" in str(type(conn)) else ""),
            (pedido.id_mesa, pedido.id_usuario)
        )
        id_pedido = last_id(conn, cur)

        for item in pedido.items:
            conn.execute(
                "INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, observaciones)"
                " VALUES (?,?,?,?)",
                (id_pedido, item["id_producto"], item["cantidad"],
                 item.get("observaciones", ""))
            )

        conn.execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=?",
                     (pedido.id_mesa,))
        conn.commit()
        return {"ok": True, "id_pedido": id_pedido}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@app.get("/api/stock")
def stock_actual():
    """Stock actual por depósito."""
    conn = get_connection_direct()
    try:
        cur = conn.execute("""
            SELECT i.nombre AS insumo, i.stock_actual, i.stock_minimo,
                   sd.cantidad_disponible, d.nombre_deposito AS deposito,
                   i.unidad_medida
            FROM stock_deposito sd
            JOIN insumos i ON i.id_insumo = sd.id_insumo
            JOIN depositos d ON d.id_deposito = sd.id_deposito
            ORDER BY d.nombre_deposito, i.nombre
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
