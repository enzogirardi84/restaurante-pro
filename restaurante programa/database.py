"""
database.py — Capa de acceso a datos, lógica transaccional y cola offline.
Soporta SQLite (local) y PostgreSQL/Supabase con tolerancia a fallos.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from cloud_config import normalized_database_url, normalized_database_url_directa

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "restaurante.db"
DB_DIR.mkdir(parents=True, exist_ok=True)
SUPABASE_SCHEMA_PATH = Path(__file__).parent / "supabase" / "schema.sql"
ADMIN_PASSWORD_HASH = "pbkdf2_sha256$260000$restaurante_pro_admin$3bf3e011536522835b606cc8b6d62689977bae8961ac46f703a8519b5cbb7d71"
ANAHI_PASSWORD_HASH = "pbkdf2_sha256$260000$restaurante_pro_anahigilardi$4dddc291f7d7d9355d779938477655ad0e21179cc056648b7b1ecf8e68121815"
ENZO_PASSWORD_HASH = "pbkdf2_sha256$260000$restaurante_pro_enzogirardi$43d87f64ede3c7d3ad5498e4c62d1cd272b03231219b42bdbff0b3806b37969b"
PG_POOL_MIN_SIZE = 0
PG_POOL_MAX_SIZE = 3
PG_POOL_TIMEOUT = 5
_PG_POOL = None
_PG_POOL_DSN = None

PK_BY_TABLE = {
    "pedidos_cabecera": "id_pedido",
    "pagos_mesa": "id_pago",
    "insumos": "id_insumo",
}

# ── Cola de sincronización offline ────────────────────────────────────

SYNC_TABLE = "cola_sincronizacion"
SYNC_SCHEMA = f"""
    CREATE TABLE IF NOT EXISTS {SYNC_TABLE} (
        id_sync INTEGER PRIMARY KEY AUTOINCREMENT,
        tabla TEXT NOT NULL,
        operacion TEXT NOT NULL CHECK (operacion IN ('INSERT', 'UPDATE', 'DELETE')),
        clave_primaria TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{{}}',
        creado_en TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        sincronizado INTEGER NOT NULL DEFAULT 0,
        ultimo_intento TEXT,
        intentos INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_sync_pendiente
        ON {SYNC_TABLE}(sincronizado, creado_en);
"""


def encolar_sync(tabla: str, operacion: str, clave_primaria: str, payload: dict | None = None) -> None:
    """Guarda una operacion pendiente de sincronizar con Supabase."""
    try:
        conn = get_connection()
        conn.execute(f"""
            INSERT INTO {SYNC_TABLE} (tabla, operacion, clave_primaria, payload_json)
            VALUES (?, ?, ?, ?)
        """, (tabla, operacion, clave_primaria, json.dumps(payload or {})))
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def procesar_cola_sincronizacion(max_items: int = 20) -> dict:
    """Procesa hasta `max_items` entradas pendientes contra Supabase.
    Retorna {ok, procesados, fallaron, errores}.
    """
    if not using_postgres():
        return {"ok": True, "procesados": 0, "fallaron": 0, "errores": []}

    pendientes = _pendientes_sync(max_items)
    if not pendientes:
        return {"ok": True, "procesados": 0, "fallaron": 0, "errores": []}

    procesados = 0
    fallaron = 0
    errores = []

    for item in pendientes:
        try:
            pg_conn = get_connection()
            payload = json.loads(item["payload_json"])
            sid = item["id_sync"]
            tabla = item["tabla"]
            op = item["operacion"]
            pk = item["clave_primaria"]

            if op == "INSERT":
                columnas = ", ".join(payload.keys())
                placeholders = ", ".join("?" for _ in payload)
                valores = list(payload.values())
                pg_conn.execute(
                    f"INSERT INTO {tabla} ({columnas}) VALUES ({placeholders}) "
                    f"ON CONFLICT DO UPDATE SET {', '.join(f'{k}=excluded.{k}' for k in payload)}",
                    tuple(valores),
                )
            elif op == "UPDATE" and payload:
                set_clause = ", ".join(f"{k}=?" for k in payload)
                valores = list(payload.values()) + [pk]
                pg_conn.execute(
                    f"UPDATE {tabla} SET {set_clause} WHERE id = ?",
                    tuple(valores),
                )

            local = get_connection()
            local.execute(
                f"UPDATE {SYNC_TABLE} SET sincronizado=1, ultimo_intento=datetime('now','localtime') WHERE id_sync=?",
                (sid,),
            )
            local.commit()
            local.close()
            procesados += 1

        except Exception as exc:
            fallaron += 1
            err_msg = f"Sync #{item['id_sync']}: {exc}"
            errores.append(err_msg)
            try:
                local = get_connection()
                local.execute(
                    f"UPDATE {SYNC_TABLE} SET intentos=intentos+1, ultimo_intento=datetime('now','localtime') WHERE id_sync=?",
                    (item["id_sync"],),
                )
                local.commit()
                local.close()
            except Exception:
                pass

    return {"ok": fallaron == 0, "procesados": procesados, "fallaron": fallaron, "errores": errores[:5]}


def _pendientes_sync(limit: int = 20) -> list[dict]:
    try:
        conn = get_connection()
        rows = conn.execute(
            f"SELECT * FROM {SYNC_TABLE} WHERE sincronizado=0 ORDER BY creado_en ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def offline_capable_execute(sql: str, params: tuple = (), *, tabla: str = "", pk: str = "") -> dict:
    """
    Ejecuta SQL con intento a Supabase primero; si falla, escribe solo local + encola.
    AHORA: captura ABSOLUTAMENTE TODAS las excepciones, libera la conexion PG
    y fallback a SQLite sin propagar errores a la UI.
    """
    pg_url = normalized_database_url()
    if not pg_url:
        return _local_execute(sql, params)

    # ── Intento Supabase ──
    pg_conn = None
    try:
        pool = get_pg_pool(pg_url)
        pg_conn = PgConnectionAdapter(pg_url, conn=pool.getconn(), pool=pool)
        pg_conn.execute(sql, params)
        pg_conn.commit()
        try:
            pool.putconn(pg_conn._conn)
        except Exception:
            pass
        return {"ok": True, "source": "supabase"}
    except Exception:
        # Liberar conexion PG pase lo que pase
        try:
            if pg_conn is not None:
                pool = get_pg_pool(pg_url)
                pool.putconn(pg_conn._conn)
        except Exception:
            pass

    # ── Fallback siempre a SQLite ──
    result = _local_execute(sql, params)
    if tabla and pk:
        try:
            encolar_sync(tabla, "UPDATE" if sql.upper().startswith("UPDATE") else "INSERT", pk, {})
        except Exception:
            pass
    return result


def _local_execute(sql: str, params: tuple = ()) -> dict:
    try:
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(sql, params)
        conn.commit()
        return {"ok": True, "source": "sqlite"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def using_postgres() -> bool:
    return bool(normalized_database_url())


def database_label() -> str:
    return "Supabase/PostgreSQL" if using_postgres() else str(DB_PATH)


def get_db_type() -> str:
    return "postgres" if using_postgres() else "sqlite"


def execute_query(sql: str, params: tuple = (), fetch: bool = False) -> list[dict] | None:
    """
    Ejecuta una consulta parametrizada de forma segura.
    Si fetch=True retorna list[dict]; si fetch=False retorna None (INSERT/UPDATE/DELETE).
    Compatible con SQLite y PostgreSQL.
    """
    conn = get_connection()
    try:
        if fetch:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        else:
            conn.execute(sql, params)
            return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


class DbRow(dict):
    """Fila compatible con sqlite.Row: permite row['campo'] y row[0]."""

    def __init__(self, columns: list[str], values: tuple[Any, ...]):
        super().__init__(zip(columns, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class PgCursorAdapter:
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def _columns(self) -> list[str]:
        return [desc.name for desc in (self._cursor.description or [])]

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return DbRow(self._columns(), row)

    def fetchall(self):
        columns = self._columns()
        return [DbRow(columns, row) for row in self._cursor.fetchall()]


class PgConnectionAdapter:
    """Adaptador minimo para ejecutar SQL estilo SQLite sobre PostgreSQL."""

    def __init__(self, dsn: str, conn=None, pool=None):
        if conn is None:
            import psycopg

            conn = psycopg.connect(dsn)
        self._conn = conn
        self._pool = pool

    def execute(self, sql: str, params: tuple | list = ()):
        command = sql.strip().upper()
        if command in {"BEGIN TRANSACTION", "BEGIN"}:
            self._conn.execute("BEGIN")
            return PgCursorAdapter(self._conn.cursor())
        if command == "COMMIT":
            self._conn.commit()
            return PgCursorAdapter(self._conn.cursor())
        if command == "ROLLBACK":
            self._conn.rollback()
            return PgCursorAdapter(self._conn.cursor())
        if command.startswith("PRAGMA"):
            return PgCursorAdapter(self._conn.cursor())

        sql = to_postgres_sql(sql)
        sql, returning_pk = add_returning_primary_key(sql)
        cur = self._conn.cursor()
        params = tuple(params or ())
        if any(p is None for p in params):
            import logging
            logging.warning("PostgreSQL execute recibi\u00f3 None en params; puede causar IndeterminateDatatype. SQL: %s", sql[:120])
        cur.execute(sql, params)
        wrapped = PgCursorAdapter(cur)
        if returning_pk and cur.description:
            returned = cur.fetchone()
            wrapped.lastrowid = returned[0] if returned else None
        return wrapped

    def executescript(self, script: str) -> None:
        for stmt in split_sql_script(script):
            self.execute(stmt)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        if self._pool is not None:
            try:
                self._conn.rollback()
            except Exception:
                pass
            self._pool.putconn(self._conn)
            return
        self._conn.close()


def get_pg_pool(dsn: str):
    global _PG_POOL, _PG_POOL_DSN
    if _PG_POOL is None or _PG_POOL_DSN != dsn:
        from psycopg_pool import ConnectionPool

        if _PG_POOL is not None:
            _PG_POOL.close()
        _PG_POOL = ConnectionPool(
            conninfo=dsn,
            min_size=PG_POOL_MIN_SIZE,
            max_size=PG_POOL_MAX_SIZE,
            timeout=PG_POOL_TIMEOUT,
            open=False,
        )
        _PG_POOL.open(wait=True)
        _PG_POOL_DSN = dsn
    return _PG_POOL


def split_sql_script(script: str) -> list[str]:
    return [stmt.strip() for stmt in script.split(";") if stmt.strip()]


def replace_placeholders(sql: str) -> str:
    result = []
    in_single = False
    i = 0
    while i < len(sql):
        char = sql[i]
        if char == "'":
            result.append(char)
            if i + 1 < len(sql) and sql[i + 1] == "'":
                result.append(sql[i + 1])
                i += 2
                continue
            in_single = not in_single
        elif char == "?" and not in_single:
            result.append("%s")
        else:
            result.append(char)
        i += 1
    return "".join(result)


def replace_group_concat(sql: str) -> str:
    sql = sql.replace(
        """GROUP_CONCAT(
                       '(' || (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) || 'x) ' || pm.nombre ||
                       CASE WHEN pd.observaciones != '' THEN ' [' || pd.observaciones || ']' ELSE '' END,
                       '\n'
                   )""",
        """STRING_AGG(
                       ('(' || (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) || 'x) ' || pm.nombre ||
                       CASE WHEN pd.observaciones != '' THEN ' [' || pd.observaciones || ']' ELSE '' END)::text,
                       E'\n'
                   )""",
    )
    sql = sql.replace(
        "GROUP_CONCAT(pd.cantidad || 'x ' || pm.nombre, ', ')",
        "STRING_AGG((pd.cantidad || 'x ' || pm.nombre)::text, ', ')",
    )
    sql = sql.replace(
        "GROUP_CONCAT((pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) || 'x ' || pm.nombre, ', ')",
        "STRING_AGG(((pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) || 'x ' || pm.nombre)::text, ', ')",
    )
    return sql


def to_postgres_sql(sql: str) -> str:
    converted = sql.strip()
    original_upper = converted.upper()
    converted = converted.replace("datetime('now','localtime')", "now()")
    converted = converted.replace("datetime('now', 'localtime')", "now()")
    converted = converted.replace("INSERT OR IGNORE INTO", "INSERT INTO")
    converted = converted.replace("MAX(cantidad_disponible - ?, 0)", "GREATEST(cantidad_disponible - ?, 0)")
    converted = replace_group_concat(converted)
    converted = replace_placeholders(converted)
    if "INSERT OR IGNORE INTO" in original_upper and "ON CONFLICT" not in converted.upper():
        converted = f"{converted} ON CONFLICT DO NOTHING"
    return converted


def add_returning_primary_key(sql: str) -> tuple[str, str | None]:
    upper = sql.upper()
    if not upper.startswith("INSERT INTO") or " RETURNING " in upper:
        return sql, None
    match = re.match(r"INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE)
    if not match:
        return sql, None
    table = match.group(1)
    pk = PK_BY_TABLE.get(table)
    if not pk:
        return sql, None
    return f"{sql} RETURNING {pk}", pk


# ── Conexión ──────────────────────────────────────────────────────────

class _FallbackConnection:
    """Conexion de fallback que devuelve resultados vacios."""
    def execute(self, *args, **kwargs):
        return self
    def executescript(self, *args, **kwargs):
        return self
    def fetchall(self):
        return []
    def fetchone(self):
        return None
    def commit(self):
        pass
    def close(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def cursor(self):
        return self
    def __iter__(self):
        return iter([])
    def __getitem__(self, key):
        return 0


_SQLITE_INIT_DONE = False


def get_connection(raise_on_error: bool = False):
    """Retorna una conexion SQLite local o PostgreSQL/Supabase."""
    global _SQLITE_INIT_DONE
    pg_url = normalized_database_url()
    if pg_url:
        try:
            pool = get_pg_pool(pg_url)
            return PgConnectionAdapter(pg_url, conn=pool.getconn(), pool=pool)
        except Exception as exc:
            if raise_on_error:
                raise
            import warnings
            warnings.warn(f"PostgreSQL no disponible ({exc}). Usando SQLite local.")
    DB_DIR.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        if not _SQLITE_INIT_DONE:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='configuracion_sistema'")
            if not cur.fetchone():
                init_db()
            _SQLITE_INIT_DONE = True
        return conn
    except sqlite3.Error as exc:
        if raise_on_error:
            raise
        import warnings
        warnings.warn(f"Error de conexion SQLite: {exc}")
        return error_connection(fallback_msg=f"Error de conexion SQLite: {exc}")


def error_connection(*, fallback_msg: str = "Error de conexion") -> _FallbackConnection:
    """Retorna una conexion de fallback que falla silenciosamente."""
    import warnings
    warnings.warn(fallback_msg)
    return _FallbackConnection()


def _migrar_proveedores() -> None:
    """Agrega columnas nuevas a proveedores si la tabla ya existe."""
    try:
        conn = get_connection()
        for col, tipo in [("cuit_rut", "TEXT NOT NULL DEFAULT ''"),
                          ("direccion", "TEXT NOT NULL DEFAULT ''")]:
            try:
                conn.execute(f"ALTER TABLE proveedores ADD COLUMN {col} {tipo}")
            except Exception:
                pass  # ya existe
        conn.commit()
    except Exception:
        pass  # la tabla todavia no existe
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _migrar_accesos_rol() -> None:
    try:
        conn = get_connection()
        try:
            conn.execute("ALTER TABLE accesos_sistema ADD COLUMN rol TEXT NOT NULL DEFAULT 'administrador'")
            conn.commit()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _migrar_facturacion_electronica() -> None:
    try:
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS facturas_electronicas (
                id_factura INTEGER PRIMARY KEY AUTOINCREMENT,
                id_pago INTEGER,
                tipo_comprobante TEXT NOT NULL DEFAULT 'B',
                punto_venta INTEGER NOT NULL DEFAULT 1,
                numero_comprobante INTEGER NOT NULL DEFAULT 0,
                cuit_cliente TEXT NOT NULL DEFAULT '',
                razon_social_cliente TEXT NOT NULL DEFAULT '',
                domicilio_cliente TEXT NOT NULL DEFAULT '',
                condicion_iva TEXT NOT NULL DEFAULT 'Consumidor Final',
                subtotal REAL NOT NULL DEFAULT 0,
                iva REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                medio_pago TEXT NOT NULL DEFAULT '',
                fecha_emision TEXT NOT NULL,
                cae TEXT NOT NULL DEFAULT '',
                cae_vencimiento TEXT NOT NULL DEFAULT '',
                estado TEXT NOT NULL DEFAULT 'emitido',
                observaciones TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _migrar_turnos() -> None:
    try:
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS turnos_personal (
                id_turno INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                hora_entrada TEXT NOT NULL,
                hora_salida TEXT,
                minutos_trabajados INTEGER NOT NULL DEFAULT 0,
                estado TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'cerrado')),
                FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
            )
        """)
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _migrar_promociones() -> None:
    """Crea la tabla promociones si no existe."""
    try:
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promociones (
                id_promocion INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('porcentaje', 'fijo', 'medio_pago', 'combo')),
                valor REAL NOT NULL CHECK (valor >= 0),
                categoria TEXT NOT NULL DEFAULT '',
                medio_pago TEXT NOT NULL DEFAULT '',
                hora_desde TEXT NOT NULL DEFAULT '',
                hora_hasta TEXT NOT NULL DEFAULT '',
                dias_semana TEXT NOT NULL DEFAULT '',
                activa INTEGER NOT NULL DEFAULT 1,
                creado TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def init_db(schema_file: str | None = None) -> None:
    """
    Ejecuta schema.sql para inicializar TODAS las bases de datos.
    SIEMPRE crea/esquema en SQLite local aunque PostgreSQL este activo,
    para que el fallback funcione sin 'no such table'.
    """
    local_schema = str(Path(__file__).parent / "schema.sql")

    # ── Inicializar SIEMPRE SQLite local (base de fallback) ──
    _init_sqlite_local(local_schema)

    # ── Inicializar PostgreSQL via conexion DIRECTA (5432) ──
    _init_postgres_directa(schema_file)

    # ── Sembrar datos de ejemplo SOLO contra SQLite local ──
    # (la conexion a Supabase se usa para CRUD, no para schema management)
    _seed_sqlite_local()


def _init_sqlite_local(schema_path: str) -> None:
    """Inicializa SQLite local con el schema completo."""
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
    except Exception as exc:
        import warnings
        warnings.warn(f"Error inicializando SQLite local: {exc}")


def _init_postgres_directa(schema_file: str | None = None) -> None:
    """Ejecuta DDL del schema contra PostgreSQL via conexion directa (5432)."""
    pg_url = normalized_database_url_directa()
    if not pg_url:
        return
    schema_path = schema_file or str(SUPABASE_SCHEMA_PATH)
    try:
        import psycopg
        pg_conn = psycopg.connect(pg_url, connect_timeout=10)
        with open(schema_path, "r", encoding="utf-8") as f:
            sql_content = f.read()
        for stmt in sql_content.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("\\"):
                try:
                    pg_conn.execute(stmt)
                except Exception:
                    pass
        pg_conn.commit()
        pg_conn.close()
    except Exception as exc:
        import warnings
        warnings.warn(f"No se pudo inicializar PostgreSQL directa: {exc}")


def _seed_sqlite_local() -> None:
    """Siembra datos de ejemplo SOLO en SQLite local para evitar
    sqlite_master y PRAGMA en PostgreSQL."""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) AS cnt FROM usuarios").fetchone()["cnt"]
        if count > 0:
            conn.close()
            return
        _seed_inserts(conn)
        _ensure_operational_schema(conn)
        conn.close()
    except Exception as exc:
        import warnings
        warnings.warn(f"Error sembrando datos en SQLite local: {exc}")


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def _ensure_user_role_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute("""
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'usuarios'
    """).fetchone()
    table_sql = row["sql"] if row else ""
    if not row:
        return
    if not _column_exists(conn, "usuarios", "mail"):
        conn.execute("ALTER TABLE usuarios ADD COLUMN mail TEXT")
    if not _column_exists(conn, "usuarios", "contrasena"):
        conn.execute("ALTER TABLE usuarios ADD COLUMN contrasena TEXT")
    conn.execute("""
        UPDATE usuarios
           SET mail = LOWER(
               REPLACE(TRIM(COALESCE(nombre, 'usuario')), ' ', '') || '.' ||
               REPLACE(TRIM(COALESCE(apellido, id_usuario)), ' ', '') || '.' ||
               id_usuario || '@local.invalid'
           )
         WHERE mail IS NULL OR TRIM(mail) = ''
    """)
    conn.execute("""
        UPDATE usuarios
           SET contrasena = CASE
               WHEN rol IN ('administrador', 'dueno') THEN ?
               ELSE ?
           END
         WHERE contrasena IS NULL OR TRIM(contrasena) = ''
    """, (ANAHI_PASSWORD_HASH, ANAHI_PASSWORD_HASH))
    conn.execute("""
        UPDATE usuarios
           SET mail = 'anahigilardi',
               contrasena = ?
         WHERE id_usuario = (
               SELECT MIN(id_usuario)
                 FROM usuarios
                WHERE rol IN ('administrador', 'dueno')
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM usuarios u2
                WHERE LOWER(u2.mail) = 'anahigilardi'
                  AND u2.id_usuario <> usuarios.id_usuario
           )
    """, (ANAHI_PASSWORD_HASH,))
    if "'caja'" not in table_sql or "'dueno'" not in table_sql or "contrasena" not in table_sql or "mail" not in table_sql:
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript("""
            DROP TABLE IF EXISTS usuarios_new;
            CREATE TABLE IF NOT EXISTS usuarios_new (
                id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                apellido TEXT NOT NULL,
                rol TEXT NOT NULL CHECK (rol IN ('mozo', 'cocina', 'caja', 'administrador', 'dueno')),
                mail TEXT NOT NULL DEFAULT '',
                contrasena TEXT NOT NULL,
                pin TEXT DEFAULT '0000',
                activo INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO usuarios_new (id_usuario, nombre, apellido, rol, mail, contrasena, pin, activo)
            SELECT id_usuario, nombre, apellido, rol, mail, contrasena, COALESCE(pin, '0000'), COALESCE(activo, 1)
              FROM usuarios;
            DROP TABLE usuarios;
            ALTER TABLE usuarios_new RENAME TO usuarios;
        """)
        conn.execute("PRAGMA foreign_keys=ON")


def _ensure_operational_schema(conn: sqlite3.Connection) -> None:
    """Aplica las migraciones minimas que comparten caja, reportes y pedidos."""
    _ensure_user_role_schema(conn)

    if not _column_exists(conn, "usuarios", "pin"):
        conn.execute("ALTER TABLE usuarios ADD COLUMN pin TEXT DEFAULT '0000'")
    if not _column_exists(conn, "usuarios", "activo"):
        conn.execute("ALTER TABLE usuarios ADD COLUMN activo INTEGER NOT NULL DEFAULT 1")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_mail_unique
            ON usuarios(mail)
            WHERE mail <> ''
    """)

    if not _column_exists(conn, "pedido_detalle", "precio_unitario_facturado"):
        conn.execute("ALTER TABLE pedido_detalle ADD COLUMN precio_unitario_facturado REAL")
    if not _column_exists(conn, "pedido_detalle", "cantidad_cobrada"):
        conn.execute("ALTER TABLE pedido_detalle ADD COLUMN cantidad_cobrada INTEGER DEFAULT 0")
    if not _column_exists(conn, "pedido_detalle", "cantidad_anulada"):
        conn.execute("ALTER TABLE pedido_detalle ADD COLUMN cantidad_anulada INTEGER DEFAULT 0")
    if not _column_exists(conn, "pedido_detalle", "motivo_anulacion"):
        conn.execute("ALTER TABLE pedido_detalle ADD COLUMN motivo_anulacion TEXT DEFAULT ''")

    if not _column_exists(conn, "pedidos_cabecera", "medio_pago"):
        conn.execute("ALTER TABLE pedidos_cabecera ADD COLUMN medio_pago TEXT DEFAULT ''")
    if not _column_exists(conn, "pedidos_cabecera", "total_cobrado"):
        conn.execute("ALTER TABLE pedidos_cabecera ADD COLUMN total_cobrado REAL DEFAULT 0")
    if not _column_exists(conn, "pedidos_cabecera", "fecha_cobro"):
        conn.execute("ALTER TABLE pedidos_cabecera ADD COLUMN fecha_cobro TEXT")
    conn.execute("""
        UPDATE pedido_detalle
           SET precio_unitario_facturado = (
               SELECT pm.precio_venta
                 FROM productos_menu pm
                WHERE pm.id_producto = pedido_detalle.id_producto
           )
         WHERE precio_unitario_facturado IS NULL
    """)

    # Crear cola de sincronización offline
    conn.executescript(SYNC_SCHEMA)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS depositos (
            id_deposito INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_deposito TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS stock_deposito (
            id_stock_deposito INTEGER PRIMARY KEY AUTOINCREMENT,
            id_insumo INTEGER NOT NULL,
            id_deposito INTEGER NOT NULL,
            cantidad_disponible REAL NOT NULL DEFAULT 0 CHECK (cantidad_disponible >= 0),
            UNIQUE(id_insumo, id_deposito),
            FOREIGN KEY (id_insumo) REFERENCES insumos(id_insumo),
            FOREIGN KEY (id_deposito) REFERENCES depositos(id_deposito)
        );

        CREATE TABLE IF NOT EXISTS proveedores (
            id_proveedor INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            telefono TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            notas TEXT NOT NULL DEFAULT '',
            cuit_rut TEXT NOT NULL DEFAULT '',
            direccion TEXT NOT NULL DEFAULT '',
            activo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS movimientos_stock (
            id_movimiento_stock INTEGER PRIMARY KEY AUTOINCREMENT,
            id_insumo INTEGER NOT NULL,
            id_usuario INTEGER,
            id_proveedor INTEGER,
            tipo_movimiento TEXT NOT NULL CHECK (tipo_movimiento IN ('compra', 'ajuste_entrada', 'ajuste_salida', 'descuento_receta', 'merma')),
            cantidad REAL NOT NULL CHECK (cantidad > 0),
            stock_anterior REAL NOT NULL DEFAULT 0,
            stock_nuevo REAL NOT NULL DEFAULT 0,
            descripcion TEXT NOT NULL DEFAULT '',
            fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (id_insumo) REFERENCES insumos(id_insumo),
            FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario),
            FOREIGN KEY (id_proveedor) REFERENCES proveedores(id_proveedor)
        );

        CREATE TABLE IF NOT EXISTS cajas_diarias (
            id_caja INTEGER PRIMARY KEY AUTOINCREMENT,
            id_usuario_cajero INTEGER NOT NULL,
            fecha_apertura TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            fecha_cierre TEXT,
            monto_apertura REAL NOT NULL DEFAULT 0 CHECK (monto_apertura >= 0),
            monto_ventas REAL NOT NULL DEFAULT 0 CHECK (monto_ventas >= 0),
            monto_cierre_real REAL DEFAULT NULL CHECK (monto_cierre_real IS NULL OR monto_cierre_real >= 0),
            diferencia_cierre REAL NOT NULL DEFAULT 0,
            observacion_cierre TEXT NOT NULL DEFAULT '',
            estado_caja TEXT NOT NULL DEFAULT 'abierta' CHECK (estado_caja IN ('abierta', 'cerrada')),
            FOREIGN KEY (id_usuario_cajero) REFERENCES usuarios(id_usuario)
        );

        CREATE TABLE IF NOT EXISTS movimientos_caja (
            id_movimiento INTEGER PRIMARY KEY AUTOINCREMENT,
            id_caja INTEGER NOT NULL,
            tipo_movimiento TEXT NOT NULL CHECK (tipo_movimiento IN ('ingreso_venta', 'egreso_proveedor', 'retiro_efectivo')),
            monto REAL NOT NULL CHECK (monto > 0),
            descripcion TEXT NOT NULL DEFAULT '',
            fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (id_caja) REFERENCES cajas_diarias(id_caja)
        );

        CREATE TABLE IF NOT EXISTS auditoria_eventos (
            id_evento INTEGER PRIMARY KEY AUTOINCREMENT,
            modulo TEXT NOT NULL,
            accion TEXT NOT NULL,
            detalle TEXT NOT NULL DEFAULT '',
            fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS pagos_mesa (
            id_pago INTEGER PRIMARY KEY AUTOINCREMENT,
            id_mesa INTEGER NOT NULL,
            id_usuario INTEGER,
            fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            medio_pago TEXT NOT NULL DEFAULT '',
            subtotal REAL NOT NULL DEFAULT 0,
            descuento REAL NOT NULL DEFAULT 0,
            servicio REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            tipo TEXT NOT NULL DEFAULT 'total' CHECK (tipo IN ('total', 'parcial')),
            FOREIGN KEY (id_mesa) REFERENCES mesas(id_mesa),
            FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
        );

        CREATE TABLE IF NOT EXISTS pago_detalle (
            id_pago_detalle INTEGER PRIMARY KEY AUTOINCREMENT,
            id_pago INTEGER NOT NULL,
            id_detalle INTEGER NOT NULL,
            cantidad INTEGER NOT NULL CHECK (cantidad > 0),
            precio_unitario REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (id_pago) REFERENCES pagos_mesa(id_pago),
            FOREIGN KEY (id_detalle) REFERENCES pedido_detalle(id_detalle)
        );

        CREATE TABLE IF NOT EXISTS configuracion_sistema (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS accesos_sistema (
            usuario TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            actualizado_en TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
    """)

    # Migration: add descuento column to pagos_mesa
    try:
        conn.execute("ALTER TABLE pagos_mesa ADD COLUMN descuento REAL NOT NULL DEFAULT 0")
    except Exception:
        pass

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS promociones (
            id_promocion INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('porcentaje', 'fijo', 'medio_pago', 'combo')),
            valor REAL NOT NULL CHECK (valor >= 0),
            categoria TEXT NOT NULL DEFAULT '',
            medio_pago TEXT NOT NULL DEFAULT '',
            hora_desde TEXT NOT NULL DEFAULT '',
            hora_hasta TEXT NOT NULL DEFAULT '',
            dias_semana TEXT NOT NULL DEFAULT '',
            activa INTEGER NOT NULL DEFAULT 1,
            creado TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS sistema_estado (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL DEFAULT '',
            actualizado_en TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
    """)

    if not _column_exists(conn, "cajas_diarias", "diferencia_cierre"):
        conn.execute("ALTER TABLE cajas_diarias ADD COLUMN diferencia_cierre REAL DEFAULT 0")
    if not _column_exists(conn, "cajas_diarias", "observacion_cierre"):
        conn.execute("ALTER TABLE cajas_diarias ADD COLUMN observacion_cierre TEXT DEFAULT ''")

    conn.execute("""
        INSERT OR IGNORE INTO configuracion_sistema (clave, valor)
        VALUES ('usuario_sistema', 'anahigilardi')
    """)
    conn.execute("""
        INSERT OR IGNORE INTO configuracion_sistema (clave, valor)
        VALUES ('password_sistema', 'pbkdf2_sha256$260000$restaurante_pro_anahigilardi$4dddc291f7d7d9355d779938477655ad0e21179cc056648b7b1ecf8e68121815')
    """)
    conn.execute("""
        UPDATE configuracion_sistema
           SET valor = 'anahigilardi'
         WHERE clave = 'usuario_sistema'
           AND valor IN ('sistema', 'admin')
    """)
    conn.execute("""
        UPDATE configuracion_sistema
           SET valor = ?
        WHERE clave = 'password_sistema'
           AND valor IN ('restaurante', ?)
    """, (ANAHI_PASSWORD_HASH, ADMIN_PASSWORD_HASH))
    for usuario, password_hash in [
        ("anahigilardi", ANAHI_PASSWORD_HASH),
        ("enzogirardi", ENZO_PASSWORD_HASH),
    ]:
        conn.execute("""
            INSERT INTO accesos_sistema (usuario, password_hash, activo)
            VALUES (?, ?, 1)
            ON CONFLICT(usuario) DO NOTHING
        """, (usuario, password_hash))
    for clave, valor in [
        ("restaurante_nombre", "Restaurante Pro"),
        ("restaurante_direccion", ""),
        ("restaurante_telefono", ""),
        ("restaurante_identificacion", ""),
        ("ticket_footer", "Gracias por su visita."),
        ("servicio_porcentaje", "10"),
        ("metodos_pago", "Efectivo,Tarjeta,Transferencia"),
        ("promo_activa", "0"),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO configuracion_sistema (clave, valor) VALUES (?, ?)",
            (clave, valor),
        )

    for clave, valor in [
        ("schema_version", "2026.06.05"),
        ("storage", "sqlite"),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO sistema_estado (clave, valor) VALUES (?, ?)",
            (clave, valor),
        )

    seed_menu_premium()
    conn.execute("UPDATE usuarios SET pin = '1234' WHERE rol = 'mozo' AND (pin IS NULL OR pin = '0000')")
    conn.execute("UPDATE usuarios SET pin = '2222' WHERE rol = 'cocina' AND (pin IS NULL OR pin = '0000')")
    conn.execute("UPDATE usuarios SET pin = '3333' WHERE rol = 'caja' AND (pin IS NULL OR pin = '0000')")
    conn.execute("UPDATE usuarios SET pin = '9999' WHERE rol = 'administrador' AND (pin IS NULL OR pin = '0000')")
    conn.execute("""
        INSERT INTO usuarios (nombre, apellido, rol, pin, activo)
        SELECT 'Lucía', 'Pérez', 'caja', '3333', 1
        WHERE NOT EXISTS (SELECT 1 FROM usuarios WHERE rol = 'caja')
    """)

    conn.execute("INSERT OR IGNORE INTO depositos (nombre_deposito) VALUES ('Deposito principal')")
    conn.execute("""
        INSERT OR IGNORE INTO stock_deposito (id_insumo, id_deposito, cantidad_disponible)
        SELECT id_insumo, 1, stock_actual
          FROM insumos
         WHERE stock_actual > 0
    """)
    conn.execute("""
        UPDATE mesas
           SET estado = 'libre'
         WHERE estado = 'ocupada'
           AND NOT EXISTS (
               SELECT 1
                 FROM pedidos_cabecera pc
                WHERE pc.id_mesa = mesas.id_mesa
                  AND pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado')
           )
    """)

    admin = conn.execute("""
        SELECT id_usuario
          FROM usuarios
         WHERE rol = 'administrador'
         ORDER BY id_usuario
         LIMIT 1
    """).fetchone()
    if admin:
        conn.execute("""
            INSERT INTO cajas_diarias (id_usuario_cajero, monto_apertura, estado_caja)
            SELECT ?, 0, 'abierta'
             WHERE NOT EXISTS (
                 SELECT 1 FROM cajas_diarias WHERE estado_caja = 'abierta'
             )
        """, (admin["id_usuario"],))

    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_usuarios_rol_activo
            ON usuarios(rol, activo);
        CREATE INDEX IF NOT EXISTS idx_mesas_estado
            ON mesas(estado);
        CREATE INDEX IF NOT EXISTS idx_productos_categoria_activo
            ON productos_menu(categoria, activo);
        CREATE INDEX IF NOT EXISTS idx_recetas_producto
            ON recetas_escandallo(id_producto);
        CREATE INDEX IF NOT EXISTS idx_recetas_insumo
            ON recetas_escandallo(id_insumo);
        CREATE INDEX IF NOT EXISTS idx_pedidos_estado_fecha
            ON pedidos_cabecera(estado_comanda, fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_pedidos_mesa_estado
            ON pedidos_cabecera(id_mesa, estado_comanda);
        CREATE INDEX IF NOT EXISTS idx_pedidos_usuario_fecha
            ON pedidos_cabecera(id_usuario, fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_detalle_pedido
            ON pedido_detalle(id_pedido);
        CREATE INDEX IF NOT EXISTS idx_detalle_producto
            ON pedido_detalle(id_producto);
        CREATE INDEX IF NOT EXISTS idx_pagos_fecha
            ON pagos_mesa(fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_pagos_mesa_fecha
            ON pagos_mesa(id_mesa, fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_pagos_medio
            ON pagos_mesa(medio_pago);
        CREATE INDEX IF NOT EXISTS idx_pago_detalle_pago
            ON pago_detalle(id_pago);
        CREATE INDEX IF NOT EXISTS idx_pago_detalle_detalle
            ON pago_detalle(id_detalle);
        CREATE INDEX IF NOT EXISTS idx_stock_insumo_fecha
            ON movimientos_stock(id_insumo, fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_auditoria_fecha
            ON auditoria_eventos(fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_cajas_estado_fecha
            ON cajas_diarias(estado_caja, fecha_apertura);
        CREATE INDEX IF NOT EXISTS idx_accesos_sistema_activo
            ON accesos_sistema(activo);
    """)

    conn.commit()


def _seed_inserts(conn: sqlite3.Connection) -> None:
    """Inserta datos de ejemplo separados del CREATE SCHEMA."""
    from datetime import datetime

    data = [
        "INSERT INTO usuarios (nombre, apellido, rol) VALUES ('Carlos', 'García', 'mozo');",
        "INSERT INTO usuarios (nombre, apellido, rol) VALUES ('María', 'López', 'cocina');",
        "INSERT INTO usuarios (nombre, apellido, rol) VALUES ('Lucía', 'Pérez', 'caja');",
        "INSERT INTO usuarios (nombre, apellido, rol) VALUES ('Admin', 'Root', 'administrador');",
        "INSERT INTO mesas (numero_mesa, estado) VALUES (1, 'libre'), (2, 'libre'), (3, 'libre'), (4, 'libre'), (5, 'libre');",
        "INSERT INTO insumos (nombre, stock_actual, stock_minimo, unidad_medida) VALUES "
        "('Carne de res', 8000, 2000, 'gramos'), ('Papa', 5000, 1000, 'gramos'), "
        "('Queso mozzarella', 3000, 500, 'gramos'), ('Pan de hamburguesa', 20, 10, 'unidad'), "
        "('Lechuga', 2000, 500, 'gramos'), ('Tomate', 3000, 500, 'gramos'), "
        "('Vino tinto botella', 12, 6, 'unidad'), ('Helado', 4000, 1000, 'mililitros'), "
        "('Harina', 5000, 1000, 'gramos'), ('Aceite', 3000, 500, 'mililitros');",
        "INSERT INTO productos_menu (nombre, precio_venta, categoria, activo) VALUES "
        "('Hamburguesa Clásica', 8500, 'cocina', 1), ('Papas Fritas', 3500, 'cocina', 1), "
        "('Milanesa con guarnición', 7500, 'cocina', 1), ('Vino Tinto Casa', 4500, 'bebidas', 1), "
        "('Helado artesanal', 3200, 'postres', 1);",
        "INSERT INTO recetas_escandallo (id_producto, id_insumo, cantidad_a_descontar) VALUES "
        "(1, 1, 150), (1, 4, 1), (1, 5, 30), (1, 6, 50), "
        "(2, 2, 250), (2, 10, 20), "
        "(3, 1, 200), (3, 9, 100), (3, 2, 200), (3, 10, 30), "
        "(4, 7, 1), "
        "(5, 8, 200);",
    ]
    for stmt in data:
        conn.execute(stmt)
    conn.commit()


# ── Transacción crítica: confirmar pedido y descontar stock ────────────

def confirmar_pedido_cocina(id_pedido: int) -> dict:
    """
    Transacción ATÓMICA que:
      1. Cambia el estado del pedido a 'listo'.
      2. Descuenta del inventario los insumos según las recetas de escandallo.

    Retorna un dict con resultado y mensaje.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        # ── 1. Validar que el pedido existe y está en 'en_cocina' ──
        row = conn.execute(
            "SELECT estado_comanda FROM pedidos_cabecera WHERE id_pedido = ?",
            (id_pedido,)
        ).fetchone()

        if row is None:
            conn.execute("ROLLBACK")
            return {"ok": False, "error": f"El pedido {id_pedido} no existe."}

        if row["estado_comanda"] != "en_cocina":
            conn.execute("ROLLBACK")
            return {
                "ok": False,
                "error": f"Estado inválido: '{row['estado_comanda']}'. Debe ser 'en_cocina'."
            }

        # ── 2. Obtener detalle del pedido ──
        detalle = conn.execute("""
            SELECT pd.id_producto, pd.cantidad, pm.nombre
            FROM pedido_detalle pd
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pd.id_pedido = ?
        """, (id_pedido,)).fetchall()

        if not detalle:
            conn.execute("ROLLBACK")
            return {"ok": False, "error": "El pedido no tiene productos asociados."}

        # ── 3. Descontar insumos según escandallo ──
        for item in detalle:
            recetas = conn.execute("""
                SELECT id_insumo, cantidad_a_descontar
                FROM recetas_escandallo
                WHERE id_producto = ?
            """, (item["id_producto"],)).fetchall()

            if not recetas:
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "error": f"'{item['nombre']}' no tiene receta de escandallo registrada."
                }

            for receta in recetas:
                cantidad_total = receta["cantidad_a_descontar"] * item["cantidad"]
                stock = conn.execute("""
                    SELECT nombre, stock_actual, unidad_medida
                    FROM insumos
                    WHERE id_insumo = ?
                """, (receta["id_insumo"],)).fetchone()
                if stock is None:
                    conn.execute("ROLLBACK")
                    return {"ok": False, "error": "La receta tiene un insumo inexistente."}
                if stock["stock_actual"] < cantidad_total:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "error": (
                            f"Stock insuficiente para '{stock['nombre']}'. "
                            f"Necesita {cantidad_total:.0f} {stock['unidad_medida']} "
                            f"y hay {stock['stock_actual']:.0f}."
                        )
                    }
                stock_anterior = float(stock["stock_actual"])
                stock_nuevo = stock_anterior - float(cantidad_total)
                conn.execute("""
                    UPDATE insumos
                    SET stock_actual = stock_actual - ?
                    WHERE id_insumo = ?
                """, (cantidad_total, receta["id_insumo"]))
                conn.execute("""
                    INSERT INTO movimientos_stock
                        (id_insumo, tipo_movimiento, cantidad, stock_anterior, stock_nuevo, descripcion)
                    VALUES (?, 'descuento_receta', ?, ?, ?, ?)
                """, (
                    receta["id_insumo"],
                    cantidad_total,
                    stock_anterior,
                    stock_nuevo,
                    f"Pedido {id_pedido} - {item['nombre']}",
                ))
                conn.execute("""
                    UPDATE stock_deposito
                       SET cantidad_disponible = MAX(cantidad_disponible - ?, 0)
                     WHERE id_insumo = ?
                       AND id_deposito = (
                           SELECT id_deposito
                             FROM stock_deposito
                            WHERE id_insumo = ?
                            ORDER BY cantidad_disponible DESC
                            LIMIT 1
                       )
                """, (cantidad_total, receta["id_insumo"], receta["id_insumo"]))

        # ── 4. Cambiar estado a 'listo' ──
        conn.execute("""
            UPDATE pedidos_cabecera
            SET estado_comanda = 'listo'
            WHERE id_pedido = ?
        """, (id_pedido,))

        conn.execute("COMMIT")

        # ── 5. Verificar stock mínimo y devolver advertencias ──
        advertencias = []
        bajos = conn.execute("""
            SELECT nombre, stock_actual, stock_minimo
            FROM insumos
            WHERE stock_actual <= stock_minimo
        """).fetchall()
        for ins in bajos:
            advertencias.append(
                f"⚠️  Stock bajo: '{ins['nombre']}' "
                f"({ins['stock_actual']:.0f} / {ins['stock_minimo']:.0f})"
            )

        return {"ok": True, "advertencias": advertencias}

    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        return {"ok": False, "error": f"Error de base de datos: {str(e)}"}
    finally:
        conn.close()


# ── Consultas helper para la UI ───────────────────────────────────────

def obtener_pedidos_por_estado() -> dict[str, list]:
    """Retorna los pedidos agrupados por estado_comanda."""
    conn = get_connection()
    try:
        filas = conn.execute("""
            SELECT pc.id_pedido,
                   pc.fecha_hora,
                   pc.estado_comanda,
                   m.numero_mesa,
                   u.nombre || ' ' || u.apellido AS mozo,
                   GROUP_CONCAT(
                       '(' || (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) || 'x) ' || pm.nombre ||
                       CASE WHEN pd.observaciones != '' THEN ' [' || pd.observaciones || ']' ELSE '' END,
                       '\n'
                   ) AS detalle_texto
            FROM pedidos_cabecera pc
            JOIN mesas m           ON m.id_mesa = pc.id_mesa
            JOIN usuarios u        ON u.id_usuario = pc.id_usuario
            JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN productos_menu pm ON pm.id_producto = pd.id_producto
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina', 'listo')
              AND (pd.cantidad - COALESCE(pd.cantidad_anulada, 0)) > 0
            GROUP BY pc.id_pedido, pc.fecha_hora, pc.estado_comanda, m.numero_mesa, u.nombre, u.apellido
            ORDER BY pc.fecha_hora ASC
        """).fetchall()

        agrupados: dict[str, list] = {"pendiente": [], "en_cocina": [], "listo": []}
        for f in filas:
            agrupados[f["estado_comanda"]].append({
                "id":         f["id_pedido"],
                "mesa":       f["numero_mesa"],
                "mozo":       f["mozo"],
                "fecha":      f["fecha_hora"],
                "detalle":    f["detalle_texto"],
                "estado":     f["estado_comanda"],
            })
        return agrupados
    finally:
        conn.close()


def avanzar_estado(id_pedido: int, estado_actual: str) -> dict:
    """
    Avanza el estado de un pedido:
        pendiente -> en_cocina
        en_cocina -> ejecuta confirmar_pedido_cocina (transacción con stock)
    """
    conn = get_connection()
    try:
        if estado_actual == "pendiente":
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                UPDATE pedidos_cabecera
                SET estado_comanda = 'en_cocina'
                WHERE id_pedido = ?
            """, (id_pedido,))
            conn.commit()
            return {"ok": True}
        elif estado_actual == "en_cocina":
            return confirmar_pedido_cocina(id_pedido)
        return {"ok": False, "error": "Estado no manejado."}
    finally:
        conn.close()


def marcar_pedido_entregado(id_pedido: int) -> dict:
    """Marca un pedido listo como entregado por el mozo."""
    conn = get_connection()
    try:
        cur = conn.execute("""
            UPDATE pedidos_cabecera
               SET estado_comanda = 'entregado'
             WHERE id_pedido = ?
               AND estado_comanda = 'listo'
        """, (id_pedido,))
        conn.commit()
        if cur.rowcount == 0:
            return {"ok": False, "error": "El pedido no esta listo o no existe."}
        return {"ok": True}
    finally:
        conn.close()


def registrar_auditoria(modulo: str, accion: str, detalle: str = "") -> None:
    """Registra una accion operativa sin interrumpir la pantalla si falla."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO auditoria_eventos (modulo, accion, detalle)
            VALUES (?, ?, ?)
        """, (modulo, accion, detalle))
        conn.commit()
    finally:
        conn.close()


def registrar_auditoria_operativa(usuario: str, accion: str, detalle: str = "",
                                  metadata_json: str = "{}") -> None:
    """Registra una accion critica en logs_operaciones para auditoria de caja.
    Acciones tipicas: eliminacion_item, cambio_precio, apertura_forzada,
    mesa_reabierta, cierre_anticipado, anulacion_factura."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO logs_operaciones (usuario, accion, detalle, metadata_json)
            VALUES (?, ?, ?, ?)
        """, (usuario, accion, detalle, metadata_json))
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def logs_operaciones_recientes(limit: int = 100) -> list[dict]:
    """Retorna los ultimos logs operativos para el panel de auditoria."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id_log, usuario, accion, detalle, created_at
            FROM logs_operaciones
            ORDER BY id_log DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _get_unidad(id_insumo):
    conn = get_connection()
    try:
        row = conn.execute("SELECT unidad_medida FROM insumos WHERE id_insumo = ?", (id_insumo,)).fetchone()
        return row["unidad_medida"] if row else ""
    finally:
        conn.close()


# ── Seed de pedidos de prueba para la demo ────────────────────────────

def seed_menu_premium() -> None:
    """Inserta los 30 platos premium si la tabla productos_menu esta vacia."""
    try:
        conn = get_connection()
    except Exception:
        return
    try:
        conn.execute("SELECT COUNT(*) FROM productos_menu").fetchone()
    except Exception:
        conn.close()
        init_db()
        try:
            conn = get_connection()
        except Exception:
            return
    try:
        cur = conn.execute("SELECT COUNT(*) AS cnt FROM productos_menu")
        if cur.fetchone()["cnt"] > 0:
            conn.close()
            return
    except Exception:
        conn.close()
        return
    platos = [
        ("Provolone con mermelada de tomates y pesto, con escabeches y focaccia", 12000, "Entradas"),
        ("Pera asada con queso azul, nueces y miel sobre verdes", 12000, "Entradas"),
        ("Dúo empanadas carne cortada a cuchillo / humita y mozzarella", 12000, "Entradas"),
        ("Carpaccio de lomo curado, crema de parmesano, alcaparras, pistacho tostados, focaccia y hojas verdes fritas", 12000, "Entradas"),
        ("Tabla charcutería de elaboración propia, quesos, escabeches, alioli de ajo", 12000, "Entradas"),
        ("Rotolo di tata (de cabrito y verduras)", 15000, "Pastas"),
        ("Lasaña de pollo y espinaca al forno", 15000, "Pastas"),
        ("Creps de espinaca y parmesano con finas hierbas", 15000, "Pastas"),
        ("Cintas anchas en tinta de sepia con crema de mariscos", 15000, "Pastas"),
        ("Ñoquis boniato con manteca y almendras tostadas", 15000, "Pastas"),
        ("Cintas finas al huevo con fileto y estofado", 15000, "Pastas"),
        ("Cintas finas al huevo con crema de hongos de pino", 15000, "Pastas"),
        ("Cintas finas al huevo a la carbonara", 15000, "Pastas"),
        ("Ojo de bife con aligot de papa y salsa criolla", 22000, "Carnes"),
        ("Ojo de bife con salsa patrón", 22000, "Carnes"),
        ("Ojo de bife con salsa de hongos", 22000, "Carnes"),
        ("Lomo en demiglase con terrina de papa y vegetales glaseados", 22000, "Carnes"),
        ("Bondiola ahumada en reducción de miel y jengibre con batatas rotas", 22000, "Carnes"),
        ("Milanesa de entrecot con fideos al huevo con crema de hierbas", 22000, "Carnes"),
        ("Salmón rosado con manteca de lima y azafrán acompañado de ensalada tibia", 18000, "Pescados"),
        ("Trucha con alcaparras, manteca, naranja y miel, acompañado de papines y verduras salteadas", 18000, "Pescados"),
        ("Pacú con papas rústicas y hojas verdes acompañados de salsa criolla", 18000, "Pescados"),
        ("Locro criollo con verdeo picante", 13000, "Comidas Criollas"),
        ("Humita", 13000, "Comidas Criollas"),
        ("Guiso de lentejas", 13000, "Comidas Criollas"),
        ("Tiramisú", 8000, "Postres"),
        ("Lingote de chocolate", 8000, "Postres"),
        ("Flan tradicional", 8000, "Postres"),
        ("Panna cotta con frutos rojos", 8000, "Postres"),
        ("Tarta vasca", 8000, "Postres"),
    ]
    for nombre, precio, categoria in platos:
        try:
            conn.execute("INSERT OR IGNORE INTO productos_menu (nombre, precio_venta, categoria, activo) VALUES (?, ?, ?, 1)",
                         (nombre, precio, categoria))
        except Exception:
            pass
    conn.commit()
    conn.close()


def seed_pedidos_demo() -> None:
    """Crea pedidos de ejemplo para probar la pantalla KDS."""
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT COUNT(*) AS cnt FROM pedidos_cabecera"
        ).fetchone()["cnt"]
        if existing > 0:
            return  # ya hay datos

        from datetime import datetime, timedelta

        ahora = datetime.now()

        # Pedido 1 — pendiente (recién llegado)
        conn.execute("""
            INSERT INTO pedidos_cabecera (id_mesa, id_usuario, fecha_hora, estado_comanda)
            VALUES (?, ?, ?, 'pendiente')
        """, (1, 1, (ahora - timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")))
        pid1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _insert_detalle(conn, pid1, 1, 2, "sin cebolla")
        _insert_detalle(conn, pid1, 2, 1, "")
        conn.execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=1")

        # Pedido 2 — pendiente (hace 12 min, alerta amarilla)
        conn.execute("""
            INSERT INTO pedidos_cabecera (id_mesa, id_usuario, fecha_hora, estado_comanda)
            VALUES (?, ?, ?, 'pendiente')
        """, (2, 1, (ahora - timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M:%S")))
        pid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _insert_detalle(conn, pid2, 3, 1, "punto jugoso")
        _insert_detalle(conn, pid2, 5, 2, "")
        conn.execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=2")

        # Pedido 3 — en cocina
        conn.execute("""
            INSERT INTO pedidos_cabecera (id_mesa, id_usuario, fecha_hora, estado_comanda)
            VALUES (?, ?, ?, 'en_cocina')
        """, (3, 1, (ahora - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")))
        pid3 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _insert_detalle(conn, pid3, 1, 1, "con queso extra")
        _insert_detalle(conn, pid3, 2, 1, "")
        _insert_detalle(conn, pid3, 4, 1, "tinto de la casa")
        conn.execute("UPDATE mesas SET estado='ocupada' WHERE id_mesa=3")

        conn.commit()
    finally:
        conn.close()


def _insert_detalle(
    conn: sqlite3.Connection,
    id_pedido: int,
    id_producto: int,
    cantidad: int,
    observaciones: str,
) -> None:
    precio = conn.execute(
        "SELECT precio_venta FROM productos_menu WHERE id_producto = ?",
        (id_producto,),
    ).fetchone()
    if _column_exists(conn, "pedido_detalle", "precio_unitario_facturado"):
        conn.execute("""
            INSERT INTO pedido_detalle
                (id_pedido, id_producto, cantidad, observaciones, precio_unitario_facturado)
            VALUES (?, ?, ?, ?, ?)
        """, (
            id_pedido,
            id_producto,
            cantidad,
            observaciones,
            precio["precio_venta"] if precio else 0,
        ))
    else:
        conn.execute("""
            INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, observaciones)
            VALUES (?, ?, ?, ?)
        """, (id_pedido, id_producto, cantidad, observaciones))
