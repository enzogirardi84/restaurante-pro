-- Restaurante Pro - esquema PostgreSQL/Supabase

create table if not exists usuarios (
    id_usuario bigserial primary key,
    nombre text not null,
    apellido text not null,
    rol text not null check (rol in ('mozo', 'cocina', 'caja', 'administrador', 'dueno')),
    mail text not null default '',
    contrasena text not null default '',
    pin text default '0000',
    activo integer not null default 1
);

-- Migracion defensiva: si la tabla usuarios ya existia con otro formato,
-- agregamos las columnas que usa la aplicacion antes de crear claves foraneas.
alter table usuarios
    add column if not exists id_usuario bigserial;

alter table usuarios
    add column if not exists nombre text not null default 'Usuario';

alter table usuarios
    add column if not exists apellido text not null default 'Sistema';

alter table usuarios
    add column if not exists rol text not null default 'dueno';

alter table usuarios
    add column if not exists mail text not null default '';

alter table usuarios
    add column if not exists contrasena text not null default '';

alter table usuarios
    add column if not exists pin text default '0000';

alter table usuarios
    add column if not exists activo integer not null default 1;

alter table usuarios
    drop constraint if exists usuarios_rol_check;

alter table usuarios
    add constraint usuarios_rol_check
    check (rol in ('mozo', 'cocina', 'caja', 'administrador', 'dueno'));

create unique index if not exists idx_usuarios_id_usuario_unique
    on usuarios(id_usuario);

create unique index if not exists idx_usuarios_mail_unique
    on usuarios (lower(mail))
    where mail <> '';

create table if not exists mesas (
    id_mesa bigserial primary key,
    numero_mesa integer not null unique,
    estado text not null default 'libre'
        check (estado in ('libre', 'ocupada', 'esperando_cuenta'))
);

create table if not exists insumos (
    id_insumo bigserial primary key,
    nombre text not null,
    stock_actual numeric not null default 0,
    stock_minimo numeric not null default 0,
    unidad_medida text not null default 'unidad'
);

create table if not exists proveedores (
    id_proveedor bigserial primary key,
    nombre text not null unique,
    telefono text not null default '',
    email text not null default '',
    notas text not null default '',
    cuit_rut text not null default '',
    direccion text not null default '',
    activo integer not null default 1
);

create table if not exists movimientos_stock (
    id_movimiento_stock bigserial primary key,
    id_insumo bigint not null references insumos(id_insumo),
    id_usuario bigint references usuarios(id_usuario),
    id_proveedor bigint references proveedores(id_proveedor),
    tipo_movimiento text not null check (tipo_movimiento in ('compra', 'ajuste_entrada', 'ajuste_salida', 'descuento_receta', 'merma')),
    cantidad numeric not null check (cantidad > 0),
    stock_anterior numeric not null default 0,
    stock_nuevo numeric not null default 0,
    descripcion text not null default '',
    fecha_hora timestamptz not null default now()
);

create table if not exists productos_menu (
    id_producto bigserial primary key,
    nombre text not null,
    precio_venta numeric not null check (precio_venta >= 0),
    categoria text not null default 'cocina',
    activo integer not null default 1
);

create table if not exists recetas_escandallo (
    id_receta bigserial primary key,
    id_producto bigint not null references productos_menu(id_producto),
    id_insumo bigint not null references insumos(id_insumo),
    cantidad_a_descontar numeric not null check (cantidad_a_descontar > 0),
    unique (id_producto, id_insumo)
);

create table if not exists pedidos_cabecera (
    id_pedido bigserial primary key,
    id_mesa bigint not null references mesas(id_mesa),
    id_usuario bigint not null references usuarios(id_usuario),
    fecha_hora timestamptz not null default now(),
    estado_comanda text not null default 'pendiente'
        check (estado_comanda in ('pendiente', 'en_cocina', 'listo', 'entregado', 'cobrado')),
    medio_pago text default '',
    total_cobrado numeric default 0,
    fecha_cobro timestamptz
);

alter table pedidos_cabecera
    add column if not exists medio_pago text default '';

alter table pedidos_cabecera
    add column if not exists total_cobrado numeric default 0;

alter table pedidos_cabecera
    add column if not exists fecha_cobro timestamptz;

create table if not exists pedido_detalle (
    id_detalle bigserial primary key,
    id_pedido bigint not null references pedidos_cabecera(id_pedido),
    id_producto bigint not null references productos_menu(id_producto),
    cantidad integer not null check (cantidad > 0),
    observaciones text default '',
    precio_unitario_facturado numeric,
    cantidad_cobrada integer default 0,
    cantidad_anulada integer default 0,
    motivo_anulacion text default ''
);

alter table pedido_detalle
    add column if not exists precio_unitario_facturado numeric;

alter table pedido_detalle
    add column if not exists cantidad_cobrada integer default 0;

alter table pedido_detalle
    add column if not exists cantidad_anulada integer default 0;

alter table pedido_detalle
    add column if not exists motivo_anulacion text default '';

create table if not exists pagos_mesa (
    id_pago bigserial primary key,
    id_mesa bigint not null references mesas(id_mesa),
    id_usuario bigint references usuarios(id_usuario),
    fecha_hora timestamptz not null default now(),
    medio_pago text not null default '',
    subtotal numeric not null default 0,
    servicio numeric not null default 0,
    total numeric not null default 0,
    tipo text not null default 'total' check (tipo in ('total', 'parcial'))
);

alter table pagos_mesa
    add column if not exists subtotal numeric not null default 0;

alter table pagos_mesa
    add column if not exists servicio numeric not null default 0;

alter table pagos_mesa
    add column if not exists tipo text not null default 'total';

create table if not exists pago_detalle (
    id_pago_detalle bigserial primary key,
    id_pago bigint not null references pagos_mesa(id_pago),
    id_detalle bigint not null references pedido_detalle(id_detalle),
    cantidad integer not null check (cantidad > 0),
    precio_unitario numeric not null default 0
);

alter table pago_detalle
    add column if not exists precio_unitario numeric not null default 0;

create table if not exists depositos (
    id_deposito bigserial primary key,
    nombre_deposito text not null unique
);

create table if not exists stock_deposito (
    id_stock_deposito bigserial primary key,
    id_insumo bigint not null references insumos(id_insumo),
    id_deposito bigint not null references depositos(id_deposito),
    cantidad_disponible numeric not null default 0 check (cantidad_disponible >= 0),
    unique (id_insumo, id_deposito)
);

create table if not exists cajas_diarias (
    id_caja bigserial primary key,
    id_usuario_cajero bigint not null references usuarios(id_usuario),
    fecha_apertura timestamptz not null default now(),
    fecha_cierre timestamptz,
    monto_apertura numeric not null default 0 check (monto_apertura >= 0),
    monto_ventas numeric not null default 0 check (monto_ventas >= 0),
    monto_cierre_real numeric check (monto_cierre_real is null or monto_cierre_real >= 0),
    diferencia_cierre numeric not null default 0,
    observacion_cierre text not null default '',
    estado_caja text not null default 'abierta' check (estado_caja in ('abierta', 'cerrada'))
);

alter table cajas_diarias
    add column if not exists diferencia_cierre numeric not null default 0;

alter table cajas_diarias
    add column if not exists observacion_cierre text not null default '';

create table if not exists movimientos_caja (
    id_movimiento bigserial primary key,
    id_caja bigint not null references cajas_diarias(id_caja),
    tipo_movimiento text not null check (tipo_movimiento in ('ingreso_venta', 'egreso_proveedor', 'retiro_efectivo')),
    monto numeric not null check (monto > 0),
    descripcion text not null default '',
    fecha_hora timestamptz not null default now()
);

create table if not exists auditoria_eventos (
    id_evento bigserial primary key,
    modulo text not null,
    accion text not null,
    detalle text not null default '',
    fecha_hora timestamptz not null default now()
);

create table if not exists configuracion_sistema (
    clave text primary key,
    valor text not null default ''
);

create table if not exists accesos_sistema (
    usuario text primary key,
    password_hash text not null,
    activo integer not null default 1,
    rol text not null default 'administrador',
    creado_en timestamptz not null default now(),
    actualizado_en timestamptz not null default now()
);

alter table accesos_sistema
    add column if not exists activo integer not null default 1;

alter table accesos_sistema
    add column if not exists rol text not null default 'administrador';

alter table accesos_sistema
    add column if not exists creado_en timestamptz not null default now();

alter table accesos_sistema
    add column if not exists actualizado_en timestamptz not null default now();

create table if not exists sistema_estado (
    clave text primary key,
    valor text not null default '',
    actualizado_en timestamptz not null default now()
);

alter table sistema_estado
    add column if not exists actualizado_en timestamptz not null default now();

create index if not exists idx_usuarios_rol_activo
    on usuarios(rol, activo);
create index if not exists idx_mesas_estado
    on mesas(estado);
create index if not exists idx_productos_categoria_activo
    on productos_menu(categoria, activo);
create index if not exists idx_recetas_producto
    on recetas_escandallo(id_producto);
create index if not exists idx_recetas_insumo
    on recetas_escandallo(id_insumo);
create index if not exists idx_pedidos_estado_fecha
    on pedidos_cabecera(estado_comanda, fecha_hora);
create index if not exists idx_pedidos_mesa_estado
    on pedidos_cabecera(id_mesa, estado_comanda);
create index if not exists idx_pedidos_usuario_fecha
    on pedidos_cabecera(id_usuario, fecha_hora);
create index if not exists idx_detalle_pedido
    on pedido_detalle(id_pedido);
create index if not exists idx_detalle_producto
    on pedido_detalle(id_producto);
create index if not exists idx_pagos_fecha
    on pagos_mesa(fecha_hora);
create index if not exists idx_pagos_mesa_fecha
    on pagos_mesa(id_mesa, fecha_hora);
create index if not exists idx_pagos_medio
    on pagos_mesa(medio_pago);
create index if not exists idx_pago_detalle_pago
    on pago_detalle(id_pago);
create index if not exists idx_pago_detalle_detalle
    on pago_detalle(id_detalle);
create index if not exists idx_stock_insumo_fecha
    on movimientos_stock(id_insumo, fecha_hora);
create index if not exists idx_auditoria_fecha
    on auditoria_eventos(fecha_hora);
create index if not exists idx_cajas_estado_fecha
    on cajas_diarias(estado_caja, fecha_apertura);
create index if not exists idx_accesos_sistema_activo
    on accesos_sistema(activo);

insert into configuracion_sistema (clave, valor)
values
    ('usuario_sistema', 'anahigilardi'),
    ('password_sistema', 'pbkdf2_sha256$260000$restaurante_pro_anahigilardi$4dddc291f7d7d9355d779938477655ad0e21179cc056648b7b1ecf8e68121815'),
    ('restaurante_nombre', 'Restaurante Pro'),
    ('restaurante_direccion', ''),
    ('restaurante_telefono', ''),
    ('restaurante_identificacion', ''),
    ('ticket_footer', 'Gracias por su visita.'),
    ('servicio_porcentaje', '10'),
    ('metodos_pago', 'Efectivo,Tarjeta,Transferencia'),
    ('promo_activa', '0')
on conflict (clave) do nothing;

insert into sistema_estado (clave, valor)
values
    ('schema_version', '2026.06.05'),
    ('app_name', 'COMANDAPRO ERP'),
    ('storage', 'supabase')
on conflict (clave) do update
set valor = excluded.valor,
    actualizado_en = now();

update configuracion_sistema
   set valor = 'anahigilardi'
 where clave = 'usuario_sistema'
   and valor in ('sistema', 'admin');

update configuracion_sistema
   set valor = 'pbkdf2_sha256$260000$restaurante_pro_anahigilardi$4dddc291f7d7d9355d779938477655ad0e21179cc056648b7b1ecf8e68121815'
 where clave = 'password_sistema'
   and valor in (
       'restaurante',
       'pbkdf2_sha256$260000$restaurante_pro_admin$3bf3e011536522835b606cc8b6d62689977bae8961ac46f703a8519b5cbb7d71'
   );

insert into accesos_sistema (usuario, password_hash, activo, rol)
values
    ('anahigilardi', 'pbkdf2_sha256$260000$restaurante_pro_anahigilardi$4dddc291f7d7d9355d779938477655ad0e21179cc056648b7b1ecf8e68121815', 1, 'administrador'),
    ('enzogirardi', 'pbkdf2_sha256$260000$restaurante_pro_enzogirardi$43d87f64ede3c7d3ad5498e4c62d1cd272b03231219b42bdbff0b3806b37969b', 1, 'administrador')
on conflict (usuario) do update
set password_hash = excluded.password_hash,
    activo = excluded.activo,
    rol = excluded.rol,
    actualizado_en = now();

insert into usuarios (nombre, apellido, rol, pin, activo)
values
    ('Carlos', 'Garcia', 'mozo', '1234', 1),
    ('Maria', 'Lopez', 'cocina', '2222', 1),
    ('Lucia', 'Perez', 'caja', '3333', 1),
    ('Admin', 'Root', 'administrador', '9999', 1)
on conflict do nothing;

update usuarios
   set mail = lower(rol || '.' || id_usuario || '@local.invalid'),
       contrasena = case
       when rol in ('administrador', 'dueno') then 'pbkdf2_sha256$260000$restaurante_pro_anahigilardi$4dddc291f7d7d9355d779938477655ad0e21179cc056648b7b1ecf8e68121815'
       else 'pbkdf2_sha256$260000$restaurante_pro_anahigilardi$4dddc291f7d7d9355d779938477655ad0e21179cc056648b7b1ecf8e68121815'
   end
 where mail = '';

update usuarios
   set mail = 'anahigilardi',
       contrasena = 'pbkdf2_sha256$260000$restaurante_pro_anahigilardi$4dddc291f7d7d9355d779938477655ad0e21179cc056648b7b1ecf8e68121815'
 where id_usuario = (
       select min(id_usuario)
       from usuarios
       where rol in ('administrador', 'dueno')
   )
   and not exists (
       select 1
       from usuarios u2
       where lower(u2.mail) = 'anahigilardi'
         and u2.id_usuario <> usuarios.id_usuario
   );

insert into mesas (numero_mesa, estado)
values (1, 'libre'), (2, 'libre'), (3, 'libre'), (4, 'libre'), (5, 'libre')
on conflict (numero_mesa) do nothing;

insert into depositos (nombre_deposito)
values ('Deposito principal')
on conflict (nombre_deposito) do nothing;

insert into insumos (nombre, stock_actual, stock_minimo, unidad_medida)
select *
from (
    values
        ('Carne de res', 8000, 2000, 'gramos'),
        ('Papa', 5000, 1000, 'gramos'),
        ('Queso mozzarella', 3000, 500, 'gramos'),
        ('Pan de hamburguesa', 20, 10, 'unidad'),
        ('Lechuga', 2000, 500, 'gramos'),
        ('Tomate', 3000, 500, 'gramos'),
        ('Vino tinto botella', 12, 6, 'unidad'),
        ('Helado', 4000, 1000, 'mililitros'),
        ('Harina', 5000, 1000, 'gramos'),
        ('Aceite', 3000, 500, 'mililitros')
) as data(nombre, stock_actual, stock_minimo, unidad_medida)
where not exists (
    select 1 from insumos i where i.nombre = data.nombre
);

insert into productos_menu (nombre, precio_venta, categoria, activo)
select *
from (
    values
        ('Hamburguesa Clasica', 8500, 'cocina', 1),
        ('Papas Fritas', 3500, 'cocina', 1),
        ('Milanesa con guarnicion', 7500, 'cocina', 1),
        ('Vino Tinto Casa', 4500, 'bebidas', 1),
        ('Helado artesanal', 3200, 'postres', 1)
) as data(nombre, precio_venta, categoria, activo)
where not exists (
    select 1 from productos_menu pm where pm.nombre = data.nombre
);

insert into recetas_escandallo (id_producto, id_insumo, cantidad_a_descontar)
select pm.id_producto, i.id_insumo, data.cantidad_a_descontar
from (
    values
        ('Hamburguesa Clasica', 'Carne de res', 150),
        ('Hamburguesa Clasica', 'Pan de hamburguesa', 1),
        ('Hamburguesa Clasica', 'Lechuga', 30),
        ('Hamburguesa Clasica', 'Tomate', 50),
        ('Papas Fritas', 'Papa', 250),
        ('Papas Fritas', 'Aceite', 20),
        ('Milanesa con guarnicion', 'Carne de res', 200),
        ('Milanesa con guarnicion', 'Harina', 100),
        ('Milanesa con guarnicion', 'Papa', 200),
        ('Milanesa con guarnicion', 'Aceite', 30),
        ('Vino Tinto Casa', 'Vino tinto botella', 1),
        ('Helado artesanal', 'Helado', 200)
) as data(producto, insumo, cantidad_a_descontar)
join productos_menu pm on pm.nombre = data.producto
join insumos i on i.nombre = data.insumo
where not exists (
    select 1
    from recetas_escandallo r
    where r.id_producto = pm.id_producto
      and r.id_insumo = i.id_insumo
);

insert into stock_deposito (id_insumo, id_deposito, cantidad_disponible)
select i.id_insumo, d.id_deposito, i.stock_actual
from insumos i
cross join depositos d
where d.nombre_deposito = 'Deposito principal'
on conflict (id_insumo, id_deposito) do nothing;

create table if not exists promociones (
    id_promocion bigserial primary key,
    nombre text not null,
    tipo text not null check (tipo in ('porcentaje', 'fijo', 'medio_pago', 'combo')),
    valor numeric not null check (valor >= 0),
    categoria text not null default '',
    medio_pago text not null default '',
    hora_desde text not null default '',
    hora_hasta text not null default '',
    dias_semana text not null default '',
    activa integer not null default 1,
    creado timestamp not null default now()
);

create table if not exists turnos_personal (
    id_turno bigserial primary key,
    id_usuario bigint not null references usuarios(id_usuario),
    fecha date not null,
    hora_entrada time not null,
    hora_salida time,
    minutos_trabajados integer not null default 0,
    estado text not null default 'activo' check (estado in ('activo', 'cerrado'))
);

create table if not exists facturas_electronicas (
    id_factura bigserial primary key,
    id_pago bigint references pagos_mesa(id_pago),
    tipo_comprobante text not null default 'B' check (tipo_comprobante in ('A', 'B', 'X', 'ticket')),
    punto_venta integer not null default 1,
    numero_comprobante integer not null default 0,
    cuit_cliente text not null default '',
    razon_social_cliente text not null default '',
    domicilio_cliente text not null default '',
    condicion_iva text not null default 'Consumidor Final',
    subtotal numeric not null default 0,
    iva numeric not null default 0,
    total numeric not null default 0,
    medio_pago text not null default '',
    fecha_emision date not null,
    cae text not null default '',
    cae_vencimiento text not null default '',
    estado text not null default 'emitido' check (estado in ('pendiente', 'emitido', 'anulado')),
    observaciones text not null default ''
);

-- Migraciones para columnas agregadas en tablas existentes
alter table proveedores add column if not exists cuit_rut text not null default '';
alter table proveedores add column if not exists direccion text not null default '';
alter table accesos_sistema add column if not exists rol text not null default 'administrador';
