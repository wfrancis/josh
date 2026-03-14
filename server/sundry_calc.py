"""
Sundry calculator: given a material_type and installed_qty,
compute the required sundry items and quantities.
"""

import math
from config import SUNDRY_RULES


def calculate_sundries(material_type: str, installed_qty: float) -> list[dict]:
    """
    Calculate sundry items needed for a given material type and quantity.

    Args:
        material_type: e.g. "unit_carpet_no_pattern", "unit_lvt", "floor_tile"
        installed_qty: the installed quantity (in the material's native unit)

    Returns:
        List of sundry items:
        [
            {
                "sundry_name": str,
                "qty": float,
                "unit": str,
                "notes": str | None,
            },
            ...
        ]
    """
    rules = SUNDRY_RULES.get(material_type, [])
    if not rules:
        return []

    results = []
    for rule in rules:
        sundry_name = rule["sundry_name"]
        coverage = rule.get("coverage")
        unit = rule.get("unit", "")
        waste = rule.get("waste", 0.0)
        notes = rule.get("notes")

        if coverage is None or coverage <= 0:
            # Special case: caulking or items without standard coverage
            # Skip items that don't have a calculable coverage
            continue

        # Apply waste to the installed qty for certain sundries (e.g. pad)
        effective_qty = installed_qty * (1 + waste) if waste else installed_qty

        # Calculate how many units are needed
        qty_needed = math.ceil(effective_qty / coverage)

        unit_price = rule.get("unit_price", 0)
        extended_cost = round(qty_needed * unit_price, 2)

        results.append({
            "sundry_name": sundry_name,
            "qty": qty_needed,
            "unit": unit,
            "unit_price": unit_price,
            "extended_cost": extended_cost,
            "notes": notes,
        })

    return results


def calculate_sundries_for_materials(materials: list[dict]) -> list[dict]:
    """
    Calculate sundries for a list of material line items.

    Args:
        materials: list of material dicts, each with at least
                   "material_type", "installed_qty", and optionally "id" or "item_code"

    Returns:
        Flat list of sundry items, each tagged with material_id or item_code.
    """
    all_sundries = []
    for mat in materials:
        material_type = mat.get("material_type", "")
        installed_qty = mat.get("installed_qty", 0)
        material_id = mat.get("id") or mat.get("item_code")

        sundries = calculate_sundries(material_type, installed_qty)
        for s in sundries:
            s["material_id"] = material_id
        all_sundries.extend(sundries)

    return all_sundries
