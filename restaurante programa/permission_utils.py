"""Permisos por rol para la navegacion principal."""
from __future__ import annotations


ADMIN_MODULES = [
    "Panel",
    "Mozo",
    "Cocina",
    "Caja",
    "Reportes",
    "Usuarios",
    "Menu",
    "Recetas",
    "Mesas",
    "Inventario",
    "Proveedores",
    "Promociones",
    "Turnos",
    "Facturación",
    "Sistema",
    "Backups",
]

ROLE_MODULES = {
    "mozo": ["Mozo"],
    "cocina": ["Cocina"],
    "caja": ["Caja", "Reportes"],
    "administrador": ADMIN_MODULES,
    "dueno": ADMIN_MODULES,
}

TERMINAL_MODULES = {"Mozo", "Cocina", "Caja", "Panel"}


def modules_for_role(role: str, terminal_lock: str | None = None) -> list[str]:
    if terminal_lock in TERMINAL_MODULES:
        return [terminal_lock]
    return list(ROLE_MODULES.get(str(role or "").strip().lower(), []))
