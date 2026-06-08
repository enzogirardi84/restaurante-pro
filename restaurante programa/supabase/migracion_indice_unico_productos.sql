-- Migracion: indice unico sobre nombre en productos_menu
-- Necesario para que ON CONFLICT (nombre) DO UPDATE funcione correctamente
-- Ejecutar en Supabase SQL Editor ANTES de correr cargar_menu_patron.py

CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_menu_nombre_unique
    ON productos_menu (lower(trim(nombre)));
