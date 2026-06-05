-- =====================================================================
--  COMANDAPRO ERP — Migración: agregar columna url_imagen
--  Se aplica sobre una base existente que no tenga las columnas.
-- =====================================================================

-- Productos del menú
ALTER TABLE productos_menu ADD COLUMN url_imagen VARCHAR(255) DEFAULT '';

-- Insumos (para el panel de inventario)
ALTER TABLE insumos ADD COLUMN url_imagen VARCHAR(255) DEFAULT '';

-- Asignar imágenes de ejemplo a productos conocidos (rutas en assets/)
UPDATE productos_menu SET url_imagen = 'assets/ejemplos/hamburguesa.jpg' WHERE nombre LIKE '%Hamburguesa%';
UPDATE productos_menu SET url_imagen = 'assets/ejemplos/papas_fritas.jpg'  WHERE nombre LIKE '%Papas%';
UPDATE productos_menu SET url_imagen = 'assets/ejemplos/milanesa.jpg'     WHERE nombre LIKE '%Milanesa%';
UPDATE productos_menu SET url_imagen = 'assets/ejemplos/vino_tinto.jpg'   WHERE nombre LIKE '%Vino%';
UPDATE productos_menu SET url_imagen = 'assets/ejemplos/helado.jpg'       WHERE nombre LIKE '%Helado%';
