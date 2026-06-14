"""
database.py — Conexión centralizada con soporte dual SQLite/PostgreSQL.
Incluye pool de conexiones Postgres y decorador transaccional.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Generator

import config


# ── Helpers de portabilidad ───────────────────────────────────────────

def ph() -> str:
    """Retorna el placeholder SQL adecuado según el motor."""
    return "%s" if config.DB_ENGINE == "postgresql" else "?"


def last_id(conn, cur) -> int:
    """
    Retorna el último id insertado.
    SQLite: cur.lastrowid
    PostgreSQL: cur.fetchone()[0] (requiere RETURNING)
    """
    if config.DB_ENGINE == "postgresql":
        row = cur.fetchone()
        return row[0] if row else 0
    return cur.lastrowid


def sql_date(expr: str) -> str:
    """
    Retorna expresión SQL de fecha compatible con SQLite y PostgreSQL.
    Ej: sql_date("now") -> "date('now')" (SQLite) o "CURRENT_DATE" (PG)
        sql_date("now', '-7 days') -> "date('now', '-7 days')" (SQLite) o "CURRENT_DATE - INTERVAL '7 days'" (PG)
    """
    if config.DB_ENGINE == "postgresql":
        if "now" in expr:
            return "CURRENT_DATE"
        if "days" in expr:
            import re
            m = re.search(r"-(\d+)\s+days", expr)
            n = m.group(1) if m else "1"
            return f"CURRENT_DATE - INTERVAL '{n} days'"
        return expr
    return f"date({expr})"


def str_agg(column: str, separator: str = "\\n") -> str:
    """
    Retorna función de agregación de strings compatible.
    SQLite: GROUP_CONCAT(col, sep)
    PostgreSQL: STRING_AGG(col, sep)
    """
    sep_esc = separator.replace("\\n", "\\n")
    if config.DB_ENGINE == "postgresql":
        return f"STRING_AGG({column}, '{sep_esc}')"
    return f"GROUP_CONCAT({column}, '{sep_esc}')"

# ── Import condicional: psycopg2 solo si se usa PostgreSQL ─────────────
_pg_pool = None

def _ensure_pg_imports() -> None:
    """Importa psycopg2 solo cuando se necesita una conexion PostgreSQL."""
    global psycopg2, pg_pool, RealDictCursor
    if "psycopg2" not in globals():
        import psycopg2
        from psycopg2 import pool as pg_pool
        from psycopg2.extras import RealDictCursor


def _pg_connect_kwargs() -> dict:
    """Retorna kwargs para psycopg2.connect() priorizando DATABASE_URL."""
    _ensure_pg_imports()
    if config.DATABASE_URL:
        return {"dsn": config.DATABASE_URL, "cursor_factory": RealDictCursor}
    return {
        "host": config.DB_HOST,
        "port": config.DB_PORT,
        "dbname": config.DB_NAME,
        "user": config.DB_USER,
        "password": config.DB_PASSWORD,
        "sslmode": "require",
        "cursor_factory": RealDictCursor,
    }


def _pg_pool_kwargs() -> dict:
    """Retorna kwargs compatibles con ThreadedConnectionPool."""
    if config.DATABASE_URL:
        from urllib.parse import urlparse

        parsed = urlparse(config.DATABASE_URL)
        return {
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "dbname": parsed.path.lstrip("/"),
            "user": parsed.username,
            "password": parsed.password,
            "sslmode": "require",
        }
    return {
        "host": config.DB_HOST,
        "port": config.DB_PORT,
        "dbname": config.DB_NAME,
        "user": config.DB_USER,
        "password": config.DB_PASSWORD,
        "sslmode": "require",
    }


def _get_pg_pool():
    """Crea el pool PostgreSQL de forma perezosa."""
    global _pg_pool
    _ensure_pg_imports()
    if _pg_pool is None:
        _pg_pool = pg_pool.ThreadedConnectionPool(
            config.DB_POOL_MIN, config.DB_POOL_MAX, **_pg_pool_kwargs(),
        )
    return _pg_pool


# ── Pool de conexiones ─────────────────────────────────────────────────

@contextmanager
def get_connection() -> Generator[Any, None, None]:
    """
    Context manager que retorna una conexión del pool.
    - PostgreSQL: toma/retorna un ítem del pool.
    - SQLite: crea/cierra conexión con WAL + foreign_keys.
    """
    if config.DB_ENGINE == "postgresql":
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            yield conn
        finally:
            pool.putconn(conn)
    else:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_path = str(config.DATA_DIR / config.DB_PATH)
        conn = sqlite3.connect(db_path)
        conn.row_factory = lambda c, r: dict(sqlite3.Row(c, r))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()


def get_connection_direct() -> Any:
    """Versión simple (no context-manager) para scripts rápidos.
    Retorna conexiones con row_factory que produce dict nativos."""
    if config.DB_ENGINE == "postgresql":
        from urllib.parse import urlparse
        kwargs = _pg_connect_kwargs()
        return psycopg2.connect(**kwargs)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DATA_DIR / config.DB_PATH))
    conn.row_factory = lambda c, r: dict(sqlite3.Row(c, r))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Decorador transaccional ───────────────────────────────────────────

def transactional(func: Callable) -> Callable:
    """
    Envuelve la función en una transacción.
    Si la función lanza una excepción → ROLLBACK.
    Si retorna normalmente → COMMIT.
    La función recibe `conn` como primer argumento.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        conn = get_connection_direct()
        try:
            conn.execute("BEGIN TRANSACTION" if config.DB_ENGINE == "sqlite"
                         else "BEGIN")
            kwargs["conn"] = conn
            result = func(*args, **kwargs)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    return wrapper


# ── Inicialización de esquema (idempotente) ───────────────────────────

def init_db(schema_file: str | None = None) -> dict:
    """
    Ejecuta el schema correspondiente según el motor de base de datos.
    Retorna {"ok": True} o {"ok": False, "error": str}.
    """
    if schema_file is None:
        if config.DB_ENGINE == "postgresql":
            schema_file = str(config.BASE_DIR / "schema_produccion.sql")
        else:
            schema_file = str(config.BASE_DIR / "schema.sqlite.sql")

    try:
        conn = get_connection_direct()
        try:
            with open(schema_file, "r", encoding="utf-8") as f:
                sql = f.read()
            if config.DB_ENGINE == "sqlite":
                conn.executescript(sql)
            else:
                cur = conn.cursor()
                cur.execute(sql)
                cur.close()
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": f"Error creando esquema: {e}"}

    # Sembrar datos de ejemplo si la tabla está vacía
    try:
        _seed_if_empty()
    except Exception as e:
        return {"ok": False, "error": f"Error sembrando datos: {e}"}

    # Sembrar platos premium si la tabla productos_menu esta vacia
    try:
        conn = get_connection_direct()
        cur = conn.execute("SELECT COUNT(*) AS cnt FROM productos_menu")
        row = cur.fetchone()
        count = row["cnt"] if hasattr(row, "__getitem__") else row[0]
        if count == 0:
            _seed_menu_premium(conn)
            conn.commit()
        conn.close()
    except Exception:
        pass

    return {"ok": True}


def _seed_menu_premium(conn) -> None:
    platos = [
        (12000, "Entradas", "Provolone con mermelada de tomates y pesto, con escabeches y focaccia"),
        (12000, "Entradas", "Pera asada con queso azul, nueces y miel sobre verdes"),
        (12000, "Entradas", "Dúo empanadas carne cortada a cuchillo / humita y mozzarella"),
        (12000, "Entradas", "Carpaccio de lomo curado, crema de parmesano, alcaparras, pistacho tostados, focaccia y hojas verdes fritas"),
        (12000, "Entradas", "Tabla charcutería de elaboración propia, quesos, escabeches, alioli de ajo"),
        (15000, "Pastas", "Rotolo di tata (de cabrito y verduras)"),
        (15000, "Pastas", "Lasaña de pollo y espinaca al forno"),
        (15000, "Pastas", "Creps de espinaca y parmesano con finas hierbas"),
        (15000, "Pastas", "Cintas anchas en tinta de sepia con crema de mariscos"),
        (15000, "Pastas", "Ñoquis boniato con manteca y almendras tostadas"),
        (15000, "Pastas", "Cintas finas al huevo con fileto y estofado"),
        (15000, "Pastas", "Cintas finas al huevo con crema de hongos de pino"),
        (15000, "Pastas", "Cintas finas al huevo a la carbonara"),
        (22000, "Carnes", "Ojo de bife con aligot de papa y salsa criolla"),
        (22000, "Carnes", "Ojo de bife con salsa patrón"),
        (22000, "Carnes", "Ojo de bife con salsa de hongos"),
        (22000, "Carnes", "Lomo en demiglase con terrina de papa y vegetales glaseados"),
        (22000, "Carnes", "Bondiola ahumada en reducción de miel y jengibre con batatas rotas"),
        (22000, "Carnes", "Milanesa de entrecot con fideos al huevo con crema de hierbas"),
        (18000, "Pescados", "Salmón rosado con manteca de lima y azafrán acompañado de ensalada tibia"),
        (18000, "Pescados", "Trucha con alcaparras, manteca, naranja y miel, acompañado de papines y verduras salteadas"),
        (18000, "Pescados", "Pacú con papas rústicas y hojas verdes acompañados de salsa criolla"),
        (13000, "Comidas Criollas", "Locro criollo con verdeo picante"),
        (13000, "Comidas Criollas", "Humita"),
        (13000, "Comidas Criollas", "Guiso de lentejas"),
        (8000, "Postres", "Tiramisú"),
        (8000, "Postres", "Lingote de chocolate"),
        (8000, "Postres", "Flan tradicional"),
        (8000, "Postres", "Panna cotta con frutos rojos"),
        (8000, "Postres", "Tarta vasca"),
    ]
    ph = "%s" if str(getattr(config, 'DB_ENGINE', 'sqlite')) == "postgresql" else "?"
    for precio, categoria, nombre in platos:
        try:
            conn.execute(f"INSERT INTO productos_menu (nombre, precio_venta, categoria, activo) VALUES ({ph},{ph},{ph},1)", (nombre, precio, categoria))
        except Exception:
            pass


def _seed_if_empty() -> None:
    conn = get_connection_direct()
    try:
        cur = conn.execute("SELECT COUNT(*) AS cnt FROM usuarios")
        row = cur.fetchone()
        count = row["cnt"] if hasattr(row, "__getitem__") else row[0]
        if count > 0:
            return

        _exec_seed(conn)
        conn.commit()
    finally:
        conn.close()


def _exec_seed(conn) -> None:
    """Inserta datos demo (sintaxis SQLite/PostgreSQL compatible)."""
    import hashlib

    def _hash(pw: str) -> str:
        return hashlib.sha256(pw.encode()).hexdigest()

    usuarios_data = [
        ("Carlos", "García", "mozo", "carlos", _hash("1234")),
        ("María", "López", "cocina", "maria", _hash("1234")),
        ("Admin", "Root", "administrador", "admin", _hash("admin")),
    ]
    for nombre, apellido, rol, usr, pwhash in usuarios_data:
        conn.execute(
            f"INSERT INTO usuarios (nombre, apellido, rol, username, password_hash) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()})",
            (nombre, apellido, rol, usr, pwhash)
        )

    conn.execute("INSERT INTO mesas (numero_mesa, estado) VALUES (1, 'libre')")
    conn.execute("INSERT INTO mesas (numero_mesa, estado) VALUES (2, 'libre')")
    conn.execute("INSERT INTO mesas (numero_mesa, estado) VALUES (3, 'libre')")
    conn.execute("INSERT INTO mesas (numero_mesa, estado) VALUES (4, 'libre')")
    conn.execute("INSERT INTO mesas (numero_mesa, estado) VALUES (5, 'libre')")

    conn.execute("""
        INSERT INTO insumos (nombre, stock_actual, stock_minimo, unidad_medida, url_imagen)
        VALUES
            ('Carne de res', 8000, 2000, 'gramos', ''),
            ('Papa', 5000, 1000, 'gramos', ''),
            ('Queso mozzarella', 3000, 500, 'gramos', ''),
            ('Pan de hamburguesa', 20, 10, 'unidad', ''),
            ('Lechuga', 2000, 500, 'gramos', ''),
            ('Tomate', 3000, 500, 'gramos', ''),
            ('Vino tinto botella', 12, 6, 'unidad', ''),
            ('Helado', 4000, 1000, 'mililitros', ''),
            ('Harina', 5000, 1000, 'gramos', ''),
            ('Aceite', 3000, 500, 'mililitros', '')
    """)

    conn.execute("""
        INSERT INTO productos_menu (nombre, precio_venta, categoria, activo, url_imagen)
        VALUES
            ('Hamburguesa Clásica', 8500, 'cocina', 1, 'assets/ejemplos/hamburguesa.svg'),
            ('Papas Fritas', 3500, 'cocina', 1, 'assets/ejemplos/papas_fritas.svg'),
            ('Milanesa con guarnición', 7500, 'cocina', 1, 'assets/ejemplos/milanesa.svg'),
            ('Vino Tinto Casa', 4500, 'bebidas', 1, 'assets/ejemplos/vino_tinto.svg'),
            ('Helado artesanal', 3200, 'postres', 1, 'assets/ejemplos/helado.svg')
    """)

    conn.execute("""
        INSERT INTO recetas_escandallo (id_producto, id_insumo, cantidad_a_descontar)
        VALUES
            (1, 1, 150), (1, 4, 1), (1, 5, 30), (1, 6, 50),
            (2, 2, 250), (2, 10, 20),
            (3, 1, 200), (3, 9, 100), (3, 2, 200), (3, 10, 30),
            (4, 7, 1),
            (5, 8, 200)
    """)

    conn.execute("INSERT INTO depositos (nombre_deposito) VALUES ('Bodega Central')")
    conn.execute("INSERT INTO depositos (nombre_deposito) VALUES ('Barra Principal')")

    conn.execute("""
        INSERT INTO stock_deposito (id_insumo, id_deposito, cantidad_disponible)
        SELECT id_insumo, 1, stock_actual FROM insumos WHERE stock_actual > 0
    """)

    conn.execute("""INSERT INTO cajas_diarias (id_usuario_cajero, monto_apertura, estado_caja)
                    VALUES (3, 50000, 'abierta')""")


# ── Transacción crítica: stock ─────────────────────────────────────────

def confirmar_pedido_cocina(id_pedido: int) -> dict:
    """
    Transacción ATÓMICA que cambia el pedido a 'listo'
    y descuenta stock según recetas de escandallo.
    """
    conn = get_connection_direct()
    try:
        conn.execute("BEGIN TRANSACTION" if config.DB_ENGINE == "sqlite" else "BEGIN")
        p = ph()

        cur = conn.execute(
            f"SELECT estado_comanda FROM pedidos_cabecera WHERE id_pedido = {p}",
            (id_pedido,)
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return {"ok": False, "error": f"Pedido {id_pedido} no existe."}
        estado = row["estado_comanda"] if hasattr(row, "__getitem__") else row[0]
        if estado != "en_cocina":
            conn.rollback()
            return {"ok": False, "error": f"Estado inválido: '{estado}'. Se esperaba 'en_cocina'."}

        cur = conn.execute(
            f"SELECT pd.id_producto, pd.cantidad, pm.nombre"
            f" FROM pedido_detalle pd"
            f" JOIN productos_menu pm ON pm.id_producto = pd.id_producto"
            f" WHERE pd.id_pedido = {p}",
            (id_pedido,)
        )
        detalle = cur.fetchall()

        for item in detalle:
            cur2 = conn.execute(
                f"SELECT id_insumo, cantidad_a_descontar FROM recetas_escandallo WHERE id_producto = {p}",
                (item["id_producto"],)
            )
            for receta in cur2.fetchall():
                qty = receta["cantidad_a_descontar"] * item["cantidad"]
                conn.execute(
                    f"UPDATE insumos SET stock_actual = stock_actual - {p} WHERE id_insumo = {p}",
                    (qty, receta["id_insumo"])
                )

        conn.execute(
            f"UPDATE pedidos_cabecera SET estado_comanda = 'listo' WHERE id_pedido = {p}",
            (id_pedido,)
        )
        conn.commit()

        cur = conn.execute(
            "SELECT nombre, stock_actual, stock_minimo FROM insumos WHERE stock_actual <= stock_minimo"
        )
        advertencias = [
            f"⚠️ Stock bajo: '{r['nombre']}' ({r['stock_actual']:.0f}/{r['stock_minimo']:.0f})"
            for r in cur.fetchall()
        ]
        return {"ok": True, "advertencias": advertencias}

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def avanzar_estado(id_pedido: int, estado_actual: str) -> dict:
    """Avanza el estado de un pedido: pendiente→en_cocina→listo."""
    transiciones = {
        "pendiente": "en_cocina",
        "en_cocina": "listo",
    }
    nuevo_estado = transiciones.get(estado_actual)
    if not nuevo_estado:
        return {"ok": False, "error": f"Estado '{estado_actual}' no tiene transición definida."}

    # en_cocina → listo usa la función atómica (descuenta stock)
    if nuevo_estado == "listo":
        return confirmar_pedido_cocina(id_pedido)

    # pendiente → en_cocina: update simple
    conn = get_connection_direct()
    try:
        p = ph()
        cur = conn.execute(
            f"SELECT estado_comanda FROM pedidos_cabecera WHERE id_pedido = {p}",
            (id_pedido,)
        )
        row = cur.fetchone()
        if row is None:
            return {"ok": False, "error": f"Pedido {id_pedido} no existe."}
        estado_db = row["estado_comanda"] if hasattr(row, "__getitem__") else row[0]
        if estado_db != estado_actual:
            return {"ok": False, "error": f"Estado en DB es '{estado_db}', se esperaba '{estado_actual}'."}
        conn.execute(
            f"UPDATE pedidos_cabecera SET estado_comanda = {p} WHERE id_pedido = {p}",
            (nuevo_estado, id_pedido)
        )
        conn.commit()
        return {"ok": True, "advertencias": []}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def obtener_pedidos_por_estado() -> dict[str, list[dict]]:
    """Retorna comandas agrupadas por estado. Siempre incluye las keys: pendiente, en_cocina, listo."""
    grupos: dict[str, list[dict]] = {"pendiente": [], "en_cocina": [], "listo": []}
    conn = get_connection_direct()
    try:
        agg = str_agg("pm.nombre || ' x' || pd.cantidad")
        resultado = conn.execute(f"""
            SELECT
                pc.id_pedido       AS id,
                pc.fecha_hora      AS fecha,
                pc.estado_comanda  AS estado,
                m.numero_mesa      AS mesa,
                u.nombre || ' ' || u.apellido AS mozo,
                {agg}              AS detalle
            FROM pedidos_cabecera pc
            JOIN mesas m           ON m.id_mesa      = pc.id_mesa
            JOIN usuarios u        ON u.id_usuario   = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido   = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo')
              AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
            GROUP BY pc.id_pedido, pc.fecha_hora, pc.estado_comanda,
                     m.numero_mesa, u.nombre, u.apellido
            ORDER BY pc.fecha_hora ASC
        """).fetchall()
    finally:
        conn.close()

    for r in resultado:
        estado = r["estado"]
        if estado in grupos:
            grupos[estado].append(dict(r))

    return grupos


def seed_pedidos_demo() -> None:
    """Compatibilidad: no hace nada."""
    pass
