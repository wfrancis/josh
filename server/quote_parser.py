"""
Parse vendor quotes from email, PDF, text, CSV, and XLSX files.
Uses pdfplumber for PDF text extraction and the model selected in Settings for structured parsing.
"""

import base64
from difflib import SequenceMatcher
import email
import json
import math
import os
import re
import tempfile
from email import policy
from io import BytesIO
from typing import Optional

import pdfplumber

from ai_client import chat_complete, get_provider_info
from quote_evidence import normalize_quote_unit


MAX_QUOTE_FILE_BYTES = 25 * 1024 * 1024
MAX_AI_TEXT_CHARS = 200_000
MAX_NESTED_EMAIL_DEPTH = 2
MAX_PDF_VISION_PAGES = 8
MAX_PDF_VISION_IMAGE_BYTES = 18 * 1024 * 1024
PDF_VISION_RESOLUTION = 144


def _bounded_quote_text(value: str) -> str:
    text = str(value or "")
    if len(text) <= MAX_AI_TEXT_CHARS:
        return text
    return text[:MAX_AI_TEXT_CHARS] + "\n[remaining quote text omitted]"

# ── Configurable OpenAI settings ──────────────────────────────────────────────
_openai_config = {
    "api_key": None,   # None = use OPENAI_API_KEY env var
    "num_passes": 2,
}


def set_openai_config(api_key: str = None, model: str = None, num_passes: int = None):
    """Update OpenAI configuration at runtime."""
    if api_key is not None:
        _openai_config["api_key"] = api_key if api_key else None
    if num_passes is not None:
        _openai_config["num_passes"] = max(1, min(5, num_passes))


SYSTEM_PROMPT = """You are a flooring vendor quote parser for Standard Interiors, a commercial flooring contractor.
Extract product pricing from the vendor quote text.

IMPORTANT RULES:
1. If a single price applies to multiple product lines (e.g. "WG100 and WG200 $27.25"), create a SEPARATE entry for EACH product line with the same price.
2. Match the original quote request if included in the email thread — use those product names and codes.
3. The unit for carpet tile (CPT) is always SY (square yards). LVT units are typically SF (square feet).
4. Extract accessory/adhesive pricing as separate products (TacTiles, adhesives, primers, etc.)

Return a JSON object with a "products" array. Each product should have:
- vendor: string (company name of the vendor)
- product_name: string (product line name / style — e.g. "WG100", "Breakout", "Dot-O-Mine")
- unit_price: number (price per unit)
- unit: string (SF, SY, LF, EA, etc.)
- freight: string or null (freight terms if mentioned, e.g. "FOB La Grange, GA")
- lead_time: string or null (delivery lead time if mentioned)
- notes: string or null (any special notes, minimums, conditions, backing info)

If you cannot determine a field, set it to null.
Only return the JSON object, no other text."""


def _positive_price(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "")
        match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        value = match.group(0)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if math.isfinite(number) and number > 0 else None


def _normalize_products(products) -> list[dict]:
    """Keep only usable source-priced rows and normalize their numeric contract."""
    normalized = []
    for raw in products if isinstance(products, list) else []:
        if not isinstance(raw, dict):
            continue
        product_name = str(raw.get("product_name") or "").strip()
        unit_price = _positive_price(raw.get("unit_price"))
        if not product_name or unit_price is None:
            continue
        product = dict(raw)
        product["product_name"] = product_name
        product["vendor"] = str(product.get("vendor") or "").strip()
        product["unit"] = normalize_quote_unit(product.get("unit"))
        product["unit_price"] = unit_price
        freight = product.get("freight")
        if isinstance(freight, (int, float)) and not isinstance(freight, bool):
            product["freight"] = round(float(freight), 4) if math.isfinite(float(freight)) else None
        elif freight is not None:
            product["freight"] = str(freight).strip() or None
        normalized.append(product)
    return normalized


def _explicit_product_code(product: dict) -> str:
    """Find a clearly labeled or hyphenated item code across AI output fields."""
    direct = str(product.get("item_code") or "").strip()
    if direct and re.search(r"\d", direct):
        return re.sub(r"[^a-z0-9]+", "", direct.lower())

    texts = [
        str(product.get(field) or "")
        for field in ("product_name", "notes", "description")
        if product.get(field)
    ]
    patterns = (
        r"\b(?:item|product)\s*code\s*[:#-]?\s*([a-z]{1,10}\s*-?\s*\d{2,}[a-z0-9.-]*)\b",
        r"\b([a-z]{1,10}\s*-\s*\d{2,}[a-z0-9.-]*)\b",
        r"^\s*([a-z]{1,10}\d{2,}[a-z0-9.-]*)\b",
    )
    for pattern in patterns:
        for text in texts:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return re.sub(r"[^a-z0-9]+", "", match.group(1).lower())
    return ""


def _product_identity_key(product: dict) -> tuple[str, str]:
    """Return a conservative identity for reconciling repeated AI reads."""
    raw_name = str(product.get("product_name") or "").lower()
    item_code = _explicit_product_code(product)
    if item_code:
        name = f"code:{item_code}"
        vendor = ""
    else:
        name = f"name:{re.sub(r'[^a-z0-9]+', '', raw_name)}"
        vendor = re.sub(r"[^a-z0-9]+", "", str(product.get("vendor") or "").lower())
    return name, vendor


def _identity_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").lower())


def _vendor_identity_tokens(value: str) -> set[str]:
    ignored = {"co", "company", "corp", "corporation", "dba", "inc", "llc", "ltd", "the"}
    return {token for token in _identity_tokens(value) if token not in ignored}


def _vendors_compatible(left: dict, right: dict) -> bool:
    left_tokens = _vendor_identity_tokens(left.get("vendor"))
    right_tokens = _vendor_identity_tokens(right.get("vendor"))
    if not left_tokens or not right_tokens:
        return True
    overlap = len(left_tokens & right_tokens)
    return overlap / min(len(left_tokens), len(right_tokens)) >= 0.75


def _product_name_similarity(left: dict, right: dict) -> float:
    """Score only conservative, source-row-like name differences."""
    left_tokens = _identity_tokens(left.get("product_name"))
    right_tokens = _identity_tokens(right.get("product_name"))
    if min(len(left_tokens), len(right_tokens)) < 3:
        return 0.0

    left_numbers = {token for token in left_tokens if any(char.isdigit() for char in token)}
    right_numbers = {token for token in right_tokens if any(char.isdigit() for char in token)}
    if left_numbers != right_numbers:
        return 0.0

    left_text = " ".join(left_tokens)
    right_text = " ".join(right_tokens)
    sequence_score = SequenceMatcher(None, left_text, right_text).ratio()
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    if left_set == right_set and len(left_set) >= 4:
        return max(sequence_score, 0.99)

    if (
        min(len(left_set), len(right_set)) >= 4
        and (left_set <= right_set or right_set <= left_set)
        and len(left_set ^ right_set) <= 2
    ):
        return max(sequence_score, 0.92)
    return sequence_score


def _fuzzy_identity_group(product: dict, groups: list[list[dict]]) -> int | None:
    """Return one unambiguous high-confidence group or fail closed."""
    if _explicit_product_code(product):
        return None

    candidates = []
    for index, variants in enumerate(groups):
        compatible = [variant for variant in variants if _vendors_compatible(product, variant)]
        if not compatible:
            continue
        score = max(_product_name_similarity(product, variant) for variant in compatible)
        if score >= 0.82:
            candidates.append((score, index))

    strong = [(score, index) for score, index in candidates if score >= 0.90]
    if len(strong) == 1 and len(candidates) == 1:
        return strong[0][1]
    if candidates:
        label = str(product.get("product_name") or "product")
        matches = ", ".join(
            str(groups[index][0].get("product_name") or "product")
            for _, index in sorted(candidates, reverse=True)
        )
        raise ValueError(
            f"AI quote-reading passes produced an ambiguous product name for {label}: "
            f"possible match(es): {matches}. Review the source and retry."
        )
    return None


def _extract_pdf_text(pdf_path: str) -> str:
    """Extract all text from a PDF file using pdfplumber."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
                if sum(len(part) for part in text_parts) >= MAX_AI_TEXT_CHARS:
                    break
    return _bounded_quote_text("\n".join(text_parts))


def _extract_pdf_page_images(pdf_path: str) -> list[str]:
    """Render image-only quote pages as bounded JPEG data URLs for vision parsing."""
    image_data_urls = []
    total_image_bytes = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:MAX_PDF_VISION_PAGES]:
            page_image = page.to_image(
                resolution=PDF_VISION_RESOLUTION,
                antialias=True,
            )
            original = page_image.original
            rendered = original.convert("RGB")
            try:
                with BytesIO() as image_buffer:
                    rendered.save(image_buffer, format="JPEG", quality=82, optimize=True)
                    image_bytes = image_buffer.getvalue()
            finally:
                rendered.close()
                if original is not rendered:
                    original.close()
            if total_image_bytes + len(image_bytes) > MAX_PDF_VISION_IMAGE_BYTES:
                break
            total_image_bytes += len(image_bytes)
            encoded = base64.b64encode(image_bytes).decode("ascii")
            image_data_urls.append(f"data:image/jpeg;base64,{encoded}")
    return image_data_urls


def _extract_eml(eml_path: str) -> dict:
    """
    Parse an .eml file. Returns:
    {
        "headers": {from, subject, date},
        "body": str,
        "attachments": [{filename, content_type, data}]
    }
    """
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    headers = {
        "from": str(msg.get("From", "")),
        "subject": str(msg.get("Subject", "")),
        "date": str(msg.get("Date", "")),
    }

    body_parts = []
    attachments = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = part.get_content_disposition()

        if disposition == "attachment" or (
            part.get_filename() and content_type in (
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/octet-stream",
            )
        ):
            attachments.append({
                "filename": part.get_filename() or "attachment",
                "content_type": content_type,
                "data": part.get_payload(decode=True),
            })
        elif content_type == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                body_parts.append(payload.decode("utf-8", errors="replace"))
        elif content_type == "text/html" and not body_parts:
            payload = part.get_payload(decode=True)
            if payload:
                # Basic HTML strip for fallback
                import re
                html_text = payload.decode("utf-8", errors="replace")
                clean = re.sub(r"<[^>]+>", " ", html_text)
                clean = re.sub(r"\s+", " ", clean).strip()
                body_parts.append(clean)

    return {
        "headers": headers,
        "body": "\n".join(body_parts),
        "attachments": attachments,
    }


def _call_ai_single(
    quote_text: str,
    api_key: str,
    model: str,
    image_data_urls: list[str] | None = None,
) -> list[dict]:
    """Single pass: send text to AI and parse the structured response."""
    content = chat_complete(
        system=SYSTEM_PROMPT,
        user=quote_text,
        api_key=api_key,
        model=model,
        json_mode=True,
        image_data_urls=image_data_urls,
    )
    parsed = json.loads(content)
    return _normalize_products(parsed.get("products", []) if isinstance(parsed, dict) else [])


def _merge_multipass_results(all_results: list[list[dict]]) -> list[dict]:
    """
    Merge repeated extraction results without inventing source values.

    Explicit codes, punctuation-only names, and one unambiguous high-similarity
    name are treated as the same row. Ambiguous names and source-value
    disagreements fail closed so the caller cannot write duplicate or averaged
    values that were not proven by the quote.
    """
    groups: list[list[dict]] = []
    exact_groups: dict[tuple[str, str], int] = {}
    for pass_result in all_results:
        prior_group_count = len(groups)
        for product in _normalize_products(pass_result):
            identity = _product_identity_key(product)
            group_index = exact_groups.get(identity)
            if group_index is None:
                group_index = _fuzzy_identity_group(product, groups[:prior_group_count])
            if group_index is None:
                group_index = len(groups)
                groups.append([])
            groups[group_index].append(product)
            exact_groups[identity] = group_index

    merged = []
    for variants in groups:
        richest = max(
            variants,
            key=lambda value: (
                len(_identity_tokens(value.get("product_name"))),
                len(str(value.get("product_name") or "")),
            ),
        )
        base = dict(richest)
        label = str(base.get("product_name") or "product")
        prices = sorted({round(float(v["unit_price"]), 4) for v in variants})
        if len(prices) != 1:
            raise ValueError(
                f"AI quote-reading passes disagree on the price for {label}: "
                f"{', '.join(f'${price:g}' for price in prices)}. Review the source and retry."
            )
        base["unit_price"] = prices[0]

        units = sorted({str(v.get("unit") or "").strip().upper() for v in variants if v.get("unit")})
        if len(units) > 1:
            raise ValueError(
                f"AI quote-reading passes disagree on the unit for {label}: "
                f"{', '.join(units)}. Review the source and retry."
            )
        if units:
            base["unit"] = units[0]

        if not base.get("vendor"):
            base["vendor"] = next((v.get("vendor") for v in variants if v.get("vendor")), "")

        freights = [v.get("freight") for v in variants if v.get("freight")]
        if freights:
            numeric_freights = sorted({
                round(float(f), 4)
                for f in freights
                if isinstance(f, (int, float)) and not isinstance(f, bool)
            })
            if len(numeric_freights) > 1:
                raise ValueError(
                    f"AI quote-reading passes disagree on freight for {label}. "
                    "Review the source and retry."
                )
            if numeric_freights:
                base["freight"] = numeric_freights[0]
            else:
                base["freight"] = freights[0]

        merged.append(base)

    return _normalize_products(merged)


def quote_multipass_audit_contract() -> dict:
    """Return a deterministic contract used by the deployed release harness."""
    duplicate_passes = [
        [{
            "vendor": "Harness Vision Supply",
            "product_name": "Harness Scanned Tile (OCR-100)",
            "unit_price": 7.25,
            "unit": "SF",
        }],
        [{
            "vendor": "Harness Vision Supply",
            "product_name": "Harness Scanned Tile",
            "unit_price": 7.25,
            "unit": "SF",
            "notes": "Item Code: OCR-100",
        }],
    ]
    merged = _merge_multipass_results(duplicate_passes)

    semantic_duplicate_passes = [
        [{
            "vendor": "Concept Surfaces",
            "product_name": "Raw Stone 05 - Ceppo Di Gre 12x24",
            "unit_price": 5.9,
            "unit": "SF",
        }],
        [{
            "vendor": "Concept Surfaces LLC",
            "product_name": "Stone 05 - Ceppo Di Gre 12x24",
            "unit_price": 5.9,
            "unit": "SF",
        }],
    ]
    semantic_merged = _merge_multipass_results(semantic_duplicate_passes)
    piece_unit_merged = _merge_multipass_results([
        [{
            "vendor": "Concept Surfaces",
            "product_name": "Industry Titanium 3x36 Bullnose",
            "unit_price": 14.45,
            "unit": "PC",
        }],
        [{
            "vendor": "Concept Surfaces",
            "product_name": "Industry Titanium 3x36 Bullnose",
            "unit_price": 14.45,
            "unit": "EA",
        }],
    ])

    price_conflict = None
    try:
        _merge_multipass_results([
            duplicate_passes[0],
            [{**duplicate_passes[1][0], "unit_price": 7.75}],
        ])
    except ValueError as exc:
        price_conflict = str(exc)

    unit_conflict = None
    try:
        _merge_multipass_results([
            duplicate_passes[0],
            [{**duplicate_passes[1][0], "unit": "EA"}],
        ])
    except ValueError as exc:
        unit_conflict = str(exc)

    semantic_price_conflict = None
    try:
        _merge_multipass_results([
            semantic_duplicate_passes[0],
            [{**semantic_duplicate_passes[1][0], "unit_price": 6.25}],
        ])
    except ValueError as exc:
        semantic_price_conflict = str(exc)

    ambiguous_name = None
    try:
        _merge_multipass_results([
            [
                {
                    "vendor": "Concept Surfaces",
                    "product_name": "Pueblo Bianco Matte 12x24",
                    "unit_price": 5.2,
                    "unit": "SF",
                },
                {
                    "vendor": "Concept Surfaces",
                    "product_name": "Pueblo Bianco Satin 12x24",
                    "unit_price": 5.2,
                    "unit": "SF",
                },
            ],
            [{
                "vendor": "Concept Surfaces",
                "product_name": "Pueblo Bianco 12x24",
                "unit_price": 5.2,
                "unit": "SF",
            }],
        ])
    except ValueError as exc:
        ambiguous_name = str(exc)

    passed = (
        len(merged) == 1
        and merged[0].get("unit_price") == 7.25
        and merged[0].get("unit") == "SF"
        and len(semantic_merged) == 1
        and semantic_merged[0].get("product_name") == "Raw Stone 05 - Ceppo Di Gre 12x24"
        and semantic_merged[0].get("unit_price") == 5.9
        and len(piece_unit_merged) == 1
        and piece_unit_merged[0].get("unit") == "EA"
        and bool(price_conflict)
        and bool(unit_conflict)
        and bool(semantic_price_conflict)
        and bool(ambiguous_name)
    )
    return {
        "status": "pass" if passed else "fail",
        "merged": merged,
        "semantic_merged": semantic_merged,
        "piece_unit_merged": piece_unit_merged,
        "price_conflict_rejected": bool(price_conflict),
        "price_conflict_error": price_conflict,
        "unit_conflict_rejected": bool(unit_conflict),
        "unit_conflict_error": unit_conflict,
        "semantic_price_conflict_rejected": bool(semantic_price_conflict),
        "semantic_price_conflict_error": semantic_price_conflict,
        "ambiguous_name_rejected": bool(ambiguous_name),
        "ambiguous_name_error": ambiguous_name,
    }


def _call_openai(
    quote_text: str,
    *,
    strict: bool = False,
    image_data_urls: list[str] | None = None,
) -> list[dict]:
    """Multi-pass AI call: runs N passes and merges results for accuracy."""
    quote_text = _bounded_quote_text(quote_text)
    from models import get_settings
    settings = get_settings()
    api_key = settings.get("openai_api_key") or _openai_config["api_key"] or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    num_passes = _openai_config["num_passes"]

    # Check if any AI provider is available
    provider = get_provider_info(api_key)
    if not provider["available"]:
        print("[quote_parser] No AI API key available — cannot parse quotes")
        return []

    if num_passes <= 1:
        return _call_ai_single(quote_text, api_key, model, image_data_urls)

    # Run multiple passes
    all_results = []
    for i in range(num_passes):
        try:
            result = _call_ai_single(quote_text, api_key, model, image_data_urls)
            all_results.append(result)
        except Exception:
            if strict or i == 0:
                raise
            # If later passes fail, just skip

    if not all_results:
        return []

    return _merge_multipass_results(all_results)


def parse_quote_pdf(pdf_path: str, *, strict: bool = False) -> list[dict]:
    """Parse a vendor quote from a PDF file."""
    text = _extract_pdf_text(pdf_path)
    if text.strip():
        return _call_openai(text, strict=strict)
    page_images = _extract_pdf_page_images(pdf_path)
    if not page_images:
        return []
    return _call_openai(
        "This PDF has no extractable text. The attached images are its pages in order. "
        "Read the visible quote and extract every priced product row.",
        strict=strict,
        image_data_urls=page_images,
    )


def _deduplicate_products(products: list[dict]) -> list[dict]:
    """Remove exact duplicate rows produced by an email body and attachment."""
    result = []
    seen = set()
    for product in _normalize_products(products):
        key = (
            str(product.get("vendor") or "").strip().lower(),
            str(product.get("product_name") or "").strip().lower(),
            str(product.get("unit") or "").strip().lower(),
            str(product.get("unit_price") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(product)
    return result


def _rows_to_quote_text(rows, *, max_rows: int = 5000, max_columns: int = 100) -> str:
    lines = []
    for row_index, row in enumerate(rows):
        if row_index >= max_rows:
            lines.append("[remaining rows omitted]")
            break
        values = []
        for value in list(row)[:max_columns]:
            text = "" if value is None else str(value)
            values.append(" ".join(text.split()))
        if any(values):
            lines.append("\t".join(values))
    return "\n".join(lines)


def _parse_structured_quote_csv(file_path: str) -> list[dict] | None:
    """Parse a named-column vendor CSV without an AI round trip.

    Return ``None`` when the file is not using the supported structured
    contract so the existing text/AI parser can handle free-form exports.
    """
    import csv

    aliases = {
        "product": "product_name",
        "product_name": "product_name",
        "item": "product_name",
        "item_code": "item_code",
        "sku": "item_code",
        "description": "description",
        "vendor": "vendor",
        "manufacturer": "vendor",
        "unit_price": "unit_price",
        "price": "unit_price",
        "cost": "unit_price",
        "unit": "unit",
        "uom": "unit",
        "freight": "freight",
        "lead_time": "lead_time",
        "notes": "notes",
    }
    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        raw_fields = reader.fieldnames or []
        field_map = {
            field: aliases.get("_".join(str(field or "").strip().lower().split()))
            for field in raw_fields
        }
        mapped_fields = {mapped for mapped in field_map.values() if mapped}
        if "unit_price" not in mapped_fields or not ({"product_name", "item_code"} & mapped_fields):
            return None

        products = []
        for raw_row in reader:
            row = {
                mapped: str(raw_row.get(source) or "").strip()
                for source, mapped in field_map.items()
                if mapped
            }
            raw_price = row.get("unit_price", "").replace("$", "").replace(",", "").strip()
            try:
                unit_price = float(raw_price)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(unit_price) or unit_price <= 0:
                continue
            item_code = row.get("item_code", "")
            description = row.get("description", "")
            product_name = row.get("product_name", "")
            if not product_name:
                product_name = " - ".join(value for value in (item_code, description) if value)
            elif item_code and item_code.lower() not in product_name.lower():
                product_name = f"{item_code} - {product_name}"
            if not product_name:
                continue
            products.append({
                "product_name": product_name,
                "description": description,
                "vendor": row.get("vendor", ""),
                "unit_price": unit_price,
                "unit": row.get("unit", ""),
                "freight": row.get("freight", ""),
                "lead_time": row.get("lead_time", ""),
                "notes": row.get("notes", ""),
            })
    return _deduplicate_products(products)


def parse_quote_spreadsheet(file_path: str, *, strict: bool = False) -> list[dict]:
    """Convert CSV/XLSX cells to stable text and parse vendor pricing."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        import csv
        structured = _parse_structured_quote_csv(file_path)
        if structured is not None:
            return structured
        with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            text = _rows_to_quote_text(csv.reader(handle))
    elif ext == ".xlsx":
        import openpyxl
        workbook = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        try:
            sections = []
            for sheet in workbook.worksheets:
                sheet_text = _rows_to_quote_text(sheet.iter_rows(values_only=True))
                if sheet_text:
                    sections.append(f"Worksheet: {sheet.title}\n{sheet_text}")
            text = "\n\n".join(sections)
        finally:
            workbook.close()
    else:
        raise ValueError(f"Unsupported spreadsheet type: {ext}")
    return _call_openai(text, strict=strict) if text.strip() else []


def parse_quote_eml(eml_path: str, *, depth: int = 0, strict: bool = False) -> list[dict]:
    """Parse a vendor quote from an .eml file. Processes body + PDF attachments."""
    eml_data = _extract_eml(eml_path)
    all_products = []

    # Process email body
    if eml_data["body"].strip():
        context = (
            f"Vendor Email from: {eml_data['headers']['from']}\n"
            f"Subject: {eml_data['headers']['subject']}\n"
            f"Date: {eml_data['headers']['date']}\n\n"
            f"{eml_data['body']}"
        )
        try:
            products = _call_openai(context, strict=strict)
            all_products.extend(products)
        except Exception as e:
            if strict:
                raise RuntimeError("Vendor email body parsing failed") from e
            print(f"[quote_parser] Error parsing email body: {e}")
            import traceback; traceback.print_exc()

    # Process supported quote attachments.
    for att in eml_data["attachments"]:
        filename = att.get("filename") or "attachment"
        ext = os.path.splitext(filename)[1].lower()
        data = att.get("data")
        if ext not in {".pdf", ".txt", ".csv", ".xlsx", ".eml", ".msg"}:
            continue
        if not data:
            if strict:
                raise ValueError(f"Vendor email attachment {filename} is empty")
            continue
        if len(data) > MAX_QUOTE_FILE_BYTES:
            if strict:
                raise ValueError(
                    f"Vendor email attachment {filename} exceeds the "
                    f"{MAX_QUOTE_FILE_BYTES // (1024 * 1024)} MB limit"
                )
            continue
        if ext in {".eml", ".msg"} and depth >= MAX_NESTED_EMAIL_DEPTH:
            if strict:
                raise ValueError(f"Nested vendor email attachment {filename} exceeds the supported depth")
            continue
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            all_products.extend(parse_quote_file(tmp_path, _depth=depth + 1, strict=strict))
        except Exception as exc:
            if strict:
                raise RuntimeError(f"Vendor email attachment {filename} could not be parsed") from exc
            print(f"[quote_parser] Error parsing attachment {filename}: {exc}")
        finally:
            os.unlink(tmp_path)

    return _deduplicate_products(all_products)


def parse_quote_msg(msg_path: str, *, depth: int = 0, strict: bool = False) -> list[dict]:
    """Parse an Outlook .msg email body and any attached PDFs."""
    import extract_msg

    message = extract_msg.openMsg(msg_path)
    try:
        context = (
            f"Vendor Email from: {getattr(message, 'sender', '') or ''}\n"
            f"Subject: {getattr(message, 'subject', '') or ''}\n"
            f"Date: {getattr(message, 'date', '') or ''}\n\n"
            f"{getattr(message, 'body', '') or ''}"
        )
        all_products = _call_openai(context, strict=strict) if context.strip() else []

        for attachment in getattr(message, "attachments", []) or []:
            filename = (
                getattr(attachment, "longFilename", None)
                or getattr(attachment, "shortFilename", None)
                or getattr(attachment, "name", None)
                or "attachment"
            )
            data = getattr(attachment, "data", None)
            ext = os.path.splitext(str(filename))[1].lower()
            if ext not in {".pdf", ".txt", ".csv", ".xlsx", ".eml", ".msg"}:
                continue
            if not isinstance(data, (bytes, bytearray)) or not data:
                if strict:
                    raise ValueError(f"Outlook attachment {filename} is empty")
                continue
            if len(data) > MAX_QUOTE_FILE_BYTES:
                if strict:
                    raise ValueError(
                        f"Outlook attachment {filename} exceeds the "
                        f"{MAX_QUOTE_FILE_BYTES // (1024 * 1024)} MB limit"
                    )
                continue
            if ext in {".eml", ".msg"} and depth >= MAX_NESTED_EMAIL_DEPTH:
                if strict:
                    raise ValueError(f"Nested Outlook attachment {filename} exceeds the supported depth")
                continue
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                all_products.extend(parse_quote_file(tmp_path, _depth=depth + 1, strict=strict))
            except Exception as exc:
                if strict:
                    raise RuntimeError(f"Outlook attachment {filename} could not be parsed") from exc
                print(f"[quote_parser] Error parsing .msg attachment {filename}: {exc}")
            finally:
                os.unlink(tmp_path)
        return _deduplicate_products(all_products)
    finally:
        message.close()


def parse_quote_text(text_path: str, *, strict: bool = False) -> list[dict]:
    """Parse a plain-text vendor response."""
    with open(text_path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.read(MAX_AI_TEXT_CHARS + 1)
    return _call_openai(content, strict=strict) if content.strip() else []


def parse_quote_file(file_path: str, *, _depth: int = 0, strict: bool = False) -> list[dict]:
    """Auto-detect file type and parse accordingly."""
    try:
        file_size = os.path.getsize(file_path)
    except OSError as exc:
        raise ValueError(f"Quote file is unavailable: {exc}") from exc
    if file_size > MAX_QUOTE_FILE_BYTES:
        raise ValueError(f"Quote file exceeds the {MAX_QUOTE_FILE_BYTES // (1024 * 1024)} MB limit")
    if _depth > MAX_NESTED_EMAIL_DEPTH:
        raise ValueError("Nested vendor email depth exceeds the supported limit")
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".eml":
        return parse_quote_eml(file_path, depth=_depth, strict=strict)
    if ext == ".msg":
        return parse_quote_msg(file_path, depth=_depth, strict=strict)
    if ext == ".pdf":
        return parse_quote_pdf(file_path, strict=strict)
    if ext == ".txt":
        return parse_quote_text(file_path, strict=strict)
    if ext in (".csv", ".xlsx"):
        return parse_quote_spreadsheet(file_path, strict=strict)
    raise ValueError(f"Unsupported file type: {ext}. Expected .eml, .msg, .pdf, .txt, .csv, or .xlsx")
