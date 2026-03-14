"""
Bid assembler: combines materials, sundries, labor, and freight
into bundled line items with descriptions and totals.
"""

from config import BID_TEMPLATES, WASTE_FACTORS, FREIGHT_RATES, EXCLUSIONS_TEMPLATE


def _get_freight_rate(material_type: str) -> float:
    """Look up freight rate for a material type. Returns 0 if none applies."""
    # Map material types to freight rate keys
    freight_map = {
        "cpt_tile": "cpt_tile",
        "corridor_broadloom": "broadloom",
        "unit_lvt": "lvt_5mm",  # Default to 5mm; could be parameterized
    }
    key = freight_map.get(material_type)
    if key:
        return FREIGHT_RATES.get(key, 0)
    return 0


def _get_template_key(material_type: str) -> str:
    """Map material_type to the BID_TEMPLATES key."""
    if material_type in ("unit_carpet_no_pattern", "unit_carpet_pattern"):
        return "unit_carpet"
    return material_type


def _generate_description(
    material_type: str,
    material: dict,
    installed_qty: float,
    unit: str,
) -> str:
    """Generate bid description text from template."""
    template_key = _get_template_key(material_type)
    template = BID_TEMPLATES.get(template_key)
    if not template:
        return f"Furnish, deliver and install {material.get('description', material_type)}\nInstalled QTY {installed_qty} {unit}"

    return template.format(
        product_name=material.get("description", ""),
        product_spec=material.get("description", ""),
        pattern=material.get("pattern", "Standard"),
        height=material.get("height", "TBD"),
        installed_qty=installed_qty,
        unit=unit,
    )


def assemble_bid(
    job_info: dict,
    materials: list[dict],
    sundries: list[dict],
    labor_items: list[dict],
    exclusions: list[str] = None,
) -> dict:
    """
    Assemble a complete bid from all components.

    Args:
        job_info: job details dict (project_name, tax_rate, etc.)
        materials: list of material dicts with pricing
        sundries: list of sundry dicts with pricing
        labor_items: list of labor dicts with rates

    Returns:
        {
            "job_info": dict,
            "bundles": [{bundle_name, description_text, installed_qty, unit,
                         material_cost, sundry_cost, labor_cost, freight_cost,
                         total_price}],
            "subtotal": float,
            "tax_rate": float,
            "tax_amount": float,
            "grand_total": float,
            "exclusions": [str],
        }
    """
    tax_rate = job_info.get("tax_rate", 0)
    markup_pct = job_info.get("markup_pct", 0) or 0

    # Index sundries and labor by material_id for fast lookup
    sundries_by_mat: dict[str, list[dict]] = {}
    for s in sundries:
        mid = s.get("material_id")
        sundries_by_mat.setdefault(mid, []).append(s)

    labor_by_mat: dict[str, list[dict]] = {}
    for l in labor_items:
        mid = l.get("material_id")
        labor_by_mat.setdefault(mid, []).append(l)

    bundles = []
    for mat in materials:
        material_type = mat.get("material_type", "unknown")
        installed_qty = mat.get("installed_qty", 0)
        unit = mat.get("unit", "")
        waste_pct = mat.get("waste_pct") or WASTE_FACTORS.get(material_type, 0)
        unit_price = mat.get("unit_price", 0)
        mat_id = mat.get("id") or mat.get("item_code")

        # Calculate order qty with waste
        order_qty = installed_qty * (1 + waste_pct)

        # Material cost
        material_cost = round(order_qty * unit_price, 2)

        # Sundry cost
        mat_sundries = sundries_by_mat.get(mat_id, [])
        sundry_cost = round(sum(s.get("extended_cost", 0) for s in mat_sundries), 2)

        # Labor cost
        mat_labor = labor_by_mat.get(mat_id, [])
        labor_cost = round(sum(l.get("extended_cost", 0) for l in mat_labor), 2)

        # Freight
        freight_rate = _get_freight_rate(material_type)
        freight_cost = round(order_qty * freight_rate, 2)

        # Total for this bundle
        total_price = round(material_cost + sundry_cost + labor_cost + freight_cost, 2)

        # Description text
        description_text = _generate_description(
            material_type, mat, installed_qty, unit
        )

        bundle_name = mat.get("item_code") or material_type
        bundles.append({
            "bundle_name": bundle_name,
            "material_type": material_type,
            "description_text": description_text,
            "installed_qty": installed_qty,
            "unit": unit,
            "waste_pct": waste_pct,
            "unit_price": unit_price,
            "material_cost": material_cost,
            "sundry_cost": sundry_cost,
            "labor_cost": labor_cost,
            "freight_cost": freight_cost,
            "total_price": total_price,
            "order_qty": round(order_qty, 2),
        })

    subtotal = round(sum(b["total_price"] for b in bundles), 2)
    markup_amount = round(subtotal * markup_pct, 2) if markup_pct else 0
    subtotal_with_markup = round(subtotal + markup_amount, 2)
    tax_amount = round(subtotal_with_markup * tax_rate, 2)
    grand_total = round(subtotal_with_markup + tax_amount, 2)

    return {
        "job_info": job_info,
        "bundles": bundles,
        "subtotal": subtotal,
        "markup_pct": markup_pct,
        "markup_amount": markup_amount,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "grand_total": grand_total,
        "exclusions": exclusions if exclusions is not None else EXCLUSIONS_TEMPLATE,
    }
