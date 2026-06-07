# Supabase

Esta carpeta contiene el esquema PostgreSQL para crear las tablas principales del sistema en Supabase.

## Pasos

1. Entrar a Supabase.
2. Crear un proyecto.
3. Ir a `SQL Editor`.
4. Ejecutar el contenido de `schema.sql`.
5. Copiar el connection string PostgreSQL en `DATABASE_URL` o `SUPABASE_DB_URL`.
6. En Streamlit Community Cloud, cargarlo en `App settings > Secrets`.

No hace falta crear tablas manualmente desde `Table Editor`. Si creaste una tabla de prueba, se puede borrar o ignorar; el sistema usa las tablas del archivo `schema.sql`.

## Datos que se necesitan

- `DATABASE_URL`: connection string PostgreSQL. Es obligatorio para operar con Supabase como base principal.
- `SUPABASE_URL`: URL del proyecto. Sirve para futuras funciones por API.
- `SUPABASE_ANON_KEY`: clave publica/API.
- `SUPABASE_SERVICE_ROLE_KEY`: clave administrativa. No compartir, no subir a GitHub y rotar si se expone.

## Nota

El esquema crea usuarios, mesas, menu inicial, insumos, recetas, stock, caja, pagos, auditoria y configuracion.

El sistema usa SQLite local si no hay secretos cloud. Cuando existe `DATABASE_URL`/`SUPABASE_DB_URL`, usa Supabase/PostgreSQL.
