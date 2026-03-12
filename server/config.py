"""
SOP Business Rules for Standard Interiors Bid Tool.
All waste factors, sundry coverage rates, freight rates, labor qty rules,
bid templates, and exclusions.
"""

# ─── Waste Factors ────────────────────────────────────────────────────────────
WASTE_FACTORS: dict[str, float] = {
    "unit_carpet_no_pattern": 0.20,
    "unit_carpet_pattern": 0.25,
    "pad": 0.05,
    "unit_lvt": 0.12,
    "cpt_tile": 0.15,
    "corridor_broadloom": 0.22,
    "floor_tile": 0.15,
    "wall_tile": 0.15,
    "backsplash": 0.15,
    "tub_shower_surround": 0.18,
    "rubber_base": 0.05,
    "vct": 0.12,
    "rubber_tile": 0.12,
    "rubber_sheet": 0.20,
    "wood": 0.15,
    "tread_riser": 0.04,
}

# ─── Sundry Rules ─────────────────────────────────────────────────────────────
# Each entry: list of dicts with sundry_name, coverage, unit, notes
SUNDRY_RULES: dict[str, list[dict]] = {
    "unit_carpet_no_pattern": [
        {"sundry_name": "pad", "coverage": 30, "unit": "SY/roll", "waste": 0.05},
        {"sundry_name": "pad_cement", "coverage": 100, "unit": "SY/each"},
        {"sundry_name": "tack_strip", "coverage": 400, "unit": "LF/carton",
         "notes": "estimate 1 LF per SY for perimeter"},
        {"sundry_name": "seam_tape", "coverage": 60, "unit": "LF/roll"},
    ],
    "unit_carpet_pattern": [
        {"sundry_name": "pad", "coverage": 30, "unit": "SY/roll", "waste": 0.05},
        {"sundry_name": "pad_cement", "coverage": 100, "unit": "SY/each"},
        {"sundry_name": "tack_strip", "coverage": 400, "unit": "LF/carton",
         "notes": "estimate 1 LF per SY for perimeter"},
        {"sundry_name": "seam_tape", "coverage": 60, "unit": "LF/roll"},
    ],
    "unit_lvt": [
        {"sundry_name": "adhesive", "coverage": 700, "unit": "SF/pail",
         "notes": "4-gal pail"},
        {"sundry_name": "primer", "coverage": 350, "unit": "SF/pail"},
    ],
    "floor_tile": [
        {"sundry_name": "thinset", "coverage": 40, "unit": "SF/bag"},
        {"sundry_name": "lft_thinset", "coverage": 33, "unit": "SF/bag"},
        {"sundry_name": "grout", "coverage": 100, "unit": "SF/bag",
         "notes": "approximate"},
        {"sundry_name": "caulking", "coverage": None, "unit": "each",
         "notes": "not typically needed for floor tile"},
    ],
    "wall_tile": [
        {"sundry_name": "thinset", "coverage": 40, "unit": "SF/bag"},
        {"sundry_name": "lft_thinset", "coverage": 33, "unit": "SF/bag"},
        {"sundry_name": "grout", "coverage": 100, "unit": "SF/bag",
         "notes": "approximate"},
        {"sundry_name": "caulking", "coverage": None, "unit": "each",
         "notes": "depends on application"},
    ],
    "backsplash": [
        {"sundry_name": "thinset", "coverage": 40, "unit": "SF/bag"},
        {"sundry_name": "lft_thinset", "coverage": 33, "unit": "SF/bag"},
        {"sundry_name": "grout", "coverage": 100, "unit": "SF/bag",
         "notes": "approximate"},
        {"sundry_name": "caulking", "coverage": 4, "unit": "units/tube",
         "notes": "1 tube per 4 units"},
    ],
    "tub_shower_surround": [
        {"sundry_name": "thinset", "coverage": 40, "unit": "SF/bag"},
        {"sundry_name": "lft_thinset", "coverage": 33, "unit": "SF/bag"},
        {"sundry_name": "grout", "coverage": 100, "unit": "SF/bag",
         "notes": "approximate"},
        {"sundry_name": "caulking", "coverage": 2, "unit": "units/tube",
         "notes": "1 tube per 2 units for tubs, 1 per 3 for surrounds"},
    ],
    "rubber_base": [
        {"sundry_name": "adhesive", "coverage": 60, "unit": "LF/tube"},
    ],
}

# ─── Freight Rates ────────────────────────────────────────────────────────────
FREIGHT_RATES: dict[str, float] = {
    "cpt_tile": 1.25,          # per SY
    "broadloom": 0.65,         # per SY
    "lvt_2mm": 0.11,           # per SF
    "lvt_5mm": 0.25,           # per SF
    "non_stocked_adhesive": 5.00,  # per bucket
}

# ─── Labor Quantity Rules ─────────────────────────────────────────────────────
LABOR_QTY_RULES: dict[str, str] = {
    "broadloom": "with_waste",
    "rubber_base": "no_waste",
    "transitions": "from_measure",
    "default": "with_waste",
}

# ─── Bid Description Templates ───────────────────────────────────────────────
BID_TEMPLATES: dict[str, str] = {
    "unit_carpet": (
        "Furnish, deliver and install {product_name}\n"
        "Quote is figured as {product_spec}\n"
        "Installation is figured as Stretch-In over Pad\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "unit_lvt": (
        "Furnish, deliver and install Unit LVT\n"
        "Quote is figured as {product_spec}\n"
        "Installation is figured as Direct Glue over Primed Substrate\n"
        "Sound Mat is excluded at this time\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "floor_tile": (
        "Furnish, deliver and install Floor Tile\n"
        "Quote is figured as {product_spec}\n"
        "Installation is figured as {pattern}\n"
        "Quote includes ANSI 118.7 Grout\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "backsplash": (
        "Furnish, deliver and install Wall Tile\n"
        "Quote is figured as {product_spec}\n"
        "Installation is figured as {pattern}\n"
        "Wall Tile Height is figured per elevations\n"
        "Quote includes ANSI 118.7 Grout\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "tub_shower_surround": (
        "Furnish, deliver and install Wall Tile\n"
        "Quote is figured as {product_spec}\n"
        "Installation is figured as {pattern}\n"
        "Wall Tile Height is figured as {height} AFF\n"
        "Quote includes ANSI 118.7 Grout\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "rubber_base": (
        "Furnish, deliver and install Rubber Base\n"
        "Quote is figured as {product_spec}\n"
        "All Corners have been figured as Job Formed\n"
        "Preformed Corners have been Excluded\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "transitions": (
        "Furnish, deliver and install Transitions\n"
        "Quote is figured as {product_spec}\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "waterproofing": (
        "Furnish, deliver and install Waterproofing\n"
        "Quote is figured as 2 Coats of a Fluid Applied Membrane\n"
        "Quote includes Mesh Fabric for Corners and Seams\n"
        "Installation is direct roll onto substrate\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "cpt_tile": (
        "Furnish, deliver and install Carpet Tile\n"
        "Quote is figured as {product_spec}\n"
        "Installation is figured as Direct Glue over Primed Substrate\n"
        "Installed QTY {installed_qty} {unit}"
    ),
    "corridor_broadloom": (
        "Furnish, deliver and install Broadloom\n"
        "Quote is figured as {product_spec}\n"
        "Installation is figured as Direct Glue over Primed Substrate\n"
        "Installed QTY {installed_qty} {unit}"
    ),
}

# ─── Exclusions Template ─────────────────────────────────────────────────────
EXCLUSIONS_TEMPLATE: list[str] = [
    "Offsite Mockup is excluded at this time",
    "Exterior installs are excluded at this time",
    "Epoxy grout is excluded at this time",
    "Grout Sealer is excluded at this time",
    "Sound mat is excluded at this time",
    "Floor Protection is excluded at this time",
]
