#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cargar_menu_patron.py — Carga masiva de la nueva carta premium
"El Patron" en la base de datos (SQLite local + Supabase via database.py).

USO:
    python cargar_menu_patron.py                    # solo vista previa
    python cargar_menu_patron.py --execute          # ejecuta la insercion
    python cargar_menu_patron.py --execute --precio-carne 15000   # precios custom
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── Agregar los dos directorios al path para importar database.py ──
BASE_DIR = Path(__file__).parent.resolve()
INNER_DIR = BASE_DIR / "restaurante programa"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(INNER_DIR))

# ── Carta premium ────────────────────────────────────────────────────
# Cada entrada: (nombre_plato, precio_base)
NUEVO_MENU = {
    "Entradas": [
        ("Provolone con mermelada de tomates y pesto, con escabeches y focaccia", 0),
        ("Pera asada con queso azul, nueces y miel sobre verdes", 0),
        ("Duo empanadas carne cortada a cuchillo / humita y mozzarella", 0),
        ("Carpaccio de lomo curado, crema de parmesano, alcaparras, pistacho tostados, focaccia y hojas verdes fritas", 0),
        ("Tabla charcuteria de elaboracion propia, quesos, escabeches, alioli de ajo", 0),
    ],
    "Pastas": [
        ("Rotolo di tata (de cabrito y verduras)", 0),
        ("Lasana de pollo y espinaca al forno", 0),
        ("Creps de espinaca y parmesano con finas hierbas", 0),
        ("Cintas anchas en tinta de sepia con crema de mariscos", 0),
        ("Noquis boniato con manteca y almendras tostadas", 0),
        ("Cintas finas al huevo con fileto y estofado", 0),
        ("Cintas finas al huevo con crema de hongos de pino", 0),
        ("Cintas finas al huevo a la carbonara", 0),
    ],
    "Carnes": [
        ("Ojo de bife con aligot de papa y salsa criolla", 0),
        ("Ojo de bife con salsa patron", 0),
        ("Ojo de bife con salsa de hongos", 0),
        ("Lomo en demiglace con terrina de papa y vegetales glaseados", 0),
        ("Bondiola ahumada en reduccion de miel y jengibre con batatas rotas", 0),
        ("Milanesa de entrecot con fideos al huevo con crema de hierbas", 0),
    ],
    "Pescados": [
        ("Salmon rosado con manteca de lima y azafran acompanado de ensalada tibia", 0),
        ("Trucha con alcaparras, manteca, naranja y miel, acompanado de papines y verduras salteadas", 0),
        ("Pacu con papas rusiticas y hojas verdes acompanados de salsa criolla", 0),
    ],
    "Comidas Criollas": [
        ("Locro criollo con verdeo picante", 0),
        ("Humita", 0),
        ("Guiso de lentejas", 0),
    ],
    "Postres": [
        ("Tiramisu", 0),
        ("Lingote de chocolate", 0),
        ("Flan tradicional", 0),
        ("Panna cotta con frutos rojos", 0),
        ("Tarta vasca", 0),
    ],
}

# ── Precios sugeridos por categoria (editar antes de --execute) ───────
PRECIOS_POR_CATEGORIA = {
    "Entradas": 12000,
    "Pastas": 15000,
    "Carnes": 22000,
    "Pescados": 18000,
    "Comidas Criollas": 13000,
    "Postres": 8000,
}


def limpiar_nombre(nombre: str) -> str:
    """Limpia caracteres especiales y normaliza espacios."""
    return " ".join(nombre.strip().split())


def conectar_db():
    """Intenta conectar primero con database.py del inner app, fallback al root."""
    # Intentar import desde restaurante programa (inner)
    try:
        sys.path.insert(0, str(INNER_DIR))
        from database import get_connection, using_postgres, execute
        return get_connection, using_postgres, execute, "inner"
    except ImportError:
        pass
    # Intentar import desde root
    try:
        sys.path.insert(0, str(BASE_DIR))
        from database import get_connection_direct, get_connection
        import config
        _get_conn = get_connection_direct
        def _using_pg():
            return config.DB_ENGINE == "postgresql"
        def _execute(sql, params):
            conn = _get_conn()
            try:
                conn.execute(sql if config.DB_ENGINE == "sqlite" else sql.replace("?", "%s"), params)
                conn.commit()
            finally:
                conn.close()
        return _get_conn, _using_pg, _execute, "root"
    except ImportError as e:
        print(f"  [ERROR] No se pudo importar database.py: {e}")
        print("  Asegurate de ejecutar el script desde la raiz del proyecto.")
        sys.exit(1)


def obtener_precio(nombre: str, categoria: str,
                   precios_por_categoria: dict | None = None,
                   precio_general: float | None = None) -> float:
    """Determina el precio final del plato."""
    if precio_general is not None and precio_general > 0:
        return precio_general
    if precios_por_categoria and categoria in precios_por_categoria:
        return precios_por_categoria[categoria]
    return 0


def generar_reporte_previa() -> dict:
    """Genera un reporte de lo que se insertaria sin ejecutar cambios."""
    total_platos = 0
    reporte = {}
    for categoria, platos in NUEVO_MENU.items():
        precio_cat = PRECIOS_POR_CATEGORIA.get(categoria, 0)
        limpios = [(limpiar_nombre(p[0]), precio_cat if p[1] == 0 else p[1]) for p in platos]
        reporte[categoria] = limpios
        total_platos += len(limpios)
        print(f"  {categoria}: {len(limpios)} platos (${precio_cat:,.0f} c/u)")
        for nombre, precio in limpios:
            print(f"    - {nombre}")
    print(f"\n  TOTAL: {total_platos} platos en {len(reporte)} categorias")
    return reporte


def crear_indice_unico_supabase() -> str:
    """Retorna el SQL necesario para crear el indice unico en Supabase."""
    return """
-- Ejecutar en Supabase SQL Editor antes de la carga masiva
-- Este indice permite que ON CONFLICT (nombre) funcione correctamente

CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_menu_nombre_unique
    ON productos_menu (lower(trim(nombre)));
"""


def crear_indice_unico_sqlite() -> str:
    """Retorna el SQL para SQLite."""
    return """
-- Ejecutar en SQLite local si no existe el indice
CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_menu_nombre
    ON productos_menu (nombre);
"""


def ejecutar_carga(conn_func, using_pg_func, execute_func, db_origen: str,
                   precios_por_categoria: dict | None = None,
                   precio_general: float | None = None,
                   dry_run: bool = False) -> dict:
    """Ejecuta la insercion masiva de todos los platos."""
    resultado = {"insertados": 0, "actualizados": 0, "errores": [], "categorias": {}}

    is_pg = using_pg_func() if callable(using_pg_func) else False
    ph = "%s" if is_pg else "?"

    total_platos_procesados = 0

    for categoria, platos in NUEVO_MENU.items():
        precio_cat = precios_por_categoria.get(categoria, 0) if precios_por_categoria else 0
        insertados_cat = 0
        actualizados_cat = 0

        for nombre_raw, precio_plato in platos:
            nombre = limpiar_nombre(nombre_raw)
            precio = precio_general if (precio_general or 0) > 0 else (precio_plato or precio_cat)

            if dry_run:
                total_platos_procesados += 1
                insertados_cat += 1
                continue

            sql = f"""
                INSERT INTO productos_menu (nombre, precio_venta, categoria, activo)
                VALUES ({ph}, {ph}, {ph}, 1)
                ON CONFLICT(nombre) DO UPDATE SET
                    precio_venta = CASE WHEN excluded.precio_venta > 0 THEN excluded.precio_venta ELSE productos_menu.precio_venta END,
                    categoria = excluded.categoria,
                    activo = 1
            """
            try:
                conn = conn_func()
                try:
                    conn.execute(sql, (nombre, precio, categoria))
                    if not is_pg:
                        conn.commit()
                    if conn.rowcount and conn.rowcount > 0:
                        actualizados_cat += 1
                    else:
                        insertados_cat += 1
                    total_platos_procesados += 1
                except Exception as exc:
                    conn.rollback()
                    resultado["errores"].append(f"{categoria} - {nombre}: {exc}")
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
            except Exception as exc:
                resultado["errores"].append(f"CONEXION - {categoria} - {nombre}: {exc}")

        resultado["categorias"][categoria] = {
            "total": len(platos),
            "insertados": insertados_cat,
            "actualizados": actualizados_cat,
        }

    # Commit final si PostgreSQL (cada conn ya hizo commit)
    resultado["insertados"] = total_platos_procesados - len(resultado["errores"])
    resultado["actualizados"] = 0

    return resultado


def main():
    parser = argparse.ArgumentParser(
        description="Cargar menu premium de El Patron en la base de datos."
    )
    parser.add_argument("--execute", action="store_true",
                        help="Ejecuta la insercion masiva (sin flag solo muestra previa)")
    parser.add_argument("--precio-gral", type=float, default=None,
                        help="Precio general para todos los platos (sobrescribe precios por categoria)")
    parser.add_argument("--precio-entradas", type=float, default=None)
    parser.add_argument("--precio-pastas", type=float, default=None)
    parser.add_argument("--precio-carnes", type=float, default=None)
    parser.add_argument("--precio-pescados", type=float, default=None)
    parser.add_argument("--precio-criollas", type=float, default=None)
    parser.add_argument("--precio-postres", type=float, default=None)

    args = parser.parse_args()

    print("=" * 65)
    print("  CARTA PREMIUM — EL PATRON")
    print("  Carga masiva de menu")
    print("=" * 65)

    # Precios custom por CLI
    precios_custom = {}
    cli_mapping = [
        ("--precio-entradas", "Entradas"),
        ("--precio-pastas", "Pastas"),
        ("--precio-carnes", "Carnes"),
        ("--precio-pescados", "Pescados"),
        ("--precio-criollas", "Comidas Criollas"),
        ("--precio-postres", "Postres"),
    ]
    for cli_flag, categoria in cli_mapping:
        val = getattr(args, cli_flag.lstrip("--").replace("-", "_"), None)
        if val is not None:
            precios_custom[categoria] = val

    precios_finales = precios_custom if precios_custom else PRECIOS_POR_CATEGORIA

    # ── Vista previa ────────────────────────────────────────────────
    print("\n  Vista previa de platos a insertar:\n")
    generar_reporte_previa()

    # ── SQL de indices ──────────────────────────────────────────────
    print("\n" + "-" * 65)
    print("  SQL para indice unico (ejecutar en Supabase SQL Editor):")
    print("-" * 65)
    print(crear_indice_unico_supabase())
    print(crear_indice_unico_sqlite())

    if not args.execute:
        print("-" * 65)
        print("  MODO VISTA PREVIA — No se ejecutaron cambios.")
        print("  Agrega --execute para realizar la insercion.")
        print("-" * 65)
        return

    # ── Ejecutar carga ──────────────────────────────────────────────
    print("\n  Conectando a la base de datos...")
    conn_func, using_pg_func, execute_func, db_origen = conectar_db()
    is_pg = using_pg_func() if callable(using_pg_func) else False
    print(f"  Motor: {'Supabase/PostgreSQL' if is_pg else 'SQLite local'} ({db_origen})")

    print("\n  Ejecutando carga masiva...\n")
    resultado = ejecutar_carga(
        conn_func=conn_func,
        using_pg_func=using_pg_func,
        execute_func=execute_func,
        db_origen=db_origen,
        precios_por_categoria=precios_finales,
        precio_general=args.precio_gral,
    )

    # ── Reporte final ──────────────────────────────────────────────
    print("=" * 65)
    print("  RESULTADO DE LA CARGA")
    print("=" * 65)
    for categoria, stats in resultado["categorias"].items():
        print(f"  {categoria}: {stats['total']} platos")
    print(f"\n  Total procesados: {resultado['insertados']}")

    if resultado["errores"]:
        print(f"\n  [ERROR] {len(resultado['errores'])} error(es):")
        for err in resultado["errores"][:5]:
            print(f"    - {err}")
        if len(resultado["errores"]) > 5:
            print(f"    ... y {len(resultado['errores']) - 5} mas.")

    if not resultado["errores"]:
        print("\n  [OK] Carga completada sin errores.")
        print("  Los platos estan visibles en Menu > Productos existentes.")
        print("  Asigna los precios finales desde st.data_editor() en la UI.")


if __name__ == "__main__":
    main()
