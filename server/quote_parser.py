"""
Parse vendor quotes from .eml and .pdf files.
Uses pdfplumber for PDF text extraction and OpenAI GPT-5 Mini for structured parsing.
"""

import email
import json
import os
import tempfile
from email import policy
from typing import Optional

import pdfplumber
from openai import OpenAI


SYSTEM_PROMPT = """You are a flooring vendor quote parser. Extract product pricing from the vendor quote text.
Return a JSON object with a "products" array. Each product should have:
- vendor: string (company name of the vendor)
- product_name: string (full product name / style / color)
- unit_price: number (price per unit)
- unit: string (SF, SY, LF, EA, etc.)
- freight: number or null (freight cost per unit if mentioned)
- lead_time: string or null (delivery lead time if mentioned)
- notes: string or null (any special notes, minimums, conditions)

If you cannot determine a field, set it to null.
Only return the JSON object, no other text."""


def _extract_pdf_text(pdf_path: str) -> str:
    """Extract all text from a PDF file using pdfplumber."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


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


def _call_openai(quote_text: str) -> list[dict]:
    """Send extracted text to OpenAI GPT-5 Mini and parse the structured response."""
    client = OpenAI()  # uses OPENAI_API_KEY env var
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": quote_text},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    parsed = json.loads(content)
    return parsed.get("products", [])


def parse_quote_pdf(pdf_path: str) -> list[dict]:
    """Parse a vendor quote from a PDF file."""
    text = _extract_pdf_text(pdf_path)
    if not text.strip():
        return []
    return _call_openai(text)


def parse_quote_eml(eml_path: str) -> list[dict]:
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
        except Exception:
            pass  # Body might not contain pricing

    # Process PDF attachments
    for att in eml_data["attachments"]:
        if att["content_type"] == "application/pdf" or (
            att["filename"] and att["filename"].lower().endswith(".pdf")
        ):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(att["data"])
                tmp_path = tmp.name
            try:
                products = parse_quote_pdf(tmp_path)
                all_products.extend(products)
            finally:
                os.unlink(tmp_path)

    return all_products


def parse_quote_file(file_path: str) -> list[dict]:
    """Auto-detect file type and parse accordingly."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".eml":
        return parse_quote_eml(file_path)
    elif ext == ".pdf":
        return parse_quote_pdf(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Expected .eml or .pdf")
