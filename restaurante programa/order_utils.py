"""Utilidades puras para pedidos y carrito."""
from __future__ import annotations


MAX_ORDER_NOTE_LENGTH = 240


def normalize_order_cart(cart: dict) -> list[dict]:
    """Convierte un carrito de pantalla en renglones validos para guardar."""
    merged: dict[int, dict] = {}
    for item in cart.values():
        try:
            quantity = int(item.get("cantidad", 0) or 0)
            product_id = int(item["id_producto"])
        except (KeyError, TypeError, ValueError):
            continue
        if quantity <= 0:
            continue

        note = str(item.get("observaciones", "") or "").strip()
        note = " ".join(note.split())[:MAX_ORDER_NOTE_LENGTH]

        if product_id not in merged:
            merged[product_id] = {
                "id_producto": product_id,
                "cantidad": quantity,
                "observaciones": note,
            }
            continue

        merged[product_id]["cantidad"] += quantity
        if note and note not in merged[product_id]["observaciones"]:
            current = merged[product_id]["observaciones"]
            merged[product_id]["observaciones"] = f"{current}; {note}".strip("; ")[:MAX_ORDER_NOTE_LENGTH]

    return list(merged.values())
