#!/usr/bin/env python3
"""
subir_a_supabase.py — Vuelca SQLite local → Supabase via REST API (upsert).
Usa urllib (stdlib) para evitar dependencias externas.

Uso:
  streamlit run subir_a_supabase.py   → UI en el browser
  python subir_a_supabase.py          → CLI directo
"""

import os, sys, json, sqlite3, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ── Tablas en orden respetando FK (maestros primero) ────────────────────────
TABLAS = [
    "categorias", "usuarios", "productos_menu", "mesas",
    "configuracion_sistema", "insumos", "depositos",
    "recetas_escandallo", "promociones", "proveedores",
    "stock_deposito", "movimientos_stock", "pedidos_cabecera",
    "pedido_detalle", "turnos_personal", "cajas_diarias",
    "movimientos_caja", "accesos_sistema", "sistema_estado",
]

DB_REL = Path("restaurante programa/data/restaurante.db")


def _get_config():
    """Retorna (url, service_key, db_path)."""
    try:
        import streamlit as st
        url  = st.secrets.get("SUPABASE_URL", "") or os.environ.get("SUPABASE_URL", "")
        key  = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        return url, key
    except ImportError:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv("restaurante programa/.env")
    except ImportError:
        pass
    url = os.environ.get("SUPABASE_URL", "")
    key  = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return url, key


def upsert_tabla(base_url, headers, tabla, filas):
    """Envía todas las filas de una tabla mediante POST upsert."""
    if not filas:
        return {"tabla": tabla, "filas": 0, "status": "vacia"}
    body = json.dumps(filas).encode("utf-8")
    req = Request(f"{base_url}/{tabla}", data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=30) as r:
            pass
        return {"tabla": tabla, "filas": len(filas), "status": "ok"}
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        return {"tabla": tabla, "filas": len(filas), "status": f"HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"tabla": tabla, "filas": len(filas), "status": str(e)}


def subir_todo(url, key, db_path=None):
    """Vuelca todas las tablas a Supabase, retorna lista de resultados."""
    if db_path is None:
        db_path = DB_REL
    db_path = Path(db_path)
    if not db_path.exists():
        return [{"tabla": "—", "filas": 0, "status": f"NO EXISTE {db_path}"}]

    base_url = url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    resultados = []
    for tabla in TABLAS:
        filas = []
        try:
            cur = con.execute(f'SELECT * FROM "{tabla}"')
            filas = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            resultados.append({"tabla": tabla, "filas": 0, "status": f"error SQLite: {e}"})
            continue
        res = upsert_tabla(base_url, headers, tabla, filas)
        resultados.append(res)
        time.sleep(0.25)
    con.close()
    return resultados


# ── Modo CLI ────────────────────────────────────────────────────────────────
def _cli():
    url, key = _get_config()
    if not url or not key:
        print("❌  Faltan SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    print(f"🔄  Supabase: {url}")
    print(f"    DB local: {DB_REL}\n")
    resultados = subir_todo(url, key)
    for r in resultados:
        icon = "✅" if r["status"] == "ok" else ("⏭" if r["status"] == "vacia" else "❌")
        print(f"  {icon}  {r['tabla']:25s}  {r['filas']:>4} filas  {r['status']}")
    errores = [r for r in resultados if r["status"] not in ("ok", "vacia")]
    total = sum(r["filas"] for r in resultados if r["status"] == "ok")
    print(f"\n{'❌' if errores else '✅'}  {total} filas subidas, {len(errores)} error(es)")
    sys.exit(1 if errores else 0)


# ── Modo Streamlit ──────────────────────────────────────────────────────────
def _streamlit_ui():
    import streamlit as st
    st.set_page_config(page_title="Subir a Supabase", page_icon="☁️")
    st.title("☁️ Subir SQLite local → Supabase")
    url, key = _get_config()
    st.info(f"Proyecto: `{url}`  |  DB local: `{DB_REL}`")
    if not url or not key:
        st.error("Faltan SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY en secrets")
        return
    if st.button("🚀 Subir todo a Supabase", type="primary"):
        with st.spinner("Subiendo... (puede tardar unos segundos)"):
            resultados = subir_todo(url, key)
        errores = [r for r in resultados if r["status"] not in ("ok", "vacia")]
        if errores:
            st.error(f"{len(errores)} tabla(s) con error")
        else:
            total = sum(r["filas"] for r in resultados if r["status"] == "ok")
            st.success(f"✅ {total} filas subidas sin errores")
        st.dataframe(resultados, use_container_width=True)


if __name__ == "__main__":
    try:
        import streamlit.runtime.scriptrunner as _sr
        if _sr.get_script_run_ctx() is not None:
            _streamlit_ui()
            sys.exit()
    except Exception:
        pass
    _cli()
