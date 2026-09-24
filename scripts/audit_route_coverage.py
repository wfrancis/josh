#!/usr/bin/env python3
"""Check every write route says how it is audited.

Imports the app (without starting it), walks app.routes and lists every
POST/PUT/PATCH/DELETE route and websocket with its audit policy:

    audited    @audit_route("job.update", ...)   writes audit entries
    no_audit   @no_audit("reason")               deliberately not audited
    MISSING    neither                          -> exit code 1

Usage:
    python3 scripts/audit_route_coverage.py            # table, then the missing ones
    python3 scripts/audit_route_coverage.py --missing  # only the missing ones
    python3 scripts/audit_route_coverage.py --json     # machine-readable
    python3 scripts/audit_route_coverage.py --server-dir /app   # server code elsewhere

The Docker build runs it with --missing, so a deploy fails while any write
route has no policy.

Uses a throwaway database and artifact folder, so it never touches real data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT, "server")


def load_app(server_dir: str = SERVER_DIR):
    scratch = tempfile.mkdtemp(prefix="audit-coverage-")
    os.environ.setdefault("DATABASE_PATH", os.path.join(scratch, "coverage.db"))
    os.environ.setdefault("ARTIFACT_ROOT", os.path.join(scratch, "artifacts"))
    sys.path.insert(0, server_dir)
    import main  # noqa: E402  (needs the environment above)
    return main.app


def describe(policy: dict | None) -> tuple[str, str]:
    if not policy:
        return "MISSING", ""
    if policy.get("kind") == "no_audit":
        return "no_audit", policy.get("reason") or ""
    return "audited", ", ".join(policy.get("actions") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--missing", action="store_true", help="only list routes without a policy")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--server-dir", default=SERVER_DIR,
                        help="folder holding main.py (default: server/ next to this script)")
    args = parser.parse_args()

    app = load_app(os.path.abspath(args.server_dir))
    from audit import list_route_policies

    rows = list_route_policies(app)
    missing = [row for row in rows if not row["policy"]]

    if args.json:
        print(json.dumps({"routes": rows, "missing": len(missing)}, indent=2, default=str))
        return 1 if missing else 0

    shown = missing if args.missing else rows
    for row in sorted(shown, key=lambda row: (row["path"], row["methods"])):
        status, detail = describe(row["policy"])
        methods = ",".join(row["methods"])
        print(f"{status:<9} {methods:<12} {row['path']:<60} {row['name']}" + (f"  [{detail}]" if detail else ""))

    audited = sum(1 for row in rows if row["policy"] and row["policy"].get("kind") == "audited")
    exempt = sum(1 for row in rows if row["policy"] and row["policy"].get("kind") == "no_audit")
    print()
    print(f"{len(rows)} write routes: {audited} audited, {exempt} marked no_audit, {len(missing)} missing a policy.")
    if missing:
        print("Every write route needs @audit_route(...) or @no_audit(reason) (from audit.py).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
