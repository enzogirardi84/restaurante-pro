"""
Script de reseteo de accesos del sistema.
Ejecutar: python reset_accesos.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from database import get_connection, init_db, using_postgres
from access_utils import DEFAULT_SYSTEM_ACCESSES

init_db()
conn = get_connection()
try:
    for usuario, hash_val in DEFAULT_SYSTEM_ACCESSES.items():
        if using_postgres():
            conn.execute("""
                INSERT INTO accesos_sistema (usuario, password_hash, activo)
                VALUES (%s, %s, 1)
                ON CONFLICT (usuario) DO UPDATE SET password_hash = %s, activo = 1
            """, (usuario, hash_val, hash_val))
        else:
            conn.execute("""
                INSERT OR REPLACE INTO accesos_sistema (usuario, password_hash, activo)
                VALUES (?, ?, 1)
            """, (usuario, hash_val))
    admin_hash = DEFAULT_SYSTEM_ACCESSES["anahigilardi"]
    if using_postgres():
        conn.execute("""
            UPDATE usuarios
               SET mail = %s,
                   contrasena = %s,
                   activo = 1
             WHERE id_usuario = (
                   SELECT MIN(id_usuario)
                   FROM usuarios
                   WHERE rol IN ('administrador', 'dueno')
             )
        """, ("anahigilardi", admin_hash))
    else:
        conn.execute("""
            UPDATE usuarios
               SET mail = ?,
                   contrasena = ?,
                   activo = 1
             WHERE id_usuario = (
                   SELECT MIN(id_usuario)
                   FROM usuarios
                   WHERE rol IN ('administrador', 'dueno')
             )
        """, ("anahigilardi", admin_hash))
    conn.commit()
    print("Accesos reseteados correctamente.")
    print("  anahigilardi / 1999")
    print("  enzogirardi / clave configurada")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
