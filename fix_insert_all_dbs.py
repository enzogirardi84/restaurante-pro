"""Inserta los 30 platos en las DBs correctas que ya tienen el schema completo."""
import sqlite3, os, sys
sys.path.insert(0, "restaurante programa")
from database import get_connection

PLATOS = {
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
        "Locro criollo con verdeo picante",
        "Humita",
        "Guiso de lentejas",
    ],
    "Postres": [
        "Tiramisu",
        "Lingote de chocolate",
        "Flan tradicional",
        "Panna cotta con frutos rojos",
        "Tarta vasca",
    ],
}

PRECIOS = {
    "Entradas": 12000, "Pastas": 15000, "Carnes": 22000,
    "Pescados": 18000, "Comidas Criollas": 13000, "Postres": 8000,
}

dbs = [
    "data/restaurante.db",
    "data/comandapro.db",
    "restaurante programa/data/restaurante.db",
]

for db_path in dbs:
    if not os.path.exists(db_path):
        print(f"{db_path}: NO EXISTE, salteando")
        continue
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=OFF")
    # Leer esquema actual para saber cuantas columnas tiene
    info = conn.execute("PRAGMA table_info(productos_menu)").fetchall()
    cols = [r[1] for r in info]
    has_url = "url_imagen" in cols
    col_defs = ", ".join(f"{r[1]} {r[2]}" for r in info)
    col_names = ", ".join(cols)
    placeholders = ", ".join("?" for _ in cols)
    # Recrear la tabla SIN el CHECK constraint
    conn.execute("DROP TABLE IF EXISTS productos_menu_new")
    conn.execute(f"CREATE TABLE productos_menu_new ({col_defs})")
    conn.execute(f"INSERT INTO productos_menu_new ({col_names}) SELECT {col_names} FROM productos_menu")
    conn.execute("DROP TABLE productos_menu")
    conn.execute("ALTER TABLE productos_menu_new RENAME TO productos_menu")
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pm_nombre ON productos_menu (nombre)")
    except Exception:
        pass
    conn.commit()

    total = 0
    # Leer columnas actualizadas
    info2 = conn.execute("PRAGMA table_info(productos_menu)").fetchall()
    cols2 = [r[1] for r in info2]
    has_url2 = "url_imagen" in cols2
    for cat, platos in PLATOS.items():
        for nombre in platos:
            try:
                if has_url2:
                    conn.execute(
                        "INSERT OR IGNORE INTO productos_menu (nombre, precio_venta, categoria, activo, url_imagen) VALUES (?, ?, ?, 1, '')",
                        (nombre, PRECIOS[cat], cat),
                    )
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO productos_menu (nombre, precio_venta, categoria, activo) VALUES (?, ?, ?, 1)",
                        (nombre, PRECIOS[cat], cat),
                    )
                total += 1
            except Exception as e:
                print(f"  ERROR {db_path} - {nombre[:40]}: {e}")
    conn.commit()
    conn.close()
    c2 = sqlite3.connect(db_path)
    final = c2.execute("SELECT COUNT(*) FROM productos_menu").fetchone()[0]
    c2.close()
    print(f"{db_path}: +{total} nuevas, {final} platos totales")
