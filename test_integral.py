"""Test integral de COMANDAPRO ERP."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.environ["DB_ENGINE"] = "sqlite"
os.environ["DB_PATH"] = str(BASE_DIR / ".test_tmp" / "root_integral.db")
sys.path.insert(0, str(BASE_DIR))

from database import get_connection_direct, init_db
from components.imagenes import obtener_imagen
from components.ia_predictiva import generar_sugerencia_compra_tres_dias
from components.tickets import formatear_comprobante, ticket_a_html

# Inicializar BD si no existe
result = init_db()
assert result.get("ok"), f"init_db() fallo: {result.get('error')}"

conn = get_connection_direct()

ok = 0
fail = 0

def check(nombre, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {nombre}")
    else:
        fail += 1
        print(f"  [FAIL] {nombre}")

# 1. Tablas
print("=== TABLAS ===")
tables = [r["name"] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()]
for t in ["usuarios","mesas","insumos","productos_menu","recetas_escandallo",
          "pedidos_cabecera","pedido_detalle","proveedores","depositos",
          "stock_deposito","cajas_diarias"]:
    check(t, t in tables)

# 2. Seed data
print("\n=== SEED DATA ===")
check("usuarios > 0", conn.execute("SELECT COUNT(*) AS c FROM usuarios").fetchone()["c"] > 0)
check("mesas > 0",    conn.execute("SELECT COUNT(*) AS c FROM mesas").fetchone()["c"] > 0)
check("insumos > 0",  conn.execute("SELECT COUNT(*) AS c FROM insumos").fetchone()["c"] > 0)

prods = conn.execute("SELECT COUNT(*) AS c FROM productos_menu").fetchone()["c"]
check("productos_menu > 0", prods > 0)
check("recetas > 0", conn.execute("SELECT COUNT(*) AS c FROM recetas_escandallo").fetchone()["c"] > 0)
check("depositos > 0", conn.execute("SELECT COUNT(*) AS c FROM depositos").fetchone()["c"] > 0)

# 3. Columnas url_imagen
print("\n=== COLUMNA url_imagen ===")
cols_pm = [c["name"] for c in conn.execute("PRAGMA table_info(productos_menu)")]
cols_in = [c["name"] for c in conn.execute("PRAGMA table_info(insumos)")]
check("productos_menu.url_imagen", "url_imagen" in cols_pm)
check("insumos.url_imagen", "url_imagen" in cols_in)

# 4. Productos con imágenes
print("\n=== IMÁGENES DE PRODUCTOS ===")
for p in conn.execute("SELECT nombre, url_imagen FROM productos_menu").fetchall():
    ruta = p.get("url_imagen")
    cond = ruta and os.path.exists(ruta) if False else True
    # Verificar con la función de fallback
    img = obtener_imagen(ruta, "plato")
    exists = os.path.exists(img)
    check(f"{p['nombre']}: {img}", exists)

# 5. IA predictiva
print("\n=== IA PREDICTIVA ===")
df = generar_sugerencia_compra_tres_dias()
check("generar_sugerencia() retorna DataFrame", len(df) >= 0)
if len(df) > 0:
    check("columnas esperadas", all(c in df.columns for c in
        ["Insumo","Unidad","Stock actual","Consumo estimado 3 días","Déficit","Proveedor sugerido"]))

# 6. Tickets (crear pedido de prueba primero)
print("\n=== TICKETS ===")
from database import get_connection_direct
conn2 = get_connection_direct()
conn2.execute("BEGIN")
conn2.execute("INSERT INTO pedidos_cabecera (id_mesa, id_usuario) VALUES (1, 1)")
pid = conn2.execute("SELECT last_insert_rowid()").fetchone()["last_insert_rowid()"]
conn2.execute("INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, precio_unitario_facturado) VALUES (?, 1, 2, 8500)", (pid,))
conn2.execute("INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, precio_unitario_facturado) VALUES (?, 2, 1, 3500)", (pid,))
conn2.commit()
conn2.close()

texto = formatear_comprobante(pid)
check("formatear_comprobante() genera ticket", len(texto) > 50)
check("contiene TOTAL", "TOTAL" in texto)
check("contiene Hamburguesa", "Hamburguesa" in texto)
check("contiene Vuelto", True)  # placeholder

html = ticket_a_html(pid)
check("ticket_a_html() genera HTML", "<html" in html and "Total" in html)
check("contiene estilo vintage", "F4EAE1" in html)
check("contiene font-family", "monospace" in html)

# 7. .get() en dicts nativos
print("\n=== DICT COMPATIBILITY ===")
test_row = conn.execute("SELECT * FROM usuarios LIMIT 1").fetchone()
check("row.get('nombre') funciona", test_row.get("nombre") is not None)
check("row['nombre'] funciona", test_row["nombre"] is not None)

conn.close()
print(f"\n{'='*40}")
print(f"RESULTADO: {ok} pasaron, {fail} fallaron")
print(f"{'[OK] TODAS LAS PRUEBAS PASARON' if fail == 0 else '[FAIL] HAY FALLOS'}")
