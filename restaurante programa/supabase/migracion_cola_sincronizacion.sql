-- Migracion: crear tabla cola_sincronizacion en Supabase
-- Ejecutar directamente en el SQL Editor de Supabase
-- Esta tabla es necesaria para el mecanismo offline-first de la app

create table if not exists cola_sincronizacion (
    id_sync bigserial primary key,
    tabla text not null,
    operacion text not null check (operacion in ('INSERT', 'UPDATE', 'DELETE')),
    clave_primaria text not null,
    payload_json text not null default '{}',
    creado_en timestamptz not null default now(),
    sincronizado integer not null default 0,
    ultimo_intento timestamptz,
    intentos integer not null default 0
);

create index if not exists idx_sync_pendiente
    on cola_sincronizacion(sincronizado, creado_en);
