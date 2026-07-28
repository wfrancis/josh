#!/usr/bin/env python3
"""Deployed-only harness for deterministic material quote automation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any


class HarnessError(RuntimeError):
    pass


def request(
    base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 120,
) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HarnessError(f"{method} {path} failed ({exc.code}): {detail}") from exc
    return json.loads(raw) if raw else {}


def request_text(base_url: str, path: str, timeout: float = 120) -> str:
    req = urllib.request.Request(base_url.rstrip("/") + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HarnessError(f"GET {path} failed ({exc.code}): {detail}") from exc


def expect_http_status(
    base_url: str,
    method: str,
    path: str,
    expected_status: int,
    body: dict | None = None,
    timeout: float = 120,
) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            actual_status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        actual_status = exc.code
        raw = exc.read()
    if actual_status != expected_status:
        detail = raw.decode("utf-8", errors="replace")
        raise HarnessError(
            f"{method} {path} returned {actual_status}, expected "
            f"{expected_status}: {detail}"
        )
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"raw": raw.decode("utf-8", errors="replace")}
    return {"status": actual_status, "body": payload}


def fingerprint_job(job: dict) -> str:
    payload = {
        "id": job.get("id"),
        "project_name": job.get("project_name"),
        "proposal_data": job.get("proposal_data"),
        "materials": [
            {
                key: material.get(key)
                for key in (
                    "id",
                    "item_code",
                    "description",
                    "unit",
                    "order_qty",
                    "vendor",
                    "unit_price",
                    "price_source",
                    "quote_source_hash",
                )
            }
            for material in job.get("materials") or []
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def run(
    base_url: str,
    keep_job: bool,
    expected_commit: str | None = None,
) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:8]
    job_id = None
    vendor_id = None
    checks = []
    try:
        build = request(base_url, "GET", "/api/system/build")
        checks.append(
            {
                "name": "deployed_build",
                "passed": build.get("environment") == "staging"
                and build.get("commit") not in {None, "", "unknown"}
                and (
                    expected_commit is None
                    or build.get("commit") == expected_commit
                ),
                "details": {
                    "commit": build.get("commit"),
                    "expected_commit": expected_commit,
                    "environment": build.get("environment"),
                    "frontend_asset": build.get("frontend_asset"),
                    "runtime_fingerprint": build.get("runtime_fingerprint"),
                },
            }
        )
        outlook = request(base_url, "GET", "/api/integrations/outlook/status")
        if outlook.get("mode") != "staging":
            raise HarnessError(
                "Refusing destructive quote tests because QUOTE_AUTOMATION_MODE is not staging."
            )
        checks.append(
            {
                "name": "staging_guards",
                "passed": outlook.get("enabled") is True
                and outlook.get("configured") is True
                and outlook.get("mailbox_allowlist_count") == 1
                and outlook.get("test_recipient_allowlist_count") == 1
                and outlook.get("test_sender_allowlist_count") == 1
                and (outlook.get("mailbox_recheck") or {}).get(
                    "configured_mailbox_allowed"
                )
                is True
                and (outlook.get("mailbox_recheck") or {}).get(
                    "replacement_mailbox_blocked"
                )
                is True
                and (outlook.get("mailbox_recheck") or {}).get(
                    "checked_on_every_connection_use"
                )
                is True,
                "details": outlook,
            }
        )
        contract = request(
            base_url, "GET", "/api/system/deterministic-quote-contract"
        )
        checks.append(
            {
                "name": "deterministic_contract",
                "passed": contract.get("status") == "pass"
                and (contract.get("checks") or {}).get("ai_calls") == 0,
                "details": contract,
            }
        )

        vendor = request(
            base_url,
            "POST",
            "/api/vendors",
            {
                "name": f"Harness Quote Vendor {suffix}",
                "contact_name": "Harness Vendor",
                "contact_email": "wbfranci@gmail.com",
            },
        )
        vendor_id = vendor.get("id")
        created = request(
            base_url,
            "POST",
            "/api/jobs",
            {
                "project_name": f"Deterministic Quote Harness {suffix}",
                "gc_name": "Harness GC",
                "address": "123 Harness Street",
                "city": "Denver",
                "state": "CO",
                "zip": "80202",
                "notes": "Disposable deployed quote-automation harness job.",
            },
        )
        job_id = created["id"]
        request(
            base_url,
            "PUT",
            f"/api/jobs/{job_id}/materials",
            {
                "materials": [
                    {
                        "item_code": "CPT-TEST-100",
                        "description": "Harness Carpet Tile",
                        "material_type": "carpet_tile",
                        "installed_qty": 100,
                        "order_qty": 105,
                        "unit": "SY",
                        "vendor": vendor["name"],
                        "unit_price": 0,
                        "extended_cost": 0,
                    },
                    {
                        "item_code": "LVT-TEST-200",
                        "description": "Harness LVT",
                        "material_type": "lvt",
                        "installed_qty": 200,
                        "order_qty": 210,
                        "unit": "SF",
                        "vendor": vendor["name"],
                        "unit_price": 0,
                        "extended_cost": 0,
                    },
                ]
            },
        )
        before = request(base_url, "GET", f"/api/jobs/{job_id}")
        before_fingerprint = fingerprint_job(before)
        plan = request(base_url, "GET", f"/api/jobs/{job_id}/quotes/plan")
        groups = plan.get("groups") or []
        checks.append(
            {
                "name": "per_bid_quote_plan",
                "passed": len(groups) == 1
                and groups[0].get("can_send") is True
                and len(groups[0].get("materials_to_send") or []) == 2
                and (plan.get("matching_engine") or {}).get("ai_calls") == 0,
                "details": plan,
            }
        )
        hub_before = request(base_url, "GET", "/api/material-quotes/bids")
        initial_bid_summary = next(
            (
                bid
                for bid in hub_before.get("bids") or []
                if int(bid.get("job_id") or 0) == int(job_id)
            ),
            {},
        )
        draft_before = request(
            base_url,
            "GET",
            f"/api/jobs/{job_id}/quotes/email-draft",
        )
        checks.append(
            {
                "name": "hub_lists_unprepared_bid",
                "passed": initial_bid_summary.get("quote_stage") == "needs_setup"
                and draft_before.get("draft") is None
                and (hub_before.get("matching_engine") or {}).get("ai_calls") == 0,
                "details": initial_bid_summary,
            }
        )

        draft_payload = {
            "source_fingerprint": plan.get("source_fingerprint"),
            "prepared_by": "Harness Estimator",
            "groups": [
                {
                    "vendor_id": groups[0].get("vendor_id"),
                    "vendor_name": groups[0].get("vendor_name"),
                    "vendor_email": groups[0].get("vendor_email"),
                    "material_ids": [
                        item.get("id")
                        for item in groups[0].get("materials_to_send") or []
                    ],
                    "subject": groups[0].get("subject"),
                    "body": groups[0].get("body"),
                }
            ],
        }
        saved_draft = request(
            base_url,
            "PUT",
            f"/api/jobs/{job_id}/quotes/email-draft",
            draft_payload,
        )
        saved_group = ((saved_draft.get("draft") or {}).get("groups") or [{}])[0]
        group_id = saved_group.get("group_id")
        after_draft_save = request(base_url, "GET", f"/api/jobs/{job_id}")
        requests_after_save = request(
            base_url,
            "GET",
            f"/api/jobs/{job_id}/quote-requests",
        )
        checks.append(
            {
                "name": "draft_prepares_without_sending",
                "passed": saved_draft.get("status") == "saved"
                and saved_group.get("can_send") is True
                and bool(group_id)
                and requests_after_save == []
                and fingerprint_job(after_draft_save) == before_fingerprint
                and saved_draft.get("ai_calls") == 0,
                "details": {
                    "message": saved_draft.get("message"),
                    "group_id": group_id,
                    "request_count": len(requests_after_save),
                },
            }
        )

        patched_draft = request(
            base_url,
            "PATCH",
            f"/api/jobs/{job_id}/quotes/email-draft/groups/{group_id}",
            {
                "vendor_email": "wbfranci@gmail.com",
                "subject": f"Harness saved subject {suffix}",
                "body": f"Harness saved email body {suffix}",
            },
        )
        patched_group = ((patched_draft.get("draft") or {}).get("groups") or [{}])[0]
        center_locked = request(
            base_url,
            "GET",
            "/api/material-quotes/email-center",
        )
        center_draft = next(
            (
                draft
                for draft in center_locked.get("drafts") or []
                if int(draft.get("job_id") or 0) == int(job_id)
            ),
            {},
        )
        center_requests_for_job = [
            quote_request
            for quote_request in center_locked.get("requests") or []
            if int(quote_request.get("job_id") or 0) == int(job_id)
        ]
        hub_ready = request(base_url, "GET", "/api/material-quotes/bids")
        ready_bid_summary = next(
            (
                bid
                for bid in hub_ready.get("bids") or []
                if int(bid.get("job_id") or 0) == int(job_id)
            ),
            {},
        )
        checks.append(
            {
                "name": "email_center_reads_saved_bid_draft",
                "passed": patched_group.get("group_id") == group_id
                and patched_group.get("subject")
                == f"Harness saved subject {suffix}"
                and center_locked.get("mailbox_locked") is True
                and center_requests_for_job == []
                and center_draft.get("ready_group_count") == 1
                and ready_bid_summary.get("quote_stage") == "ready_to_send"
                and (center_locked.get("matching_engine") or {}).get("ai_calls") == 0,
                "details": {
                    "draft": center_draft,
                    "bid_summary": ready_bid_summary,
                    "new_bid_request_count": len(center_requests_for_job),
                    "saved_requests_from_other_bids": len(
                        center_locked.get("requests") or []
                    ),
                },
            }
        )
        disconnected_send = expect_http_status(
            base_url,
            "POST",
            f"/api/jobs/{job_id}/quotes/email-draft/send",
            401,
            {},
        )
        requests_after_blocked_send = request(
            base_url,
            "GET",
            f"/api/jobs/{job_id}/quote-requests",
        )
        checks.append(
            {
                "name": "outlook_required_to_send",
                "passed": disconnected_send["status"] == 401
                and requests_after_blocked_send == [],
                "details": disconnected_send,
            }
        )

        changed_materials = after_draft_save.get("materials") or []
        changed_materials[0] = {
            **changed_materials[0],
            "installed_qty": float(
                changed_materials[0].get("installed_qty") or 0
            )
            + 1,
            "order_qty": float(changed_materials[0].get("order_qty") or 0) + 1,
        }
        request(
            base_url,
            "PUT",
            f"/api/jobs/{job_id}/materials",
            {"materials": changed_materials},
        )
        stale_draft = request(
            base_url,
            "GET",
            f"/api/jobs/{job_id}/quotes/email-draft",
        ).get("draft") or {}
        stale_send = expect_http_status(
            base_url,
            "POST",
            f"/api/jobs/{job_id}/quotes/email-draft/send",
            409,
            {},
        )
        checks.append(
            {
                "name": "material_change_blocks_stale_draft",
                "passed": stale_draft.get("stale") is True
                and stale_send["status"] == 409
                and request(
                    base_url,
                    "GET",
                    f"/api/jobs/{job_id}/quote-requests",
                )
                == [],
                "details": {
                    "stale": stale_draft.get("stale"),
                    "send": stale_send,
                },
            }
        )

        refreshed_plan = request(
            base_url,
            "GET",
            f"/api/jobs/{job_id}/quotes/plan",
        )
        refreshed_group = (refreshed_plan.get("groups") or [{}])[0]
        refreshed_save = request(
            base_url,
            "PUT",
            f"/api/jobs/{job_id}/quotes/email-draft",
            {
                "source_fingerprint": refreshed_plan.get("source_fingerprint"),
                "prepared_by": "Harness Estimator",
                "groups": [
                    {
                        "vendor_id": refreshed_group.get("vendor_id"),
                        "vendor_name": refreshed_group.get("vendor_name"),
                        "vendor_email": refreshed_group.get("vendor_email"),
                        "material_ids": [
                            item.get("id")
                            for item in refreshed_group.get("materials_to_send") or []
                        ],
                        "subject": refreshed_group.get("subject"),
                        "body": refreshed_group.get("body"),
                    }
                ],
            },
        )
        refreshed_saved_group = (
            (refreshed_save.get("draft") or {}).get("groups") or [{}]
        )[0]
        checks.append(
            {
                "name": "draft_group_identity_survives_refresh",
                "passed": refreshed_saved_group.get("group_id") == group_id
                and (refreshed_save.get("draft") or {}).get("stale") is False,
                "details": {
                    "before_group_id": group_id,
                    "after_group_id": refreshed_saved_group.get("group_id"),
                },
            }
        )
        before = request(base_url, "GET", f"/api/jobs/{job_id}")
        before_fingerprint = fingerprint_job(before)
        simulation = request(
            base_url,
            "POST",
            f"/api/jobs/{job_id}/quote-simulator/runs",
            {"scenario": "all"},
        )
        run_id = simulation["id"]
        checks.append(
            {
                "name": "simulator_scenarios",
                "passed": simulation.get("status") == "pass"
                and (simulation.get("result") or {}).get("ai_calls") == 0
                and (simulation.get("result") or {}).get("live_job_mutated") is False,
                "details": simulation,
            }
        )
        simulator_labels = {
            str(item.get("label") or "")
            for item in (simulation.get("result") or {}).get("checks") or []
            if item.get("passed") is True
        }
        required_race_checks = {
            "Josh can explicitly choose the quote after the current price changed",
            "An old screen cannot overwrite a newer material price",
            "Cancelling a request also cancels its pending prices and follow-ups",
            "Removing an email from one bid keeps its other possible bid",
            "Ambiguous email can be assigned after inbox processing",
            "Interrupted assignment can retry the same exact bid",
            "A second live worker cannot price the same email",
            "An expired worker cannot write after a retry takes over",
            "Cancelling during assignment releases the email without keeping prices",
            "Changing bid materials during assignment makes the request stale",
            "A no-price email cannot reopen a cancelled request",
            "A stopped price read removes partial rows and keeps the candidate",
            "A rolled-back assignment removes its uncommitted job file",
            "Old received requests are treated as complete",
            "A last-second quantity or unit change blocks the follow-up",
        }
        checks.append(
            {
                "name": "race_and_legacy_regressions",
                "passed": required_race_checks <= simulator_labels,
                "details": {
                    "required": sorted(required_race_checks),
                    "passed": sorted(required_race_checks & simulator_labels),
                },
            }
        )
        advanced = request(
            base_url,
            "POST",
            f"/api/jobs/{job_id}/quote-simulator/runs/{run_id}/advance",
            {"business_days": 3},
        )
        timeline = (advanced.get("result") or {}).get("timeline") or []
        checks.append(
            {
                "name": "simulated_followup",
                "passed": sum(
                    1
                    for item in timeline
                    if "Follow-up 1 was previewed as due"
                    in str(item.get("event") or "")
                )
                == 1
                and advanced.get("status")
                == (advanced.get("result") or {}).get("status"),
                "details": {
                    "timeline": timeline,
                    "stored_status": advanced.get("status"),
                    "result_status": (advanced.get("result") or {}).get("status"),
                },
            }
        )
        advanced_again = request(
            base_url,
            "POST",
            f"/api/jobs/{job_id}/quote-simulator/runs/{run_id}/advance",
            {"business_days": 6},
        )
        followups = (advanced_again.get("result") or {}).get("followups") or []
        checks.append(
            {
                "name": "followups_exactly_once",
                "passed": len(followups) == 2
                and all(item.get("sent_count") == 1 for item in followups)
                and (advanced_again.get("result") or {}).get(
                    "followups_sent_once"
                )
                is True,
                "details": {"followups": followups},
            }
        )
        report = request_text(
            base_url,
            f"/api/jobs/{job_id}/quote-simulator/runs/{run_id}/report",
        )
        checks.append(
            {
                "name": "downloadable_report",
                "passed": "Material Quote Simulation Report" in report
                and "AI calls: 0" in report
                and "Real bid changed: NO" in report,
                "details": {"length": len(report)},
            }
        )
        after = request(base_url, "GET", f"/api/jobs/{job_id}")
        after_fingerprint = fingerprint_job(after)
        persisted_draft = request(
            base_url,
            "GET",
            f"/api/jobs/{job_id}/quotes/email-draft",
        ).get("draft") or {}
        checks.append(
            {
                "name": "live_job_unchanged",
                "passed": before_fingerprint == after_fingerprint,
                "details": {
                    "before": before_fingerprint,
                    "after": after_fingerprint,
                },
            }
        )
        checks.append(
            {
                "name": "draft_survives_other_workflows",
                "passed": persisted_draft.get("stale") is False
                and (
                    (persisted_draft.get("groups") or [{}])[0].get("group_id")
                    == group_id
                ),
                "details": {
                    "group_id": (
                        (persisted_draft.get("groups") or [{}])[0].get("group_id")
                    ),
                    "updated_at": persisted_draft.get("updated_at"),
                },
            }
        )
        legacy_create = expect_http_status(
            base_url,
            "POST",
            f"/api/jobs/{job_id}/quote-requests",
            410,
            {"vendor_name": vendor["name"], "material_ids": []},
        )
        legacy_clear = expect_http_status(
            base_url,
            "DELETE",
            f"/api/jobs/{job_id}/quotes",
            409,
        )
        checks.append(
            {
                "name": "legacy_unsafe_paths_blocked",
                "passed": legacy_create["status"] == 410
                and legacy_clear["status"] == 409,
                "details": {
                    "create_status": legacy_create["status"],
                    "clear_status": legacy_clear["status"],
                },
            }
        )
    finally:
        if job_id is not None and not keep_job:
            try:
                request(base_url, "DELETE", f"/api/jobs/{job_id}")
            except HarnessError:
                pass
        if vendor_id is not None:
            try:
                request(base_url, "DELETE", f"/api/vendors/{vendor_id}")
            except HarnessError:
                pass
    return {
        "status": "pass" if checks and all(item["passed"] for item in checks) else "fail",
        "scope": "deployed simulator and static safety checks only",
        "release_ready": False,
        "required_next": (
            "Complete the signed-in Outlook and Gmail workflow in Chrome before release."
        ),
        "base_url": base_url,
        "job_id": job_id,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--keep-job", action="store_true")
    parser.add_argument("--expected-commit")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    try:
        result = run(args.base_url, args.keep_job, args.expected_commit)
    except HarnessError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
