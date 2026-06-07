# Restaurante Pro

Sistema de gestion para restaurante con terminales de mozo, cocina, caja y panel administrador.

## Funciones principales

- Login general configurable.
- Cambio obligatorio de contrasena inicial y guardado con hash.
- Terminal automatica para mozo, cocina, caja y panel.
- Gestion de personal: mozo, cocina, caja y administrador.
- Pedidos por mesa con notas para cocina.
- Cocina tipo KDS con tiempos, estados y despacho.
- Caja con cobro total/parcial, ticket y cierre.
- Menu, promociones automaticas, recetas por plato e inventario.
- Inventario con proveedores, compras, ajustes, mermas e historial de movimientos.
- Reportes con descarga CSV/XLSX.
- Backups locales de base de datos.
- Exportaciones CSV en modo Supabase/PostgreSQL.
- Diagnostico del sistema y checklist de deploy.
- Estado publico basico en `?status=public`.
- CI en GitHub Actions para validar sintaxis y pruebas.

## Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run sistema_restaurante.py
```

Acceso inicial:

```text
Usuario: anahigilardi
Contrasena: 1999
```

Si una base vieja todavia tiene `sistema/restaurante` o `admin/admin`, el sistema la migra automaticamente a `anahigilardi/1999`.

Terminales:

```text
http://localhost:8501/?terminal=mozo
http://localhost:8501/?terminal=cocina
http://localhost:8501/?terminal=caja
http://localhost:8501/?terminal=panel
http://localhost:8501/?status=public
```

## Base de datos

El sistema usa SQLite local en `data/restaurante.db` cuando no hay `DATABASE_URL`.
Si Streamlit Secrets o variables de entorno incluyen `DATABASE_URL`/`SUPABASE_DB_URL`, la app usa Supabase/PostgreSQL.
El archivo `.db` local no se sube a GitHub porque contiene datos operativos.

## Supabase

Supabase puede usarse como base PostgreSQL en la nube. El SQL inicial esta en:

```text
supabase/schema.sql
```

Para cargarlo:

1. Crear un proyecto en Supabase.
2. Abrir SQL Editor.
3. Pegar y ejecutar `supabase/schema.sql`.

La aplicacion puede usar Supabase como base principal con `DATABASE_URL` o `SUPABASE_DB_URL` en Streamlit Secrets.

Tabla tecnica para verificar persistencia en Supabase:

```text
sistema_estado
```

La app actualiza esa tabla con nombre, version, modo de base y ultimo arranque.

Secrets recomendados para Streamlit:

```toml
DB_ENGINE = "postgresql"
DATABASE_URL = "postgresql://..."
NOMBRE_LOCAL = "Restaurante Pro"
SERVICIO_PORCENTAJE = "10"
```

## Streamlit Community Cloud

Recomendado para una primera publicacion online:

1. Entrar a Streamlit Community Cloud.
2. Crear una app desde el repositorio de GitHub.
3. Usar como archivo principal `sistema_restaurante.py`.
4. En `App settings > Secrets`, cargar los valores siguiendo `.streamlit/secrets.toml.example`.
5. Ejecutar `supabase/schema.sql` en Supabase antes de conectar la app a PostgreSQL.

Importante: Streamlit Community Cloud no debe depender de `data/restaurante.db` para datos reales, porque el almacenamiento local de la app no esta pensado como base persistente. Para operar en la nube hay que usar `DATABASE_URL` de Supabase/PostgreSQL.

Si una clave secreta fue compartida por error, rotarla en Supabase antes de publicar.

## Pruebas

```bash
python tests_restaurante.py
```

## Checklist antes de produccion

Dentro del sistema abrir `Sistema` para revisar:

- Base local.
- SQL de Supabase.
- Personal, mesas, menu, inventario y recetas.
- Productos activos sin receta.
- Stock bajo.
- Estado de caja.
- DATABASE_URL y modo de base.
- Seguridad del acceso general.

## GitHub Actions

El workflow `.github/workflows/ci.yml` ejecuta:

- `python -m py_compile sistema_restaurante.py database.py tests_restaurante.py`
- `python tests_restaurante.py`
