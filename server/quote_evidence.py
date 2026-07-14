"""Conservative, read-only checks for vendor quote price evidence."""

from __future__ import annotations

import math
import re


_ITEM_CODE_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{1,5})[\s-]?(\d{2,4}(?:\.\d+)?)(?![A-Z0-9])",
    re.IGNORECASE,
)

_UNIT_ALIASES = {
    "SF": "SF",
    "SQFT": "SF",
    "SQ FT": "SF",
    "SQUARE FEET": "SF",
    "SY": "SY",
    "SQYD": "SY",
    "SQ YD": "SY",
    "SQUARE YARDS": "SY",
    "LF": "LF",
    "LINEAR FEET": "LF",
    "EA": "EA",
    "EACH": "EA",
    "CTN": "CTN",
    "CARTON": "CTN",
    "BOX": "CTN",
}


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _unit(value) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip().upper())
    return _UNIT_ALIASES.get(raw, raw)


def normalize_quote_unit(value) -> str:
    """Return the canonical unit used by evidence comparisons and decisions."""
    return _unit(value)


def extract_item_code_tokens(value: str | None) -> set[str]:
    """Return normalized product codes without allowing T-100 to match ST-100."""
    return {
        f"{prefix.upper()}{number.upper()}"
        for prefix, number in _ITEM_CODE_RE.findall(str(value or ""))
    }


def find_verified_quote_price_conflicts(
    materials: list[dict],
    quotes: list[dict],
    verified_source_hashes: set[str],
    *,
    price_tolerance: float = 0.005,
) -> list[dict]:
    """Find exact-code price conflicts without changing any accepted value.

    A row is returned only when the material has no intact selected receipt,
    the quote artifact is verified, the item code appears explicitly in the
    quote product text, and the units are directly comparable. The check is
    deliberately source-agnostic so relabeling a conflicting accepted price as
    "manual" cannot hide newer exact-code evidence.
    """
    verified_hashes = {str(value or "").strip() for value in verified_source_hashes} - {""}
    quote_candidates: list[dict] = []
    seen_quote_rows: set[tuple] = set()
    for quote in quotes or []:
        if not isinstance(quote, dict):
            continue
        source_hash = str(quote.get("source_hash") or quote.get("_source_hash") or "").strip()
        price = _number(quote.get("unit_price"))
        unit = _unit(quote.get("unit"))
        if source_hash not in verified_hashes or price is None or price <= 0 or not unit:
            continue
        text = " ".join(
            str(quote.get(field) or "")
            for field in ("product_name", "description", "notes")
        )
        codes = extract_item_code_tokens(text)
        if not codes:
            continue
        dedupe_key = (
            source_hash,
            round(price, 6),
            unit,
            str(quote.get("file_name") or ""),
            tuple(sorted(codes)),
        )
        if dedupe_key in seen_quote_rows:
            continue
        seen_quote_rows.add(dedupe_key)
        quote_candidates.append({
            "codes": codes,
            "source_hash": source_hash,
            "source_file": str(quote.get("file_name") or "").strip(),
            "vendor": str(quote.get("vendor") or "").strip(),
            "quote_price": price,
            "quote_unit": unit,
            "product_name": str(quote.get("product_name") or "").strip(),
        })

    conflicts: list[dict] = []
    seen_conflicts: set[tuple] = set()
    for material in materials or []:
        if not isinstance(material, dict):
            continue
        linked_hash = str(material.get("quote_source_hash") or "").strip()
        if linked_hash in verified_hashes:
            continue
        accepted_price = _number(material.get("unit_price"))
        accepted_unit = _unit(material.get("unit"))
        material_codes = extract_item_code_tokens(material.get("item_code"))
        if accepted_price is None or accepted_price <= 0 or not accepted_unit or not material_codes:
            continue

        for quote in quote_candidates:
            matched_codes = sorted(material_codes & quote["codes"])
            if not matched_codes or accepted_unit != quote["quote_unit"]:
                continue
            delta = round(quote["quote_price"] - accepted_price, 2)
            if abs(quote["quote_price"] - accepted_price) <= price_tolerance:
                continue
            dedupe_key = (
                material.get("id"),
                quote["source_hash"],
                round(quote["quote_price"], 6),
                quote["quote_unit"],
            )
            if dedupe_key in seen_conflicts:
                continue
            seen_conflicts.add(dedupe_key)
            conflicts.append({
                "material_id": material.get("id"),
                "item_code": material.get("item_code") or material.get("description") or "material",
                "description": material.get("description") or "",
                "accepted_price": round(accepted_price, 2),
                "accepted_unit": accepted_unit,
                "accepted_source": str(material.get("price_source") or "").strip().lower(),
                "quote_price": round(quote["quote_price"], 2),
                "quote_unit": quote["quote_unit"],
                "delta": delta,
                "source_hash": quote["source_hash"],
                "source_file": quote["source_file"],
                "vendor": quote["vendor"],
                "product_name": quote["product_name"],
                "matched_code": matched_codes[0],
                "match_basis": "exact_item_code",
                "status": "conflict",
            })

    conflicts.sort(key=lambda row: (-abs(row["delta"]), str(row["item_code"])))
    return conflicts
