#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
forzar_carga_supabase.py — Carga forzada de los 30 platos premium
directamente contra Supabase via psycopg2.

REQUISITO: tener DATABASE_URL configurada en .env o variable de entorno.
Formato: postgresql://user:password@db.xxxxx.supabase.co:5432/postgres?sslmode=require

USO:
    python forzar_carga_supabase.py                          # vista previa
    python forzar_carga_supabase.py --execute                 # insertar en Supabase
    python forzar_carga_supabase.py --execute --precio 15000  # precio general
"""

import os
import sys
from pathlib import Path

# Cargar .env manualmente
ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    with open(ENV_PATH, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, _, v = linea.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL", "")

NUEVO_MENU = {
    "Entradas": [
        "Provolone con mermelada de tomates y pesto, con escabeches y focaccia",
        "Pera asada con queso azul, nueces y miel sobre verdes",
        "Duo empanadas carne cortada a cuchillo / humita y mozzarella",
        "Carpaccio de lomo curado, crema de parmesano, alcaparras, pistacho tostados, focaccia y hojas verdes fritas",
        "Tabla charcuteria de elaboracion propia, quesos, escabeches, alioli de ajo",
    ],
    "Pastas": [
        "Rotolo di tata (de cabrito y verduras)",
        "Lasana de pollo y espinaca al forno",
        "Creps de espinaca y parmesano con finas hierbas",
        "Cintas anchas en tinta de sepia con crema de mariscos",
        "Noquis boniato con manteca y almendras tostadas",
        "Cintas finas al huevo con fileto y estofado",
        "Cintas finas al huevo con crema de hongos de pino",
        "Cintas finas al huevo a la carbonara",
    ],
    "Carnes": [
        "Ojo de bife con aligot de papa y salsa criolla",
        "Ojo de bife con salsa patron",
        "Ojo de bife con salsa de hongos",
        "Lomo en demiglace con terrina de papa y vegetales glaseados",
        "Bondiola ahumada en reduccion de miel y jengibre con batatas rotas",
        "Milanesa de entrecot con fideos al huevo con crema de hierbas",
    ],
    "Pescados": [
        "Salmon rosado con manteca de lima y azafran acompanado de ensalada tibia",
        "Trucha con alcaparras, manteca, naranja y miel, acompanado de papines y verduras salteadas",
        "Pacu con papas rusiticas y hojas verdes acompanados de salsa criolla",
    ],
    "Comidas Criollas": [
        "Locro criollo con verdeo picante", "Humita", "Guiso de lentejas",
    ],
    "Postres": [
        "Tiramisu", "Lingote de chocolate", "Flan tradicional",
        "Panna cotta con frutos rojos", "Tarta vasca",
    ],
}

PRECIOS = {"Entradas": 12000, "Pastas": 15000, "Carnes": 22000,
           "Pescados": 18000, "Comidas Criollas": 13000, "Postres": 8000}


def main():
    args = sys.argv[1:]
    execute = "--execute" in args
    precio_gral = None
    for a in args:
        if a.startswith("--precio"):
            try:
                precio_gral = float(a.split("=")[-1])
            except (ValueError, IndexError):
                pass

    print("=" * 65)
    print("  CARGA FORZADA A SUPABASE — EL PATRON")
    print("=" * 65)

    if not DATABASE_URL:
        print("\n  [ERROR] DATABASE_URL no configurada.")
        print("  Agregala a .env o como variable de entorno:")
        print('    DATABASE_URL=postgresql://user:pass@db.xxx.supabase.co:5432/postgres?sslmode=require')
        sys.exit(1)

    # Vista previa
    total_platos = sum(len(v) for v in NUEVO_MENU.values())
    print(f"\n  Platos a insertar: {total_platos}")

    if not execute:
        for cat, platos in NUEVO_MENU.items():
            p = precio_gral or PRECIOS.get(cat, 0)
            print(f"  {cat}: {len(platos)} platos a ${p:,.0f}")
        print("\n  Modo vista previa. Agrega --execute para insertar en Supabase.")
        return

    # Ejecutar
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # PASO A: Eliminar CHECK constraint antiguo
        print("\n  [1/3] Eliminando CHECK constraint antiguo...")
        cur.execute("""
            DO $$ DECLARE cname text; BEGIN
                SELECT conname INTO cname FROM pg_constraint
                WHERE conrelid = 'public.productos_menu'::regclass AND contype = 'c';
                IF cname IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE public.productos_menu DROP CONSTRAINT %I', cname);
                    RAISE NOTICE 'CHECK % dropped', cname;
                END IF;
            END $$;
        """)
        conn.commit()
        print("  [OK] Constraints eliminados.")

        # PASO B: Crear indice unico si no existe
        print("  [2/3] Asegurando indice unico en nombre...")
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_menu_nombre_unique
                ON public.productos_menu (lower(trim(nombre)))
        """)
        conn.commit()
        print("  [OK] Indice unico listo.")

        # PASO C: Insertar todos los platos con ON CONFLICT
        print("  [3/3] Insertando 30 platos premium...")
        insertados = 0
        actualizados = 0
        for cat, platos in NUEVO_MENU.items():
            precio = precio_gral or PRECIOS.get(cat, 0)
            for nombre in platos:
                cur.execute("""
                    INSERT INTO public.productos_menu (nombre, precio_venta, categoria, activo)
                    VALUES (%s, %s, %s, 1)
                    ON CONFLICT (lower(trim(nombre))) DO UPDATE SET
                        precio_venta = CASE WHEN EXCLUDED.precio_venta > 0 THEN EXCLUDED.precio_venta ELSE productos_menu.precio_venta END,
                        categoria = EXCLUDED.categoria,
                        activo = 1
                """, (nombre.strip(), precio, cat))
                if cur.rowcount > 0 and "UPDATE" in cur.statusmessage:
                    actualizados += 1
                else:
                    insertados += 1

        conn.commit()

        # Verificar resultado
        cur.execute("SELECT COUNT(*) FROM public.productos_menu")
        total_final = cur.fetchone()[0]
        cur.execute("SELECT categoria, COUNT(*) FROM public.productos_menu GROUP BY categoria ORDER BY categoria")
        rows = cur.fetchall()
        conn.close()

        print(f"\n  [OK] Carga completada.")
        print(f"  Total en Supabase: {total_final} platos")
        print(f"  Nuevos: {insertados}, Actualizados: {actualizados}")
        for cat, cnt in rows:
            print(f"    {cat}: {cnt}")

    except Exception as e:
        print(f"\n  [ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
