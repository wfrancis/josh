"""Shared proposal arithmetic for generation, save, replay, and PDF checks."""

from __future__ import annotations

import math


def money(value) -> float:
    try:
        number = float(value or 0)
        return round(number, 2) if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def number(value) -> float:
    try:
        value = float(value or 0)
        return value if math.isfinite(value) else 0.0
    except (TypeError, ValueError):
        return 0.0


def effective_bundle_total(bundle: dict) -> float:
    value = bundle.get("price_override")
    return money(value if value is not None else bundle.get("total_price"))


def _allocate_money(total, weights: list[float]) -> list[float]:
    """Allocate whole cents by largest remainder so bundle sums stay exact."""
    total_cents = int(round(money(total) * 100))
    normalized = [max(number(weight), 0.0) for weight in weights]
    weight_total = sum(normalized)
    if total_cents <= 0 or weight_total <= 0:
        return [0.0 for _ in normalized]

    raw_cents = [total_cents * weight / weight_total for weight in normalized]
    allocated = [int(value) for value in raw_cents]
    remainder = total_cents - sum(allocated)
    order = sorted(
        range(len(normalized)),
        key=lambda index: (raw_cents[index] - allocated[index], -index),
        reverse=True,
    )
    for index in order[:remainder]:
        allocated[index] += 1
    return [cents / 100 for cents in allocated]


def normalize_proposal_totals(proposal: dict) -> dict:
    """Mutate a proposal into the one canonical estimator/PDF total contract.

    Bundle ``total_price`` is the calculated tax-inclusive amount. A
    ``price_override`` is the accepted tax-inclusive amount and changes the
    proposal subtotal/grand total without pretending the raw engine produced it.
    """
    bundles = [bundle for bundle in (proposal.get("bundles") or []) if isinstance(bundle, dict)]
    tax_rate = number(proposal.get("tax_rate"))
    gpm_pct = number(proposal.get("gpm_pct"))

    bundle_costs = [
        money(
            money(bundle.get("material_cost"))
            + money(bundle.get("sundry_cost"))
            + money(bundle.get("labor_cost"))
            + money(bundle.get("freight_override") if bundle.get("freight_override") is not None else bundle.get("freight_cost"))
        )
        for bundle in bundles
    ]
    total_cost = money(sum(bundle_costs))
    if 0 < gpm_pct < 1 and total_cost > 0:
        gpm_profit = money(total_cost / (1 - gpm_pct) - total_cost)
        gpm_labor = money(gpm_profit * 0.9793)
        gpm_material = money(gpm_profit - gpm_labor)
    else:
        gpm_profit = gpm_labor = gpm_material = 0.0
    labor_allocations = _allocate_money(gpm_labor, bundle_costs)
    material_allocations = _allocate_money(gpm_material, bundle_costs)

    calculated_total = 0.0
    accepted_total = 0.0
    taxable_total = 0.0
    tax_total = 0.0
    for index, bundle in enumerate(bundles):
        bundle["material_cost"] = money(bundle.get("material_cost"))
        bundle["sundry_cost"] = money(bundle.get("sundry_cost"))
        bundle["labor_cost"] = money(bundle.get("labor_cost"))
        bundle["freight_cost"] = money(bundle.get("freight_cost"))
        freight = money(bundle.get("freight_override") if bundle.get("freight_override") is not None else bundle.get("freight_cost"))
        bundle_cost = bundle_costs[index]
        bundle["gpm_labor_adder"] = labor_allocations[index]
        bundle["gpm_material_adder"] = material_allocations[index]
        bundle["gpm_adder"] = money(bundle["gpm_labor_adder"] + bundle["gpm_material_adder"])
        bundle["taxable"] = money(
            money(bundle.get("material_cost"))
            + money(bundle.get("sundry_cost"))
            + freight
            + bundle["gpm_material_adder"]
        )
        bundle["tax_amount"] = money(bundle["taxable"] * tax_rate)
        bundle["total_price"] = money(bundle_cost + bundle["gpm_adder"] + bundle["tax_amount"])

        calculated_total = money(calculated_total + bundle["total_price"])
        accepted_total = money(accepted_total + effective_bundle_total(bundle))
        taxable_total = money(taxable_total + bundle["taxable"])
        tax_total = money(tax_total + bundle["tax_amount"])

    manual_adjustment = money(accepted_total - calculated_total)
    subtotal = money(accepted_total - tax_total)
    textura_enabled = bool(int(number(proposal.get("textura_fee"))))
    textura_amount = money(min(round(accepted_total * 0.0022, 2), 5000.0) if textura_enabled else 0.0)
    proposal.update({
        "bundles": bundles,
        "taxable": taxable_total,
        "gpm_profit": gpm_profit,
        "gpm_labor": gpm_labor,
        "gpm_material": gpm_material,
        "manual_adjustment": manual_adjustment,
        "subtotal": subtotal,
        "tax_amount": tax_total,
        "textura_amount": textura_amount,
        "grand_total": money(accepted_total + textura_amount),
    })
    return proposal
