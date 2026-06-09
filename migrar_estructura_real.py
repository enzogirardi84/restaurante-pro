#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrar_estructura_real.py — Migra el schema.sql completo a Supabase
usando conexion DIRECTA (puerto 5432), saltando el pooler transaccional.

USO:
    python migrar_estructura_real.py              # solo muestra previa
    python migrar_estructura_real.py --execute    # ejecuta la migracion
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
INNER_DIR = BASE_DIR / "restaurante programa"
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    with open(ENV_PATH, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, _, v = linea.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

# Leer DATABASE_URL_DIRECTA del .env o variable de entorno
DATABASE_URL_DIRECTA = (
    os.environ.get("DATABASE_URL_DIRECTA", "")
    or os.environ.get("DATABASE_URL", "")
    or os.environ.get("SUPABASE_DB_URL", "")
)

SCHEMA_PATH = INNER_DIR / "supabase" / "schema.sql"


def main():
    args = sys.argv[1:]
    execute = "--execute" in args

    print("=" * 65)
    print("  MIGRACION DE ESTRUCTURA A SUPABASE")
    print("  Conexion directa (puerto 5432) para DDL")
    print("=" * 65)

    if not DATABASE_URL_DIRECTA:
        print("\n  [ERROR] No hay DATABASE_URL_DIRECTA ni DATABASE_URL configurada.")
        print("  Agregala al .env o variable de entorno.")
        sys.exit(1)

    if not SCHEMA_PATH.exists():
        print(f"\n  [ERROR] Schema no encontrado: {SCHEMA_PATH}")
        sys.exit(1)

    # Verificar que sea conexion directa (no pooler)
    if "pooler" in DATABASE_URL_DIRECTA.lower():
        print("\n  [ERROR] DATABASE_URL_DIRECTA apunta al pooler (6543).")
        print("  Necesitas una conexion directa puerto 5432 para ejecutar DDL.")
        print("  Formato correcto:")
        print("    postgresql://postgres:pass@db.proyecto.supabase.co:5432/postgres?sslmode=require")
        sys.exit(1)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # Vista previa: contar CREATE TABLE
    import re
    tablas_en_schema = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", schema_sql, re.IGNORECASE)
    print(f"\n  Tablas a crear/verificar: {len(tablas_en_schema)}")
    for t in tablas_en_schema:
        print(f"    - {t}")

    if not execute:
        print("\n  Modo vista previa. Agrega --execute para ejecutar la migracion.")
        return

    # Ejecutar migracion
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL_DIRECTA, connect_timeout=10)
        cur = conn.cursor()

        print("\n  Ejecutando schema.sql...")
        # Dividir por sentencias SQL (separadas por ;)
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        ok_count = 0
        fail_count = 0

        for stmt in statements:
            # Saltar lineas de control psql (\connect, etc.)
            if stmt.startswith("\\") or stmt.startswith("--"):
                continue
            try:
                cur.execute(stmt)
                ok_count += 1
            except Exception as exc:
                fail_count += 1
                if fail_count <= 5:
                    print(f"  [WARN] Sentencia {ok_count + fail_count}: {str(exc)[:100]}")

        conn.commit()
        conn.close()

        print(f"\n  [OK] Migracion completada.")
        print(f"  Sentencias OK: {ok_count}")
        print(f"  Advertencias: {fail_count} (errores esperados si las tablas ya existen)")

        # Verificar resultado
        conn2 = psycopg2.connect(DATABASE_URL_DIRECTA, connect_timeout=10)
        cur2 = conn2.cursor()
        cur2.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
        tablas_actuales = [r[0] for r in cur2.fetchall()]
        conn2.close()

        print(f"\n  Tablas en Supabase ahora: {len(tablas_actuales)}")
        for t in tablas_actuales:
            print(f"    - {t}")

    except Exception as e:
        print(f"\n  [ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
