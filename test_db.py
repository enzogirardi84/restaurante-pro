"""Diagnóstico de conexión Supabase PostgreSQL."""
import sys, os

# Configurar manualmente (esto NO sube a Streamlit Cloud)
DB_USER = "postgres.jyisecrmuiebuvtgqjhy"
DB_PASS = "Enzo37108100"
DB_HOST = "aws-1-us-east-1.pooler.supabase.com"

print("=" * 60)
print("DIAGNÓSTICO DE CONEXIÓN SUPABASE")
print("=" * 60)

# 1. Verificar que psycopg2 está instalado
try:
    import psycopg2
    print(f"[OK] psycopg2 versión: {psycopg2.__version__}")
except ImportError:
    print("[INSTALAR] pip install psycopg2-binary")
    sys.exit(1)

# 2. Probar conexión con puerto 5432
for puerto, nombre in [(5432, "Directo"), (6543, "Pooler")]:
    print(f"\n--- Probando conexión {nombre} (puerto {puerto}) ---")
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=puerto,
            dbname="postgres",
            user=DB_USER,
            password=DB_PASS,
            sslmode="require",
            connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]
        cur.execute("SELECT current_database();")
        dbname = cur.fetchone()[0]
        print(f"  ✅ CONECTADO")
        print(f"  Base: {dbname}")
        print(f"  Versión: {version[:60]}...")
        conn.close()
    except Exception as e:
        error = str(e).lower()
        if "password" in error or "authentication" in error:
            print(f"  ❌ Contraseña incorrecta")
        elif "connection refused" in error or "timeout" in error:
            print(f"  ❌ Puerto {puerto} no responde")
        elif "ssl" in error:
            print(f"  ❌ Error SSL")
        else:
            print(f"  ❌ {e}")

print("\n" + "=" * 60)
print("SI CONECTA LOCALMENTE pero falla en Streamlit Cloud:")
print("  → La DATABASE_URL en Secrets tiene la contraseña mal escrita")
print("  → O la contraseña tiene caracteres no codificados (@ # % etc)")
print()
print("SI NO CONECTA LOCALMENTE:")
print("  → La contraseña es incorrecta")
print("  → O el proyecto Supabase está en pausa (check en supabase.com)")
print("=" * 60)
