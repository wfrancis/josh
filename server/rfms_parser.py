"""
Parse RFMS Measure pivot table Excel files (.xlsx).
Reads the "By Item" sheet for material summaries and "Customer" sheet for job info.

The "By Item" sheet layout:
  Rows 1-6: Work order header (company name, address, date)
  Row 7:    Column headers — DESCRIPTION | QUANTITY | LINE TOTAL
  Row 8+:   Material/sundry/labor line items
  Last row:  "Grand Total"

Strategy:
  1. Read all rows from "By Item" sheet.
  2. Separate into: material lines, install lines, sundry lines.
  3. Send material + install lines to OpenAI GPT to classify each material
     by matching it to its corresponding install line.
  4. If AI is unavailable, materials stay "unknown" for manual review.
"""

import json
import os
import re
from typing import Optional

import openpyxl

# ── Valid material types for the bid tool ─────────────────────────────────────
VALID_MATERIAL_TYPES = [
    "unit_carpet_no_pattern",
    "unit_carpet_pattern",
    "unit_lvt",
    "cpt_tile",
    "corridor_broadloom",
    "floor_tile",
    "wall_tile",
    "backsplash",
    "tub_shower_surround",
    "rubber_base",
    "vct",
    "rubber_tile",
    "rubber_sheet",
    "wood",
    "tread_riser",
    "transitions",
    "waterproofing",
]

# ── Sundry / skip patterns ───────────────────────────────────────────────────
SUNDRY_PREFIXES = [
    "adhesive",
    "thin set",
    "thinset",
    "crack isolation",
    "carpet pad",
    "tack strip",
    "seam seal",
    "isolation strip",
    "weld rod",
    "primer",
    "grout ",
    "caulk",
]


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_str(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _find_header_row(ws) -> int:
    for row in ws.iter_rows(min_row=1, max_row=20, max_col=3, values_only=False):
        a_val = _safe_str(row[0].value).lower()
        if "description" in a_val:
            return row[0].row
    return 7


def _is_sundry(desc: str) -> bool:
    desc_lower = desc.lower().strip()
    if not desc_lower or desc_lower in ("none", "none:"):
        return True
    # Strip scheme prefix before checking e.g. "(Scheme A & B) - Carpet Pad"
    clean = re.sub(r'^\(scheme\s+[a-z](?:\s*&\s*[a-z])?\)\s*-?\s*', '', desc_lower)
    for prefix in SUNDRY_PREFIXES:
        if desc_lower.startswith(prefix) or clean.startswith(prefix):
            return True
    return False


def _is_install(desc: str) -> bool:
    return desc.lower().strip().startswith("install")



def _extract_unit(desc: str, material_type: str) -> str:
    if material_type in ("rubber_base", "transitions"):
        return "LF"
    if material_type in ("corridor_broadloom", "unit_carpet_no_pattern", "unit_carpet_pattern"):
        return "SY"
    return "SF"


def _extract_item_label(desc: str) -> str:
    # Strip scheme prefix
    clean = re.sub(r'^\(Scheme\s+[A-Z](?:\s*&\s*[A-Z])?\)\s*', '', desc)
    # Match codes like F102, W131/W132/W133, B102
    m = re.match(r'^([A-Z]\d{2,4}(?:/[A-Z]\d{2,4})*)\b', clean)
    if m:
        return m.group(1)
    parts = clean.split(' - ')
    if parts:
        return parts[0].strip()[:30]
    return desc[:30]


# ── AI Classification ────────────────────────────────────────────────────────

AI_CLASSIFICATION_PROMPT = """You are a commercial flooring estimator assistant. I need you to classify each material line item from an RFMS takeoff pivot table.

You will receive two lists:
1. MATERIAL LINES — the actual materials that need to be classified
2. INSTALL LINES — these tell you what each material IS (e.g. "Install - F102 - Carpet Tile" means F102 is carpet tile)

Use the install lines to identify each material's type. The install line's description after the code tells you the material category. The @location after the dash tells you WHERE it goes, which sometimes changes the classification (e.g. "Wall Tile @Kitchen Backsplash" = backsplash, "Wall Tile @Shower Surrounds" = tub_shower_surround).

VALID MATERIAL TYPES (you must use exactly one of these):
- unit_carpet_no_pattern: Unit carpet without pattern (stretch-in over pad)
- unit_carpet_pattern: Unit carpet with pattern repeat
- unit_lvt: Luxury vinyl plank/tile (LVP/LVT)
- cpt_tile: Carpet tile (modular carpet squares)
- corridor_broadloom: Broadloom carpet for corridors/stairs (direct glue)
- floor_tile: Floor tile (porcelain, ceramic, mosaic floor)
- wall_tile: Wall tile (deco, mosaic, ceramic wall applications)
- backsplash: Kitchen backsplash tile
- tub_shower_surround: Tile for tub/shower surround walls
- rubber_base: Vinyl/rubber base (cove base)
- vct: Vinyl composition tile
- rubber_tile: Rubber floor tile
- rubber_sheet: Rubber sheet flooring
- wood: Hardwood flooring
- tread_riser: Stair tread and riser
- transitions: Transitions, edge trims, Schluter profiles
- waterproofing: Waterproofing membrane

CLASSIFICATION RULES:
- Match material codes (F102, W131, B102, etc.) to their install line counterparts
- "Wall Tile @Kitchen Backsplash" → backsplash (location overrides)
- "Wall Tile @Shower Surrounds" or "@Tub Surrounds" → tub_shower_surround (location overrides)
- "Deco Wall Tile @Dog Wash Tub Surrounds" → wall_tile (it says "Deco Wall Tile", the tub surround is the location name, not the material application)
- Transitions, Schluter profiles, edge trims → transitions
- Vinyl Base, Rubber Base → rubber_base
- Carpet with "Broadloom" and in common areas/stairwells → corridor_broadloom
- Carpet with "Broadloom" in units/bedrooms → unit_carpet_no_pattern (or unit_carpet_pattern if pattern repeat is mentioned)
- Lines about carpet pad, isolation strips, adhesive → these are sundries, classify as "sundry"

Return a JSON array where each element has:
  {"index": <number>, "material_type": "<type>"}

Only return the JSON array, nothing else."""


def _classify_with_ai(material_lines: list[tuple[int, str]],
                       install_lines: list[str]) -> dict[int, str]:
    """
    Use OpenAI to classify material lines by matching with install lines.
    Returns: {index: material_type}
    """
    try:
        from openai import OpenAI
        from quote_parser import _openai_config

        # Use same API key/model as quote parser (set by main.py on startup)
        api_key = _openai_config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return {}

        model = _openai_config.get("model", "gpt-5-mini")

        client = OpenAI(api_key=api_key)

        # Build the user message
        mat_text = "\n".join(
            f"  [{idx}] {desc}" for idx, desc in material_lines
        )
        inst_text = "\n".join(f"  - {desc}" for desc in install_lines)

        user_msg = f"""MATERIAL LINES (classify each one):
{mat_text}

INSTALL LINES (use these to identify material types):
{inst_text}"""

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": AI_CLASSIFICATION_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)

        # Handle both {"classifications": [...]} and bare [...]
        if isinstance(parsed, dict):
            items = parsed.get("classifications", parsed.get("results", []))
        elif isinstance(parsed, list):
            items = parsed
        else:
            return {}

        result = {}
        for item in items:
            idx = item.get("index")
            mtype = item.get("material_type", "unknown")
            if idx is not None and mtype in VALID_MATERIAL_TYPES:
                result[idx] = mtype
            elif idx is not None and mtype == "sundry":
                result[idx] = "sundry"

        return result

    except Exception as e:
        print(f"[rfms_parser] AI classification failed, materials will be 'unknown': {e}")
        return {}


# ── Main parser ──────────────────────────────────────────────────────────────

def parse_rfms(file_path: str) -> dict:
    """
    Parse an RFMS pivot table Excel file.

    Returns:
        {
            "job_info": {project_name, address, city, state, zip, gc_name},
            "materials": [
                {item_code, qty, unit, description, material_type},
                ...
            ]
        }
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)

    # ── Parse Customer sheet ─────────────────────────────────────────────────
    job_info = {}
    customer_sheet = None
    for name in wb.sheetnames:
        if "customer" in name.lower():
            customer_sheet = wb[name]
            break

    if customer_sheet:
        for row in customer_sheet.iter_rows(min_row=1, max_col=2, values_only=True):
            key = _safe_str(row[0]).lower() if row[0] else ""
            val = _safe_str(row[1]) if len(row) > 1 and row[1] else ""
            if "project" in key or "jobname" in key or key == "name":
                job_info["project_name"] = val
            elif "jobaddress" in key or ("address" in key and "project" not in key):
                job_info["address"] = val
            elif "city" in key:
                job_info["city"] = val
            elif "state" in key:
                job_info["state"] = val
            elif "zip" in key:
                job_info["zip"] = val
            elif "contractor" in key or "gc" in key or "builder" in key:
                job_info["gc_name"] = val

    # ── Find By Item sheet ───────────────────────────────────────────────────
    by_item_sheet = None
    for name in wb.sheetnames:
        if "by item" in name.lower():
            by_item_sheet = wb[name]
            break
    if by_item_sheet is None and len(wb.sheetnames) >= 3:
        by_item_sheet = wb[wb.sheetnames[2]]

    if not by_item_sheet:
        wb.close()
        return {"job_info": job_info, "materials": []}

    header_row = _find_header_row(by_item_sheet)

    # ── Read all rows ────────────────────────────────────────────────────────
    all_rows = []
    for row in by_item_sheet.iter_rows(
        min_row=header_row + 1, max_col=3, values_only=True
    ):
        desc_raw = _safe_str(row[0]).rstrip(":")
        qty = _safe_float(row[1]) if len(row) > 1 else 0.0
        if not desc_raw or desc_raw.lower() in ("none", "") or qty == 0:
            continue
        if desc_raw.lower().strip() in ("grand total", "total"):
            continue
        all_rows.append((desc_raw, qty))

    # ── Separate into categories ─────────────────────────────────────────────
    material_lines = []   # (index, description, qty)
    install_lines = []    # descriptions only
    idx = 0

    for desc, qty in all_rows:
        if _is_install(desc):
            install_lines.append(desc)
        elif _is_sundry(desc):
            pass  # skip sundries
        else:
            material_lines.append((idx, desc, qty))
            idx += 1

    # ── Classify with AI ─────────────────────────────────────────────────────
    ai_input = [(i, desc) for i, desc, qty in material_lines]
    ai_results = _classify_with_ai(ai_input, install_lines)

    # ── Build materials list ─────────────────────────────────────────────────
    materials = []
    for i, desc, qty in material_lines:
        # Use AI result — no fallback, stays "unknown" if AI didn't classify
        material_type = ai_results.get(i, "unknown")

        # Skip if AI classified as sundry
        if material_type == "sundry":
            continue

        unit = _extract_unit(desc, material_type)
        item_code = _extract_item_label(desc)

        materials.append({
            "item_code": item_code,
            "qty": qty,
            "unit": unit,
            "description": desc,
            "material_type": material_type,
        })

    wb.close()
    return {"job_info": job_info, "materials": materials}
