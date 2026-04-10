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
    "sound_mat": 0.05,
    "rubber_sheet": 0.20,
    "wood": 0.15,
    "tread_riser": 0.04,
}

# ─── Sundry Rules ─────────────────────────────────────────────────────────────
# Each entry: list of dicts with sundry_name, coverage, unit, unit_price, notes
SUNDRY_RULES: dict[str, list[dict]] = {
    "unit_carpet_no_pattern": [
        {"sundry_name": "pad", "coverage": 30, "unit": "SY/roll", "waste": 0.05, "unit_price": 41.40,
         "notes": "$1.38/SY x 30 SY/roll"},
        {"sundry_name": "pad_cement", "coverage": 100, "unit": "SY/each", "unit_price": 28.00},
        {"sundry_name": "tack_strip", "coverage": 400, "unit": "LF/carton", "unit_price": 36.990,
         "qty_source": "tack_strip_lf", "notes": "RFMS measured LF / 400 LF per carton"},
        {"sundry_name": "seam_tape", "coverage": 60, "unit": "LF/roll", "unit_price": 9.09,
         "qty_source": "seam_tape_lf", "notes": "RFMS measured LF / 60 LF per roll"},
    ],
    "unit_carpet_pattern": [
        {"sundry_name": "pad", "coverage": 30, "unit": "SY/roll", "waste": 0.05, "unit_price": 41.40,
         "notes": "$1.38/SY x 30 SY/roll"},
        {"sundry_name": "pad_cement", "coverage": 100, "unit": "SY/each", "unit_price": 28.00},
        {"sundry_name": "tack_strip", "coverage": 400, "unit": "LF/carton", "unit_price": 36.990,
         "qty_source": "tack_strip_lf", "notes": "RFMS measured LF / 400 LF per carton"},
        {"sundry_name": "seam_tape", "coverage": 60, "unit": "LF/roll", "unit_price": 9.09,
         "qty_source": "seam_tape_lf", "notes": "RFMS measured LF / 60 LF per roll"},
    ],
    "unit_lvt": [
        {"sundry_name": "adhesive", "coverage": 700, "unit": "SF/pail", "unit_price": 73.00,
         "notes": "Taylor Dynamics 4-gal pail"},
        {"sundry_name": "primer", "coverage": 350, "unit": "SF/bucket", "unit_price": 17.00,
         "notes": "Taylor 2025 1"},
    ],
    "cpt_tile": [
        {"sundry_name": "adhesive", "coverage": 700, "unit": "SF/pail", "unit_price": 73.00,
         "notes": "Taylor Dynamics 4-gal pail"},
        {"sundry_name": "primer", "coverage": 350, "unit": "SF/bucket", "unit_price": 17.00,
         "notes": "Taylor 2025 1"},
    ],
    "corridor_broadloom": [
        {"sundry_name": "adhesive", "coverage": 80, "unit": "SY/pail", "unit_price": 95.00,
         "freight_per_unit": 5.00, "notes": "direct glue adhesive"},
        {"sundry_name": "primer", "coverage": 100, "unit": "SY/pail", "unit_price": 65.00},
        {"sundry_name": "seam_tape", "coverage": 60, "unit": "LF/roll", "unit_price": 9.09},
    ],
    "floor_tile": [
        {"sundry_name": "thinset", "coverage": 40, "unit": "SF/bag", "unit_price": 15.95,
         "white_price": 17.95, "skip_if_lft": True, "notes": "grey $15.95, white $17.95 for mosaic/backsplash. Skipped for large format tiles."},
        {"sundry_name": "lft_thinset", "coverage": 30, "unit": "SF/bag", "unit_price": 16.85,
         "min_tile_size": 15, "notes": "only for tiles >15x15"},
        {"sundry_name": "grout", "coverage": 100, "unit": "SF/bag", "unit_price": 32.00,
         "qty_basis": "grout_formula", "joint_width": 0.1875,
         "notes": "Prism 17lb bag. Coverage from tile dims + 3/16 joint. Formula: 2.73*(W*L)/((W+L)*J*T)"},
    ],
    "wall_tile": [
        {"sundry_name": "thinset", "coverage": 40, "unit": "SF/bag", "unit_price": 15.95,
         "white_price": 17.95, "skip_if_lft": True, "notes": "grey $15.95, white $17.95 for mosaic/backsplash. Skipped for large format tiles."},
        {"sundry_name": "lft_thinset", "coverage": 30, "unit": "SF/bag", "unit_price": 16.85,
         "min_tile_size": 15, "notes": "only for tiles >15x15"},
        {"sundry_name": "grout", "coverage": 100, "unit": "SF/bag", "unit_price": 32.00,
         "qty_basis": "grout_formula", "joint_width": 0.1875,
         "notes": "Prism 17lb bag. Coverage from tile dims + 3/16 joint. Formula: 2.73*(W*L)/((W+L)*J*T)"},
    ],
    "backsplash": [
        {"sundry_name": "thinset", "coverage": 40, "unit": "SF/bag", "unit_price": 17.95,
         "skip_if_lft": True, "notes": "backsplash always uses white thinset. Skipped for large format tiles."},
        {"sundry_name": "lft_thinset", "coverage": 30, "unit": "SF/bag", "unit_price": 16.85,
         "min_tile_size": 15, "notes": "only for tiles >15x15"},
        {"sundry_name": "grout", "coverage": 100, "unit": "SF/bag", "unit_price": 32.00,
         "qty_basis": "grout_formula", "joint_width": 0.1875,
         "notes": "Prism 17lb bag. Coverage from tile dims + 3/16 joint. Formula: 2.73*(W*L)/((W+L)*J*T)"},
        {"sundry_name": "caulking", "coverage": 2, "unit": "units/tube", "unit_price": 13.85,
         "qty_basis": "unit_count", "notes": "1 tube per 2 unit backsplashes"},
    ],
    "tub_shower_surround": [
        {"sundry_name": "thinset", "coverage": 40, "unit": "SF/bag", "unit_price": 15.95,
         "white_price": 17.95, "skip_if_lft": True, "notes": "grey $15.95, white $17.95 for mosaic. Skipped for large format tiles."},
        {"sundry_name": "lft_thinset", "coverage": 30, "unit": "SF/bag", "unit_price": 16.85,
         "min_tile_size": 15, "notes": "only for tiles >15x15"},
        {"sundry_name": "grout", "coverage": 100, "unit": "SF/bag", "unit_price": 32.00,
         "qty_basis": "grout_formula", "joint_width": 0.1875,
         "notes": "Prism 17lb bag. Coverage from tile dims + 3/16 joint. Formula: 2.73*(W*L)/((W+L)*J*T)"},
        {"sundry_name": "caulking", "coverage": 2, "unit": "units/tube", "unit_price": 13.85,
         "qty_basis": "tub_shower_total", "notes": "1 tube per 2 tubs/showers"},
        {"sundry_name": "schluter_jolly", "coverage": 0.5, "unit": "EA/stick", "unit_price": 9.78,
         "qty_basis": "tub_shower_total",
         "notes": "Schluter Jolly J 100 AE, 8' stick, $9.78/stick. 2 sticks per tub/shower (1 per side). Qty = tub_shower_count * 2"},
    ],
    "rubber_base": [
        {"sundry_name": "adhesive", "coverage": 60, "unit": "LF/tube", "unit_price": 12.00},
    ],
    "rubber_tile": [
        {"sundry_name": "adhesive", "coverage": 700, "unit": "SF/pail", "unit_price": 95.00,
         "freight_per_unit": 5.00},
        {"sundry_name": "primer", "coverage": 350, "unit": "SF/pail", "unit_price": 65.00},
    ],
    "sound_mat": [
        {"sundry_name": "adhesive", "coverage": 700, "unit": "SF/pail", "unit_price": 73.00,
         "notes": "Taylor Dynamics 4-gal pail (stocked, no freight)"},
        {"sundry_name": "primer", "coverage": 350, "unit": "SF/bucket", "unit_price": 17.00,
         "notes": "Taylor 2025 1"},
    ],
    "rubber_sheet": [
        {"sundry_name": "adhesive", "coverage": 700, "unit": "SF/pail", "unit_price": 95.00,
         "freight_per_unit": 5.00},
        {"sundry_name": "primer", "coverage": 350, "unit": "SF/pail", "unit_price": 65.00},
        {"sundry_name": "weld_rod", "coverage": 500, "unit": "LF/roll", "unit_price": 45.00,
         "qty_source": "weld_rod_lf"},
    ],
    "transitions": [
        {"sundry_name": "silver_pin_metal", "coverage": 12, "unit": "LF/stick", "unit_price": 7.94,
         "notes": "Silver pin metal transition strip, 12' stick. UNIT stretch-in CPT to LVT only, NOT common area CPT."},
    ],
    "vct": [
        {"sundry_name": "adhesive", "coverage": 700, "unit": "SF/pail", "unit_price": 85.00,
         "freight_per_unit": 5.00},
        {"sundry_name": "primer", "coverage": 350, "unit": "SF/pail", "unit_price": 65.00},
    ],
    "wood": [
        {"sundry_name": "adhesive", "coverage": 700, "unit": "SF/pail", "unit_price": 110.00,
         "freight_per_unit": 5.00},
        {"sundry_name": "moisture_barrier", "coverage": 500, "unit": "SF/roll", "unit_price": 75.00},
    ],
    "waterproofing": [
        {"sundry_name": "mesh_fabric", "coverage": 300, "unit": "SF/roll", "unit_price": 42.00,
         "notes": "Mesh tape for corners and seams. RedGard pails are the material, not a sundry."},
    ],
    "tread_riser": [
        {"sundry_name": "adhesive", "coverage": 50, "unit": "LF/tube", "unit_price": 12.00},
        {"sundry_name": "nosing", "coverage": 12, "unit": "LF/piece", "unit_price": 35.00},
    ],
}

# ─── Stair Sundry Kits ──────────────────────────────────────────────────────
# Per-stair ratios based on commercial stair (4' × 1' × 8" tall)
STAIR_SUNDRY_KITS: dict[str, list[dict]] = {
    "stretched": [
        {"sundry_name": "Stair Pad (6lb 3/8\")", "ratio_per_stair": 0.74, "unit": "SY", "unit_price": 1.38, "roll_size": 30},
        {"sundry_name": "Stair Tack Strip", "ratio_per_stair": 6.0, "unit": "LF", "unit_price": 0.055,
         "notes": "$22/carton ÷ 400 LF/carton = $0.055/LF"},
        {"sundry_name": "Stair Seam Sealer", "ratio_per_stair": 5.307, "unit": "LF", "unit_price": 0.1515,
         "notes": "$9.09/roll ÷ 60 LF/roll = $0.1515/LF"},
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
# Labor is paid on NET installed area for everything EXCEPT unit stretch-in
# broadloom (unit_carpet_*), where installers are paid by the roll/total material.
LABOR_QTY_RULES: dict[str, str] = {
    "unit_carpet_no_pattern": "with_waste",
    "unit_carpet_pattern": "with_waste",
    "corridor_broadloom": "no_waste",
    "transitions": "from_measure",
    "default": "no_waste",
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

# ─── Derived Bundle Rules ────────────────────────────────────────────────────
# Virtual bundles auto-generated from existing material quantities.
DERIVED_BUNDLE_RULES: dict[str, dict] = {
    "waterproofing": {
        "source_type": "tub_shower_surround",
        "material_name": "Custom RedGard Fluid Applied Membrane",
        "coverage_sf": 275,
        "pail_cost": 156.00,
        "mesh_coverage_sf": 300,
        "mesh_cost": 42.00,
        "labor_rate_sf": 0.54,
        "labor_description": "Waterproofing Roll On",
        "notes": "Roll-on application, NOT Kerdi. No separate membrane sundry — RedGard pails ARE the membrane.",
    },
    "crack_isolation": {
        "source_type": "floor_tile",
        "area_type": "common",
        "material_name": "Custom RedGard Crack Isolation Membrane",
        "coverage_sf": 500,
        "pail_cost": 156.00,
        "labor_rate_sf": 0.28,
    },
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
