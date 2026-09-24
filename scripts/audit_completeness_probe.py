#!/usr/bin/env python3
"""Check on a running server that write routes really land in the history.

Logs in, then calls write routes on a throwaway bid and a throwaway vendor.
For each response it looks up the X-Request-Id in /api/audit and checks:

  * there is an entry for that request, with one of the expected actions;
  * the entry names the person who logged in;
  * it lists changes (except events that change no fields);
  * its "after" values match what a fresh GET returns.

The throwaway bid, its copy and the vendor are deleted at the end (those
deletes are checked too). Nothing else is touched: no AI calls, no emails,
no settings, no people.

Usage (staging):
    AUDIT_PROBE_PIN=... python3 scripts/audit_completeness_probe.py \\
        --base-url https://si-bid-stg-20260714-c0fa.fly.dev --username e2e-alice

Exit code 0 when every check passes, 1 when any fails. --list-unprobed also
imports the app locally (needs server/requirements.txt installed) and lists
the audited write routes this probe doesn't call yet.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── HTTP ──────────────────────────────────────────────────────────────────────
class HttpTransport:
    """Talks to a real server; keeps the login cookie between calls."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, method: str, path: str, body=None) -> tuple[int, dict, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("Origin", self.base_url)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=60) as resp:
                return resp.status, _lower_keys(resp.headers), _parse(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, _lower_keys(err.headers), _parse(err.read())


def _lower_keys(headers) -> dict:
    return {str(key).lower(): value for key, value in (headers or {}).items()}


def _parse(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        return raw[:200].decode("utf-8", "replace")


# ── Comparing values ──────────────────────────────────────────────────────────
def _blank(value) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and len(value) == 0)


def same_value(a, b) -> bool:
    """Loose equality between a history "after" value and a fresh GET value."""
    if _blank(a) and _blank(b):
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    try:
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-6)
    except (TypeError, ValueError):
        return False
    if isinstance(a, str) and isinstance(b, (list, dict)):
        try:
            a = json.loads(a)
        except ValueError:
            return False
    if isinstance(b, str) and isinstance(a, (list, dict)):
        try:
            b = json.loads(b)
        except ValueError:
            return False
    return a == b


def _top_level_key(path: str) -> str | None:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in str(path or "").split("/")[1:]]
    return parts[0] if len(parts) == 1 else None


def compare_after(entry: dict, fresh: dict, keys: set[str] | None = None) -> list[str]:
    """Problems where an edited top-level field's "after" differs from ``fresh``."""
    problems = []
    for change in entry.get("changes") or []:
        if change.get("derived") or change.get("redacted") or change.get("op") == "remove":
            continue
        after = change.get("after")
        if isinstance(after, dict) and after.get("truncated"):
            continue
        key = _top_level_key(change.get("path"))
        if key is None or key not in fresh or (keys is not None and key not in keys):
            continue
        if not same_value(after, fresh[key]):
            problems.append(f"history says {key} = {after!r}, the server now has {fresh[key]!r}")
    return problems


# ── Steps ─────────────────────────────────────────────────────────────────────
@dataclass
class Step:
    name: str
    route: str                      # "METHOD /api/path/{param}" as the app declares it
    path: Callable[[dict], str]     # the URL to call, from what earlier steps saved
    body: Callable[[dict], object] | None = None
    actions: tuple[str, ...] = ()
    needs_changes: bool = True
    check: Callable[["Probe", dict], list[str]] | None = None   # fresh-GET comparison
    save: Callable[[dict, object], None] | None = None          # keep ids from the response
    needs: tuple[str, ...] = ()     # skip unless these were saved


def _job_fields(probe: "Probe", entry: dict) -> list[str]:
    status, _, job = probe.transport.request("GET", f"/api/jobs/{probe.state['job']}")
    if status != 200 or not isinstance(job, dict):
        return [f"GET the bid failed ({status})"]
    return compare_after(entry, job)


def _exclusions(probe: "Probe", entry: dict) -> list[str]:
    status, _, data = probe.transport.request("GET", f"/api/jobs/{probe.state['job']}/exclusions")
    if status != 200 or not isinstance(data, dict):
        return [f"GET exclusions failed ({status})"]
    return compare_after(entry, {"exclusions": data.get("exclusions")})


def _tracking(probe: "Probe", entry: dict) -> list[str]:
    status, _, data = probe.transport.request("GET", f"/api/jobs/{probe.state['job']}/bid-tracking")
    if status != 200 or not isinstance(data, dict):
        return [f"GET bid tracking failed ({status})"]
    return compare_after(entry, data.get("tracking") or {})


def _comment(probe: "Probe", entry: dict) -> list[str]:
    status, _, data = probe.transport.request("GET", f"/api/jobs/{probe.state['job']}/comments")
    if status != 200 or not isinstance(data, list):
        return [f"GET comments failed ({status})"]
    found = next((row for row in data if str(row.get("id")) == str(probe.state.get("comment"))), None)
    return compare_after(entry, found, {"text"}) if found else ["the new comment isn't in the comment list"]


def _vendor(probe: "Probe", entry: dict) -> list[str]:
    status, _, data = probe.transport.request("GET", f"/api/vendors/{probe.state['vendor']}")
    if status != 200 or not isinstance(data, dict):
        return [f"GET the vendor failed ({status})"]
    return compare_after(entry, data)


def _gone(url: Callable[[dict], str]) -> Callable[["Probe", dict], list[str]]:
    def check(probe: "Probe", entry: dict) -> list[str]:
        status, _, _ = probe.transport.request("GET", url(probe.state))
        return [] if status == 404 else [f"still there after deleting (GET returned {status})"]
    return check


def build_steps(stamp: str) -> list[Step]:
    name = f"Audit probe {stamp}"
    return [
        Step("create a bid", "POST /api/jobs", lambda s: "/api/jobs",
             lambda s: {"project_name": name, "city": "Probeville", "gc_name": "Probe GC"},
             ("job.create",), check=_job_fields, save=lambda s, r: s.update(job=r["id"])),
        Step("change two header fields", "PUT /api/jobs/{job_id}", lambda s: f"/api/jobs/{s['job']}",
             lambda s: {"address": "1 Probe Way", "zip": "80202"}, ("job.update",),
             check=_job_fields, needs=("job",)),
        Step("change notes", "PUT /api/jobs/{job_id}/notes", lambda s: f"/api/jobs/{s['job']}/notes",
             lambda s: {"notes": f"Probe notes {stamp}"}, ("job.notes.update",),
             check=_job_fields, needs=("job",)),
        Step("change exclusions", "PUT /api/jobs/{job_id}/exclusions",
             lambda s: f"/api/jobs/{s['job']}/exclusions",
             lambda s: {"exclusions": ["Probe exclusion one", "Probe exclusion two"]},
             ("job.exclusions.update",), check=_exclusions, needs=("job",)),
        Step("change bid tracking", "PATCH /api/jobs/{job_id}/bid-tracking",
             lambda s: f"/api/jobs/{s['job']}/bid-tracking",
             lambda s: {"estimator": "Probe Estimator"},
             ("bid.status", "bid.sent", "bid.tracking.update", "bid.note"), check=_tracking, needs=("job",)),
        Step("add a bid note", "POST /api/jobs/{job_id}/bid-events",
             lambda s: f"/api/jobs/{s['job']}/bid-events",
             lambda s: {"event_type": "note", "note": f"Probe note {stamp}"},
             ("bid.note",), needs_changes=False, needs=("job",)),
        Step("add a comment", "POST /api/jobs/{job_id}/comments", lambda s: f"/api/jobs/{s['job']}/comments",
             lambda s: {"text": f"Probe comment {stamp}"}, ("comment.add",), check=_comment,
             save=lambda s, r: s.update(comment=r["id"]), needs=("job",)),
        Step("copy the bid", "POST /api/jobs/{job_id}/duplicate", lambda s: f"/api/jobs/{s['job']}/duplicate",
             None, ("job.duplicate",), save=lambda s, r: s.update(copy=r["id"]), needs=("job",)),
        Step("delete the copy", "DELETE /api/jobs/{job_id}", lambda s: f"/api/jobs/{s['copy']}",
             None, ("job.delete",), check=_gone(lambda s: f"/api/jobs/{s['copy']}"), needs=("copy",)),
        Step("add a vendor", "POST /api/vendors", lambda s: "/api/vendors",
             lambda s: {"name": f"{name} vendor", "contact_email": "probe@example.com"}, ("vendor.create",),
             check=_vendor, save=lambda s, r: s.update(vendor=r["id"])),
        Step("change the vendor", "PUT /api/vendors/{vendor_id}", lambda s: f"/api/vendors/{s['vendor']}",
             lambda s: {"contact_phone": "303 555 0100"}, ("vendor.update",), check=_vendor, needs=("vendor",)),
        Step("delete the vendor", "DELETE /api/vendors/{vendor_id}", lambda s: f"/api/vendors/{s['vendor']}",
             None, ("vendor.delete",), check=_gone(lambda s: f"/api/vendors/{s['vendor']}"), needs=("vendor",)),
        Step("delete the bid", "DELETE /api/jobs/{job_id}", lambda s: f"/api/jobs/{s['job']}",
             None, ("job.delete",), check=_gone(lambda s: f"/api/jobs/{s['job']}"), needs=("job",)),
    ]


# ── Running ───────────────────────────────────────────────────────────────────
@dataclass
class Result:
    step: str
    ok: bool
    problems: list[str] = field(default_factory=list)
    request_id: str | None = None
    entry_id: int | None = None


class Probe:
    def __init__(self, transport, username: str, *, audit_wait_seconds: float = 5.0):
        self.transport = transport
        self.username = username
        self.audit_wait_seconds = audit_wait_seconds
        self.state: dict = {}

    def login(self, pin: str) -> None:
        status, _, body = self.transport.request("POST", "/api/auth/login", {"username": self.username, "pin": pin})
        if status != 200:
            detail = body.get("detail") if isinstance(body, dict) else body
            raise SystemExit(f"Couldn't log in as {self.username} ({status}): {detail}")
        self.username = (body or {}).get("username") or self.username

    def find_entries(self, request_id: str) -> list[dict]:
        query = urllib.parse.urlencode({"q": request_id, "limit": 50})
        deadline = time.monotonic() + self.audit_wait_seconds
        while True:
            status, _, page = self.transport.request("GET", f"/api/audit?{query}")
            items = (page or {}).get("items") if status == 200 and isinstance(page, dict) else []
            found = [
                item for item in items or []
                if item.get("request_id") == request_id
                or request_id in ((item.get("extra") or {}).get("request_ids") or [])
            ]
            if found or time.monotonic() >= deadline:
                return found
            time.sleep(0.5)

    def names_me(self, entry: dict) -> bool:
        me = self.username.lower()
        if str(entry.get("actor_username") or "").lower() == me:
            return True
        return any(str(actor.get("username") or "").lower() == me for actor in entry.get("actors") or [])

    def run_step(self, step: Step) -> Result:
        missing = [key for key in step.needs if key not in self.state]
        if missing:
            return Result(step.name, False, [f"skipped: an earlier step didn't give a {', '.join(missing)}"])
        body = step.body(self.state) if step.body else None
        status, headers, response = self.transport.request(step.route.split()[0], step.path(self.state), body)
        request_id = headers.get("x-request-id")
        result = Result(step.name, True, request_id=request_id)
        if not 200 <= status < 300:
            detail = response.get("detail") if isinstance(response, dict) else response
            result.problems.append(f"the request failed ({status}): {detail}")
        elif step.save:
            try:
                step.save(self.state, response)
            except (KeyError, TypeError) as err:
                result.problems.append(f"the response had no {err} to keep")
        if not request_id:
            result.problems.append("the response has no X-Request-Id header")
        elif 200 <= status < 300:
            entries = self.find_entries(request_id)
            matching = [entry for entry in entries if entry.get("action") in step.actions]
            if not entries:
                result.problems.append("no history entry for this request")
            elif not matching:
                actions = ", ".join(sorted({str(entry.get("action")) for entry in entries}))
                result.problems.append(f"history entry has action {actions}, expected {', '.join(step.actions)}")
            else:
                entry = matching[0]
                result.entry_id = entry.get("id")
                if not self.names_me(entry):
                    result.problems.append(f"entry names {entry.get('actor_display')!r}, not {self.username!r}")
                if step.needs_changes and not entry.get("changes"):
                    result.problems.append("entry lists no changes")
                if step.check:
                    result.problems.extend(step.check(self, entry))
        result.ok = not result.problems
        return result

    def run(self, steps: list[Step]) -> list[Result]:
        return [self.run_step(step) for step in steps]


def unprobed_routes(steps: list[Step]) -> list[str]:
    """Audited write routes (from the local app) that no step calls."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from audit_route_coverage import load_app  # noqa: E402

    app = load_app()
    from audit import list_route_policies  # noqa: E402

    probed = {step.route for step in steps}
    missing = []
    for row in list_route_policies(app):
        policy = row["policy"] or {}
        if policy.get("kind") != "audited":
            continue
        for method in row["methods"]:
            route = f"{method} {row['path']}"
            if route not in probed:
                missing.append(route)
    return sorted(missing)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="e.g. https://si-bid-stg-20260714-c0fa.fly.dev")
    parser.add_argument("--username", default=os.environ.get("AUDIT_PROBE_USERNAME", ""),
                        help="login to use (or AUDIT_PROBE_USERNAME)")
    parser.add_argument("--pin-env", default="AUDIT_PROBE_PIN",
                        help="environment variable holding the PIN (default AUDIT_PROBE_PIN)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--list-unprobed", action="store_true",
                        help="also list audited write routes this probe doesn't call")
    args = parser.parse_args()
    pin = os.environ.get(args.pin_env, "")
    if not args.username or not pin:
        parser.error(f"give --username (or AUDIT_PROBE_USERNAME) and put the PIN in {args.pin_env}")

    probe = Probe(HttpTransport(args.base_url), args.username)
    probe.login(pin)
    steps = build_steps(time.strftime("%Y-%m-%d %H:%M:%S"))
    results = probe.run(steps)
    unprobed = unprobed_routes(steps) if args.list_unprobed else None

    failed = [result for result in results if not result.ok]
    if args.json:
        print(json.dumps({
            "results": [result.__dict__ for result in results],
            "failed": len(failed),
            "unprobed": unprobed,
        }, indent=2))
    else:
        for result in results:
            mark = "ok  " if result.ok else "FAIL"
            print(f"{mark}  {result.step}" + (f"  (entry #{result.entry_id})" if result.entry_id else ""))
            for problem in result.problems:
                print(f"        {problem}")
        print(f"\n{len(results) - len(failed)} of {len(results)} steps passed.")
        if unprobed is not None:
            print(f"{len(unprobed)} audited write routes not probed yet:")
            for route in unprobed:
                print(f"  {route}")
        leftovers = {key: probe.state[key] for key in ("job", "copy", "vendor") if key in probe.state}
        if failed and leftovers:
            print(f"Check for leftover probe data: {leftovers}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
