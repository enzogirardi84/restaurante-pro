-- ============================================================
-- PASO 1: INTERROGACION y DEMOLICION de restricciones
-- Ejecutar en SUPABASE SQL EDITOR (una sola vez)
-- ============================================================

-- 1. Identificar restricciones existentes en productos_menu
SELECT conname AS constraint_name,
       contype AS constraint_type,
       pg_get_constraintdef(oid) AS constraint_definition
FROM pg_constraint
WHERE conrelid = 'public.productos_menu'::regclass;

-- 2. Borrar el CHECK constraint antiguo (cualquiera sea su nombre)
ALTER TABLE public.productos_menu
    DROP CONSTRAINT IF EXISTS productos_menu_categoria_check;

-- (Opcional: si el nombre del sistema es otro, este comando lo borra igual)
DO $$
DECLARE
    constraint_name_var text;
BEGIN
    SELECT conname INTO constraint_name_var
    FROM pg_constraint
    WHERE conrelid = 'public.productos_menu'::regclass
      AND contype = 'c';
    IF constraint_name_var IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.productos_menu DROP CONSTRAINT %I', constraint_name_var);
        RAISE NOTICE 'CHECK constraint % dropped successfully', constraint_name_var;
    ELSE
        RAISE NOTICE 'No CHECK constraint found on productos_menu';
    END IF;
END $$;

-- 3. Aplicar el nuevo CHECK con las 6 categorias premium
ALTER TABLE public.productos_menu
    ADD CONSTRAINT productos_menu_categoria_premium_check
    CHECK (categoria IN ('Entradas', 'Pastas', 'Carnes', 'Pescados', 'Comidas Criollas', 'Postres', 'cocina', 'bebidas', 'postres'));

-- 4. Insertar un plato de prueba para verificar
INSERT INTO public.productos_menu (nombre, precio_venta, categoria, activo)
VALUES ('Carpaccio de lomo curado, crema de parmesano, alcaparras, pistacho tostados, focaccia y hojas verdes fritas', 12000, 'Entradas', 1)
ON CONFLICT (nombre) DO UPDATE SET categoria = EXCLUDED.categoria, activo = 1;

-- 5. Verificar que el plato se inserto correctamente
SELECT id_producto, nombre, categoria, precio_venta, activo
FROM public.productos_menu
WHERE categoria IN ('Entradas', 'Pastas', 'Carnes', 'Pescados', 'Comidas Criollas', 'Postres')
LIMIT 10;
