"""Quick verification that key improvements are in place."""
import sys, os, urllib.request

sys.path.insert(0, r"C:\comandapro_erp")
from database import get_connection_direct
from components.imagenes import obtener_imagen

ok = 0
def check(nombre, cond):
    global ok
    ok += 1
    status = "OK" if cond else "FAIL"
    print(f"  [{status}] {nombre}")

print("=== MEJORAS IMPLEMENTADAS ===")
print()

# 1. Login por usuario/contraseña
conn = get_connection_direct()
user = conn.execute("SELECT username, password_hash FROM usuarios LIMIT 1").fetchone()
check("Login: columna username existe", "username" in user)
check("Login: columna password_hash existe", "password_hash" in user)
check("Login: seed data con hashes", len(user["password_hash"]) == 64)

# 2. Impresión con auto-detección
from components.tickets import _detectar_puerto, ticket_a_html
check("Tickets: auto-detect puertos", callable(_detectar_puerto))
check("Tickets: export HTML vintage", "F4EAE1" in ticket_a_html(1))

# 3. Medios de pago en caja
conn.close()

# 4. Imágenes con fallback
check("Imagenes: fallback default_plato", obtener_imagen(None, "plato").endswith("default_plato.svg"))
check("Imagenes: fallback default_insumo", obtener_imagen("", "insumo").endswith("default_insumo.svg"))

# Verificar imagen real de seed data
for ruta_base in ["assets/ejemplos/hamburguesa.svg", "assets/ejemplos/helado.svg"]:
    ruta = os.path.join(r"C:\comandapro_erp", ruta_base)
    check(f"Imagenes: existe {ruta_base}", os.path.exists(ruta))

# 5. Notificaciones KDS (cocina.py)
f = open(os.path.join(r"C:\comandapro_erp", "views", "cocina.py"), "r")
content = f.read()
f.close()
check("KDS: notificacion toast", "st.toast" in content)
check("KDS: alerta sonora", "st.audio" in content)
check("KDS: badge titulo", "document.title" in content)

# 6. Cierre de caja en dashboard
f = open(os.path.join(r"C:\comandapro_erp", "views", "dashboard.py"), "r")
dash = f.read()
f.close()
check("Dashboard: cierre de caja", "CERRAR CAJA" in dash or "cerrar_caja" in dash)

# 7. API REST
check("API REST: archivo existe", os.path.exists(os.path.join(r"C:\comandapro_erp", "api.py")))

# 8. DATABASE_URL support
f = open(os.path.join(r"C:\comandapro_erp", "config.py"), "r")
cfg = f.read()
f.close()
check("Config: DATABASE_URL cloud", "DATABASE_URL" in cfg)

# 9. SSL mode para Supabase
f = open(os.path.join(r"C:\comandapro_erp", "database.py"), "r")
db = f.read()
f.close()
check("DB: SSL mode Supabase", "sslmode" in db or "ssl" in db)

print()
print(f"Total: {ok} verificaciones")
