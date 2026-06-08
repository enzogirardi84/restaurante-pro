-- =====================================================================
--  SISTEMA ERP GASTRONÓMICO — Extensiones para producción
--  Compatible con SQLite 3.x  |  Portabilidad a PostgreSQL marcada
-- =====================================================================
--  Este script se aplica DESPUÉS de schema.sql y conserva todas las
--  tablas originales.  Solo añade + modifica.
-- =====================================================================

BEGIN TRANSACTION;

-- =====================================================================
--  1.  MÓDULO DE PROVEEDORES Y ABASTECIMIENTO (COMPRAS)
-- =====================================================================

CREATE TABLE IF NOT EXISTS proveedores (
    id_proveedor INTEGER PRIMARY KEY AUTOINCREMENT,
    razon_social TEXT    NOT NULL,
    cuit_rut     TEXT    NOT NULL UNIQUE,
    telefono     TEXT    NOT NULL DEFAULT '',
    email        TEXT    NOT NULL DEFAULT '',
    direccion    TEXT    NOT NULL DEFAULT ''
    -- PostgreSQL: id_proveedor SERIAL PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS compras_maestro (
    id_compra     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_proveedor  INTEGER NOT NULL,
    id_deposito   INTEGER NOT NULL,         -- dónde se almacena lo recibido
    fecha_compra  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    numero_factura TEXT   NOT NULL DEFAULT '',
    total_compra  REAL    NOT NULL DEFAULT 0 CHECK (total_compra >= 0),
    estado        TEXT    NOT NULL DEFAULT 'pendiente'
                   CHECK (estado IN ('pendiente', 'recibido')),
    FOREIGN KEY (id_proveedor) REFERENCES proveedores(id_proveedor)
        ON DELETE RESTRICT,
    FOREIGN KEY (id_deposito)  REFERENCES depositos(id_deposito)
        ON DELETE RESTRICT
    -- PostgreSQL: fecha_compra TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS compras_detalle (
    id_compra_detalle  INTEGER PRIMARY KEY AUTOINCREMENT,
    id_compra          INTEGER NOT NULL,
    id_insumo          INTEGER NOT NULL,
    cantidad_comprada  REAL    NOT NULL CHECK (cantidad_comprada > 0),
    precio_costo_unitario REAL NOT NULL CHECK (precio_costo_unitario >= 0),
    FOREIGN KEY (id_compra) REFERENCES compras_maestro(id_compra)
        ON DELETE RESTRICT,
    FOREIGN KEY (id_insumo) REFERENCES insumos(id_insumo)
        ON DELETE RESTRICT
);

-- ── Trigger: al recibir una compra, actualizar stock ──────────────────
--   SQLite no permite CREATE OR REPLACE TRIGGER, así que primero
--   se elimina si existe para que el script sea idempotente.
DROP TRIGGER IF EXISTS trg_compras_recibir;

CREATE TRIGGER trg_compras_recibir
    AFTER UPDATE OF estado ON compras_maestro
    FOR EACH ROW
    WHEN NEW.estado = 'recibido' AND OLD.estado = 'pendiente'
BEGIN
    -- 1. Incrementar stock global del insumo
    UPDATE insumos
       SET stock_actual = stock_actual + (
               SELECT cd.cantidad_comprada
               FROM   compras_detalle cd
               WHERE  cd.id_compra = NEW.id_compra
                 AND  cd.id_insumo = insumos.id_insumo
           )
     WHERE id_insumo IN (
               SELECT id_insumo
               FROM   compras_detalle
               WHERE  id_compra = NEW.id_compra
           );

    -- 2. Incrementar stock en el depósito destino
    --    (upsert: si el par (id_insumo, id_deposito) existe, suma;
    --     si no, inserta)
    INSERT INTO stock_deposito (id_insumo, id_deposito, cantidad_disponible)
         SELECT cd.id_insumo, NEW.id_deposito, cd.cantidad_comprada
         FROM   compras_detalle cd
         WHERE  cd.id_compra = NEW.id_compra
    ON CONFLICT(id_insumo, id_deposito) DO UPDATE SET
        cantidad_disponible = cantidad_disponible + excluded.cantidad_disponible;
END;

-- PostgreSQL equivalente (función + trigger):
-- CREATE OR REPLACE FUNCTION fn_trg_compras_recibir() RETURNS TRIGGER AS $$
--   ...
-- $$ LANGUAGE plpgsql;
-- CREATE TRIGGER trg_compras_recibir
--     AFTER UPDATE OF estado ON compras_maestro
--     FOR EACH ROW WHEN (NEW.estado = 'recibido' AND OLD.estado = 'pendiente')
--     EXECUTE FUNCTION fn_trg_compras_recibir();


-- =====================================================================
--  2.  MÓDULO LOGÍSTICO — MULTI-DEPÓSITOS
-- =====================================================================

CREATE TABLE IF NOT EXISTS depositos (
    id_deposito     INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_deposito TEXT    NOT NULL UNIQUE
);

-- Esta tabla reemplaza conceptualmente el stock plano de insumos.
-- insumos.stock_actual se mantiene como TOTAL GLOBAL (redundancia controlada).
CREATE TABLE IF NOT EXISTS stock_deposito (
    id_stock_deposito   INTEGER PRIMARY KEY AUTOINCREMENT,
    id_insumo           INTEGER NOT NULL,
    id_deposito         INTEGER NOT NULL,
    cantidad_disponible REAL    NOT NULL DEFAULT 0 CHECK (cantidad_disponible >= 0),
    UNIQUE(id_insumo, id_deposito),
    FOREIGN KEY (id_insumo)   REFERENCES insumos(id_insumo)
        ON DELETE RESTRICT,
    FOREIGN KEY (id_deposito) REFERENCES depositos(id_deposito)
        ON DELETE RESTRICT
);

-- Trigger: mantener stock_deposito sincronizado con el descuento de
--          cocina (para que el KDS descuente del depósito correcto).
--
-- En producción habría que determinar desde qué depósito se descuenta
-- (por receta o por configuración).  Este trigger es un placeholder
-- que descuenta del primer depósito disponible como fallback.
DROP TRIGGER IF EXISTS trg_stock_post_receta;

CREATE TRIGGER trg_stock_post_receta
    AFTER UPDATE OF stock_actual ON insumos
    FOR EACH ROW
    WHEN NEW.stock_actual < OLD.stock_actual
BEGIN
    UPDATE stock_deposito
       SET cantidad_disponible = MAX(
               cantidad_disponible - (OLD.stock_actual - NEW.stock_actual),
               0
           )
     WHERE id_insumo = NEW.id_insumo
       AND id_deposito = (
               SELECT id_deposito
               FROM   stock_deposito
               WHERE  id_insumo = NEW.id_insumo
               ORDER  BY cantidad_disponible DESC
               LIMIT  1
           );
END;


-- =====================================================================
--  3.  MÓDULO FINANCIERO — ARQUEO Y TURNOS DE CAJA
-- =====================================================================

CREATE TABLE IF NOT EXISTS cajas_diarias (
    id_caja              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_usuario_cajero    INTEGER NOT NULL,
    fecha_apertura       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    fecha_cierre         TEXT,
    monto_apertura       REAL    NOT NULL DEFAULT 0 CHECK (monto_apertura >= 0),
    monto_ventas         REAL    NOT NULL DEFAULT 0 CHECK (monto_ventas >= 0),
    monto_cierre_real    REAL    DEFAULT NULL CHECK (monto_cierre_real IS NULL OR monto_cierre_real >= 0),
    diferencia_cierre    REAL    NOT NULL DEFAULT 0,
    observacion_cierre   TEXT    NOT NULL DEFAULT '',
    estado_caja          TEXT    NOT NULL DEFAULT 'abierta'
                          CHECK (estado_caja IN ('abierta', 'cerrada')),
    FOREIGN KEY (id_usuario_cajero) REFERENCES usuarios(id_usuario)
        ON DELETE RESTRICT
    -- PostgreSQL: fecha_apertura TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS movimientos_caja (
    id_movimiento  INTEGER PRIMARY KEY AUTOINCREMENT,
    id_caja        INTEGER NOT NULL,
    tipo_movimiento TEXT   NOT NULL CHECK (tipo_movimiento IN (
                        'ingreso_venta', 'egreso_proveedor', 'retiro_efectivo'
                    )),
    monto          REAL   NOT NULL CHECK (monto > 0),
    descripcion    TEXT   NOT NULL DEFAULT '',
    fecha_hora     TEXT   NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (id_caja) REFERENCES cajas_diarias(id_caja)
        ON DELETE RESTRICT
    -- PostgreSQL: fecha_hora TIMESTAMP DEFAULT now()
);


-- =====================================================================
--  4.  REFACTORIZACIÓN DE pedido_detalle — AUDITORÍA DE PRECIOS
-- =====================================================================
--   Agrega precio_unitario_facturado para congelar el precio de venta
--   al momento del pedido, independientemente de cambios futuros.
-- =====================================================================

-- 4a. La columna precio_unitario_facturado ya existe en schema.sql.
--     Para bases antiguas, database.py la agrega de forma segura al iniciar.

-- 4b. Poblar los registros existentes con el precio actual del menú
UPDATE pedido_detalle
   SET precio_unitario_facturado = (
       SELECT pm.precio_venta
       FROM   productos_menu pm
       WHERE  pm.id_producto = pedido_detalle.id_producto
   )
 WHERE precio_unitario_facturado IS NULL;

-- 4c. Garantizar NOT NULL hacia adelante
--     En SQLite no se puede ADD CONSTRAINT NOT NULL, pero podemos
--     forzarlo con un CHECK a nivel de tabla (requeriría recrear).
--     Como alternativa práctica, se crea un trigger de inserción.
DROP TRIGGER IF EXISTS trg_pedido_detalle_precio_not_null;

CREATE TRIGGER trg_pedido_detalle_precio_not_null
    BEFORE INSERT ON pedido_detalle
    FOR EACH ROW
    WHEN NEW.precio_unitario_facturado IS NULL
BEGIN
    SELECT RAISE(ABORT, 'precio_unitario_facturado no puede ser NULL');
END;

-- En PostgreSQL se haría simplemente:
-- ALTER TABLE pedido_detalle ALTER COLUMN precio_unitario_facturado SET NOT NULL;


-- =====================================================================
--  DATOS DE EJEMPLO PARA LOS NUEVOS MÓDULOS
-- =====================================================================

INSERT OR IGNORE INTO depositos (nombre_deposito) VALUES
    ('Bodega Central'),
    ('Barra Principal'),
    ('Cámara de Congelados');

INSERT OR IGNORE INTO proveedores (razon_social, cuit_rut) VALUES
    ('Distribuidora de Carnes S.A.',        '30-12345678-9'),
    ('Frutas y Verduras del Sur',           '30-23456789-0'),
    ('Bebidas y Licores Cuyo SRL',          '30-34567890-1'),
    ('Lácteos y Helados Patagónicos',       '30-45678901-2'),
    ('Panificados y Harinas La Central',    '30-56789012-3'),
    ('Proveedor de Aceites y Enlatados',    '30-67890123-4');

-- Vincular stock existente a los depósitos (migración del stock plano)
INSERT OR IGNORE INTO stock_deposito (id_insumo, id_deposito, cantidad_disponible)
SELECT id_insumo, 1, stock_actual FROM insumos
WHERE stock_actual > 0;

-- Caja inicial abierta (para poder registrar movimientos)
INSERT OR IGNORE INTO cajas_diarias (id_usuario_cajero, monto_apertura, estado_caja)
VALUES (3, 50000, 'abierta');

-- Tabla de auditoria operativa para registrar acciones criticas
CREATE TABLE IF NOT EXISTS logs_operaciones (
    id_log INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT NOT NULL,
    accion TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    ip_origen TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_logs_fecha ON logs_operaciones(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_accion ON logs_operaciones(accion);


COMMIT;
