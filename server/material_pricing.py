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


PIECE_PRICED_TRANSITION_SOURCES = frozenset({"price_book", "default_rule"})


def is_piece_priced_transition(line: dict) -> bool:
    """Transition line whose unit_price is per stick (transition rule or price book)."""
    return (
        str(line.get("material_type") or "").strip().lower() == "transitions"
        and str(line.get("price_source") or "").strip().lower() in PIECE_PRICED_TRANSITION_SOURCES
    )


def transition_pieces(order_qty_lf, vendor, fixture_count) -> int:
    """Whole sticks for a piece-priced transition line (Silver Pin=12', Schluter=8'2").
    Fixture sides (2 per fixture) apply to Schluter only. Same rule as the
    materials editor's transitionPiecesFromLf and PUT /materials."""
    order_qty = _number(order_qty_lf)
    vendor_name = str(vendor or "").lower()
    stick_lf = SILVER_PIN_STICK_LF if "silver pin" in vendor_name else SCHLUTER_STICK_LF
    if order_qty <= 0:
        return 0
    fixtures = _number(fixture_count) if vendor_name == "schluter" else 0.0
    if fixtures.is_integer():
        fixtures = int(fixtures)
    if fixtures > 0:
        sides = 2
        lf_per_side = order_qty / (fixtures * sides)
        return fixtures * sides * math.ceil(lf_per_side / stick_lf)
    return math.ceil(order_qty / stick_lf)


def order_qty_is_lf(line: dict, order_qty) -> bool:
    """True when order_qty equals the line's LF figure, installed_qty x (1 + waste_pct).
    The old editor reset order_qty to that LF value on every edit, even on EA
    transition lines, so on an EA line such a value is LF, not a stick count."""
    lf_qty = round(_number(line.get("installed_qty")), 4) * (1 + round(_number(line.get("waste_pct")), 4))
    return abs(round(_number(order_qty), 4) - round(lf_qty, 2)) <= 0.01


def order_qty_holds_sticks(line: dict) -> bool:
    """EA transition row whose stored order_qty is a whole-stick count
    (not the LF figure the old editor saved on EA rows)."""
    order_qty = line.get("order_qty")
    return (
        str(line.get("unit") or "").strip().upper() == "EA"
        and order_qty is not None
        and not order_qty_is_lf(line, order_qty)
    )


def transition_pricing_pieces(line: dict, order_qty) -> int | float:
    """Sticks billed on a piece-priced transition line for the given order_qty:
    the stored stick count on an EA stick row, else sticks counted from LF."""
    if order_qty_holds_sticks(line):
        return _number(order_qty)
    return transition_pieces(order_qty, line.get("vendor"), line.get("fixture_count"))


def material_pricing_context(line: dict) -> dict:
    """Return the deterministic quantity/formula used to verify a material total.

    Historical transition rows used two storage conventions: some retained LF in
    ``order_qty`` while pricing full sticks, and some stored the stick count
    directly. An EA row that stores sticks (order_qty_holds_sticks) is priced by
    that count; any other row by sticks counted from its LF, where an older stick
    length is accepted only when the saved extended cost proves it. New
    calculations continue to expose the selected basis in their audit inputs.
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

    if not is_piece_priced_transition(line):
        return default

    # An EA row that stores sticks is billed order_qty x unit_price by PUT
    # /materials, the bid assembler and the materials editor, so that is its only
    # valid total; the LF-derived stick counts below apply to rows holding LF.
    if order_qty_holds_sticks(line):
        return {
            **default,
            "basis": "stored_transition_pieces",
            "pricing_unit": "EA",
        }

    vendor = str(line.get("vendor") or "").strip().lower()
    primary_length = SILVER_PIN_STICK_LF if "silver pin" in vendor else SCHLUTER_STICK_LF
    unit_price_input = round(unit_price, 4)

    # The current stick count first (same rule as PUT /materials, the materials
    # editor and the bid assembler), so it is the formula reported when no
    # saved total matches.
    current_pieces = transition_pieces(order_qty, line.get("vendor"), line.get("fixture_count"))
    candidates = [{
        "basis": "transition_sticks",
        "formula": "transition_pieces(order_qty, vendor, fixture_count) * unit_price",
        "pricing_quantity": current_pieces,
        "pricing_unit": "EA",
        "expected_cost": round(current_pieces * unit_price, 2),
        "inputs": {
            "order_qty": round(order_qty, 4),
            "vendor": line.get("vendor") or "",
            "fixture_count": int(_number(line.get("fixture_count"))),
            "piece_lf": round(primary_length, 4),
            "piece_count": current_pieces,
            "unit_price": unit_price_input,
        },
    }]

    # Older stick counts, still accepted when the saved total proves them.
    lengths = [primary_length]
    if primary_length == SCHLUTER_STICK_LF:
        lengths.append(SCHLUTER_LEGACY_STICK_LF)
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
                "unit_price": unit_price_input,
            },
        }
        if not any(existing["expected_cost"] == candidate["expected_cost"] for existing in candidates):
            candidates.append(candidate)

    for candidate in candidates:
        if abs(candidate["expected_cost"] - actual_cost) <= 0.02:
            return candidate
    return candidates[0]
