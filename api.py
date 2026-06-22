"""
api.py — API REST ligera para COMANDAPRO ERP.
Corre en un proceso separado del Streamlit (puerto 8000).
Instalación: pip install fastapi uvicorn
Ejecución:   uvicorn api:app --reload --port 8000
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime
from typing import Optional

import config
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import get_connection_direct, sql_date, ph, last_id

app = FastAPI(title="COMANDAPRO ERP API", version="2.0")

# ── CORS ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Modelos ──────────────────────────────────────────────────────────────
class PedidoCreate(BaseModel):
    id_mesa: int
    id_usuario: int = 1
    items: list[dict]

class LoginRequest(BaseModel):
    username: str
    password: str

class TerminalLoginRequest(BaseModel):
    terminal: str

# ── Auth Endpoints ──────────────────────────────────────────────────────────
@app.post("/auth/login")
def auth_login(req: LoginRequest):
    password_hash = hashlib.sha256(req.password.encode()).hexdigest()
    p = ph()
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            f"SELECT id_usuario, nombre, apellido, rol, username FROM usuarios WHERE username={p} AND password_hash={p}",
            (req.username, password_hash)
        )
        user = cur.fetchone()
    finally:
        conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return {"ok": True, "user": {"id_usuario": user["id_usuario"], "nombre": user["nombre"], "apellido": user["apellido"], "rol": user["rol"], "username": user["username"]}}

@app.post("/auth/terminal")
def auth_terminal(req: TerminalLoginRequest):
    role_map = {"mozo": "mozo", "cocina": "cocina", "caja": "administrador"}
    rol = role_map.get(req.terminal)
    if not rol:
        raise HTTPException(status_code=400, detail=f"Terminal inválido: {req.terminal}")
    p = ph()
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            f"SELECT id_usuario, nombre, apellido, rol, username FROM usuarios WHERE rol={p} LIMIT 1",
            (rol,)
        )
        user = cur.fetchone()
    finally:
        conn.close()
    if not user:
        raise HTTPException(status_code=404, detail=f"No hay usuario con rol '{rol}'")
    return {"ok": True, "user": {"id_usuario": user["id_usuario"], "nombre": user["nombre"], "apellido": user["apellido"], "rol": user["rol"], "username": user["username"]}}

@app.post("/auth/admin")
def auth_admin():
    p = ph()
    conn = get_connection_direct()
    try:
        cur = conn.execute(
            f"SELECT id_usuario, nombre, apellido, rol, username FROM usuarios WHERE rol={p} LIMIT 1",
            ("administrador",)
        )
        user = cur.fetchone()
    finally:
        conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="No hay usuario administrador")
    return {"ok": True, "user": {"id_usuario": user["id_usuario"], "nombre": user["nombre"], "apellido": user["apellido"], "rol": user["rol"], "username": user["username"]}}

# ── Endpoints ───────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"app": "COMANDAPRO ERP API", "version": "2.0"}

@app.get("/api/mesas")
def listar_mesas(estado: Optional[str] = None):
    p = ph()
    conn = get_connection_direct()
    try:
        if estado:
            cur = conn.execute(f"SELECT id_mesa, numero_mesa, estado FROM mesas WHERE estado={p} ORDER BY numero_mesa", (estado,))
        else:
            cur = conn.execute("SELECT id_mesa, numero_mesa, estado FROM mesas ORDER BY numero_mesa")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/api/productos")
def listar_productos(categoria: Optional[str] = None):
    p = ph()
    conn = get_connection_direct()
    try:
        if categoria:
            cur = conn.execute(
                "SELECT id_producto, nombre, precio_venta, categoria, activo, url_imagen "
                f"FROM productos_menu WHERE lower(trim(categoria))=lower(trim({p})) "
                "AND activo=1 ORDER BY nombre",
                (categoria,),
            )
        else:
            cur = conn.execute("SELECT id_producto, nombre, precio_venta, categoria, activo, url_imagen FROM productos_menu WHERE activo=1 ORDER BY categoria, nombre")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/api/pedidos")
def listar_pedidos(estado: Optional[str] = None, mesa: Optional[int] = None):
    p = ph()
    conn = get_connection_direct()
    try:
        sql = "SELECT pc.id_pedido, pc.id_mesa, m.numero_mesa, pc.fecha_hora, pc.estado_comanda, u.nombre || ' ' || u.apellido AS mozo FROM pedidos_cabecera pc JOIN mesas m ON m.id_mesa = pc.id_mesa JOIN usuarios u ON u.id_usuario = pc.id_usuario WHERE 1=1"
        params = []
        if estado:
            sql += f" AND pc.estado_comanda={p}"
            params.append(estado)
        if mesa:
            sql += f" AND pc.id_mesa={p}"
            params.append(mesa)
        sql += " ORDER BY pc.fecha_hora DESC"
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/api/pedidos/{id_pedido}")
def detalle_pedido(id_pedido: int):
    p = ph()
    conn = get_connection_direct()
    try:
        cur = conn.execute(f"SELECT pc.id_pedido, pc.fecha_hora, pc.estado_comanda, m.numero_mesa, u.nombre || ' ' || u.apellido AS mozo FROM pedidos_cabecera pc JOIN mesas m ON m.id_mesa = pc.id_mesa JOIN usuarios u ON u.id_usuario = pc.id_usuario WHERE pc.id_pedido={p}", (id_pedido,))
        cabecera = cur.fetchone()
        if not cabecera:
            raise HTTPException(404, "Pedido no encontrado")
        cur = conn.execute(f"SELECT pd.id_detalle, pm.nombre AS producto, pd.cantidad, pd.precio_unitario_facturado, pd.observaciones FROM pedido_detalle pd JOIN productos_menu pm ON pm.id_producto = pd.id_producto WHERE pd.id_pedido={p}", (id_pedido,))
        return {"pedido": dict(cabecera), "detalle": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()

@app.get("/api/ventas/hoy")
def ventas_hoy():
    conn = get_connection_direct()
    try:
        cur = conn.execute(f"SELECT COUNT(DISTINCT pc.id_pedido) AS pedidos, COALESCE(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total, COUNT(DISTINCT pc.id_mesa) AS mesas FROM pedidos_cabecera pc JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido WHERE pc.estado_comanda = 'cobrado' AND {sql_date('pc.fecha_hora')} = {sql_date(chr(39)+'now'+chr(39))}")
        row = cur.fetchone()
        return dict(row) if row else {"pedidos": 0, "total": 0, "mesas": 0}
    finally:
        conn.close()

@app.get("/api/ventas/semana")
def ventas_semana():
    conn = get_connection_direct()
    try:
        cur = conn.execute(f"SELECT {sql_date('pc.fecha_hora')} AS dia, ROUND(SUM(pd.cantidad * pd.precio_unitario_facturado), 0) AS total FROM pedidos_cabecera pc JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido WHERE pc.estado_comanda = 'cobrado' AND pc.fecha_hora >= {sql_date(chr(39)+'now'+chr(39))} GROUP BY dia ORDER BY dia")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/api/insumos/criticos")
def insumos_criticos():
    conn = get_connection_direct()
    try:
        cur = conn.execute("SELECT i.nombre, i.stock_actual, i.stock_minimo, i.unidad_medida, d.nombre_deposito AS deposito FROM stock_deposito sd JOIN insumos i ON i.id_insumo = sd.id_insumo JOIN depositos d ON d.id_deposito = sd.id_deposito WHERE sd.cantidad_disponible <= i.stock_minimo ORDER BY (i.stock_minimo - sd.cantidad_disponible) DESC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.post("/api/pedidos")
def crear_pedido(pedido: PedidoCreate):
    p = ph()
    conn = get_connection_direct()
    try:
        conn.execute("BEGIN")
        returning = " RETURNING id_pedido" if config.DB_ENGINE == "postgresql" else ""
        cur = conn.execute(f"INSERT INTO pedidos_cabecera (id_mesa, id_usuario) VALUES ({p},{p}){returning}", (pedido.id_mesa, pedido.id_usuario))
        id_pedido = last_id(conn, cur)
        for item in pedido.items:
            conn.execute(f"INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, observaciones) VALUES ({p},{p},{p},{p})", (id_pedido, item["id_producto"], item["cantidad"], item.get("observaciones", "")))
        conn.execute(f"UPDATE mesas SET estado='ocupada' WHERE id_mesa={p}", (pedido.id_mesa,))
        conn.commit()
        return {"ok": True, "id_pedido": id_pedido}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()

@app.get("/api/stock")
def stock_actual():
    conn = get_connection_direct()
    try:
        cur = conn.execute("SELECT i.nombre AS insumo, i.stock_actual, i.stock_minimo, sd.cantidad_disponible, d.nombre_deposito AS deposito, i.unidad_medida FROM stock_deposito sd JOIN insumos i ON i.id_insumo = sd.id_insumo JOIN depositos d ON d.id_deposito = sd.id_deposito ORDER BY d.nombre_deposito, i.nombre")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
