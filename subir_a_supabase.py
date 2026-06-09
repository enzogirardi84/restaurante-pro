
"""Sube todas las tablas del SQLite local a Supabase via REST API.
Uso: streamlit run subir_a_supabase.py  (lee secrets de st.secrets)
     python subir_a_supabase.py              (lee de .env)
"""
import os, sys, json, sqlite3, urllib.request, urllib.error, time

DB_PATH = "restaurante programa/data/restaurante.db"

TABLAS = [
    "usuarios", "productos_menu", "mesas", "configuracion_sistema",
    "categorias", "insumos", "recetas_escandallo", "pedidos_cabecera",
    "pedido_detalle", "turnos_personal", "cajas_diarias",
    "movimientos_caja", "proveedores", "movimientos_stock",
    "depositos", "stock_deposito", "promociones",
    "sistema_estado", "accesos_sistema",
]

def obtener_credenciales():
    try:
        import streamlit as st
        supabase_url = (st.secrets.get("SUPABASE_URL", "") or
                        os.environ.get("SUPABASE_URL", ""))
        service_key = (st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "") or
                       os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))
        return supabase_url, service_key
    except ImportError:
        from dotenv import load_dotenv
        load_dotenv("restaurante programa/.env")
        supabase_url = os.environ.get("SUPABASE_URL", "")
        service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        return supabase_url, service_key

def main():
    supabase_url, service_key = obtener_credenciales()
    if not supabase_url or not service_key:
        print("ERROR: SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY requeridas")
        sys.exit(1)

    base_url = supabase_url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    if not os.path.exists(DB_PATH):
        print(f"ERROR: No existe {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    total_upserted = 0
    total_errors = 0

    for tabla in TABLAS:
        try:
            cur = conn.execute(f'SELECT * FROM "{tabla}"')
            filas = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            print(f"  ⏭  {tabla}: ERROR leyendo SQLite — {e}")
            continue

        if not filas:
            print(f"  ⏭  {tabla}: vacía (0 filas)")
            continue

        body = json.dumps(filas).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/{tabla}",
            data=body, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
            print(f"  ✅ {tabla}: {len(filas)} filas upsertadas (HTTP {status})")
            total_upserted += len(filas)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode(errors="replace")[:200]
            print(f"  ❌ {tabla}: HTTP {e.code} — {error_body}")
            total_errors += 1
        except Exception as e:
            print(f"  ❌ {tabla}: {e}")
            total_errors += 1

        time.sleep(0.3)

    conn.close()
    print(f"\n--- Resumen: {total_upserted} filas subidas, {total_errors} errores ---")

if __name__ == "__main__":
    main()
