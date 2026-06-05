"""
config.py — Configuración centralizada del sistema COMANDAPRO ERP.
Carga variables de entorno y expone constantes tipadas.
Soporta DATABASE_URL (estándar cloud) o parámetros individuales.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto
load_dotenv(Path(__file__).parent / ".env")

# ── Base de datos ──────────────────────────────────────────────────────
DB_ENGINE: str = os.getenv("DB_ENGINE", "sqlite").lower()

# DATABASE_URL completa (formato: postgresql://user:pass@host:5432/db?sslmode=require)
# Si está definida, se usa en lugar de los parámetros individuales
DATABASE_URL: str | None = os.getenv("DATABASE_URL")

DB_PATH: str = os.getenv("DB_PATH", "comandapro.db")

DB_HOST:     str = os.getenv("DB_HOST", "localhost")
DB_PORT:     int = int(os.getenv("DB_PORT", "5432"))
DB_NAME:     str = os.getenv("DB_NAME", "comandapro")
DB_USER:     str = os.getenv("DB_USER", "postgres")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")
DB_POOL_MIN: int = int(os.getenv("DB_POOL_MIN", "2"))
DB_POOL_MAX: int = int(os.getenv("DB_POOL_MAX", "10"))

# ── Restaurante ────────────────────────────────────────────────────────
NOMBRE_LOCAL:       str = os.getenv("NOMBRE_LOCAL", "Mi Restaurante")
DIRECCION_LOCAL:    str = os.getenv("DIRECCION_LOCAL", "")
CUIT_LOCAL:         str = os.getenv("CUIT_LOCAL", "")
SERVICIO_PORCENTAJE: int = int(os.getenv("SERVICIO_PORCENTAJE", "10"))

# ── Rutas de proyecto ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
