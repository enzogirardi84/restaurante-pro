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
    rol           TEXT NOT NULL CHECK (rol IN ('mozo', 'cocina', 'caja', 'administrador')),
    pin           TEXT DEFAULT '0000'
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
                   CHECK (estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado', 'cobrado')),
    medio_pago     TEXT DEFAULT '',
    total_cobrado  REAL DEFAULT 0,
    fecha_cobro    TEXT
);

CREATE TABLE IF NOT EXISTS pedido_detalle (
    id_detalle               INTEGER PRIMARY KEY AUTOINCREMENT,
    id_pedido                INTEGER NOT NULL REFERENCES pedidos_cabecera(id_pedido) ON DELETE RESTRICT,
    id_producto              INTEGER NOT NULL REFERENCES productos_menu(id_producto) ON DELETE RESTRICT,
    cantidad                 INTEGER NOT NULL CHECK (cantidad > 0),
    observaciones            TEXT NOT NULL DEFAULT '',
    precio_unitario_facturado REAL,
    cantidad_cobrada         INTEGER DEFAULT 0,
    cantidad_anulada         INTEGER DEFAULT 0,
    motivo_anulacion         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS auditoria_eventos (
    id_evento  INTEGER PRIMARY KEY AUTOINCREMENT,
    modulo     TEXT NOT NULL,
    accion     TEXT NOT NULL,
    detalle    TEXT NOT NULL DEFAULT '',
    fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS movimientos_stock (
    id_movimiento_stock INTEGER PRIMARY KEY AUTOINCREMENT,
    id_insumo           INTEGER NOT NULL REFERENCES insumos(id_insumo) ON DELETE RESTRICT,
    id_usuario          INTEGER REFERENCES usuarios(id_usuario) ON DELETE SET NULL,
    id_proveedor        INTEGER REFERENCES proveedores(id_proveedor) ON DELETE SET NULL,
    tipo_movimiento     TEXT NOT NULL DEFAULT 'ajuste_entrada',
    cantidad            REAL NOT NULL DEFAULT 0,
    stock_anterior      REAL NOT NULL DEFAULT 0,
    stock_nuevo         REAL NOT NULL DEFAULT 0,
    descripcion         TEXT NOT NULL DEFAULT '',
    fecha_hora          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS pagos_mesa (
    id_pago    INTEGER PRIMARY KEY AUTOINCREMENT,
    id_mesa    INTEGER NOT NULL REFERENCES mesas(id_mesa) ON DELETE RESTRICT,
    id_usuario INTEGER REFERENCES usuarios(id_usuario) ON DELETE SET NULL,
    fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    medio_pago TEXT NOT NULL DEFAULT '',
    subtotal   REAL NOT NULL DEFAULT 0,
    descuento  REAL NOT NULL DEFAULT 0,
    servicio   REAL NOT NULL DEFAULT 0,
    total      REAL NOT NULL DEFAULT 0,
    tipo       TEXT NOT NULL DEFAULT 'total' CHECK (tipo IN ('total', 'parcial'))
);

CREATE TABLE IF NOT EXISTS pago_detalle (
    id_pago_detalle INTEGER PRIMARY KEY AUTOINCREMENT,
    id_pago         INTEGER NOT NULL REFERENCES pagos_mesa(id_pago) ON DELETE RESTRICT,
    id_detalle      INTEGER NOT NULL REFERENCES pedido_detalle(id_detalle) ON DELETE RESTRICT,
    cantidad        INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turnos_personal (
    id_turno INTEGER PRIMARY KEY AUTOINCREMENT,
    id_usuario INTEGER NOT NULL REFERENCES usuarios(id_usuario) ON DELETE RESTRICT,
    fecha TEXT NOT NULL,
    hora_entrada TEXT NOT NULL,
    hora_salida TEXT,
    minutos_trabajados INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'cerrado'))
);

CREATE TABLE IF NOT EXISTS cola_sincronizacion (
    id_sync INTEGER PRIMARY KEY AUTOINCREMENT,
    tabla TEXT NOT NULL,
    operacion TEXT NOT NULL,
    clave_primaria TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    creado_en TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    sincronizado INTEGER NOT NULL DEFAULT 0,
    ultimo_intento TEXT,
    intentos INTEGER NOT NULL DEFAULT 0
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
