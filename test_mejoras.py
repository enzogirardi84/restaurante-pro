"""Quick verification that key improvements are in place."""
from pathlib import Path
import os
import sys
import urllib.request

os.environ["DB_ENGINE"] = "sqlite"

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
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
    ruta = BASE_DIR / ruta_base
    check(f"Imagenes: existe {ruta_base}", ruta.exists())

# 5. Notificaciones KDS (cocina.py)
content = (BASE_DIR / "views" / "cocina.py").read_text(encoding="utf-8")
check("KDS: notificacion toast", "st.toast" in content)
check("KDS: alerta sonora", "st.audio" in content)
check("KDS: badge titulo", "document.title" in content)

# 6. Cierre de caja en dashboard
dash = (BASE_DIR / "views" / "dashboard.py").read_text(encoding="utf-8")
check("Dashboard: cierre de caja", "CERRAR CAJA" in dash or "cerrar_caja" in dash)

# 7. API REST
check("API REST: archivo existe", (BASE_DIR / "api.py").exists())

# 8. DATABASE_URL support
cfg = (BASE_DIR / "config.py").read_text(encoding="utf-8")
check("Config: DATABASE_URL cloud", "DATABASE_URL" in cfg)

# 9. SSL mode para Supabase
db = (BASE_DIR / "database.py").read_text(encoding="utf-8")
check("DB: SSL mode Supabase", "sslmode" in db or "ssl" in db)

print()
print(f"Total: {ok} verificaciones")
