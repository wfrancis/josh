"""
Proposal bundler: intelligently groups job materials into proposal bundles
matching the format from a real Standard Interiors proposal.

Bundles group related materials (e.g., all unit carpet, all unit LVT) and
produce description text, totals, and metadata for the proposal editor.
"""

import re
from collections import defaultdict
from typing import Optional

from config import BID_TEMPLATES, FREIGHT_RATES, DERIVED_BUNDLE_RULES


# ─── Terms & Conditions (full 17-item list from reference proposal) ──────────
PROPOSAL_TERMS: list[str] = [
    (
        "Material pricing is very volatile at this time. Upon award Standard "
        "Interiors will provide dates that material pricing is secured until. "
        "Approval to order material must be provided from Contractor to avoid "
        "price impacts by those dates. If material is required to be purchased "
        "more than three months prior to installation Standard Interiors will "
        "require a change order to cover extended material storage costs."
    ),
    (
        "This proposal is valid for 30 days, should prices increase after this "
        "time period Standard Interiors (SI) reserves the right to re-negotiate "
        "pricing."
    ),
    (
        "Standard Interiors is not responsible for delays in shipping or "
        "discontinued products."
    ),
    (
        "Areas to receive flooring shall be clear of debris, materials and any "
        "contaminants which may inhibit the flooring installation. SI will "
        "remove leftover material and do a construction clean however are not "
        "responsible for vacuuming or final clean."
    ),
    (
        "Standard Interiors will exercise due caution and care around existing "
        "finishes however some dust, clean and touch up of paint, trim, etc. "
        "should be expected after completion of flooring/tile installation, and "
        "is not the responsibility of Standard Interiors."
    ),
    (
        "Standard Interiors excludes removal of any concrete curing compounds, "
        "sealing compounds, solvents, cleaners, or any materials that could "
        "affect the bonding of flooring/tile to the concrete. It is the "
        "GC/Owners responsibility to inform Standard Interiors of the use of "
        "these materials on concrete slabs."
    ),
    (
        "Prior to installation of flooring/tile, it is the responsibility of "
        "the GC/Owner to test the concrete for vapor emission and alkalinity "
        "per ASTM F2170 and/or F1869, to confirm it is within the "
        "manufacturer's allowable tolerances. If the GC/Owner has not completed "
        "testing within two (2) weeks of installation Standard Interiors can "
        "test the areas to be installed at the GC/Owners expense or the "
        "warranty may be waived. If the results are outside of the "
        "manufacturers recommendations mitigation measures will be priced "
        "separately by SI. The GC/Owner may choose to waive the warranty"
    ),
    (
        "Standard Interiors is assuming that substrates are within acceptable "
        "tolerances and typical floor prep is included. Typical floor prep is "
        "defined as light skimcoating of hairline cracks or small (less than "
        '2" in diameter and 1/2" in depth) recesses. Anything above is not '
        "typical and will incur additional floor prep costs which are to be "
        "performed on T&M basis. Floor prep can be expensive and very time "
        "consuming."
    ),
    (
        "Standard Interiors will store excess material for 30 days from punch "
        "list completion. After that any excess material will be removed from "
        "the jobsite and disposed of. The GC/Owner needs to provide attic "
        "stock storage and submit quantities for each product."
    ),
    (
        "Standard Interiors is not responsible for the color variation of "
        "material. Color should be verified by the architect and/or owner's "
        "representative by samples and/or mockups prior to ordering material."
    ),
    (
        "Standard Interiors is not responsible for leveling of concrete "
        "substrate. Leveling will be performed on a T&M basis. Acceptable "
        'tolerances per ASTM are 3/16" in 10\' for commercial flooring and '
        '1/8" in 10\' for tile flooring.'
    ),
    (
        "If Standard Interiors incurs any costs or expenses to enforce its "
        "rights under this agreement or to collect any amounts due, purchaser "
        "agrees to pay Standard Interiors for all such costs and expenses, "
        "including reasonable attorney's fees and monthly interest of 1.5%."
    ),
    (
        "Code compliance with all Authorities Having Jurisdiction is the "
        "responsibility of the Architect and GC. Standard Interiors is not "
        "responsible for checking work of others on the plans or as "
        "constructed in the field for compliance with code requirements."
    ),
    (
        "Standard Interiors will assign a Superintendent to the project who "
        "will make daily visits to the project site, attend weekly "
        "subcontractor meetings and be available to make decisions daily. Full "
        "time on site supervision will be by the individual crew foremen."
    ),
    (
        "Standard Interiors has allocated manpower to this project based upon "
        "the schedule provided at time of contract. If project schedule delays "
        "manpower may be allocated to other projects resulting in Standard "
        "Interiors not being able to perform the work at the new schedule "
        "dates and/or requiring a change order for increased labor costs to "
        "staff the project."
    ),
    (
        "Standard Interiors reserves the right to stop work if payment is "
        "greater than thirty (30) days past due at any point during the "
        "project without any recourse from the GC/Owner and/or Purchaser for "
        "delay or similar damages."
    ),
    (
        "Price increases due to tariffs or trade disputes may result in "
        "additional costs."
    ),
]


# ─── Exclusions (full 18-item list from reference proposal) ──────────────────
PROPOSAL_EXCLUSIONS: list[str] = [
    "Waterproofing (unless specifically included in scope)",
    "Sound underlayment",
    "All flooring and tile substrates",
    (
        "Demo, Hoisting, Forklift, and/or Elevator for transport to work area "
        "provided by customer"
    ),
    (
        "Grounding and Testing of Static Dissipative Flooring/ESD flooring is "
        "by qualified electrician provided by customer"
    ),
    (
        "Waxing & Sealing of all materials as this is part of the customers "
        "maintenance program"
    ),
    (
        "Countertops, wood base, solid surface products, elevator cab finishes, "
        "FRP, Sealing or Staining of Concrete Exterior and/or landscaping tile "
        "or flooring products"
    ),
    (
        "Caulking to material installed by other trades, including base, trim, "
        "cabinets, toilets, bathtubs, shower pans, windows, doors, etc."
    ),
    "Floor protection, protection of other trades finished materials",
    (
        "Touchup or repairs required to wall base installed prior to flooring "
        "for primer, adhesive and scratches from lvt and carpet installation"
    ),
    "Bonding",
    "Prevailing Wage, Davis Bacon, or other related programs",
    "Credits for participation in OCIP/CCIP programs",
    "Door modification & cut down",
    "Clean-up program participation",
    "Temporary HVAC and/or weather protection",
    "Price increases due to tariffs or trade disputes",
    (
        "Extended project durations may incur additional supervision and "
        "material storage fees"
    ),
]


# ─── Location keywords that trigger a separate bundle for transitions ────────
_SPECIAL_LOCATION_KEYWORDS = [
    "amenity", "boh", "parking", "elevator", "lobby", "dog wash",
    "fitness", "club", "pool", "leasing", "mail", "trash",
]

# Regex for F-### and W-### item codes
_F_CODE_RE = re.compile(r"^F-?\d+", re.IGNORECASE)
_W_CODE_RE = re.compile(r"^W-?\d+", re.IGNORECASE)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    """Convert a value to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _config_freight_rate(material_type: str) -> float:
    """Look up freight rate from config FREIGHT_RATES by material type."""
    _freight_map = {
        "cpt_tile": "cpt_tile",
        "corridor_broadloom": "broadloom",
        "unit_carpet_no_pattern": "broadloom",
        "unit_carpet_pattern": "broadloom",
        "unit_lvt": "lvt_2mm",
    }
    key = _freight_map.get(material_type)
    if key:
        return FREIGHT_RATES.get(key, 0)
    return 0


def _parse_scheme_letters(desc: str) -> set[str]:
    """Parse all scheme letters from a description string.

    Handles formats like:
      "(Scheme A)"       -> {"A"}
      "(Scheme A & B)"   -> {"A", "B"}
      "(Scheme A&B)"     -> {"A", "B"}
      "(Scheme A, B & C)" -> {"A", "B", "C"}
    """
    desc_upper = desc.upper()
    letters = set()
    # First, find the full "(SCHEME ...)" block and extract all letters from it
    block_match = re.search(r"\(SCHEME\s+([^)]+)\)", desc_upper)
    if block_match:
        # Extract all single uppercase letters from the block content
        # e.g. "A & B" -> ["A", "B"], "A" -> ["A"]
        block_content = block_match.group(1)
        for ch in re.findall(r"[A-Z]", block_content):
            letters.add(ch)
    else:
        # Fallback: find individual "SCHEME X" patterns (letter must be alone, not part of a word)
        for match in re.finditer(r"SCHEME\s+([A-Z])(?![A-Z])", desc_upper):
            letters.add(match.group(1))
    return letters


def _extract_schemes(materials: list[dict]) -> str:
    """Detect scheme labels (A, B, C, ...) from material descriptions."""
    schemes = set()
    for mat in materials:
        desc = mat.get("description") or ""
        schemes.update(_parse_scheme_letters(desc))
    if not schemes:
        return ""
    sorted_schemes = sorted(schemes)
    if len(sorted_schemes) == 1:
        return f"(Scheme {sorted_schemes[0]})"
    return f"(Scheme {'&'.join(sorted_schemes)})"


def _get_scheme_label(mat: dict) -> Optional[str]:
    """Extract the scheme letter from a single material description.
    For materials with multiple schemes (A & B), returns the first one."""
    desc = mat.get("description") or ""
    letters = _parse_scheme_letters(desc)
    if not letters:
        return None
    return sorted(letters)[0]


def _get_option_label(mat: dict) -> Optional[str]:
    """Extract option prefix (Standard, Premium, Alternate) from item_code.
    e.g. '(Standard) CPT-200' → 'Standard', '(Premium) T-203' → 'Premium'"""
    item_code = (mat.get("item_code") or "").strip()
    m = re.match(r'^\((\w+)\)', item_code)
    if m:
        label = m.group(1).title()
        if label.lower() in ("standard", "premium", "alternate", "budget", "base", "upgrade"):
            return label
    return None


def _strip_option_prefix(item_code: str) -> str:
    """Strip option prefix from item_code for regex matching.
    '(Standard) CPT-200' → 'CPT-200', '(Premium) F102' → 'F102'"""
    return re.sub(r'^\([^)]+\)\s*', '', item_code.strip())


def _description_contains_location(mat: dict) -> Optional[str]:
    """Check if a material description references a special location.
    Returns the location keyword found, or None."""
    desc = (mat.get("description") or "").lower()
    item_code = (mat.get("item_code") or "").lower()
    combined = f"{desc} {item_code}"
    for kw in _SPECIAL_LOCATION_KEYWORDS:
        if kw in combined:
            return kw
    return None


def _is_boh(mat: dict) -> bool:
    """Check if material is back-of-house."""
    desc = (mat.get("description") or "").lower()
    item_code = (mat.get("item_code") or "").lower()
    return "boh" in desc or "boh" in item_code or "back of house" in desc


def _build_description(
    template_key: str,
    materials: list[dict],
    installed_qty: float,
    unit: str,
    extra_lines: list[str] = None,
) -> str:
    """Build multi-line description text from a BID_TEMPLATES key or fallback."""
    # Use the first material for product spec details
    primary = materials[0] if materials else {}
    product_name = primary.get("description", "")
    product_spec = product_name
    pattern = primary.get("pattern", "Standard")
    height = primary.get("height", "TBD")

    # If multiple materials, list them all in the spec
    if len(materials) > 1:
        specs = [m.get("description", "") for m in materials if m.get("description")]
        product_spec = " / ".join(specs) if specs else product_name

    template = BID_TEMPLATES.get(template_key)
    if template:
        try:
            text = template.format(
                product_name=product_name,
                product_spec=product_spec,
                pattern=pattern,
                height=height,
                installed_qty=round(installed_qty, 2),
                unit=unit,
            )
        except KeyError:
            text = (
                f"Furnish, deliver and install {product_spec}\n"
                f"Installed QTY {round(installed_qty, 2)} {unit}"
            )
    else:
        text = (
            f"Furnish, deliver and install {product_spec}\n"
            f"Installed QTY {round(installed_qty, 2)} {unit}"
        )

    if extra_lines:
        text += "\n" + "\n".join(extra_lines)

    return text


def _sum_material_costs(
    materials: list[dict],
    sundries_by_mat: dict,
    labor_by_mat: dict,
) -> dict:
    """Sum up costs across a group of materials.

    Returns dict with material_cost, sundry_cost, labor_cost, freight_cost,
    total_price, installed_qty, unit, and the materials list itself.
    """
    material_cost = 0.0
    sundry_cost = 0.0
    labor_cost = 0.0
    freight_cost = 0.0
    installed_qty = 0.0
    unit = ""
    sundry_items = []
    labor_items_list = []

    for mat in materials:
        mat_id = mat.get("id") or mat.get("item_code")
        mat_ext = _safe_float(mat.get("extended_cost"))
        material_cost += mat_ext
        installed_qty += _safe_float(mat.get("installed_qty"))
        if not unit:
            unit = mat.get("unit", "")

        for s in sundries_by_mat.get(mat_id, []):
            sundry_cost += _safe_float(s.get("extended_cost"))
            freight_cost += _safe_float(s.get("freight_cost"))
            sundry_items.append(s)

        for l in labor_by_mat.get(mat_id, []):
            labor_cost += _safe_float(l.get("extended_cost"))
            labor_items_list.append(l)

        # Calculate freight: freight_per_unit * order_qty, fall back to config FREIGHT_RATES
        freight_per_unit = _safe_float(mat.get("freight_per_unit"))
        if freight_per_unit <= 0:
            # Fall back to config freight rates by material type
            freight_per_unit = _config_freight_rate(mat.get("material_type", ""))
        order_qty = _safe_float(mat.get("order_qty", mat.get("installed_qty", 0)))
        if freight_per_unit > 0:
            freight_cost += round(freight_per_unit * order_qty, 2)

    total_price = material_cost + sundry_cost + labor_cost + freight_cost

    return {
        "material_cost": round(material_cost, 2),
        "sundry_cost": round(sundry_cost, 2),
        "labor_cost": round(labor_cost, 2),
        "freight_cost": round(freight_cost, 2),
        "total_price": round(total_price, 2),
        "installed_qty": round(installed_qty, 2),
        "unit": unit,
        "sundry_items": sundry_items,
        "labor_items": labor_items_list,
    }


def _make_bundle(
    bundle_name: str,
    materials: list[dict],
    sundries_by_mat: dict,
    labor_by_mat: dict,
    template_key: str = "",
    extra_desc_lines: list[str] = None,
) -> dict:
    """Create a single bundle dict from a group of materials."""
    costs = _sum_material_costs(materials, sundries_by_mat, labor_by_mat)

    description_text = _build_description(
        template_key=template_key,
        materials=materials,
        installed_qty=costs["installed_qty"],
        unit=costs["unit"],
        extra_lines=extra_desc_lines,
    )

    return {
        "bundle_name": bundle_name,
        "description_text": description_text,
        "materials": materials,
        "sundry_items": costs["sundry_items"],
        "labor_items": costs["labor_items"],
        "material_cost": costs["material_cost"],
        "sundry_cost": costs["sundry_cost"],
        "labor_cost": costs["labor_cost"],
        "freight_cost": costs["freight_cost"],
        "total_price": costs["total_price"],
        "installed_qty": costs["installed_qty"],
        "unit": costs["unit"],
        "editable": True,
    }


# ─── Classification ─────────────────────────────────────────────────────────

def _classify_material(mat: dict) -> tuple[str, str]:
    """Classify a material into a bundle group.

    Returns (group_key, template_key) where group_key is used as a dict key
    for grouping and template_key maps to BID_TEMPLATES.

    Group key conventions:
        "f_code:F-102"     -> individual F-### bundle
        "w_code:W-127"     -> individual W-### bundle
        "unit_cpt"         -> Unit CPT
        "corridor_broadloom" -> Corridor Broadloom
        "unit_lvt"         -> Unit LVT
        "boh_lvt"          -> BOH LVT
        "tub_shower"       -> Unit Tile Surrounds
        "waterproofing"    -> Unit Tile Surround Waterproofing
        "backsplash:A"     -> Unit Backsplash (Scheme A)
        "transitions:unit" -> Unit Transitions
        "transitions:loc"  -> location-specific transition bundle
        "rubber_base"      -> BOH and Stair Landing Rubber Base
        "boh_rubber_base"  -> BOH Rubber Base (when BOH-specific)
        "individual:..."   -> catch-all individual bundle
    """
    item_code = (mat.get("item_code") or "").strip()
    material_type = (mat.get("material_type") or "").strip().lower()
    desc = (mat.get("description") or "").lower()
    area_type = (mat.get("area_type") or "unit").lower()
    option_label = _get_option_label(mat)  # "Standard", "Premium", etc. or None
    bare_code = _strip_option_prefix(item_code)  # strip "(Standard) " for regex matching

    # ── Rule 1: F-### codes → individual bundles
    if _F_CODE_RE.match(bare_code):
        group_key, tmpl = f"f_code:{bare_code.upper()}", "floor_tile"
    # ── Rule 2: W-### codes → individual bundles
    elif _W_CODE_RE.match(bare_code):
        group_key, tmpl = f"w_code:{bare_code.upper()}", "wall_tile"
    # ── Rule 3: Transitions
    elif material_type == "transitions":
        location = _description_contains_location(mat)
        if location:
            group_key, tmpl = f"transitions:{location}", "transitions"
        else:
            group_key, tmpl = "transitions:unit", "transitions"
    # ── Rule 4: Carpet / Broadloom
    elif material_type in (
        "unit_carpet_no_pattern", "unit_carpet_pattern",
        "carpet", "broadloom",
    ):
        if _is_boh(mat):
            group_key, tmpl = "boh_cpt", "unit_carpet"
        elif "corridor" in desc or material_type == "corridor_broadloom":
            group_key, tmpl = "corridor_broadloom", "corridor_broadloom"
        else:
            group_key, tmpl = "unit_cpt", "unit_carpet"
    elif material_type == "corridor_broadloom":
        group_key, tmpl = "corridor_broadloom", "corridor_broadloom"
    elif material_type == "cpt_tile":
        if _is_boh(mat):
            group_key, tmpl = "boh_cpt_tile", "cpt_tile"
        else:
            group_key, tmpl = "unit_cpt_tile", "cpt_tile"
    # ── Rule 5: Unit LVT
    elif material_type == "unit_lvt":
        if _is_boh(mat):
            group_key, tmpl = "boh_lvt", "unit_lvt"
        else:
            group_key, tmpl = "unit_lvt", "unit_lvt"
    # ── Rule 6: Tub/Shower Surrounds
    elif material_type == "tub_shower_surround":
        group_key, tmpl = "tub_shower", "tub_shower_surround"
    # ── Rule 7: Waterproofing
    elif material_type == "waterproofing":
        location = _description_contains_location(mat)
        if location:
            group_key, tmpl = f"waterproofing:{location}", "waterproofing"
        else:
            group_key, tmpl = "waterproofing:unit", "waterproofing"
    # ── Rule 8: Backsplash — group by scheme
    elif material_type == "backsplash":
        scheme = _get_scheme_label(mat)
        if scheme:
            group_key, tmpl = f"backsplash:{scheme}", "backsplash"
        else:
            group_key, tmpl = "backsplash:all", "backsplash"
    # ── Rule 9: Rubber Base
    elif material_type == "rubber_base":
        if _is_boh(mat):
            group_key, tmpl = "boh_rubber_base", "rubber_base"
        else:
            group_key, tmpl = "rubber_base", "rubber_base"
    # ── Rule 10: Other known types get their own group
    elif material_type in ("floor_tile", "wall_tile"):
        group_key, tmpl = f"{material_type}:{item_code or desc[:30]}", material_type
    elif material_type == "vct":
        group_key, tmpl = "vct", "unit_lvt"  # closest template
    elif material_type in ("wood", "rubber_tile", "rubber_sheet", "tread_riser"):
        group_key, tmpl = f"{material_type}:{item_code or 'all'}", material_type
    else:
        # ── Catch-all: individual bundle per material
        fallback_key = item_code or desc[:40] or str(id(mat))
        group_key, tmpl = f"individual:{fallback_key}", ""

    # Append option label (Standard/Premium) to separate variants into different bundles
    if option_label and not group_key.startswith(("f_code:", "w_code:", "individual:")):
        group_key = f"{group_key}:{option_label}"

    # Prefix with "common:" for common area materials to keep them separate
    if area_type == "common":
        group_key = f"common:{group_key}"

    return group_key, tmpl


# ─── Bundle Naming ───────────────────────────────────────────────────────────

_GROUP_DISPLAY_NAMES: dict[str, str] = {
    "unit_cpt": "Unit CPT",
    "unit_cpt_tile": "Unit Carpet Tile",
    "boh_cpt": "BOH Carpet",
    "boh_cpt_tile": "BOH Carpet Tile",
    "corridor_broadloom": "Corridor Broadloom",
    "unit_lvt": "Unit LVT",
    "boh_lvt": "BOH LVT",
    "tub_shower": "Unit Tile Surrounds",
    "rubber_base": "BOH and Stair Landing Rubber Base",
    "boh_rubber_base": "BOH Rubber Base",
    "vct": "VCT",
}


def _bundle_display_name(group_key: str, materials: list[dict]) -> str:
    """Convert a group key into a human-readable bundle name."""
    # Handle common area prefix — strip it, get base name, prepend "Common Area"
    if group_key.startswith("common:"):
        base_key = group_key[len("common:"):]
        base_name = _bundle_display_name(base_key, materials)
        # Replace "Unit" with "Common Area" if present, otherwise prepend
        if base_name.startswith("Unit "):
            return "Common Area" + base_name[4:]
        return f"Common Area {base_name}"

    # F-### and W-### codes
    if group_key.startswith("f_code:") or group_key.startswith("w_code:"):
        code = group_key.split(":", 1)[1]
        # Use just the code as the bundle name — description goes in description_text
        return code

    # Transitions
    if group_key == "transitions:unit":
        return "Unit Transitions"
    if group_key.startswith("transitions:"):
        location = group_key.split(":", 1)[1].title()
        return f"{location} Transitions"

    # Waterproofing
    if group_key == "waterproofing:unit":
        return "Unit Tile Surround Waterproofing"
    if group_key.startswith("waterproofing:"):
        location = group_key.split(":", 1)[1].title()
        return f"{location} Waterproofing"

    # Backsplash by scheme
    if group_key.startswith("backsplash:"):
        scheme = group_key.split(":", 1)[1]
        if scheme == "all":
            scheme_label = _extract_schemes(materials)
            return f"Unit Backsplash {scheme_label}".strip()
        return f"Unit Backsplash (Scheme {scheme})"

    # Static display names — check for option suffix (Standard/Premium/etc.)
    _OPTION_LABELS = {"standard", "premium", "alternate", "budget", "base", "upgrade"}
    parts = group_key.split(":")
    base_key = parts[0]
    option_suffix = parts[-1] if len(parts) > 1 and parts[-1].lower() in _OPTION_LABELS else None

    if base_key in _GROUP_DISPLAY_NAMES:
        display = _GROUP_DISPLAY_NAMES[base_key]
        # Append scheme labels for unit-level bundles if detectable
        if base_key in ("unit_cpt", "unit_lvt", "tub_shower"):
            scheme_label = _extract_schemes(materials)
            if scheme_label:
                display = f"{display} {scheme_label}"
        # Append option label (Standard/Premium)
        if option_suffix:
            display = f"{display} ({option_suffix})"
        return display

    # Individual / floor_tile / wall_tile with code
    if group_key.startswith("individual:"):
        label = group_key.split(":", 1)[1]
        return label.title() if label else "Miscellaneous"

    if group_key.startswith("floor_tile:") or group_key.startswith("wall_tile:"):
        code = group_key.split(":", 1)[1]
        if materials and materials[0].get("description"):
            return f"{code} - {materials[0]['description']}"
        return code

    # Fallback
    return group_key.replace("_", " ").replace(":", " - ").title()


# ─── Main Bundler ────────────────────────────────────────────────────────────

def auto_bundle_materials(
    materials: list[dict],
    sundries: list[dict] = None,
    labor_items: list[dict] = None,
) -> list[dict]:
    """Group materials into proposal bundles.

    Args:
        materials: list of material dicts (from job_materials table).
        sundries: list of sundry dicts (from job_sundries table).
            Each must have a ``material_id`` matching a material's id or item_code.
        labor_items: list of labor dicts (from job_labor table).
            Each must have a ``material_id`` matching a material's id or item_code.

    Returns:
        List of bundle dicts ready for the proposal editor.  Each bundle has:
            bundle_name, description_text, materials, material_cost, sundry_cost,
            labor_cost, freight_cost, total_price, installed_qty, unit, editable.
    """
    if not materials:
        return []

    sundries = sundries or []
    labor_items = labor_items or []

    # Index sundries and labor by material_id
    sundries_by_mat: dict[str, list[dict]] = defaultdict(list)
    for s in sundries:
        mid = s.get("material_id")
        if mid is not None:
            sundries_by_mat[mid].append(s)

    labor_by_mat: dict[str, list[dict]] = defaultdict(list)
    for l in labor_items:
        mid = l.get("material_id")
        if mid is not None:
            labor_by_mat[mid].append(l)

    # Classify and group materials
    groups: dict[str, list[dict]] = defaultdict(list)
    group_templates: dict[str, str] = {}
    group_order: list[str] = []  # preserve insertion order for stable output

    for mat in materials:
        group_key, template_key = _classify_material(mat)
        groups[group_key].append(mat)
        group_templates[group_key] = template_key
        if group_key not in group_order:
            group_order.append(group_key)

    # Define display order priorities so proposal reads logically:
    #   unit carpet -> unit lvt -> backsplash -> surrounds -> waterproofing
    #   -> transitions -> F-codes -> W-codes -> BOH -> everything else
    _ORDER_PRIORITY = {
        "unit_cpt": 10,
        "unit_cpt_tile": 11,
        "corridor_broadloom": 12,
        "unit_lvt": 20,
    }

    def _sort_key(group_key: str) -> tuple:
        # Top-level: ALL unit bundles before ALL common area bundles
        area_priority = 1000 if group_key.startswith("common:") else 0
        base = group_key.replace("common:", "").split(":")[0] if ":" in group_key else group_key
        priority = _ORDER_PRIORITY.get(base)
        if priority is not None:
            return (area_priority + priority, group_key)
        if group_key.startswith("backsplash:") or base == "backsplash":
            return (area_priority + 30, group_key)
        if base == "tub_shower":
            return (area_priority + 40, group_key)
        if base == "waterproofing" or group_key.startswith("waterproofing:"):
            return (area_priority + 50, group_key)
        if base == "sound_mat":
            return (area_priority + 55, group_key)
        if group_key.startswith("transitions:") or base == "transitions":
            loc = group_key.split(":", 1)[1] if ":" in group_key else "unit"
            return (area_priority + (60 if loc == "unit" else 61), group_key)
        if group_key.startswith("f_code:"):
            return (area_priority + 70, group_key)
        if group_key.startswith("w_code:"):
            return (area_priority + 80, group_key)
        if base in ("rubber_base", "boh_rubber_base"):
            return (area_priority + 90, group_key)
        if base in ("boh_lvt", "boh_cpt", "boh_cpt_tile"):
            return (area_priority + 95, group_key)
        if group_key.startswith("individual:"):
            return (area_priority + 200, group_key)
        return (area_priority + 100, group_key)

    sorted_keys = sorted(group_order, key=_sort_key)

    # Build bundle dicts
    bundles = []
    for group_key in sorted_keys:
        mats = groups[group_key]
        template_key = group_templates.get(group_key, "")
        bundle_name = _bundle_display_name(group_key, mats)

        bundle = _make_bundle(
            bundle_name=bundle_name,
            materials=mats,
            sundries_by_mat=sundries_by_mat,
            labor_by_mat=labor_by_mat,
            template_key=template_key,
        )
        bundles.append(bundle)

    return bundles


# ─── Derived Bundles (Waterproofing / Crack Isolation) ──────────────────────

def _generate_derived_bundles(job: dict, materials: list[dict]) -> list[dict]:
    """Auto-generate virtual bundles for waterproofing and crack isolation.

    - Unit Waterproofing: from tub_shower_surround net SF.
      RedGard pails + mesh tape + labor.
    - Common Area Crack Isolation: from common-area floor_tile.
      Uses crack_isolation_sf if available, else installed_qty.
      RedGard pails + labor.
    """
    import math
    derived = []
    unit_count = _safe_float(job.get("unit_count", 0))

    # ── Unit Waterproofing ────────────────────────────────────────────────
    # Skip derived waterproofing if RFMS already has a waterproofing material line
    # (e.g. "Liquid-Latex Rubber...Redgard" parsed as material_type=waterproofing)
    has_rfms_waterproofing = any(
        m.get("material_type") == "waterproofing" for m in materials
    )
    wp_rule = DERIVED_BUNDLE_RULES.get("waterproofing", {})
    surround_sf = sum(
        _safe_float(m.get("installed_qty"))
        for m in materials
        if m.get("material_type") == wp_rule.get("source_type")
    )
    if surround_sf > 0 and not has_rfms_waterproofing:
        pails = math.ceil(surround_sf / wp_rule["coverage_sf"])
        material_cost = round(pails * wp_rule["pail_cost"], 2)
        mesh_cost = round(math.ceil(unit_count / 100) * wp_rule["mesh_per_100_units"], 2) if unit_count > 0 else 0
        labor_cost = round(surround_sf * wp_rule["labor_rate_sf"], 2)
        total = material_cost + mesh_cost + labor_cost

        desc_lines = [
            f"Furnish, deliver and install {wp_rule['material_name']}",
            f"2 Coats of Fluid Applied Membrane on Tub/Shower Surround Walls",
            f"Includes Mesh Fabric for Corners and Seams",
            f"Coverage: {wp_rule['coverage_sf']} SF/pail, {pails} pails needed",
            f"Net Area: {round(surround_sf, 2)} SF",
        ]

        sundry_items = [
            {"sundry_name": "RedGard 5 Gal Pail", "qty": pails,
             "unit": "EA", "unit_price": wp_rule["pail_cost"],
             "extended_cost": material_cost},
        ]
        if mesh_cost > 0:
            sundry_items.append({
                "sundry_name": "Mesh Tape", "qty": math.ceil(unit_count / 100),
                "unit": "EA", "unit_price": wp_rule["mesh_per_100_units"],
                "extended_cost": mesh_cost,
            })

        labor_items = [{
            "labor_description": "Waterproofing Application",
            "qty": round(surround_sf, 2),
            "unit": "SF",
            "rate": wp_rule["labor_rate_sf"],
            "extended_cost": labor_cost,
        }]

        derived.append({
            "bundle_name": "Unit Waterproofing",
            "description_text": "\n".join(desc_lines),
            "materials": [],
            "sundry_items": sundry_items,
            "labor_items": labor_items,
            "material_cost": material_cost + mesh_cost,
            "sundry_cost": 0,
            "labor_cost": labor_cost,
            "freight_cost": 0,
            "total_price": total,
            "installed_qty": round(surround_sf, 2),
            "unit": "SF",
            "editable": True,
            "is_derived": True,
            "_sort_priority": 45,
        })

    # ── Common Area Crack Isolation ───────────────────────────────────────
    ci_rule = DERIVED_BUNDLE_RULES.get("crack_isolation", {})
    # Sum crack_isolation_sf from common-area floor_tile materials
    common_floor_mats = [
        m for m in materials
        if m.get("material_type") == ci_rule.get("source_type")
        and (m.get("area_type") or "unit").lower() == "common"
    ]
    ci_sf = sum(_safe_float(m.get("crack_isolation_sf")) for m in common_floor_mats)
    # Fallback: use installed_qty if crack_isolation_sf not captured
    if ci_sf <= 0:
        ci_sf = sum(_safe_float(m.get("installed_qty")) for m in common_floor_mats)

    if ci_sf > 0:
        pails = math.ceil(ci_sf / ci_rule["coverage_sf"])
        material_cost = round(pails * ci_rule["pail_cost"], 2)
        labor_cost = round(ci_sf * ci_rule["labor_rate_sf"], 2)
        total = material_cost + labor_cost

        desc_lines = [
            f"Furnish, deliver and install {ci_rule['material_name']}",
            f"Crack Isolation Membrane on Common Area Floor Tile",
            f"Coverage: {ci_rule['coverage_sf']} SF/pail, {pails} pails needed",
            f"Net Area: {round(ci_sf, 2)} SF",
        ]

        sundry_items = [
            {"sundry_name": "RedGard 5 Gal Pail", "qty": pails,
             "unit": "EA", "unit_price": ci_rule["pail_cost"],
             "extended_cost": material_cost},
        ]

        labor_items = [{
            "labor_description": "Crack Isolation Application",
            "qty": round(ci_sf, 2),
            "unit": "SF",
            "rate": ci_rule["labor_rate_sf"],
            "extended_cost": labor_cost,
        }]

        derived.append({
            "bundle_name": "Common Area Crack Isolation",
            "description_text": "\n".join(desc_lines),
            "materials": [],
            "sundry_items": sundry_items,
            "labor_items": labor_items,
            "material_cost": material_cost,
            "sundry_cost": 0,
            "labor_cost": labor_cost,
            "freight_cost": 0,
            "total_price": total,
            "installed_qty": round(ci_sf, 2),
            "unit": "SF",
            "editable": True,
            "is_derived": True,
            "_sort_priority": 46,
        })

    return derived


# ─── Proposal Generator ─────────────────────────────────────────────────────

def generate_proposal_data(job_id: int, job: dict) -> dict:
    """Generate full proposal data with bundles, totals, T&C, exclusions.

    Args:
        job_id: numeric job ID.
        job: fully loaded job dict from ``models.load_job()``.  Must contain
            ``materials``, ``sundries``, ``labor``, and job-level fields
            like ``tax_rate``.

    Returns:
        {
            "bundles": [...],
            "subtotal": float,
            "tax_rate": float,
            "tax_amount": float,
            "grand_total": float,
            "notes": [...],
            "terms": [...],
            "exclusions": [...],
        }
    """
    materials = job.get("materials", [])
    sundries = job.get("sundries", [])
    labor_items = job.get("labor", [])
    tax_rate = _safe_float(job.get("tax_rate", 0))

    bundles = auto_bundle_materials(
        materials=materials,
        sundries=sundries,
        labor_items=labor_items,
    )

    # ── Insert derived bundles (waterproofing, crack isolation) ───────────
    derived = _generate_derived_bundles(job, materials)
    for db in derived:
        name_lower = db["bundle_name"].lower()
        if "common area crack isolation" in name_lower:
            # Insert after the last common area floor material bundle
            # (Common Area F-codes, W-codes, etc.), before Common Area Transitions
            insert_idx = len(bundles)
            last_common_floor = -1
            for i, b in enumerate(bundles):
                bn = b["bundle_name"].lower()
                if bn.startswith("common area") and "transition" not in bn and "lvt" not in bn and "crack" not in bn:
                    last_common_floor = i
            if last_common_floor >= 0:
                insert_idx = last_common_floor + 1
            else:
                # Fallback: before common area transitions
                for i, b in enumerate(bundles):
                    bn = b["bundle_name"].lower()
                    if "common" in bn and "transition" in bn:
                        insert_idx = i
                        break
            bundles.insert(insert_idx, db)
        else:
            # Unit Waterproofing / Unit Crack Isolation: after tub_shower, before transitions
            # Unit Crack Isolation goes right after Unit Waterproofing
            insert_idx = len(bundles)
            if "crack isolation" in name_lower:
                # Find Unit Waterproofing and insert right after it
                for i, b in enumerate(bundles):
                    if "waterproofing" in b["bundle_name"].lower():
                        insert_idx = i + 1
                        break
            else:
                # Waterproofing: after surrounds, before transitions/F-codes
                for i, b in enumerate(bundles):
                    bn = b["bundle_name"].lower()
                    if "transition" in bn or bn.startswith("f1") or bn.startswith("w1"):
                        insert_idx = i
                        break
            bundles.insert(insert_idx, db)

    # ── Apply GPM (Gross Profit Margin) ──────────────────────────────────
    # GPM is calculated on the TOTAL project cost (material + sundry + freight + labor).
    # Revenue = TotalCost / (1 - GPM%), profit distributed proportionally across bundles.
    # The resulting profit is split: 97.93% loaded onto labor, 2.07% onto material.
    gpm_pct = _safe_float(job.get("gpm_pct", 0))
    total_cost = round(sum(
        b["material_cost"] + b["sundry_cost"] + b["freight_cost"] + b["labor_cost"]
        for b in bundles
    ), 2)

    if gpm_pct > 0 and gpm_pct < 1 and total_cost > 0:
        revenue = total_cost / (1 - gpm_pct)
        gpm_profit = round(revenue - total_cost, 2)
        # Split: 97.93% loaded onto labor, 2.07% onto material
        gpm_labor_adder = round(gpm_profit * 0.9793, 2)
        gpm_material_adder = round(gpm_profit - gpm_labor_adder, 2)

        # Distribute proportionally across bundles by total cost share
        for b in bundles:
            bundle_cost = b["material_cost"] + b["sundry_cost"] + b["freight_cost"] + b["labor_cost"]
            if total_cost > 0 and bundle_cost > 0:
                share = bundle_cost / total_cost
                b["gpm_labor_adder"] = round(gpm_labor_adder * share, 2)
                b["gpm_material_adder"] = round(gpm_material_adder * share, 2)
            else:
                b["gpm_labor_adder"] = 0
                b["gpm_material_adder"] = 0

            b["gpm_adder"] = b["gpm_labor_adder"] + b["gpm_material_adder"]
            b["total_price"] = round(bundle_cost + b["gpm_adder"], 2)

    # ── Calculate per-bundle tax ──────────────────────────────────────────
    # Tax applies only to materials (material + sundry + freight + GPM material adder), not labor
    for b in bundles:
        b_taxable = b["material_cost"] + b["sundry_cost"] + b["freight_cost"] + b.get("gpm_material_adder", 0)
        b["taxable"] = round(b_taxable, 2)
        b["tax_amount"] = round(b_taxable * tax_rate, 2)
        b["total_price"] = round(b["total_price"] + b["tax_amount"], 2)

    subtotal = round(sum(b["total_price"] for b in bundles), 2)
    taxable = round(sum(b["taxable"] for b in bundles), 2)
    tax_amount = round(sum(b["tax_amount"] for b in bundles), 2)
    grand_total = subtotal  # tax is already included in each bundle's total_price

    # ── Textura fee (0.22% of total project dollars, capped at $5,000) ───
    textura_fee = int(job.get("textura_fee", 0))
    textura_amount = min(round(grand_total * 0.0022, 2), 5000.00) if textura_fee else 0
    if textura_fee:
        grand_total = round(grand_total + textura_amount, 2)

    # Qualification notes — auto-generated from the bundles present
    notes = _build_qualification_notes(bundles, job)

    return {
        "bundles": bundles,
        "subtotal": subtotal,
        "taxable": taxable,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "textura_fee": textura_fee,
        "textura_amount": textura_amount,
        "grand_total": grand_total,
        "notes": notes,
        "terms": list(PROPOSAL_TERMS),
        "exclusions": list(PROPOSAL_EXCLUSIONS),
    }


def _build_qualification_notes(bundles: list[dict], job: dict) -> list[str]:
    """Build qualification/scope notes based on what bundles are present."""
    notes = []
    bundle_names_lower = [b["bundle_name"].lower() for b in bundles]
    has = lambda keyword: any(keyword in n for n in bundle_names_lower)

    project_name = job.get("project_name", "")
    if project_name:
        notes.append(
            f"This proposal is for the furnish, delivery, and installation of "
            f"flooring and tile scopes at {project_name}."
        )

    unit_count = job.get("unit_count", 0)
    if unit_count:
        notes.append(f"Quote is based on {unit_count} units.")

    if has("cpt") or has("carpet"):
        notes.append(
            "Carpet quantities include waste per SI SOP. "
            "Seaming diagrams will be provided upon award."
        )

    if has("lvt"):
        notes.append(
            "LVT installation is figured as direct glue over primed substrate. "
            "Sound mat is excluded unless specifically included."
        )

    if has("surround") or has("waterproofing"):
        notes.append(
            "Tub/shower surround tile heights are figured per architectural "
            "elevations. Waterproofing scope is as noted in the individual "
            "line items."
        )

    if has("transition"):
        notes.append(
            "Transition quantities are based on plan review and field "
            "verification may result in adjustments."
        )

    if has("backsplash"):
        notes.append(
            "Backsplash tile height is figured per architectural elevations."
        )

    return notes
