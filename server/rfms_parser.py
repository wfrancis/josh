"""
Parse RFMS pivot table Excel files (.xlsx).
Reads the "By Item" sheet for material summaries and "Customer" sheet for job info.
"""

import re
from typing import Optional
import openpyxl


# Map item code prefixes to material types
PREFIX_MAP: dict[str, str] = {
    "CPTP": "unit_carpet_pattern",
    "CPT": "unit_carpet_no_pattern",
    "LVP": "unit_lvt",
    "LVT": "unit_lvt",
    "CT": "cpt_tile",
    "BL": "corridor_broadloom",
    "FT": "floor_tile",
    "WT": "wall_tile",
    "BS": "backsplash",
    "TS": "tub_shower_surround",
    "RB": "rubber_base",
    "BR": "rubber_base",
    "VCT": "vct",
    "RT": "rubber_tile",
    "RS": "rubber_sheet",
    "RF": "rubber_tile",
    "WD": "wood",
    "TR": "tread_riser",
    "SCH": "transitions",
    "WP": "waterproofing",
    "T": "floor_tile",
}


def _classify_item_code(item_code: str) -> str:
    """Determine material_type from an item code like CPT-1, LVT-2, BR-1."""
    if not item_code:
        return "unknown"
    code_upper = item_code.strip().upper()
    # Try longest prefixes first to match CPTP before CPT
    for prefix in sorted(PREFIX_MAP.keys(), key=len, reverse=True):
        if code_upper.startswith(prefix):
            return PREFIX_MAP[prefix]
    return "unknown"


def _safe_float(val) -> float:
    """Convert a cell value to float, returning 0.0 on failure."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_str(val) -> str:
    """Convert a cell value to string."""
    if val is None:
        return ""
    return str(val).strip()


def parse_rfms(file_path: str) -> dict:
    """
    Parse an RFMS pivot table Excel file.

    Returns:
        {
            "job_info": {project_name, address, city, state, zip, gc_name, ...},
            "materials": [
                {item_code, qty, unit, description, material_type},
                ...
            ]
        }
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)

    # ── Parse Customer sheet (Sheet 5 or named "Customer") ────────────────
    job_info = {}
    customer_sheet = None
    for name in wb.sheetnames:
        if "customer" in name.lower():
            customer_sheet = wb[name]
            break
    if customer_sheet is None and len(wb.sheetnames) >= 5:
        customer_sheet = wb[wb.sheetnames[4]]  # Sheet 5 (0-indexed: 4)

    if customer_sheet:
        for row in customer_sheet.iter_rows(min_row=1, max_col=2, values_only=True):
            key = _safe_str(row[0]).lower() if row[0] else ""
            val = _safe_str(row[1]) if len(row) > 1 else ""
            if "project" in key or "name" in key:
                job_info["project_name"] = val
            elif "address" in key:
                job_info["address"] = val
            elif "city" in key:
                job_info["city"] = val
            elif "state" in key:
                job_info["state"] = val
            elif "zip" in key:
                job_info["zip"] = val
            elif "contractor" in key or "gc" in key or "builder" in key:
                job_info["gc_name"] = val

    if "project_name" not in job_info:
        job_info["project_name"] = "Untitled Project"

    # ── Parse By Item sheet (Sheet 3 or named "By Item") ──────────────────
    materials = []
    by_item_sheet = None
    for name in wb.sheetnames:
        if "by item" in name.lower() or "item" in name.lower():
            by_item_sheet = wb[name]
            break
    if by_item_sheet is None and len(wb.sheetnames) >= 3:
        by_item_sheet = wb[wb.sheetnames[2]]  # Sheet 3 (0-indexed: 2)
    if by_item_sheet is None and len(wb.sheetnames) >= 1:
        by_item_sheet = wb[wb.sheetnames[0]]  # Fallback: first sheet

    if by_item_sheet:
        # Auto-detect column layout from header row
        col_map = {"item_code": 0, "qty": 1, "description": 2, "unit": 3}
        header_row = next(by_item_sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if header_row:
            for idx, cell in enumerate(header_row):
                h = _safe_str(cell).lower()
                if "item" in h and ("code" in h or "id" in h or h == "item"):
                    col_map["item_code"] = idx
                elif "qty" in h or "quantity" in h or "installed" in h:
                    col_map["qty"] = idx
                elif "desc" in h or "product" in h or "style" in h or "name" in h:
                    col_map["description"] = idx
                elif h in ("unit", "uom", "units"):
                    col_map["unit"] = idx

        max_col = max(col_map.values()) + 1
        for row in by_item_sheet.iter_rows(min_row=2, max_col=max_col, values_only=True):
            item_code = _safe_str(row[col_map["item_code"]]) if len(row) > col_map["item_code"] and row[col_map["item_code"]] else ""
            if not item_code or item_code.lower() in ("total", "grand total", ""):
                continue

            qty = _safe_float(row[col_map["qty"]]) if len(row) > col_map["qty"] else 0.0
            description = _safe_str(row[col_map["description"]]) if len(row) > col_map["description"] else ""
            unit = _safe_str(row[col_map["unit"]]) if len(row) > col_map["unit"] else ""

            # If unit wasn't in column D, try to extract from description
            if not unit:
                if "sy" in description.lower():
                    unit = "SY"
                elif "sf" in description.lower():
                    unit = "SF"
                elif "lf" in description.lower():
                    unit = "LF"
                elif "ea" in description.lower():
                    unit = "EA"

            material_type = _classify_item_code(item_code)

            # Refine tile classification based on description
            if material_type == "floor_tile":
                desc_lower = item_code.lower() + " " + description.lower()
                if "wall tile" in desc_lower:
                    material_type = "wall_tile"
                elif "backsplash" in desc_lower:
                    material_type = "backsplash"
                elif "surround" in desc_lower or "tub" in desc_lower or "shower" in desc_lower:
                    material_type = "tub_shower_surround"

            # Skip sundry/labor lines that are already in the pivot table
            # (these start with "Install", "Adhesive", "Thin Set", etc.)
            item_lower = item_code.lower()
            if any(item_lower.startswith(skip) for skip in [
                "install", "adhesive", "thin set", "thinset", "crack iso",
                "carpet pad", "tack strip", "seam seal", "none"
            ]):
                continue

            materials.append({
                "item_code": item_code,
                "qty": qty,
                "unit": unit,
                "description": description,
                "material_type": material_type,
            })

    wb.close()
    return {"job_info": job_info, "materials": materials}
