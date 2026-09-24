"""Pure readiness checks used by the API and estimator trust UI.

Every message here is read by estimators, not engineers: say what is wrong in
their words and exactly what to click. Each check can carry an ``action``
(the button the page shows next to it) and ``technical`` (shown only under
"Technical details", never in the to-do list).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from material_pricing import material_pricing_context
from rfms_parser import VALID_MATERIAL_TYPES


VALID_MATERIAL_CLASSIFICATIONS = frozenset(VALID_MATERIAL_TYPES)

# Where each fix happens, in the words the page uses.
REVIEW_STEP = "the Review & Generate step"
TAKEOFF_STEP = "the Takeoff & Pricing step"
CLICK_REGENERATE = f"Click Regenerate on {REVIEW_STEP} to update the numbers."
NO_BID_YET = f"There's no bid yet. Open {REVIEW_STEP} to make one."

# Buttons the readiness card can show next to a check (id -> button text).
ACTIONS = {
    "job_details": "Edit job details",
    "materials": "Go to materials",
    "price_lines": "Go to materials",
    "quotes": "Fix quote prices",
    "proposal": "Open Review & Generate",
    "regenerate": "Regenerate",
    "make_pdf": "Make PDF",
    "labor_prices": "Open labor prices",
}

JOB_FIELD_LABELS = {
    "project_name": "project name",
    "gc_name": "general contractor",
    "salesperson": "salesperson",
}

# Plain words for the amounts on a bid.
AMOUNT_WORDS = {
    "tax_rate": "tax rate",
    "gpm_pct": "GPM %",
    "subtotal": "subtotal",
    "tax_amount": "tax",
    "grand_total": "total",
    "gpm_profit": "GPM",
    "gpm_labor": "labor GPM",
    "gpm_material": "material GPM",
    "textura_amount": "Textura fee",
    "manual_adjustment": "price adjustment",
    "material_cost": "material cost",
    "sundry_cost": "sundries cost",
    "labor_cost": "labor cost",
    "freight_cost": "freight",
    "gpm_labor_adder": "labor GPM",
    "gpm_material_adder": "material GPM",
    "gpm_adder": "GPM",
    "taxable": "taxable amount",
    "total_price": "price",
    "price_override": "price you typed",
    "freight_override": "freight you typed",
    "total_cost": "total cost",
    "markup_amount": "markup",
}

# Kept word for word by scripts/rules_audit_harness.py and the cent probe in main.py.
GRAND_TOTAL_MISMATCH = "The total doesn't equal the subtotal plus tax and Textura fee."


def amount_word(field: str) -> str:
    return AMOUNT_WORDS.get(field, str(field).replace("_", " "))


def plain_list(items, limit: int = 5) -> str:
    """'A', 'A and B', 'A, B and C', 'A, B, C, D, E and 3 more'."""
    items = [str(item) for item in items if str(item or "").strip()]
    if not items:
        return ""
    shown = items[:limit]
    extra = len(items) - len(shown)
    if extra:
        return f"{', '.join(shown)} and {extra} more"
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def money_text(value) -> str:
    return f"${_number(value):,.2f}"


def is_valid_material_classification(value) -> bool:
    return str(value or "").strip().lower() in VALID_MATERIAL_CLASSIFICATIONS


def _number(value) -> float:
    try:
        number = float(value or 0)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _finite_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _money_differs(left, right) -> bool:
    """Compare currency as integer cents so one-cent drift is never hidden."""
    return int(round(_number(left) * 100)) != int(round(_number(right) * 100))


def _plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


_DOESNT, _DONT, _ISNT, _ARENT = "doesn't", "don't", "isn't", "aren't"


def _verb(count: int, one: str, many: str) -> str:
    """'needs' / 'need': the verb that goes with ``count``."""
    return one if count == 1 else many


def _check(check_id: str, status: str, message: str, affected_items=None, *,
           action: str | None = None, technical: bool = False) -> dict:
    result = {
        "id": check_id,
        "status": status,
        "message": message,
        "affected_items": affected_items or [],
        "technical": technical,
        "action": {"id": action, "label": ACTIONS[action]} if action and status != "pass" else None,
        # Another failing check that already tells the estimator what to do
        # about this one; the page lists only that one.
        "covered_by": None,
    }
    return result


def _mark_covered_checks(checks: list[dict]) -> None:
    by_id = {check["id"]: check for check in checks}

    def failing(check_id: str) -> bool:
        return (by_id.get(check_id) or {}).get("status") == "fail"

    # "The price of X changed after this bid was made" already says Regenerate.
    if failing("current_audit") and failing("proposal_source_values"):
        by_id["current_audit"]["covered_by"] = "proposal_source_values"
    # A new PDF only helps once the bid itself is fixed: list that fix alone.
    pdf = by_id.get("proposal_pdf")
    if pdf and pdf["status"] == "fail":
        for check_id in ("proposal_source_values", "current_audit"):
            if failing(check_id):
                pdf["covered_by"] = check_id
                break
    files = by_id.get("durable_artifacts")
    if files and files["status"] == "fail" and files["affected_items"]:
        covering = set()
        for item in files["affected_items"]:
            text = str(item)
            # Wording from main._artifact_readiness.
            if text.startswith("The proposal PDF") and failing("proposal_pdf"):
                covering.add("proposal_pdf")
            elif "priced from a vendor quote" in text and failing("vendor_quote_evidence"):
                covering.add("vendor_quote_evidence")
            else:
                covering = set()
                break
        if covering:
            files["covered_by"] = sorted(covering)[0]


def proposal_math_errors(proposal: dict) -> list[str]:
    """Plain-English reasons the bid's numbers don't add up (empty when they do)."""
    bundles = [b for b in (proposal.get("bundles") or []) if isinstance(b, dict)]
    errors = []
    for field in (
        "tax_rate", "gpm_pct", "subtotal", "tax_amount", "grand_total",
        "gpm_profit", "gpm_labor", "gpm_material", "textura_amount",
    ):
        if _finite_number(proposal.get(field)) is None:
            errors.append(f"The bid's {amount_word(field)} is not a valid number.")
    if proposal.get("manual_adjustment") is not None and _finite_number(proposal.get("manual_adjustment")) is None:
        errors.append(f"The bid's {amount_word('manual_adjustment')} is not a valid number.")
    tax_rate = _number(proposal.get("tax_rate"))
    gpm_pct = _number(proposal.get("gpm_pct"))
    if tax_rate < 0 or tax_rate > 1:
        errors.append("Tax rate must be between 0% and 100%.")
    if gpm_pct < 0 or gpm_pct >= 1:
        errors.append("GPM must be at least 0% and less than 100%.")
    for index, bundle in enumerate(bundles):
        name = bundle.get("bundle_name") or f"Bundle {index + 1}"
        for field in (
            "material_cost", "sundry_cost", "labor_cost", "freight_cost",
            "gpm_labor_adder", "gpm_material_adder", "gpm_adder", "taxable",
            "tax_amount", "total_price",
        ):
            value = _finite_number(bundle.get(field))
            if value is None:
                errors.append(f"{name}: the {amount_word(field)} is not a valid number.")
            elif value < 0:
                errors.append(f"{name}: the {amount_word(field)} can't be negative.")
        for field in ("price_override", "freight_override"):
            if bundle.get(field) is None:
                continue
            value = _finite_number(bundle.get(field))
            if value is None:
                errors.append(f"{name}: the {amount_word(field)} is not a valid number.")
            elif value < 0:
                errors.append(f"{name}: the {amount_word(field)} can't be negative.")
        material = _number(bundle.get("material_cost"))
        sundry = _number(bundle.get("sundry_cost"))
        labor = _number(bundle.get("labor_cost"))
        freight = _number(bundle.get("freight_override") if bundle.get("freight_override") is not None else bundle.get("freight_cost"))
        gpm_labor = _number(bundle.get("gpm_labor_adder"))
        gpm_material = _number(bundle.get("gpm_material_adder"))
        expected_gpm = round(gpm_labor + gpm_material, 2)
        expected_taxable = round(material + sundry + freight + gpm_material, 2)
        expected_tax = round(expected_taxable * tax_rate, 2)
        expected_total = round(material + sundry + labor + freight + expected_gpm + expected_tax, 2)

        material_lines = [line for line in (bundle.get("materials") or []) if isinstance(line, dict)]
        sundry_lines = [line for line in (bundle.get("sundry_items") or []) if isinstance(line, dict)]
        labor_lines = [line for line in (bundle.get("labor_items") or []) if isinstance(line, dict)]
        if not bundle.get("is_derived"):
            material_line_total = round(sum(_number(line.get("extended_cost")) for line in material_lines), 2)
            sundry_line_total = round(sum(_number(line.get("extended_cost")) for line in sundry_lines), 2)
            if _money_differs(material_line_total, material):
                errors.append(f"{name}: the material lines don't add up to the material cost.")
            if _money_differs(sundry_line_total, sundry):
                errors.append(f"{name}: the sundry lines don't add up to the sundries cost.")
        labor_line_total = round(sum(_number(line.get("extended_cost")) for line in labor_lines), 2)
        if _money_differs(labor_line_total, labor):
            errors.append(f"{name}: the labor lines don't add up to the labor cost.")

        for line_index, line in enumerate(material_lines):
            quantity_value = line.get("order_qty") if line.get("order_qty") is not None else line.get("installed_qty")
            for field, value in (("quantity", quantity_value), ("unit price", line.get("unit_price")), ("amount", line.get("extended_cost"))):
                number = _finite_number(value)
                if number is None:
                    errors.append(f"{name}, material line {line_index + 1}: the {field} is not a valid number.")
                elif number < 0:
                    errors.append(f"{name}, material line {line_index + 1}: the {field} can't be negative.")
            pricing = material_pricing_context(line)
            expected_line = pricing["expected_cost"]
            if _money_differs(expected_line, line.get("extended_cost")):
                errors.append(
                    f"{name}, material line {line_index + 1}: the amount doesn't match its "
                    f"quantity and {pricing['basis'].replace('_', ' ')} price."
                )
        for line_index, line in enumerate(sundry_lines):
            for field, value in (("quantity", line.get("qty")), ("unit price", line.get("unit_price")), ("amount", line.get("extended_cost"))):
                number = _finite_number(value)
                if number is None:
                    errors.append(f"{name}, sundry line {line_index + 1}: the {field} is not a valid number.")
                elif number < 0:
                    errors.append(f"{name}, sundry line {line_index + 1}: the {field} can't be negative.")
            expected_line = round(_number(line.get("qty")) * _number(line.get("unit_price")), 2)
            if _money_differs(expected_line, line.get("extended_cost")):
                errors.append(f"{name}, sundry line {line_index + 1}: the amount doesn't equal quantity times price.")
        for line_index, line in enumerate(labor_lines):
            for field, value in (("quantity", line.get("qty")), ("rate", line.get("rate")), ("amount", line.get("extended_cost"))):
                number = _finite_number(value)
                if number is None:
                    errors.append(f"{name}, labor line {line_index + 1}: the {field} is not a valid number.")
                elif number < 0:
                    errors.append(f"{name}, labor line {line_index + 1}: the {field} can't be negative.")
            expected_line = round(_number(line.get("qty")) * _number(line.get("rate")), 2)
            if _money_differs(expected_line, line.get("extended_cost")):
                errors.append(f"{name}, labor line {line_index + 1}: the amount doesn't equal quantity times rate.")

        if _money_differs(expected_gpm, bundle.get("gpm_adder")):
            errors.append(f"{name}: the labor and material GPM don't add up to its GPM.")
        if _money_differs(expected_taxable, bundle.get("taxable")):
            errors.append(f"{name}: the taxable amount doesn't add up.")
        if _money_differs(expected_tax, bundle.get("tax_amount")):
            errors.append(f"{name}: the tax doesn't match the tax rate.")
        if _money_differs(expected_total, bundle.get("total_price")):
            errors.append(f"{name}: the price doesn't add up from its cost, GPM and tax.")
        accepted_total = bundle.get("price_override") if bundle.get("price_override") is not None else bundle.get("total_price")
        if _finite_number(accepted_total) is None or _number(accepted_total) <= 0:
            errors.append(f"{name} needs a price above $0.")

    bundle_total = round(sum(
        _number(b.get("price_override") if b.get("price_override") is not None else b.get("total_price"))
        for b in bundles
    ), 2)

    bundle_tax = round(sum(_number(b.get("tax_amount")) for b in bundles), 2)
    if _money_differs(bundle_tax, proposal.get("tax_amount")):
        errors.append("The bid's tax doesn't equal the tax on its bundles.")

    expected_before_textura = round(_number(proposal.get("subtotal")) + bundle_tax, 2)
    if _money_differs(bundle_total, expected_before_textura):
        errors.append("The bundle prices don't add up to the subtotal plus tax.")

    calculated_bundle_total = round(sum(_number(b.get("total_price")) for b in bundles), 2)
    expected_adjustment = round(bundle_total - calculated_bundle_total, 2)
    if _money_differs(expected_adjustment, proposal.get("manual_adjustment")):
        errors.append("The price adjustment doesn't match the bundle prices you typed.")

    expected_grand = round(_number(proposal.get("subtotal")) + bundle_tax + _number(proposal.get("textura_amount")), 2)
    if _money_differs(expected_grand, proposal.get("grand_total")):
        errors.append(GRAND_TOTAL_MISMATCH)

    expected_gpm = round(_number(proposal.get("gpm_labor")) + _number(proposal.get("gpm_material")), 2)
    if _money_differs(expected_gpm, proposal.get("gpm_profit")):
        errors.append("The labor and material GPM don't add up to the total GPM.")
    bundle_gpm_labor = round(sum(_number(bundle.get("gpm_labor_adder")) for bundle in bundles), 2)
    bundle_gpm_material = round(sum(_number(bundle.get("gpm_material_adder")) for bundle in bundles), 2)
    if _money_differs(bundle_gpm_labor, proposal.get("gpm_labor")):
        errors.append("The bundles' labor GPM doesn't add up to the bid's labor GPM.")
    if _money_differs(bundle_gpm_material, proposal.get("gpm_material")):
        errors.append("The bundles' material GPM doesn't add up to the bid's material GPM.")

    accepted_before_textura = round(_number(proposal.get("subtotal")) + bundle_tax, 2)
    expected_textura = round(min(accepted_before_textura * 0.0022, 5000), 2) if _number(proposal.get("textura_fee")) else 0.0
    if _money_differs(expected_textura, proposal.get("textura_amount")):
        errors.append("The Textura fee doesn't match the bid total.")
    return errors


def proposal_check_message(check: dict) -> tuple[str, str, str | None]:
    """(status, message, action) for the saved bid's numbers check.

    ``check`` comes from main._proposal_check_status: its ``kind`` says whether
    the bid is current, only needs the automatic recheck after an app update,
    or needs the estimator to act.
    """
    kind = (check or {}).get("kind")
    if kind == "current":
        return "pass", "The bid's numbers are up to date.", None
    if kind == "tool_updated":
        return (
            "pass",
            "The app or its rates were updated after this bid was saved. The numbers will be "
            "rechecked automatically when you make the PDF.",
            None,
        )
    if kind == "totals_changed":
        return "fail", totals_changed_message(check.get("old_total"), check.get("new_total")), "proposal"
    if kind == "job_changed":
        if check.get("detail"):
            # A material the bid copies changed (the message names it).
            return "fail", str(check["detail"]), "regenerate"
        changes = check.get("changes") or []
        return "fail", job_changed_message(changes, guessed=bool(check.get("guessed"))), job_changed_action(changes)
    if kind == "no_proposal":
        return "fail", NO_BID_YET, "proposal"
    return (
        "fail",
        f"This bid's numbers haven't been saved yet. {CLICK_REGENERATE}",
        "regenerate",
    )


def totals_changed_message(old_total, new_total) -> str:
    """The app's math or rates changed so that the saved bid's amounts move.
    Generate PDF saves the bid with the new amounts first, so that is the fix."""
    if _money_differs(old_total, new_total):
        change = f"the total changes from {money_text(old_total)} to {money_text(new_total)}"
    else:
        change = f"some bundle amounts change (the total stays {money_text(old_total)})"
    return (
        f"The app's rates or math were updated after this bid was saved, so {change}. "
        f"Check the new total on {REVIEW_STEP}, then click Generate PDF."
    )


# Job details a bid's numbers are made from (see main._job_changes_since_bid),
# in the words the job details form uses.
JOB_INPUT_WORDS = {
    "tax_rate": "tax rate",
    "gpm_pct": "GPM",
    "textura_fee": "Textura fee",
    "unit_count": "unit count",
    "tub_shower_count": "total tubs/showers",
    "markup_pct": "markup",
    "sundries": "sundry lines",
    "labor": "labor lines",
}
_PERCENT_INPUTS = {"tax_rate", "gpm_pct", "markup_pct"}
# The box on the Review & Generate step that holds the bid's own value.
_BID_BOXES = {"tax_rate": "Tax", "gpm_pct": "GPM Profit"}


def _input_text(field: str, value) -> str:
    number = _number(value)
    if field in _PERCENT_INPUTS:
        return f"{round(number * 100, 2):g}%"
    return f"{round(number, 2):g}"


def job_changed_action(changes: list[dict]) -> str:
    """Regenerate when it brings the change into the bid; otherwise the fix is
    typed on the Review & Generate step (Regenerate keeps the bid's own tax
    rate, GPM and Textura fee)."""
    return "regenerate" if any(change.get("fix") == "regenerate" for change in changes) else "proposal"


def job_changed_message(changes: list[dict], *, guessed: bool = False) -> str:
    """Name what changed in the job after the bid was made, then the fix.

    ``changes`` come from main._job_changes_since_bid. ``guessed``: the bid
    was saved before bids kept what the job said, so only a difference between
    the job and the bid is known, not the job's old value.
    """
    said, fixes = [], []
    regenerate = [change for change in changes if change.get("fix") == "regenerate"]
    own = [change for change in changes if change.get("fix") != "regenerate"]
    for change in regenerate:
        field = change.get("field")
        word = JOB_INPUT_WORDS.get(field, str(field).replace("_", " "))
        if "before" in change and "after" in change:
            said.append(
                f"The job's {word} changed from {_input_text(field, change['before'])} to "
                f"{_input_text(field, change['after'])} after this bid was made."
            )
        else:
            said.append(f"The job's {word} changed after this bid was made.")
    if regenerate:
        fixes.append(CLICK_REGENERATE)
    for change in own:
        field = change.get("field")
        before, after, bid = change.get("before"), change.get("after"), change.get("bid")
        if field == "textura_fee":
            if _number(after):
                said.append(
                    "The job charges the Textura fee, but this bid doesn't."
                    if guessed else
                    "The job's Textura fee was turned on after this bid was made, but the bid doesn't charge it."
                )
                fixes.append(f"Turn on Textura on {REVIEW_STEP}, or turn the Textura fee off in the job details.")
            else:
                said.append(
                    "The job doesn't charge the Textura fee, but this bid does."
                    if guessed else
                    "The job's Textura fee was turned off after this bid was made, but the bid still charges it."
                )
                fixes.append(
                    f"Turn off Textura on {REVIEW_STEP}, or turn the Textura fee {'' if guessed else 'back '}on "
                    "in the job details."
                )
            continue
        word = JOB_INPUT_WORDS.get(field, str(field).replace("_", " "))
        new, used = _input_text(field, after), _input_text(field, bid)
        if guessed:
            said.append(f"The job's {word} is {new}, but this bid uses {used}.")
        else:
            said.append(
                f"The job's {word} changed from {_input_text(field, before)} to {new} after this bid "
                f"was made, but the bid uses {used}."
            )
        back = "back " if not guessed and not _money_differs(_number(before) * 100, _number(bid) * 100) else ""
        box = _BID_BOXES.get(field)
        typed = f"Type {new} in the {box} box on {REVIEW_STEP}" if box else f"Change it on {REVIEW_STEP}"
        fixes.append(f"{typed}, or change the job's {word} {back}to {used}.")
    if not said:
        return f"The job changed after this bid was made. {CLICK_REGENERATE}"
    shown = said[:3]
    if len(said) > 3:
        shown.append(f"{_plural(len(said) - 3, 'other detail')} changed too.")
    return " ".join(shown + fixes)


def evaluate_job_readiness(
    job: dict,
    *,
    latest_run: dict | None,
    current_ruleset_version: int | None,
    pdf_ready: bool,
    pdf_message: str | None,
    proposal_source_fingerprint: str | None,
    proposal_source_ok: bool = True,
    proposal_source_message: str | None = None,
    artifact_status: str = "pass",
    artifact_message: str | None = None,
    artifact_items: list | None = None,
    golden_status: str | None = None,
    golden_verification_status: str | None = None,
    current_replay_status: str | None = None,
    current_replay_drift_classification: str | None = None,
    labor_catalog_count: int = 0,
    labor_required_types: set[str] | frozenset[str] | None = None,
    build: dict | None = None,
    trust_summary: dict | None = None,
    proposal_check: dict | None = None,
) -> dict:
    """Evaluate whether a job is safe to send without changing any data."""
    checks = []
    proposal = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    trust = trust_summary or {}

    def material_key(material: dict) -> str:
        return str(
            material.get("item_code")
            or material.get("id")
            or material.get("material_id")
            or ""
        )

    raw_deleted_codes = {str(code) for code in (proposal.get("deleted_material_codes") or []) if code}
    deleted_reasons = proposal.get("deleted_material_reasons")
    if not isinstance(deleted_reasons, dict):
        deleted_reasons = {}
    deleted_codes = {
        code for code in raw_deleted_codes
        if str(deleted_reasons.get(code) or "").strip()
    }
    materials = [m for m in (job.get("materials") or []) if isinstance(m, dict)]
    active_materials = [m for m in materials if material_key(m) not in deleted_codes]

    missing_fields = [field for field in ("project_name", "gc_name", "salesperson") if not str(job.get(field) or "").strip()]
    missing_labels = [JOB_FIELD_LABELS[field] for field in missing_fields]
    checks.append(_check(
        "required_job_fields",
        "fail" if missing_fields else "pass",
        (
            "The project name, general contractor and salesperson are filled in."
            if not missing_fields
            else f"Fill in the {plain_list(missing_labels)} on the job. Click Edit job details at the top of the page."
        ),
        [label.capitalize() for label in missing_labels],
        action="job_details",
    ))

    current_build = build or {}
    required_build_fields = (
        "commit", "tag", "built_at", "environment", "engine_fingerprint",
        "config_fingerprint", "runtime_fingerprint", "frontend_asset",
        "frontend_fingerprint",
    )
    missing_build_fields = [
        field for field in required_build_fields
        if not str(current_build.get(field) or "").strip()
        or str(current_build.get(field)).strip().lower() == "unknown"
    ]
    # Never blocks sending: the numbers don't depend on the version label.
    checks.append(_check(
        "deployed_build_identity",
        "warn" if missing_build_fields else "pass",
        (
            "This copy of the app is labeled with its version."
            if not missing_build_fields
            else (
                "This copy of the app is missing its version label. Ask whoever installs app "
                "updates to fix it. Your numbers are not affected."
            )
        ),
        missing_build_fields,
        technical=True,
    ))

    unknown = [
        m.get("item_code") or m.get("description") or "material"
        for m in active_materials
        if not is_valid_material_classification(m.get("material_type"))
    ]
    checks.append(_check(
        "unknown_materials",
        "fail" if unknown else "pass",
        (
            "Every material has a type."
            if not unknown
            else f"{_plural(len(unknown), 'material')} {_verb(len(unknown), 'needs', 'need')} a type. Pick one in the Type column on {TAKEOFF_STEP}."
        ),
        unknown,
        action="materials",
    ))

    unpriced = [m.get("item_code") or m.get("description") or "material" for m in active_materials if _number(m.get("unit_price")) <= 0]
    checks.append(_check(
        "unpriced_materials",
        "fail" if unpriced else "pass",
        (
            "Every material has a price."
            if not unpriced
            else f"{_plural(len(unpriced), 'material')} still {_verb(len(unpriced), 'needs', 'need')} a price. Type a price on each line marked \"Needs price\" on {TAKEOFF_STEP}."
        ),
        unpriced,
        action="price_lines",
    ))

    required_labor_types = {
        str(value or "").strip().lower()
        for value in (labor_required_types or set())
        if str(value or "").strip()
    }

    def expects_labor(material: dict) -> bool:
        material_type = str(material.get("material_type") or "").strip().lower()
        if material_type not in required_labor_types:
            return False
        if material_type != "transitions":
            return True
        description = str(material.get("description") or "").lower()
        return any(term in description for term in ("schluter", "jolly", "exposed edge trim", "metal trim"))

    labor_expected = [material for material in active_materials if expects_labor(material)]
    catalog_missing = [
        material.get("item_code") or material.get("description") or "material"
        for material in labor_expected
    ] if labor_expected and labor_catalog_count <= 0 else []
    checks.append(_check(
        "labor_catalog",
        "fail" if catalog_missing else "pass",
        (
            "The labor price list is loaded."
            if not catalog_missing
            else (
                "The labor price list is empty, so installation can't be priced. Upload it on the "
                "Pricing & Rules page (Labor tab), then click Regenerate on the Review & Generate step."
            )
        ),
        catalog_missing,
        action="labor_prices",
    ))

    labor_rows = [
        item for item in (job.get("labor") or [])
        if isinstance(item, dict)
    ]
    proposal_labor_rows = [
        item
        for bundle in (proposal.get("bundles") or [])
        if isinstance(bundle, dict)
        for item in (bundle.get("labor_items") or [])
        if isinstance(item, dict)
    ]
    proposal_material_keys_by_id = {
        str(item.get("id")): material_key(item)
        for bundle in (proposal.get("bundles") or [])
        if isinstance(bundle, dict)
        for item in (bundle.get("materials") or [])
        if isinstance(item, dict)
        and item.get("id") is not None
        and material_key(item)
    }
    valid_labor_material_ids = {
        str(item.get("material_id"))
        for item in labor_rows
        if item.get("material_id") is not None
        and _number(item.get("qty")) > 0
        and _number(item.get("rate")) > 0
        and _number(item.get("extended_cost")) > 0
    }
    valid_proposal_labor_keys = {
        proposal_material_keys_by_id[str(item.get("material_id"))]
        for item in proposal_labor_rows
        if item.get("material_id") is not None
        and str(item.get("material_id")) in proposal_material_keys_by_id
        and _number(item.get("qty")) > 0
        and _number(item.get("rate")) > 0
        and _number(item.get("extended_cost")) > 0
    }
    missing_labor = [
        material.get("item_code") or material.get("description") or "material"
        for material in labor_expected
        if (
            (material.get("id") is None or str(material.get("id")) not in valid_labor_material_ids)
            and material_key(material) not in valid_proposal_labor_keys
        )
    ]
    checks.append(_check(
        "labor_coverage",
        "fail" if missing_labor else "pass",
        (
            "Every material that gets installed has labor."
            if not missing_labor
            else (
                f"{_plural(len(missing_labor), 'material')} {_verb(len(missing_labor), 'has', 'have')} no labor cost. Click Regenerate on "
                f"{REVIEW_STEP}, or add a labor line for each one there."
            )
        ),
        missing_labor,
        action="regenerate",
    ))

    historical_prices = [
        m.get("item_code") or m.get("description") or "material"
        for m in active_materials
        if str(m.get("price_source") or "").strip().lower() == "vendor_history"
    ]
    ai_estimates = [
        m.get("item_code") or m.get("description") or "material"
        for m in active_materials
        if str(m.get("price_source") or "").strip().lower() == "ai_estimate"
    ]
    missing_price_sources = [
        m.get("item_code") or m.get("description") or "material"
        for m in active_materials
        if _number(m.get("unit_price")) > 0
        and not str(m.get("price_source") or "").strip()
    ]
    price_evidence_items = [
        *(f"Past quote: {item}" for item in historical_prices),
        *(f"AI guess: {item}" for item in ai_estimates),
        *(f"Origin unknown: {item}" for item in missing_price_sources),
    ]
    checks.append(_check(
        "price_evidence",
        "warn" if price_evidence_items else "pass",
        (
            "Every price shows where it came from."
            if not price_evidence_items
            else (
                f"Double-check {_plural(len(price_evidence_items), 'price')} before sending: "
                f"{_verb(len(price_evidence_items), 'it', 'they')} came from a past quote or an AI guess, or "
                f"{_verb(len(price_evidence_items), _DOESNT, _DONT)} say where "
                f"{_verb(len(price_evidence_items), 'it', 'they')} came from."
            )
        ),
        price_evidence_items,
        action="materials",
    ))

    missing_vendor_receipts = int(_number(trust.get("missing_vendor_receipt_count")))
    vendor_conflicts = [
        row for row in (trust.get("vendor_price_conflicts") or [])
        if isinstance(row, dict)
    ]
    vendor_conflict_count = max(
        int(_number(trust.get("vendor_price_conflict_count"))),
        len(vendor_conflicts),
    )
    missing_vendor_files = [str(item) for item in (trust.get("quote_source_files_needed") or [])]
    vendor_evidence_failures = [
        *(row.get("item_code") or "material" for row in vendor_conflicts),
        *missing_vendor_files,
    ]
    vendor_evidence_blocked = bool(missing_vendor_receipts or vendor_conflict_count or missing_vendor_files)
    vendor_parts = []
    if missing_vendor_receipts:
        vendor_parts.append(
            f"{_plural(missing_vendor_receipts, 'vendor price')} {_verb(missing_vendor_receipts, _ISNT, _ARENT)} "
            f"linked to the quote file {_verb(missing_vendor_receipts, 'it', 'they')} came from"
        )
    if vendor_conflict_count:
        vendor_parts.append(
            f"{_plural(vendor_conflict_count, 'price')} {_verb(vendor_conflict_count, _DOESNT, _DONT)} "
            "match the vendor's quote (pick which price to use)"
        )
    if missing_vendor_files:
        vendor_parts.append(
            f"{_plural(len(missing_vendor_files), 'quote file')} "
            f"{_verb(len(missing_vendor_files), 'needs', 'need')} to be added again"
        )
    checks.append(_check(
        "vendor_quote_evidence",
        "fail" if vendor_evidence_blocked else "pass",
        (
            "Every vendor price matches its quote."
            if not vendor_evidence_blocked
            else (
                f"Vendor quote prices need attention: {'; '.join(vendor_parts)}. "
                "Click Fix quote prices to add the quote files, or Review on each price that differs."
            )
        ),
        vendor_evidence_failures,
        action="quotes",
    ))

    vendor_overrides = [
        row for row in (trust.get("vendor_price_overrides") or [])
        if isinstance(row, dict)
    ]
    vendor_override_count = max(
        int(_number(trust.get("vendor_price_override_count"))),
        len(vendor_overrides),
    )
    checks.append(_check(
        "vendor_price_overrides",
        "warn" if vendor_override_count else "pass",
        (
            "No kept price differs from its vendor quote."
            if not vendor_override_count
            else (
                f"{_plural(vendor_override_count, 'price')} {_verb(vendor_override_count, 'differs', 'differ')} from the "
                f"vendor's quote and {_verb(vendor_override_count, 'was', 'were')} kept on purpose. "
                f"Check {_verb(vendor_override_count, 'it', 'they')} {_verb(vendor_override_count, 'is', 'are')} still right."
            )
        ),
        [
            f"{row.get('item_code') or 'material'}: {row.get('reviewer_name') or 'reviewer'} - {row.get('reason') or 'reason recorded'}"
            for row in vendor_overrides
        ],
        action="materials",
    ))

    bundle_material_codes = {
        material_key(material)
        for bundle in (proposal.get("bundles") or [])
        if isinstance(bundle, dict)
        for material in (bundle.get("materials") or [])
        if isinstance(material, dict) and material_key(material)
    }
    contradictory_deleted_codes = sorted(raw_deleted_codes & bundle_material_codes)
    checks.append(_check(
        "deleted_material_conflicts",
        "fail" if contradictory_deleted_codes else "pass",
        (
            "No deleted material is still on the bid."
            if not contradictory_deleted_codes
            else f"Some materials are deleted but still show on the bid. Click Regenerate on {REVIEW_STEP} to clean this up."
        ),
        contradictory_deleted_codes,
        action="regenerate",
    ))
    missing_from_proposal = [
        m.get("item_code") or m.get("description") or "material"
        for m in active_materials
        if not material_key(m) or material_key(m) not in bundle_material_codes
    ]
    has_bundles = bool(proposal.get("bundles"))
    if has_bundles:
        coverage_message = (
            "Every material is on the bid."
            if not missing_from_proposal
            else (
                f"{_plural(len(missing_from_proposal), 'material')} {_verb(len(missing_from_proposal), _ISNT, _ARENT)} on the bid. Click Regenerate on "
                f"{REVIEW_STEP} to add them, or delete them there with a reason."
            )
        )
    else:
        coverage_message = NO_BID_YET
    checks.append(_check(
        "proposal_coverage",
        "fail" if (missing_from_proposal or not has_bundles) else "pass",
        coverage_message,
        missing_from_proposal,
        action="regenerate" if has_bundles else "proposal",
    ))
    checks.append(_check(
        "proposal_source_values",
        "pass" if proposal_source_ok else "fail",
        "The bid uses the current material quantities and prices." if proposal_source_ok else (
            proposal_source_message
            or f"Material quantities or prices changed after this bid was made. {CLICK_REGENERATE}"
        ),
        action="regenerate" if has_bundles else "proposal",
    ))
    missing_deletion_reasons = [code for code in sorted(raw_deleted_codes) if code not in deleted_codes]
    checks.append(_check(
        "deletion_reasons",
        "fail" if missing_deletion_reasons else "pass",
        (
            "Every deleted material has a reason."
            if not missing_deletion_reasons
            else f"Give a reason for each deleted material. Type it on each deleted line on {REVIEW_STEP}."
        ),
        missing_deletion_reasons,
        action="proposal",
    ))

    deleted_bundle_names = {str(name) for name in (proposal.get("deleted_bundles") or []) if name}
    deleted_bundle_reasons = proposal.get("deleted_bundle_reasons")
    if not isinstance(deleted_bundle_reasons, dict):
        deleted_bundle_reasons = {}
    missing_bundle_reasons = [
        name for name in sorted(deleted_bundle_names)
        if not str(deleted_bundle_reasons.get(name) or "").strip()
    ]
    checks.append(_check(
        "bundle_deletion_reasons",
        "fail" if missing_bundle_reasons else "pass",
        (
            "Every deleted bundle has a reason."
            if not missing_bundle_reasons
            else f"Give a reason for each deleted bundle on {REVIEW_STEP}."
        ),
        missing_bundle_reasons,
        action="proposal",
    ))

    missing_labor_reasons = []
    for bundle in proposal.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        reasons = bundle.get("deleted_labor_reasons")
        if not isinstance(reasons, dict):
            reasons = {}
        for key in bundle.get("deleted_labor_keys") or []:
            if not str(reasons.get(key) or "").strip():
                missing_labor_reasons.append(f"{bundle.get('bundle_name') or 'bundle'}: {key}")
    checks.append(_check(
        "labor_deletion_reasons",
        "fail" if missing_labor_reasons else "pass",
        (
            "Every deleted labor line has a reason."
            if not missing_labor_reasons
            else f"Give a reason for each deleted labor line on {REVIEW_STEP}."
        ),
        missing_labor_reasons,
        action="proposal",
    ))

    if proposal_check is not None:
        # Checked against the calculation the saved bid points to: a newer
        # one nothing points to (a Regenerate the editor didn't apply) left
        # the bid as it was, so it doesn't count here.
        audit_status, audit_message, audit_action = proposal_check_message(proposal_check)
    else:
        run_metadata = (latest_run or {}).get("metadata") or {}
        audit_ok = bool(latest_run and latest_run.get("status") == "completed")
        proposal_audit_run_id = (proposal.get("audit") or {}).get("run_id") if isinstance(proposal.get("audit"), dict) else None
        try:
            audit_ok = audit_ok and int(proposal_audit_run_id) == int((latest_run or {}).get("id"))
        except (TypeError, ValueError):
            audit_ok = False
        current_engine = current_build.get("engine_fingerprint")
        current_config = current_build.get("config_fingerprint")
        audit_ok = audit_ok and bool(
            current_engine
            and current_config
            and run_metadata.get("engine_fingerprint") == current_engine
            and run_metadata.get("config_fingerprint") == current_config
        )
        stored_fingerprint = proposal.get("audit_source_fingerprint")
        fingerprint_ok = bool(stored_fingerprint and proposal_source_fingerprint and stored_fingerprint == proposal_source_fingerprint)
        audit_ok = audit_ok and fingerprint_ok
        audit_status = "pass" if audit_ok else "fail"
        audit_message = (
            "The bid's numbers are up to date."
            if audit_ok
            else f"The bid's numbers need to be saved again. {CLICK_REGENERATE}"
        )
        audit_action = None if audit_ok else "regenerate"
    checks.append(_check("current_audit", audit_status, audit_message, action=audit_action))

    math_errors = proposal_math_errors(proposal) if has_bundles else []
    if not has_bundles:
        math_message = NO_BID_YET
    elif math_errors:
        math_message = f"Some numbers on the bid don't add up. {CLICK_REGENERATE}"
    else:
        math_message = "The bid's numbers add up."
    checks.append(_check(
        "proposal_arithmetic",
        "fail" if (math_errors or not has_bundles) else "pass",
        math_message,
        math_errors,
        action="regenerate" if has_bundles else "proposal",
    ))

    nonpositive_bundles = [
        bundle.get("bundle_name") or f"bundle {index + 1}"
        for index, bundle in enumerate(proposal.get("bundles") or [])
        if isinstance(bundle, dict)
        and _number(bundle.get("price_override") if bundle.get("price_override") is not None else bundle.get("total_price")) <= 0
    ]
    checks.append(_check(
        "bundle_sell_prices",
        "fail" if nonpositive_bundles else "pass",
        (
            "Every bundle has a price."
            if not nonpositive_bundles
            else (
                f"{plain_list(nonpositive_bundles)} {_verb(len(nonpositive_bundles), 'has', 'have')} a $0 price. "
                f"Give {_verb(len(nonpositive_bundles), 'it', 'each one')} a price or delete "
                f"{_verb(len(nonpositive_bundles), 'it', 'them')} with a reason on {REVIEW_STEP}."
            )
        ),
        nonpositive_bundles,
        action="proposal",
    ))

    checks.append(_check(
        "proposal_pdf",
        "pass" if pdf_ready else "fail",
        "The PDF is up to date." if pdf_ready else (
            pdf_message or f"Make a new PDF: the bid changed after the last one was made. Click Generate PDF on {REVIEW_STEP}."
        ),
        action="make_pdf" if has_bundles else "proposal",
    ))

    checks.append(_check(
        "durable_artifacts",
        artifact_status,
        artifact_message or {
            "fail": "Some files saved with this bid are missing or damaged.",
            "warn": "Some older uploads have no saved copy. Nothing to do unless you need the original file.",
        }.get(artifact_status, "All files saved with this bid are intact."),
        artifact_items,
        technical=True,
    ))

    golden_words = {
        "fail": "its numbers are different now",
        "incomparable": "the app was updated after it was saved",
        "not_replayed": "it hasn't been checked yet",
        "stale": "the bid changed after it was saved",
    }
    if golden_verification_status in ("pass", "golden_verified"):
        checks.append(_check("golden_replay", "pass", "The bid still matches its saved reference copy.", technical=True))
    elif golden_verification_status in golden_words:
        checks.append(_check(
            "golden_replay",
            "warn",
            f"The bid can't be matched to its saved reference copy: {golden_words[golden_verification_status]}.",
            technical=True,
        ))
    if current_replay_status in ("warn", "fail", "incomparable"):
        metadata_only = (
            current_replay_status == "warn"
            and current_replay_drift_classification == "metadata_only"
        )
        checks.append(_check(
            "current_replay_drift",
            "warn",
            (
                "Only rule notes changed since the reference copy was saved. The numbers are the same."
                if metadata_only
                else (
                    "Pricing this bid again with today's rates gives different numbers than its saved "
                    "reference copy."
                )
            ),
            technical=True,
        ))

    _mark_covered_checks(checks)
    blocking_count = sum(1 for item in checks if item["status"] == "fail")
    # Technical warnings show only under "Technical details": they don't make
    # the bid "Needs Review" (the card says "Ready to send" for them too).
    warning_count = sum(1 for item in checks if item["status"] == "warn" and not item["technical"])
    return {
        "status": "blocked" if blocking_count else ("warning" if warning_count else "ready"),
        "checks": checks,
        "blocking_count": blocking_count,
        "warning_count": warning_count,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "build": build or {},
        "golden_status": golden_status,
        "golden_verification_status": golden_verification_status,
        "current_replay_status": current_replay_status,
        "current_replay_drift_classification": current_replay_drift_classification,
        "trust_summary": trust,
    }
