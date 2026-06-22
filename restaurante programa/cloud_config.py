"""
Helpers de configuracion cloud.

No imprimen ni guardan secretos: solo indican si la app tiene lo necesario
para conectar servicios externos como Supabase y Streamlit Community Cloud.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import dotenv_values
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent

_PREEXISTING_ENV_KEYS = set(os.environ)


def _load_project_envs() -> None:
    merged: dict[str, str] = {}
    for env_path in (ROOT_DIR / ".env", APP_DIR / ".env"):
        if not env_path.exists():
            continue
        for key, value in dotenv_values(env_path).items():
            if value is not None:
                merged[key] = str(value)
    for key, value in merged.items():
        if key not in _PREEXISTING_ENV_KEYS:
            os.environ[key] = value


_load_project_envs()


SECRET_KEYS = (
    "DB_ENGINE",
    "DATABASE_URL",
    "DATABASE_URL_POOLER",
    "DATABASE_URL_DIRECTA",
    "SUPABASE_DB_URL",
    "SUPABASE_URL",
    "SUPABASE_REST_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "NOMBRE_LOCAL",
    "SERVICIO_PORCENTAJE",
)


@dataclass(frozen=True)
class CloudStatus:
    database_url: bool
    database_url_pooler: bool
    database_url_directa: bool
    supabase_url: bool
    supabase_anon_key: bool
    supabase_service_role_key: bool

    @property
    def ready_for_postgres(self) -> bool:
        return self.database_url or self.database_url_pooler

    @property
    def ready_for_ddl(self) -> bool:
        return bool(self.database_url_directa or self.database_url)

    @property
    def ready_for_supabase_api(self) -> bool:
        return self.supabase_url and self.supabase_anon_key


def _streamlit_secret(name: str) -> str:
    try:
        import streamlit as st

        value = st.secrets.get(name, "")
        if value is None:
            return ""
        if isinstance(value, str):
            return str(value).strip()

        # Si el secreto esta anidado bajo [supabase]
        supabase_section = st.secrets.get("supabase", {})
        if isinstance(supabase_section, dict):
            # Mapear nombres planos a claves anidadas
            key_map = {
                "SUPABASE_URL": "url",
                "SUPABASE_REST_URL": "rest_url",
                "SUPABASE_ANON_KEY": "anon_key",
                "SUPABASE_SERVICE_ROLE_KEY": "service_role_key",
            }
            nested_key = key_map.get(name)
            if nested_key:
                val = supabase_section.get(nested_key, "")
                return str(val).strip() if val else ""
        return ""
    except Exception:
        return ""


def get_secret(name: str) -> str:
    """Lee un secreto desde variables de entorno o st.secrets.
    Prioridad: st.secrets > os.environ > .env (ya cargado).
    En Streamlit Cloud, los Secrets del panel tienen maxima prioridad."""
    env_val = os.environ.get(name, "").strip()
    ss_val = _streamlit_secret(name)
    return ss_val or env_val


def normalize_supabase_url(value: str) -> str:
    """Convierte endpoints REST de Supabase en la URL base del proyecto."""
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def supabase_url() -> str:
    """Devuelve la URL base del proyecto Supabase."""
    return normalize_supabase_url(get_secret("SUPABASE_REST_URL") or get_secret("SUPABASE_URL"))


def database_url() -> str:
    """Devuelve la URL PostgreSQL preferida para Supabase/Cloud."""
    return get_secret("DATABASE_URL") or get_secret("SUPABASE_DB_URL")


def database_url_pooler() -> str:
    """URL del pooler transaccional (puerto 6543) para CRUD diario.
    Si no existe, cae a DATABASE_URL."""
    return get_secret("DATABASE_URL_POOLER") or database_url()


def database_url_directa() -> str:
    """URL directa (puerto 5432) para DDL y migraciones.
    Si no existe, cae a DATABASE_URL."""
    return get_secret("DATABASE_URL_DIRECTA") or database_url()


def db_engine() -> str:
    """Motor de base solicitado por configuracion."""
    return (get_secret("DB_ENGINE") or "").strip().lower()


def app_name(default: str = "Restaurante Pro") -> str:
    """Nombre visible de la aplicacion."""
    return get_secret("NOMBRE_LOCAL") or default


def default_service_percentage(default: float = 10) -> float:
    """Porcentaje de servicio por defecto desde secrets/env."""
    raw = get_secret("SERVICIO_PORCENTAJE")
    if not raw:
        return float(default)
    try:
        return max(float(raw), 0)
    except ValueError:
        return float(default)


def _ensure_sslmode(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return url
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    query.setdefault("connect_timeout", "5")
    return urlunparse(parsed._replace(query=urlencode(query)))


def normalized_database_url() -> str:
    """Devuelve DATABASE_URL del pooler (6543) con SSL para CRUD diario."""
    engine = db_engine()
    if engine in {"sqlite", "local"}:
        return ""
    raw = database_url_pooler()
    if not raw:
        return ""
    return _ensure_sslmode(raw)


def normalized_database_url_directa() -> str:
    """Devuelve DATABASE_URL directa (5432) para DDL y migraciones."""
    if db_engine() in {"sqlite", "local"}:
        return ""
    raw = database_url_directa()
    if not raw:
        return ""
    return _ensure_sslmode(raw)


def database_url_warnings() -> list[str]:
    raw = database_url()
    warnings = []
    if not raw:
        return warnings
    if "[YOUR-PASSWORD]" in raw or "TU_PASSWORD" in raw:
        warnings.append("DATABASE_URL todavia tiene el placeholder de password.")
    if "@" not in raw:
        warnings.append("DATABASE_URL no parece incluir usuario, password y host.")
    if "supabase.com" not in raw and "pooler.supabase.com" not in raw:
        warnings.append("DATABASE_URL no parece ser de Supabase.")
    return warnings


def cloud_status() -> CloudStatus:
    return CloudStatus(
        database_url=bool(normalized_database_url()),
        database_url_pooler=bool(get_secret("DATABASE_URL_POOLER")),
        database_url_directa=bool(get_secret("DATABASE_URL_DIRECTA")),
        supabase_url=bool(supabase_url()),
        supabase_anon_key=bool(get_secret("SUPABASE_ANON_KEY")),
        supabase_service_role_key=bool(get_secret("SUPABASE_SERVICE_ROLE_KEY")),
    )


def masked_status_table() -> list[dict[str, str]]:
    status = cloud_status()
    return [
        {
            "secreto": "DATABASE_URL (pooler 6543)",
            "estado": "Cargado" if status.database_url else "Pendiente",
            "uso": "Conexion transaccional diaria (CRUD)",
        },
        {
            "secreto": "DATABASE_URL_DIRECTA (5432)",
            "estado": "Cargado" if status.database_url_directa else "Pendiente",
            "uso": "Conexion directa para DDL y migraciones",
        },
        {
            "secreto": "SUPABASE_URL",
            "estado": "Cargado" if status.supabase_url else "Pendiente",
            "uso": "API de Supabase",
        },
        {
            "secreto": "SUPABASE_ANON_KEY",
            "estado": "Cargado" if status.supabase_anon_key else "Pendiente",
            "uso": "Clave publica para API de Supabase",
        },
        {
            "secreto": "SUPABASE_SERVICE_ROLE_KEY",
            "estado": "Cargado" if status.supabase_service_role_key else "Pendiente",
            "uso": "Clave administrativa; no debe compartirse ni subirse",
        },
    ]

