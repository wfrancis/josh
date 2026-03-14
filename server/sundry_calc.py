"""
Sundry calculator: given a material_type and installed_qty,
compute the required sundry items and quantities.
"""

import math
from config import SUNDRY_RULES


def _load_sundry_rules():
    """Load sundry rules from DB, falling back to config.py defaults."""
    try:
        from models import get_company_rate
        import json
        data = get_company_rate("sundry_rules")
        if data:
            return json.loads(data)
    except Exception:
        pass
    return SUNDRY_RULES


def calculate_sundries(material_type: str, installed_qty: float, sundry_rules: dict = None) -> list[dict]:
    """
    Calculate sundry items needed for a given material type and quantity.

    Args:
        material_type: e.g. "unit_carpet_no_pattern", "unit_lvt", "floor_tile"
        installed_qty: the installed quantity (in the material's native unit)
        sundry_rules: optional override for sundry rules (if None, loads from DB)
    """
    if sundry_rules is None:
        sundry_rules = _load_sundry_rules()

    rules = sundry_rules.get(material_type, [])
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
            continue

        effective_qty = installed_qty * (1 + waste) if waste else installed_qty
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
    Loads sundry rules from DB once for efficiency.
    """
    sundry_rules = _load_sundry_rules()
    all_sundries = []
    for mat in materials:
        material_type = mat.get("material_type", "")
        installed_qty = mat.get("installed_qty", 0)
        material_id = mat.get("id") or mat.get("item_code")

        sundries = calculate_sundries(material_type, installed_qty, sundry_rules)
        for s in sundries:
            s["material_id"] = material_id
        all_sundries.extend(sundries)

    return all_sundries
