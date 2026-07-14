"""Pure readiness checks used by the API and estimator trust UI."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from rfms_parser import VALID_MATERIAL_TYPES


VALID_MATERIAL_CLASSIFICATIONS = frozenset(VALID_MATERIAL_TYPES)


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


def _check(check_id: str, status: str, message: str, affected_items=None) -> dict:
    return {
        "id": check_id,
        "status": status,
        "message": message,
        "affected_items": affected_items or [],
    }


def proposal_math_errors(proposal: dict) -> list[str]:
    bundles = [b for b in (proposal.get("bundles") or []) if isinstance(b, dict)]
    errors = []
    for field in (
        "tax_rate", "gpm_pct", "subtotal", "tax_amount", "grand_total",
        "gpm_profit", "gpm_labor", "gpm_material", "textura_amount",
    ):
        if _finite_number(proposal.get(field)) is None:
            errors.append(f"Proposal {field} must be a finite number.")
    if proposal.get("manual_adjustment") is not None and _finite_number(proposal.get("manual_adjustment")) is None:
        errors.append("Proposal manual_adjustment must be a finite number.")
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
                errors.append(f"{name} {field} must be a finite number.")
            elif value < 0:
                errors.append(f"{name} {field} cannot be negative.")
        for field in ("price_override", "freight_override"):
            if bundle.get(field) is None:
                continue
            value = _finite_number(bundle.get(field))
            if value is None:
                errors.append(f"{name} {field} must be a finite number.")
            elif value < 0:
                errors.append(f"{name} {field} cannot be negative.")
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
            if abs(material_line_total - material) > 0.02:
                errors.append(f"{name} material lines do not equal its material cost.")
            if abs(sundry_line_total - sundry) > 0.02:
                errors.append(f"{name} sundry lines do not equal its sundry cost.")
        labor_line_total = round(sum(_number(line.get("extended_cost")) for line in labor_lines), 2)
        if abs(labor_line_total - labor) > 0.02:
            errors.append(f"{name} labor lines do not equal its labor cost.")

        for line_index, line in enumerate(material_lines):
            quantity_value = line.get("order_qty") if line.get("order_qty") is not None else line.get("installed_qty")
            for field, value in (("quantity", quantity_value), ("unit price", line.get("unit_price")), ("extended cost", line.get("extended_cost"))):
                number = _finite_number(value)
                if number is None:
                    errors.append(f"{name} material line {line_index + 1} {field} must be a finite number.")
                elif number < 0:
                    errors.append(f"{name} material line {line_index + 1} {field} cannot be negative.")
            expected_line = round(
                _number(quantity_value)
                * _number(line.get("unit_price")),
                2,
            )
            if abs(expected_line - _number(line.get("extended_cost"))) > 0.02:
                errors.append(f"{name} material line {line_index + 1} does not equal quantity times unit price.")
        for line_index, line in enumerate(sundry_lines):
            for field, value in (("quantity", line.get("qty")), ("unit price", line.get("unit_price")), ("extended cost", line.get("extended_cost"))):
                number = _finite_number(value)
                if number is None:
                    errors.append(f"{name} sundry line {line_index + 1} {field} must be a finite number.")
                elif number < 0:
                    errors.append(f"{name} sundry line {line_index + 1} {field} cannot be negative.")
            expected_line = round(_number(line.get("qty")) * _number(line.get("unit_price")), 2)
            if abs(expected_line - _number(line.get("extended_cost"))) > 0.02:
                errors.append(f"{name} sundry line {line_index + 1} does not equal quantity times unit price.")
        for line_index, line in enumerate(labor_lines):
            for field, value in (("quantity", line.get("qty")), ("rate", line.get("rate")), ("extended cost", line.get("extended_cost"))):
                number = _finite_number(value)
                if number is None:
                    errors.append(f"{name} labor line {line_index + 1} {field} must be a finite number.")
                elif number < 0:
                    errors.append(f"{name} labor line {line_index + 1} {field} cannot be negative.")
            expected_line = round(_number(line.get("qty")) * _number(line.get("rate")), 2)
            if abs(expected_line - _number(line.get("extended_cost"))) > 0.02:
                errors.append(f"{name} labor line {line_index + 1} does not equal quantity times rate.")

        if abs(expected_gpm - _number(bundle.get("gpm_adder"))) > 0.02:
            errors.append(f"{name} GPM split does not equal its GPM adder.")
        if abs(expected_taxable - _number(bundle.get("taxable"))) > 0.02:
            errors.append(f"{name} taxable amount does not equal its taxable cost components.")
        if abs(expected_tax - _number(bundle.get("tax_amount"))) > 0.02:
            errors.append(f"{name} tax does not equal taxable amount times the proposal tax rate.")
        if abs(expected_total - _number(bundle.get("total_price"))) > 0.02:
            errors.append(f"{name} calculated sell price does not equal its cost, GPM, and tax components.")
        accepted_total = bundle.get("price_override") if bundle.get("price_override") is not None else bundle.get("total_price")
        if _finite_number(accepted_total) is None or _number(accepted_total) <= 0:
            errors.append(f"{name} must have a positive accepted sell price.")

    bundle_total = round(sum(
        _number(b.get("price_override") if b.get("price_override") is not None else b.get("total_price"))
        for b in bundles
    ), 2)

    bundle_tax = round(sum(_number(b.get("tax_amount")) for b in bundles), 2)
    if abs(bundle_tax - _number(proposal.get("tax_amount"))) > 0.02:
        errors.append("Proposal tax does not equal the sum of bundle tax.")

    expected_before_textura = round(_number(proposal.get("subtotal")) + bundle_tax, 2)
    if abs(bundle_total - expected_before_textura) > 0.02:
        errors.append("Accepted bundle totals do not equal subtotal plus tax.")

    calculated_bundle_total = round(sum(_number(b.get("total_price")) for b in bundles), 2)
    expected_adjustment = round(bundle_total - calculated_bundle_total, 2)
    if abs(expected_adjustment - _number(proposal.get("manual_adjustment"))) > 0.02:
        errors.append("Manual bundle adjustments do not match the accepted bundle prices.")

    expected_grand = round(_number(proposal.get("subtotal")) + bundle_tax + _number(proposal.get("textura_amount")), 2)
    if abs(expected_grand - _number(proposal.get("grand_total"))) > 0.02:
        errors.append("Proposal grand total does not equal subtotal plus tax and Textura.")

    expected_gpm = round(_number(proposal.get("gpm_labor")) + _number(proposal.get("gpm_material")), 2)
    if abs(expected_gpm - _number(proposal.get("gpm_profit"))) > 0.02:
        errors.append("GPM labor and material splits do not equal GPM profit.")
    bundle_gpm_labor = round(sum(_number(bundle.get("gpm_labor_adder")) for bundle in bundles), 2)
    bundle_gpm_material = round(sum(_number(bundle.get("gpm_material_adder")) for bundle in bundles), 2)
    if abs(bundle_gpm_labor - _number(proposal.get("gpm_labor"))) > 0.02:
        errors.append("Bundle labor GPM adders do not equal proposal labor GPM.")
    if abs(bundle_gpm_material - _number(proposal.get("gpm_material"))) > 0.02:
        errors.append("Bundle material GPM adders do not equal proposal material GPM.")

    accepted_before_textura = round(_number(proposal.get("subtotal")) + bundle_tax, 2)
    expected_textura = round(min(accepted_before_textura * 0.0022, 5000), 2) if _number(proposal.get("textura_fee")) else 0.0
    if abs(expected_textura - _number(proposal.get("textura_amount"))) > 0.02:
        errors.append("Textura amount does not match the accepted proposal total and cap.")
    return errors


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
) -> dict:
    """Evaluate whether a job is safe to send without changing any data."""
    checks = []
    proposal = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}

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
    checks.append(_check(
        "required_job_fields",
        "fail" if missing_fields else "pass",
        "Required job fields are complete." if not missing_fields else f"Missing required fields: {', '.join(missing_fields)}.",
        missing_fields,
    ))

    current_build = build or {}
    required_build_fields = (
        "commit", "tag", "built_at", "environment", "engine_fingerprint",
        "config_fingerprint", "frontend_asset",
    )
    missing_build_fields = [
        field for field in required_build_fields
        if not str(current_build.get(field) or "").strip()
        or str(current_build.get(field)).strip().lower() == "unknown"
    ]
    checks.append(_check(
        "deployed_build_identity",
        "fail" if missing_build_fields else "pass",
        (
            "The deployed frontend and estimator engine are tied to a named Git build."
            if not missing_build_fields
            else f"Deployed build identity is incomplete: {', '.join(missing_build_fields)}."
        ),
        missing_build_fields,
    ))

    unknown = [
        m.get("item_code") or m.get("description") or "material"
        for m in active_materials
        if not is_valid_material_classification(m.get("material_type"))
    ]
    checks.append(_check(
        "unknown_materials",
        "fail" if unknown else "pass",
        "All active materials have a valid classification." if not unknown else f"{len(unknown)} active material(s) need a valid classification.",
        unknown,
    ))

    unpriced = [m.get("item_code") or m.get("description") or "material" for m in active_materials if _number(m.get("unit_price")) <= 0]
    checks.append(_check(
        "unpriced_materials",
        "fail" if unpriced else "pass",
        "All active materials have prices." if not unpriced else f"{len(unpriced)} active material(s) need pricing.",
        unpriced,
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
            "The labor catalog is loaded for active installation materials."
            if not catalog_missing
            else "The labor catalog is empty, so installation cost cannot be trusted."
        ),
        catalog_missing,
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
            "Every active installation material has positive labor evidence in the calculation or accepted proposal."
            if not missing_labor
            else f"{len(missing_labor)} active installation material(s) are missing positive labor cost."
        ),
        missing_labor,
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
        *(f"AI estimate: {item}" for item in ai_estimates),
        *(f"No source: {item}" for item in missing_price_sources),
    ]
    checks.append(_check(
        "price_evidence",
        "warn" if price_evidence_items else "pass",
        (
            "Every active price has a current or explicit source."
            if not price_evidence_items
            else "Some prices come from history, AI, or have no recorded source; confirm them before sending."
        ),
        price_evidence_items,
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
        "No material is both deleted and present in the accepted proposal." if not contradictory_deleted_codes else "Some material codes are marked deleted but still appear in an accepted bundle.",
        contradictory_deleted_codes,
    ))
    missing_from_proposal = [
        m.get("item_code") or m.get("description") or "material"
        for m in active_materials
        if not material_key(m) or material_key(m) not in bundle_material_codes
    ]
    if not proposal.get("bundles"):
        missing_from_proposal = missing_from_proposal or ["proposal bundles"]
    checks.append(_check(
        "proposal_coverage",
        "fail" if missing_from_proposal else "pass",
        "Every active material is represented in the saved proposal." if not missing_from_proposal else "Some active materials are missing from the saved proposal.",
        missing_from_proposal,
    ))
    checks.append(_check(
        "proposal_source_values",
        "pass" if proposal_source_ok else "fail",
        "Proposal quantities and prices match the current material source." if proposal_source_ok else (
            proposal_source_message or "Proposal material values are stale. Regenerate the proposal."
        ),
    ))
    missing_deletion_reasons = [code for code in sorted(raw_deleted_codes) if code not in deleted_codes]
    checks.append(_check(
        "deletion_reasons",
        "fail" if missing_deletion_reasons else "pass",
        "All deleted materials have an explicit reason." if not missing_deletion_reasons else "Some deleted materials are missing an explicit reason.",
        missing_deletion_reasons,
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
        "All deleted bundles have an explicit reason." if not missing_bundle_reasons else "Some deleted bundles are missing an explicit reason.",
        missing_bundle_reasons,
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
        "All deleted labor lines have an explicit reason." if not missing_labor_reasons else "Some deleted labor lines are missing an explicit reason.",
        missing_labor_reasons,
    ))

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
    audit_message = "The proposal audit is current and matches the job source." if audit_ok else "The proposal audit is missing, stale, or does not match the current job source."
    checks.append(_check("current_audit", "pass" if audit_ok else "fail", audit_message))

    math_errors = proposal_math_errors(proposal) if proposal.get("bundles") else ["No saved proposal bundles exist."]
    if math_errors:
        visible_errors = math_errors[:5]
        remaining = len(math_errors) - len(visible_errors)
        math_message = " ".join(visible_errors)
        if remaining:
            math_message += f" Plus {remaining} more arithmetic issue(s)."
    else:
        math_message = "Proposal arithmetic is internally consistent."
    checks.append(_check("proposal_arithmetic", "fail" if math_errors else "pass", math_message, math_errors))

    nonpositive_bundles = [
        bundle.get("bundle_name") or f"bundle {index + 1}"
        for index, bundle in enumerate(proposal.get("bundles") or [])
        if isinstance(bundle, dict)
        and _number(bundle.get("price_override") if bundle.get("price_override") is not None else bundle.get("total_price")) <= 0
    ]
    checks.append(_check(
        "bundle_sell_prices",
        "fail" if nonpositive_bundles else "pass",
        "Every accepted bundle has a positive sell price." if not nonpositive_bundles else "A zero-dollar bundle must be priced or deleted with a reason.",
        nonpositive_bundles,
    ))

    checks.append(_check(
        "proposal_pdf",
        "pass" if pdf_ready else "fail",
        "The current proposal PDF is available and passes its audit gates." if pdf_ready else (pdf_message or "The current proposal PDF is missing or stale."),
    ))

    checks.append(_check(
        "durable_artifacts",
        artifact_status,
        artifact_message or "Recorded source files and the proposal PDF pass their hash checks.",
        artifact_items,
    ))

    if golden_verification_status in ("pass", "golden_verified"):
        checks.append(_check("golden_replay", "pass", "Golden replay passed."))
    elif golden_verification_status in ("fail", "incomparable", "not_replayed", "stale"):
        checks.append(_check("golden_replay", "warn", f"Golden replay status: {golden_verification_status}."))
    if current_replay_status in ("warn", "fail", "incomparable"):
        metadata_only = (
            current_replay_status == "warn"
            and current_replay_drift_classification == "metadata_only"
        )
        checks.append(_check(
            "current_replay_drift",
            "warn",
            (
                "Current replay found rules-registry metadata changes only; calculated results did not drift."
                if metadata_only
                else f"Current replay detected calculation drift ({current_replay_status})."
            ),
        ))

    blocking_count = sum(1 for item in checks if item["status"] == "fail")
    warning_count = sum(1 for item in checks if item["status"] == "warn")
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
        "trust_summary": trust_summary or {},
    }
