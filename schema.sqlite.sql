-- =====================================================================
--  COMANDAPRO ERP — DDL para SQLite
--  Sin triggers PL/pgSQL (se manejan desde database.py)
-- =====================================================================

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario    INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre        TEXT NOT NULL,
    apellido      TEXT NOT NULL,
    username      TEXT NOT NULL UNIQUE DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT '',
    rol           TEXT NOT NULL CHECK (rol IN ('mozo', 'cocina', 'administrador'))
);

CREATE TABLE IF NOT EXISTS mesas (
    id_mesa     INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_mesa INTEGER NOT NULL UNIQUE,
    estado      TEXT NOT NULL DEFAULT 'libre'
                CHECK (estado IN ('libre', 'ocupada', 'esperando_cuenta'))
);

CREATE TABLE IF NOT EXISTS insumos (
    id_insumo    INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL,
    stock_actual REAL NOT NULL DEFAULT 0,
    stock_minimo REAL NOT NULL DEFAULT 0,
    unidad_medida TEXT NOT NULL DEFAULT 'unidad',
    url_imagen   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS productos_menu (
    id_producto  INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL,
    precio_venta REAL NOT NULL CHECK (precio_venta >= 0),
    categoria    TEXT NOT NULL DEFAULT 'cocina',
    activo       INTEGER NOT NULL DEFAULT 1,
    url_imagen   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS recetas_escandallo (
    id_receta            INTEGER PRIMARY KEY AUTOINCREMENT,
    id_producto          INTEGER NOT NULL REFERENCES productos_menu(id_producto) ON DELETE RESTRICT,
    id_insumo            INTEGER NOT NULL REFERENCES insumos(id_insumo) ON DELETE RESTRICT,
    cantidad_a_descontar REAL NOT NULL CHECK (cantidad_a_descontar > 0)
);

CREATE TABLE IF NOT EXISTS pedidos_cabecera (
    id_pedido      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_mesa        INTEGER NOT NULL REFERENCES mesas(id_mesa) ON DELETE RESTRICT,
    id_usuario     INTEGER NOT NULL REFERENCES usuarios(id_usuario) ON DELETE RESTRICT,
    fecha_hora     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    estado_comanda TEXT NOT NULL DEFAULT 'pendiente'
                   CHECK (estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado', 'cobrado'))
);

CREATE TABLE IF NOT EXISTS pedido_detalle (
    id_detalle               INTEGER PRIMARY KEY AUTOINCREMENT,
    id_pedido                INTEGER NOT NULL REFERENCES pedidos_cabecera(id_pedido) ON DELETE RESTRICT,
    id_producto              INTEGER NOT NULL REFERENCES productos_menu(id_producto) ON DELETE RESTRICT,
    cantidad                 INTEGER NOT NULL CHECK (cantidad > 0),
    observaciones            TEXT NOT NULL DEFAULT '',
    precio_unitario_facturado REAL
);

CREATE TABLE IF NOT EXISTS proveedores (
    id_proveedor INTEGER PRIMARY KEY AUTOINCREMENT,
    razon_social TEXT NOT NULL,
    cuit_rut     TEXT NOT NULL UNIQUE,
    telefono     TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    direccion    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS depositos (
    id_deposito     INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_deposito TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS compras_maestro (
    id_compra     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_proveedor  INTEGER NOT NULL REFERENCES proveedores(id_proveedor) ON DELETE RESTRICT,
    id_deposito   INTEGER NOT NULL REFERENCES depositos(id_deposito) ON DELETE RESTRICT,
    fecha_compra  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    numero_factura TEXT NOT NULL DEFAULT '',
    total_compra  REAL NOT NULL DEFAULT 0 CHECK (total_compra >= 0),
    estado        TEXT NOT NULL DEFAULT 'pendiente'
                  CHECK (estado IN ('pendiente', 'recibido'))
);

CREATE TABLE IF NOT EXISTS compras_detalle (
    id_compra_detalle    INTEGER PRIMARY KEY AUTOINCREMENT,
    id_compra            INTEGER NOT NULL REFERENCES compras_maestro(id_compra) ON DELETE RESTRICT,
    id_insumo            INTEGER NOT NULL REFERENCES insumos(id_insumo) ON DELETE RESTRICT,
    cantidad_comprada    REAL NOT NULL CHECK (cantidad_comprada > 0),
    precio_costo_unitario REAL NOT NULL CHECK (precio_costo_unitario >= 0)
);

CREATE TABLE IF NOT EXISTS stock_deposito (
    id_stock_deposito   INTEGER PRIMARY KEY AUTOINCREMENT,
    id_insumo           INTEGER NOT NULL REFERENCES insumos(id_insumo) ON DELETE RESTRICT,
    id_deposito         INTEGER NOT NULL REFERENCES depositos(id_deposito) ON DELETE RESTRICT,
    cantidad_disponible REAL NOT NULL DEFAULT 0 CHECK (cantidad_disponible >= 0),
    UNIQUE(id_insumo, id_deposito)
);

CREATE TABLE IF NOT EXISTS cajas_diarias (
    id_caja           INTEGER PRIMARY KEY AUTOINCREMENT,
    id_usuario_cajero INTEGER NOT NULL REFERENCES usuarios(id_usuario) ON DELETE RESTRICT,
    fecha_apertura    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    fecha_cierre      TEXT,
    monto_apertura    REAL NOT NULL DEFAULT 0 CHECK (monto_apertura >= 0),
    monto_ventas      REAL NOT NULL DEFAULT 0 CHECK (monto_ventas >= 0),
    monto_cierre_real REAL CHECK (monto_cierre_real IS NULL OR monto_cierre_real >= 0),
    estado_caja       TEXT NOT NULL DEFAULT 'abierta'
                      CHECK (estado_caja IN ('abierta', 'cerrada'))
);

CREATE TABLE IF NOT EXISTS movimientos_caja (
    id_movimiento  INTEGER PRIMARY KEY AUTOINCREMENT,
    id_caja        INTEGER NOT NULL REFERENCES cajas_diarias(id_caja) ON DELETE RESTRICT,
    tipo_movimiento TEXT NOT NULL CHECK (tipo_movimiento IN (
                       'ingreso_venta', 'egreso_proveedor', 'retiro_efectivo'
                   )),
    monto          REAL NOT NULL CHECK (monto > 0),
    descripcion    TEXT NOT NULL DEFAULT '',
    fecha_hora     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
