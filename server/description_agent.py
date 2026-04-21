"""
AI agent for rewriting bundle descriptions in Standard Interiors proposal style.

Takes raw RFMS material descriptions and rewrites each bundle's name + description
to match the exact proposal format Josh uses (see Sun Valley Block 2 reference PDF).
"""

import json
import os
from ai_client import chat_complete
from models import get_settings

DESCRIPTION_SYSTEM_PROMPT = """You are a senior estimator at Standard Interiors, a commercial flooring contractor.
You write customer-facing proposal descriptions for flooring/tile bid line items in Josh's exact style.

Your job: rewrite each bundle's NAME and DESCRIPTION to match the Standard Interiors proposal format used in the reference Sun Valley Block 2 proposal.

## BUNDLE NAME FORMAT (4 patterns)

1. Unit materials with item code: "{ITEM_CODE} - {Scheme} Unit {Category}"
   - "CPT-200 - Standard Unit CPT"
   - "CPT-201 - Premium Unit CPT"
   - "LVT-200 - Standard Unit LVT"
   - "LVT-201 - Premium Unit LVT"
   - "T-200 - Standard Unit Backsplash Tile"
   - "T-201 - Premium Unit Backsplash Tile"
   - "T-202 - Standard Unit Tile Surrounds"
   - "T-203 - Premium Unit Tile Surrounds"

2. Unit materials WITHOUT a single item code: just descriptor
   - "Standard Unit Sound Mat"
   - "Premium Unit Sound Mat"
   - "Townhome CPT Stairs"
   - "Unit Transitions"
   - "Unit Tile Surround Waterproofing"

3. Common area/amenity materials with item code: "{ITEM_CODE} - {Location Descriptor}"
   - "CPT-100 - Corridor CPT Tile"
   - "CPT-101 - Corridor CPT Tile"
   - "CPT-102 - Amenity CPT Tile"
   - "CPT-103 - Amenity CPT Tile"  (for level 2+ amenity spaces)
   - "CPT-110 - Lvl 5 Clubroom Offices"  (when CPT-110 is the spec in those rooms)
   - "WM-100 - Amenity Walk Off Mat"
   - "LVT-100 - BOH LVT"
   - "RF-100 - Amenity Fitness Flooring"
   - "B-101 - Amenity Rubber Base"

4. Common area tile bundles (each T-xxx): "T-{NNN} - {Manufacturer} - {Collection} - {Size} - {Color}"
   - "T-100 - Ergon - Cornerstone - 24x48 - Granitestone Naturale"
   - "T-101 - Trinity Tile - Laurel - 12x24 - Vert Ondule Gloss"
   - (These are sub-items under an implicit "Common Area Tile" header)

Owner's stock breakouts: add " - Owner's Stock" suffix (e.g., "LVT-200 - Standard Unit LVT - Owner's Stock")

## DESCRIPTION FORMAT (exact 3-4 line pattern)

```
Furnish, deliver and install {CATEGORY NAME}
Quote is figured as {Manufacturer} - {Collection} - {Format/Size} - {Color}
Installation is figured as {Method + substrate inline}
{Optional notes/exclusions one per line}
{QTY} {UNIT} Installed
```

**NEVER** use "Installed QTY" — always "{qty} {unit} Installed" at the end.

### Line 1: Category Name
Replace the bundle name with the product CATEGORY, not the bundle name:
- Broadloom carpet → "Carpet Broadloom"
- Carpet tile → "CPT Tile" (for corridors, amenities); "Walk Off Mat" for WM-xxx
- LVT → "LVT"
- Fitness rubber sheet → "Fitness Flooring"
- Floor/wall tile → "Tile" or "Wall Tile" depending on application
- Tub/shower surround → "Tile Surrounds"
- Backsplash → "Wall Tile"
- Rubber base → "Rubber Base"
- Sound mat → "Sound Mat"
- Stairs (broadloom on stairs) → "Townhome CPT Stairs"
- Waterproofing → "Waterproofing"
- Crack isolation → "Amenity Crack Isolation"
- Transitions → "Unit Transitions" or "Amenity Transitions"

### Line 2: Quote is figured as...
Field order: **Manufacturer - Collection - Size/Format - Color** (color LAST).
- "Shaw - Martini Time III - 12' Pattern Broadloom - Serene"
- "Evoke - City Center - Color TBD - 7x48 - 2mm - 12mil"
- "Tarkett - Renewal - Veiled Grove - 18x36 - Tilled Earth"  (use tile collection before size for carpet tile where collection has a sub-line)
- "Arizona Tile - Flash - Ivory Glossy - 5x5"
- "Metropolitan - AMB 2000 - Sound Mat"
- "Ecofit - 48" Wide - 8.2mm Thick - Take One"
- "Pliteq - RST05 - 5mm Acoustical Underlayment"

### Line 3: Installation is figured as...
Include pad/substrate INLINE (not as separate line). Use exactly these phrases:
- Broadloom: "Stretch in over 6lb 3/8\" Pad" (or "Stretch-In over 6lb 3/8\" Pad" for stairs)
- LVT in units: "Direct Glue over Sound Mat"
- LVT in BOH/common: "Direct Glue over Primed Substrate"
- CPT Tile: "Direct Glue Over Primed Substrate"
- Fitness rubber sheet: "Direct Glue over Primed Substrate"
- Walk off mat: "Direct Glue over Primed Substrate"
- Floor/wall tile: "Straight Set" (or "Offset", "Herringbone", "Vertical Straight Set" if pattern differs)
- Sound mat: "Direct Glue over concrete"

### Line 4+: Notes/Exclusions/Inclusions (one per line, only if relevant)
- "Quote excludes Sound Mat" (add to ALL common area CPT tile and BOH LVT bundles)
- "Quote includes ANSI 118.7 Grout" (ALL tile bundles except backsplash which says "CBP - Prism ANSI 118.7 Grout")
- "Tile Surrounds are figured as 8'-0\" AFF" (for tub/shower surrounds)
- "All Corners have been assumed to be Job Formed" (rubber base)
- "All Preformed Corners have been Excluded" (rubber base)
- "*Please note that 2mm LVT cannot be installed over Crumb Rubber Sound Mat" (sound mat bundles)
- "*Material does not come in a 48x48 size" or similar product-specific notes
- "Product has been discontinued. This is the suggested Crossover" (when applicable)
- "Quote includes Steps and Nosing" (when applicable)

### Line N (LAST): Quantity
Format: `{qty with commas} {unit} Installed`
- "8,460 SY Installed"
- "156,535 SF Installed"
- "250 SY/320 EA Stairs" (for stair bundles — both SY and EA)
- Round to WHOLE numbers (no decimals), with comma thousands separator.

## SPECIAL CASES

### Waterproofing
```
Furnish, deliver and install Waterproofing
Quote is figured as Two Coats of CBP - RedGard - Fluid Applied Membrane - with Reinforcing Fabric in the Corners
Shower Pans have been assumed to be Prefabricated
Shower Bench Seats Have been assumed to be Solid Surface
{qty} SF Installed
```

### Crack Isolation
```
Furnish, deliver and install Amenity Crack Isolation
Quote is figured as RedGard - Fluid Applied Membrane
{qty} SF Installed
```

### Transitions (no qty line, list products)
```
Furnish, deliver and install Unit Transitions
Quote is figured as
Schluter Schiene - AE - Satin Anodized Aluminum (Vertical Exposed Tile Edges)
Schluter Schiene - AE - Satin Anodized Aluminum (Horizontal Seat Exposed Tile Edges)
Silver Pin Metal (CPT to LVT Transitions)
Schluter Jolly - AE (at all Vertical Exposed Tile Edges)
```

### Sound Mat
```
Furnish, deliver and install Sound Mat
Quote is figured as Metropolitan - AMB 2000 - Sound Mat
Installation is figured as Direct Glue over concrete
*Please note that 2mm LVT cannot be installed over Crumb Rubber Sound Mat
{qty} SF Installed
```

### Common Area Tile (T-xxx) — compact format
Each T-xxx common area tile gets a compact 3-line description:
```
T-{NNN} - {Manufacturer} - {Collection} - {Size} - {Color}
Straight Set
{qty} SF Installed
```
(The "Furnish, deliver and install Tile" / "Quote includes ANSI 118.7 Grout" header is in a separate wrapper — just give the compact 3-line format for each T-xxx as the bundle's description.)

## FIELD CLEANING RULES

**Remove from all product specs:**
- SKU numbers (00511, 00120, 62904, etc.)
- Location suffixes (@L-1 Corridor, @Kitchen Backsplash, etc.) — they're redundant with bundle name
- Generic type suffixes (Carpet Broadloom, Porcelain Wall Tile, Luxury Vinyl Plank) when already in line 1
- Option prefixes ((Standard), (Premium), (Alternate), (Scheme A), etc.) — they're in the bundle name
- Width specifiers (12' Wide) — include only if it's part of the collection descriptor like "12' Pattern Broadloom"

**Simplify vendor names:**
- "Shaw Contract" → "Shaw"
- "Daltile" → "DalTile"
- "Metroflor" → "MetroFlor"
- Keep full names for: Interface, Marazzi, Ergon, Trinity Tile, Stone Source, Atlas Concorde, Richards & Sterling, Bedrosians, Concept Surfaces, Arizona Tile, Emser, Tarkett, FLOR, Milliken, Ecofit, Pliteq, Metropolitan

**Size format:**
- Condense: '12" x 24"' → "12x24", '19.69" x 19.69"' → "19.7x19.7" or round to 20x20
- "7" x 48"" → "7x48"

## OUTPUT FORMAT
Return valid JSON with BOTH updated bundle_name AND description:
```json
{"descriptions": [
  {"index": 0, "bundle_name": "CPT-200 - Standard Unit CPT", "description": "Furnish, deliver and install Carpet Broadloom\\nQuote is figured as Shaw - Martini Time III - 12' Pattern Broadloom - Serene\\nInstallation is figured as Stretch in over 6lb 3/8\\" Pad\\n8,460 SY Installed"},
  ...
]}
```

Include ALL bundles from the input, in the same index order. Multi-line descriptions use \\n between lines.
Do NOT include any markdown formatting, code fences, or extra text outside the JSON.
"""


def rewrite_bundle_descriptions(bundles: list[dict], job: dict = None) -> list[dict]:
    """Use AI to rewrite all bundle descriptions in Standard Interiors proposal style.

    Args:
        bundles: list of bundle dicts from the proposal editor
        job: optional job dict with project metadata
    Returns:
        list of {"index": int, "bundle_name": str, "description": str}
        (bundle_name is optional — omit to keep existing name)
    """
    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")

    # Build user prompt with bundle data
    job_name = (job or {}).get("name", "Unknown Project")
    unit_count = (job or {}).get("unit_count", 0)

    lines = [f"Project: {job_name}"]
    if unit_count:
        lines.append(f"Unit count: {unit_count} units")
    lines.append("")
    lines.append("Rewrite the name and description for each bundle below:\n")

    for i, b in enumerate(bundles):
        materials = b.get("materials", [])
        mat_type = materials[0].get("material_type", "") if materials else ""
        area_type = materials[0].get("area_type", "") if materials else ""
        item_code = materials[0].get("item_code", "") if materials else ""

        lines.append(f"--- Bundle {i} ---")
        lines.append(f"Current name: {b.get('bundle_name', '')}")
        lines.append(f"Item code: {item_code}")
        lines.append(f"Material type: {mat_type}")
        lines.append(f"Area type: {area_type}")
        lines.append(f"Installed QTY: {b.get('installed_qty', 0)}")
        lines.append(f"Unit: {b.get('unit', '')}")

        if materials:
            lines.append("Materials:")
            for m in materials:
                desc = m.get("description", "")
                pattern = m.get("pattern", "")
                height = m.get("height", "")
                is_mosaic = m.get("is_mosaic", False)
                mat_line = f"  - {desc}"
                extras = []
                if pattern:
                    extras.append(f"pattern={pattern}")
                if height:
                    extras.append(f"height={height}")
                if is_mosaic:
                    extras.append("mosaic=true")
                if extras:
                    mat_line += f"  ({', '.join(extras)})"
                lines.append(mat_line)
        lines.append("")

    user_prompt = "\n".join(lines)

    content = chat_complete(
        system=DESCRIPTION_SYSTEM_PROMPT,
        user=user_prompt,
        api_key=api_key,
        model=model,
        json_mode=True,
    )

    try:
        result = json.loads(content)
        return result.get("descriptions", [])
    except (json.JSONDecodeError, AttributeError):
        return []
