-- Migracion: crear tabla logs_operaciones para auditoria operativa
-- Ejecutar en SQL Editor de Supabase y replicar en SQLite via schema.sql

create table if not exists logs_operaciones (
    id_log bigserial primary key,
    usuario text not null,
    accion text not null,
    detalle text not null default '',
    metadata_json text not null default '{}',
    ip_origen text not null default '',
    created_at timestamptz not null default now()
);

create index if not exists idx_logs_fecha
    on logs_operaciones(created_at desc);

create index if not exists idx_logs_accion
    on logs_operaciones(accion);
