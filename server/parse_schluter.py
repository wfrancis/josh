"""
Schluter Price Book PDF Parser
Extracts product data from the Schluter price list PDF and outputs JSON
for import into the SI Bid Tool database.

Parses:
- Transition profiles (pages 33-43): SCHIENE, RENO-T, RENO-TK, RENO-V, RENO-RAMP, RENO-U
- JOLLY (pages 45-49)
- DITRA/KERDI waterproofing (pages 130-135)
- KERDI-BOARD building panels (pages 119-128)
"""

import pdfplumber
import json
import re
import os
from collections import defaultdict

PDF_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "schluter-price-list-usa.pdf")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "schluter_prices.json")

DISCOUNT_MULTIPLIER = 0.45  # Net price = list_price * 0.45


def parse_profile_pages(pdf):
    """Parse transition/edge profile pages and JOLLY pages.

    These pages share a common format:
    - Product line header: "Schluter-SCHIENE", "Schluter-RENO-TK", etc.
    - Material header rows with finish names
    - Length specification (2.5 m or 3.05 m)
    - Size/item/price rows: "8 - 5/16 E 80 39.68" or multi-column variants
    """
    products = []

    # Pages to parse (0-indexed)
    # Transition profiles: 34-42, JOLLY: 44-48
    page_ranges = list(range(34, 43)) + list(range(44, 49))

    for page_idx in page_ranges:
        page = pdf.pages[page_idx]
        text = page.extract_text()
        if not text:
            continue

        lines = text.split('\n')
        current_product_line = None
        current_length = "2.5 m - 8' 2-1/2\""
        current_materials = []  # List of (material_name, item_prefix_or_none)
        in_accessory_section = False

        for i, line in enumerate(lines):
            line = line.strip()

            # Detect product line headers
            product_match = re.search(r'Schluter.*?-(SCHIENE-RADIUS|SCHIENE|DECO|RENO-TK|RENO-T|RENO-V|RENO-RAMP-K|RENO-RAMP|RENO-U|RENO-VT|RENO-VB|JOLLY-P|JOLLY)', line)
            if product_match:
                candidate = product_match.group(1)
                # Only update if this looks like a section header (not a reference)
                # Check it's not just a "see page" reference
                if 'see page' not in line.lower() and 'page ' not in line.lower():
                    current_product_line = candidate
                    in_accessory_section = False
                    continue

            # Detect length
            if '3.05 m' in line or "10'" in line:
                if '3.05' in line:
                    current_length = "3.05 m - 10'"
            elif '2.5 m' in line or "8' 2-1/2" in line:
                current_length = "2.5 m - 8' 2-1/2\""

            # Detect accessory sections
            if re.search(r'Accessory|Outside corner|Inside corner|End cap|Connector', line, re.IGNORECASE):
                if 'Item No' in line or '$ /' in line:
                    in_accessory_section = True

            if not current_product_line:
                continue

            # Parse price lines - look for lines with dollar amounts (decimal numbers)
            # Profile lines: "8 - 5/16 E 80 39.68" or "8 - 5/16 E 80 39.68 E 80 EB 49.09 M 80 40.13"
            # Accessory lines: "Inside corner, 90 C/I90/AHK1S/DP 35.00"

            # Multi-column profile line pattern:
            # size_mm - size_in ITEM PRICE [ITEM PRICE ...]
            # e.g., "8 - 5/16 E 80 39.68 E 80 EB 49.09 M 80 40.13 A 80 11.12 AE 80 16.42"

            # First check if line has a size prefix pattern
            size_match = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:-\d+)?/\d+(?:")?)\s+(.+)', line)
            if size_match:
                size_mm = size_match.group(1)
                size_inches = size_match.group(2).rstrip('"')
                remainder = size_match.group(3)

                # Extract all item_no + price pairs from the remainder
                # Patterns: "E 80 39.68", "E 80 EB 49.09", "A 80 ACG 19.32", "AETK 100 23.27"
                # Also: "A 60 + color* 34.77", "color* + 45 6.52"
                # General: sequence of non-numeric tokens = item_no, then a price

                # Find all prices (numbers with exactly 2 decimal places)
                price_positions = [(m.start(), m.end(), m.group())
                                   for m in re.finditer(r'\b(\d+(?:,\d{3})*\.\d{2})\b', remainder)]

                if price_positions:
                    prev_end = 0
                    for idx, (start, end, price_str) in enumerate(price_positions):
                        # Item number is the text between previous price end and this price
                        item_text = remainder[prev_end:start].strip()
                        prev_end = end

                        # Clean up item text - remove stray dashes that mean "not available"
                        if not item_text or item_text == '-' or item_text == '- -':
                            continue

                        # Remove leading/trailing dashes and clean
                        # Handle multi-column empty cells: "- -" or "- - -"
                        item_text = re.sub(r'^[\s-]+', '', item_text)
                        item_text = re.sub(r'[\s-]+$', '', item_text)
                        item_text = re.sub(r'\s*-\s*-\s*', ' ', item_text)  # collapse "- -" in middle
                        item_text = item_text.strip()

                        if not item_text or item_text == '-' or len(item_text) < 2:
                            continue

                        price = float(price_str.replace(',', ''))

                        # Determine material from item number prefix
                        material = guess_material(item_text, current_product_line)

                        # Determine unit
                        unit = "length"
                        if in_accessory_section:
                            unit = "ea"

                        products.append({
                            "product_line": current_product_line,
                            "item_no": item_text,
                            "material_finish": material,
                            "size_mm": size_mm,
                            "size_inches": size_inches,
                            "list_price": price,
                            "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                            "length": current_length,
                            "unit": unit,
                        })
                continue

            # Accessory lines (no size prefix): "Inside corner, 90 C/I90/AHK1S/DP 35.00"
            # Or: "V / J PP4 4 2.94" (connector)
            # Or corner items: "EV / J 60 EB 23.30"
            if in_accessory_section or re.search(r'corner|end cap|connector', line, re.IGNORECASE):
                # Look for item + price at end
                acc_match = re.search(r'([\w/\s]+?)\s+(\d+\.\d{2})\s*$', line)
                if acc_match:
                    item_text = acc_match.group(1).strip()
                    price = float(acc_match.group(2))

                    # Try to extract a cleaner item number
                    # "Inside corner, 90 C/I90/AHK1S/DP" -> item = "C/I90/AHK1S/DP"
                    item_parts = re.split(r',\s*\d+\s*', item_text)
                    if len(item_parts) > 1:
                        item_text = item_parts[-1].strip()

                    # Skip if it's just descriptive text
                    if len(item_text) < 3:
                        continue

                    # Outside corners for JOLLY: "EV / J 60 EB 23.30"
                    if 'EV /' in item_text or 'E/' in item_text:
                        material = guess_material(item_text, current_product_line)
                        products.append({
                            "product_line": current_product_line,
                            "item_no": item_text,
                            "material_finish": material,
                            "size_mm": "",
                            "size_inches": "",
                            "list_price": price,
                            "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                            "length": "",
                            "unit": "ea",
                        })

    return products


def guess_material(item_no, product_line):
    """Guess the material/finish from the item number prefix."""
    item = item_no.upper().strip()

    # Matte white / matte black - check before color-coated
    if 'MBW' in item:
        return "Matte white color-coated aluminum"
    if 'MGS' in item:
        return "Matte black color-coated aluminum"

    # Color-coated patterns
    if '+ COLOR' in item or 'TS' in item.split()[-1:]:
        return "Textured color-coated aluminum"

    # Check suffix codes for anodized aluminum finishes
    finish_codes = {
        'AGSG': 'Bright black anodized aluminum',
        'AGRB': 'Brushed graphite anodized aluminum',
        'ABGB': 'Brushed antique bronze anodized aluminum',
        'ACGB': 'Brushed chrome anodized aluminum',
        'ACG': 'Polished chrome anodized aluminum',
        'ACB': 'Bright chrome anodized aluminum',
        'ATGB': 'Brushed nickel anodized aluminum',
        'ATG': 'Polished nickel anodized aluminum',
        'AT': 'Satin nickel anodized aluminum',
        'AKGB': 'Brushed copper anodized aluminum',
        'AKG': 'Polished copper anodized aluminum',
        'AK': 'Satin copper anodized aluminum',
        'AMGB': 'Brushed brass anodized aluminum',
        'AMG': 'Polished brass anodized aluminum',
        'AM': 'Satin brass anodized aluminum',
        'AE': 'Satin anodized aluminum',
    }

    for code, finish in finish_codes.items():
        # Check if the code appears as a suffix/part of the item
        if re.search(r'\b' + code + r'\b', item) or item.endswith(' ' + code):
            return finish

    # Check prefix patterns
    if item.startswith('EB') or '/EB ' in item or ' EB ' in item:
        return "Brushed stainless steel 304"
    if item.startswith('E ') or item.startswith('E/') or re.match(r'^[A-Z]*E\s+\d', item):
        # Check it's not an anodized aluminum code
        if not any(code in item for code in finish_codes):
            return "Stainless steel 304"
    if item.startswith('MC') or ' MC ' in item or item.endswith(' MC'):
        return "Chrome-plated solid brass"
    if item.startswith('M ') or item.startswith('M/') or re.match(r'^[A-Z]*M\s+\d', item):
        if not any(code in item for code in ['MC', 'MBW', 'MGS', 'AMG', 'AMGB', 'AM ']):
            return "Solid brass"
    if re.match(r'^R/', item):
        # Radius version - check what follows
        after_r = item[2:].strip()
        if after_r.startswith('E '):
            return "Stainless steel 304"
        if after_r.startswith('M '):
            return "Solid brass"
        if after_r.startswith('AE') or after_r.startswith('A '):
            return "Satin anodized aluminum" if 'AE' in after_r else "Aluminum"

    # Generic aluminum (A prefix without finish code)
    if re.match(r'^A\s+\d', item):
        return "Aluminum"

    # RENO-V specific
    if item.startswith('AEVT') or item.startswith('AEVB'):
        return "Satin anodized aluminum"
    if item.startswith('AERP') or item.startswith('AERPK'):
        return "Satin anodized aluminum"
    if item.startswith('AEU') or item.startswith('AE'):
        return "Satin anodized aluminum"
    if item.startswith('EU '):
        return "Stainless steel 304"
    if item.startswith('EBU') or item.startswith('EBTK') or item.startswith('EB'):
        return "Brushed stainless steel 304"
    if item.startswith('MU') or item.startswith('MTK'):
        return "Solid brass"
    if item.startswith('ETK'):
        return "Stainless steel 304"
    if item.startswith('AETK'):
        return "Satin anodized aluminum"
    if item.startswith('ATK'):
        # Has suffix code
        return "Anodized aluminum"
    if item.startswith('AU '):
        return "Anodized aluminum"

    # JOLLY
    if item.startswith('J ') and 'EB' in item:
        return "Brushed stainless steel 304"
    if item.startswith('J ') and 'MC' in item:
        return "Chrome-plated solid brass"
    if item.startswith('J ') and 'AE' in item:
        return "Satin anodized aluminum"

    # JOLLY-P PVC
    if product_line == 'JOLLY-P':
        return "PVC"

    # RENO-T
    if item.startswith('T '):
        if ' EB ' in item or item.endswith(' EB'):
            return "Brushed stainless steel 304"
        if ' E ' in item or ' E' == item[-2:]:
            return "Stainless steel 304"
        if ' M ' in item or item.endswith(' M'):
            return "Solid brass"
        if ' AE' in item:
            return "Satin anodized aluminum"
        if ' AT ' in item or item.endswith(' AT'):
            return "Satin nickel anodized aluminum"
        if ' AK ' in item or item.endswith(' AK'):
            return "Satin copper anodized aluminum"
        if ' AM ' in item or item.endswith(' AM'):
            return "Satin brass anodized aluminum"

    # Color-coated PVC / color patterns
    for pvc_code in ['BW', 'W', 'SP', 'BH', 'HB', 'HG', 'PG', 'G', 'GS']:
        if item.startswith(pvc_code + ' ') or item == pvc_code:
            return "PVC" if product_line == 'JOLLY-P' else "Color-coated aluminum"

    # EV / corner pieces
    if 'EV /' in item or 'EV/' in item:
        for code, finish in finish_codes.items():
            if code in item:
                return finish
        if ' EB' in item:
            return "Brushed stainless steel 304"
        if ' MC' in item:
            return "Chrome-plated solid brass"

    return "Unknown"


def parse_membrane_pages(pdf):
    """Parse DITRA/KERDI waterproofing membrane pages (0-indexed 129-134)."""
    products = []

    for page_idx in range(129, 135):
        page = pdf.pages[page_idx]
        text = page.extract_text()
        if not text:
            continue

        lines = text.split('\n')
        current_product = None

        for line in lines:
            line = line.strip()

            # Detect product headers
            if 'DITRA-PS' in line and 'Schluter' in line:
                current_product = 'DITRA-PS'
            elif 'DITRA-XL' in line and 'Schluter' in line:
                current_product = 'DITRA-XL'
            elif 'DITRA ' in line and 'Schluter' in line and 'HEAT' not in line:
                current_product = 'DITRA'
            elif 'KERDI-DS' in line and 'Schluter' in line:
                current_product = 'KERDI-DS'
            elif 'KERDI-FLEX' in line and 'Schluter' in line:
                current_product = 'KERDI-FLEX'
            elif 'KERDI-BAND' in line and 'Schluter' in line:
                current_product = 'KERDI-BAND'
            elif 'KERDI-KERECK' in line and 'Schluter' in line:
                current_product = 'KERDI-KERECK'
            elif 'KERDI-KERS-B' in line and 'Schluter' in line:
                current_product = 'KERDI-KERS-B'
            elif 'KERDI-KERS' in line and 'Schluter' in line:
                current_product = 'KERDI-KERS'
            elif 'KERDI-SEAL-PS' in line and 'Schluter' in line:
                current_product = 'KERDI-SEAL-PS'
            elif 'KERDI-SEAL-MV' in line and 'Schluter' in line:
                current_product = 'KERDI-SEAL-MV'
            elif 'KERDI-KM' in line and 'Schluter' in line:
                current_product = 'KERDI-KM'
            elif 'KERDI-FIX' in line and 'Schluter' in line:
                current_product = 'KERDI-FIX'
            elif re.search(r'Schluter.*KERDI\b', line) and 'BOARD' not in line:
                if current_product not in ['KERDI-DS', 'KERDI-FLEX', 'KERDI-BAND']:
                    current_product = 'KERDI'

            if not current_product:
                continue

            # DITRA roll lines: may have descriptive text prepended from left column
            # e.g., "installation of tile over a wide range of substrates, DITRA 5M 0.995 m x 5.1 m = 5 m2 - 3' 3" x 16' 8" = 54 ft2 2.55 137.72"
            ditra_match = re.search(r'(DITRA(?:-?PS|-?XL)?\s+\S+)\s+[\d.]+\s*m\s*x\s*[\d.]+\s*m\s*=.*?(\d+\.\d{2})\s+(\d+(?:,\d{3})*\.\d{2})\s*$', line)
            if ditra_match:
                item_no = ditra_match.group(1).strip()
                price_sqft = float(ditra_match.group(2))
                price_roll = float(ditra_match.group(3).replace(',', ''))

                # Extract dimensions from the line
                dims_match = re.search(r"([\d.]+\s*m\s*x\s*[\d.]+\s*m\s*=\s*[\d.]+\s*m2.*?=\s*\d+\s*ft2)", line)
                dims = dims_match.group(1) if dims_match else ""

                # Determine product line from item number
                if 'DITRAPS' in item_no or 'DITRA-PS' in item_no:
                    pl = 'DITRA-PS'
                elif 'DITRA-XL' in item_no or 'DITRAXL' in item_no:
                    pl = 'DITRA-XL'
                else:
                    pl = 'DITRA'

                products.append({
                    "product_line": pl,
                    "item_no": item_no,
                    "material_finish": "Polyethylene membrane",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price_roll,
                    "net_price": round(price_roll * DISCOUNT_MULTIPLIER, 2),
                    "length": dims,
                    "unit": "roll",
                })
                # Also add per-sqft entry
                products.append({
                    "product_line": pl,
                    "item_no": item_no,
                    "material_finish": "Polyethylene membrane",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price_sqft,
                    "net_price": round(price_sqft * DISCOUNT_MULTIPLIER, 2),
                    "length": dims,
                    "unit": "sf",
                })
                continue

            # DITRA pallet lines: "... DITRA 30M 0.995 m x 30.4 m = 30 m2 2.23 720.53 9 6,484.77"
            pallet_match = re.search(r'(DITRA\s+\S+)\s+[\d.]+\s*m\s*x\s*[\d.]+\s*m\s*=.*?(\d+\.\d{2})\s+(\d+(?:,\d{3})*\.\d{2})\s+(\d+)\s+(\d+(?:,\d{3})*\.\d{2})\s*$', line)
            if pallet_match:
                item_no = pallet_match.group(1).strip()
                price_sqft = float(pallet_match.group(2))
                price_roll = float(pallet_match.group(3).replace(',', ''))

                dims_match = re.search(r"([\d.]+\s*m\s*x\s*[\d.]+\s*m\s*=\s*[\d.]+\s*m2.*?=\s*\d+\s*ft2)", line)
                dims = dims_match.group(1) if dims_match else ""

                products.append({
                    "product_line": "DITRA",
                    "item_no": item_no + " (pallet)",
                    "material_finish": "Polyethylene membrane",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price_roll,
                    "net_price": round(price_roll * DISCOUNT_MULTIPLIER, 2),
                    "length": dims,
                    "unit": "roll",
                })
                continue

            # KERDI roll lines: may have descriptive text prepended
            # e.g., "applications. KERDI-DS is 20-mil thick and" (not a data line)
            # vs "KERDI 200/5M 1 m x 5 m = 5 m2 - 3' 3" x 16' 5" = 54 ft2 2.55 137.72"
            kerdi_roll = re.search(r'(KERDI(?:-DS)?\s+\S+)\s+[\d.]+\s*m\s*x\s*[\d.]+\s*m\s*=.*?(\d+\.\d{2})\s+(\d+(?:,\d{3})*\.\d{2})\s*$', line)
            if kerdi_roll:
                item_no = kerdi_roll.group(1).strip()
                price_sqft = float(kerdi_roll.group(2))
                price_roll = float(kerdi_roll.group(3).replace(',', ''))

                dims_match = re.search(r"([\d.]+\s*m\s*x\s*[\d.]+\s*m\s*=\s*[\d.]+\s*m2.*?=\s*\d+\s*ft2)", line)
                dims = dims_match.group(1) if dims_match else ""

                pl = 'KERDI-DS' if 'KERDI-DS' in item_no else 'KERDI'

                products.append({
                    "product_line": pl,
                    "item_no": item_no,
                    "material_finish": "Polyethylene membrane",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price_roll,
                    "net_price": round(price_roll * DISCOUNT_MULTIPLIER, 2),
                    "length": dims,
                    "unit": "roll",
                })
                products.append({
                    "product_line": pl,
                    "item_no": item_no,
                    "material_finish": "Polyethylene membrane",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price_sqft,
                    "net_price": round(price_sqft * DISCOUNT_MULTIPLIER, 2),
                    "length": dims,
                    "unit": "sf",
                })
                continue

            # KERDI-BAND lines: "KEBA 100/125/5M 125 mm - 5" 5 m - 16' 5" 4 mil 1.56 25.56"
            band_match = re.match(r'^(KEBA\S*)\s+(\d+\s*mm\s*-\s*[\d/"]+)\s+(.+?)\s+(\d+)\s*mil\s+(\d+\.\d{2})\s+(\d+(?:,\d{3})*\.\d{2})\s*$', line)
            if band_match:
                item_no = band_match.group(1).strip()
                width = band_match.group(2).strip()
                length_str = band_match.group(3).strip()
                price_ft = float(band_match.group(5))
                price_roll = float(band_match.group(6).replace(',', ''))

                products.append({
                    "product_line": "KERDI-BAND",
                    "item_no": item_no,
                    "material_finish": "Polyethylene waterproofing strip",
                    "size_mm": width,
                    "size_inches": "",
                    "list_price": price_roll,
                    "net_price": round(price_roll * DISCOUNT_MULTIPLIER, 2),
                    "length": length_str,
                    "unit": "roll",
                })
                continue

            # KERDI-FLEX lines: "FLEX 125/5M 125 mm - 5" 5 m - 16' 5" 12 mil 2.94 48.31"
            flex_match = re.match(r'^(FLEX\s*\S+)\s+(\d+\s*mm\s*-\s*[\d/"]+)\s+(.+?)\s+(\d+)\s*mil\s+(\d+\.\d{2})\s+(\d+(?:,\d{3})*\.\d{2})\s*$', line)
            if flex_match:
                item_no = flex_match.group(1).strip()
                width = flex_match.group(2).strip()
                length_str = flex_match.group(3).strip()
                price_ft = float(flex_match.group(5))
                price_roll = float(flex_match.group(6).replace(',', ''))

                products.append({
                    "product_line": "KERDI-FLEX",
                    "item_no": item_no,
                    "material_finish": "Polyethylene waterproofing strip",
                    "size_mm": width,
                    "size_inches": "",
                    "list_price": price_roll,
                    "net_price": round(price_roll * DISCOUNT_MULTIPLIER, 2),
                    "length": length_str,
                    "unit": "roll",
                })
                continue

            # KERDI-KERECK corner pieces: "KERECK/FI 2 4 mil 2 Inside corners 19.72"
            kereck_match = re.match(r'^(KERECK\S*)\s+.*?(\d+\.\d{2})\s*$', line)
            if kereck_match and current_product in ['KERDI-KERECK', 'KERDI-KERS-B']:
                item_no = kereck_match.group(1).strip()
                price = float(kereck_match.group(2))

                products.append({
                    "product_line": current_product,
                    "item_no": item_no,
                    "material_finish": "Polyethylene waterproofing",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "pkg",
                })
                continue

            # KERDI-KERS-B lines: "KERSB 135 K LR ... 46.10"
            kersb_match = re.match(r'^(KERSB\s+\S+.*?)\s+(\d+\.\d{2})\s*$', line)
            if kersb_match:
                item_text = kersb_match.group(1).strip()
                price = float(kersb_match.group(2))
                # Clean up - remove packaging descriptions
                item_no = re.split(r'\s+\d+\s*mil\s+', item_text)[0].strip()

                products.append({
                    "product_line": "KERDI-KERS-B",
                    "item_no": item_no,
                    "material_finish": "Polyethylene waterproofing",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "pkg",
                })
                continue

            # KERDI-KERS lines: "KERS 20 L 20 - 3/4 4 mil Left inside corner 26.52"
            kers_match = re.match(r'^(KERS\s+\d+\s+[LR])\s+.*?(\d+\.\d{2})\s*$', line)
            if kers_match:
                item_no = kers_match.group(1).strip()
                price = float(kers_match.group(2))

                products.append({
                    "product_line": "KERDI-KERS",
                    "item_no": item_no,
                    "material_finish": "Polyethylene waterproofing",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "ea",
                })
                continue

            # KERDI-SEAL-PS: "KMS172/12 12.5 mm ... 9.72"
            seal_match = re.match(r'^(KMS\S+)\s+.*?(\d+\.\d{2})\s*$', line)
            if seal_match:
                item_no = seal_match.group(1).strip()
                price = float(seal_match.group(2))

                pl = "KERDI-SEAL-PS" if "MV" not in item_no else "KERDI-SEAL-MV"
                if "KMSMV" in item_no:
                    pl = "KERDI-SEAL-MV"

                products.append({
                    "product_line": pl,
                    "item_no": item_no,
                    "material_finish": "Polyethylene seal",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "ea" if "10" not in item_no.replace("114", "") else "pkg",
                })
                continue

            # KERDI-KM: "KM5117/22 22 mm ... 11.44"
            km_match = re.match(r'^(KM\d+\S*)\s+.*?(\d+\.\d{2})\s*$', line)
            if km_match and 'KMS' not in line:
                item_no = km_match.group(1).strip()
                price = float(km_match.group(2))

                products.append({
                    "product_line": "KERDI-KM",
                    "item_no": item_no,
                    "material_finish": "Polyethylene seal",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "pkg",
                })
                continue

            # KERDI-FIX: "KERDIFIX / + color* 33.04" or "KERDIFIX 100 G 19.19"
            fix_match = re.match(r'^(KERDIFIX\s*\S*)\s+.*?(\d+\.\d{2})\s*$', line)
            if fix_match:
                item_no = fix_match.group(1).strip()
                price = float(fix_match.group(2))

                products.append({
                    "product_line": "KERDI-FIX",
                    "item_no": item_no,
                    "material_finish": "Sealant",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "ea",
                })
                continue

            # DITRA-PS lines: "DITRAPS 110 ... Roll 2.98 327.83"
            ditraps_match = re.search(r'(DITRAPS\s+\S+)\s+[\d.]+\s*m\s*x\s*[\d.]+\s*m\s*=.*?(Roll|Sheet)\s+(\d+\.\d{2})\s+(\d+(?:,\d{3})*\.\d{2})\s*$', line)
            if ditraps_match:
                item_no = ditraps_match.group(1).strip()
                format_type = ditraps_match.group(2).lower()
                price_sqft = float(ditraps_match.group(3))
                price_unit = float(ditraps_match.group(4).replace(',', ''))

                dims_match = re.search(r"([\d.]+\s*m\s*x\s*[\d.]+\s*m\s*=.*?ft2)", line)
                dims = dims_match.group(1) if dims_match else ""

                products.append({
                    "product_line": "DITRA-PS",
                    "item_no": item_no,
                    "material_finish": "Peel and stick polyethylene membrane",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price_unit,
                    "net_price": round(price_unit * DISCOUNT_MULTIPLIER, 2),
                    "length": dims,
                    "unit": format_type,
                })
                products.append({
                    "product_line": "DITRA-PS",
                    "item_no": item_no,
                    "material_finish": "Peel and stick polyethylene membrane",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price_sqft,
                    "net_price": round(price_sqft * DISCOUNT_MULTIPLIER, 2),
                    "length": dims,
                    "unit": "sf",
                })
                continue

    return products


def parse_kerdi_board_pages(pdf):
    """Parse KERDI-BOARD building panel pages (0-indexed 118-127)."""
    products = []

    for page_idx in range(119, 128):  # Skip 118 which is the intro page
        page = pdf.pages[page_idx]
        text = page.extract_text()
        if not text:
            continue

        lines = text.split('\n')
        current_sub_product = "KERDI-BOARD"

        for line in lines:
            line = line.strip()

            # Detect sub-product
            if 'KERDI-BOARD-V' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-V"
            elif 'KERDI-BOARD-E' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-E"
            elif 'KERDI-BOARD-U' in line and 'Schluter' in line and 'ZU' not in line:
                current_sub_product = "KERDI-BOARD-U"
            elif 'KERDI-BOARD-SB' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-SB"
            elif 'KERDI-BOARD-SC' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-SC"
            elif 'KERDI-BOARD-SN' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-SN"
            elif 'KERDI-BOARD-ZC' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-ZC"
            elif 'KERDI-BOARD-ZA' in line and 'Schluter' in line and 'ZSA' not in line:
                current_sub_product = "KERDI-BOARD-ZA"
            elif 'KERDI-BOARD-ZB' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-ZB"
            elif 'KERDI-BOARD-ZW' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-ZW"
            elif 'KERDI-BOARD-ZSD' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-ZSD"
            elif 'KERDI-BOARD-ZT' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-ZT"
            elif 'KERDI-BOARD-ZS' in line and 'Schluter' in line and 'ZSA' not in line and 'ZSD' not in line:
                current_sub_product = "KERDI-BOARD-ZS"
            elif 'KERDI-BOARD-ZFP' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-ZFP"
            elif 'KERDI-BOARD-ZSA' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-ZSA"
            elif 'KERDI-BOARD-ZDK' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BOARD-ZDK"
            elif 'KERDI-BAND' in line and 'Schluter' in line:
                current_sub_product = "KERDI-BAND"

            # KERDI-BOARD panel lines: "12.5 - 1/2 KB 12 1220 812 47.88 144 6,894.72"
            # or: "5 - 3/16 KB 5 1220 1625 87.24 10 872.40"
            kb_match = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\S+)\s+(KB\s+\d+\s+\d+\s+\d+(?:\s*\*)?)\s+(\d+(?:,\d{3})*\.\d{2})', line)
            if kb_match and current_sub_product in ['KERDI-BOARD', 'KERDI-BOARD-V', 'KERDI-BOARD-E', 'KERDI-BOARD-U']:
                size_mm = kb_match.group(1)
                size_in = kb_match.group(2)
                item_no = kb_match.group(3).strip().rstrip('*')
                price = float(kb_match.group(4).replace(',', ''))

                products.append({
                    "product_line": current_sub_product,
                    "item_no": item_no,
                    "material_finish": "Extruded polystyrene panel",
                    "size_mm": size_mm,
                    "size_inches": size_in,
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "ea",
                })
                continue

            # KERDI-BOARD-SB bench: "KBSB 410 TA 41 cm..."
            # These are tricky - price is at end: "197.21" etc
            kbsb_match = re.match(r'^(KBSB\s+\S+\s+\S+)\s+.*?(\d+\.\d{2})\s*$', line)
            if kbsb_match and current_sub_product == 'KERDI-BOARD-SB':
                item_no = kbsb_match.group(1).strip()
                price = float(kbsb_match.group(2))
                if price > 50:  # Filter out dimension numbers
                    products.append({
                        "product_line": "KERDI-BOARD-SB",
                        "item_no": item_no,
                        "material_finish": "KERDI-BOARD prefabricated bench",
                        "size_mm": "",
                        "size_inches": "",
                        "list_price": price,
                        "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                        "length": "",
                        "unit": "ea",
                    })
                continue

            # KERDI-BOARD-SC curb: "KBSC 115 150 970 97 cm ... 71.37"
            kbsc_match = re.match(r'^(KBSC\s+\S+\s+\S+\s+\S+)\s+.*?(\d+\.\d{2})\s*$', line)
            if kbsc_match and current_sub_product == 'KERDI-BOARD-SC':
                item_no = kbsc_match.group(1).strip()
                price = float(kbsc_match.group(2))
                if price > 10:
                    products.append({
                        "product_line": "KERDI-BOARD-SC",
                        "item_no": item_no,
                        "material_finish": "KERDI-BOARD prefabricated curb",
                        "size_mm": "",
                        "size_inches": "",
                        "list_price": price,
                        "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                        "length": "",
                        "unit": "ea",
                    })
                continue

            # KERDI-BOARD-SN niche: "KB 12 SN 305 152 AF ... 70.73"
            kbsn_match = re.match(r'^(KB\s+12\s+SN\s+\S+\s+\S+\s+AF)\s+.*?(\d+\.\d{2})\s*$', line)
            if kbsn_match:
                item_no = kbsn_match.group(1).strip()
                price = float(kbsn_match.group(2))

                products.append({
                    "product_line": "KERDI-BOARD-SN",
                    "item_no": item_no,
                    "material_finish": "KERDI-BOARD prefabricated niche",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "ea",
                })
                continue

            # KERDI-BOARD-ZC/ZA profile lines: "38 - 1-1/2 KB ZC 38 EB" (price may be separate)
            # These have prices floating separately in the text extraction
            # Let's try: line contains "KB Z" and ends with a price
            kbz_match = re.match(r'^.*?(KB\s+Z\w+\s+\d+\s*\w*)\s+(\d+\.\d{2})\s*$', line)
            if kbz_match:
                item_no = kbz_match.group(1).strip()
                price = float(kbz_match.group(2))

                if 'ZC' in item_no:
                    sub = "KERDI-BOARD-ZC"
                elif 'ZA' in item_no:
                    sub = "KERDI-BOARD-ZA"
                elif 'ZB' in item_no:
                    sub = "KERDI-BOARD-ZB"
                elif 'ZW' in item_no:
                    sub = "KERDI-BOARD-ZW"
                elif 'ZFP' in item_no:
                    sub = "KERDI-BOARD-ZFP"
                else:
                    sub = current_sub_product

                material = "Brushed stainless steel" if 'EB' in item_no else "Stainless steel"

                products.append({
                    "product_line": sub,
                    "item_no": item_no,
                    "material_finish": material,
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "2.5 m - 8' 2-1/2\"",
                    "unit": "length",
                })
                continue

            # Corner/connector pieces: "E/KB ZC 38 EB 26.52" or "V/KB Z 38 EB 8.35"
            corner_match = re.match(r'^.*?([EV]/KB\s+Z\w*\s+\d+\s*\w*)\s+(\d+\.\d{2})\s*$', line)
            if corner_match:
                item_no = corner_match.group(1).strip()
                price = float(corner_match.group(2))

                products.append({
                    "product_line": current_sub_product,
                    "item_no": item_no,
                    "material_finish": "Brushed stainless steel",
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "ea",
                })
                continue

            # ZSD anchors, ZT washers, ZS screws: "KB ZSD 90 E 25" + price nearby
            # These have tricky formatting. Try generic: "KB Z... price"
            kbz2_match = re.match(r'^.*?(KB\s+Z\w+\s+\S+(?:\s+\S+)?)\s+(\d+\.\d{2})\s*$', line)
            if kbz2_match and not kbz_match:
                item_no = kbz2_match.group(1).strip()
                price = float(kbz2_match.group(2))

                # Determine sub-product
                if 'ZSD' in item_no:
                    sub = "KERDI-BOARD-ZSD"
                    material = "Stainless steel anchor" if 'E' in item_no.split()[-1] else "Galvanized steel anchor"
                elif 'ZT' in item_no:
                    sub = "KERDI-BOARD-ZT"
                    material = "Galvanized steel washer"
                elif 'ZS ' in item_no or item_no.startswith('KB ZS'):
                    sub = "KERDI-BOARD-ZS"
                    material = "Steel screw"
                elif 'ZSA' in item_no:
                    sub = "KERDI-BOARD-ZSA"
                    material = "Joint reinforcement tape"
                elif 'ZDK' in item_no:
                    sub = "KERDI-BOARD-ZDK"
                    material = "Double-sided adhesive tape"
                elif 'ZFP' in item_no:
                    sub = "KERDI-BOARD-ZFP"
                    material = "Flat plastic profile"
                else:
                    sub = current_sub_product
                    material = "Stainless steel"

                products.append({
                    "product_line": sub,
                    "item_no": item_no,
                    "material_finish": material,
                    "size_mm": "",
                    "size_inches": "",
                    "list_price": price,
                    "net_price": round(price * DISCOUNT_MULTIPLIER, 2),
                    "length": "",
                    "unit": "box" if 'ZSD' in item_no or 'ZT' in item_no or 'ZS' in item_no else "roll",
                })
                continue

            # KERDI-BAND on KERDI-BOARD pages (page 127)
            if current_sub_product == "KERDI-BAND":
                band_match = re.match(r'^(KEBA\S*)\s+(\d+\s*mm\s*-\s*[\d/"]+)\s+(.+?)\s+(\d+)\s*mil\s+(\d+\.\d{2})\s+(\d+(?:,\d{3})*\.\d{2})\s*$', line)
                if band_match:
                    item_no = band_match.group(1).strip()
                    price_roll = float(band_match.group(6).replace(',', ''))
                    length_str = band_match.group(3).strip()

                    products.append({
                        "product_line": "KERDI-BAND",
                        "item_no": item_no,
                        "material_finish": "Polyethylene waterproofing strip",
                        "size_mm": band_match.group(2).strip(),
                        "size_inches": "",
                        "list_price": price_roll,
                        "net_price": round(price_roll * DISCOUNT_MULTIPLIER, 2),
                        "length": length_str,
                        "unit": "roll",
                    })

    return products


def main():
    print(f"Opening PDF: {os.path.abspath(PDF_PATH)}")
    pdf = pdfplumber.open(PDF_PATH)
    print(f"Total pages: {len(pdf.pages)}")

    all_products = []

    # Parse profile pages
    print("\nParsing transition/edge profiles and JOLLY...")
    profile_products = parse_profile_pages(pdf)
    all_products.extend(profile_products)

    # Parse membrane pages
    print("Parsing DITRA/KERDI waterproofing membranes...")
    membrane_products = parse_membrane_pages(pdf)
    all_products.extend(membrane_products)

    # Parse KERDI-BOARD pages
    print("Parsing KERDI-BOARD building panels...")
    board_products = parse_kerdi_board_pages(pdf)
    all_products.extend(board_products)

    pdf.close()

    # Summary
    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)

    counts = defaultdict(int)
    for p in all_products:
        counts[p['product_line']] += 1

    total = 0
    for line in sorted(counts.keys()):
        print(f"  {line:30s} {counts[line]:5d} items")
        total += counts[line]

    print(f"  {'TOTAL':30s} {total:5d} items")

    # Material distribution
    print("\n" + "-" * 60)
    print("MATERIAL DISTRIBUTION")
    print("-" * 60)
    mat_counts = defaultdict(int)
    for p in all_products:
        mat_counts[p['material_finish']] += 1
    for mat in sorted(mat_counts.keys()):
        print(f"  {mat:45s} {mat_counts[mat]:5d}")

    # Write JSON
    output_path = os.path.abspath(OUTPUT_PATH)
    with open(output_path, 'w') as f:
        json.dump(all_products, f, indent=2)

    print(f"\nJSON written to: {output_path}")
    print(f"File size: {os.path.getsize(output_path):,} bytes")

    # Print sample
    print("\n" + "=" * 60)
    print("SAMPLE OUTPUT (first 5 items)")
    print("=" * 60)
    for item in all_products[:5]:
        print(json.dumps(item, indent=2))

    print("\n" + "=" * 60)
    print("SAMPLE OUTPUT (DITRA/KERDI - first 3)")
    print("=" * 60)
    membrane_items = [p for p in all_products if p['product_line'] in ['DITRA', 'KERDI', 'DITRA-PS']]
    for item in membrane_items[:3]:
        print(json.dumps(item, indent=2))

    print("\n" + "=" * 60)
    print("SAMPLE OUTPUT (KERDI-BOARD - first 3)")
    print("=" * 60)
    board_items = [p for p in all_products if 'KERDI-BOARD' in p['product_line']]
    for item in board_items[:3]:
        print(json.dumps(item, indent=2))


if __name__ == '__main__':
    main()
