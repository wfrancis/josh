"""Golden job capture and dry-run replay helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from typing import Any

from audit_engine import AuditTraceBuilder
from labor_calc import calculate_labor_for_materials
from proposal_bundler import generate_proposal_data
from proposal_totals import effective_bundle_total, normalize_proposal_totals
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
    "manual_adjustment",
    "textura_amount",
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
    "vendor",
    "price_source",
    "quote_status",
    "ai_confidence",
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
        number = float(value or 0)
        return round(number, 2) if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _num(value) -> float:
    try:
        number = float(value or 0)
        return number if math.isfinite(number) else 0.0
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
    proposal_source_fingerprint: str | None = None,
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
        "proposal_source_fingerprint": str(proposal_source_fingerprint or ""),
        "tolerance": {**DEFAULT_TOLERANCE, **(tolerance or {})},
    }
    capture_trace = AuditTraceBuilder(
        int(job.get("id") or 0),
        default_source="golden_capture:raw_engine",
    )
    raw_engine_proposal = _generate_raw_replay_proposal(
        snapshot,
        rates=snapshot["company_rates"],
        labor_catalog=snapshot["labor_catalog"],
        config=snapshot["config_snapshot"] or _config_snapshot(),
        trace=capture_trace,
    )
    snapshot["raw_engine_proposal"] = raw_engine_proposal
    snapshot["raw_engine_totals"] = proposal_totals(raw_engine_proposal)
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
        "proposal_source_fingerprint": snapshot["proposal_source_fingerprint"],
        "raw_engine_proposal": snapshot["raw_engine_proposal"],
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
    existing_by_signature: dict[tuple[str, ...], list[dict]] = {}
    existing_by_name = {}
    for bundle in accepted.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        signature = _bundle_signature(bundle)
        if signature:
            existing_by_signature.setdefault(signature, []).append(bundle)
        if bundle.get("bundle_name"):
            existing_by_name[bundle["bundle_name"]] = bundle
    for bundle in generated.get("bundles") or []:
        signature = _bundle_signature(bundle)
        candidates = existing_by_signature.get(signature, []) if signature else []
        rewrite = next(
            (candidate for candidate in candidates if candidate.get("bundle_name") == bundle.get("bundle_name")),
            candidates[0] if len(candidates) == 1 else existing_by_name.get(bundle.get("bundle_name")),
        )
        if not rewrite:
            continue
        if rewrite.get("bundle_name"):
            bundle["bundle_name"] = rewrite["bundle_name"]
        if rewrite.get("description_text"):
            bundle["description_text"] = rewrite["description_text"]
    for field in ("notes", "terms", "exclusions", "deleted_bundles", "deleted_bundle_reasons", "deleted_material_codes", "deleted_material_reasons"):
        if field in accepted:
            generated[field] = copy.deepcopy(accepted[field])


def _sync_editor_totals(proposal: dict) -> None:
    normalize_proposal_totals(proposal)


def _material_key(item: dict) -> str:
    return str(item.get("item_code") or item.get("id") or item.get("material_id") or "")


def _bundle_signature(bundle: dict) -> tuple[str, ...]:
    return tuple(sorted(code for code in (_material_key(item) for item in (bundle.get("materials") or [])) if code))


def _material_line_freight(item: dict) -> float:
    if item.get("freight_cost") is not None:
        return _money(item.get("freight_cost"))
    quantity = item.get("order_qty") if item.get("order_qty") is not None else item.get("installed_qty")
    return _money(_num(quantity) * _num(item.get("freight_per_unit")))


def _sundry_key(item: dict) -> tuple[str, str]:
    return (
        str(item.get("material_id") or ""),
        str(item.get("sundry_name") or "").strip().lower(),
    )


def _labor_identity(item: dict) -> tuple[str, str]:
    return (
        str(item.get("material_id") or item.get("id") or ""),
        str(item.get("labor_description") or "").strip().lower(),
    )


def _labor_line_key(item: dict) -> str:
    material_id, description = _labor_identity(item)
    unit = str(item.get("unit") or "").strip().upper()
    return "\x1f".join((material_id, description, unit))


def _manual_edit_contract(bundle: dict, reference_bundle: dict | None = None) -> dict:
    """Return only explicit accepted inputs that replay must preserve exactly."""
    contract = {}
    for field in ("price_override", "freight_override"):
        if bundle.get(field) is not None:
            contract[field] = _money(bundle.get(field))
    for field in ("stair_count", "stair_labor_type"):
        if bundle.get(field) not in (None, ""):
            contract[field] = copy.deepcopy(bundle.get(field))

    reference_materials = {
        _material_key(item): item
        for item in ((reference_bundle or {}).get("materials") or [])
        if isinstance(item, dict)
    }
    manual_materials = []
    for material in bundle.get("materials") or []:
        if not isinstance(material, dict):
            continue
        reference = reference_materials.get(_material_key(material))
        freight_changed = bool(
            reference is None
            or _money(material.get("freight_per_unit")) != _money(reference.get("freight_per_unit"))
            or (
                "freight_cost" in material
                and _money(material.get("freight_cost")) != _money(reference.get("freight_cost"))
            )
        )
        if material.get("freight_is_manual") or freight_changed:
            manual_materials.append({
                "key": _material_key(material),
                "freight_per_unit": _money(material.get("freight_per_unit")),
                "freight_cost": _material_line_freight(material),
            })
    if manual_materials:
        contract["manual_material_freight"] = sorted(manual_materials, key=lambda item: item["key"])

    reference_sundries = {
        _sundry_key(item): item
        for item in ((reference_bundle or {}).get("sundry_items") or [])
        if isinstance(item, dict)
    }
    manual_sundries = []
    for sundry in bundle.get("sundry_items") or []:
        if not isinstance(sundry, dict):
            continue
        reference = reference_sundries.get(_sundry_key(sundry))
        sundry_changed = bool(
            reference is None
            or _num(sundry.get("qty")) != _num(reference.get("qty"))
            or str(sundry.get("unit") or "") != str(reference.get("unit") or "")
            or _money(sundry.get("unit_price")) != _money(reference.get("unit_price"))
            or _money(sundry.get("extended_cost")) != _money(reference.get("extended_cost"))
        )
        if sundry.get("is_manual_price") or sundry.get("is_stair_sundry") or sundry_changed:
            manual_sundries.append({
                "key": "\x1f".join(_sundry_key(sundry)),
                "qty": _num(sundry.get("qty")),
                "unit": str(sundry.get("unit") or ""),
                "unit_price": _money(sundry.get("unit_price")),
                "extended_cost": _money(sundry.get("extended_cost")),
                "is_stair_sundry": bool(sundry.get("is_stair_sundry")),
            })
    if manual_sundries:
        contract["manual_sundries"] = sorted(manual_sundries, key=lambda item: item["key"])

    reference_labor = {
        _labor_identity(item): item
        for item in ((reference_bundle or {}).get("labor_items") or [])
        if isinstance(item, dict)
    }
    manual_labor = []
    for labor in bundle.get("labor_items") or []:
        if not isinstance(labor, dict):
            continue
        reference = reference_labor.get(_labor_identity(labor))
        labor_changed = bool(
            reference is None
            or _num(labor.get("qty")) != _num(reference.get("qty"))
            or str(labor.get("unit") or "") != str(reference.get("unit") or "")
            or _money(labor.get("rate")) != _money(reference.get("rate"))
            or _money(labor.get("extended_cost")) != _money(reference.get("extended_cost"))
        )
        if labor.get("is_manual") or labor.get("is_stair_labor") or labor_changed:
            manual_labor.append({
                "key": "\x1f".join(_labor_identity(labor)),
                "description": str(labor.get("labor_description") or ""),
                "qty": _num(labor.get("qty")),
                "unit": str(labor.get("unit") or ""),
                "rate": _money(labor.get("rate")),
                "extended_cost": _money(labor.get("extended_cost")),
                "is_stair_labor": bool(labor.get("is_stair_labor")),
            })
    if manual_labor:
        contract["manual_labor"] = sorted(manual_labor, key=lambda item: (item["key"], item["description"], item["unit"]))

    deleted_keys = sorted(str(key) for key in (bundle.get("deleted_labor_keys") or []))
    if deleted_keys:
        reasons = bundle.get("deleted_labor_reasons") or {}
        contract["deleted_labor"] = [
            {"key": key, "reason": str(reasons.get(key) or "")}
            for key in deleted_keys
        ]
    return contract


def _find_accepted_bundle(bundle: dict, accepted_bundles: list[dict]) -> dict | None:
    signature = _bundle_signature(bundle)
    candidates = [candidate for candidate in accepted_bundles if _bundle_signature(candidate) == signature] if signature else []
    named = [candidate for candidate in candidates if candidate.get("bundle_name") == bundle.get("bundle_name")]
    if len(named) == 1:
        return named[0]
    if len(candidates) == 1:
        return candidates[0]
    if not signature:
        by_name = [candidate for candidate in accepted_bundles if candidate.get("bundle_name") == bundle.get("bundle_name")]
        if len(by_name) == 1:
            return by_name[0]
    return None


def _ordered_materials(materials: list[dict], accepted_bundle: dict) -> list[dict]:
    """Follow the accepted material order without copying accepted calculations."""
    remaining = [copy.deepcopy(item) for item in materials if isinstance(item, dict)]
    ordered = []
    for accepted_material in accepted_bundle.get("materials") or []:
        key = _material_key(accepted_material)
        match_index = next((index for index, item in enumerate(remaining) if _material_key(item) == key), None)
        if match_index is not None:
            ordered.append(remaining.pop(match_index))
    ordered.extend(remaining)
    return ordered


def _combine_generated_bundles(selected: list[dict], accepted_bundle: dict) -> dict:
    materials = _ordered_materials(
        [item for bundle in selected for item in (bundle.get("materials") or [])],
        accepted_bundle,
    )
    sundries = [copy.deepcopy(item) for bundle in selected for item in (bundle.get("sundry_items") or [])]
    labor = [copy.deepcopy(item) for bundle in selected for item in (bundle.get("labor_items") or [])]
    return {
        "bundle_name": accepted_bundle.get("bundle_name") or selected[0].get("bundle_name") or "Bundle",
        "description_text": accepted_bundle.get("description_text") or selected[0].get("description_text") or "",
        "materials": materials,
        "sundry_items": sundries,
        "labor_items": labor,
        "material_cost": _money(sum(_money(bundle.get("material_cost")) for bundle in selected)),
        "sundry_cost": _money(sum(_money(bundle.get("sundry_cost")) for bundle in selected)),
        "labor_cost": _money(sum(_money(bundle.get("labor_cost")) for bundle in selected)),
        "freight_cost": _money(sum(_money(bundle.get("freight_cost")) for bundle in selected)),
        "installed_qty": _num(sum(_num(bundle.get("installed_qty")) for bundle in selected)),
        "unit": accepted_bundle.get("unit") or selected[0].get("unit") or "",
        "editable": True,
        "is_derived": bool(len(selected) == 1 and selected[0].get("is_derived")),
    }


def apply_accepted_bundle_structure(generated: dict, accepted: dict) -> int:
    """Rebuild accepted ordering/grouping from raw bundles without copying totals."""
    raw_bundles = [copy.deepcopy(bundle) for bundle in (generated.get("bundles") or []) if isinstance(bundle, dict)]
    accepted_bundles = [bundle for bundle in (accepted.get("bundles") or []) if isinstance(bundle, dict)]
    if not accepted_bundles:
        return 0

    used_indexes = set()
    rebuilt = []
    changed = 0
    for accepted_index, accepted_bundle in enumerate(accepted_bundles):
        accepted_signature = _bundle_signature(accepted_bundle)
        exact_indexes = [
            index for index, candidate in enumerate(raw_bundles)
            if index not in used_indexes and _bundle_signature(candidate) == accepted_signature
        ] if accepted_signature else []
        named_exact = [
            index for index in exact_indexes
            if raw_bundles[index].get("bundle_name") == accepted_bundle.get("bundle_name")
        ]
        named_code_free = [
            index for index, candidate in enumerate(raw_bundles)
            if index not in used_indexes
            and not accepted_signature
            and not _bundle_signature(candidate)
            and candidate.get("bundle_name") == accepted_bundle.get("bundle_name")
        ]
        selected_indexes = []
        if len(named_exact) == 1:
            selected_indexes = named_exact
        elif len(exact_indexes) == 1:
            selected_indexes = exact_indexes
        elif len(named_code_free) == 1:
            selected_indexes = named_code_free
        elif accepted_signature:
            remaining_codes = Counter(accepted_signature)
            subset_indexes = []
            for index, candidate in enumerate(raw_bundles):
                if index in used_indexes:
                    continue
                candidate_signature = _bundle_signature(candidate)
                candidate_codes = Counter(candidate_signature)
                if not candidate_codes or any(
                    count > remaining_codes[code]
                    for code, count in candidate_codes.items()
                ):
                    continue
                subset_indexes.append(index)
                remaining_codes.subtract(candidate_codes)
            if not +remaining_codes:
                selected_indexes = subset_indexes

        if selected_indexes:
            selected = [raw_bundles[index] for index in selected_indexes]
            rebuilt_bundle = _combine_generated_bundles(selected, accepted_bundle)
            used_indexes.update(selected_indexes)
            if (
                len(selected_indexes) != 1
                or selected_indexes[0] != accepted_index
                or selected[0].get("bundle_name") != accepted_bundle.get("bundle_name")
                or selected[0].get("description_text") != accepted_bundle.get("description_text")
            ):
                changed += 1
        elif not accepted_signature:
            # A code-free custom bundle is an accepted manual structure. Its
            # explicit price, sundry, and labor inputs are applied in the next
            # phase; no accepted engine-derived total is copied here.
            rebuilt_bundle = _combine_generated_bundles([{
                "bundle_name": accepted_bundle.get("bundle_name"),
                "description_text": accepted_bundle.get("description_text"),
                "materials": [],
                "sundry_items": [],
                "labor_items": [],
                "material_cost": 0,
                "sundry_cost": 0,
                "labor_cost": 0,
                "freight_cost": 0,
                "installed_qty": 0,
                "unit": accepted_bundle.get("unit") or "",
            }], accepted_bundle)
            changed += 1
        else:
            # Keep an unmatched accepted structure in the comparison without
            # copying its calculated output. The unmatched raw work is appended
            # below, making the structural drift explicit and impossible to hide.
            rebuilt_bundle = _combine_generated_bundles([{
                "bundle_name": accepted_bundle.get("bundle_name"),
                "description_text": accepted_bundle.get("description_text"),
                "materials": [],
                "sundry_items": [],
                "labor_items": [],
                "material_cost": 0,
                "sundry_cost": 0,
                "labor_cost": 0,
                "freight_cost": 0,
                "installed_qty": 0,
                "unit": accepted_bundle.get("unit") or "",
            }], accepted_bundle)
            changed += 1
        rebuilt.append(rebuilt_bundle)

    # Unmapped raw work remains visible as an extra bundle so comparison fails
    # honestly instead of allowing an accepted overlay to hide new engine work.
    rebuilt.extend(raw_bundles[index] for index in range(len(raw_bundles)) if index not in used_indexes)
    generated["bundles"] = rebuilt
    _reapply_accepted_rewrites(generated, accepted)
    return changed


def apply_accepted_numeric_edits(generated: dict, accepted: dict) -> int:
    """Apply only explicit estimator inputs/overrides, never copied outputs.

    Raw engine totals are calculated before this function. The accepted replay
    may then explain a delta using saved manual freight, sundry, labor, or sell
    price edits, while all derived costs/GPM/tax/totals are recalculated.
    """
    changed = 0
    for field in ("tax_rate", "gpm_pct", "textura_fee"):
        if field in accepted:
            old = generated.get(field)
            generated[field] = copy.deepcopy(accepted[field])
            if _money(old) != _money(accepted[field]):
                changed += 1

    accepted_bundles = [bundle for bundle in (accepted.get("bundles") or []) if isinstance(bundle, dict)]

    for bundle in generated.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        accepted_bundle = _find_accepted_bundle(bundle, accepted_bundles)
        if not accepted_bundle:
            continue

        for field in ("price_override", "freight_override"):
            value = accepted_bundle.get(field)
            if value is not None:
                old = bundle.get(field)
                bundle[field] = copy.deepcopy(value)
                if _money(old) != _money(value):
                    changed += 1
        for field in ("stair_count", "stair_labor_type"):
            value = accepted_bundle.get(field)
            if value not in (None, ""):
                old = bundle.get(field)
                bundle[field] = copy.deepcopy(value)
                if old != value:
                    changed += 1

        accepted_materials = {_material_key(item): item for item in (accepted_bundle.get("materials") or []) if isinstance(item, dict)}
        freight_delta = 0.0
        for material in bundle.get("materials") or []:
            accepted_material = accepted_materials.get(_material_key(material))
            if not accepted_material:
                continue
            accepted_freight_changed = bool(
                _money(accepted_material.get("freight_per_unit")) != _money(material.get("freight_per_unit"))
                or (
                    accepted_material.get("freight_cost") is not None
                    and _material_line_freight(accepted_material) != _material_line_freight(material)
                )
            )
            if not accepted_material.get("freight_is_manual") and not accepted_freight_changed:
                continue
            old_line_freight = _material_line_freight(material)
            accepted_line_freight = _material_line_freight(accepted_material)
            freight_delta = _money(freight_delta + accepted_line_freight - old_line_freight)
            for field in ("freight_per_unit", "freight_cost"):
                old = material.get(field)
                material[field] = accepted_line_freight if field == "freight_cost" else copy.deepcopy(accepted_material.get(field))
                if _money(old) != _money(material.get(field)):
                    changed += 1
            material["freight_is_manual"] = True
        if freight_delta:
            bundle["freight_cost"] = _money(_money(bundle.get("freight_cost")) + freight_delta)

        accepted_sundries = {
            _sundry_key(item): item
            for item in (accepted_bundle.get("sundry_items") or [])
            if isinstance(item, dict)
        }
        replayed_sundries = []
        generated_sundry_keys = set()
        for sundry in bundle.get("sundry_items") or []:
            key = _sundry_key(sundry)
            generated_sundry_keys.add(key)
            accepted_sundry = accepted_sundries.get(key)
            accepted_difference = bool(
                accepted_sundry
                and (
                    _num(accepted_sundry.get("qty")) != _num(sundry.get("qty"))
                    or str(accepted_sundry.get("unit") or "") != str(sundry.get("unit") or "")
                    or _money(accepted_sundry.get("unit_price")) != _money(sundry.get("unit_price"))
                    or _money(accepted_sundry.get("extended_cost")) != _money(sundry.get("extended_cost"))
                )
            )
            if accepted_sundry and (accepted_sundry.get("is_manual_price") or accepted_difference):
                old = (_num(sundry.get("qty")), str(sundry.get("unit") or ""), _money(sundry.get("unit_price")))
                sundry = copy.deepcopy(sundry)
                sundry["qty"] = copy.deepcopy(accepted_sundry.get("qty"))
                sundry["unit"] = copy.deepcopy(accepted_sundry.get("unit"))
                sundry["unit_price"] = copy.deepcopy(accepted_sundry.get("unit_price"))
                sundry["extended_cost"] = _money(_num(sundry.get("qty")) * _num(sundry.get("unit_price")))
                sundry["is_manual_price"] = True
                if old != (_num(sundry.get("qty")), str(sundry.get("unit") or ""), _money(sundry.get("unit_price"))):
                    changed += 1
            replayed_sundries.append(sundry)
        for key, accepted_sundry in accepted_sundries.items():
            if key not in generated_sundry_keys:
                replayed = copy.deepcopy(accepted_sundry)
                if not replayed.get("is_stair_sundry"):
                    replayed["is_manual_price"] = True
                replayed["extended_cost"] = _money(_num(replayed.get("qty")) * _num(replayed.get("unit_price")))
                replayed_sundries.append(replayed)
                changed += 1
        bundle["sundry_items"] = replayed_sundries
        if not bundle.get("is_derived"):
            bundle["sundry_cost"] = _money(sum(_money(item.get("extended_cost")) for item in replayed_sundries))

        generated_labor = [item for item in (bundle.get("labor_items") or []) if isinstance(item, dict)]
        generated_by_identity = {_labor_identity(item): item for item in generated_labor}
        manual_labor = []
        for accepted_labor in (accepted_bundle.get("labor_items") or []):
            if not isinstance(accepted_labor, dict):
                continue
            source_line = generated_by_identity.get(_labor_identity(accepted_labor))
            differs = bool(
                source_line is None
                or _num(accepted_labor.get("qty")) != _num(source_line.get("qty"))
                or _num(accepted_labor.get("rate")) != _num(source_line.get("rate"))
                or str(accepted_labor.get("unit") or "") != str(source_line.get("unit") or "")
            )
            if not (accepted_labor.get("is_manual") or accepted_labor.get("is_stair_labor") or differs):
                continue
            replayed = copy.deepcopy(accepted_labor)
            replayed["is_manual"] = True
            replayed["manual_source_key"] = replayed.get("manual_source_key") or _labor_line_key(source_line or replayed)
            replayed["extended_cost"] = _money(_num(replayed.get("qty")) * _num(replayed.get("rate")))
            manual_labor.append(replayed)

        manual_source_keys = {str(item.get("manual_source_key") or _labor_line_key(item)) for item in manual_labor}
        deleted_labor_keys = {str(key) for key in (accepted_bundle.get("deleted_labor_keys") or [])}
        kept_generated_labor = [
            item for item in generated_labor
            if _labor_line_key(item) not in manual_source_keys and _labor_line_key(item) not in deleted_labor_keys
        ]
        if manual_labor or deleted_labor_keys:
            bundle["labor_items"] = kept_generated_labor + manual_labor
            bundle["deleted_labor_keys"] = sorted(deleted_labor_keys)
            bundle["deleted_labor_reasons"] = copy.deepcopy(accepted_bundle.get("deleted_labor_reasons") or {})
            bundle["labor_cost"] = _money(sum(_money(item.get("extended_cost")) for item in bundle["labor_items"]))
            changed += len(manual_labor) + len(deleted_labor_keys)

    normalize_proposal_totals(generated)
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
    defaults = DEFAULT_TOLERANCE

    def threshold(key: str, fallback: float) -> float:
        try:
            value = float(tolerance.get(key, fallback))
            return value if math.isfinite(value) and value >= 0 else fallback
        except (TypeError, ValueError):
            return fallback

    pass_abs = threshold(f"{prefix}_pass_abs", defaults[f"{prefix}_pass_abs"])
    warn_abs = max(threshold(f"{prefix}_warn_abs", defaults[f"{prefix}_warn_abs"]), pass_abs)
    warn_pct = threshold(f"{prefix}_warn_pct", defaults[f"{prefix}_warn_pct"])
    abs_delta = abs(delta)
    pct_delta = abs_delta / abs(target) if target else float("inf")
    if abs_delta <= pass_abs:
        return "pass"
    if abs_delta <= warn_abs or (warn_pct and pct_delta <= warn_pct):
        return "warn"
    return "fail"


def compare_replay(
    generated: dict,
    snapshot: dict,
    tolerance: dict,
    *,
    target_proposal: dict | None = None,
    target_source: str | None = None,
) -> dict:
    accepted = target_proposal if isinstance(target_proposal, dict) else (snapshot.get("proposal_data") or {})
    if target_proposal is None:
        target_totals = snapshot.get("target_totals") or {}
        accepted_totals = snapshot.get("accepted_totals") or proposal_totals(accepted)
    else:
        target_totals = {}
        accepted_totals = proposal_totals(accepted)
    total_rows = []
    status = "pass"
    for field in PROPOSAL_TOTAL_FIELDS:
        target = _money(accepted_totals.get(field))
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
            "target_source": target_source or "accepted_proposal",
        })

    jr_total_rows = []
    for field in PROPOSAL_TOTAL_FIELDS:
        if field not in target_totals:
            continue
        target = _money(target_totals.get(field))
        actual = _money(generated.get(field))
        delta = round(actual - target, 2)
        jr_total_rows.append({
            "field": field,
            "target": target,
            "actual": actual,
            "delta": delta,
            "status": _money_status(delta, target, tolerance, "proposal"),
            "target_source": "jr",
        })

    accepted_bundles = [b for b in accepted.get("bundles") or [] if isinstance(b, dict)]
    generated_bundles = [b for b in generated.get("bundles") or [] if isinstance(b, dict)]
    if target_proposal is None:
        reference_bundles = [
            b for b in ((snapshot.get("raw_engine_proposal") or {}).get("bundles") or [])
            if isinstance(b, dict)
        ]
    else:
        reference_bundles = accepted_bundles
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

    accepted_bundle_reasons = accepted.get("deleted_bundle_reasons") or {}
    generated_bundle_reasons = generated.get("deleted_bundle_reasons") or {}
    if accepted_bundle_reasons != generated_bundle_reasons:
        structural.append({
            "check": "deleted_bundle_reasons",
            "status": "fail",
            "message": "Deleted bundle reasons changed.",
            "accepted": accepted_bundle_reasons,
            "actual": generated_bundle_reasons,
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

    accepted_deleted_reasons = accepted.get("deleted_material_reasons") or {}
    generated_deleted_reasons = generated.get("deleted_material_reasons") or {}
    if accepted_deleted_reasons != generated_deleted_reasons:
        structural.append({
            "check": "deleted_material_reasons",
            "status": "fail",
            "message": "Deleted material reasons changed.",
            "accepted": accepted_deleted_reasons,
            "actual": generated_deleted_reasons,
        })
        status = "fail"

    bundle_rows = []
    used_generated_indexes = set()
    for index, accepted_bundle in enumerate(accepted_bundles):
        name = accepted_bundle.get("bundle_name") or f"bundle:{index}"
        accepted_codes = _bundle_codes(accepted_bundle)
        candidate_indexes = [
            generated_index
            for generated_index, candidate in enumerate(generated_bundles)
            if generated_index not in used_generated_indexes
            and candidate.get("bundle_name") == accepted_bundle.get("bundle_name")
            and _bundle_codes(candidate) == accepted_codes
        ]
        if not candidate_indexes:
            candidate_indexes = [
                generated_index
                for generated_index, candidate in enumerate(generated_bundles)
                if generated_index not in used_generated_indexes
                and candidate.get("bundle_name") == accepted_bundle.get("bundle_name")
            ]
        if not candidate_indexes and accepted_codes:
            candidate_indexes = [
                generated_index
                for generated_index, candidate in enumerate(generated_bundles)
                if generated_index not in used_generated_indexes
                and _bundle_codes(candidate) == accepted_codes
            ]
        actual_index = candidate_indexes[0] if candidate_indexes else None
        actual_bundle = generated_bundles[actual_index] if actual_index is not None else None
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
        used_generated_indexes.add(actual_index)
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
        reference_bundle = _find_accepted_bundle(accepted_bundle, reference_bundles)
        accepted_manual_edits = _manual_edit_contract(accepted_bundle, reference_bundle)
        actual_manual_edits = _manual_edit_contract(actual_bundle, reference_bundle)
        if accepted_manual_edits != actual_manual_edits:
            structural.append({
                "check": "accepted_manual_edits",
                "status": "fail",
                "message": f"Accepted manual edits changed for {name}.",
                "bundle_name": name,
                "accepted": accepted_manual_edits,
                "actual": actual_manual_edits,
            })
            status = "fail"
        target_total = effective_bundle_total(accepted_bundle)
        actual_total = effective_bundle_total(actual_bundle)
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

    extra_names = [
        generated_bundles[index].get("bundle_name") or f"bundle:{index}"
        for index in range(len(generated_bundles))
        if index not in used_generated_indexes
    ]
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
        "jr_totals": jr_total_rows,
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
            "classification": "calculation_behavior_changed",
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
            "classification": "calculation_behavior_changed",
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


def _generate_raw_replay_proposal(
    snapshot: dict,
    *,
    rates: dict,
    labor_catalog: list[dict],
    config: dict,
    trace: AuditTraceBuilder,
) -> dict:
    """Calculate the deterministic engine result before accepted numeric edits."""
    job = _copy_jsonable(snapshot.get("job") or {})
    source_job_id = int(job.get("id") or 0)
    job["id"] = source_job_id
    job["materials"] = _copy_jsonable(snapshot.get("materials") or [])
    job["proposal_data"] = _copy_jsonable(snapshot.get("proposal_data") or {})

    # Proposal-editor controls are calculation inputs. Price/freight overrides,
    # manual lines, and deleted labor are applied only after raw proof.
    for field in ("tax_rate", "gpm_pct", "textura_fee"):
        if field in job["proposal_data"]:
            job[field] = copy.deepcopy(job["proposal_data"][field])

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
        labor_qty_rules_override=config.get("labor_qty_rules") or {},
        waste_factors_override=rates.get("waste_factors") or config.get("waste_factors") or {},
    )
    proposal = generate_proposal_data(
        source_job_id,
        job,
        trace=trace,
        freight_rates_override=rates.get("freight_rates") or config.get("freight_rates") or {},
    )
    _sync_editor_totals(proposal)
    _reapply_accepted_rewrites(proposal, job.get("proposal_data") or {})
    return proposal


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

    source_job_id = int(golden_job.get("source_job_id") or (snapshot.get("job") or {}).get("id") or 0)

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

    proposal = _generate_raw_replay_proposal(
        snapshot,
        rates=rates,
        labor_catalog=labor_catalog,
        config=config,
        trace=trace,
    )
    tolerance = {**DEFAULT_TOLERANCE, **(golden_job.get("tolerance") or snapshot.get("tolerance") or {})}
    raw_engine_target = snapshot.get("raw_engine_proposal")
    if isinstance(raw_engine_target, dict) and raw_engine_target.get("bundles"):
        engine_diff = compare_replay(
            copy.deepcopy(proposal),
            snapshot,
            tolerance,
            target_proposal=raw_engine_target,
            target_source="raw_engine_baseline",
        )
    else:
        comparability = "incomparable"
        engine_diff = {
            "status": "incomparable",
            "totals": [],
            "bundles": [],
            "structural": [{
                "check": "raw_engine_baseline",
                "status": "incomparable",
                "message": "This older baseline does not contain a captured raw-engine result. Capture a new version.",
            }],
        }
    accepted_structure_replay_count = apply_accepted_bundle_structure(proposal, snapshot.get("proposal_data") or {})
    if accepted_structure_replay_count:
        trace.record(
            entity_type="golden_replay",
            entity_id=golden_job.get("id"),
            entity_key=mode,
            output_field="accepted_bundle_structure",
            formula="rebuild accepted bundle order/grouping from raw engine bundles without copying accepted totals",
            inputs={"mode": mode},
            result=accepted_structure_replay_count,
            rule_id="golden_replay:accepted_bundle_structure",
            source="golden_replay",
        )
    accepted_money_replay_count = apply_accepted_numeric_edits(proposal, snapshot.get("proposal_data") or {})
    if accepted_money_replay_count:
        trace.record(
            entity_type="golden_replay",
            entity_id=golden_job.get("id"),
            entity_key=mode,
            output_field="accepted_numeric_edits",
            formula="reapply explicit saved estimator inputs and overrides, then recalculate derived totals",
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
    metadata_drift_count = len([
        row for row in diff["drift"]
        if row.get("classification") == "metadata_only"
    ])
    behavior_drift_count = len(diff["drift"]) - metadata_drift_count
    if engine_diff["status"] != "pass" or accepted_proposal_status != "pass":
        behavior_drift_count += 1
    drift_classification = (
        "calculation_behavior_changed" if behavior_drift_count
        else "metadata_only" if metadata_drift_count
        else "none"
    )
    jr_target_status = (
        _max_status(*(row.get("status", "pass") for row in diff.get("jr_totals") or []))
        if diff.get("jr_totals")
        else "not_compared"
    )
    summary = {
        "mode": mode,
        "status": diff["status"],
        "overall_status": diff["status"],
        "engine_status": engine_diff["status"],
        "raw_engine_status": engine_diff["status"],
        "accepted_proposal_status": accepted_proposal_status,
        "jr_target_status": jr_target_status,
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
        "accepted_structural_edit_count": accepted_structure_replay_count,
        "failing_structural_count": len([row for row in diff["structural"] if row.get("status") == "fail"]),
        "engine_failing_structural_count": len([row for row in engine_diff["structural"] if row.get("status") == "fail"]),
        "engine_warning_total_count": len([row for row in engine_diff["totals"] if row.get("status") == "warn"]),
        "engine_failing_total_count": len([row for row in engine_diff["totals"] if row.get("status") == "fail"]),
        "drift_count": len(diff["drift"]),
        "metadata_drift_count": metadata_drift_count,
        "behavior_drift_count": behavior_drift_count,
        "drift_classification": drift_classification,
        "warning_total_count": len([row for row in diff["totals"] if row.get("status") == "warn"]),
        "failing_total_count": len([row for row in diff["totals"] if row.get("status") == "fail"]),
    }
    proposal["replay"] = summary
    return {"summary": summary, "diff": diff, "proposal": proposal}, trace
