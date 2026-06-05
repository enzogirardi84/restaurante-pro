"""
components/imagenes.py — Gestión dinámica de imágenes con fallback.
Verifica existencia física del archivo y retorna default si no existe.
"""
from __future__ import annotations

import os
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent / "assets"
DEFAULT_PLATO   = str(ASSETS_DIR / "default_plato.svg")
DEFAULT_INSUMO  = str(ASSETS_DIR / "default_insumo.svg")


def obtener_imagen(url_db: str | None, tipo: str = "plato") -> str:
    """
    Retorna la ruta de archivo válida para mostrar en st.image().

    Parámetros:
        url_db: Columna url_imagen obtenida de la base de datos (puede ser NULL o vacía).
        tipo:   "plato" o "insumo" — determina cuál default usar.

    Lógica:
        1. Si url_db no es nulo y no está vacío, se toma como ruta.
        2. Se verifica os.path.exists().
        3. Si el archivo no existe físicamente → fallback al default correspondiente.
    """
    if url_db and str(url_db).strip():
        ruta = str(url_db).strip()
        # Si es ruta relativa, resolver contra la raiz del proyecto
        if not os.path.isabs(ruta):
            ruta = str(ASSETS_DIR.parent / ruta)
        if os.path.exists(ruta):
            return ruta

    return DEFAULT_PLATO if tipo == "plato" else DEFAULT_INSUMO
