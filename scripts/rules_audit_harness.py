#!/usr/bin/env python3
"""
Rules/audit deployed-environment harness.

This script intentionally targets an already-deployed SI Bid Tool base URL.
It does not start or require local app services.
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import os
import random
import string
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_FIXTURE = os.path.join(ROOT, "test_data", "rules_audit", "josh_lessons_cases.json")

FORMAL_REGISTRY_ENDPOINTS = [
    "/api/rules/registry",
    "/api/rule-registry",
    "/api/rules",
    "/api/audit/rules",
    "/api/pricing-rules/registry",
]

LEGACY_REGISTRY_ENDPOINTS = [
    "/api/company-rates",
    "/api/labor-catalog",
]

RULE_EVAL_ENDPOINTS = [
    "/api/rules/evaluate",
    "/api/rules/test",
    "/api/rules/material",
    "/api/rule-registry/evaluate",
]

AUDIT_ENDPOINTS = [
    "/api/jobs/{job_id}/audit",
    "/api/jobs/{job_id}/proposal/audit",
    "/api/jobs/{job_id}/rules/audit",
    "/api/jobs/{job_id}/calculation-audit",
]


@dataclass
class Check:
    name: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


class HarnessError(Exception):
    pass


class Client:
    def __init__(self, base_url: str, timeout: float, headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {}

    def url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        ok_statuses: tuple[int, ...] = (200,),
    ) -> tuple[int, Any, str]:
        req_headers = dict(self.headers)
        if headers:
            req_headers.update(headers)
        data = body
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.url(path), data=data, headers=req_headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = self._parse_json(raw)
                status = resp.getcode()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            parsed = self._parse_json(raw)
            status = exc.code
        except urllib.error.URLError as exc:
            raise HarnessError(f"{method} {path} failed: {exc}") from exc

        if ok_statuses and status not in ok_statuses:
            snippet = raw[:500].replace("\n", " ")
            raise HarnessError(f"{method} {path} returned HTTP {status}: {snippet}")
        return status, parsed, raw

    def get_optional(self, path: str) -> tuple[int, Any, str]:
        return self.request("GET", path, ok_statuses=())

    def post_multipart(
        self,
        path: str,
        *,
        fields: dict[str, str] | None = None,
        files: list[tuple[str, str, str, bytes]],
    ) -> tuple[int, Any, str]:
        boundary = "----rules-audit-" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for name, value in (fields or {}).items():
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            chunks.append(str(value).encode("utf-8"))
            chunks.append(b"\r\n")
        for field_name, filename, content_type, content in files:
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
            )
            chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
            chunks.append(content)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        return self.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    @staticmethod
    def _parse_json(raw: str) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None


def now_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def load_fixture(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_cell(ref: str, value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def make_sheet(rows: list[list[Any]]) -> str:
    row_xml = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            col = ""
            n = c_idx
            while n:
                n, rem = divmod(n - 1, 26)
                col = chr(65 + rem) + col
            cells.append(make_cell(f"{col}{r_idx}", value))
        row_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def build_rfms_workbook(fixture: dict[str, Any]) -> bytes:
    customer_rows = [
        ["Project", fixture.get("name", "Rules Audit Harness")],
        ["Contractor", fixture.get("job", {}).get("gc_name", "Harness QA")],
        ["City", fixture.get("job", {}).get("city", "")],
        ["State", fixture.get("job", {}).get("state", "")],
    ]
    by_item_rows = [["DESCRIPTION", "QUANTITY", "LINE TOTAL"]]
    for row in fixture["rfms_rows"]:
        qty = float(row.get("quantity", 0))
        by_item_rows.append([row["description"], qty, 0])
    by_item_rows.append(["Grand Total", 1, 0])

    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>"
            '<sheet name="Customer" sheetId="1" r:id="rId1"/>'
            '<sheet name="By Item" sheetId="2" r:id="rId2"/>'
            "</sheets>"
            "</workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": make_sheet(customer_rows),
        "xl/worksheets/sheet2.xml": make_sheet(by_item_rows),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>'
        ),
    }

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return out.getvalue()


def normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def parse_headers(items: list[str]) -> dict[str, str]:
    headers = {}
    for item in items:
        if ":" not in item:
            raise SystemExit(f"Invalid header {item!r}; expected 'Name: value'")
        name, value = item.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


def find_material(materials: list[dict[str, Any]], item_code: str) -> dict[str, Any] | None:
    wanted = item_code.upper()
    for mat in materials:
        if (mat.get("item_code") or "").upper() == wanted:
            return mat
    return None


def material_id_value(mat: dict[str, Any]) -> Any:
    return mat.get("id") or mat.get("item_code")


def related_labor(labor_items: list[dict[str, Any]], mat: dict[str, Any]) -> list[dict[str, Any]]:
    mid = material_id_value(mat)
    mid_s = str(mid)
    return [l for l in labor_items if str(l.get("material_id")) == mid_s]


def find_bundle_with_code(bundles: list[dict[str, Any]], item_code: str) -> dict[str, Any] | None:
    wanted = item_code.upper()
    for bundle in bundles:
        for mat in bundle.get("materials") or []:
            if (mat.get("item_code") or "").upper() == wanted:
                return bundle
    return None


def recursive_pick_trace_payloads(obj: Any) -> list[Any]:
    payloads = []
    trace_words = ("audit", "trace", "explain", "explanation", "rule_trace", "calculation_trace")

    def walk(value: Any, key_hint: str = "") -> None:
        key_lower = key_hint.lower()
        if any(word in key_lower for word in trace_words):
            payloads.append(value)
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, key_hint)

    walk(obj)
    return payloads


def iter_trace_rows(payloads: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(value: Any, key_hint: str = "") -> None:
        if isinstance(value, dict):
            if value.get("entity_type") and value.get("output_field"):
                rows.append(value)
            for key in ("traces", "events", "calculation_trace", "audit_trace", "audit_traces"):
                nested = value.get(key)
                if isinstance(nested, list):
                    for item in nested:
                        walk(item, key)
            if key_hint in ("audit", "trace", "events"):
                for nested in value.values():
                    walk(nested, key_hint)
        elif isinstance(value, list):
            for item in value:
                walk(item, key_hint)

    for payload in payloads:
        walk(payload)
    return rows


def audit_categories_present(payloads: list[Any], categories: list[str]) -> dict[str, bool]:
    rows = iter_trace_rows(payloads)
    result = {category: False for category in categories}
    for row in rows:
        entity = str(row.get("entity_type") or "").lower()
        field = str(row.get("output_field") or "").lower()
        if entity == "material" and field in ("order_qty", "extended_cost"):
            result["material"] = True
        if entity == "sundry" and field in ("qty", "extended_cost", "freight_cost"):
            result["sundry"] = True
        if entity == "labor" and field in ("qty", "extended_cost"):
            result["labor"] = True
        if field in ("taxable", "tax_amount") and entity in ("bundle", "proposal"):
            result["tax"] = True
        if field in ("gpm_profit", "gpm_adder", "gpm_labor_adder", "gpm_material_adder"):
            result["gpm"] = True
    return {category: result.get(category, False) for category in categories}


def almost_equal(a: float, b: float, tolerance: float = 0.02) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def sum_bundle_field(bundles: list[dict[str, Any]], field_name: str) -> float:
    return round(sum(float(b.get(field_name) or 0) for b in bundles), 2)


def try_rule_registry(client: Client) -> Check:
    formal_hits = []
    legacy_hits = []

    for path in FORMAL_REGISTRY_ENDPOINTS:
        status, parsed, _ = client.get_optional(path)
        if status == 200 and parsed is not None:
            formal_hits.append({"path": path, "keys": sorted(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__})

    if formal_hits:
        return Check(
            "rule_registry",
            "PASS",
            f"formal registry available at {formal_hits[0]['path']}",
            {"formal_hits": formal_hits},
        )

    for path in LEGACY_REGISTRY_ENDPOINTS:
        status, parsed, _ = client.get_optional(path)
        if status == 200 and parsed is not None:
            detail: dict[str, Any] = {"path": path}
            if isinstance(parsed, dict):
                detail["keys"] = sorted(parsed.keys())
                if "count" in parsed:
                    detail["count"] = parsed.get("count")
            legacy_hits.append(detail)

    if len(legacy_hits) == len(LEGACY_REGISTRY_ENDPOINTS):
        return Check(
            "rule_registry",
            "PASS",
            "legacy rule surfaces available; no formal registry endpoint found",
            {"formal_endpoints_tried": FORMAL_REGISTRY_ENDPOINTS, "legacy_hits": legacy_hits},
        )

    return Check(
        "rule_registry",
        "FAIL",
        "no rule registry surface was reachable",
        {
            "formal_endpoints_tried": FORMAL_REGISTRY_ENDPOINTS,
            "legacy_endpoints_tried": LEGACY_REGISTRY_ENDPOINTS,
            "legacy_hits": legacy_hits,
        },
    )


def try_rule_eval(client: Client, fixture: dict[str, Any]) -> Check:
    cases = []
    for item_code, expected in fixture.get("expected_materials", {}).items():
        desc = None
        for row in fixture.get("rfms_rows", []):
            if row["description"].upper().startswith(item_code.upper()):
                desc = row["description"]
                break
        if not desc:
            continue
        cases.append({"item_code": item_code, "description": desc, "expected": expected})

    for endpoint in RULE_EVAL_ENDPOINTS:
        endpoint_results = []
        had_200 = False
        for case in cases:
            payload = {
                "case_id": case["item_code"],
                "material": {
                    "item_code": case["item_code"],
                    "description": case["description"],
                    "material_type": "unknown",
                    "installed_qty": 1,
                    "unit": "SF",
                },
            }
            try:
                status, parsed, raw = client.request("POST", endpoint, json_body=payload, ok_statuses=())
            except HarnessError as exc:
                endpoint_results.append({"case_id": case["item_code"], "error": str(exc)})
                continue
            if status != 200:
                endpoint_results.append({"case_id": case["item_code"], "status": status})
                continue
            had_200 = True
            endpoint_results.append(validate_rule_eval_response(case, parsed, raw))
        if had_200:
            failed = [r for r in endpoint_results if r.get("status") == "FAIL"]
            return Check(
                "rule_eval_endpoint",
                "FAIL" if failed else "PASS",
                f"rule evaluator exercised at {endpoint}",
                {"endpoint": endpoint, "cases": endpoint_results},
            )

    return Check(
        "rule_eval_endpoint",
        "WARN",
        "no standalone rule evaluator endpoint found; parser/proposal path will cover available behavior",
        {"endpoints_tried": RULE_EVAL_ENDPOINTS},
    )


def validate_rule_eval_response(case: dict[str, Any], parsed: Any, raw: str) -> dict[str, Any]:
    text = raw.lower()
    expected = case["expected"]
    failures = []
    if "material_type" in expected and expected["material_type"] not in text:
        failures.append(f"expected material_type {expected['material_type']}")
    if "is_mosaic" in expected:
        expected_bool = bool(expected["is_mosaic"])
        found_bool = None
        if isinstance(parsed, dict):
            for key in ("is_mosaic", "mosaic"):
                if key in parsed:
                    found_bool = bool(parsed[key])
            material = parsed.get("material") or parsed.get("result") if isinstance(parsed, dict) else None
            if isinstance(material, dict):
                for key in ("is_mosaic", "mosaic"):
                    if key in material:
                        found_bool = bool(material[key])
        if found_bool is not None and found_bool != expected_bool:
            failures.append(f"expected is_mosaic={expected_bool}, got {found_bool}")
    return {
        "case_id": case["item_code"],
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "response_keys": sorted(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__,
    }


def create_or_use_job(client: Client, fixture: dict[str, Any], job_id: str | None) -> tuple[str, bool, Check]:
    if job_id:
        status, parsed, _ = client.request("GET", f"/api/jobs/{job_id}")
        return str(parsed.get("id", job_id)), False, Check("job", "PASS", f"using existing job {job_id}", {"job": summarize_job(parsed)})

    suffix = now_label() + "-" + "".join(random.choice(string.ascii_lowercase) for _ in range(4))
    job_cfg = fixture.get("job", {})
    payload = {
        "project_name": f"{job_cfg.get('project_name_prefix', 'Rules Audit Harness')} {suffix}",
        "gc_name": job_cfg.get("gc_name", "Harness QA"),
        "city": job_cfg.get("city", ""),
        "state": job_cfg.get("state", ""),
        "tax_rate": float(job_cfg.get("tax_rate", 0)),
        "gpm_pct": float(job_cfg.get("gpm_pct", 0)),
        "notes": "Created by scripts/rules_audit_harness.py against a deployed environment.",
    }
    _, parsed, _ = client.request("POST", "/api/jobs", json_body=payload)
    new_id = str(parsed["id"])
    return new_id, True, Check("job", "PASS", f"created test job {new_id}", {"create_payload": payload, "response": parsed})


def summarize_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "slug": job.get("slug"),
        "project_name": job.get("project_name"),
        "material_count": len(job.get("materials") or []),
        "tax_rate": job.get("tax_rate"),
        "gpm_pct": job.get("gpm_pct"),
    }


def upload_rfms_fixture(client: Client, job_id: str, fixture: dict[str, Any]) -> tuple[list[dict[str, Any]], Check]:
    workbook = build_rfms_workbook(fixture)
    filename = f"rules_audit_{now_label()}.xlsx"
    _, parsed, _ = client.post_multipart(
        f"/api/jobs/{job_id}/upload-rfms",
        files=[("files", filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", workbook)],
    )
    materials = parsed.get("materials") if isinstance(parsed, dict) else None
    if not materials:
        return [], Check("rfms_upload", "FAIL", "RFMS fixture upload returned no materials", {"response": parsed})
    return materials, Check(
        "rfms_upload",
        "PASS",
        f"uploaded synthesized RFMS fixture with {len(materials)} materials",
        {"filename": filename, "material_codes": [m.get("item_code") for m in materials]},
    )


def price_materials(client: Client, job_id: str, fixture: dict[str, Any]) -> tuple[list[dict[str, Any]], Check]:
    _, job, _ = client.request("GET", f"/api/jobs/{job_id}")
    materials = job.get("materials") or []
    pricing = fixture.get("pricing", {})
    default_price = float(pricing.get("default_unit_price", 10))
    by_code = {k.upper(): float(v) for k, v in (pricing.get("by_item_code") or {}).items()}
    priced = []
    for mat in materials:
        code = (mat.get("item_code") or "").upper()
        unit_price = by_code.get(code, default_price)
        mat["unit_price"] = unit_price
        mat["price_source"] = "rules_audit_harness"
        mat["quote_status"] = "quoted"
        priced.append(mat)
    _, parsed, _ = client.request("PUT", f"/api/jobs/{job_id}/materials", json_body={"materials": priced})
    updated = parsed.get("materials") or []
    return updated, Check(
        "material_pricing",
        "PASS",
        f"set deterministic unit pricing on {len(updated)} materials",
        {"priced_codes": {m.get("item_code"): m.get("unit_price") for m in updated}},
    )


def validate_parsed_materials(
    fixture: dict[str, Any],
    materials: list[dict[str, Any]],
    labor_items: list[dict[str, Any]] | None = None,
) -> Check:
    labor_items = labor_items or []
    cases = []
    failures = []
    for item_code, expected in fixture.get("expected_materials", {}).items():
        mat = find_material(materials, item_code)
        case = {"item_code": item_code, "status": "PASS", "checks": []}
        if not mat:
            case["status"] = "FAIL"
            case["checks"].append({"name": "exists", "ok": False})
            cases.append(case)
            failures.append(f"{item_code} missing")
            continue

        for key in ("material_type",):
            if key in expected:
                ok = mat.get(key) == expected[key]
                case["checks"].append({"name": key, "ok": ok, "expected": expected[key], "actual": mat.get(key)})
                if not ok:
                    case["status"] = "FAIL"

        if "description_contains" in expected:
            needle = expected["description_contains"].lower()
            description = (mat.get("description") or "").lower()
            ok = needle in description
            case["checks"].append({"name": "description_contains", "ok": ok, "expected": needle, "actual": description})
            if not ok:
                case["status"] = "FAIL"

        if "installed_qty" in expected:
            ok = almost_equal(float(mat.get("installed_qty") or 0), float(expected["installed_qty"]))
            case["checks"].append({"name": "installed_qty", "ok": ok, "expected": expected["installed_qty"], "actual": mat.get("installed_qty")})
            if not ok:
                case["status"] = "FAIL"

        if "is_mosaic" in expected:
            ok = bool(mat.get("is_mosaic")) == bool(expected["is_mosaic"])
            case["checks"].append({"name": "is_mosaic", "ok": ok, "expected": expected["is_mosaic"], "actual": bool(mat.get("is_mosaic"))})
            if not ok:
                case["status"] = "FAIL"

        mat_labor = related_labor(labor_items, mat)
        descriptions = " | ".join(str(l.get("labor_description", "")) for l in mat_labor).lower()

        if expected.get("requires_labor"):
            ok = len(mat_labor) > 0
            case["checks"].append({"name": "requires_labor", "ok": ok, "labor_count": len(mat_labor)})
            if not ok:
                case["status"] = "FAIL"

        if "labor_rate" in expected:
            rates = [float(l.get("rate") or 0) for l in mat_labor]
            ok = any(almost_equal(rate, float(expected["labor_rate"])) for rate in rates)
            case["checks"].append({"name": "labor_rate", "ok": ok, "expected": expected["labor_rate"], "actual": rates})
            if not ok:
                case["status"] = "FAIL"

        if "labor_unit" in expected:
            units = [str(l.get("unit") or "") for l in mat_labor]
            ok = expected["labor_unit"] in units
            case["checks"].append({"name": "labor_unit", "ok": ok, "expected": expected["labor_unit"], "actual": units})
            if not ok:
                case["status"] = "FAIL"

        if "labor_qty" in expected:
            quantities = [float(l.get("qty") or 0) for l in mat_labor]
            ok = any(almost_equal(qty, float(expected["labor_qty"])) for qty in quantities)
            case["checks"].append({"name": "labor_qty", "ok": ok, "expected": expected["labor_qty"], "actual": quantities})
            if not ok:
                case["status"] = "FAIL"

        if "labor_description_contains" in expected:
            needle = expected["labor_description_contains"].lower()
            ok = needle in descriptions
            case["checks"].append({"name": "labor_description_contains", "ok": ok, "expected": needle, "actual": descriptions})
            if not ok:
                case["status"] = "FAIL"

        if "labor_description_excludes" in expected:
            needle = expected["labor_description_excludes"].lower()
            ok = needle not in descriptions
            case["checks"].append({"name": "labor_description_excludes", "ok": ok, "expected_absent": needle, "actual": descriptions})
            if not ok:
                case["status"] = "FAIL"

        if case["status"] == "FAIL":
            failures.append(item_code)
        cases.append(case)

    return Check(
        "josh_lesson_cases",
        "FAIL" if failures else "PASS",
        "validated parser/material/labor permanent cases" if not failures else f"{len(failures)} case(s) failed",
        {"cases": cases},
    )


def run_calculate(client: Client, job_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Check]:
    _, parsed, _ = client.request("POST", f"/api/jobs/{job_id}/calculate")
    sundries = parsed.get("sundries") or []
    labor = parsed.get("labor") or []
    status = "PASS" if labor else "FAIL"
    summary = f"calculated {len(sundries)} sundries and {len(labor)} labor items"
    return sundries, labor, Check(
        "calculate",
        status,
        summary,
        {
            "sundry_count": len(sundries),
            "labor_count": len(labor),
            "labor_samples": labor[:5],
            "sundry_samples": sundries[:5],
        },
    )


def generate_proposal(client: Client, job_id: str) -> tuple[dict[str, Any], Check]:
    _, proposal, _ = client.request("POST", f"/api/jobs/{job_id}/proposal/generate")
    bundles = proposal.get("bundles") or []
    status = "PASS" if bundles else "FAIL"
    return proposal, Check(
        "proposal_generate",
        status,
        f"generated {len(bundles)} proposal bundles",
        {"bundle_names": [b.get("bundle_name") for b in bundles], "totals": summarize_proposal(proposal)},
    )


def summarize_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    bundles = proposal.get("bundles") or []
    return {
        "bundle_count": len(bundles),
        "material_cost": sum_bundle_field(bundles, "material_cost"),
        "sundry_cost": sum_bundle_field(bundles, "sundry_cost"),
        "labor_cost": sum_bundle_field(bundles, "labor_cost"),
        "freight_cost": sum_bundle_field(bundles, "freight_cost"),
        "gpm_adder": sum_bundle_field(bundles, "gpm_adder"),
        "gpm_labor_adder": sum_bundle_field(bundles, "gpm_labor_adder"),
        "gpm_material_adder": sum_bundle_field(bundles, "gpm_material_adder"),
        "taxable": proposal.get("taxable"),
        "tax_amount": proposal.get("tax_amount"),
        "subtotal": proposal.get("subtotal"),
        "grand_total": proposal.get("grand_total"),
    }


def validate_totals(proposal: dict[str, Any]) -> Check:
    bundles = proposal.get("bundles") or []
    tax_rate = float(proposal.get("tax_rate") or 0)
    expected_taxable = round(
        sum(
            float(b.get("material_cost") or 0)
            + float(b.get("sundry_cost") or 0)
            + float(b.get("freight_cost") or 0)
            + float(b.get("gpm_material_adder") or 0)
            for b in bundles
        ),
        2,
    )
    expected_tax = round(expected_taxable * tax_rate, 2)
    actual_taxable = round(float(proposal.get("taxable") or 0), 2)
    actual_tax = round(float(proposal.get("tax_amount") or 0), 2)
    labor_total = sum_bundle_field(bundles, "labor_cost")
    material_total = sum_bundle_field(bundles, "material_cost")
    sundry_total = sum_bundle_field(bundles, "sundry_cost")
    freight_total = sum_bundle_field(bundles, "freight_cost")
    gpm_total = round(sum(float(b.get("gpm_adder") or 0) for b in bundles), 2)
    gpm_labor_total = round(sum(float(b.get("gpm_labor_adder") or 0) for b in bundles), 2)
    gpm_material_total = round(sum(float(b.get("gpm_material_adder") or 0) for b in bundles), 2)
    total_cost = round(material_total + sundry_total + labor_total + freight_total, 2)
    gpm_pct = float(proposal.get("gpm_pct") or 0)
    expected_gpm = round(total_cost / (1 - gpm_pct) - total_cost, 2) if 0 < gpm_pct < 1 and total_cost > 0 else 0
    expected_gpm_labor = round(expected_gpm * 0.9793, 2)
    expected_gpm_material = round(expected_gpm - expected_gpm_labor, 2)
    labor_included_tax = round((expected_taxable + labor_total) * tax_rate, 2)

    checks = [
        {"name": "material_total_positive", "ok": material_total > 0, "actual": material_total},
        {"name": "labor_total_positive", "ok": labor_total > 0, "actual": labor_total},
        {"name": "sundry_total_positive", "ok": sundry_total > 0, "actual": sundry_total},
        {"name": "gpm_formula", "ok": almost_equal(gpm_total, expected_gpm, 0.05), "expected": expected_gpm, "actual": gpm_total},
        {"name": "gpm_labor_split", "ok": almost_equal(gpm_labor_total, expected_gpm_labor, 0.05), "expected": expected_gpm_labor, "actual": gpm_labor_total},
        {"name": "gpm_material_split", "ok": almost_equal(gpm_material_total, expected_gpm_material, 0.05), "expected": expected_gpm_material, "actual": gpm_material_total},
        {"name": "taxable_excludes_labor", "ok": almost_equal(actual_taxable, expected_taxable), "expected": expected_taxable, "actual": actual_taxable},
        {"name": "tax_amount_excludes_labor", "ok": almost_equal(actual_tax, expected_tax), "expected": expected_tax, "actual": actual_tax},
        {
            "name": "tax_not_calculated_on_labor",
            "ok": not almost_equal(actual_tax, labor_included_tax) if labor_total > 0 else True,
            "labor_included_tax": labor_included_tax,
            "actual": actual_tax,
        },
    ]
    failures = [c for c in checks if not c["ok"]]
    return Check(
        "proposal_totals",
        "FAIL" if failures else "PASS",
        "tax excludes labor and GPM/totals are populated" if not failures else f"{len(failures)} total check(s) failed",
        {"checks": checks, "summary": summarize_proposal(proposal)},
    )


def proposal_save_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundles": proposal.get("bundles", []),
        "notes": proposal.get("notes", []),
        "terms": proposal.get("terms", []),
        "exclusions": proposal.get("exclusions", []),
        "tax_rate": proposal.get("tax_rate", 0),
        "gpm_pct": proposal.get("gpm_pct", 0),
        "textura_fee": proposal.get("textura_fee", 0),
        "subtotal": proposal.get("subtotal", 0),
        "tax_amount": proposal.get("tax_amount", 0),
        "grand_total": proposal.get("grand_total", 0),
        "gpm_profit": proposal.get("gpm_profit", 0),
        "gpm_labor": proposal.get("gpm_labor", 0),
        "gpm_material": proposal.get("gpm_material", 0),
        "textura_amount": proposal.get("textura_amount", 0),
        "deleted_bundles": proposal.get("deleted_bundles", []),
        "deleted_material_codes": proposal.get("deleted_material_codes", []),
        "audit": proposal.get("audit", {}),
    }


def validate_manual_override_audit(client: Client, job_id: str, proposal: dict[str, Any]) -> Check:
    bundles = proposal.get("bundles") or []
    if not bundles:
        return Check("manual_override_audit", "WARN", "no proposal bundle available for manual override audit")

    baseline = copy.deepcopy(proposal)
    client.request("PUT", f"/api/jobs/{job_id}/proposal/bundles", json_body=proposal_save_payload(baseline))

    edited = copy.deepcopy(proposal)
    target = edited["bundles"][0]
    old_price = float(target.get("price_override") if target.get("price_override") is not None else target.get("total_price") or 0)
    new_price = round(old_price + 12.34, 2)
    target["price_override"] = new_price
    _, save_result, _ = client.request("PUT", f"/api/jobs/{job_id}/proposal/bundles", json_body=proposal_save_payload(edited))
    _, audit, _ = client.request("GET", f"/api/jobs/{job_id}/audit")
    client.request("PUT", f"/api/jobs/{job_id}/proposal/bundles", json_body=proposal_save_payload(baseline))
    traces = audit.get("traces") or []
    target_name = target.get("bundle_name")
    hit = next(
        (
            t for t in traces
            if t.get("source") == "manual_override"
            and t.get("output_field") == "price_override"
            and (not target_name or t.get("entity_key") == target_name)
        ),
        None,
    )
    ok = bool(hit) and int(save_result.get("manual_trace_count") or 0) > 0
    return Check(
        "manual_override_audit",
        "PASS" if ok else "FAIL",
        "manual proposal edit created a manual_override audit row" if ok else "manual proposal edit did not create an audit row",
        {
            "bundle_name": target_name,
            "old_price": old_price,
            "new_price": new_price,
            "save_result": save_result,
            "trace": hit,
        },
    )


def validate_deleted_bundle(client: Client, job_id: str, proposal: dict[str, Any], fixture: dict[str, Any]) -> Check:
    item_code = fixture.get("deletion_case", {}).get("item_code")
    if not item_code:
        return Check("deleted_bundle", "WARN", "no deletion_case.item_code in fixture")
    bundles = proposal.get("bundles") or []
    target = find_bundle_with_code(bundles, item_code)
    if not target:
        return Check("deleted_bundle", "FAIL", f"could not find bundle containing {item_code}")

    target_name = target.get("bundle_name")
    target_codes = [
        m.get("item_code")
        for m in target.get("materials") or []
        if m.get("item_code")
    ]
    kept = [b for b in bundles if b is not target]
    save_payload = proposal_save_payload(proposal)
    save_payload.update({
        "bundles": kept,
        "deleted_bundles": [target_name],
        "deleted_material_codes": target_codes,
    })
    client.request("PUT", f"/api/jobs/{job_id}/proposal/bundles", json_body=save_payload)
    _, regenerated, _ = client.request("POST", f"/api/jobs/{job_id}/proposal/generate")
    resurrected = find_bundle_with_code(regenerated.get("bundles") or [], item_code)
    deleted_codes = regenerated.get("deleted_material_codes") or []
    ok = resurrected is None and item_code in [str(c) for c in deleted_codes]
    return Check(
        "deleted_bundle",
        "PASS" if ok else "FAIL",
        f"deleted bundle for {item_code} stayed deleted" if ok else f"deleted bundle for {item_code} was resurrected",
        {
            "target_bundle": target_name,
            "target_codes": target_codes,
            "regenerated_bundle_names": [b.get("bundle_name") for b in regenerated.get("bundles") or []],
            "deleted_material_codes": deleted_codes,
        },
    )


def fetch_audit_payloads(client: Client, job_id: str, proposal: dict[str, Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    payloads = []
    attempts = []
    for tmpl in AUDIT_ENDPOINTS:
        path = tmpl.format(job_id=job_id)
        status, parsed, raw = client.get_optional(path)
        attempts.append({"path": path, "status": status})
        if status == 200 and parsed is not None:
            payloads.append(parsed)
    payloads.extend(recursive_pick_trace_payloads(proposal))
    return payloads, attempts


def validate_audit_trace(client: Client, job_id: str, proposal: dict[str, Any], fixture: dict[str, Any], allow_missing: bool) -> Check:
    payloads, attempts = fetch_audit_payloads(client, job_id, proposal)
    categories = fixture.get("audit_categories") or ["material", "sundry", "labor", "tax", "gpm"]
    present = audit_categories_present(payloads, categories)
    missing = [cat for cat, ok in present.items() if not ok]
    if not payloads:
        status = "WARN" if allow_missing else "FAIL"
        return Check(
            "audit_trace",
            status,
            "no audit trace payload found",
            {"audit_endpoints_tried": attempts, "required_categories": categories},
        )
    status = "PASS" if not missing else ("WARN" if allow_missing else "FAIL")
    return Check(
        "audit_trace",
        status,
        "audit trace includes required total categories" if not missing else f"audit trace missing categories: {', '.join(missing)}",
        {
            "audit_endpoints_tried": attempts,
            "payload_count": len(payloads),
            "categories_present": present,
        },
    )


def cleanup_job(client: Client, job_id: str, created: bool, keep_job: bool) -> Check:
    if not created:
        return Check("cleanup", "WARN", "existing job was used; cleanup skipped", {"job_id": job_id})
    if keep_job:
        return Check("cleanup", "WARN", "test job retained by --keep-job", {"job_id": job_id})
    try:
        client.request("DELETE", f"/api/jobs/{job_id}")
        return Check("cleanup", "PASS", f"deleted test job {job_id}", {"job_id": job_id})
    except HarnessError as exc:
        return Check("cleanup", "FAIL", f"failed to delete test job {job_id}", {"error": str(exc)})


def print_report(result: dict[str, Any]) -> None:
    checks = result["checks"]
    failed = [c for c in checks if c["status"] == "FAIL"]
    warned = [c for c in checks if c["status"] == "WARN"]
    print("\nRules/Audit Harness Report")
    print("=" * 72)
    print(f"Base URL: {result['base_url']}")
    print(f"Fixture:  {result['fixture']}")
    print(f"Job ID:   {result.get('job_id') or 'n/a'}")
    print(f"Result:   {'FAIL' if failed else 'PASS'} ({len(failed)} failed, {len(warned)} warnings)")
    print("-" * 72)
    for check in checks:
        print(f"[{check['status']:<4}] {check['name']}: {check['summary']}")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deployed rules/audit harness against an SI Bid Tool base URL.")
    parser.add_argument("--base-url", required=True, help="Deployed app base URL, for example https://si-bid-tool.fly.dev")
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE, help=f"Fixture JSON path (default: {DEFAULT_FIXTURE})")
    parser.add_argument("--job-id", help="Use an existing job ID/slug instead of creating a temporary test job")
    parser.add_argument("--keep-job", action="store_true", help="Do not delete the generated test job at the end")
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP timeout in seconds")
    parser.add_argument("--header", action="append", default=[], help="Extra HTTP header, e.g. 'Authorization: Bearer ...'")
    parser.add_argument("--json-output", help="Optional path for JSON detail output")
    parser.add_argument("--allow-missing-audit", action="store_true", help="Downgrade missing audit trace checks to WARN")
    args = parser.parse_args()

    fixture = load_fixture(args.fixture)
    client = Client(normalize_base_url(args.base_url), args.timeout, parse_headers(args.header))
    checks: list[Check] = []
    job_id = None
    created_job = False

    try:
        checks.append(try_rule_registry(client))
        checks.append(try_rule_eval(client, fixture))

        job_id, created_job, job_check = create_or_use_job(client, fixture, args.job_id)
        checks.append(job_check)

        _, upload_check = upload_rfms_fixture(client, job_id, fixture)
        checks.append(upload_check)

        materials, pricing_check = price_materials(client, job_id, fixture)
        checks.append(pricing_check)

        sundries, labor, calc_check = run_calculate(client, job_id)
        checks.append(calc_check)

        _, refreshed_job, _ = client.request("GET", f"/api/jobs/{job_id}")
        materials = refreshed_job.get("materials") or materials
        checks.append(validate_parsed_materials(fixture, materials, labor))

        proposal, proposal_check = generate_proposal(client, job_id)
        checks.append(proposal_check)
        checks.append(validate_totals(proposal))
        checks.append(validate_manual_override_audit(client, job_id, proposal))
        checks.append(validate_deleted_bundle(client, job_id, proposal, fixture))
        checks.append(validate_audit_trace(client, job_id, proposal, fixture, args.allow_missing_audit))
    except HarnessError as exc:
        checks.append(Check("harness_error", "FAIL", str(exc)))
    except Exception as exc:
        checks.append(Check("harness_exception", "FAIL", f"{type(exc).__name__}: {exc}"))
    finally:
        if job_id:
            try:
                checks.append(cleanup_job(client, job_id, created_job, args.keep_job))
            except Exception as exc:
                checks.append(Check("cleanup", "FAIL", f"cleanup raised {type(exc).__name__}: {exc}"))

    result = {
        "base_url": client.base_url,
        "fixture": os.path.abspath(args.fixture),
        "job_id": job_id,
        "created_job": created_job,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": [check.__dict__ for check in checks],
    }
    result["status"] = "FAIL" if any(c.status == "FAIL" for c in checks) else "PASS"

    print_report(result)
    print("\nJSON_DETAILS_BEGIN")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    print("JSON_DETAILS_END")

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, sort_keys=True, default=str)
            f.write("\n")

    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
