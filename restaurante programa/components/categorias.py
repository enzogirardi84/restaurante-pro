"""Mapa centralizado de categorias del menu premium.
Todas las vistas (menu, mozo, cocina) deben importar de aca
para garantizar consistencia entre terminales."""
from __future__ import annotations

import unicodedata

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


def normalizar_categoria(value: object) -> str:
    """Devuelve una clave estable para comparar categorias del menu."""
    raw = " ".join(str(value or "").strip().split())
    sin_tildes = unicodedata.normalize("NFKD", raw)
    ascii_text = "".join(ch for ch in sin_tildes if not unicodedata.combining(ch))
    key = ascii_text.casefold()
    aliases = {
        "bebida": "bebidas",
        "bebidas": "bebidas",
        "bodega": "bodega",
        "postre": "postres",
        "postres": "postres",
        "criollas": "comidas criollas",
        "comida criolla": "comidas criollas",
        "comidas criollas": "comidas criollas",
    }
    return aliases.get(key, key)


def categoria_coincide(actual: object, esperada: object) -> bool:
    return normalizar_categoria(actual) == normalizar_categoria(esperada)


def categorias_visibles(menu: list[dict], preferidas: list[str] | None = None) -> list[str]:
    """Ordena categorias por preferencia y conserva extras presentes."""
    preferidas = preferidas or CATEGORIAS_TOTAL
    presentes: dict[str, str] = {}
    for producto in menu:
        categoria = str(producto.get("categoria") or "").strip()
        if not categoria:
            continue
        presentes.setdefault(normalizar_categoria(categoria), categoria)

    ordenadas: list[str] = []
    usados: set[str] = set()
    for categoria in preferidas:
        key = normalizar_categoria(categoria)
        if key in presentes and key not in usados:
            ordenadas.append(presentes[key])
            usados.add(key)

    for key, categoria in sorted(presentes.items(), key=lambda item: item[1].casefold()):
        if key not in usados:
            ordenadas.append(categoria)
    return ordenadas


def productos_de_categoria(menu: list[dict], categoria: object, filtro: str = "") -> list[dict]:
    """Filtra productos por categoria y texto sin depender de mayusculas/tildes."""
    filtro_norm = normalizar_categoria(filtro) if filtro else ""
    productos: list[dict] = []
    for producto in menu:
        if not categoria_coincide(producto.get("categoria"), categoria):
            continue
        if filtro_norm and filtro_norm not in normalizar_categoria(producto.get("nombre")):
            continue
        productos.append(producto)
    return productos
