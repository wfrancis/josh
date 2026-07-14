"""
Parse vendor quotes from email, PDF, text, CSV, and XLSX files.
Uses pdfplumber for PDF text extraction and the model selected in Settings for structured parsing.
"""

import email
import json
import math
import os
import re
import tempfile
from email import policy
from typing import Optional

import statistics

import pdfplumber

from ai_client import chat_complete, get_provider_info


MAX_QUOTE_FILE_BYTES = 25 * 1024 * 1024
MAX_AI_TEXT_CHARS = 200_000
MAX_NESTED_EMAIL_DEPTH = 2


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
        product["unit"] = str(product.get("unit") or "").strip().upper()
        product["unit_price"] = unit_price
        freight = product.get("freight")
        if isinstance(freight, (int, float)) and not isinstance(freight, bool):
            product["freight"] = round(float(freight), 4) if math.isfinite(float(freight)) else None
        elif freight is not None:
            product["freight"] = str(freight).strip() or None
        normalized.append(product)
    return normalized


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


def _call_ai_single(quote_text: str, api_key: str, model: str) -> list[dict]:
    """Single pass: send text to AI and parse the structured response."""
    content = chat_complete(
        system=SYSTEM_PROMPT,
        user=quote_text,
        api_key=api_key,
        model=model,
        json_mode=True,
    )
    parsed = json.loads(content)
    return _normalize_products(parsed.get("products", []) if isinstance(parsed, dict) else [])


def _merge_multipass_results(all_results: list[list[dict]]) -> list[dict]:
    """
    Merge results from multiple passes. For each product found,
    take the median price across passes for stability.
    """
    if len(all_results) == 1:
        return all_results[0]

    # Index products by normalized name across all passes
    product_map: dict[str, list[dict]] = {}
    for pass_result in all_results:
        for product in pass_result:
            key = (product.get("product_name", "").strip().lower(),
                   product.get("vendor", "").strip().lower())
            norm_key = f"{key[0]}||{key[1]}"
            product_map.setdefault(norm_key, []).append(product)

    merged = []
    seen = set()
    for norm_key, variants in product_map.items():
        if norm_key in seen:
            continue
        seen.add(norm_key)

        # Use the most common version as the base
        base = variants[0]

        # Take median unit_price for stability
        prices = [v.get("unit_price", 0) for v in variants if v.get("unit_price")]
        if prices:
            base["unit_price"] = round(statistics.median(prices), 2)

        # Take median freight if numeric, otherwise keep first string value
        freights = [v.get("freight") for v in variants if v.get("freight")]
        if freights:
            numeric_freights = [f for f in freights if isinstance(f, (int, float))]
            if numeric_freights:
                base["freight"] = round(statistics.median(numeric_freights), 2)
            else:
                base["freight"] = freights[0]  # Keep string like "FOB La Grange, GA"

        merged.append(base)

    return merged


def _call_openai(quote_text: str) -> list[dict]:
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
        return _call_ai_single(quote_text, api_key, model)

    # Run multiple passes
    all_results = []
    for i in range(num_passes):
        try:
            result = _call_ai_single(quote_text, api_key, model)
            all_results.append(result)
        except Exception:
            if i == 0:
                raise
            # If later passes fail, just skip

    if not all_results:
        return []

    return _merge_multipass_results(all_results)


def parse_quote_pdf(pdf_path: str) -> list[dict]:
    """Parse a vendor quote from a PDF file."""
    text = _extract_pdf_text(pdf_path)
    if not text.strip():
        return []
    return _call_openai(text)


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


def parse_quote_spreadsheet(file_path: str) -> list[dict]:
    """Convert CSV/XLSX cells to stable text and parse vendor pricing."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        import csv
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
    return _call_openai(text) if text.strip() else []


def parse_quote_eml(eml_path: str, *, depth: int = 0) -> list[dict]:
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
            products = _call_openai(context)
            all_products.extend(products)
        except Exception as e:
            print(f"[quote_parser] Error parsing email body: {e}")
            import traceback; traceback.print_exc()

    # Process supported quote attachments.
    for att in eml_data["attachments"]:
        filename = att.get("filename") or "attachment"
        ext = os.path.splitext(filename)[1].lower()
        data = att.get("data")
        if (
            ext not in {".pdf", ".txt", ".csv", ".xlsx", ".eml", ".msg"}
            or not data
            or len(data) > MAX_QUOTE_FILE_BYTES
            or (ext in {".eml", ".msg"} and depth >= MAX_NESTED_EMAIL_DEPTH)
        ):
            continue
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            all_products.extend(parse_quote_file(tmp_path, _depth=depth + 1))
        except Exception as exc:
            print(f"[quote_parser] Error parsing attachment {filename}: {exc}")
        finally:
            os.unlink(tmp_path)

    return _deduplicate_products(all_products)


def parse_quote_msg(msg_path: str, *, depth: int = 0) -> list[dict]:
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
        all_products = _call_openai(context) if context.strip() else []

        for attachment in getattr(message, "attachments", []) or []:
            filename = (
                getattr(attachment, "longFilename", None)
                or getattr(attachment, "shortFilename", None)
                or getattr(attachment, "name", None)
                or "attachment"
            )
            data = getattr(attachment, "data", None)
            ext = os.path.splitext(str(filename))[1].lower()
            if (
                ext not in {".pdf", ".txt", ".csv", ".xlsx", ".eml", ".msg"}
                or not isinstance(data, (bytes, bytearray))
                or len(data) > MAX_QUOTE_FILE_BYTES
                or (ext in {".eml", ".msg"} and depth >= MAX_NESTED_EMAIL_DEPTH)
            ):
                continue
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                all_products.extend(parse_quote_file(tmp_path, _depth=depth + 1))
            except Exception as exc:
                print(f"[quote_parser] Error parsing .msg attachment {filename}: {exc}")
            finally:
                os.unlink(tmp_path)
        return _deduplicate_products(all_products)
    finally:
        message.close()


def parse_quote_text(text_path: str) -> list[dict]:
    """Parse a plain-text vendor response."""
    with open(text_path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.read(MAX_AI_TEXT_CHARS + 1)
    return _call_openai(content) if content.strip() else []


def parse_quote_file(file_path: str, *, _depth: int = 0) -> list[dict]:
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
        return parse_quote_eml(file_path, depth=_depth)
    if ext == ".msg":
        return parse_quote_msg(file_path, depth=_depth)
    if ext == ".pdf":
        return parse_quote_pdf(file_path)
    if ext == ".txt":
        return parse_quote_text(file_path)
    if ext in (".csv", ".xlsx"):
        return parse_quote_spreadsheet(file_path)
    raise ValueError(f"Unsupported file type: {ext}. Expected .eml, .msg, .pdf, .txt, .csv, or .xlsx")
