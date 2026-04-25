"""
Sundry calculator: given a material_type and installed_qty,
compute the required sundry items and quantities.

Supports RFMS-measured quantities for carpet sundries:
- tack_strip: uses measured tack_strip_lf / 400 LF per carton
- seam_tape: uses measured seam_tape_lf / 60 LF per roll
- pad: installed_qty * 1.05 / 30 SY per roll at $1.38/SY
"""

import math
import re
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


def _is_large_format_tile(description: str, min_w: float = 16, min_h: float = 30) -> bool:
    """Check if tile is large format (dims >= min_w x min_h, e.g. 16x30+)."""
    dim_match = re.findall(r'(\d+(?:\.\d+)?)\s*["\u201d]?\s*x\s*(\d+(?:\.\d+)?)\s*["\u201d]?', description.lower())
    if dim_match:
        w, h = float(dim_match[0][0]), float(dim_match[0][1])
        # Check both orientations (16x30 or 30x16)
        return (w >= min_w and h >= min_h) or (w >= min_h and h >= min_w)
    return False


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def calculate_sundries(
    material_type: str,
    installed_qty: float,
    sundry_rules: dict = None,
    material: dict = None,
    trace=None,
) -> list[dict]:
    """
    Calculate sundry items needed for a given material type and quantity.

    Args:
        material_type: e.g. "unit_carpet_no_pattern", "unit_lvt", "floor_tile"
        installed_qty: the installed quantity (in the material's native unit)
        sundry_rules: optional override for sundry rules (if None, loads from DB)
        material: optional full material dict with RFMS-measured fields
            (tack_strip_lf, seam_tape_lf, pad_sy)
    """
    if sundry_rules is None:
        sundry_rules = _load_sundry_rules()

    rules = sundry_rules.get(material_type, [])
    if not rules:
        return []

    material = material or {}

    results = []
    for rule in rules:
        sundry_name = rule["sundry_name"]
        coverage = rule.get("coverage")
        unit = rule.get("unit", "")
        waste = rule.get("waste", 0.0)
        notes = rule.get("notes")
        qty_source = rule.get("qty_source")

        if coverage is None or coverage <= 0:
            continue

        # Skip LFT thinset for tiles under 16x30
        min_tile_size = rule.get("min_tile_size")
        if min_tile_size:
            desc = material.get("description", "")
            if not _is_large_format_tile(desc):
                continue

        # Skip regular thinset when tile IS large format (use LFT thinset instead)
        if rule.get("skip_if_lft"):
            desc = material.get("description", "")
            if _is_large_format_tile(desc):
                continue

        # Grout: use tile-dimension-based formula from Custom Building Products Prism calculator
        # Coverage = 2.73 × (W × L) / ((W + L) × J × T) SF per 17 lb bag
        # where W,L = tile dims in inches, J = joint width, T = tile thickness
        qty_basis = rule.get("qty_basis")
        if qty_basis == "grout_formula":
            formula = "ceil(installed_qty / grout_coverage_per_bag)"
            desc = material.get("description", "")
            dims = re.findall(r'(\d+(?:\.\d+)?)\s*["\u201d]?\s*x\s*(\d+(?:\.\d+)?)\s*["\u201d]?', desc.lower())
            if dims:
                tw, tl = float(dims[0][0]), float(dims[0][1])
                # Default joint width 3/16", default thickness 3/8" (common commercial)
                joint = rule.get("joint_width", 0.1875)
                thickness = 0.25 if max(tw, tl) <= 6 else 0.375
                if (tw + tl) > 0 and joint > 0 and thickness > 0:
                    coverage_per_bag = 2.73 * (tw * tl) / ((tw + tl) * joint * thickness)
                    qty_needed = math.ceil(installed_qty / coverage_per_bag) if coverage_per_bag > 0 else 0
                else:
                    qty_needed = math.ceil(installed_qty / coverage) if coverage else 0
            else:
                # No dimensions found, fall back to flat coverage
                qty_needed = math.ceil(installed_qty / coverage) if coverage else 0
        elif qty_basis == "unit_count":
            basis_qty = _safe_float(material.get("unit_count"))
            qty_needed = math.ceil(basis_qty / coverage) if basis_qty > 0 else 0
            formula = "ceil(unit_count / coverage)"
        elif qty_basis == "tub_shower_total":
            basis_qty = _safe_float(material.get("tub_shower_total"))
            qty_needed = math.ceil(basis_qty / coverage) if basis_qty > 0 else 0
            formula = "ceil(tub_shower_total / coverage)"
        elif qty_source and _safe_float(material.get(qty_source)) > 0:
            # Use RFMS-measured quantity if available via qty_source
            source_qty = _safe_float(material.get(qty_source))
            qty_needed = math.ceil(source_qty / coverage)
            formula = f"ceil({qty_source} / coverage)"
        else:
            # Fallback: estimate from installed_qty
            effective_qty = installed_qty * (1 + waste) if waste else installed_qty
            # Convert SY → SF when material is in SY but sundry coverage is in SF
            mat_unit = (material.get("unit") or "").upper()
            coverage_unit = (unit or "").upper()
            if mat_unit == "SY" and "SF" in coverage_unit:
                effective_qty = effective_qty * 9
            qty_needed = math.ceil(effective_qty / coverage)
            formula = "ceil(installed_qty * (1 + waste) / coverage)"

        unit_price = rule.get("unit_price", 0)
        # Use white thinset price for mosaic or backsplash materials
        white_price = rule.get("white_price")
        if white_price and sundry_name == "thinset":
            if material.get("is_mosaic") or material_type == "backsplash":
                unit_price = white_price
        extended_cost = round(qty_needed * unit_price, 2)

        # Add freight cost per unit if defined (e.g. $5/pail for adhesive)
        freight_per_unit = rule.get("freight_per_unit", 0)
        freight_cost = round(qty_needed * freight_per_unit, 2) if freight_per_unit else 0

        results.append({
            "sundry_name": sundry_name,
            "qty": qty_needed,
            "unit": unit,
            "unit_price": unit_price,
            "extended_cost": extended_cost,
            "freight_per_unit": freight_per_unit,
            "freight_cost": freight_cost,
            "notes": notes,
        })

        if trace:
            material_id = material.get("id") or material.get("item_code")
            entity_key = f"{material_id}:{sundry_name}" if material_id else sundry_name
            inputs = {
                "material_id": material_id,
                "material_type": material_type,
                "installed_qty": installed_qty,
                "coverage": coverage,
                "waste": waste,
                "qty_basis": qty_basis,
                "qty_source": qty_source,
                "unit_price": unit_price,
            }
            trace.record(
                entity_type="sundry",
                entity_id=material_id,
                entity_key=entity_key,
                output_field="qty",
                formula=formula,
                inputs=inputs,
                result=qty_needed,
                rule_id=f"sundry:{material_type}:{sundry_name}",
                source="sundry_rules",
            )
            trace.record(
                entity_type="sundry",
                entity_id=material_id,
                entity_key=entity_key,
                output_field="extended_cost",
                formula="qty * unit_price",
                inputs={"qty": qty_needed, "unit_price": unit_price},
                result=extended_cost,
                rule_id=f"sundry:{material_type}:{sundry_name}",
                source="sundry_rules",
            )
            if freight_cost:
                trace.record(
                    entity_type="sundry",
                    entity_id=material_id,
                    entity_key=entity_key,
                    output_field="freight_cost",
                    formula="qty * freight_per_unit",
                    inputs={"qty": qty_needed, "freight_per_unit": freight_per_unit},
                    result=freight_cost,
                    rule_id=f"sundry:{material_type}:{sundry_name}",
                    source="sundry_rules",
                )

    return results


def calculate_sundries_for_materials(materials: list[dict], trace=None) -> list[dict]:
    """
    Calculate sundries for a list of material line items.
    Loads sundry rules from DB once for efficiency.

    Job-level sundries (qty_basis = "tub_shower_total" or "unit_count") are
    allocated to ONE material per (material_type, sundry_name). Without this
    dedup, a job with multiple tub_shower_surround materials (e.g. T-202,
    T-203, T-116) would get caulking billed N times instead of once —
    the rule uses the job's tub_shower_count regardless of which material
    it fires on.
    """
    sundry_rules = _load_sundry_rules()
    all_sundries = []

    # Sort so the largest-qty material of each type receives the job-level
    # sundries; smaller alternates / accent pieces (T-116 mosaic under
    # tub_shower_surround, premium alternates, etc.) get skipped.
    ordered = sorted(
        materials,
        key=lambda m: (m.get("material_type") or "", -(_safe_float(m.get("installed_qty")))),
    )

    emitted_job_level: set[tuple[str, str]] = set()
    JOB_LEVEL_BASES = {"tub_shower_total", "unit_count"}

    for mat in ordered:
        material_type = mat.get("material_type", "")
        installed_qty = mat.get("installed_qty", 0)
        material_id = mat.get("id") or mat.get("item_code")

        sundries = calculate_sundries(
            material_type, installed_qty, sundry_rules, material=mat, trace=trace
        )

        rules_for_type = sundry_rules.get(material_type, [])
        rule_by_name = {r.get("sundry_name"): r for r in rules_for_type}
        filtered = []
        for s in sundries:
            rule = rule_by_name.get(s.get("sundry_name"))
            if rule and rule.get("qty_basis") in JOB_LEVEL_BASES:
                key = (material_type, s["sundry_name"])
                if key in emitted_job_level:
                    continue  # job-level sundry already allocated to primary material
                emitted_job_level.add(key)
            filtered.append(s)

        for s in filtered:
            s["material_id"] = material_id
        all_sundries.extend(filtered)

    return all_sundries
