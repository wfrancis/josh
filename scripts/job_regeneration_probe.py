#!/usr/bin/env python3
"""Prove accepted proposal regeneration on a disposable staging job clone."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from rules_audit_harness import (
    Client,
    HarnessError,
    normalize_base_url,
    proposal_save_payload,
    summarize_proposal,
)


PRODUCTION_HOSTS = {"si-bid-tool.fly.dev", "www.si-bid-tool.fly.dev"}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def material_code(item: dict[str, Any]) -> str:
    return str(item.get("item_code") or item.get("id") or item.get("material_id") or "")


def money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def require_disposable_staging(
    client: Client,
    expected_commit: str | None,
) -> dict[str, Any]:
    hostname = (urlparse(client.base_url).hostname or "").lower()
    if (
        hostname in PRODUCTION_HOSTS
        or not hostname.endswith(".fly.dev")
        or ("stg" not in hostname and "staging" not in hostname)
    ):
        raise HarnessError(f"refusing mutation outside an explicitly named staging host: {hostname or 'unknown'}")
    _, build, _ = client.request("GET", "/api/system/build")
    if str(build.get("environment") or "").lower() != "staging":
        raise HarnessError("refusing mutation because /api/system/build does not report environment=staging")
    if expected_commit and build.get("commit") != expected_commit:
        raise HarnessError(
            f"deployed commit {build.get('commit')!r} does not match expected commit {expected_commit!r}"
        )
    return build


def remap_accepted_proposal(
    source_job: dict[str, Any],
    clone_job: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    proposal = copy.deepcopy(source_job.get("proposal_data") or {})
    clone_by_code = {
        str(material.get("item_code") or ""): material
        for material in (clone_job.get("materials") or [])
        if material.get("item_code")
    }
    source_id_to_code = {
        str(material.get("id")): str(material.get("item_code"))
        for material in (source_job.get("materials") or [])
        if material.get("id") is not None and material.get("item_code")
    }
    unmapped: list[dict[str, Any]] = []

    for bundle in proposal.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        for material in bundle.get("materials") or []:
            if not isinstance(material, dict):
                continue
            code = str(material.get("item_code") or "")
            old_id = material.get("id")
            if old_id is not None and code:
                source_id_to_code[str(old_id)] = code
            clone_material = clone_by_code.get(code)
            if not clone_material:
                unmapped.append({"kind": "material", "bundle": bundle.get("bundle_name"), "item_code": code})
                continue
            material["id"] = clone_material.get("id")
            material["job_id"] = clone_job.get("id")

    for bundle in proposal.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        for collection in ("sundry_items", "labor_items"):
            for item in bundle.get(collection) or []:
                if not isinstance(item, dict):
                    continue
                old_material_id = item.get("material_id")
                code = source_id_to_code.get(str(old_material_id))
                clone_material = clone_by_code.get(code or "")
                if old_material_id is not None and not clone_material:
                    unmapped.append({
                        "kind": collection,
                        "bundle": bundle.get("bundle_name"),
                        "material_id": old_material_id,
                        "item_code": code,
                    })
                    continue
                if clone_material:
                    item["material_id"] = clone_material.get("id")
                if "job_id" in item:
                    item["job_id"] = clone_job.get("id")
    return proposal, unmapped


def structure_contract(proposal: dict[str, Any]) -> dict[str, Any]:
    bundles = []
    for bundle in proposal.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        bundles.append({
            "bundle_name": bundle.get("bundle_name"),
            "description_text": bundle.get("description_text"),
            "material_codes": [material_code(item) for item in (bundle.get("materials") or [])],
            "price_override": bundle.get("price_override"),
            "freight_override": bundle.get("freight_override"),
            "stair_count": bundle.get("stair_count"),
            "stair_labor_type": bundle.get("stair_labor_type"),
        })
    return {
        "bundles": bundles,
        "notes": proposal.get("notes") or [],
        "terms": proposal.get("terms") or [],
        "exclusions": proposal.get("exclusions") or [],
        "deleted_bundles": proposal.get("deleted_bundles") or [],
        "deleted_bundle_reasons": proposal.get("deleted_bundle_reasons") or {},
        "deleted_material_codes": proposal.get("deleted_material_codes") or [],
        "deleted_material_reasons": proposal.get("deleted_material_reasons") or {},
    }


def structure_differences(
    accepted: dict[str, Any],
    regenerated: dict[str, Any],
) -> list[dict[str, Any]]:
    differences = []
    accepted_bundles = accepted.get("bundles") or []
    regenerated_bundles = regenerated.get("bundles") or []
    if len(accepted_bundles) != len(regenerated_bundles):
        differences.append({
            "field": "bundle_count",
            "accepted": len(accepted_bundles),
            "regenerated": len(regenerated_bundles),
        })
    for index in range(max(len(accepted_bundles), len(regenerated_bundles))):
        accepted_bundle = accepted_bundles[index] if index < len(accepted_bundles) else None
        regenerated_bundle = regenerated_bundles[index] if index < len(regenerated_bundles) else None
        if accepted_bundle != regenerated_bundle:
            differences.append({
                "field": "bundle",
                "index": index,
                "accepted": accepted_bundle,
                "regenerated": regenerated_bundle,
            })
    for field in (
        "notes",
        "terms",
        "exclusions",
        "deleted_bundles",
        "deleted_bundle_reasons",
        "deleted_material_codes",
        "deleted_material_reasons",
    ):
        if accepted.get(field) != regenerated.get(field):
            differences.append({
                "field": field,
                "accepted": accepted.get(field),
                "regenerated": regenerated.get(field),
            })
    return differences


def explicit_manual_contract(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for bundle in proposal.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        bundle_name = bundle.get("bundle_name")
        for field in ("price_override", "freight_override", "stair_count", "stair_labor_type"):
            if bundle.get(field) not in (None, ""):
                entries.append({"kind": "bundle", "bundle": bundle_name, "field": field, "value": bundle.get(field)})
        for material in bundle.get("materials") or []:
            if isinstance(material, dict) and material.get("freight_is_manual"):
                entries.append({
                    "kind": "material_freight",
                    "bundle": bundle_name,
                    "item_code": material_code(material),
                    "freight_per_unit": material.get("freight_per_unit"),
                    "freight_cost": material.get("freight_cost"),
                })
        for sundry in bundle.get("sundry_items") or []:
            if isinstance(sundry, dict) and sundry.get("is_manual_price"):
                entries.append({
                    "kind": "sundry",
                    "bundle": bundle_name,
                    "material_id": sundry.get("material_id"),
                    "name": sundry.get("sundry_name"),
                    "qty": sundry.get("qty"),
                    "unit": sundry.get("unit"),
                    "unit_price": sundry.get("unit_price"),
                })
        for labor in bundle.get("labor_items") or []:
            if isinstance(labor, dict) and (labor.get("is_manual") or labor.get("is_stair_labor")):
                entries.append({
                    "kind": "labor",
                    "bundle": bundle_name,
                    "material_id": labor.get("material_id"),
                    "description": labor.get("labor_description"),
                    "qty": labor.get("qty"),
                    "unit": labor.get("unit"),
                    "rate": labor.get("rate"),
                    "is_stair_labor": bool(labor.get("is_stair_labor")),
                })
        for key in bundle.get("deleted_labor_keys") or []:
            entries.append({
                "kind": "deleted_labor",
                "bundle": bundle_name,
                "key": key,
                "reason": (bundle.get("deleted_labor_reasons") or {}).get(str(key)),
            })
    return sorted(entries, key=lambda entry: json.dumps(entry, sort_keys=True, default=str))


def money_deltas(accepted: dict[str, Any], regenerated: dict[str, Any]) -> list[dict[str, Any]]:
    accepted_bundles = accepted.get("bundles") or []
    regenerated_bundles = regenerated.get("bundles") or []
    component_fields = (
        "material_cost",
        "sundry_cost",
        "labor_cost",
        "freight_cost",
        "gpm_labor_adder",
        "gpm_material_adder",
        "tax_amount",
    )
    rows = []
    for index, accepted_bundle in enumerate(accepted_bundles):
        regenerated_bundle = regenerated_bundles[index] if index < len(regenerated_bundles) else {}
        accepted_total = money(
            accepted_bundle.get("price_override")
            if accepted_bundle.get("price_override") is not None
            else accepted_bundle.get("total_price")
        )
        regenerated_total = money(
            regenerated_bundle.get("price_override")
            if regenerated_bundle.get("price_override") is not None
            else regenerated_bundle.get("total_price")
        )
        row = {
            "bundle_name": accepted_bundle.get("bundle_name"),
            "accepted_total": accepted_total,
            "regenerated_total": regenerated_total,
            "delta": round(regenerated_total - accepted_total, 2),
        }
        for field in component_fields:
            accepted_value = money(accepted_bundle.get(field))
            regenerated_value = money(regenerated_bundle.get(field))
            row[field] = {
                "accepted": accepted_value,
                "regenerated": regenerated_value,
                "delta": round(regenerated_value - accepted_value, 2),
            }
        rows.append(row)
    return sorted(rows, key=lambda row: abs(row["delta"]), reverse=True)


def bundle_signature(bundle: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(material_code(item) for item in (bundle.get("materials") or []) if material_code(item)))


def bundle_line_summary(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bundle:
        return None
    return {
        "bundle_name": bundle.get("bundle_name"),
        "costs": {
            field: money(bundle.get(field))
            for field in ("material_cost", "sundry_cost", "labor_cost", "freight_cost", "total_price")
        },
        "materials": [
            {
                "item_code": material_code(item),
                "order_qty": item.get("order_qty"),
                "unit": item.get("unit"),
                "unit_price": item.get("unit_price"),
                "extended_cost": item.get("extended_cost"),
            }
            for item in (bundle.get("materials") or [])
            if isinstance(item, dict)
        ],
        "sundries": [
            {
                "material_id": item.get("material_id"),
                "name": item.get("sundry_name"),
                "qty": item.get("qty"),
                "unit": item.get("unit"),
                "unit_price": item.get("unit_price"),
                "extended_cost": item.get("extended_cost"),
                "is_manual_price": bool(item.get("is_manual_price")),
            }
            for item in (bundle.get("sundry_items") or [])
            if isinstance(item, dict)
        ],
        "labor": [
            {
                "material_id": item.get("material_id"),
                "description": item.get("labor_description"),
                "qty": item.get("qty"),
                "unit": item.get("unit"),
                "rate": item.get("rate"),
                "extended_cost": item.get("extended_cost"),
                "is_manual": bool(item.get("is_manual")),
                "is_stair_labor": bool(item.get("is_stair_labor")),
            }
            for item in (bundle.get("labor_items") or [])
            if isinstance(item, dict)
        ],
    }


def changed_bundle_line_details(
    accepted: dict[str, Any],
    raw_engine: dict[str, Any],
    regenerated: dict[str, Any],
    deltas: list[dict[str, Any]],
    limit: int = 12,
) -> list[dict[str, Any]]:
    accepted_bundles = accepted.get("bundles") or []
    regenerated_bundles = regenerated.get("bundles") or []
    raw_bundles = [bundle for bundle in (raw_engine.get("bundles") or []) if isinstance(bundle, dict)]
    raw_by_signature: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for bundle in raw_bundles:
        signature = bundle_signature(bundle)
        if signature:
            raw_by_signature.setdefault(signature, []).append(bundle)

    rows = []
    for delta in [row for row in deltas if abs(row.get("delta") or 0) >= 0.01][:limit]:
        index = next(
            (
                candidate_index
                for candidate_index, bundle in enumerate(accepted_bundles)
                if bundle.get("bundle_name") == delta.get("bundle_name")
            ),
            None,
        )
        if index is None:
            continue
        accepted_bundle = accepted_bundles[index]
        regenerated_bundle = regenerated_bundles[index] if index < len(regenerated_bundles) else None
        signature = bundle_signature(accepted_bundle)
        raw_candidates = raw_by_signature.get(signature, []) if signature else []
        named_raw = [bundle for bundle in raw_candidates if bundle.get("bundle_name") == accepted_bundle.get("bundle_name")]
        raw_bundle = named_raw[0] if len(named_raw) == 1 else (raw_candidates[0] if len(raw_candidates) == 1 else None)
        if not raw_bundle and not signature:
            named = [bundle for bundle in raw_bundles if bundle.get("bundle_name") == accepted_bundle.get("bundle_name")]
            raw_bundle = named[0] if len(named) == 1 else None
        rows.append({
            "bundle_name": delta.get("bundle_name"),
            "total_delta": delta.get("delta"),
            "accepted": bundle_line_summary(accepted_bundle),
            "raw_engine": bundle_line_summary(raw_bundle),
            "regenerated": bundle_line_summary(regenerated_bundle),
        })
    return rows


def readiness_summary(readiness: dict[str, Any]) -> dict[str, Any]:
    checks = readiness.get("checks") or []
    return {
        "status": readiness.get("status"),
        "blocking_count": readiness.get("blocking_count"),
        "warning_count": readiness.get("warning_count"),
        "blocking_checks": [
            {
                "id": check.get("id"),
                "message": check.get("message"),
                "affected_items": check.get("affected_items") or [],
            }
            for check in checks
            if check.get("status") == "fail"
        ],
        "warning_checks": [
            {
                "id": check.get("id"),
                "message": check.get("message"),
                "affected_items": check.get("affected_items") or [],
            }
            for check in checks
            if check.get("status") == "warn"
        ],
        "trust_summary": readiness.get("trust_summary") or {},
    }


def write_result(path: str | None, result: dict[str, Any]) -> None:
    if not path:
        return
    output_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Disposable deployed Fly staging URL")
    parser.add_argument("--source-job", default="sun-valley-block-2", help="Source job ID or slug")
    parser.add_argument("--expected-commit", help="Exact commit required from /api/system/build")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--json-output")
    args = parser.parse_args()

    client = Client(normalize_base_url(args.base_url), args.timeout, {})
    result: dict[str, Any] = {
        "base_url": client.base_url,
        "source_job": args.source_job,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL",
    }
    clone_id: str | None = None
    source_before: dict[str, Any] | None = None
    source_before_hash: str | None = None
    operation_error: str | None = None
    cleanup_error: str | None = None

    try:
        result["build"] = require_disposable_staging(client, args.expected_commit)
        _, source_before, _ = client.request("GET", f"/api/jobs/{args.source_job}")
        source_before_hash = canonical_hash(source_before)
        result["source_before_hash"] = source_before_hash
        source_proposal = source_before.get("proposal_data") or {}
        if not source_proposal.get("bundles"):
            raise HarnessError("source job has no accepted proposal bundles")
        _, source_readiness, _ = client.request("GET", f"/api/jobs/{args.source_job}/readiness")
        result["source_readiness"] = readiness_summary(source_readiness)

        _, duplicate, _ = client.request("POST", f"/api/jobs/{args.source_job}/duplicate")
        clone_id = str(duplicate.get("id") or "")
        if not clone_id:
            raise HarnessError("duplicate endpoint did not return a clone ID")
        result["clone"] = duplicate

        client.request("POST", f"/api/jobs/{clone_id}/calculate")
        _, clone_job, _ = client.request("GET", f"/api/jobs/{clone_id}")
        accepted, unmapped = remap_accepted_proposal(source_before, clone_job)
        result["identity_remap"] = {
            "source_material_count": len(source_before.get("materials") or []),
            "clone_material_count": len(clone_job.get("materials") or []),
            "unmapped": unmapped,
        }
        if unmapped:
            raise HarnessError(f"could not remap {len(unmapped)} accepted proposal row(s) to the clone")

        _, raw_engine, _ = client.request("POST", f"/api/jobs/{clone_id}/proposal/generate")
        result["raw_engine_totals"] = summarize_proposal(raw_engine)
        result["raw_engine_bundle_count"] = len(raw_engine.get("bundles") or [])

        _, seeded, _ = client.request(
            "PUT",
            f"/api/jobs/{clone_id}/proposal/bundles",
            json_body=proposal_save_payload(accepted),
        )
        accepted = seeded.get("proposal_data") or accepted
        _, regenerated, _ = client.request("POST", f"/api/jobs/{clone_id}/proposal/generate")

        accepted_structure = structure_contract(accepted)
        regenerated_structure = structure_contract(regenerated)
        accepted_manual = explicit_manual_contract(accepted)
        regenerated_manual = explicit_manual_contract(regenerated)
        regenerated_manual_keys = {json.dumps(entry, sort_keys=True, default=str) for entry in regenerated_manual}
        missing_manual = [
            entry
            for entry in accepted_manual
            if json.dumps(entry, sort_keys=True, default=str) not in regenerated_manual_keys
        ]
        structural_match = accepted_structure == regenerated_structure
        result["regeneration_contract"] = {
            "structural_match": structural_match,
            "accepted_bundle_count": len(accepted_structure["bundles"]),
            "regenerated_bundle_count": len(regenerated_structure["bundles"]),
            "accepted_manual_entries": accepted_manual,
            "regenerated_manual_entries": regenerated_manual,
            "missing_manual_entries": missing_manual,
            "accepted_structure_hash": canonical_hash(accepted_structure),
            "regenerated_structure_hash": canonical_hash(regenerated_structure),
            "structure_differences": structure_differences(accepted_structure, regenerated_structure),
        }
        result["accepted_totals"] = summarize_proposal(accepted)
        result["regenerated_totals"] = summarize_proposal(regenerated)
        result["total_delta"] = round(
            money(regenerated.get("grand_total")) - money(accepted.get("grand_total")),
            2,
        )
        result["raw_engine_to_accepted_delta"] = round(
            money(accepted.get("grand_total")) - money(raw_engine.get("grand_total")),
            2,
        )
        result["accepted_overlay_to_raw_engine_delta"] = round(
            money(regenerated.get("grand_total")) - money(raw_engine.get("grand_total")),
            2,
        )
        bundle_deltas = money_deltas(accepted, regenerated)
        result["bundle_money_deltas"] = bundle_deltas
        result["changed_bundle_lines"] = changed_bundle_line_details(
            accepted,
            raw_engine,
            regenerated,
            bundle_deltas,
        )

        _, saved, _ = client.request(
            "PUT",
            f"/api/jobs/{clone_id}/proposal/bundles",
            json_body=proposal_save_payload(regenerated),
        )
        result["saved_clone_proposal_hash"] = canonical_hash(saved.get("proposal_data") or {})
        _, clone_readiness, _ = client.request("GET", f"/api/jobs/{clone_id}/readiness")
        result["clone_readiness"] = readiness_summary(clone_readiness)

        _, source_during, _ = client.request("GET", f"/api/jobs/{args.source_job}")
        source_during_hash = canonical_hash(source_during)
        result["source_during_hash"] = source_during_hash
        result["source_unchanged_during_probe"] = source_during_hash == source_before_hash
        mechanics_pass = (
            structural_match
            and not missing_manual
            and len(regenerated.get("bundles") or []) == len(accepted.get("bundles") or [])
            and source_during_hash == source_before_hash
        )
        result["mechanics_status"] = "PASS" if mechanics_pass else "FAIL"
        if not mechanics_pass:
            raise HarnessError("Sun Valley regeneration contract did not pass")
    except Exception as exc:
        operation_error = f"{type(exc).__name__}: {exc}"
    finally:
        if clone_id:
            try:
                client.request("DELETE", f"/api/jobs/{clone_id}")
                deleted_status, _, _ = client.get_optional(f"/api/jobs/{clone_id}")
                result["clone_cleanup"] = {"status": deleted_status, "deleted": deleted_status == 404}
                if deleted_status != 404:
                    cleanup_error = f"clone {clone_id} still returned HTTP {deleted_status} after deletion"
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
        if source_before is not None and source_before_hash:
            try:
                _, source_after, _ = client.request("GET", f"/api/jobs/{args.source_job}")
                source_after_hash = canonical_hash(source_after)
                result["source_after_hash"] = source_after_hash
                result["source_unchanged_after_cleanup"] = source_after_hash == source_before_hash
            except Exception as exc:
                result["source_after_error"] = f"{type(exc).__name__}: {exc}"

    result["operation_error"] = operation_error
    result["cleanup_error"] = cleanup_error
    passed = (
        operation_error is None
        and cleanup_error is None
        and result.get("mechanics_status") == "PASS"
        and result.get("source_unchanged_after_cleanup") is True
        and (result.get("clone_cleanup") or {}).get("deleted") is True
    )
    result["status"] = "PASS" if passed else "FAIL"
    write_result(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
