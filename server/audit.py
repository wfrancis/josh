"""
Audit trail: who changed what, and when, for everything in the bid tool.

Every change is one row in ``audit_log``:

* who: a snapshot of the person (user id, username, display name), or
  "System" plus a source for background and startup work (``system_context``);
* where from: request id, session, caller address and route;
* what: an action ("job.update", "auth.login", ...), the entity it touched,
  the bid it belongs to (``job_id``; no foreign key, so history outlives a
  deleted bid), a plain-English summary and a structured list of changes
  from ``diff()``;
* when: UTC timestamps with milliseconds, ``ts_first`` .. ``ts``.

Rows are append-only: database triggers refuse DELETE, and refuse UPDATE
except on an open group. Quick repeated edits of the same field are grouped
into one row while the group is open (first "before", latest "after", every
editor in ``audit_log_actors`` and an edit count); a sweeper closes idle
groups. ``seq`` is a global counter that every insert and group update bumps,
so a live client can catch up with "everything after seq N".

``record()`` writes in the caller's transaction. Live updates (Phase 3) hook
in through ``register_publisher``; publishers only run after the commit.

Every write route must carry ``@audit_route(...)`` or ``@no_audit(reason)``
(checked by scripts/audit_route_coverage.py). ``AuditBackstopMiddleware``
catches a route that changed data without writing an audit row.
"""

from __future__ import annotations

import asyncio
import contextvars
import csv
import difflib
import hashlib
import io
import json
import math
import os
import re
import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import models


# ── Schema ────────────────────────────────────────────────────────────────────
# group_deadline is when an open group closes: the earlier of "idle for too
# long" and "open for too long". The sweeper closes groups past it.
AUDIT_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seq INTEGER NOT NULL UNIQUE,
        ts_first TEXT NOT NULL,
        ts TEXT NOT NULL,
        actor_user_id INTEGER,
        actor_username TEXT,
        actor_display TEXT,
        actor_kind TEXT NOT NULL DEFAULT 'system',
        source TEXT NOT NULL DEFAULT 'system',
        request_id TEXT,
        session_id INTEGER,
        client_ip TEXT,
        route TEXT,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        job_id INTEGER,
        field_path TEXT,
        summary TEXT NOT NULL DEFAULT '',
        changes TEXT NOT NULL DEFAULT '[]',
        group_key TEXT,
        group_open INTEGER NOT NULL DEFAULT 0,
        group_deadline TEXT,
        edit_count INTEGER NOT NULL DEFAULT 1,
        net_noop INTEGER NOT NULL DEFAULT 0,
        proposal_version_id INTEGER,
        extra TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_audit_log_job ON audit_log(job_id, id);
    CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id, id);
    CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);
    CREATE INDEX IF NOT EXISTS idx_audit_log_request ON audit_log(request_id);
    CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log(actor_username, id);
    -- At most one open group per entity + field.
    CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_log_open_group
        ON audit_log(group_key) WHERE group_open = 1;
    CREATE INDEX IF NOT EXISTS idx_audit_log_group_deadline
        ON audit_log(group_deadline) WHERE group_open = 1;

    -- Everyone who edited a grouped entry. Rows that were never grouped have
    -- no actor rows; their one actor is on audit_log itself.
    CREATE TABLE IF NOT EXISTS audit_log_actors (
        audit_id INTEGER NOT NULL,
        actor_key TEXT NOT NULL,
        user_id INTEGER,
        username TEXT,
        display_name TEXT,
        actor_kind TEXT NOT NULL DEFAULT 'user',
        edit_count INTEGER NOT NULL DEFAULT 1,
        first_ts TEXT NOT NULL,
        last_ts TEXT NOT NULL,
        PRIMARY KEY (audit_id, actor_key)
    );
    CREATE INDEX IF NOT EXISTS idx_audit_log_actors_user ON audit_log_actors(username, audit_id);

    CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
    BEFORE DELETE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit_log is append-only: entries cannot be deleted');
    END;

    CREATE TRIGGER IF NOT EXISTS audit_log_closed_is_final
    BEFORE UPDATE ON audit_log
    WHEN OLD.group_open = 0
    BEGIN
        SELECT RAISE(ABORT, 'audit_log entries cannot be changed once closed');
    END;

    CREATE TRIGGER IF NOT EXISTS audit_log_open_group_identity
    BEFORE UPDATE ON audit_log
    WHEN OLD.group_open = 1 AND (
        NEW.id IS NOT OLD.id OR NEW.ts_first IS NOT OLD.ts_first
        OR NEW.action IS NOT OLD.action OR NEW.entity_type IS NOT OLD.entity_type
        OR NEW.entity_id IS NOT OLD.entity_id OR NEW.job_id IS NOT OLD.job_id
        OR NEW.field_path IS NOT OLD.field_path OR NEW.group_key IS NOT OLD.group_key
        OR NEW.actor_user_id IS NOT OLD.actor_user_id
        OR NEW.actor_username IS NOT OLD.actor_username
    )
    BEGIN
        SELECT RAISE(ABORT, 'an open audit_log group can only gain edits');
    END;

    CREATE TRIGGER IF NOT EXISTS audit_log_actors_no_delete
    BEFORE DELETE ON audit_log_actors
    BEGIN
        SELECT RAISE(ABORT, 'audit_log_actors is append-only');
    END;

    CREATE TRIGGER IF NOT EXISTS audit_log_actors_insert_open_only
    BEFORE INSERT ON audit_log_actors
    WHEN (SELECT group_open FROM audit_log WHERE id = NEW.audit_id) IS NOT 1
    BEGIN
        SELECT RAISE(ABORT, 'editors can only be added to an open audit_log group');
    END;

    CREATE TRIGGER IF NOT EXISTS audit_log_actors_update_open_only
    BEFORE UPDATE ON audit_log_actors
    WHEN (SELECT group_open FROM audit_log WHERE id = OLD.audit_id) IS NOT 1
    BEGIN
        SELECT RAISE(ABORT, 'editors of a closed audit_log group cannot change');
    END;
"""

BACKFILL_SETTING_KEY = "audit_legacy_backfill_v1"


def ensure_schema(conn) -> None:
    """Create the audit tables, indexes and triggers (safe to run every start)."""
    conn.executescript(AUDIT_SCHEMA_SQL)


def init_audit(conn) -> None:
    """Called from models.init_db: schema, one-time legacy backfill, and close
    any groups a previous run left open (nobody is mid-edit after a restart)."""
    ensure_schema(conn)
    backfill_legacy(conn)
    close_all_open_groups(conn)


# ── Time ──────────────────────────────────────────────────────────────────────
# Tests replace this with a function returning a fixed aware datetime.
_clock = None


def utc_now() -> datetime:
    return _clock() if _clock is not None else datetime.now(timezone.utc)


def iso_ms(value: datetime) -> str:
    """UTC ISO text with milliseconds and a Z, e.g. 2026-09-24T14:05:09.123Z.

    Same format as JavaScript's Date.toISOString(), and one fixed width, so
    timestamps sort and compare correctly as text.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def parse_ts(text) -> datetime | None:
    """Read a stored or legacy timestamp. Naive values are UTC (the server's
    clock is UTC on Fly). Returns an aware datetime, or None."""
    if isinstance(text, datetime):
        value = text
    else:
        text = str(text or "").strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ── Who is acting ─────────────────────────────────────────────────────────────
_system_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar("si_audit_system", default=None)

# Sources a live request can have (models.get_audit_context) -> audit source.
_REQUEST_SOURCES = {"http": "http", "websocket": "ws", "ws": "ws"}


@contextmanager
def system_context(source: str, **detail):
    """Attribute writes in this block to "System" with the given source.

    For startup, background threads and migrations, e.g.::

        with system_context("inbox_monitor", mailbox=address):
            log_activity(...)

    A logged-in person (if any) is still recorded as the actor; the source
    says where the work came from. ``detail`` is saved in the entry's extra.
    """
    token = _system_context.set({"source": str(source), "detail": dict(detail) or None})
    try:
        yield
    finally:
        _system_context.reset(token)


def current_actor() -> dict:
    """Who is making the current change, and from where."""
    user = models.get_current_user()
    context = models.get_audit_context()
    system = _system_context.get()
    request_source = context.get("source")
    if system is not None:
        source = system["source"]
    else:
        source = _REQUEST_SOURCES.get(request_source, request_source or "system")
    if user:
        kind = "user"
        display = user.get("display_name") or user.get("username")
    elif system is not None or request_source in (None, "system"):
        kind = "system"
        display = "System"
    else:
        kind = "anonymous"
        display = "Not logged in"
    username = (user or {}).get("username")
    return {
        "user_id": (user or {}).get("id"),
        "username": username,
        "display": display,
        "kind": kind,
        "source": source,
        "key": username.lower() if username else f"{kind}:{source}",
        "request_id": context.get("request_id"),
        "session_id": context.get("session_id"),
        "client_ip": context.get("client_ip"),
        "route": context.get("route"),
        "detail": system["detail"] if system is not None else None,
    }


def actor_label() -> str:
    """Short text for jobs.updated_by: the username, or system:<source>."""
    actor = current_actor()
    return actor["username"] or f"system:{actor['source']}"


def _request_context() -> dict | None:
    # The live per-request dict (not the copy get_audit_context returns), so
    # counts written in a worker thread are seen by the middleware.
    return models._audit_context.get()


def note_checked(job_id=None, *, legacy: bool = False) -> None:
    """Tell the backstop this request went through the audit layer.

    ``record()`` calls it; a write wrapper that found nothing changed calls it
    directly, so a save with no changes isn't reported as unaudited.
    """
    context = _request_context()
    if context is None:
        return
    context["write_count"] = int(context.get("write_count") or 0) + 1
    if job_id is not None and not legacy:
        try:
            context.setdefault("audited_jobs", set()).add(int(job_id))
        except (TypeError, ValueError):
            pass


def job_audited_in_request(job_id) -> bool:
    context = _request_context()
    if context is None or job_id is None:
        return False
    try:
        return int(job_id) in (context.get("audited_jobs") or set())
    except (TypeError, ValueError):
        return False


# ── Active write (job_write / entity_write on this thread) ───────────────────
# Lets log_activity write inside the open transaction instead of opening a
# second connection that would wait on the write lock.
_active = threading.local()


def push_active_write(tx) -> None:
    stack = getattr(_active, "stack", None)
    if stack is None:
        stack = _active.stack = []
    stack.append(tx)


def pop_active_write(tx) -> None:
    stack = getattr(_active, "stack", None) or []
    if stack and stack[-1] is tx:
        stack.pop()
    elif tx in stack:
        stack.remove(tx)


def active_write():
    stack = getattr(_active, "stack", None)
    return stack[-1] if stack else None


# ── Structured diff ───────────────────────────────────────────────────────────
# Keys that change on every save without meaning anything to a person.
VOLATILE_KEYS = frozenset({
    "_client_session_id", "_client_edit_version", "_client_save_sequence",
    "_server_revision", "audit", "audit_source_fingerprint",
    "pdf_generated_at", "last_seen_at",
})
# Rows in a list are matched by the first of these every row has (unique).
ROW_ID_KEYS = ("uid", "line_key", "id", "item_code")
# Values the server computes from other values: flagged derived=true so the
# history can hide them behind the edit that caused them.
DERIVED_KEYS = frozenset({
    "extended_cost", "total_price", "taxable", "tax_amount", "gpm_adder",
    "gpm_labor_adder", "gpm_material_adder", "material_cost", "sundry_cost",
    "labor_cost", "freight_cost", "bundle_cost", "total_cost", "subtotal",
    "grand_total", "gpm_profit", "gpm_labor", "gpm_material",
    "manual_adjustment", "textura_amount", "slug", "pdf_source_fingerprint",
    "pdf_audit_run_id", "pdf_ruleset_version",
})
DERIVED_SEGMENTS = frozenset({"totals", "pdf_totals", "computed"})
# Whole parts of a bid that are calculated (sundry and labor rows, generated
# bid bundles, the generated bid). Only applies to job entries.
DERIVED_JOB_ROOTS = frozenset({"sundries", "labor", "bundles", "bid"})


def escape_path_key(key) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def split_path(path: str | None) -> list[str]:
    if not path:
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in str(path).split("/")[1:]]


def is_derived_path(path: str, entity_type: str | None = None) -> bool:
    parts = split_path(path)
    if not parts:
        return False
    if entity_type in (None, "job") and parts[0] in DERIVED_JOB_ROOTS:
        return True
    if any(part in DERIVED_SEGMENTS for part in parts):
        return True
    return parts[-1] in DERIVED_KEYS


def _blank(value) -> bool:
    """Nothing there: None, "", or an empty list or dict. A field going from
    missing to [] or {} is not a change anyone made."""
    if value is None:
        return True
    if isinstance(value, (str, list, tuple, dict)):
        return len(value) == 0
    return False


def values_equal(a, b) -> bool:
    """Deep equality for audit purposes: None, "", [] and {} are the same,
    numbers compare with a tiny tolerance, volatile keys and
    missing-vs-blank keys are ignored."""
    if _blank(a) and _blank(b):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
        except (OverflowError, ValueError):
            return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return all(values_equal(a.get(key), b.get(key)) for key in (set(a) | set(b)) - VOLATILE_KEYS)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b))
    return a == b


def _strip_volatile(value):
    if isinstance(value, dict):
        return {key: _strip_volatile(item) for key, item in value.items() if key not in VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_strip_volatile(item) for item in value]
    return value


def _canonical(value) -> str:
    return json.dumps(_strip_volatile(value), sort_keys=True, default=str)


def _change(path: str, op: str, before, after) -> dict:
    return {"path": path, "op": op, "before": _strip_volatile(before), "after": _strip_volatile(after), "derived": False}


def line_hunks(before: list, after: list) -> list[dict]:
    """difflib line operations between two lists of strings."""
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return [
        {"op": tag, "before_start": i1, "after_start": j1, "before": before[i1:i2], "after": after[j1:j2]}
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def _pick_row_key(before: list, after: list) -> str | None:
    rows = list(before) + list(after)
    for key in ROW_ID_KEYS:
        if not all(not _blank(row.get(key)) for row in rows):
            continue
        if all(len({str(row[key]) for row in side}) == len(side) for side in (before, after)):
            return key
    return None


def _diff_value(before, after, path: str, out: list) -> None:
    if values_equal(before, after):
        return
    if isinstance(before, dict) and isinstance(after, dict):
        keys = list(before) + [key for key in after if key not in before]
        for key in keys:
            if key in VOLATILE_KEYS:
                continue
            child = f"{path}/{escape_path_key(key)}"
            if key not in after:
                if isinstance(before[key], (dict, list, tuple)):
                    _diff_value(before[key], None, child, out)  # per key / per row
                elif not _blank(before[key]):
                    out.append(_change(child, "remove", before[key], None))
            elif key not in before:
                if isinstance(after[key], (dict, list, tuple)):
                    _diff_value(None, after[key], child, out)  # per key / per row
                elif not _blank(after[key]):
                    out.append(_change(child, "add", None, after[key]))
            else:
                _diff_value(before[key], after[key], child, out)
        return
    if isinstance(before, (list, tuple)) and isinstance(after, (list, tuple)):
        _diff_list(list(before), list(after), path, out)
        return
    # A list or dict appearing in (or cleared from) an empty field: diff it
    # as rows/lines or key by key, so the history shows what was added or
    # cleared instead of one unreadable blob.
    if _blank(before) and isinstance(after, (list, tuple)):
        _diff_list([], list(after), path, out)
        return
    if isinstance(before, (list, tuple)) and _blank(after):
        _diff_list(list(before), [], path, out)
        return
    if _blank(before) and isinstance(after, dict):
        _diff_value({}, after, path, out)
        return
    if isinstance(before, dict) and _blank(after):
        _diff_value(before, {}, path, out)
        return
    out.append(_change(path, "replace", before, after))


def _diff_list(before: list, after: list, path: str, out: list) -> None:
    items = before + after
    if items and all(isinstance(item, str) for item in items):
        out.append({
            "path": path, "op": "lines", "before": before, "after": after,
            "derived": False, "hunks": line_hunks(before, after),
        })
        return
    if items and all(isinstance(item, dict) for item in items):
        key = _pick_row_key(before, after)
        if key is not None:
            _diff_keyed_rows(before, after, key, path, out)
            return
        _diff_aligned(before, after, path, out)
        return
    if all(not isinstance(item, (dict, list, tuple)) for item in items):
        out.append(_change(path, "replace", before, after))
        return
    _diff_aligned(before, after, path, out)


def _diff_keyed_rows(before: list, after: list, key: str, path: str, out: list) -> None:
    before_rows = {str(row[key]): row for row in before}
    after_rows = {str(row[key]): row for row in after}
    for row_id, row in before_rows.items():
        child = f"{path}/{escape_path_key(row_id)}"
        if row_id not in after_rows:
            out.append(_change(child, "remove", row, None))
        else:
            _diff_value(row, after_rows[row_id], child, out)
    for row_id, row in after_rows.items():
        if row_id not in before_rows:
            out.append(_change(f"{path}/{escape_path_key(row_id)}", "add", None, row))
    kept_before = [row_id for row_id in before_rows if row_id in after_rows]
    kept_after = [row_id for row_id in after_rows if row_id in before_rows]
    if kept_before != kept_after:
        out.append(_change(f"{path}/_order", "replace", list(before_rows), list(after_rows)))


def _diff_aligned(before: list, after: list, path: str, out: list) -> None:
    """Rows without ids: line them up by content, then diff paired rows."""
    matcher = difflib.SequenceMatcher(
        None, [_canonical(item) for item in before], [_canonical(item) for item in after], autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        paired = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        for offset in range(paired):
            _diff_value(before[i1 + offset], after[j1 + offset], f"{path}/{j1 + offset}", out)
        for index in range(i1 + paired, i2):
            out.append(_change(f"{path}/{index}", "remove", before[index], None))
        for index in range(j1 + paired, j2):
            out.append(_change(f"{path}/{index}", "add", None, after[index]))


def diff(before, after, path: str = "", *, entity_type: str | None = None) -> list[dict]:
    """Structured changes from ``before`` to ``after``.

    Returns ``[{path, op, before, after, derived}]`` where ``path`` is a JSON
    pointer such as ``/materials/12/unit_price`` and ``op`` is add, remove,
    replace or lines. Dicts are compared key by key; lists of dicts match rows
    by uid / line_key / id / item_code (rows without ids are lined up by
    content); lists of strings give one "lines" change with difflib hunks.
    None and "" are equal, and VOLATILE_KEYS are ignored at any depth.
    """
    out: list[dict] = []
    if isinstance(before, dict) and after is None:
        _diff_value(before, {}, path, out)
    elif before is None and isinstance(after, dict):
        _diff_value({}, after, path, out)
    else:
        _diff_value(before, after, path, out)
    for change in out:
        change["derived"] = is_derived_path(change["path"], entity_type)
    return out


def common_path(paths) -> str | None:
    """Longest shared path prefix, by segment ("/a/b/c", "/a/b/d" -> "/a/b")."""
    split = [str(path).split("/")[1:] for path in paths if path]
    if not split:
        return None
    shared = []
    for parts in zip(*split):
        if len(set(parts)) != 1:
            break
        shared.append(parts[0])
    return "/" + "/".join(shared) if shared else None


def describe_changes(changes: list[dict], noun: str = "") -> str:
    """Fallback plain-English summary, e.g. "Changed notes and city"."""
    shown = [change for change in changes if not change.get("derived")] or list(changes)
    labels: list[str] = []
    for change in shown:
        parts = [part for part in split_path(change.get("path")) if part != "_order" and not part.isdigit()]
        label = (parts[-1] if parts else noun or "details").replace("_", " ")
        if label not in labels:
            labels.append(label)
    if not labels:
        return f"Changed {noun}".strip() if noun else "Changed"
    if len(labels) == 1:
        return f"Changed {labels[0]}"
    if len(labels) <= 3:
        return f"Changed {', '.join(labels[:-1])} and {labels[-1]}"
    return f"Changed {', '.join(labels[:2])} and {len(labels) - 2} more"


# ── Redaction and size caps ───────────────────────────────────────────────────
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[^a-z])(?:api_?keys?|passwords?|passwd|secrets?|tokens?|pins?|pin_?hash(?:es)?)(?:$|[^a-z])"
)
REDACTED = {"redacted": True, "changed": True}
MAX_VALUE_BYTES = 8 * 1024
MAX_CHANGES = 500
MAX_CHANGES_JSON_BYTES = 512 * 1024
SMALL_VALUE_BYTES = 1024
_HEAD_CHARS = 300


def is_sensitive_key(key) -> bool:
    """API keys, passwords, secrets, tokens and PINs never go in the audit log."""
    return bool(_SENSITIVE_KEY_RE.search(str(key).lower()))


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def scrub(value):
    """Replace the values of sensitive keys at any depth (also inside JSON text)."""
    if isinstance(value, dict):
        return {
            key: ({"redacted": True} if is_sensitive_key(key) and not _blank(item) else scrub(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str) and value[:1] in ("{", "[") and len(value) < 200_000:
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        if isinstance(parsed, (dict, list)):
            cleaned = scrub(parsed)
            if cleaned != parsed:
                return json.dumps(cleaned, ensure_ascii=False)
        return value
    return value


def _cap(value, limit: int = MAX_VALUE_BYTES):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict) and value.get("truncated") is True and "hash" in value:
        return value  # already capped
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    size = len(text.encode("utf-8"))
    if size <= limit:
        return value
    head = value if isinstance(value, str) else text
    return {
        "truncated": True,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "len": size,
        "head": head[:_HEAD_CHARS],
    }


def _cap_change(change: dict, limit: int) -> None:
    change["before"] = _cap(change.get("before"), limit)
    change["after"] = _cap(change.get("after"), limit)
    for hunk in change.get("hunks") or []:
        if isinstance(hunk, dict):
            hunk["before"] = _cap(hunk.get("before"), limit)
            hunk["after"] = _cap(hunk.get("after"), limit)


def prepare_changes(changes, entity_type: str | None = None) -> tuple[list[dict], dict | None]:
    """Make changes safe and small enough to store: redact secrets, cap big
    values and keep at most MAX_CHANGES (edits first, derived values last).
    Returns (changes, truncation info or None). Safe to run twice."""
    prepared: list[dict] = []
    for raw in changes or []:
        change = dict(raw)
        change["path"] = str(change.get("path") or "")
        change["op"] = change.get("op") or "replace"
        change["derived"] = bool(change["derived"]) if "derived" in change else is_derived_path(change["path"], entity_type)
        change["before"] = _jsonable(change.get("before"))
        change["after"] = _jsonable(change.get("after"))
        if "hunks" in change:
            change["hunks"] = _jsonable(change["hunks"])
        if change.get("redacted") or any(is_sensitive_key(part) for part in split_path(change["path"])):
            change["before"] = dict(REDACTED) if not _blank(change["before"]) else None
            change["after"] = dict(REDACTED) if not _blank(change["after"]) else None
            change.pop("hunks", None)
            change["redacted"] = True
        else:
            change["before"] = scrub(change["before"])
            change["after"] = scrub(change["after"])
            if "hunks" in change:
                change["hunks"] = scrub(change["hunks"])
        _cap_change(change, MAX_VALUE_BYTES)
        prepared.append(change)

    truncation = None
    if len(prepared) > MAX_CHANGES:
        ordered = [c for c in prepared if not c["derived"]] + [c for c in prepared if c["derived"]]
        truncation = {
            "total": len(prepared),
            "kept": MAX_CHANGES,
            "by_op": dict(Counter(c["op"] for c in prepared)),
            "derived": sum(1 for c in prepared if c["derived"]),
        }
        prepared = ordered[:MAX_CHANGES]
    if len(json.dumps(prepared, ensure_ascii=False, default=str).encode("utf-8")) > MAX_CHANGES_JSON_BYTES:
        for change in prepared:
            _cap_change(change, SMALL_VALUE_BYTES)
    return prepared, truncation


def _prepare_extra(extra, truncation: dict | None, system_detail: dict | None):
    result = dict(extra or {})
    if truncation:
        result["changes_truncated"] = truncation
    if system_detail:
        result.setdefault("context", system_detail)
    if not result:
        return None
    result = scrub(_jsonable(result))
    return {key: _cap(value) for key, value in result.items()}


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


# ── Grouping ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GroupPolicy:
    """Join an open entry for the same entity + field while it has been idle
    at most ``idle_s`` seconds and open at most ``max_s`` seconds."""

    idle_s: float
    max_s: float = 15 * 60


TEXT_EDITS = GroupPolicy(idle_s=60, max_s=15 * 60)
NUMBER_EDITS = GroupPolicy(idle_s=30, max_s=15 * 60)


def group_key(entity_type: str, entity_id, field_path) -> str:
    raw = f"{entity_type}|{'' if entity_id is None else entity_id}|{field_path or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def edited_paths(changes) -> set[str]:
    """Paths a person edited (derived values left out, unless that's all there is)."""
    changes = list(changes or [])
    edited = {str(change.get("path") or "") for change in changes if not change.get("derived")}
    return edited or {str(change.get("path") or "") for change in changes}


def _group_field(field_path: str | None, changes: list[dict]) -> str:
    """What a group is keyed on besides the entity: the field, or for a save
    that changed several unrelated fields, that exact set of fields (so it
    only joins other saves of the same fields, never unrelated ones)."""
    if field_path:
        return field_path
    paths = sorted(edited_paths(changes))
    return "fields:" + "\n".join(paths) if paths else ""


def _group_deadline(now: datetime, first: datetime, policy: GroupPolicy) -> str:
    return iso_ms(min(now + timedelta(seconds=policy.idle_s), first + timedelta(seconds=policy.max_s)))


def _change_is_noop(change: dict) -> bool:
    if change.get("redacted"):
        return False
    before, after = change.get("before"), change.get("after")
    if isinstance(before, dict) and isinstance(after, dict) and before.get("truncated") and after.get("truncated"):
        return before.get("hash") == after.get("hash")
    return values_equal(before, after)


def merge_changes(earlier: list[dict], later: list[dict]) -> list[dict]:
    """Fold a later edit into an open group: keep the first "before" for each
    path and the latest "after"."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for change in earlier:
        path = change.get("path")
        if path not in merged:
            order.append(path)
        merged[path] = dict(change)
    for change in later:
        path = change.get("path")
        if path not in merged:
            merged[path] = dict(change)
            order.append(path)
            continue
        entry = merged[path]
        before_absent = entry.get("op") == "add"
        after_absent = change.get("op") == "remove"
        entry["after"] = change.get("after")
        entry["derived"] = bool(entry.get("derived")) and bool(change.get("derived"))
        entry["redacted"] = bool(entry.get("redacted")) or bool(change.get("redacted"))
        if not entry["redacted"]:
            entry.pop("redacted")
        before, after = entry.get("before"), entry["after"]
        if (
            isinstance(before, list) and isinstance(after, list)
            and all(isinstance(line, str) for line in before + after)
        ):
            entry["op"] = "lines"
            entry["hunks"] = line_hunks(before, after)
            continue
        entry.pop("hunks", None)
        if before_absent and not after_absent:
            entry["op"] = "add"
        elif after_absent and not before_absent:
            entry["op"] = "remove"
        else:
            entry["op"] = "replace"
    return [merged[path] for path in order]


# ── Writing ───────────────────────────────────────────────────────────────────
def _ensure_write_transaction(conn) -> None:
    # MAX(seq)+1 and the group lookups are only safe while holding the write
    # lock. A connection already in a transaction has written something, so
    # it holds the lock; otherwise take it now. The caller commits.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _next_seq(conn) -> int:
    return int(conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_log").fetchone()[0])


def record(
    conn,
    *,
    action: str,
    entity_type: str,
    entity_id=None,
    job_id=None,
    summary: str,
    before=None,
    after=None,
    changes=None,
    field_path: str | None = None,
    group: GroupPolicy | None = None,
    extra: dict | None = None,
    proposal_version_id: int | None = None,
    _legacy: bool = False,
) -> int | None:
    """Write one audit entry in the caller's transaction; returns its id.

    Give either ``before``/``after`` (diffed here, paths under ``field_path``)
    or a ready ``changes`` list, or neither for an event with no field changes
    (a login, a PDF). When before/after are given and nothing changed, nothing
    is written and None is returned.

    ``group``: join the open entry for this entity + field_path if it has the
    same action and is within the policy's idle/max time; otherwise start one.
    With no field_path (a save that changed several fields) the group is
    keyed on that exact set of edited fields instead. Without a group the
    entry is written closed, and any open groups on the same entity are
    closed first so history reads in order.

    Takes the write lock (BEGIN IMMEDIATE) if the connection isn't already in
    a transaction; the caller commits and then calls ``after_commit(conn)``.
    If you open the transaction yourself, open it with BEGIN IMMEDIATE (or
    write something first), so the seq number can't race another writer.
    """
    note_checked(job_id, legacy=_legacy)
    compare = before is not None or after is not None
    if changes is None:
        changes = diff(before, after, field_path or "", entity_type=entity_type) if compare else []
    else:
        changes = list(changes)
    if compare and not changes:
        return None

    _ensure_write_transaction(conn)
    actor = current_actor()
    changes, truncation = prepare_changes(changes, entity_type)
    extra_value = _prepare_extra(extra, truncation, actor["detail"])
    if group is not None and actor["request_id"]:
        # A group spans several requests; keep them all findable.
        extra_value = dict(extra_value or {})
        extra_value.setdefault("request_ids", [actor["request_id"]])
    now = utc_now()
    ts = iso_ms(now)
    entity_id = None if entity_id is None else str(entity_id)
    job_id = None if job_id is None else int(job_id)

    if group is None:
        close_entity_groups(conn, entity_type, entity_id, now=now)
        return _insert(conn, actor, ts, action, entity_type, entity_id, job_id, field_path, summary,
                       changes, None, None, extra_value, proposal_version_id)

    key = group_key(entity_type, entity_id, _group_field(field_path, changes))
    open_row = conn.execute(
        "SELECT * FROM audit_log WHERE group_key = ? AND group_open = 1", (key,)
    ).fetchone()
    if open_row is not None:
        last = parse_ts(open_row["ts"]) or now
        first = parse_ts(open_row["ts_first"]) or now
        if (
            open_row["action"] == action
            and (now - last).total_seconds() <= group.idle_s
            and (now - first).total_seconds() <= group.max_s
        ):
            return _join_group(conn, open_row, actor, now, changes, summary, extra_value, group)
        close_group(conn, open_row)
    return _insert(conn, actor, ts, action, entity_type, entity_id, job_id, field_path, summary,
                   changes, key, _group_deadline(now, now, group), extra_value, proposal_version_id)


def _insert(conn, actor, ts, action, entity_type, entity_id, job_id, field_path, summary,
            changes, key, deadline, extra_value, proposal_version_id) -> int:
    seq = _next_seq(conn)
    group_open = 1 if key else 0
    cur = conn.execute(
        """INSERT INTO audit_log (
               seq, ts_first, ts, actor_user_id, actor_username, actor_display, actor_kind,
               source, request_id, session_id, client_ip, route, action, entity_type,
               entity_id, job_id, field_path, summary, changes, group_key, group_open,
               group_deadline, edit_count, net_noop, proposal_version_id, extra)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)""",
        (
            seq, ts, ts, actor["user_id"], actor["username"], actor["display"], actor["kind"],
            actor["source"], actor["request_id"], actor["session_id"], actor["client_ip"],
            actor["route"], action, entity_type, entity_id, job_id, field_path,
            str(summary or ""), _dumps(changes), key, group_open, deadline,
            proposal_version_id, _dumps(extra_value) if extra_value else None,
        ),
    )
    audit_id = int(cur.lastrowid)
    if group_open:
        _upsert_actor(conn, audit_id, actor, ts)
    _queue_publish(conn, {
        "id": audit_id, "seq": seq, "job_id": job_id, "entity_type": entity_type,
        "entity_id": entity_id, "action": action, "group_open": bool(group_open),
    })
    return audit_id


def _upsert_actor(conn, audit_id: int, actor: dict, ts: str) -> None:
    conn.execute(
        """INSERT INTO audit_log_actors
               (audit_id, actor_key, user_id, username, display_name, actor_kind, edit_count, first_ts, last_ts)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
           ON CONFLICT(audit_id, actor_key) DO UPDATE SET
               edit_count = edit_count + 1,
               last_ts = excluded.last_ts,
               display_name = excluded.display_name""",
        (audit_id, actor["key"], actor["user_id"], actor["username"], actor["display"], actor["kind"], ts, ts),
    )


def _join_group(conn, row, actor, now, changes, summary, extra_value, policy: GroupPolicy) -> int:
    try:
        earlier = json.loads(row["changes"] or "[]")
    except ValueError:
        earlier = []
    merged, truncation = prepare_changes(merge_changes(earlier, changes), row["entity_type"])
    if merged and not edited_paths(changes) >= edited_paths(merged):
        # This edit's summary only describes this edit, but the entry also
        # holds earlier edits to other fields: describe all of them.
        noun = "bid" if row["entity_type"] == "job" else str(row["entity_type"]).replace("_", " ")
        summary = describe_changes(merged, noun)
    try:
        extra_merged = json.loads(row["extra"]) if row["extra"] else {}
    except ValueError:
        extra_merged = {}
    if truncation:
        extra_merged["changes_truncated"] = truncation
    request_ids = list(extra_merged.get("request_ids") or [])
    for request_id in (extra_value or {}).get("request_ids") or []:
        if request_id not in request_ids:
            request_ids.append(request_id)
    if request_ids:
        extra_merged["request_ids"] = request_ids[-50:]
    ts = iso_ms(now)
    first = parse_ts(row["ts_first"]) or now
    seq = _next_seq(conn)
    conn.execute(
        """UPDATE audit_log
           SET ts = ?, seq = ?, changes = ?, summary = ?, edit_count = edit_count + 1,
               group_deadline = ?, request_id = COALESCE(?, request_id), extra = ?
           WHERE id = ? AND group_open = 1""",
        (
            ts, seq, _dumps(merged), str(summary or row["summary"] or ""),
            _group_deadline(now, first, policy), actor["request_id"],
            _dumps(extra_merged) if extra_merged else None, row["id"],
        ),
    )
    _upsert_actor(conn, int(row["id"]), actor, ts)
    _queue_publish(conn, {
        "id": int(row["id"]), "seq": seq, "job_id": row["job_id"], "entity_type": row["entity_type"],
        "entity_id": row["entity_id"], "action": row["action"], "group_open": True,
    })
    return int(row["id"])


def close_group(conn, row) -> None:
    """Close one open group; net_noop when every path ended where it started."""
    try:
        changes = json.loads(row["changes"] or "[]")
    except ValueError:
        changes = []
    net_noop = 1 if changes and all(_change_is_noop(change) for change in changes) else 0
    seq = _next_seq(conn)
    conn.execute(
        "UPDATE audit_log SET group_open = 0, net_noop = ?, seq = ? WHERE id = ? AND group_open = 1",
        (net_noop, seq, row["id"]),
    )
    _queue_publish(conn, {
        "id": int(row["id"]), "seq": seq, "job_id": row["job_id"], "entity_type": row["entity_type"],
        "entity_id": row["entity_id"], "action": row["action"], "group_open": False,
    })


def close_entity_groups(conn, entity_type: str, entity_id, now: datetime | None = None) -> int:
    """Close every open group on one entity (before a one-off entry on it)."""
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE group_open = 1 AND entity_type = ? AND entity_id IS ?",
        (entity_type, None if entity_id is None else str(entity_id)),
    ).fetchall()
    for row in rows:
        close_group(conn, row)
    return len(rows)


@contextmanager
def write_transaction():
    """A connection holding the write lock; commits (and publishes) on success."""
    conn = models._get_conn()
    committed = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
        committed = True
        after_commit(conn)
    except BaseException:
        if not committed:
            try:
                conn.rollback()
            except Exception:
                pass
            discard_pending(conn)
        raise
    finally:
        conn.close()


def close_all_open_groups(conn=None) -> int:
    """Startup: nobody is mid-edit after a restart, so close every open group."""
    if conn is None:
        with write_transaction() as own:
            return close_all_open_groups(own)
    if not conn.in_transaction:
        if conn.execute("SELECT 1 FROM audit_log WHERE group_open = 1 LIMIT 1").fetchone() is None:
            return 0
        conn.execute("BEGIN IMMEDIATE")
        count = _close_rows(conn, conn.execute("SELECT * FROM audit_log WHERE group_open = 1").fetchall())
        conn.commit()
        after_commit(conn)
        return count
    return _close_rows(conn, conn.execute("SELECT * FROM audit_log WHERE group_open = 1").fetchall())


def _close_rows(conn, rows) -> int:
    for row in rows:
        close_group(conn, row)
    return len(rows)


def sweep_idle_groups(now: datetime | None = None) -> int:
    """Close groups whose idle/max time has passed. Returns how many closed."""
    cutoff = iso_ms(now or utc_now())
    conn = models._get_conn()
    committed = False
    try:
        due = conn.execute(
            "SELECT 1 FROM audit_log WHERE group_open = 1 AND group_deadline <= ? LIMIT 1", (cutoff,)
        ).fetchone()
        if due is None:
            return 0  # the usual case: no write lock needed
        conn.execute("BEGIN IMMEDIATE")
        count = _close_rows(conn, conn.execute(
            "SELECT * FROM audit_log WHERE group_open = 1 AND group_deadline <= ?", (cutoff,)
        ).fetchall())
        conn.commit()
        committed = True
        after_commit(conn)
        return count
    except BaseException:
        if not committed:
            try:
                conn.rollback()
            except Exception:
                pass
            discard_pending(conn)
        raise
    finally:
        conn.close()


SWEEP_INTERVAL_SECONDS = 10
_sweeper_tasks: dict = {}


async def _sweep_forever() -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(sweep_idle_groups)
        except Exception as err:  # keep sweeping; a busy database clears up
            print(f"[audit] Couldn't close idle history entries: {err}")


def start_sweeper() -> None:
    """Start the idle-group sweeper on the running event loop (once per loop)."""
    loop = asyncio.get_running_loop()
    task = _sweeper_tasks.get(loop)
    if task is None or task.done():
        _sweeper_tasks[loop] = loop.create_task(_sweep_forever())


def stop_sweeper() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = _sweeper_tasks.pop(loop, None)
    if task is not None:
        task.cancel()


# ── After-commit publishing ───────────────────────────────────────────────────
# record() queues a small event per written/updated row on the connection;
# after_commit() hands them to the publishers (none yet: the live channel
# arrives in Phase 3). Events of a rolled-back transaction are discarded.
_publishers: list = []
_foreign_pending: dict[int, tuple[object, list]] = {}
_foreign_lock = threading.Lock()


def register_publisher(publisher) -> None:
    """``publisher(events)`` is called after each commit that wrote audit rows.
    Events are {id, seq, job_id, entity_type, entity_id, action, group_open};
    read the rows by seq for details. Errors are logged, never raised."""
    if publisher not in _publishers:
        _publishers.append(publisher)


def unregister_publisher(publisher) -> None:
    if publisher in _publishers:
        _publishers.remove(publisher)


def _queue_publish(conn, event: dict) -> None:
    pending = getattr(conn, "_audit_pending", None)
    if pending is None:
        try:
            conn._audit_pending = pending = []
        except AttributeError:
            # A plain sqlite3 connection can't carry attributes; keep its
            # events here (with the connection, so the id isn't reused).
            with _foreign_lock:
                entry = _foreign_pending.get(id(conn))
                if entry is None or entry[0] is not conn:
                    entry = _foreign_pending[id(conn)] = (conn, [])
                    if len(_foreign_pending) > 1000:
                        _foreign_pending.pop(next(iter(_foreign_pending)))
                pending = entry[1]
    pending.append(event)


def _take_pending(conn) -> list:
    pending = getattr(conn, "_audit_pending", None)
    if pending is not None:
        events = list(pending)
        pending.clear()
        return events
    with _foreign_lock:
        entry = _foreign_pending.pop(id(conn), None)
    return list(entry[1]) if entry is not None and entry[0] is conn else []


def discard_pending(conn) -> None:
    """Drop queued events after a rollback."""
    _take_pending(conn)


def after_commit(conn) -> None:
    """Publish the events queued on ``conn``. Call right after conn.commit()."""
    events = _take_pending(conn)
    if not events:
        return
    for publisher in list(_publishers):
        try:
            publisher(events)
        except Exception as err:
            print(f"[audit] Live update publisher failed: {err}")


# ── Legacy activity (models.log_activity) ─────────────────────────────────────
# job_activity action -> audit action.
LEGACY_ACTIONS = {
    "job_created": "job.create",
    "job_updated": "job.update",
    "notes_updated": "job.notes.update",
    "exclusions_updated": "job.exclusions.update",
    "materials_updated": "materials.update",
    "materials_deleted": "materials.delete",
    "transition_sticks_recounted": "materials.recount_transitions",
    "vendor_price_decision": "materials.price_decision",
    "ai_estimate": "materials.ai_estimate",
    "rfms_uploaded": "rfms.upload",
    "rfms_lines_removed": "rfms.lines_removed",
    "quotes_uploaded": "quotes.upload",
    "quotes_cleared": "quotes.clear",
    "quote_updated": "quotes.update",
    "agent_quote_imported": "quotes.auto_import",
    "quote_email_sent": "quote_request.email",
    "bid_calculated": "bid.calculate",
    "bid_generated": "bid.generate",
    "bid_cleared": "bid.clear",
    "proposal_generated": "proposal.pdf",
    "bid_sent": "bid.sent",
    "bid_won": "bid.won",
    "bid_lost": "bid.lost",
    "bid_follow_up": "bid.follow_up",
    "bid_note_added": "bid.note",
    "bid_status_changed": "bid.status",
    "bid_tracking_updated": "bid.tracking.update",
    "comment_added": "comment.add",
    "golden_baseline_captured": "golden.capture",
    "golden_replay_ran": "golden.replay",
}


def legacy_action(action: str) -> str:
    action = str(action or "").strip()
    return LEGACY_ACTIONS.get(action) or ("activity." + (action or "unknown"))


def changes_from_detail(detail) -> tuple[list[dict], dict | None]:
    """Old-style activity detail -> (changes, rest). Understands
    {"changes": {field: {"old", "new"}}} and a top-level {"old", "new"}."""
    if not isinstance(detail, dict):
        return [], ({"detail": detail} if detail not in (None, "", {}) else None)
    rest = dict(detail)
    changes: list[dict] = []
    raw = rest.pop("changes", None)
    if isinstance(raw, dict):
        for field, value in raw.items():
            if isinstance(value, dict) and ("old" in value or "new" in value):
                changes.append({
                    "path": "/" + escape_path_key(field), "op": "replace",
                    "before": value.get("old"), "after": value.get("new"),
                })
            else:
                rest.setdefault("changes", {})[field] = value
    elif raw is not None:
        rest["changes"] = raw
    if "old" in rest and "new" in rest:
        changes.append({"path": "/" + escape_path_key(rest.pop("field", "value")), "op": "replace",
                        "before": rest.pop("old"), "after": rest.pop("new")})
    return changes, (rest or None)


def record_legacy_activity(conn, job_id, action: str, summary: str, detail=None) -> int | None:
    """The audit half of models.log_activity (writes in ``conn``'s transaction).

    Inside a job_write for the same bid the activity becomes that entry's
    summary instead of a second entry; after a job_write for the bid in the
    same request it is skipped (the diffed entry already covers it).
    """
    tx = active_write()
    if tx is not None and getattr(tx, "job_id", None) is not None and job_id is not None \
            and int(tx.job_id) == int(job_id) and hasattr(tx, "note_activity"):
        tx.note_activity(action, summary, detail)
        note_checked(job_id, legacy=True)
        return None
    if job_audited_in_request(job_id):
        note_checked(job_id, legacy=True)
        return None
    changes, rest = changes_from_detail(detail)
    extra = {"activity_action": action}
    if rest:
        extra["detail"] = rest
    return record(
        conn,
        action=legacy_action(action),
        entity_type="job",
        entity_id=job_id,
        job_id=job_id,
        summary=summary,
        changes=changes,
        extra=extra,
        _legacy=True,
    )


# ── One-time copy of the old history tables ──────────────────────────────────
_BID_EVENT_ACTIVITY = {
    "sent": {"bid_sent"},
    "won": {"bid_won"},
    "lost": {"bid_lost"},
    "follow_up": {"bid_follow_up"},
    "note": {"bid_note_added", "bid_tracking_updated"},
    "status_change": {"bid_status_changed"},
}
_ADMIN_ACTIONS = {
    "added": ("user.create", "Added {name}"),
    "removed": ("user.remove", "Removed {name}"),
    "restored": ("user.restore", "Restored {name}"),
    "reset_pin": ("user.reset_pin", "Gave {name} a new PIN"),
    "renamed": ("user.rename", "Renamed {name}"),
    "made_admin": ("user.make_admin", "Made {name} an admin"),
    "removed_admin": ("user.remove_admin", "Took admin rights from {name}"),
    "startup_admin": ("user.startup_admin", "Set up admin login {name} at startup"),
}
_LEGACY_MATCH_SECONDS = 5


def admin_log_entry(action: str, target_username: str, details: dict | None = None,
                    name: str | None = None) -> tuple[str, str, list[dict]]:
    """(audit action, summary, changes) for a people change written to
    admin_log (models._log_admin_action), also used to copy old admin_log rows.
    ``name`` is the person's display name. A PIN is only ever "changed"."""
    details = details if isinstance(details, dict) else {}
    target = target_username or ""
    action_name, template = _ADMIN_ACTIONS.get(action, (f"user.{action}", "Changed {name}"))
    changes: list[dict] = []
    if action == "renamed":
        changes.append({"path": "/display_name", "op": "replace",
                        "before": details.get("from"), "after": details.get("to")})
    elif action in ("made_admin", "removed_admin"):
        changes.append({"path": "/is_admin", "op": "replace",
                        "before": action == "removed_admin", "after": action == "made_admin"})
    elif action in ("removed", "restored"):
        changes.append({"path": "/active", "op": "replace",
                        "before": action == "removed", "after": action == "restored"})
    elif action == "reset_pin":
        changes.append({"path": "/pin_hash", "op": "replace", "redacted": True,
                        "before": dict(REDACTED), "after": dict(REDACTED)})
    elif action == "added":
        changes.append({"path": "/username", "op": "add", "before": None, "after": target})
        if details.get("display_name"):
            changes.append({"path": "/display_name", "op": "add", "before": None,
                            "after": details.get("display_name")})
        if details.get("is_admin"):
            changes.append({"path": "/is_admin", "op": "add", "before": None, "after": True})
    elif action == "startup_admin":
        done = details.get("changes") or []
        if "created" in done:
            changes.append({"path": "/username", "op": "add", "before": None, "after": target})
            changes.append({"path": "/is_admin", "op": "add", "before": None, "after": True})
        if "made admin" in done:
            changes.append({"path": "/is_admin", "op": "replace", "before": False, "after": True})
        if "restored" in done:
            changes.append({"path": "/active", "op": "replace", "before": False, "after": True})
        if "PIN set" in done:
            changes.append({"path": "/pin_hash", "op": "add", "redacted": True,
                            "before": None, "after": dict(REDACTED)})
    if action == "renamed" and details.get("to"):
        return action_name, f"Renamed {details.get('from') or target} to {details['to']}", changes
    return action_name, template.format(name=name or target or "someone"), changes


def _loads(raw, default):
    if raw in (None, ""):
        return default
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return value


def _bid_event_summary(event_type: str, details: dict) -> str:
    if event_type == "sent":
        who = details.get("sent_to") or details.get("gc_name")
        return f"Bid sent to {who}" if who else "Bid marked as sent"
    if event_type in ("won", "lost"):
        return f"Bid {event_type}"
    if event_type == "follow_up":
        return "Bid follow-up logged"
    if event_type == "status_change":
        return f"Bid status changed from {details.get('from') or 'none'} to {details.get('to') or 'none'}"
    if details.get("changes"):
        return "Bid tracking updated"
    return "Bid note added"


def backfill_legacy(conn) -> int:
    """Copy job_activity, bid_events and admin_log into audit_log once
    (source "legacy_import"), oldest first. Marked done in app_settings."""
    if conn.execute("SELECT 1 FROM app_settings WHERE key = ?", (BACKFILL_SETTING_KEY,)).fetchone():
        return 0
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM app_settings WHERE key = ?", (BACKFILL_SETTING_KEY,)).fetchone():
            conn.rollback()
            return 0
        entries = _legacy_entries(conn)
        entries.sort(key=lambda entry: (entry["ts"], entry["order"]))
        seq = _next_seq(conn)
        for entry in entries:
            conn.execute(
                """INSERT INTO audit_log (
                       seq, ts_first, ts, actor_user_id, actor_username, actor_display, actor_kind,
                       source, action, entity_type, entity_id, job_id, summary, changes,
                       group_open, edit_count, net_noop, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'legacy_import', ?, ?, ?, ?, ?, ?, 0, 1, 0, ?)""",
                (
                    seq, entry["ts"], entry["ts"], entry["user_id"], entry["username"], entry["display"],
                    entry["kind"], entry["action"], entry["entity_type"], entry["entity_id"],
                    entry["job_id"], entry["summary"], _dumps(entry["changes"]), _dumps(entry["extra"]),
                ),
            )
            seq += 1
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)",
            (BACKFILL_SETTING_KEY, _dumps({"at": iso_ms(utc_now()), "rows": len(entries)})),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    if entries:
        print(f"[audit] Copied {len(entries)} older history entries into the audit log")
    return len(entries)


def _legacy_entries(conn) -> list[dict]:
    users = {
        str(row["username"]).lower(): dict(row)
        for row in conn.execute("SELECT id, username, display_name FROM users").fetchall()
    }

    def actor(username, label=None) -> dict:
        user = users.get(str(username).lower()) if username else None
        if user:
            return {"user_id": user["id"], "username": user["username"],
                    "display": user["display_name"] or user["username"], "kind": "user"}
        if username:
            return {"user_id": None, "username": username, "display": label or username, "kind": "user"}
        if label and label != "System":
            return {"user_id": None, "username": None, "display": label, "kind": "user"}
        return {"user_id": None, "username": None, "display": "System", "kind": "system"}

    fallback_ts = iso_ms(utc_now())

    def when(text) -> tuple[str, datetime | None]:
        parsed = parse_ts(text)
        return (iso_ms(parsed) if parsed else fallback_ts), parsed

    activity_columns = {row[1] for row in conn.execute("PRAGMA table_info(job_activity)").fetchall()}
    activity = []
    for row in conn.execute("SELECT * FROM job_activity ORDER BY id").fetchall():
        row = dict(row)
        ts, parsed = when(row.get("created_at"))
        activity.append({**row, "_ts": ts, "_dt": parsed, "_used": False})

    # The bid tracker wrote a bid_events row and an activity row for the same
    # moment; import the bid event (it has the details) with the activity's
    # wording, and skip the matching activity row.
    by_job: dict = {}
    for row in activity:
        if str(row.get("action") or "").startswith("bid_"):
            by_job.setdefault(row["job_id"], []).append(row)

    entries: list[dict] = []
    order = 0
    for row in conn.execute("SELECT * FROM bid_events ORDER BY id").fetchall():
        row = dict(row)
        ts, parsed = when(row.get("created_at"))
        details = _loads(row.get("details"), {})
        details = details if isinstance(details, dict) else {"details": details}
        event_type = str(row.get("event_type") or "note")
        summary = _bid_event_summary(event_type, details)
        wanted = _BID_EVENT_ACTIVITY.get(event_type, set())
        if parsed is not None:
            for candidate in by_job.get(row["job_id"], []):
                if candidate["_used"] or candidate.get("action") not in wanted or candidate["_dt"] is None:
                    continue
                if abs((candidate["_dt"] - parsed).total_seconds()) <= _LEGACY_MATCH_SECONDS:
                    candidate["_used"] = True
                    summary = candidate.get("summary") or summary
                    break
        changes, rest = changes_from_detail(details)
        if event_type == "status_change" and (details.get("from") or details.get("to")):
            changes.append({"path": "/bid_status", "op": "replace",
                            "before": details.get("from"), "after": details.get("to")})
            rest = {key: value for key, value in (rest or {}).items() if key not in ("from", "to")} or None
        order += 1
        entries.append({
            **actor(row.get("username")), "ts": ts, "order": order,
            "action": f"bid.{event_type}", "entity_type": "job", "entity_id": str(row["job_id"]),
            "job_id": row["job_id"], "summary": summary,
            "changes": prepare_changes(changes, "job")[0],
            "extra": scrub({"legacy": {"table": "bid_events", "id": row["id"]}, **({"detail": rest} if rest else {})}),
        })

    for row in activity:
        if row["_used"]:
            continue
        detail = _loads(row.get("detail"), None)
        changes, rest = changes_from_detail(detail)
        extra = {"legacy": {"table": "job_activity", "id": row["id"]}, "activity_action": row.get("action")}
        if rest:
            extra["detail"] = rest
        order += 1
        entries.append({
            **actor(row.get("username") if "username" in activity_columns else None, row.get("user")),
            "ts": row["_ts"], "order": order,
            "action": legacy_action(row.get("action")), "entity_type": "job",
            "entity_id": str(row["job_id"]), "job_id": row["job_id"],
            "summary": row.get("summary") or "", "changes": prepare_changes(changes, "job")[0],
            "extra": scrub(_jsonable(extra)),
        })

    for row in conn.execute("SELECT * FROM admin_log ORDER BY id").fetchall():
        row = dict(row)
        ts, _ = when(row.get("created_at"))
        details = _loads(row.get("details"), {})
        details = details if isinstance(details, dict) else {"details": details}
        target = row.get("target_username") or ""
        target_user = users.get(target.lower()) if target else None
        name = (target_user or {}).get("display_name") or target or "someone"
        action_name, summary, changes = admin_log_entry(row.get("action"), target, details, name)
        order += 1
        entries.append({
            **actor(row.get("username")), "ts": ts, "order": order,
            "action": action_name, "entity_type": "user", "entity_id": target or None, "job_id": None,
            "summary": summary, "changes": prepare_changes(changes, "user")[0],
            "extra": scrub(_jsonable({"legacy": {"table": "admin_log", "id": row["id"]}, **({"detail": details} if details else {})})),
        })
    return entries


# ── Which routes are audited ──────────────────────────────────────────────────
AUDIT_POLICY_ATTR = "__audit_policy__"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def audit_route(*actions: str):
    """Mark a write route as audited: it writes audit entries with these actions
    (through job_write / entity_write / record)."""
    if not actions or not all(isinstance(action, str) and action for action in actions):
        raise ValueError("audit_route needs at least one action name, e.g. @audit_route('job.update')")

    def mark(endpoint):
        setattr(endpoint, AUDIT_POLICY_ATTR, {"kind": "audited", "actions": list(actions)})
        return endpoint

    return mark


def no_audit(reason: str):
    """Mark a write-method route that doesn't change stored data (or is
    deliberately not audited), with the reason."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("no_audit needs a reason, e.g. @no_audit('read-only search')")

    def mark(endpoint):
        setattr(endpoint, AUDIT_POLICY_ATTR, {"kind": "no_audit", "reason": reason.strip()})
        return endpoint

    return mark


def route_policy(endpoint) -> dict | None:
    return getattr(endpoint, AUDIT_POLICY_ATTR, None) if endpoint is not None else None


def list_route_policies(app) -> list[dict]:
    """Every write route (POST/PUT/PATCH/DELETE) and websocket, with its policy."""
    from starlette.routing import Route, WebSocketRoute

    rows = []
    for route in app.routes:
        if isinstance(route, WebSocketRoute):
            kind, methods = "websocket", ["WS"]
        elif isinstance(route, Route):
            methods = sorted(set(route.methods or ()) & WRITE_METHODS)
            if not methods:
                continue
            kind = "http"
        else:
            continue
        endpoint = getattr(route, "endpoint", None)
        rows.append({
            "kind": kind,
            "methods": methods,
            "path": route.path,
            "name": getattr(endpoint, "__name__", getattr(route, "name", "")),
            "policy": route_policy(endpoint),
        })
    return rows


# ── Backstop for routes that forgot to audit ──────────────────────────────────
# Fly apps that run strict unless AUDIT_STRICT says otherwise (Fly sets
# FLY_APP_NAME on every machine), so staging can't quietly lose the setting.
STRICT_BY_DEFAULT_APPS = frozenset({"si-bid-stg-20260714-c0fa"})


def _audit_strict() -> bool:
    value = os.environ.get("AUDIT_STRICT", "").strip().lower()
    if value:
        return value in ("1", "true", "yes", "on")
    return os.environ.get("FLY_APP_NAME", "").strip() in STRICT_BY_DEFAULT_APPS


def _record_unaudited_write(route: str, status: int, body_sha256: str, body_bytes: int) -> None:
    with write_transaction() as conn:
        record(
            conn,
            action="unaudited_write",
            entity_type="route",
            entity_id=route,
            summary=f"{route} changed data without writing a history entry",
            extra={"status": status, "body_sha256": body_sha256, "body_bytes": body_bytes},
        )


class AuditBackstopMiddleware:
    """Catch write requests that finished without touching the audit layer.

    A POST/PUT/PATCH/DELETE under /api/ that returns 2xx while the request's
    ``write_count`` (bumped by ``record``/``note_checked``) is still 0, on a
    route not marked ``@no_audit``, gets an "unaudited_write" audit entry
    (route, body hash) and an error in the log.

    With AUDIT_STRICT=1 the caller gets a 500 instead. How: the check runs
    when the handler sends "http.response.start". For ordinary FastAPI
    responses the handler has fully finished by then, so the count is final,
    and nothing has reached the client yet: the start message is swapped for
    a 500 and the original body is dropped. (The handler's data changes are
    already committed; strict mode makes the missing audit loud on staging.)
    Writes made after the response starts (streaming bodies, background
    tasks) can't be seen by this check.

    Must sit inside RequireLoginMiddleware, which sets up the audit context.
    """

    def __init__(self, app, strict: bool | None = None):
        self.app = app
        self.strict = strict

    async def __call__(self, scope, receive, send):
        path = scope.get("path") or ""
        if (
            scope.get("type") != "http"
            or scope.get("method") not in WRITE_METHODS
            or not path.startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        context = _request_context()
        if context is None:
            await self.app(scope, receive, send)
            return

        strict = _audit_strict() if self.strict is None else self.strict
        body_hash = hashlib.sha256()
        body_size = 0
        state = {"checked": False, "replacement": None}

        async def receive_and_hash():
            nonlocal body_size
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body") or b""
                body_hash.update(chunk)
                body_size += len(chunk)
            return message

        async def checked_send(message):
            if message["type"] == "http.response.start" and not state["checked"]:
                state["checked"] = True
                status = int(message.get("status") or 0)
                policy = route_policy(scope.get("endpoint"))
                exempt = policy is not None and policy.get("kind") == "no_audit"
                if 200 <= status < 300 and not int(context.get("write_count") or 0) and not exempt:
                    route = context["route"]() if callable(context.get("route")) else context.get("route")
                    route = route or f"{scope.get('method')} {path}"
                    print(
                        f"[audit] ERROR: {route} [{context.get('request_id')}] changed data without "
                        "writing a history entry. Give the route @audit_route(...) and write through "
                        "job_write/entity_write/record, or mark it @no_audit(reason)."
                    )
                    try:
                        await asyncio.to_thread(
                            _record_unaudited_write, route, status, body_hash.hexdigest(), body_size,
                        )
                    except Exception as err:
                        print(f"[audit] ERROR: couldn't record the unaudited write on {route}: {err}")
                    if strict:
                        body = json.dumps({
                            "detail": "This change was saved but not added to the history (AUDIT_STRICT). "
                                      "Tell the developers which button you pressed.",
                        }).encode("utf-8")
                        state["replacement"] = body
                        await send({
                            "type": "http.response.start",
                            "status": 500,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode("ascii")),
                            ],
                        })
                        return
            if state["replacement"] is not None:
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    await send({"type": "http.response.body", "body": state["replacement"]})
                return
            await send(message)

        await self.app(scope, receive_and_hash, checked_send)


# ── Reading ───────────────────────────────────────────────────────────────────
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
EXPORT_PAGE_SIZE = 500
EXPORT_MAX_ROWS = 100_000
EXPORT_COLUMNS = (
    "when_utc", "who", "co_editors", "action", "entity_type", "entity_id",
    "bid", "field", "summary", "changes_json", "source", "request_id",
)
FILTER_NAMES = ("job_id", "entity_type", "entity_id", "actor", "action", "since", "until", "q")


class AuditQueryError(ValueError):
    """A filter that can't be understood, with a plain-English reason."""


def _bound(text, *, end: bool) -> tuple[str, str]:
    text = str(text).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            day = date.fromisoformat(text)
        except ValueError:
            raise AuditQueryError(f"'{text}' isn't a real date.")
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        if end:
            return iso_ms(start + timedelta(days=1)), "<"
        return iso_ms(start), ">="
    parsed = parse_ts(text)
    if parsed is None:
        raise AuditQueryError(f"Couldn't read the date '{text}'. Use a date like 2026-09-24 or 2026-09-24T14:05:00Z.")
    return iso_ms(parsed), ("<=" if end else ">=")


def clean_filters(**raw) -> dict:
    """Validate query-string filters. job_id must already be a number (the
    route resolves slugs). Raises AuditQueryError."""
    filters: dict = {}
    for name in FILTER_NAMES:
        value = raw.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if name == "job_id":
            try:
                filters["job_id"] = int(value)
            except (TypeError, ValueError):
                raise AuditQueryError("job_id must be a bid number.")
        elif name == "since":
            filters["since"] = _bound(value, end=False)
        elif name == "until":
            filters["until"] = _bound(value, end=True)
        else:
            filters[name] = str(value).strip()[:500]
    return filters


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _where(filters: dict, before_id: int | None) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if "job_id" in filters:
        clauses.append("a.job_id = ?")
        params.append(filters["job_id"])
    if "entity_type" in filters:
        clauses.append("a.entity_type = ?")
        params.append(filters["entity_type"])
    if "entity_id" in filters:
        clauses.append("a.entity_id = ?")
        params.append(filters["entity_id"])
    if "actor" in filters:
        actor = filters["actor"]
        if actor.lower() == "system":
            clauses.append("a.actor_kind = 'system'")
        else:
            clauses.append(
                "(a.actor_username = ? COLLATE NOCASE OR a.id IN "
                "(SELECT audit_id FROM audit_log_actors WHERE username = ? COLLATE NOCASE))"
            )
            params += [actor, actor]
    if "action" in filters:
        options = [item.strip() for item in filters["action"].split(",") if item.strip()]
        if options:
            parts = []
            for option in options:
                # "bid" matches "bid" and "bid.sent", "bid.won", ...
                option = option.rstrip("*").rstrip(".")
                parts.append("(a.action = ? OR a.action LIKE ? ESCAPE '\\')")
                params += [option, _like(option)[1:-1] + ".%"]
            clauses.append("(" + " OR ".join(parts) + ")")
    if "since" in filters:
        value, op = filters["since"]
        clauses.append(f"a.ts {op} ?")
        params.append(value)
    if "until" in filters:
        value, op = filters["until"]
        clauses.append(f"a.ts_first {op} ?")
        params.append(value)
    if "q" in filters:
        like = _like(filters["q"])
        columns = ("a.summary", "a.field_path", "a.entity_id", "a.action", "a.actor_display",
                   "a.actor_username", "a.route", "a.changes", "a.extra", "j.project_name")
        clauses.append(
            "(" + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in columns) + " OR a.request_id = ?)"
        )
        params += [like] * len(columns) + [filters["q"]]
    if before_id is not None:
        clauses.append("a.id < ?")
        params.append(int(before_id))
    return (" AND ".join(clauses) or "1"), params


def _item(row, actors: list[dict] | None) -> dict:
    changes = _loads(row["changes"], [])
    extra = _loads(row["extra"], None)
    display = row["actor_display"] or row["actor_username"] or "System"
    if not actors:
        actors = [{"username": row["actor_username"], "display_name": display, "edit_count": row["edit_count"]}]
    return {
        "id": row["id"],
        "seq": row["seq"],
        "ts_first": row["ts_first"],
        "ts": row["ts"],
        "actor_username": row["actor_username"],
        "actor_display": display,
        "actor_kind": row["actor_kind"],
        "actors": actors,
        "source": row["source"],
        "request_id": row["request_id"],
        "route": row["route"],
        "action": row["action"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "job_id": row["job_id"],
        "job_name": row["job_name"],
        "field_path": row["field_path"],
        "summary": row["summary"],
        "changes": [
            {**change, "derived": bool(change.get("derived"))}
            for change in (changes if isinstance(changes, list) else [])
            if isinstance(change, dict)
        ],
        "edit_count": row["edit_count"],
        "group_open": bool(row["group_open"]),
        "net_noop": bool(row["net_noop"]),
        "extra": extra if isinstance(extra, dict) else None,
    }


def _actors_for(conn, ids: list[int]) -> dict[int, list[dict]]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    found: dict[int, list[dict]] = {}
    for row in conn.execute(
        f"""SELECT audit_id, username, display_name, edit_count FROM audit_log_actors
            WHERE audit_id IN ({placeholders}) ORDER BY audit_id, first_ts, rowid""",
        ids,
    ).fetchall():
        found.setdefault(row["audit_id"], []).append({
            "username": row["username"],
            "display_name": row["display_name"] or row["username"] or "System",
            "edit_count": row["edit_count"],
        })
    return found


def _page(conn, filters: dict, before_id: int | None, limit: int) -> dict:
    where, params = _where(filters, before_id)
    rows = conn.execute(
        f"""SELECT a.*, j.project_name AS job_name
            FROM audit_log a LEFT JOIN jobs j ON j.id = a.job_id
            WHERE {where}
            ORDER BY a.id DESC LIMIT ?""",
        params + [limit + 1],
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    actors = _actors_for(conn, [row["id"] for row in rows])
    items = [_item(row, actors.get(row["id"])) for row in rows]
    return {"items": items, "next_before_id": items[-1]["id"] if more and items else None}


def query_entries(filters: dict, *, before_id: int | None = None, limit: int | None = None) -> dict:
    """Newest first, keyset paged by id: {items, next_before_id}."""
    try:
        limit = int(limit if limit is not None else DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        limit = DEFAULT_PAGE_SIZE
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    conn = models._get_conn()
    try:
        return _page(conn, filters, before_id, limit)
    finally:
        conn.close()


def get_entry(audit_id: int) -> dict | None:
    conn = models._get_conn()
    try:
        row = conn.execute(
            """SELECT a.*, j.project_name AS job_name
               FROM audit_log a LEFT JOIN jobs j ON j.id = a.job_id WHERE a.id = ?""",
            (int(audit_id),),
        ).fetchone()
        if row is None:
            return None
        return _item(row, _actors_for(conn, [row["id"]]).get(row["id"]))
    finally:
        conn.close()


def _csv_cell(value) -> str:
    text = "" if value is None else str(value)
    # Spreadsheet apps run cells that start with these as formulas.
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def export_row(item: dict) -> list[str]:
    main = item.get("actor_username")
    co_editors = [
        actor.get("display_name") or actor.get("username") or ""
        for actor in item.get("actors") or []
        if (actor.get("username") or "").lower() != (main or "").lower()
    ]
    bid = item.get("job_name") or (f"#{item['job_id']}" if item.get("job_id") is not None else "")
    return [
        item.get("ts") or "",
        _csv_cell(item.get("actor_display") or "System"),
        _csv_cell("; ".join(name for name in co_editors if name)),
        _csv_cell(item.get("action")),
        _csv_cell(item.get("entity_type")),
        _csv_cell(item.get("entity_id")),
        _csv_cell(bid),
        _csv_cell(item.get("field_path")),
        _csv_cell(item.get("summary")),
        json.dumps(item.get("changes") or [], ensure_ascii=False, default=str),
        _csv_cell(item.get("source")),
        _csv_cell(item.get("request_id")),
    ]


def iter_export_csv(filters: dict):
    """CSV text in chunks (header first), newest first, up to EXPORT_MAX_ROWS."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    buffer.write("﻿")  # so Excel reads the file as UTF-8
    writer.writerow(EXPORT_COLUMNS)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    before_id = None
    sent = 0
    while sent < EXPORT_MAX_ROWS:
        conn = models._get_conn()
        try:
            page = _page(conn, filters, before_id, min(EXPORT_PAGE_SIZE, EXPORT_MAX_ROWS - sent))
        finally:
            conn.close()
        for item in page["items"]:
            writer.writerow(export_row(item))
        sent += len(page["items"])
        if page["items"]:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
        before_id = page["next_before_id"]
        if before_id is None:
            break
