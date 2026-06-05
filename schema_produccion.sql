-- =====================================================================
--  COMANDAPRO ERP — DDL unificado para PostgreSQL
--  Incluye triggers nativos PL/pgSQL y constraints de producción.
-- =====================================================================

BEGIN;

-- ── TABLAS BASE ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario    SERIAL PRIMARY KEY,
    nombre        TEXT NOT NULL,
    apellido      TEXT NOT NULL,
    username      TEXT NOT NULL UNIQUE DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT '',
    rol           TEXT NOT NULL CHECK (rol IN ('mozo', 'cocina', 'administrador'))
);

CREATE TABLE IF NOT EXISTS mesas (
    id_mesa     SERIAL PRIMARY KEY,
    numero_mesa INTEGER NOT NULL UNIQUE,
    estado      TEXT NOT NULL DEFAULT 'libre'
                CHECK (estado IN ('libre', 'ocupada', 'esperando_cuenta'))
);

CREATE TABLE IF NOT EXISTS insumos (
    id_insumo    SERIAL PRIMARY KEY,
    nombre       TEXT NOT NULL,
    stock_actual REAL NOT NULL DEFAULT 0,
    stock_minimo REAL NOT NULL DEFAULT 0,
    unidad_medida TEXT NOT NULL DEFAULT 'unidad',
    url_imagen   VARCHAR(255) DEFAULT ''   -- ruta a imagen del insumo (fallback a default_insumo.jpg)
);

CREATE TABLE IF NOT EXISTS productos_menu (
    id_producto  SERIAL PRIMARY KEY,
    nombre       TEXT NOT NULL,
    precio_venta REAL NOT NULL CHECK (precio_venta >= 0),
    categoria    TEXT NOT NULL CHECK (categoria IN ('cocina', 'bebidas', 'postres')),
    activo       BOOLEAN NOT NULL DEFAULT TRUE,
    url_imagen   VARCHAR(255) DEFAULT ''   -- ruta a foto del plato (fallback a default_plato.jpg)
);

CREATE TABLE IF NOT EXISTS recetas_escandallo (
    id_receta            SERIAL PRIMARY KEY,
    id_producto          INTEGER NOT NULL REFERENCES productos_menu(id_producto)
                         ON DELETE RESTRICT,
    id_insumo            INTEGER NOT NULL REFERENCES insumos(id_insumo)
                         ON DELETE RESTRICT,
    cantidad_a_descontar REAL NOT NULL CHECK (cantidad_a_descontar > 0)
);

CREATE TABLE IF NOT EXISTS pedidos_cabecera (
    id_pedido      SERIAL PRIMARY KEY,
    id_mesa        INTEGER NOT NULL REFERENCES mesas(id_mesa)
                   ON DELETE RESTRICT,
    id_usuario     INTEGER NOT NULL REFERENCES usuarios(id_usuario)
                   ON DELETE RESTRICT,
    fecha_hora     TIMESTAMP NOT NULL DEFAULT now(),
    estado_comanda TEXT NOT NULL DEFAULT 'pendiente'
                   CHECK (estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado', 'cobrado'))
);

CREATE TABLE IF NOT EXISTS pedido_detalle (
    id_detalle               SERIAL PRIMARY KEY,
    id_pedido                INTEGER NOT NULL REFERENCES pedidos_cabecera(id_pedido)
                             ON DELETE RESTRICT,
    id_producto              INTEGER NOT NULL REFERENCES productos_menu(id_producto)
                             ON DELETE RESTRICT,
    cantidad                 INTEGER NOT NULL CHECK (cantidad > 0),
    observaciones            TEXT NOT NULL DEFAULT '',
    precio_unitario_facturado REAL NOT NULL
);

-- ── MÓDULO PROVEEDORES ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS proveedores (
    id_proveedor SERIAL PRIMARY KEY,
    razon_social TEXT NOT NULL,
    cuit_rut     TEXT NOT NULL UNIQUE,
    telefono     TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    direccion    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS depositos (
    id_deposito     SERIAL PRIMARY KEY,
    nombre_deposito TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS compras_maestro (
    id_compra     SERIAL PRIMARY KEY,
    id_proveedor  INTEGER NOT NULL REFERENCES proveedores(id_proveedor)
                  ON DELETE RESTRICT,
    id_deposito   INTEGER NOT NULL REFERENCES depositos(id_deposito)
                  ON DELETE RESTRICT,
    fecha_compra  TIMESTAMP NOT NULL DEFAULT now(),
    numero_factura TEXT NOT NULL DEFAULT '',
    total_compra  REAL NOT NULL DEFAULT 0 CHECK (total_compra >= 0),
    estado        TEXT NOT NULL DEFAULT 'pendiente'
                  CHECK (estado IN ('pendiente', 'recibido'))
);

CREATE TABLE IF NOT EXISTS compras_detalle (
    id_compra_detalle    SERIAL PRIMARY KEY,
    id_compra            INTEGER NOT NULL REFERENCES compras_maestro(id_compra)
                         ON DELETE RESTRICT,
    id_insumo            INTEGER NOT NULL REFERENCES insumos(id_insumo)
                         ON DELETE RESTRICT,
    cantidad_comprada    REAL NOT NULL CHECK (cantidad_comprada > 0),
    precio_costo_unitario REAL NOT NULL CHECK (precio_costo_unitario >= 0)
);

CREATE TABLE IF NOT EXISTS stock_deposito (
    id_stock_deposito   SERIAL PRIMARY KEY,
    id_insumo           INTEGER NOT NULL REFERENCES insumos(id_insumo)
                        ON DELETE RESTRICT,
    id_deposito         INTEGER NOT NULL REFERENCES depositos(id_deposito)
                        ON DELETE RESTRICT,
    cantidad_disponible REAL NOT NULL DEFAULT 0 CHECK (cantidad_disponible >= 0),
    UNIQUE(id_insumo, id_deposito)
);

-- ── MÓDULO FINANCIERO ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cajas_diarias (
    id_caja           SERIAL PRIMARY KEY,
    id_usuario_cajero INTEGER NOT NULL REFERENCES usuarios(id_usuario)
                      ON DELETE RESTRICT,
    fecha_apertura    TIMESTAMP NOT NULL DEFAULT now(),
    fecha_cierre      TIMESTAMP,
    monto_apertura    REAL NOT NULL DEFAULT 0 CHECK (monto_apertura >= 0),
    monto_ventas      REAL NOT NULL DEFAULT 0 CHECK (monto_ventas >= 0),
    monto_cierre_real REAL CHECK (monto_cierre_real IS NULL OR monto_cierre_real >= 0),
    estado_caja       TEXT NOT NULL DEFAULT 'abierta'
                      CHECK (estado_caja IN ('abierta', 'cerrada'))
);

CREATE TABLE IF NOT EXISTS movimientos_caja (
    id_movimiento  SERIAL PRIMARY KEY,
    id_caja        INTEGER NOT NULL REFERENCES cajas_diarias(id_caja)
                   ON DELETE RESTRICT,
    tipo_movimiento TEXT NOT NULL CHECK (tipo_movimiento IN (
                       'ingreso_venta', 'egreso_proveedor', 'retiro_efectivo'
                   )),
    monto          REAL NOT NULL CHECK (monto > 0),
    descripcion    TEXT NOT NULL DEFAULT '',
    fecha_hora     TIMESTAMP NOT NULL DEFAULT now()
);


-- =====================================================================
--  TRIGGERS EN PL/pgSQL
-- =====================================================================

-- ── 1. Al recibir una compra: actualizar stock ───────────────────────

CREATE OR REPLACE FUNCTION fn_compras_recibir()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.estado = 'recibido' AND OLD.estado = 'pendiente' THEN

        -- 1a. Incrementar stock global del insumo
        UPDATE insumos i
        SET stock_actual = stock_actual + (
            SELECT cd.cantidad_comprada
            FROM compras_detalle cd
            WHERE cd.id_compra = NEW.id_compra
              AND cd.id_insumo = i.id_insumo
        )
        WHERE i.id_insumo IN (
            SELECT cd.id_insumo
            FROM compras_detalle cd
            WHERE cd.id_compra = NEW.id_compra
        );

        -- 1b. UPSERT en stock_deposito (INSERT … ON CONFLICT DO UPDATE)
        INSERT INTO stock_deposito (id_insumo, id_deposito, cantidad_disponible)
        SELECT cd.id_insumo, NEW.id_deposito, cd.cantidad_comprada
        FROM compras_detalle cd
        WHERE cd.id_compra = NEW.id_compra
        ON CONFLICT (id_insumo, id_deposito) DO UPDATE
        SET cantidad_disponible = stock_deposito.cantidad_disponible + EXCLUDED.cantidad_disponible;

    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_compras_recibir ON compras_maestro;
CREATE TRIGGER trg_compras_recibir
    AFTER UPDATE OF estado ON compras_maestro
    FOR EACH ROW
    EXECUTE FUNCTION fn_compras_recibir();


-- ── 2. Al descontar stock por receta: priorizar depósito con más stock ─

CREATE OR REPLACE FUNCTION fn_stock_post_receta()
RETURNS TRIGGER AS $$
DECLARE
    v_deposito_id INTEGER;
BEGIN
    IF NEW.stock_actual < OLD.stock_actual THEN

        -- Elegir el depósito con mayor cantidad disponible
        SELECT sd.id_deposito INTO v_deposito_id
        FROM stock_deposito sd
        WHERE sd.id_insumo = NEW.id_insumo
        ORDER BY sd.cantidad_disponible DESC
        LIMIT 1;

        IF FOUND THEN
            UPDATE stock_deposito
            SET cantidad_disponible = GREATEST(
                    cantidad_disponible - (OLD.stock_actual - NEW.stock_actual), 0
                )
            WHERE id_insumo = NEW.id_insumo
              AND id_deposito = v_deposito_id;
        END IF;

    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stock_post_receta ON insumos;
CREATE TRIGGER trg_stock_post_receta
    AFTER UPDATE OF stock_actual ON insumos
    FOR EACH ROW
    EXECUTE FUNCTION fn_stock_post_receta();


-- ── 3. Forzar precio_unitario_facturado en pedido_detalle ───────────

CREATE OR REPLACE FUNCTION fn_pedido_detalle_precio()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.precio_unitario_facturado IS NULL THEN
        SELECT precio_venta INTO NEW.precio_unitario_facturado
        FROM productos_menu
        WHERE id_producto = NEW.id_producto;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pedido_detalle_precio ON pedido_detalle;
CREATE TRIGGER trg_pedido_detalle_precio
    BEFORE INSERT ON pedido_detalle
    FOR EACH ROW
    EXECUTE FUNCTION fn_pedido_detalle_precio();


COMMIT;
