"""Mapa centralizado de categorias del menu premium.
Todas las vistas (menu, mozo, cocina) deben importar de aca
para garantizar consistencia entre la terminal y el KDS."""
from __future__ import annotations

CATEGORIAS_MENU: list[str] = [
    "Entradas",
    "Pastas",
    "Carnes",
    "Pescados",
    "Comidas Criollas",
    "Postres",
]

CATEGORIAS_LEGACY: list[str] = [
    "cocina",
    "bebidas",
    "postres",
]

CATEGORIAS_TOTAL: list[str] = CATEGORIAS_MENU + CATEGORIAS_LEGACY

PRECIOS_SUGERIDOS: dict[str, float] = {
    "Entradas": 12000,
    "Pastas": 15000,
    "Carnes": 22000,
    "Pescados": 18000,
    "Comidas Criollas": 13000,
    "Postres": 8000,
    "cocina": 0,
    "bebidas": 0,
    "postres": 0,
}
