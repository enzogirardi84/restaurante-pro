"""Diagnostico de conexion Supabase/PostgreSQL.

Usa DATABASE_URL o SUPABASE_DB_URL desde el entorno. No guarda credenciales
en el repositorio ni imprime la URL completa.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse


def _masked_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    host = parsed.hostname or "sin-host"
    port = parsed.port or 5432
    user = parsed.username or "sin-usuario"
    dbname = parsed.path.lstrip("/") or "postgres"
    return f"{parsed.scheme}://{user}:***@{host}:{port}/{dbname}"


def main() -> int:
    dsn = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or "").strip()
    print("=" * 60)
    print("DIAGNOSTICO DE CONEXION SUPABASE")
    print("=" * 60)

    if not dsn:
        print("[SKIP] No hay DATABASE_URL ni SUPABASE_DB_URL configurada.")
        print("       Define una de esas variables para probar la conexion real.")
        return 0

    try:
        import psycopg2
    except ImportError:
        print("[ERROR] Falta psycopg2. Instala psycopg2-binary.")
        return 1

    print(f"[INFO] psycopg2 version: {psycopg2.__version__}")
    print(f"[INFO] DSN: {_masked_dsn(dsn)}")

    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT current_database(), version();")
        dbname, version = cur.fetchone()
        conn.close()
        print("[OK] Conexion exitosa")
        print(f"     Base: {dbname}")
        print(f"     Version: {version[:80]}...")
        return 0
    except Exception as exc:
        error = str(exc).lower()
        if "password" in error or "authentication" in error:
            print("[ERROR] Autenticacion fallida. Revisa usuario/password en Secrets.")
        elif "connection refused" in error or "timeout" in error:
            print("[ERROR] Timeout o puerto no disponible. Revisa host, puerto y pooler.")
        elif "ssl" in error:
            print("[ERROR] Error SSL. Agrega sslmode=require a la URL.")
        else:
            print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
