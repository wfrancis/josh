"""Golden job capture and dry-run replay helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from audit_engine import AuditTraceBuilder
from labor_calc import calculate_labor_for_materials
from proposal_bundler import generate_proposal_data
from sundry_calc import calculate_sundries_for_materials
from build_info import build_manifest_for_snapshot, engine_fingerprint
from config import FREIGHT_RATES, LABOR_QTY_RULES, STAIR_SUNDRY_KITS, SUNDRY_RULES, WASTE_FACTORS


DEFAULT_TOLERANCE = {
    "proposal_pass_abs": 100.0,
    "proposal_warn_abs": 500.0,
    "proposal_warn_pct": 0.0005,
    "bundle_pass_abs": 25.0,
    "bundle_warn_abs": 100.0,
    "bundle_warn_pct": 0.001,
}

PROPOSAL_TOTAL_FIELDS = (
    "subtotal",
    "tax_amount",
    "grand_total",
    "gpm_profit",
    "gpm_labor",
    "gpm_material",
    "textura_amount",
)

BUNDLE_ACCEPTED_MONEY_FIELDS = (
    "material_cost",
    "sundry_cost",
    "labor_cost",
    "freight_cost",
    "freight_override",
    "gpm_labor_adder",
    "gpm_material_adder",
    "gpm_adder",
    "taxable",
    "tax_amount",
    "total_price",
    "price_override",
)

JOB_SNAPSHOT_FIELDS = (
    "id",
    "slug",
    "project_name",
    "gc_name",
    "address",
    "city",
    "state",
    "zip",
    "tax_rate",
    "gpm_pct",
    "markup_pct",
    "unit_count",
    "tub_shower_count",
    "salesperson",
    "notes",
    "exclusions",
    "architect",
    "designer",
    "textura_fee",
)

MATERIAL_FIELDS_FOR_FINGERPRINT = (
    "id",
    "item_code",
    "description",
    "material_type",
    "installed_qty",
    "unit",
    "waste_pct",
    "order_qty",
    "unit_price",
    "extended_cost",
    "freight_per_unit",
    "freight_source",
    "fixture_count",
    "labor_rate_lf",
    "labor_catalog",
    "tack_strip_lf",
    "seam_tape_lf",
    "pad_sy",
    "area_type",
    "is_mosaic",
    "is_penny_hex",
    "crack_isolation_sf",
    "weld_rod_lf",
)


def fingerprint_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _money(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _copy_jsonable(value):
    return copy.deepcopy({} if value is None else value)


def _line_snapshot(items: list[dict], fields: tuple[str, ...]) -> list[dict]:
    rows = []
    for item in items or []:
        if isinstance(item, dict):
            rows.append({field: item.get(field) for field in fields})
    return rows


def proposal_totals(proposal: dict | None) -> dict:
    proposal = proposal or {}
    return {field: _money(proposal.get(field)) for field in PROPOSAL_TOTAL_FIELDS}


def make_golden_snapshot(
    *,
    job: dict,
    company_rates: dict,
    labor_catalog: list[dict],
    ruleset: dict | None,
    target_totals: dict,
    tolerance: dict | None = None,
    build: dict | None = None,
    artifact_manifest: list[dict] | None = None,
    config_snapshot: dict | None = None,
) -> tuple[dict, str]:
    """Freeze the structured state needed for deterministic golden replay."""
    proposal_data = _copy_jsonable(job.get("proposal_data") or {})
    snapshot = {
        "job": {field: copy.deepcopy(job.get(field)) for field in JOB_SNAPSHOT_FIELDS},
        "materials": _copy_jsonable(job.get("materials") or []),
        "sundries": _copy_jsonable(job.get("sundries") or []),
        "labor": _copy_jsonable(job.get("labor") or []),
        "quotes": _copy_jsonable(job.get("quotes") or []),
        "proposal_data": proposal_data,
        "accepted_totals": proposal_totals(proposal_data),
        "target_totals": {k: _money(v) for k, v in (target_totals or {}).items() if v not in (None, "")},
        "company_rates": _copy_jsonable(company_rates),
        "labor_catalog": _copy_jsonable(labor_catalog),
        "ruleset": {
            "version": (ruleset or {}).get("version"),
            "rule_count": (ruleset or {}).get("rule_count"),
            "active_count": (ruleset or {}).get("active_count"),
            "created_at": (ruleset or {}).get("created_at"),
        },
        "ruleset_snapshot": _copy_jsonable(ruleset or {}),
        "config_snapshot": _copy_jsonable(config_snapshot or {}),
        "build": _copy_jsonable(build or build_manifest_for_snapshot()),
        "artifact_manifest": _copy_jsonable(artifact_manifest or []),
        "tolerance": {**DEFAULT_TOLERANCE, **(tolerance or {})},
    }
    fingerprint = fingerprint_payload({
        "job": snapshot["job"],
        "materials": _line_snapshot(snapshot["materials"], MATERIAL_FIELDS_FOR_FINGERPRINT),
        "proposal_data": proposal_data,
        "target_totals": snapshot["target_totals"],
        "rates": snapshot["company_rates"],
        "labor_catalog": snapshot["labor_catalog"],
        "ruleset": snapshot["ruleset"],
        "ruleset_snapshot": snapshot["ruleset_snapshot"],
        "config_snapshot": snapshot["config_snapshot"],
        "build": snapshot["build"],
        "artifact_manifest": snapshot["artifact_manifest"],
    })
    return snapshot, fingerprint


def _apply_waste_rules(materials: list[dict], waste_factors: dict, trace: AuditTraceBuilder) -> None:
    for mat in materials:
        material_type = mat.get("material_type", "")
        new_waste = waste_factors.get(material_type)
        if new_waste is None:
            continue
        mat_unit = (mat.get("unit") or "").upper()
        if mat_unit == "EA" and material_type != "sound_mat":
            continue
        old_waste = _num(mat.get("waste_pct"))
        if abs(float(new_waste) - old_waste) < 1e-6:
            continue
        installed_qty = _num(mat.get("installed_qty"))
        mat["waste_pct"] = float(new_waste)
        mat["order_qty"] = round(installed_qty * (1 + float(new_waste)), 2)
        mat["extended_cost"] = round(mat["order_qty"] * _num(mat.get("unit_price")), 2)
        trace.record(
            entity_type="material",
            entity_id=mat.get("id"),
            entity_key=mat.get("item_code"),
            output_field="order_qty",
            formula="installed_qty * (1 + waste_pct)",
            inputs={"installed_qty": installed_qty, "waste_pct": new_waste, "old_waste_pct": old_waste},
            result=mat["order_qty"],
            rule_id=f"waste_factor:{material_type}",
            source="golden_replay",
        )
        trace.record(
            entity_type="material",
            entity_id=mat.get("id"),
            entity_key=mat.get("item_code"),
            output_field="extended_cost",
            formula="order_qty * unit_price",
            inputs={"order_qty": mat["order_qty"], "unit_price": _num(mat.get("unit_price"))},
            result=mat["extended_cost"],
            rule_id=f"material:{material_type}:extended_cost",
            source="golden_replay",
        )


def _stamp_job_counts(job: dict, materials: list[dict]) -> None:
    unit_count = job.get("unit_count", 0) or 0
    tub_shower_count = job.get("tub_shower_count", 0) or 0
    for mat in materials:
        if mat.get("material_type") == "backsplash":
            mat["unit_count"] = unit_count
        if mat.get("material_type") == "tub_shower_surround":
            mat["tub_shower_total"] = tub_shower_count


def _reapply_accepted_rewrites(generated: dict, accepted: dict) -> None:
    existing = {}
    for bundle in accepted.get("bundles") or []:
        mats = bundle.get("materials") or []
        if not mats:
            continue
        key = (mats[0].get("item_code") or "").strip()
        if key:
            existing[key] = {
                "bundle_name": bundle.get("bundle_name"),
                "description_text": bundle.get("description_text"),
            }
    for bundle in generated.get("bundles") or []:
        mats = bundle.get("materials") or []
        if not mats:
            continue
        key = (mats[0].get("item_code") or "").strip()
        rewrite = existing.get(key)
        if not rewrite:
            continue
        if rewrite.get("bundle_name"):
            bundle["bundle_name"] = rewrite["bundle_name"]
        if rewrite.get("description_text"):
            bundle["description_text"] = rewrite["description_text"]
    for field in ("notes", "terms", "exclusions", "deleted_bundles", "deleted_material_codes"):
        if field in accepted:
            generated[field] = copy.deepcopy(accepted[field])


def _sync_editor_totals(proposal: dict) -> None:
    bundles = [b for b in (proposal.get("bundles") or []) if isinstance(b, dict)]
    proposal["gpm_labor"] = _money(sum(_money(b.get("gpm_labor_adder")) for b in bundles))
    proposal["gpm_material"] = _money(sum(_money(b.get("gpm_material_adder")) for b in bundles))


def _reapply_accepted_money(generated: dict, accepted: dict) -> int:
    """Replay accepted proposal-level and bundle-level numeric edits for baseline mode."""
    changed = 0
    for field in (*PROPOSAL_TOTAL_FIELDS, "taxable", "tax_rate", "gpm_pct", "textura_fee"):
        if field in accepted:
            old = generated.get(field)
            generated[field] = copy.deepcopy(accepted[field])
            if _money(old) != _money(accepted[field]):
                changed += 1

    accepted_by_name = {
        b.get("bundle_name"): b
        for b in (accepted.get("bundles") or [])
        if isinstance(b, dict) and b.get("bundle_name")
    }
    accepted_by_code = {}
    for bundle in accepted.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        codes = _bundle_codes(bundle)
        if codes:
            accepted_by_code[codes[0]] = bundle

    for bundle in generated.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        accepted_bundle = accepted_by_name.get(bundle.get("bundle_name"))
        if not accepted_bundle:
            codes = _bundle_codes(bundle)
            accepted_bundle = accepted_by_code.get(codes[0]) if codes else None
        if not accepted_bundle:
            continue
        for field in BUNDLE_ACCEPTED_MONEY_FIELDS:
            if field not in accepted_bundle:
                continue
            old = bundle.get(field)
            bundle[field] = copy.deepcopy(accepted_bundle[field])
            if _money(old) != _money(accepted_bundle[field]):
                changed += 1
    return changed


def _bundle_codes(bundle: dict) -> list[str]:
    codes = []
    for material in bundle.get("materials") or []:
        code = material.get("item_code") or material.get("id") or material.get("material_id")
        if code:
            codes.append(str(code))
    return codes


def _severity_rank(status: str) -> int:
    return {"pass": 0, "warn": 1, "fail": 2, "incomparable": 3}.get(status, 0)


def _max_status(*statuses: str) -> str:
    return max(statuses, key=_severity_rank)


def _money_status(delta: float, target: float, tolerance: dict, scope: str) -> str:
    prefix = "bundle" if scope == "bundle" else "proposal"
    pass_abs = float(tolerance.get(f"{prefix}_pass_abs", 0))
    warn_abs = float(tolerance.get(f"{prefix}_warn_abs", pass_abs))
    warn_pct = float(tolerance.get(f"{prefix}_warn_pct", 0))
    abs_delta = abs(delta)
    pct_delta = abs_delta / abs(target) if target else float("inf")
    if abs_delta <= pass_abs:
        return "pass"
    if abs_delta <= warn_abs or (warn_pct and pct_delta <= warn_pct):
        return "warn"
    return "fail"


def compare_replay(generated: dict, snapshot: dict, tolerance: dict) -> dict:
    accepted = snapshot.get("proposal_data") or {}
    target_totals = snapshot.get("target_totals") or {}
    accepted_totals = snapshot.get("accepted_totals") or proposal_totals(accepted)
    total_rows = []
    status = "pass"
    for field in PROPOSAL_TOTAL_FIELDS:
        target = _money(target_totals.get(field, accepted_totals.get(field)))
        actual = _money(generated.get(field))
        delta = round(actual - target, 2)
        row_status = _money_status(delta, target, tolerance, "proposal")
        status = max(status, row_status, key=_severity_rank)
        total_rows.append({
            "field": field,
            "target": target,
            "actual": actual,
            "delta": delta,
            "status": row_status,
            "target_source": "jr" if field in target_totals else "accepted_proposal",
        })

    accepted_bundles = [b for b in accepted.get("bundles") or [] if isinstance(b, dict)]
    generated_bundles = [b for b in generated.get("bundles") or [] if isinstance(b, dict)]
    structural = []
    accepted_order = [b.get("bundle_name") for b in accepted_bundles]
    generated_order = [b.get("bundle_name") for b in generated_bundles]
    if accepted_order != generated_order:
        structural.append({
            "check": "bundle_order",
            "status": "fail",
            "message": "Bundle order changed.",
            "accepted": accepted_order,
            "actual": generated_order,
        })
        status = "fail"

    accepted_deleted = sorted(accepted.get("deleted_bundles") or [])
    generated_deleted = sorted(generated.get("deleted_bundles") or [])
    if accepted_deleted != generated_deleted:
        structural.append({
            "check": "deleted_bundles",
            "status": "fail",
            "message": "Deleted bundle flags changed.",
            "accepted": accepted_deleted,
            "actual": generated_deleted,
        })
        status = "fail"

    accepted_deleted_codes = sorted(accepted.get("deleted_material_codes") or [])
    generated_deleted_codes = sorted(generated.get("deleted_material_codes") or [])
    if accepted_deleted_codes != generated_deleted_codes:
        structural.append({
            "check": "deleted_material_codes",
            "status": "fail",
            "message": "Deleted material-code flags changed.",
            "accepted": accepted_deleted_codes,
            "actual": generated_deleted_codes,
        })
        status = "fail"

    bundle_rows = []
    generated_by_name = {b.get("bundle_name"): b for b in generated_bundles}
    for index, accepted_bundle in enumerate(accepted_bundles):
        name = accepted_bundle.get("bundle_name") or f"bundle:{index}"
        actual_bundle = generated_by_name.get(name)
        if not actual_bundle:
            bundle_rows.append({
                "bundle_name": name,
                "status": "fail",
                "message": "Bundle missing from replay.",
                "target_total": _money(accepted_bundle.get("total_price")),
                "actual_total": None,
                "delta": None,
                "item_codes": _bundle_codes(accepted_bundle),
            })
            status = "fail"
            continue
        accepted_codes = _bundle_codes(accepted_bundle)
        actual_codes = _bundle_codes(actual_bundle)
        if accepted_codes != actual_codes:
            structural.append({
                "check": "bundle_material_codes",
                "status": "fail",
                "message": f"Material codes changed for {name}.",
                "bundle_name": name,
                "accepted": accepted_codes,
                "actual": actual_codes,
            })
            status = "fail"
        target_total = _money(accepted_bundle.get("total_price"))
        actual_total = _money(actual_bundle.get("total_price"))
        delta = round(actual_total - target_total, 2)
        row_status = _money_status(delta, target_total, tolerance, "bundle")
        status = max(status, row_status, key=_severity_rank)
        bundle_rows.append({
            "bundle_name": name,
            "status": row_status,
            "target_total": target_total,
            "actual_total": actual_total,
            "delta": delta,
            "item_codes": accepted_codes,
        })

    extra_names = [b.get("bundle_name") for b in generated_bundles if b.get("bundle_name") not in set(accepted_order)]
    if extra_names:
        structural.append({
            "check": "extra_bundles",
            "status": "fail",
            "message": "Replay produced extra bundles.",
            "actual": extra_names,
        })
        status = "fail"

    bundle_rows.sort(key=lambda row: abs(row.get("delta") or 0), reverse=True)
    return {
        "status": status,
        "totals": total_rows,
        "bundles": bundle_rows,
        "structural": structural,
    }


def _drift_rows(
    snapshot: dict,
    rates: dict,
    labor_catalog: list[dict],
    ruleset_meta: dict,
    current_engine_fingerprint: str | None = None,
    current_config_snapshot: dict | None = None,
) -> list[dict]:
    baseline_ruleset = snapshot.get("ruleset") or {}
    rows = []
    if baseline_ruleset.get("version") != ruleset_meta.get("version"):
        rows.append({
            "check": "ruleset_version",
            "status": "warn",
            "baseline": baseline_ruleset.get("version"),
            "current": ruleset_meta.get("version"),
            "classification": "metadata_only",
            "message": "Rules registry metadata changed. The engine fingerprint is checked separately to determine whether calculation behavior changed.",
        })

    baseline_engine = (snapshot.get("build") or {}).get("engine_fingerprint")
    if baseline_engine and current_engine_fingerprint and baseline_engine != current_engine_fingerprint:
        rows.append({
            "check": "engine_fingerprint",
            "status": "warn",
            "baseline": baseline_engine,
            "current": current_engine_fingerprint,
            "classification": "calculation_behavior_changed",
            "message": "The calculator build/config fingerprint changed. Current replay is a drift report, not an apples-to-apples proof.",
        })

    baseline_rates_hash = fingerprint_payload(snapshot.get("company_rates") or {})
    current_rates_hash = fingerprint_payload(rates or {})
    if baseline_rates_hash != current_rates_hash:
        rows.append({
            "check": "company_rates",
            "status": "warn",
            "baseline": baseline_rates_hash,
            "current": current_rates_hash,
            "message": "Company rates changed since the baseline was captured.",
        })

    baseline_labor_hash = fingerprint_payload(snapshot.get("labor_catalog") or [])
    current_labor_hash = fingerprint_payload(labor_catalog or [])
    if baseline_labor_hash != current_labor_hash:
        rows.append({
            "check": "labor_catalog",
            "status": "warn",
            "baseline": baseline_labor_hash,
            "current": current_labor_hash,
            "message": "Labor catalog changed since the baseline was captured.",
        })
    baseline_config_hash = fingerprint_payload(snapshot.get("config_snapshot") or {})
    current_config_hash = fingerprint_payload(current_config_snapshot or {})
    if baseline_config_hash != current_config_hash:
        rows.append({
            "check": "engine_config",
            "status": "warn",
            "baseline": baseline_config_hash,
            "current": current_config_hash,
            "classification": "calculation_behavior_changed",
            "message": "Calculation configuration changed since the baseline was captured.",
        })
    return rows


def _engine_status(snapshot: dict, mode: str) -> tuple[str, str | None]:
    """Baseline replay is only a proof when it uses the same engine build."""
    baseline_build = snapshot.get("build") or {}
    baseline_fingerprint = baseline_build.get("engine_fingerprint")
    current_fingerprint = engine_fingerprint()
    if mode == "baseline" and baseline_fingerprint and baseline_fingerprint != current_fingerprint:
        return "incomparable", current_fingerprint
    return "comparable", current_fingerprint


def _config_snapshot() -> dict:
    return {
        "waste_factors": _copy_jsonable(WASTE_FACTORS),
        "sundry_rules": _copy_jsonable(SUNDRY_RULES),
        "freight_rates": _copy_jsonable(FREIGHT_RATES),
        "labor_qty_rules": _copy_jsonable(LABOR_QTY_RULES),
        "stair_sundry_kits": _copy_jsonable(STAIR_SUNDRY_KITS),
    }


def replay_golden_job(
    *,
    golden_job: dict,
    mode: str,
    current_company_rates: dict | None = None,
    current_labor_catalog: list[dict] | None = None,
    current_ruleset: dict | None = None,
    current_config_snapshot: dict | None = None,
) -> tuple[dict, AuditTraceBuilder]:
    """Run a dry replay from a golden baseline without mutating the source job."""
    if mode not in ("baseline", "current"):
        raise ValueError("Replay mode must be 'baseline' or 'current'.")

    snapshot = _copy_jsonable(golden_job.get("snapshot") or {})
    rates = snapshot.get("company_rates") or {}
    labor_catalog = snapshot.get("labor_catalog") or []
    ruleset_meta = snapshot.get("ruleset") or {}
    if mode == "current":
        rates = current_company_rates or {}
        labor_catalog = current_labor_catalog or []
        ruleset_meta = {
            "version": (current_ruleset or {}).get("version"),
            "rule_count": (current_ruleset or {}).get("rule_count"),
            "active_count": (current_ruleset or {}).get("active_count"),
            "created_at": (current_ruleset or {}).get("created_at"),
        }
    config = _copy_jsonable(snapshot.get("config_snapshot") or _config_snapshot())
    if mode == "current":
        config = _copy_jsonable(current_config_snapshot or _config_snapshot())

    job = _copy_jsonable(snapshot.get("job") or {})
    source_job_id = int(golden_job.get("source_job_id") or job.get("id") or 0)
    job["id"] = source_job_id
    job["materials"] = _copy_jsonable(snapshot.get("materials") or [])
    job["proposal_data"] = _copy_jsonable(snapshot.get("proposal_data") or {})

    comparability, current_engine_fingerprint = _engine_status(snapshot, mode)

    trace = AuditTraceBuilder(
        source_job_id,
        default_source=f"golden_replay:{mode}",
    )
    trace.record(
        entity_type="golden_replay",
        entity_id=golden_job.get("id"),
        entity_key=mode,
        output_field="ruleset_version",
        formula="selected replay ruleset version",
        inputs={"mode": mode},
        result=ruleset_meta.get("version"),
        rule_id="golden_replay:ruleset",
        source="golden_replay",
    )

    _apply_waste_rules(job["materials"], rates.get("waste_factors") or config.get("waste_factors") or {}, trace)
    _stamp_job_counts(job, job["materials"])
    job["sundries"] = calculate_sundries_for_materials(
        job["materials"],
        trace=trace,
        sundry_rules_override=rates.get("sundry_rules") or config.get("sundry_rules") or {},
    )
    job["labor"] = calculate_labor_for_materials(
        job["materials"],
        trace=trace,
        labor_catalog_override=labor_catalog,
    )

    proposal = generate_proposal_data(source_job_id, job, trace=trace)
    _sync_editor_totals(proposal)
    _reapply_accepted_rewrites(proposal, job.get("proposal_data") or {})
    tolerance = {**DEFAULT_TOLERANCE, **(golden_job.get("tolerance") or snapshot.get("tolerance") or {})}
    engine_diff = compare_replay(copy.deepcopy(proposal), snapshot, tolerance)
    accepted_money_replay_count = 0
    if mode == "baseline":
        accepted_money_replay_count = _reapply_accepted_money(proposal, job.get("proposal_data") or {})
        if accepted_money_replay_count:
            trace.record(
                entity_type="golden_replay",
                entity_id=golden_job.get("id"),
                entity_key=mode,
                output_field="accepted_numeric_edits",
                formula="reapply saved accepted proposal numeric fields in baseline mode",
                inputs={"mode": mode},
                result=accepted_money_replay_count,
                rule_id="golden_replay:accepted_numeric_edits",
                source="golden_replay",
            )

    diff = compare_replay(proposal, snapshot, tolerance)
    accepted_proposal_status = diff["status"]
    diff["drift"] = _drift_rows(
        snapshot,
        rates,
        labor_catalog,
        ruleset_meta,
        current_engine_fingerprint=current_engine_fingerprint,
        current_config_snapshot=config,
    ) if mode == "current" else []
    if comparability == "incomparable":
        diff["status"] = "incomparable"
        engine_diff["status"] = "incomparable"
    if diff["drift"]:
        diff["status"] = _max_status(diff["status"], "warn")
    if comparability != "incomparable":
        diff["status"] = _max_status(engine_diff["status"], diff["status"])
    diff["engine"] = {
        "status": engine_diff["status"],
        "totals": engine_diff["totals"],
        "bundles": engine_diff["bundles"],
        "structural": engine_diff["structural"],
    }
    summary = {
        "mode": mode,
        "status": diff["status"],
        "engine_status": engine_diff["status"],
        "raw_engine_status": engine_diff["status"],
        "accepted_proposal_status": accepted_proposal_status,
        "engine_comparability": comparability,
        "baseline_engine_fingerprint": (snapshot.get("build") or {}).get("engine_fingerprint"),
        "current_engine_fingerprint": current_engine_fingerprint,
        "golden_job_id": golden_job.get("id"),
        "source_job_id": source_job_id,
        "ruleset_version": ruleset_meta.get("version"),
        "baseline_ruleset_version": (snapshot.get("ruleset") or {}).get("version"),
        "source_fingerprint": golden_job.get("source_fingerprint"),
        "target_totals": snapshot.get("target_totals") or {},
        "accepted_totals": snapshot.get("accepted_totals") or {},
        "generated_totals": proposal_totals(proposal),
        "accepted_numeric_edit_count": accepted_money_replay_count,
        "failing_structural_count": len([row for row in diff["structural"] if row.get("status") == "fail"]),
        "engine_failing_structural_count": len([row for row in engine_diff["structural"] if row.get("status") == "fail"]),
        "engine_warning_total_count": len([row for row in engine_diff["totals"] if row.get("status") == "warn"]),
        "engine_failing_total_count": len([row for row in engine_diff["totals"] if row.get("status") == "fail"]),
        "drift_count": len(diff["drift"]),
        "warning_total_count": len([row for row in diff["totals"] if row.get("status") == "warn"]),
        "failing_total_count": len([row for row in diff["totals"] if row.get("status") == "fail"]),
    }
    proposal["replay"] = summary
    return {"summary": summary, "diff": diff, "proposal": proposal}, trace
