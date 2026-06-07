"""Utilidades puras para el modulo Cocina."""
from __future__ import annotations


def kitchen_auto_refresh_seconds(form_open: bool, default_seconds: int = 8) -> int:
    """Pausa el refresco automatico mientras se carga un pedido manual."""
    if form_open:
        return 0
    return max(int(default_seconds), 0)
