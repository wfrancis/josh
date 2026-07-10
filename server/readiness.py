"""Pure readiness checks used by the API and estimator trust UI."""

from __future__ import annotations

from datetime import datetime, timezone


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _check(check_id: str, status: str, message: str, affected_items=None) -> dict:
    return {
        "id": check_id,
        "status": status,
        "message": message,
        "affected_items": affected_items or [],
    }


def _proposal_math_errors(proposal: dict) -> list[str]:
    bundles = [b for b in (proposal.get("bundles") or []) if isinstance(b, dict)]
    errors = []
    bundle_subtotal = round(sum(_number(b.get("total_price")) for b in bundles), 2)
    if abs(bundle_subtotal - _number(proposal.get("subtotal"))) > 0.02:
        errors.append("Proposal subtotal does not equal the sum of bundle totals.")

    bundle_tax = round(sum(_number(b.get("tax_amount")) for b in bundles), 2)
    if abs(bundle_tax - _number(proposal.get("tax_amount"))) > 0.02:
        errors.append("Proposal tax does not equal the sum of bundle tax.")

    expected_grand = round(_number(proposal.get("subtotal")) + _number(proposal.get("textura_amount")), 2)
    if abs(expected_grand - _number(proposal.get("grand_total"))) > 0.02:
        errors.append("Proposal grand total does not equal subtotal plus Textura.")

    expected_gpm = round(_number(proposal.get("gpm_labor")) + _number(proposal.get("gpm_material")), 2)
    if abs(expected_gpm - _number(proposal.get("gpm_profit"))) > 0.02:
        errors.append("GPM labor and material splits do not equal GPM profit.")
    return errors


def evaluate_job_readiness(
    job: dict,
    *,
    latest_run: dict | None,
    current_ruleset_version: int | None,
    pdf_ready: bool,
    pdf_message: str | None,
    proposal_source_fingerprint: str | None,
    golden_status: str | None = None,
    build: dict | None = None,
) -> dict:
    """Evaluate whether a job is safe to send without changing any data."""
    checks = []
    proposal = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    deleted_codes = {str(code) for code in (proposal.get("deleted_material_codes") or []) if code}
    materials = [m for m in (job.get("materials") or []) if isinstance(m, dict)]
    active_materials = [m for m in materials if str(m.get("item_code") or "") not in deleted_codes]

    missing_fields = [field for field in ("project_name", "gc_name", "salesperson") if not str(job.get(field) or "").strip()]
    checks.append(_check(
        "required_job_fields",
        "fail" if missing_fields else "pass",
        "Required job fields are complete." if not missing_fields else f"Missing required fields: {', '.join(missing_fields)}.",
        missing_fields,
    ))

    unknown = [m.get("item_code") or m.get("description") or "material" for m in active_materials if str(m.get("material_type") or "").lower() in ("", "unknown")]
    checks.append(_check(
        "unknown_materials",
        "fail" if unknown else "pass",
        "All active materials are classified." if not unknown else f"{len(unknown)} active material(s) need classification.",
        unknown,
    ))

    unpriced = [m.get("item_code") or m.get("description") or "material" for m in active_materials if _number(m.get("unit_price")) <= 0]
    checks.append(_check(
        "unpriced_materials",
        "fail" if unpriced else "pass",
        "All active materials have prices." if not unpriced else f"{len(unpriced)} active material(s) need pricing.",
        unpriced,
    ))

    def material_key(material: dict) -> str:
        return str(material.get("item_code") or (f"id:{material.get('id')}" if material.get("id") is not None else ""))

    bundle_material_codes = {
        material_key(material)
        for bundle in (proposal.get("bundles") or [])
        if isinstance(bundle, dict)
        for material in (bundle.get("materials") or [])
        if isinstance(material, dict) and material_key(material)
    }
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

    run_metadata = (latest_run or {}).get("metadata") or {}
    run_version = run_metadata.get("ruleset_version")
    audit_ok = bool(latest_run and latest_run.get("status") == "completed")
    proposal_audit_run_id = (proposal.get("audit") or {}).get("run_id") if isinstance(proposal.get("audit"), dict) else None
    if proposal_audit_run_id is not None and latest_run:
        audit_ok = audit_ok and int(proposal_audit_run_id) == int(latest_run.get("id"))
    else:
        audit_ok = False
    if current_ruleset_version is not None and run_version is not None:
        audit_ok = audit_ok and int(run_version) == int(current_ruleset_version)
    stored_fingerprint = proposal.get("audit_source_fingerprint")
    fingerprint_ok = bool(stored_fingerprint and proposal_source_fingerprint and stored_fingerprint == proposal_source_fingerprint)
    audit_ok = audit_ok and fingerprint_ok
    audit_message = "The proposal audit is current and matches the job source." if audit_ok else "The proposal audit is missing, stale, or does not match the current job source."
    checks.append(_check("current_audit", "pass" if audit_ok else "fail", audit_message))

    math_errors = _proposal_math_errors(proposal) if proposal.get("bundles") else ["No saved proposal bundles exist."]
    checks.append(_check("proposal_arithmetic", "fail" if math_errors else "pass", "Proposal arithmetic is internally consistent." if not math_errors else " ".join(math_errors), math_errors))

    checks.append(_check(
        "proposal_pdf",
        "pass" if pdf_ready else "fail",
        "The current proposal PDF is available and passes its audit gates." if pdf_ready else (pdf_message or "The current proposal PDF is missing or stale."),
    ))

    if golden_status in ("pass", "golden_verified"):
        checks.append(_check("golden_replay", "pass", "Golden replay passed."))
    elif golden_status in ("fail", "incomparable", "drift"):
        checks.append(_check("golden_replay", "warn", f"Golden replay status: {golden_status}."))
    else:
        checks.append(_check("golden_replay", "warn", "No golden replay has been recorded for this job yet."))

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
    }
