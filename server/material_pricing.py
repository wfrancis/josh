"""Shared material line arithmetic for calculators, audits, and readiness."""

from __future__ import annotations

import math


SCHLUTER_STICK_LF = 8.0 + 2.0 / 12.0
SCHLUTER_LEGACY_STICK_LF = 8.208
SILVER_PIN_STICK_LF = 12.0


def _number(value) -> float:
    try:
        number = float(value or 0)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def transition_piece_count(order_qty_lf, fixture_count=0, piece_lf=SCHLUTER_STICK_LF) -> int:
    """Convert transition LF to purchasable sticks, respecting fixture cut waste."""
    order_qty = _number(order_qty_lf)
    fixtures = max(0, int(_number(fixture_count)))
    length = _number(piece_lf)
    if order_qty <= 0 or length <= 0:
        return 0
    if fixtures:
        sides = 2
        lf_per_side = order_qty / (fixtures * sides)
        return fixtures * sides * math.ceil(lf_per_side / length)
    return math.ceil(order_qty / length)


def material_pricing_context(line: dict) -> dict:
    """Return the deterministic quantity/formula used to verify a material total.

    Historical transition rows used two storage conventions: some retained LF in
    ``order_qty`` while pricing full sticks, and some stored the stick count
    directly. We accept either only when the saved extended cost proves one of
    those exact formulas. New calculations continue to expose the selected basis
    in their audit inputs.
    """
    order_qty = _number(
        line.get("order_qty")
        if line.get("order_qty") is not None
        else line.get("installed_qty")
    )
    unit_price = _number(line.get("unit_price"))
    actual_cost = round(_number(line.get("extended_cost")), 2)
    default = {
        "basis": "order_quantity",
        "formula": "order_qty * unit_price",
        "pricing_quantity": order_qty,
        "pricing_unit": line.get("unit") or "",
        "expected_cost": round(order_qty * unit_price, 2),
        "inputs": {
            "order_qty": round(order_qty, 4),
            "unit_price": round(unit_price, 4),
        },
    }

    material_type = str(line.get("material_type") or "").strip().lower()
    price_source = str(line.get("price_source") or "").strip().lower()
    if material_type != "transitions" or price_source not in {"price_book", "default_rule"}:
        return default

    vendor = str(line.get("vendor") or "").strip().lower()
    primary_length = SILVER_PIN_STICK_LF if "silver pin" in vendor else SCHLUTER_STICK_LF
    lengths = [primary_length]
    if primary_length == SCHLUTER_STICK_LF:
        lengths.append(SCHLUTER_LEGACY_STICK_LF)

    candidates = []
    for piece_lf in lengths:
        pieces = transition_piece_count(order_qty, line.get("fixture_count"), piece_lf)
        candidate = {
            "basis": "transition_sticks",
            "formula": "transition_piece_count(order_qty, fixture_count, piece_lf) * unit_price",
            "pricing_quantity": pieces,
            "pricing_unit": "EA",
            "expected_cost": round(pieces * unit_price, 2),
            "inputs": {
                "order_qty": round(order_qty, 4),
                "fixture_count": int(_number(line.get("fixture_count"))),
                "piece_lf": round(piece_lf, 4),
                "piece_count": pieces,
                "unit_price": round(unit_price, 4),
            },
        }
        if not any(existing["expected_cost"] == candidate["expected_cost"] for existing in candidates):
            candidates.append(candidate)

    # A legacy importer sometimes converted order_qty to pieces before saving.
    # Prefer that direct convention only when its complete arithmetic matches.
    if abs(default["expected_cost"] - actual_cost) <= 0.02:
        return {
            **default,
            "basis": "stored_transition_pieces",
            "pricing_unit": "EA",
        }
    for candidate in candidates:
        if abs(candidate["expected_cost"] - actual_cost) <= 0.02:
            return candidate
    return candidates[0] if candidates else default
