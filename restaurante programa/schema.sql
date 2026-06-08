-- =============================================================
-- SISTEMA DE GESTIÓN GASTRONÓMICA E INVENTARIO AUTOMATIZADO
-- Esquema de Base de Datos Relacional (SQLite / PostgreSQL)
-- =============================================================
-- Este script crea todas las tablas del sistema.
-- Los datos de ejemplo se siembran desde database.py::init_db()

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario   INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL,
    apellido     TEXT NOT NULL,
    rol          TEXT NOT NULL CHECK (rol IN ('mozo', 'cocina', 'caja', 'administrador', 'dueno')),
    mail         TEXT NOT NULL DEFAULT '',
    contrasena   TEXT NOT NULL DEFAULT '',
    pin          TEXT DEFAULT '0000',
    activo       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mesas (
    id_mesa      INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_mesa  INTEGER NOT NULL UNIQUE,
    estado       TEXT NOT NULL DEFAULT 'libre'
                 CHECK (estado IN ('libre', 'ocupada', 'esperando_cuenta'))
);

CREATE TABLE IF NOT EXISTS insumos (
    id_insumo    INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL,
    stock_actual REAL NOT NULL DEFAULT 0,
    stock_minimo REAL NOT NULL DEFAULT 0,
    unidad_medida TEXT NOT NULL DEFAULT 'unidad'
);

CREATE TABLE IF NOT EXISTS proveedores (
    id_proveedor INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL UNIQUE,
    telefono     TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    notas        TEXT NOT NULL DEFAULT '',
    cuit_rut     TEXT NOT NULL DEFAULT '',
    direccion    TEXT NOT NULL DEFAULT '',
    activo       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS movimientos_stock (
    id_movimiento_stock INTEGER PRIMARY KEY AUTOINCREMENT,
    id_insumo           INTEGER NOT NULL,
    id_usuario          INTEGER,
    id_proveedor        INTEGER,
    tipo_movimiento     TEXT NOT NULL CHECK (tipo_movimiento IN ('compra', 'ajuste_entrada', 'ajuste_salida', 'descuento_receta', 'merma')),
    cantidad            REAL NOT NULL CHECK (cantidad > 0),
    stock_anterior      REAL NOT NULL DEFAULT 0,
    stock_nuevo         REAL NOT NULL DEFAULT 0,
    descripcion         TEXT NOT NULL DEFAULT '',
    fecha_hora          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (id_insumo) REFERENCES insumos(id_insumo),
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario),
    FOREIGN KEY (id_proveedor) REFERENCES proveedores(id_proveedor)
);

CREATE TABLE IF NOT EXISTS productos_menu (
    id_producto  INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL,
    precio_venta REAL NOT NULL CHECK (precio_venta >= 0),
    categoria    TEXT NOT NULL DEFAULT 'cocina',
    activo       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS recetas_escandallo (
    id_receta            INTEGER PRIMARY KEY AUTOINCREMENT,
    id_producto          INTEGER NOT NULL,
    id_insumo            INTEGER NOT NULL,
    cantidad_a_descontar REAL NOT NULL CHECK (cantidad_a_descontar > 0),
    FOREIGN KEY (id_producto) REFERENCES productos_menu(id_producto),
    FOREIGN KEY (id_insumo)   REFERENCES insumos(id_insumo)
);

CREATE TABLE IF NOT EXISTS pedidos_cabecera (
    id_pedido      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_mesa        INTEGER NOT NULL,
    id_usuario     INTEGER NOT NULL,
    fecha_hora     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    estado_comanda TEXT NOT NULL DEFAULT 'pendiente'
                   CHECK (estado_comanda IN ('pendiente', 'en_cocina', 'listo', 'entregado', 'cobrado')),
    medio_pago    TEXT DEFAULT '',
    total_cobrado REAL DEFAULT 0,
    fecha_cobro   TEXT,
    FOREIGN KEY (id_mesa)    REFERENCES mesas(id_mesa),
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
);

CREATE TABLE IF NOT EXISTS pedido_detalle (
    id_detalle    INTEGER PRIMARY KEY AUTOINCREMENT,
    id_pedido     INTEGER NOT NULL,
    id_producto   INTEGER NOT NULL,
    cantidad      INTEGER NOT NULL CHECK (cantidad > 0),
    observaciones TEXT DEFAULT '',
    precio_unitario_facturado REAL,
    cantidad_cobrada INTEGER DEFAULT 0,
    cantidad_anulada INTEGER DEFAULT 0,
    motivo_anulacion TEXT DEFAULT '',
    FOREIGN KEY (id_pedido)   REFERENCES pedidos_cabecera(id_pedido),
    FOREIGN KEY (id_producto) REFERENCES productos_menu(id_producto)
);

CREATE TABLE IF NOT EXISTS auditoria_eventos (
    id_evento  INTEGER PRIMARY KEY AUTOINCREMENT,
    modulo     TEXT NOT NULL,
    accion     TEXT NOT NULL,
    detalle    TEXT NOT NULL DEFAULT '',
    fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS pagos_mesa (
    id_pago    INTEGER PRIMARY KEY AUTOINCREMENT,
    id_mesa    INTEGER NOT NULL,
    id_usuario INTEGER,
    fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    medio_pago TEXT NOT NULL DEFAULT '',
    subtotal   REAL NOT NULL DEFAULT 0,
    servicio   REAL NOT NULL DEFAULT 0,
    total      REAL NOT NULL DEFAULT 0,
    tipo       TEXT NOT NULL DEFAULT 'total' CHECK (tipo IN ('total', 'parcial')),
    FOREIGN KEY (id_mesa) REFERENCES mesas(id_mesa),
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
);

CREATE TABLE IF NOT EXISTS pago_detalle (
    id_pago_detalle INTEGER PRIMARY KEY AUTOINCREMENT,
    id_pago         INTEGER NOT NULL,
    id_detalle      INTEGER NOT NULL,
    cantidad        INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (id_pago) REFERENCES pagos_mesa(id_pago),
    FOREIGN KEY (id_detalle) REFERENCES pedido_detalle(id_detalle)
);

CREATE TABLE IF NOT EXISTS configuracion_sistema (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sistema_estado (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL DEFAULT '',
    actualizado_en TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_usuarios_rol_activo
    ON usuarios(rol, activo);
CREATE INDEX IF NOT EXISTS idx_mesas_estado
    ON mesas(estado);
CREATE INDEX IF NOT EXISTS idx_productos_categoria_activo
    ON productos_menu(categoria, activo);
CREATE INDEX IF NOT EXISTS idx_recetas_producto
    ON recetas_escandallo(id_producto);
CREATE INDEX IF NOT EXISTS idx_recetas_insumo
    ON recetas_escandallo(id_insumo);
CREATE INDEX IF NOT EXISTS idx_pedidos_estado_fecha
    ON pedidos_cabecera(estado_comanda, fecha_hora);
CREATE INDEX IF NOT EXISTS idx_pedidos_mesa_estado
    ON pedidos_cabecera(id_mesa, estado_comanda);
CREATE INDEX IF NOT EXISTS idx_pedidos_usuario_fecha
    ON pedidos_cabecera(id_usuario, fecha_hora);
CREATE INDEX IF NOT EXISTS idx_detalle_pedido
    ON pedido_detalle(id_pedido);
CREATE INDEX IF NOT EXISTS idx_detalle_producto
    ON pedido_detalle(id_producto);
CREATE INDEX IF NOT EXISTS idx_pagos_fecha
    ON pagos_mesa(fecha_hora);
CREATE INDEX IF NOT EXISTS idx_pagos_mesa_fecha
    ON pagos_mesa(id_mesa, fecha_hora);
CREATE INDEX IF NOT EXISTS idx_pagos_medio
    ON pagos_mesa(medio_pago);
CREATE INDEX IF NOT EXISTS idx_pago_detalle_pago
    ON pago_detalle(id_pago);
CREATE INDEX IF NOT EXISTS idx_pago_detalle_detalle
    ON pago_detalle(id_detalle);
CREATE INDEX IF NOT EXISTS idx_stock_insumo_fecha
    ON movimientos_stock(id_insumo, fecha_hora);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha
    ON auditoria_eventos(fecha_hora);

CREATE TABLE IF NOT EXISTS promociones (
    id_promocion INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('porcentaje', 'fijo', 'medio_pago', 'combo')),
    valor REAL NOT NULL CHECK (valor >= 0),
    categoria TEXT NOT NULL DEFAULT '',
    medio_pago TEXT NOT NULL DEFAULT '',
    hora_desde TEXT NOT NULL DEFAULT '',
    hora_hasta TEXT NOT NULL DEFAULT '',
    dias_semana TEXT NOT NULL DEFAULT '',
    activa INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS turnos_personal (
    id_turno INTEGER PRIMARY KEY AUTOINCREMENT,
    id_usuario INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    hora_entrada TEXT NOT NULL,
    hora_salida TEXT,
    minutos_trabajados INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'cerrado')),
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
);

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

CREATE TABLE IF NOT EXISTS facturas_electronicas (
    id_factura INTEGER PRIMARY KEY AUTOINCREMENT,
    id_pago INTEGER,
    tipo_comprobante TEXT NOT NULL DEFAULT 'B' CHECK (tipo_comprobante IN ('A', 'B', 'X', 'ticket')),
    punto_venta INTEGER NOT NULL DEFAULT 1,
    numero_comprobante INTEGER NOT NULL DEFAULT 0,
    cuit_cliente TEXT NOT NULL DEFAULT '',
    razon_social_cliente TEXT NOT NULL DEFAULT '',
    domicilio_cliente TEXT NOT NULL DEFAULT '',
    condicion_iva TEXT NOT NULL DEFAULT 'Consumidor Final',
    subtotal REAL NOT NULL DEFAULT 0,
    iva REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    medio_pago TEXT NOT NULL DEFAULT '',
    fecha_emision TEXT NOT NULL,
    cae TEXT NOT NULL DEFAULT '',
    cae_vencimiento TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'emitido' CHECK (estado IN ('pendiente', 'emitido', 'anulado')),
    observaciones TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (id_pago) REFERENCES pagos_mesa(id_pago)
);
