-- Migracion completa para Supabase - Ejecutar en SQL Editor
-- Proyecto: jyisecrmuiebuvtgqjhy

-- 1. Eliminar CHECK constraint antiguo de categoria
DO $$ DECLARE cname text; BEGIN
    SELECT conname INTO cname FROM pg_constraint
    WHERE conrelid = 'public.productos_menu'::regclass AND contype = 'c';
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.productos_menu DROP CONSTRAINT %I', cname);
    END IF;
END $$;

-- 2. Indice unico para ON CONFLICT
CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_menu_nombre_unique
    ON public.productos_menu (lower(trim(nombre)));

-- 3. Verificar insumos tienen asignados a deposito
INSERT INTO public.depositos (nombre_deposito)
SELECT 'Deposito principal' WHERE NOT EXISTS (SELECT 1 FROM public.depositos);
INSERT INTO public.stock_deposito (id_insumo, id_deposito, cantidad_disponible)
SELECT i.id_insumo, 1, 0 FROM public.insumos i
WHERE NOT EXISTS (SELECT 1 FROM public.stock_deposito sd WHERE sd.id_insumo = i.id_insumo);

-- 4. Insertar platos premium si la tabla esta vacia
INSERT INTO public.productos_menu (nombre, precio_venta, categoria, activo)
SELECT * FROM (VALUES
    ('Provolone con mermelada de tomates y pesto, con escabeches y focaccia', 12000, 'Entradas', 1),
    ('Pera asada con queso azul, nueces y miel sobre verdes', 12000, 'Entradas', 1),
    ('Dúo empanadas carne cortada a cuchillo / humita y mozzarella', 12000, 'Entradas', 1),
    ('Carpaccio de lomo curado, crema de parmesano, alcaparras, pistacho tostados, focaccia y hojas verdes fritas', 12000, 'Entradas', 1),
    ('Tabla charcutería de elaboración propia, quesos, escabeches, alioli de ajo', 12000, 'Entradas', 1),
    ('Rotolo di tata (de cabrito y verduras)', 15000, 'Pastas', 1),
    ('Lasaña de pollo y espinaca al forno', 15000, 'Pastas', 1),
    ('Creps de espinaca y parmesano con finas hierbas', 15000, 'Pastas', 1),
    ('Cintas anchas en tinta de sepia con crema de mariscos', 15000, 'Pastas', 1),
    ('Ñoquis boniato con manteca y almendras tostadas', 15000, 'Pastas', 1),
    ('Cintas finas al huevo con fileto y estofado', 15000, 'Pastas', 1),
    ('Cintas finas al huevo con crema de hongos de pino', 15000, 'Pastas', 1),
    ('Cintas finas al huevo a la carbonara', 15000, 'Pastas', 1),
    ('Ojo de bife con aligot de papa y salsa criolla', 22000, 'Carnes', 1),
    ('Ojo de bife con salsa patrón', 22000, 'Carnes', 1),
    ('Ojo de bife con salsa de hongos', 22000, 'Carnes', 1),
    ('Lomo en demiglase con terrina de papa y vegetales glaseados', 22000, 'Carnes', 1),
    ('Bondiola ahumada en reducción de miel y jengibre con batatas rotas', 22000, 'Carnes', 1),
    ('Milanesa de entrecot con fideos al huevo con crema de hierbas', 22000, 'Carnes', 1),
    ('Salmón rosado con manteca de lima y azafrán acompañado de ensalada tibia', 18000, 'Pescados', 1),
    ('Trucha con alcaparras, manteca, naranja y miel, acompañado de papines y verduras salteadas', 18000, 'Pescados', 1),
    ('Pacú con papas rústicas y hojas verdes acompañados de salsa criolla', 18000, 'Pescados', 1),
    ('Locro criollo con verdeo picante', 13000, 'Comidas Criollas', 1),
    ('Humita', 13000, 'Comidas Criollas', 1),
    ('Guiso de lentejas', 13000, 'Comidas Criollas', 1),
    ('Tiramisú', 8000, 'Postres', 1),
    ('Lingote de chocolate', 8000, 'Postres', 1),
    ('Flan tradicional', 8000, 'Postres', 1),
    ('Panna cotta con frutos rojos', 8000, 'Postres', 1),
    ('Tarta vasca', 8000, 'Postres', 1)
) AS data(nombre, precio, categoria, activo)
WHERE NOT EXISTS (SELECT 1 FROM public.productos_menu)
ON CONFLICT (lower(trim(nombre))) DO UPDATE SET
    precio_venta = CASE WHEN EXCLUDED.precio_venta > 0 THEN EXCLUDED.precio_venta ELSE productos_menu.precio_venta END,
    categoria = EXCLUDED.categoria,
    activo = 1;
