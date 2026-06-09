#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verificar_despliegue_total.py — Auditoria final de integridad
para "El Patron / Restaurante Pro".

Verifica:
  1. Git: archivos clave pusheados, contenido esperado
  2. Supabase: estructura tablas, categorias, conteo platos
  3. KDS: query de pedidos activos no explota

USO:
    python verificar_despliegue_total.py
    python verificar_despliegue_total.py --verbose
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
INNER_DIR = BASE_DIR / "restaurante programa"

# ── Cargar .env ─────────────────────────────────────────────────────────
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    with open(ENV_PATH, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, _, v = linea.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


VERBOSE = "--verbose" in sys.argv
ERRORES = 0
WARNINGS = 0
OKS = 0


def ok(msg: str) -> None:
    global OKS
    OKS += 1
    print(f"  [OK] {msg}")


def warn(msg: str) -> None:
    global WARNINGS
    WARNINGS += 1
    print(f"  [WARN] {msg}")


def err(msg: str) -> None:
    global ERRORES
    ERRORES += 1
    print(f"  [ERROR] {msg}")


def info(msg: str) -> None:
    if VERBOSE:
        print(f"  [INFO] {msg}")


# ═══════════════════════════════════════════════════════════════════
#  PASO 1: VERIFICACION GIT
# ═══════════════════════════════════════════════════════════════════

CHECKS_GIT: list[dict] = [
    {
        "archivo": "views/cocina.py",
        "debe_contener": "@st.fragment(run_every=10)",
        "no_debe_contener": "st.button",
        "desc": "KDS pasivo con fragment auto-refresh, sin botones",
    },
    {
        "archivo": "views/menu.py",
        "debe_contener": "Comidas Criollas",
        "no_debe_contener": None,
        "desc": "Categorias premium en selector del menu",
    },
    {
        "archivo": "cloud_config.py",
        "debe_contener": "st.secrets.get",
        "no_debe_contener": None,
        "desc": "Prioridad st.secrets > os.environ",
    },
    {
        "archivo": "packages.txt",
        "debe_contener": "libpq-dev",
        "no_debe_contener": None,
        "desc": "Dependencias Linux para psycopg2 en Streamlit",
    },
    {
        "archivo": "database.py",
        "debe_contener": "seed_menu_premium",
        "no_debe_contener": None,
        "desc": "Seed automatico de 30 platos premium",
        "inner_only": True,
    },
]


def verificar_git() -> None:
    print("\n" + "=" * 72)
    print("  PASO 1: VERIFICACION GIT (ARCHIVOS Y CONTENIDO)")
    print("=" * 72)

    # 1a. Verificar que estamos en main y actualizados
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=10
        )
        branch = result.stdout.strip()
        ok(f"Rama actual: {branch}")
    except Exception as e:
        err(f"No se pudo determinar rama: {e}")

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=10
        )
        info(f"Ultimo commit local: {result.stdout.strip()}")
    except Exception:
        pass

    # 1b. Verificar que no hay cambios sin commit
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=10
        )
        unstaged = [l for l in result.stdout.strip().split("\n") if l.strip()]
        # Ignorar data/ y backups/ que estan en gitignore
        relevantes = [l for l in unstaged if not l.startswith(" M data/") and not l.startswith("?? backups/")]
        if relevantes:
            warn(f"Archivos sin commit ({len(relevantes)}):")
            for l in relevantes[:5]:
                warn(f"  {l}")
        else:
            ok("Working tree limpio (sin cambios sin commit)")
    except Exception as e:
        warn(f"No se pudo verificar git status: {e}")

    # 1c. Verificar contenido de archivos clave
    for check in CHECKS_GIT:
        archivo = check["archivo"]
        inner_only = check.get("inner_only", False)
        if inner_only:
            ruta = INNER_DIR / archivo
        else:
            ruta = BASE_DIR / archivo
            if not ruta.exists():
                ruta = INNER_DIR / archivo
        if not ruta.exists():
            err(f"Archivo no encontrado: {archivo}")
            continue

        try:
            content = ruta.read_text(encoding="utf-8")
        except Exception as e:
            err(f"No se pudo leer {archivo}: {e}")
            continue

        debe = check["debe_contener"]
        no_debe = check["no_debe_contener"]

        if debe and debe not in content:
            err(f"{archivo}: no contiene '{debe}'")
        elif debe:
            ok(f"{archivo}: contiene '{debe}'")

        if no_debe and no_debe in content:
            err(f"{archivo}: NO DEBE contener '{no_debe}'")
        elif no_debe:
            ok(f"{archivo}: libre de '{no_debe}'")

        info(f"  {check['desc']}")

    # 1d. Verificar que .gitignore no excluya archivos críticos
    gitignore_path = BASE_DIR / ".gitignore"
    if gitignore_path.exists():
        gi_content = gitignore_path.read_text(encoding="utf-8")
        problematicos = ["schema.sql", "database.py", "app.py", "packages.txt", "requirements.txt"]
        for p in problematicos:
            if p in gi_content:
                warn(f".gitignore excluye '{p}' — puede causar ausencia en deploy")
            else:
                info(f".gitignore no excluye '{p}'")


# ═══════════════════════════════════════════════════════════════════
#  PASO 2: VERIFICACION SUPABASE
# ═══════════════════════════════════════════════════════════════════

SUPABASE_URL = os.environ.get("DATABASE_URL", "") or os.environ.get("SUPABASE_DB_URL", "")


def query_supabase(sql: str, params: tuple = ()) -> list[tuple] | None:
    """Ejecuta SQL contra Supabase y retorna filas."""
    try:
        import psycopg2
        conn = psycopg2.connect(SUPABASE_URL)
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return rows
    except ImportError:
        warn("psycopg2 no instalado. No se puede verificar Supabase.")
        return None
    except Exception as e:
        err(f"Supabase query fallo: {e}")
        return None


def verificar_supabase() -> None:
    print("\n" + "=" * 72)
    print("  PASO 2: VERIFICACION SUPABASE (DATOS Y ESTRUCTURA)")
    print("=" * 72)

    if not SUPABASE_URL:
        warn("DATABASE_URL no configurada. No se puede verificar Supabase.")
        info("Para configurar: agregar DATABASE_URL al .env o variable de entorno.")
        info("Formato: postgresql://user:pass@db.xxxx.supabase.co:5432/postgres?sslmode=require")
        return

    # 2a. Verificar conexion
    rows = query_supabase("SELECT version()")
    if rows is None:
        return
    pg_ver = rows[0][0].split(",")[0] if rows else "N/A"
    ok(f"Conexion a Supabase exitosa. Version: {pg_ver}")

    # 2b. Verificar tabla productos_menu existe y columnas
    rows = query_supabase("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'productos_menu'
        ORDER BY ordinal_position
    """)
    if rows is None:
        return
    cols = {r[0]: r[1] for r in rows}
    esperadas = {"id_producto", "nombre", "precio_venta", "categoria", "activo"}
    faltan = esperadas - set(cols.keys())
    if faltan:
        err(f"Faltan columnas en productos_menu: {faltan}")
    else:
        ok("productos_menu tiene todas las columnas esperadas")

    # 2c. Verificar que NO exista CHECK constraint antiguo
    rows = query_supabase("""
        SELECT conname, pg_get_constraintdef(con.oid)
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'productos_menu' AND contype = 'c'
    """)
    if rows:
        for name, defn in rows:
            if "'cocina'" in defn.lower() and "'bebidas'" in defn.lower():
                err(f"CHECK constraint ANTIGUO aun presente: {name}")
            else:
                ok(f"CHECK constraint actualizado: {name}")
    else:
        ok("No hay CHECK constraints en productos_menu (categoria libre)")

    # 2d. Conteo por categoria
    rows = query_supabase("""
        SELECT categoria, COUNT(*) AS cnt
        FROM public.productos_menu
        GROUP BY categoria
        ORDER BY categoria
    """)
    if rows is None:
        return
    total = sum(r[1] for r in rows)
    print(f"  Platos en Supabase: {total} total")
    categorias_premium = {"Entradas", "Pastas", "Carnes", "Pescados", "Comidas Criollas", "Postres"}
    categorias_encontradas = {r[0] for r in rows}
    for cat, cnt in rows:
        marca = "★" if cat in categorias_premium else " "
        print(f"    {marca} {cat}: {cnt} platos")

    faltan_premium = categorias_premium - categorias_encontradas
    if faltan_premium:
        err(f"Categorias premium faltantes en Supabase: {faltan_premium}")
        err("Ejecuta: python cargar_menu_patron.py --execute")
    else:
        ok("Todas las 6 categorias premium estan presentes en Supabase")

    # 2e. Verificar que el indice unico existe
    rows = query_supabase("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'productos_menu' AND indexname LIKE '%nombre%'
    """)
    if rows:
        ok(f"Indice unico en nombre encontrado: {rows[0][0]}")
    else:
        warn("No se encontro indice unico en productos_menu.nombre")

    # 2f. Contar platos con precio > 0
    rows = query_supabase("SELECT COUNT(*) FROM public.productos_menu WHERE precio_venta > 0")
    if rows:
        ok(f"{rows[0][0]} platos tienen precio asignado (> 0)")


# ═══════════════════════════════════════════════════════════════════
#  PASO 3: VERIFICACION KDS (QUERY DE PEDIDOS ACTIVOS)
# ═══════════════════════════════════════════════════════════════════

def verificar_kds() -> None:
    print("\n" + "=" * 72)
    print("  PASO 3: VERIFICACION KDS (QUERY MONITOR PASIVO)")
    print("=" * 72)

    # 3a. Verificar que views/cocina.py existe y tiene fragment
    kds_path = BASE_DIR / "views" / "cocina.py"
    if not kds_path.exists():
        err("views/cocina.py no encontrado en la raiz")
        return
    content = kds_path.read_text(encoding="utf-8")
    if "@st.fragment" in content:
        ok("views/cocina.py usa @st.fragment para auto-refresh")
    else:
        err("views/cocina.py NO usa @st.fragment")
    if "st.button" in content:
        err("views/cocina.py contiene st.button — debe ser pasivo puro")
    else:
        ok("views/cocina.py no tiene botones (KDS pasivo)")

    # 3b. Verificar query KDS contra Supabase
    if SUPABASE_URL:
        rows = query_supabase("""
            SELECT pc.id_pedido, m.numero_mesa, pd.cantidad, pm.nombre, pd.observaciones
            FROM public.pedidos_cabecera pc
            JOIN public.pedido_detalle pd ON pd.id_pedido = pc.id_pedido
            JOIN public.productos_menu pm ON pd.id_producto = pm.id_producto
            JOIN public.mesas m ON pc.id_mesa = m.id_mesa
            WHERE pc.estado_comanda IN ('pendiente', 'en_cocina')
            LIMIT 5
        """)
        if rows is not None:
            ok(f"Query KDS ejecutada correctamente ({len(rows)} filas de prueba)")
            for r in rows:
                info(f"  Mesa {r[1]}: {r[2]}x {r[3]} — Obs: {r[4] or 'N/A'}")
        else:
            # No es error, puede que no haya pedidos activos
            info("Query KDS ejecutada (0 filas = no hay pedidos activos)")
    else:
        info("Sin DATABASE_URL, KDS solo verifica contra SQLite local")

    # 3c. Verificar SQLite local
    try:
        import sqlite3
        local_path = INNER_DIR / "data" / "restaurante.db"
        if local_path.exists():
            conn = sqlite3.connect(str(local_path))
            cur = conn.execute("""
                SELECT pc.id_pedido, m.numero_mesa, pd.cantidad, pm.nombre
                FROM pedidos_cabecera pc
                JOIN pedido_detalle pd ON pd.id_pedido = pc.id_pedido
                JOIN productos_menu pm ON pd.id_producto = pm.id_producto
                JOIN mesas m ON pc.id_mesa = m.id_mesa
                WHERE pc.estado_comanda IN ('pendiente', 'en_cocina')
                LIMIT 5
            """)
            filas = cur.fetchall()
            conn.close()
            ok(f"Query KDS local ejecutada ({len(filas)} filas)")
        else:
            info("SQLite local no encontrado (se crea al primer inicio)")
    except Exception as e:
        warn(f"No se pudo verificar KDS local: {e}")


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    global ERRORES, WARNINGS, OKS

    print("=" * 72)
    print("  VERIFICACION DE DESPLIEGUE TOTAL — EL PATRON")
    print(f"  Fecha: {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Directorio: {BASE_DIR}")
    print("=" * 72)

    verificar_git()
    verificar_supabase()
    verificar_kds()

    print("\n" + "=" * 72)
    print("  RESUMEN FINAL")
    print("=" * 72)
    print(f"  OK:     {OKS}")
    print(f"  WARN:   {WARNINGS}")
    print(f"  ERROR:  {ERRORES}")
    print()

    if ERRORES > 0:
        print("  Hay errores que requieren atencion antes del deploy.")
        sys.exit(1)
    elif WARNINGS > 0:
        print("  Todo ok con advertencias menores. Revisar si aplica.")
    else:
        print("  Despliegue verificado. Todos los sistemas OK.")

    print("")


if __name__ == "__main__":
    main()
