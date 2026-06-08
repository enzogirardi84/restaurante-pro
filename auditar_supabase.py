#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auditar_supabase.py — Diagnóstico exhaustivo de infraestructura cloud
para COMANDAPRO ERP / Restaurante Pro.

Conecta contra Supabase (PostgreSQL), valida esquemas contra los archivos
schema.sql / schema_ampliado.sql, detecta fugas de datos, columnas faltantes,
errores de inserción silenciosos, y propone soluciones para contenedores
efímeros de Streamlit Cloud.

USO:
    python auditar_supabase.py
    python auditar_supabase.py --insert-test   (activa la prueba de inserción)
    python auditar_supabase.py --fix-local-sync (fuerza la descarga Supabase → SQLite)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── Rutas del proyecto ─────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
INNER_DIR = BASE_DIR / "restaurante programa"
DATA_DIR = INNER_DIR / "data"
DB_PATH = DATA_DIR / "restaurante.db"
ENV_PATH = BASE_DIR / ".env"
SUPABASE_SCHEMA_PATH = INNER_DIR / "supabase" / "schema.sql"
LOCAL_SCHEMA_PATH = INNER_DIR / "schema.sql"
SCHEMA_AMPLIADO_PATH = INNER_DIR / "schema_ampliado.sql"
SCHEMA_PRODUCCION_PATH = BASE_DIR / "schema_produccion.sql"
SCHEMA_SQLITE_PATH = BASE_DIR / "schema.sqlite.sql"

# ── Tablas críticas esperadas ──────────────────────────────────────────
TABLAS_CRITICAS = [
    "usuarios",
    "mesas",
    "insumos",
    "productos_menu",
    "recetas_escandallo",
    "pedidos_cabecera",
    "pedido_detalle",
    "pagos_mesa",
    "pago_detalle",
    "proveedores",
    "depositos",
    "stock_deposito",
    "movimientos_stock",
    "cajas_diarias",
    "movimientos_caja",
    "auditoria_eventos",
    "configuracion_sistema",
    "accesos_sistema",
    "sistema_estado",
    "promociones",
    "turnos_personal",
    "facturas_electronicas",
    "cola_sincronizacion",
]

# Columnas que SIEMPRE deben existir en cada tabla crítica
COLUMNAS_OBLIGATORIAS: dict[str, list[str]] = {
    "usuarios":                    ["id_usuario", "nombre", "apellido", "rol", "mail", "contrasena", "pin", "activo"],
    "insumos":                     ["id_insumo", "nombre", "stock_actual", "stock_minimo", "unidad_medida"],
    "productos_menu":              ["id_producto", "nombre", "precio_venta", "categoria", "activo"],
    "pedidos_cabecera":            ["id_pedido", "id_mesa", "id_usuario", "fecha_hora", "estado_comanda", "medio_pago", "total_cobrado", "fecha_cobro"],
    "pedido_detalle":              ["id_detalle", "id_pedido", "id_producto", "cantidad", "observaciones", "precio_unitario_facturado", "cantidad_cobrada", "cantidad_anulada", "motivo_anulacion"],
    "pagos_mesa":                  ["id_pago", "id_mesa", "id_usuario", "fecha_hora", "medio_pago", "subtotal", "descuento", "servicio", "total", "tipo"],
    "cola_sincronizacion":         ["id_sync", "tabla", "operacion", "clave_primaria", "payload_json", "creado_en", "sincronizado", "ultimo_intento", "intentos"],
}

# ── Variables de entorno para Supabase ─────────────────────────────────
def _cargar_env() -> dict[str, str]:
    """Lee variables de entorno con prioridad: st.secrets > .env > os.environ."""
    env_vars: dict[str, str] = {}

    # 1. Leer archivo .env
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea or linea.startswith("#"):
                    continue
                if "=" in linea:
                    k, _, v = linea.partition("=")
                    env_vars[k.strip()] = v.strip().strip("\"'")

    # 2. Sobreescribir con os.environ (Streamlit Cloud los inyecta así)
    for k in [
        "DB_ENGINE", "DATABASE_URL", "SUPABASE_DB_URL",
        "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    ]:
        if os.environ.get(k, "").strip():
            env_vars[k] = os.environ[k].strip()

    # 3. Intentar st.secrets (solo si streamlit está disponible)
    try:
        import streamlit as st
        for k in list(env_vars.keys()):
            val = st.secrets.get(k)
            if val:
                env_vars[k] = str(val).strip()
    except Exception:
        pass

    return env_vars


ENV = _cargar_env()
DB_ENGINE = ENV.get("DB_ENGINE", "sqlite").lower()
DATABASE_URL = ENV.get("DATABASE_URL", "") or ENV.get("SUPABASE_DB_URL", "")


def _separador(titulo: str, char: str = "=") -> None:
    print("")
    print(char * 72)
    print(f"  {titulo}")
    print(char * 72)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _warn(msg: str) -> None:
    print(f"  [ADVERTENCIA] {msg}")


def _err(msg: str) -> None:
    print(f"  [ERROR] {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


# ═══════════════════════════════════════════════════════════════════════
#  PASO 1: PRUEBA DE CONEXIÓN Y PING EXTENDIDO
# ═══════════════════════════════════════════════════════════════════════

def probar_conexion() -> dict:
    """Mide latencia, verifica pooler, SSL, y DNS."""
    _separador("PASO 1: PRUEBA DE CONEXION Y PING EXTENDIDO")

    resultado = {
        "configurado": False,
        "alcanzable": False,
        "latencia_ms": None,
        "pooler": None,
        "ssl": None,
        "version_pg": None,
        "dns_ok": None,
        "detalles": [],
    }

    if not DATABASE_URL:
        _warn("DATABASE_URL no está configurada. Revisa el .env o Streamlit Secrets.")
        _info("Las pruebas contra Supabase se omitirán. Solo se auditará SQLite local.")
        return resultado

    if DB_ENGINE != "postgresql":
        _warn(f"DB_ENGINE={DB_ENGINE!r}, se esperaba 'postgresql'. Se fuerza intento contra DATABASE_URL igual.")

    resultado["configurado"] = True

    # Verificar estructura de DATABASE_URL
    parsed = urlparse(DATABASE_URL)
    _info(f"Host: {parsed.hostname}, Puerto: {parsed.port or 5432}, Base: {parsed.path.lstrip('/')}")
    _info(f"Usuario: {parsed.username or 'N/A'}")

    if parsed.password:
        _info("Contrasena: configurada")
    else:
        _warn("No hay contrasena en DATABASE_URL")

    # Detectar si usa pooler de Supabase
    hostname = (parsed.hostname or "").lower()
    if "pooler" in hostname:
        resultado["pooler"] = "Supabase Pooler (transaction mode)"
        _info("Usa el pooler de conexiones de Supabase (transaction mode)")
    elif "supabase" in hostname:
        resultado["pooler"] = "Conexion directa (sin pooler)"
        _info("Conexion directa a Supabase (se recomienda pooler para production)")
    else:
        resultado["pooler"] = f"Host externo: {hostname}"

    # Verificar SSL
    if "sslmode=require" in DATABASE_URL or "sslmode=require" in DATABASE_URL.lower():
        resultado["ssl"] = "SSL Requerido"
        _ok("SSL configurado correctamente")
    else:
        resultado["ssl"] = "Sin SSL explicito"
        _warn("No se detecto sslmode=require en DATABASE_URL. Supabase lo exige.")

    # Resolución DNS
    import socket
    try:
        t0 = time.time()
        ip = socket.getaddrinfo(parsed.hostname, parsed.port or 5432)
        t1 = time.time()
        resultado["dns_ok"] = True
        _ok(f"Resolucion DNS: {parsed.hostname} -> {ip[0][4][0]} ({((t1 - t0) * 1000):.1f} ms)")
    except Exception as exc:
        resultado["dns_ok"] = False
        _err(f"Resolucion DNS FALLIDA: {exc}")

    # Conexión real + medición de latencia
    try:
        import psycopg2
        t0 = time.time()
        conn = psycopg2.connect(DATABASE_URL)
        t1 = time.time()
        latencia = (t1 - t0) * 1000
        resultado["latencia_ms"] = round(latencia, 1)
        resultado["alcanzable"] = True

        cur = conn.cursor()
        cur.execute("SELECT version()")
        pg_ver = cur.fetchone()[0]
        resultado["version_pg"] = pg_ver.split(",")[0].strip() if pg_ver else "N/A"
        conn.close()

        if latencia > 3000:
            _warn(f"Latencia alta: {latencia:.0f} ms (> 3000 ms). Puede afectar el rendimiento.")
            _info("Causas posibles: pooler mal configurado, restricciones de firewall, o region remota.")
        else:
            _ok(f"Conexion exitosa. Version: {resultado['version_pg']}")
            _ok(f"Latencia: {latencia:.0f} ms")

    except Exception as exc:
        resultado["alcanzable"] = False
        _err(f"Conexion FALLIDA: {exc}")
        exc_str = str(exc).lower()
        if "dns" in exc_str or "could not translate host" in exc_str:
            _err("  -> Problema de RESOLUCION DNS. Verifica el hostname en DATABASE_URL.")
        if "ssl" in exc_str or "certificate" in exc_str or "tls" in exc_str:
            _err("  -> Problema de SSL/TLS. Agrega ?sslmode=require al final de DATABASE_URL.")
        if "timeout" in exc_str or "timed out" in exc_str:
            _err("  -> TIMEOUT. Posible firewall bloqueando el puerto 5432.")
        if "password" in exc_str or "authentication" in exc_str:
            _err("  -> Error de AUTENTICACION. Verifica usuario/contrasena.")
        if "pooler" in exc_str or "too many connections" in exc_str:
            _err("  -> Pooler saturado. Aumenta PG_POOL_MAX_SIZE o reduce conexiones simultaneas.")

    return resultado


# ═══════════════════════════════════════════════════════════════════════
#  PASO 2: AUDITORIA DE ESTRUCTURA DE TABLAS
# ═══════════════════════════════════════════════════════════════════════

# ── SQL nativo que se usará contra information_schema de Supabase ─────

SQL_LISTAR_TABLAS = """
    SELECT table_name,
           pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) AS tamanio,
           obj_description(quote_ident(table_name)::regclass, 'pg_class') AS comentario
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_type = 'BASE TABLE'
    ORDER BY table_name;
"""

SQL_COLUMNAS_POR_TABLA = """
    SELECT column_name,
           data_type,
           character_maximum_length,
           is_nullable,
           column_default,
           ordinal_position
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = %s
    ORDER BY ordinal_position;
"""

SQL_FILAS_POR_TABLA = """
    SELECT reltuples::bigint AS estimado
    FROM pg_class
    WHERE oid = quote_ident(%s)::regclass;
"""

SQL_CONTEO_EXACTO = """
    SELECT COUNT(*) AS exacto FROM {};
"""

SQL_SYNC_PENDIENTES = """
    SELECT COUNT(*) AS pendientes,
           COALESCE(MIN(intentos), 0) AS min_intentos,
           COALESCE(MAX(intentos), 0) AS max_intentos
    FROM cola_sincronizacion
    WHERE sincronizado = 0;
"""


def auditar_estructura_supabase() -> list[dict]:
    """Conecta a Supabase y audita todas las tablas críticas."""
    _separador("PASO 2: AUDITORIA DE ESTRUCTURA DE TABLAS (Supabase)")

    resultados: list[dict] = []

    if not DATABASE_URL:
        _warn("DATABASE_URL no disponible. Solo se auditará SQLite local.")
        return auditar_estructura_sqlite_local()

    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # 2a. Listar todas las tablas públicas
        cur.execute(SQL_LISTAR_TABLAS)
        tablas_remotas = {row[0]: {"tamanio": row[1], "comentario": row[2]} for row in cur.fetchall()}

        _info(f"Se encontraron {len(tablas_remotas)} tablas en Supabase.")
        for t in sorted(tablas_remotas.keys()):
            sz = tablas_remotas[t]["tamanio"] or "0 bytes"
            _info(f"  - {t} ({sz})")

        print("")

        # 2b. Verificar presencia de tablas críticas
        for tabla in TABLAS_CRITICAS:
            info_tabla: dict = {
                "tabla": tabla,
                "existe": tabla in tablas_remotas,
                "columnas": [],
                "faltantes": [],
                "filas": None,
                "tipo": None,
            }

            if not info_tabla["existe"]:
                _err(f"Tabla faltante: {tabla}  <- NO EXISTE en Supabase")
                info_tabla["tipo"] = "AUSENTE"
                resultados.append(info_tabla)
                continue

            # Extraer columnas reales
            cur.execute(SQL_COLUMNAS_POR_TABLA, (tabla,))
            columnas_reales = {row[0]: {"tipo": row[1], "nullable": row[2], "default": row[3]} for row in cur.fetchall()}
            info_tabla["columnas"] = columnas_reales

            # Contar filas
            try:
                cur.execute(SQL_CONTEO_EXACTO.format(tabla))
                info_tabla["filas"] = cur.fetchone()[0]
            except Exception:
                cur.execute(SQL_FILAS_POR_TABLA, (tabla,))
                info_tabla["filas"] = cur.fetchone()[0] if cur.rowcount > 0 else 0

            # Chequear columnas obligatorias
            esperadas = COLUMNAS_OBLIGATORIAS.get(tabla, [])
            faltan = [c for c in esperadas if c not in columnas_reales]
            info_tabla["faltantes"] = faltan

            if faltan:
                info_tabla["tipo"] = "INCOMPLETO"
                _warn(f"Tabla '{tabla}' faltan columnas: {', '.join(faltan)}")
            else:
                info_tabla["tipo"] = "OK"
                _ok(f"Tabla '{tabla}': {info_tabla['filas']} filas, {len(columnas_reales)} columnas")

            resultados.append(info_tabla)

        # 2c. Revisar cola de sincronización si existe
        if "cola_sincronizacion" in tablas_remotas:
            cur.execute(SQL_SYNC_PENDIENTES)
            sync_row = cur.fetchone()
            if sync_row and sync_row[0] > 0:
                _warn(f"Hay {sync_row[0]} registros pendientes en cola_sincronizacion remota")
                _info(f"  Intentos min: {sync_row[1]}, max: {sync_row[2]}")
                _info("  Causas posibles: tabla destino no existe, restricciones FK, o payload invalido.")
            else:
                _ok("Cola de sincronizacion remota vacia (sin pendientes)")

        conn.close()

    except Exception as exc:
        _err(f"No se pudo auditar Supabase: {exc}")
        _info("Fallback a auditoria solo de SQLite local...")
        return auditar_estructura_sqlite_local()

    return resultados


def auditar_estructura_sqlite_local() -> list[dict]:
    """Audita las tablas en SQLite local como fallback."""
    _separador("AUDITORIA LOCAL (SQLite)")

    resultados: list[dict] = []
    if not DB_PATH.exists():
        _err(f"Archivo SQLite no encontrado: {DB_PATH}")
        return resultados

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tablas_locales = {row["name"] for row in cur.fetchall()}

        _info(f"SQLite local: {len(tablas_locales)} tablas en {DB_PATH}")

        for tabla in TABLAS_CRITICAS:
            info: dict = {"tabla": tabla, "existe": tabla in tablas_locales, "columnas": [], "faltantes": [], "filas": None, "tipo": None}

            if not info["existe"]:
                _err(f"Tabla faltante en SQLite: {tabla}")
                info["tipo"] = "AUSENTE"
                resultados.append(info)
                continue

            cur.execute(f"PRAGMA table_info({tabla})")
            columnas_reales = {row["name"]: {"tipo": row["type"]} for row in cur.fetchall()}
            info["columnas"] = columnas_reales

            cur.execute(f"SELECT COUNT(*) AS cnt FROM {tabla}")
            info["filas"] = cur.fetchone()["cnt"]

            esperadas = COLUMNAS_OBLIGATORIAS.get(tabla, [])
            faltan = [c for c in esperadas if c not in columnas_reales]
            info["faltantes"] = faltan

            if faltan:
                info["tipo"] = "INCOMPLETO"
                _warn(f"SQLite '{tabla}' faltan columnas: {', '.join(faltan)}")
            else:
                info["tipo"] = "OK"
                _ok(f"SQLite '{tabla}': {info['filas']} filas, {len(columnas_reales)} columnas")

            resultados.append(info)

        # Revisar cola de sincronización local
        if "cola_sincronizacion" in tablas_locales:
            cur.execute("SELECT COUNT(*) AS cnt FROM cola_sincronizacion WHERE sincronizado=0")
            pendientes = cur.fetchone()["cnt"]
            if pendientes > 0:
                _warn(f"Cola de sincronizacion LOCAL tiene {pendientes} registros PENDIENTES")
                cur.execute("SELECT id_sync, tabla, operacion, intentos FROM cola_sincronizacion WHERE sincronizado=0 LIMIT 5")
                for row in cur.fetchall():
                    _info(f"  Sync #{row['id_sync']}: {row['operacion']} en {row['tabla']} (intentos: {row['intentos']})")

    finally:
        conn.close()

    return resultados


# ═══════════════════════════════════════════════════════════════════════
#  PASO 3: LOGS DE INSERCIÓN PRUEBA (CAZA DE ERRORES SILENCIOSOS)
# ═══════════════════════════════════════════════════════════════════════

def insertar_prueba_diagnostico() -> dict:
    """
    Intenta insertar un producto ficticio directamente en Supabase.
    Atrapa el código de error exacto de PostgreSQL.
    Verifica si el backend cae correctamente a SQLite local.
    """
    _separador("PASO 3: PRUEBA DE INSERCION CONTROLADA")

    resultado = {
        "supabase_ok": False,
        "supabase_error": None,
        "pg_error_code": None,
        "pg_error_detail": None,
        "pg_error_hint": None,
        "sqlite_fallback_ok": False,
        "sqlite_fallback_error": None,
    }

    if not DATABASE_URL:
        _warn("DATABASE_URL no disponible. Solo se probara SQLite local.")
        return _insertar_prueba_sqlite_local(resultado)

    # ── 3a. Intentar en Supabase ──
    try:
        import psycopg2
        from psycopg2 import errors as pg_errors

        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # Verificar que insumos existe
        cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='insumos')")
        existe_tabla = cur.fetchone()[0]
        if not existe_tabla:
            _err("La tabla 'insumos' NO EXISTE en Supabase. Ejecuta primero el schema.sql contra Supabase.")
            resultado["supabase_error"] = "Tabla insumos no existe en Supabase"
            conn.close()
            return _insertar_prueba_sqlite_local(resultado)

        # Insertar producto de prueba
        nombre_test = f"Insumo Test Diagnostico {datetime.now().strftime('%H%M%S')}"
        _info(f"Intentando insertar '{nombre_test}' en Supabase...")

        cur.execute(
            "INSERT INTO insumos (nombre, stock_actual, stock_minimo, unidad_medida) "
            "VALUES (%s, %s, %s, %s) RETURNING id_insumo",
            (nombre_test, 100, 10, "unidad")
        )
        id_insertado = cur.fetchone()[0]
        conn.commit()
        conn.close()

        resultado["supabase_ok"] = True
        _ok(f"Insert OK en Supabase. ID asignado: {id_insertado}")

        # Limpiar: borrar el registro de prueba
        try:
            conn2 = psycopg2.connect(DATABASE_URL)
            cur2 = conn2.cursor()
            cur2.execute("DELETE FROM insumos WHERE id_insumo = %s", (id_insertado,))
            conn2.commit()
            conn2.close()
            _ok(f"Registro de prueba eliminado (id={id_insertado})")
        except Exception:
            _warn(f"No se pudo limpiar el registro de prueba (id={id_insertado}). Puede quedar huerfano.")

        return resultado

    except Exception as exc:
        resultado["supabase_error"] = str(exc)
        resultado["supabase_ok"] = False

        # Extraer código PostgreSQL detallado
        exc_str = str(exc)
        if hasattr(exc, "pgcode"):
            resultado["pg_error_code"] = exc.pgcode
        if hasattr(exc, "pgerror"):
            resultado["pg_error_detail"] = exc.pgerror

        _err(f"Insercion en Supabase FALLIDA: {exc}")

        # Analizar tipo de error
        exc_lower = exc_str.lower()
        if "foreign key" in exc_lower or "violates foreign key" in exc_lower:
            resultado["pg_error_hint"] = "FOREIGN KEY VIOLATION: el valor de una FK no existe en la tabla padre"
            _err("  Causa: Violacion de clave foranea. Revisa las referencias a tablas padre.")
        elif "not null" in exc_lower:
            resultado["pg_error_hint"] = "NOT NULL CONSTRAINT: una columna obligatoria esta ausente en el INSERT"
            _err("  Causa: Columna NOT NULL sin valor por defecto.")
        elif "unique" in exc_lower or "duplicate key" in exc_lower:
            resultado["pg_error_hint"] = "UNIQUE CONSTRAINT: el valor ya existe en la tabla"
            _err("  Causa: Violacion de restriccion UNIQUE.")
        elif "check" in exc_lower:
            resultado["pg_error_hint"] = "CHECK CONSTRAINT: el valor no cumple una restriccion CHECK"
            _err("  Causa: Violacion de restriccion CHECK (ej: categoria invalida, valor negativo).")
        elif "type" in exc_lower or "cannot be cast" in exc_lower:
            resultado["pg_error_hint"] = "TYPE MISMATCH: tipo de dato incompatible entre SQLite y PostgreSQL"
            _err("  Causa: Descalce de tipos. Ej: SQLite acepta texto donde PostgreSQL espera numeric.")
        elif "does not exist" in exc_lower:
            resultado["pg_error_hint"] = "RELATION NOT FOUND: la tabla no existe en Supabase"
            _err("  Causa: La tabla no existe o no esta en el schema public.")
        elif "permission" in exc_lower or "denied" in exc_lower:
            resultado["pg_error_hint"] = "PERMISSION DENIED: el usuario no tiene permisos de escritura"
            _err("  Causa: Permisos insuficientes en Supabase. Usa la service_role_key si es necesario.")

        # ── 3b. Verificar fallback a SQLite ──
        _info("Verificando fallback a SQLite local...")
        return _insertar_prueba_sqlite_local(resultado)


def _insertar_prueba_sqlite_local(resultado_previo: dict) -> dict:
    """Intenta insertar el mismo producto en SQLite local."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA foreign_keys=ON")

        nombre_test = f"Insumo Test Diagnostico SQLite {datetime.now().strftime('%H%M%S')}"
        conn.execute(
            "INSERT INTO insumos (nombre, stock_actual, stock_minimo, unidad_medida) "
            "VALUES (?, ?, ?, ?)",
            (nombre_test, 100, 10, "unidad")
        )
        id_local = conn.lastrowid
        conn.commit()
        conn.close()

        resultado_previo["sqlite_fallback_ok"] = True
        _ok(f"Insert OK en SQLite local. ID: {id_local}")

        # Limpiar
        conn2 = sqlite3.connect(str(DB_PATH))
        conn2.execute("DELETE FROM insumos WHERE id_insumo = ?", (id_local,))
        conn2.commit()
        conn2.close()

    except Exception as exc2:
        resultado_previo["sqlite_fallback_error"] = str(exc2)
        resultado_previo["sqlite_fallback_ok"] = False
        _err(f"FALLBACK a SQLite TAMBIEN FALLO: {exc2}")
        _err("  -> La aplicacion se quedara sin base de datos operable!")

    return resultado_previo


# ═══════════════════════════════════════════════════════════════════════
#  PASO 4: SOLUCION AL PROBLEMA DE CONTENEDORES EFIMEROS
# ═══════════════════════════════════════════════════════════════════════

def inicializar_sqlite_desde_supabase() -> dict:
    """
    Rutina de inicialización que fuerza la descarga de datos desde Supabase
    hacia SQLite local si detecta que el archivo .db está vacío o no existe.

    Esto resuelve el problema de contenedores efímeros en Streamlit Cloud
    donde el SQLite local se evapora tras cada reinicio o commit.

    USO: llamar al inicio de la app (antes de cualquier otra operación).
    """
    _separador("PASO 4: INICIALIZACION SQLITE DESDE SUPABASE")

    resultado = {
        "db_existia": DB_PATH.exists() and DB_PATH.stat().st_size > 4096,
        "db_vacio": False,
        "tablas_restauradas": 0,
        "filas_copiadas": 0,
        "error": None,
    }

    # Si el archivo existe y tiene datos, no hacer nada
    if resultado["db_existia"]:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cur = conn.execute("SELECT COUNT(*) AS cnt FROM usuarios")
            count = cur.fetchone()[0]
            if count > 0:
                _ok(f"SQLite local OK: {count} usuarios, no requiere restauracion.")
                conn.close()
                return resultado
        except Exception:
            pass
        conn.close()

    resultado["db_vacio"] = True
    _warn("SQLite local vacio o inexistente. Intentando restaurar desde Supabase...")

    if not DATABASE_URL:
        _warn("DATABASE_URL no disponible. No se puede restaurar.")
        _info("Se creara un SQLite con datos de semilla locales.")
        _crear_sqlite_desde_schema_local()
        return resultado

    # Conectar a Supabase y descargar todas las tablas
    try:
        import psycopg2

        pg_conn = psycopg2.connect(DATABASE_URL)
        pg_cur = pg_conn.cursor()

        # Listar tablas públicas
        pg_cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
        tablas = [row[0] for row in pg_cur.fetchall()]

        # Crear/abrir SQLite
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sl_conn = sqlite3.connect(str(DB_PATH))
        sl_conn.execute("PRAGMA journal_mode=WAL")
        sl_conn.execute("PRAGMA foreign_keys=OFF")  # desactivar temporalmente

        total_filas = 0
        tablas_ok = 0

        for tabla in tablas:
            if tabla.startswith("_") or tabla in ("schema_migrations", "spatial_ref_sys"):
                continue
            try:
                # Obtener columnas de Supabase
                pg_cur.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                    (tabla,)
                )
                columnas = [row[0] for row in pg_cur.fetchall()]
                if not columnas:
                    continue

                # Descargar datos de Supabase
                pg_cur.execute(f'SELECT * FROM "{tabla}"')
                filas = pg_cur.fetchall()

                if not filas:
                    continue

                # Crear tabla en SQLite (DROP + CREATE desde pg_info)
                col_defs = ", ".join(f'"{c}"' for c in columnas)
                sl_conn.execute(f'DROP TABLE IF EXISTS "{tabla}"')
                sl_conn.execute(f'CREATE TABLE IF NOT EXISTS "{tabla}" ({col_defs})')

                # Insertar datos (lote a lote para evitar bloquear)
                placeholders = ", ".join("?" for _ in columnas)
                col_names = ", ".join(f'"{c}"' for c in columnas)
                batch_size = 100
                for i in range(0, len(filas), batch_size):
                    batch = filas[i:i + batch_size]
                    for fila in batch:
                        try:
                            sl_conn.execute(
                                f'INSERT INTO "{tabla}" ({col_names}) VALUES ({placeholders})',
                                fila
                            )
                        except Exception as row_exc:
                            pass  # ignorar filas problemáticas
                sl_conn.commit()
                total_filas += len(filas)
                tablas_ok += 1
                _ok(f"  {tabla}: {len(filas)} filas copiadas")

            except Exception as tabla_exc:
                _warn(f"No se pudo copiar tabla '{tabla}': {tabla_exc}")
                continue

        sl_conn.execute("PRAGMA foreign_keys=ON")
        sl_conn.close()
        pg_conn.close()

        resultado["tablas_restauradas"] = tablas_ok
        resultado["filas_copiadas"] = total_filas
        _ok(f"Restauracion completa: {tablas_ok} tablas, {total_filas} filas copiadas a SQLite.")

    except Exception as exc:
        resultado["error"] = str(exc)
        _err(f"Error restaurando desde Supabase: {exc}")
        _info("Creando SQLite desde schema local como fallback...")
        _crear_sqlite_desde_schema_local()

    return resultado


def _crear_sqlite_desde_schema_local() -> None:
    """Crea un SQLite nuevo ejecutando el schema local."""
    schema_path = LOCAL_SCHEMA_PATH if LOCAL_SCHEMA_PATH.exists() else SCHEMA_SQLITE_PATH
    if not schema_path.exists():
        _err("No se encuentra ningun schema SQLite para crear la base.")
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.executescript("PRAGMA foreign_keys=OFF;")
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
        _ok(f"SQLite creado desde {schema_path.name}")
    except Exception as exc:
        _err(f"Error creando SQLite desde schema: {exc}")


# ═══════════════════════════════════════════════════════════════════════
#  PASO 5: COMPARACION DE ESQUEMAS (SUPABASE vs SCHEMA.SQL)
# ═══════════════════════════════════════════════════════════════════════

def comparar_esquemas() -> dict:
    """Compara las columnas reales de Supabase contra lo esperado en schema.sql."""
    _separador("PASO 5: COMPARACION DE ESQUEMAS (Supabase vs schema.sql)")

    resultado: dict[str, dict] = {}

    if not SUPABASE_SCHEMA_PATH.exists():
        _warn(f"Archivo schema.sql no encontrado: {SUPABASE_SCHEMA_PATH}")
        return resultado

    # Parsear el schema.sql para extraer tablas y columnas esperadas
    with open(SUPABASE_SCHEMA_PATH, "r", encoding="utf-8") as f:
        contenido = f.read()

    tablas_esperadas: dict[str, list[str]] = {}
    tabla_actual = None
    en_create = False

    for linea in contenido.split("\n"):
        linea_strip = linea.strip()
        if linea_strip.startswith("create table if not exists "):
            partes = linea_strip.replace("create table if not exists ", "").split("(")
            tabla_actual = partes[0].strip().strip('"')
            if tabla_actual:
                tablas_esperadas[tabla_actual] = []
                en_create = True
        elif en_create and tabla_actual:
            # Extraer nombre de columna
            if linea_strip.startswith("--") or linea_strip.startswith("/*"):
                continue
            if linea_strip.startswith(");"):
                en_create = False
                tabla_actual = None
                continue
            if linea_strip.startswith("alter table") or linea_strip.startswith("create index") or linea_strip.startswith("insert into") or linea_strip.startswith("update") or linea_strip.startswith("on conflict") or linea_strip.startswith("--"):
                continue
            if linea_strip.startswith("("):
                linea_strip = linea_strip[1:].strip()
            # Separar primera palabra (nombre de columna)
            col_name = linea_strip.split()[0].strip().strip('"').strip(",")
            if col_name and not col_name.startswith(("constraint", "unique", "primary key", "foreign key", "check", "excluded", "values")):
                tablas_esperadas[tabla_actual].append(col_name)

    # Comparar con Supabase real
    if not DATABASE_URL:
        _warn("DATABASE_URL no disponible. No se puede comparar esquemas.")
        return resultado

    try:
        import psycopg2

        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        descalces = 0
        for tabla, cols_esperadas in sorted(tablas_esperadas.items()):
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (tabla,)
            )
            cols_reales = [row[0] for row in cur.fetchall()]

            solo_en_esperado = [c for c in cols_esperadas if c not in cols_reales]
            solo_en_real = [c for c in cols_reales if c not in cols_esperadas]

            entry: dict = {
                "esperadas": len(cols_esperadas),
                "reales": len(cols_reales),
                "solo_en_schema": solo_en_esperado,
                "solo_en_supabase": solo_en_real,
            }
            resultado[tabla] = entry

            if solo_en_esperado or solo_en_real:
                descalces += 1
                if solo_en_esperado:
                    _warn(f"  {tabla}: columnas en schema.sql pero NO en Supabase: {solo_en_esperado}")
                if solo_en_real:
                    _info(f"  {tabla}: columnas extras en Supabase (no en schema.sql): {solo_en_real}")
            else:
                _ok(f"  {tabla}: esquema coincide ({len(cols_reales)} columnas)")

        if descalces == 0:
            _ok("Todos los esquemas coinciden perfectamente.")
        else:
            _warn(f"{descalces} tabla(s) tienen descalces. Revisa las advertencias.")

        conn.close()

    except Exception as exc:
        _err(f"No se pudo comparar esquemas: {exc}")

    return resultado


# ═══════════════════════════════════════════════════════════════════════
#  MAIN — ORQUESTADOR DEL DIAGNÓSTICO
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    print("")
    print("=" * 72)
    print("  AUDITOR SUPABASE — COMANDAPRO ERP / RESTAURANTE PRO")
    print(f"  Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Directorio: {BASE_DIR}")
    print(f"  DB_ENGINE: {DB_ENGINE}")
    print(f"  DATABASE_URL: {'Configurada' if DATABASE_URL else 'NO CONFIGURADA'}")
    print("=" * 72)

    tiene_insert_test = "--insert-test" in sys.argv
    tiene_fix_sync = "--fix-local-sync" in sys.argv

    # Paso 1: Conexión
    conn_result = probar_conexion()

    # Paso 2: Auditoría de tablas
    tablas_result = auditar_estructura_supabase()

    # Paso 5: Comparación de esquemas
    esquemas_result = comparar_esquemas()

    # Paso 3: Prueba de inserción (solo si se pasa --insert-test)
    if tiene_insert_test:
        insertar_prueba_diagnostico()

    # Paso 4: Forzar sincronización local (solo si se pasa --fix-local-sync)
    if tiene_fix_sync:
        inicializar_sqlite_desde_supabase()

    # ── Resumen final ────────────────────────────────────────────────
    _separador("RESUMEN FINAL")

    if not conn_result.get("configurado"):
        _warn("DATABASE_URL no configurada. La app usa solo SQLite local.")
        if DB_PATH.exists():
            _ok(f"SQLite local existe en {DB_PATH}")
        else:
            _warn("SQLite local NO existe. La app se creara en el primer inicio.")
        print("")
        _info("Para configurar Supabase:")
        _info("  1. Copia el schema a Supabase desde: restaurante programa/supabase/schema.sql")
        _info("  2. Configura DATABASE_URL en .env o Streamlit Secrets")
        _info("  3. Cambia DB_ENGINE=postgresql")
        print("")
        return

    # Reporte de tablas
    ausentes = [r for r in tablas_result if r.get("tipo") == "AUSENTE"]
    incompletas = [r for r in tablas_result if r.get("tipo") == "INCOMPLETO"]
    ok_count = [r for r in tablas_result if r.get("tipo") == "OK"]

    _info(f"Tablas OK: {len(ok_count)}")

    if ausentes:
        _err(f"Tablas AUSENTES en Supabase: {[r['tabla'] for r in ausentes]}")
        _info("Causa probable: el schema.sql de Supabase no se ejecuto completamente.")
        _info(f"Usa el archivo: {SUPABASE_SCHEMA_PATH}")

    if incompletas:
        _warn(f"Tablas INCOMPLETAS: {[r['tabla'] for r in incompletas]}")
        for inc in incompletas:
            _info(f"  {inc['tabla']}: faltan columnas {inc['faltantes']}")

    if not ausentes and not incompletas:
        _ok("Todas las tablas estan completas y correctas.")

    print("")
    _info("PROXIMOS PASOS RECOMENDADOS:")
    _info("  1. Streamlit Cloud → Settings → Secrets: agrega DATABASE_URL, SUPABASE_URL, SUPABASE_ANON_KEY")
    _info("  2. En el panel de Supabase, verifica que el schema.sql se haya ejecutado en SQL Editor")
    _info("  3. Agrega SUPABASE_SERVICE_ROLE_KEY para operaciones administrativas")
    _info("  4. Tras cada deploy en Streamlit Cloud, ejecuta --fix-local-sync si el SQLite aparece vacio")
    print("")


# ═══════════════════════════════════════════════════════════════════════
#  BLOQUE DE INICIALIZACION PARA CONTENEDORES EFIMEROS
#  (copia este bloque al inicio de app.py o main.py)
# ═══════════════════════════════════════════════════════════════════════

BLOQUE_INICIALIZACION = '''
# ============================================================
# BLOQUE ANTI-CONTENEDOR-EFIMERO — Streamlit Cloud
# Garantiza que SQLite local siempre tenga datos aunque el
# contenedor se haya destruido tras un commit o inactividad.
# ============================================================
import os, sqlite3
from pathlib import Path

_DB_DIR = Path(__file__).parent / "data"
_DB_PATH = _DB_DIR / "restaurante.db"
_DATABASE_URL = os.environ.get("DATABASE_URL", "") or os.environ.get("SUPABASE_DB_URL", "")

def _asegurar_sqlite_local():
    \"\"\"Si el .db local esta vacio o no existe, lo clona desde Supabase.\"\"\"
    if not _DATABASE_URL:
        return  # no hay cloud, usar SQLite local normal

    necesita_restauracion = False
    if not _DB_PATH.exists() or _DB_PATH.stat().st_size < 4096:
        necesita_restauracion = True
    else:
        try:
            conn = sqlite3.connect(str(_DB_PATH))
            cur = conn.execute("SELECT COUNT(*) AS cnt FROM usuarios")
            if cur.fetchone()[0] == 0:
                necesita_restauracion = True
            conn.close()
        except Exception:
            necesita_restauracion = True

    if not necesita_restauracion:
        return

    import warnings
    warnings.warn("SQLite local vacio. Restaurando desde Supabase...")

    try:
        import psycopg2
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        pg_conn = psycopg2.connect(_DATABASE_URL)
        pg_cur = pg_conn.cursor()

        pg_cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_type='BASE TABLE'
            ORDER BY table_name
        """)
        tablas = [r[0] for r in pg_cur.fetchall()]

        sl_conn = sqlite3.connect(str(_DB_PATH))
        sl_conn.execute("PRAGMA foreign_keys=OFF")

        for tabla in tablas:
            if tabla.startswith("_"):
                continue
            try:
                pg_cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                    (tabla,)
                )
                cols = [r[0] for r in pg_cur.fetchall()]
                if not cols:
                    continue

                pg_cur.execute(f'SELECT * FROM "{tabla}"')
                filas = pg_cur.fetchall()
                if not filas:
                    continue

                col_defs = ", ".join(f'"{c}"' for c in cols)
                sl_conn.execute(f'DROP TABLE IF EXISTS "{tabla}"')
                sl_conn.execute(f'CREATE TABLE "{tabla}" ({col_defs})')

                ph = ", ".join("?" for _ in cols)
                cn = ", ".join(f'"{c}"' for c in cols)
                for fila in filas:
                    try:
                        sl_conn.execute(f'INSERT INTO "{tabla}" ({cn}) VALUES ({ph})', fila)
                    except Exception:
                        pass
                sl_conn.commit()
            except Exception:
                continue

        sl_conn.execute("PRAGMA foreign_keys=ON")
        sl_conn.close()
        pg_conn.close()
        warnings.warn(f"SQLite restaurado desde Supabase ({len(tablas)} tablas).")

    except Exception as exc:
        warnings.warn(f"No se pudo restaurar SQLite desde Supabase: {exc}")

_asegurar_sqlite_local()
# ============================================================
'''


# ═══════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDiagnostico interrumpido por el usuario.")
        sys.exit(1)
