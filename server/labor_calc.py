"""
Labor calculator: match materials to labor catalog entries,
determine quantities based on LABOR_QTY_RULES, and compute costs.
"""

import json
import os
from typing import Optional

import openpyxl
import pdfplumber
from openai import OpenAI

from config import LABOR_QTY_RULES, WASTE_FACTORS
from models import save_labor_catalog_entries, get_labor_catalog_entries

LABOR_CATALOG_PROMPT = """You are parsing a labor rate catalog for a flooring/interiors contractor.
Extract every labor line item from this document into a JSON array.

For each entry, extract:
- labor_type: the category/type (e.g. "Carpet Stretch-In", "LVT Install", "Floor Tile", etc.)
- description: any additional description or notes
- cost: the cost/rate as a number (the contractor's cost per unit)
- retail_display: the retail/display price if shown, otherwise empty string
- unit: the unit of measure (e.g. "SY", "SF", "LF", "EA", "HR")
- gpm_markup: the GPM/markup percentage as a decimal if shown (e.g. 0.35 for 35%), otherwise 0

Return JSON in this exact format:
{"entries": [{"labor_type": "...", "description": "...", "cost": 0.00, "retail_display": "...", "unit": "...", "gpm_markup": 0.00}, ...]}

Important:
- Extract ALL labor entries, not just a sample
- Cost must be a number, not a string
- If a field is missing, use empty string for text or 0 for numbers
"""

# Map material types to labor catalog type keywords
MATERIAL_TO_LABOR_MAP: dict[str, list[str]] = {
    "unit_carpet_no_pattern": ["carpet", "stretch"],
    "unit_carpet_pattern": ["carpet", "stretch", "pattern"],
    "unit_lvt": ["lvt", "vinyl plank", "luxury vinyl"],
    "cpt_tile": ["carpet tile"],
    "corridor_broadloom": ["broadloom", "direct glue carpet"],
    "floor_tile": ["floor tile", "ceramic", "porcelain"],
    "wall_tile": ["wall tile"],
    "backsplash": ["backsplash", "wall tile"],
    "tub_shower_surround": ["tub", "shower", "surround", "wall tile"],
    "rubber_base": ["rubber base", "base"],
    "vct": ["vct", "vinyl composition"],
    "rubber_tile": ["rubber tile"],
    "rubber_sheet": ["rubber sheet"],
    "wood": ["wood", "hardwood"],
    "tread_riser": ["tread", "riser", "stair"],
    "transitions": ["transition", "reducer", "t-molding"],
    "waterproofing": ["waterproof", "membrane"],
}


def load_labor_catalog(file_path: str) -> list[dict]:
    """
    Parse the Labor Catalog Excel file and persist to database.
    Sheet1, columns A-F: Labor Type, Description, Cost, Retail Display, Unit, GPM Markup
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb[wb.sheetnames[0]]  # Sheet1

    catalog = []
    for row in ws.iter_rows(min_row=2, max_col=6, values_only=True):
        labor_type = str(row[0]).strip() if row[0] else ""
        description = str(row[1]).strip() if row[1] else ""
        cost = _safe_float(row[2])
        retail_display = str(row[3]).strip() if row[3] else ""
        unit = str(row[4]).strip() if row[4] else ""
        gpm_markup = _safe_float(row[5])

        if not labor_type:
            continue

        catalog.append({
            "labor_type": labor_type,
            "description": description,
            "cost": cost,
            "retail_display": retail_display,
            "unit": unit,
            "gpm_markup": gpm_markup,
        })

    wb.close()
    save_labor_catalog_entries(catalog)
    return catalog


def load_labor_catalog_from_pdf(file_path: str, api_key: str = None, model: str = "gpt-5-mini") -> list[dict]:
    """
    Parse a Labor Catalog PDF using pdfplumber + OpenAI and persist to database.
    """
    # Extract text from PDF
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    text = "\n".join(text_parts)

    if not text.strip():
        raise ValueError("Could not extract text from labor catalog PDF")

    # Call OpenAI to parse the labor entries
    client_kwargs = {}
    if api_key:
        client_kwargs["api_key"] = api_key
    client = OpenAI(**client_kwargs)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": LABOR_CATALOG_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    parsed = json.loads(content)
    entries = parsed.get("entries", [])

    catalog = []
    for entry in entries:
        labor_type = str(entry.get("labor_type", "")).strip()
        if not labor_type:
            continue
        catalog.append({
            "labor_type": labor_type,
            "description": str(entry.get("description", "")).strip(),
            "cost": _safe_float(entry.get("cost")),
            "retail_display": str(entry.get("retail_display", "")).strip(),
            "unit": str(entry.get("unit", "")).strip(),
            "gpm_markup": _safe_float(entry.get("gpm_markup")),
        })

    save_labor_catalog_entries(catalog)
    return catalog


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _find_labor_entry(material_type: str, catalog: list[dict] = None) -> Optional[dict]:
    """Find the best matching labor catalog entry for a material type."""
    keywords = MATERIAL_TO_LABOR_MAP.get(material_type, [])
    if not keywords:
        return None

    if catalog is None:
        catalog = get_labor_catalog_entries()

    for entry in catalog:
        entry_text = f"{entry['labor_type']} {entry['description']}".lower()
        for kw in keywords:
            if kw.lower() in entry_text:
                return entry

    return None


def _get_labor_qty_rule(material_type: str) -> str:
    """Get the labor quantity rule for a material type."""
    # Check specific rules first
    for key, rule in LABOR_QTY_RULES.items():
        if key == "default":
            continue
        if key in material_type:
            return rule
    return LABOR_QTY_RULES["default"]


def calculate_labor(
    material_type: str,
    installed_qty: float,
    waste_pct: Optional[float] = None,
    measure_qty: Optional[float] = None,
) -> Optional[dict]:
    """
    Calculate labor for a material line item.

    Args:
        material_type: e.g. "unit_carpet_no_pattern"
        installed_qty: base installed quantity
        waste_pct: waste percentage (if None, looked up from WASTE_FACTORS)
        measure_qty: quantity from measure file (for "from_measure" rule)

    Returns:
        {
            "labor_description": str,
            "qty": float,
            "unit": str,
            "rate": float,
            "extended_cost": float,
        }
        or None if no matching labor entry found.
    """
    entry = _find_labor_entry(material_type)
    if not entry:
        return None

    if waste_pct is None:
        waste_pct = WASTE_FACTORS.get(material_type, 0)

    # Determine labor qty based on rule
    rule = _get_labor_qty_rule(material_type)
    if rule == "with_waste":
        labor_qty = installed_qty * (1 + waste_pct)
    elif rule == "no_waste":
        labor_qty = installed_qty
    elif rule == "from_measure" and measure_qty is not None:
        labor_qty = measure_qty
    else:
        labor_qty = installed_qty * (1 + waste_pct)

    rate = entry["cost"]
    extended_cost = labor_qty * rate

    return {
        "labor_description": f"{entry['labor_type']} - {entry['description']}",
        "qty": round(labor_qty, 2),
        "unit": entry["unit"],
        "rate": rate,
        "extended_cost": round(extended_cost, 2),
    }


def calculate_labor_for_materials(materials: list[dict]) -> list[dict]:
    """
    Calculate labor for a list of material line items.
    Loads labor catalog from DB once for efficiency.
    """
    catalog = get_labor_catalog_entries()
    results = []
    for mat in materials:
        material_type = mat.get("material_type", "")
        installed_qty = mat.get("installed_qty", 0)
        waste_pct = mat.get("waste_pct")
        material_id = mat.get("id") or mat.get("item_code")

        entry = _find_labor_entry(material_type, catalog)
        if not entry:
            continue

        if waste_pct is None:
            waste_pct = WASTE_FACTORS.get(material_type, 0)

        rule = _get_labor_qty_rule(material_type)
        if rule == "with_waste":
            labor_qty = installed_qty * (1 + waste_pct)
        elif rule == "no_waste":
            labor_qty = installed_qty
        else:
            labor_qty = installed_qty * (1 + waste_pct)

        rate = entry["cost"]
        extended_cost = labor_qty * rate

        results.append({
            "labor_description": f"{entry['labor_type']} - {entry['description']}",
            "qty": round(labor_qty, 2),
            "unit": entry["unit"],
            "rate": rate,
            "extended_cost": round(extended_cost, 2),
            "material_id": material_id,
        })

    return results


def get_labor_catalog() -> list[dict]:
    """Return the labor catalog from the database."""
    return get_labor_catalog_entries()
