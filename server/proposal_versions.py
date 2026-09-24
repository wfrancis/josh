"""
Proposal versions: saved copies of a bid's proposal that anyone can look at,
compare with the current proposal, name, and restore.

A version holds the whole proposal as it was (``proposal_data``), the job
fields the PDF prints next to it (header fields, exclusions, tax, GPM,
Textura: ``job_fields``) and the material lines it was priced from
(``materials_snapshot``). Blobs are zlib-compressed canonical JSON.

When a version is taken (``reason``):

- ``edit_burst``: someone edited the proposal or the job header and then
  stopped for 2 minutes, or has been editing for 30 minutes straight
  (``sweep_edit_bursts``, run by the audit sweeper after it closes idle
  history groups);
- ``generate``: right after the first proposal is generated;
- ``before_regenerate``: just before a regenerate recalculates the bid;
- ``pdf``: when a proposal PDF is made (the version and the PDF receipt
  point at each other);
- ``sent``: when the bid is marked sent and no proposal PDF was made (with
  a PDF, the sent event points at the version that PDF was printed from);
- ``before_restore`` / ``restore``: around a restore of an older version;
- ``rfms_upload``: before a takeoff re-upload changes the material lines;
- ``baseline``: once for every bid that already had a proposal when versions
  were added.

A new version is skipped when nothing in it differs from the bid's latest
version (same ``content_hash``); a PDF or a "sent" event then points at that
latest version instead. Versions are kept for good: the table refuses deletes,
and only a version's name (``label``) and its PDF link can change.

Nothing here opens its own write transaction except the sweeper and the
migration: callers pass ``tx.conn`` from their job_write.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import zlib
from datetime import datetime, timedelta

import audit
import models
import stable_ids
from models import JOB_ESTIMATE_HEADER_FIELDS

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS proposal_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        version_no INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT,
        created_by_user_id INTEGER,
        contributors TEXT NOT NULL DEFAULT '[]',
        reason TEXT NOT NULL,
        proposal_data BLOB,
        job_fields TEXT,
        materials_snapshot BLOB,
        materials_fingerprint TEXT,
        grand_total REAL,
        bundle_count INTEGER NOT NULL DEFAULT 0,
        content_hash TEXT NOT NULL,
        proposal_hash TEXT,
        sql_version INTEGER,
        proposal_rev INTEGER,
        artifact_id INTEGER,
        restored_from_version_id INTEGER,
        label TEXT,
        UNIQUE (job_id, version_no)
    );
    CREATE INDEX IF NOT EXISTS idx_proposal_versions_job_created
        ON proposal_versions(job_id, created_at);

    CREATE TRIGGER IF NOT EXISTS proposal_versions_no_delete
    BEFORE DELETE ON proposal_versions
    BEGIN
        SELECT RAISE(ABORT, 'proposal versions are kept for good: they cannot be deleted');
    END;

    CREATE TRIGGER IF NOT EXISTS proposal_versions_content_is_final
    BEFORE UPDATE ON proposal_versions
    WHEN NEW.id IS NOT OLD.id OR NEW.job_id IS NOT OLD.job_id
        OR NEW.version_no IS NOT OLD.version_no OR NEW.created_at IS NOT OLD.created_at
        OR NEW.created_by IS NOT OLD.created_by OR NEW.created_by_user_id IS NOT OLD.created_by_user_id
        OR NEW.contributors IS NOT OLD.contributors OR NEW.reason IS NOT OLD.reason
        OR NEW.proposal_data IS NOT OLD.proposal_data OR NEW.job_fields IS NOT OLD.job_fields
        OR NEW.materials_snapshot IS NOT OLD.materials_snapshot
        OR NEW.materials_fingerprint IS NOT OLD.materials_fingerprint
        OR NEW.grand_total IS NOT OLD.grand_total OR NEW.bundle_count IS NOT OLD.bundle_count
        OR NEW.content_hash IS NOT OLD.content_hash OR NEW.proposal_hash IS NOT OLD.proposal_hash
        OR NEW.sql_version IS NOT OLD.sql_version OR NEW.proposal_rev IS NOT OLD.proposal_rev
        OR NEW.restored_from_version_id IS NOT OLD.restored_from_version_id
    BEGIN
        SELECT RAISE(ABORT, 'a saved proposal version can only be renamed or linked to a PDF');
    END;
"""

REASONS = (
    "edit_burst", "generate", "before_regenerate", "pdf", "sent",
    "before_restore", "restore", "rfms_upload", "baseline",
)
MIGRATION_ACTOR = "system:migration"
LABEL_MAX_CHARS = 120

# Keys a PDF print adds to the saved proposal. They describe the print, not
# what the proposal says, so they are left out of content hashes and diffs
# (the job_fields hold the header fields the print used).
PRINT_META_KEYS = frozenset({
    "job_info", "pdf_totals", "pdf_audit_run_id", "pdf_ruleset_version",
    "pdf_source_fingerprint", "pdf_generated_at",
})
# Bookkeeping a restore does not bring back: which save, tab or audit run
# wrote the proposal, and the print details. The restore recomputes them.
RESTORE_DROPPED_KEYS = frozenset(audit.VOLATILE_KEYS) | PRINT_META_KEYS

# The job fields a proposal PDF prints (plus tax, GPM and Textura, which set
# its totals). "exclusions" is the job's own "excluded at this time" list.
JOB_FIELD_KEYS: tuple[str, ...] = (
    "project_name", "gc_name", "address", "city", "state", "zip", "salesperson",
    "unit_count", "tax_rate", "gpm_pct", "textura_fee", "quote_date",
    *JOB_ESTIMATE_HEADER_FIELDS,
)

# Material fields that decide pricing (same list as main._materials_source_fingerprint).
MATERIAL_FINGERPRINT_FIELDS: tuple[str, ...] = (
    "id", "item_code", "description", "material_type", "installed_qty", "unit",
    "waste_pct", "order_qty", "vendor", "unit_price", "extended_cost",
    "ai_confidence", "quote_status", "price_source", "quote_source_hash",
    "quote_file_name", "freight_per_unit", "freight_source", "fixture_count",
    "labor_rate_lf", "labor_catalog",
    "tack_strip_lf", "seam_tape_lf", "pad_sy", "area_type", "is_mosaic",
    "is_penny_hex", "crack_isolation_sf", "weld_rod_lf",
)
MATERIAL_SNAPSHOT_FIELDS: tuple[str, ...] = ("uid", *MATERIAL_FINGERPRINT_FIELDS)


class VersionNotFoundError(LookupError):
    """No such version for this bid."""


# ── Canonical JSON, hashes and blobs ─────────────────────────────────────────
def _plain_number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _content_value(value):
    """``value`` as it counts for "did the proposal change": volatile keys
    dropped at any depth, blank values (None, "", [], {}) dropped from dicts,
    whole floats as ints (browsers send 1000 for 1000.0)."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in audit.VOLATILE_KEYS:
                continue
            item = _content_value(item)
            if audit._blank(item):
                continue
            out[str(key)] = item
        return out
    if isinstance(value, (list, tuple)):
        return [_content_value(item) for item in value]
    return _plain_number(value)


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _pack(value) -> bytes:
    return zlib.compress(canonical_json(value).encode("utf-8"), 6)


def _unpack(blob, default=None):
    if blob in (None, b"", ""):
        return default
    try:
        raw = zlib.decompress(bytes(blob))
        return json.loads(raw.decode("utf-8"))
    except (zlib.error, ValueError, TypeError):
        return default


def _loads(raw, default=None):
    if raw in (None, ""):
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return default


def proposal_content(proposal) -> dict:
    """What the proposal says: print details and bookkeeping left out (what
    a comparison shows)."""
    if not isinstance(proposal, dict):
        return {}
    return _content_value({key: value for key, value in proposal.items() if key not in PRINT_META_KEYS})


# The top-level proposal keys that decide "is this the same proposal" (the
# same list main._proposal_source_fingerprint uses). Other keys are totals a
# writer may or may not copy (the PDF route drops "taxable", for one), so a
# PDF of an unchanged proposal still matches its version.
PROPOSAL_HASH_KEYS: tuple[str, ...] = (
    "bundles", "notes", "terms", "exclusions", "tax_rate", "gpm_pct", "textura_fee",
    "subtotal", "tax_amount", "grand_total", "gpm_profit", "gpm_labor", "gpm_material",
    "manual_adjustment", "textura_amount", "deleted_bundles", "deleted_bundle_reasons",
    "deleted_material_codes", "deleted_material_reasons",
)


def _hash_view(proposal) -> dict:
    if not isinstance(proposal, dict):
        return {}
    view = {key: proposal.get(key) for key in PROPOSAL_HASH_KEYS}
    # Which bundle is which (uids) isn't what the proposal says.
    view["bundles"] = stable_ids.without_identity(view.get("bundles") or [])
    return _content_value(view)


def proposal_hash(proposal) -> str:
    """Hash of the proposal's content alone (no job fields)."""
    return _sha256(_hash_view(proposal))


def content_hash(proposal, job_fields) -> str:
    """Hash of everything a version shows: the proposal and the job fields."""
    return _sha256({"proposal": _hash_view(proposal), "job_fields": _content_value(job_fields or {})})


def materials_fingerprint(materials) -> str:
    return _sha256([
        {field: _plain_number(row.get(field)) for field in MATERIAL_FINGERPRINT_FIELDS}
        for row in materials or [] if isinstance(row, dict)
    ])


def _money(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if number == number and abs(number) != float("inf") else None


# ── Reading a bid ─────────────────────────────────────────────────────────────
def job_fields_from_row(row: dict) -> dict:
    fields = {key: row.get(key) for key in JOB_FIELD_KEYS if key in row}
    exclusions = _loads(row.get("exclusions"), row.get("exclusions"))
    fields["exclusions"] = exclusions if exclusions not in (None, "") else []
    return fields


def _material_rows(conn, job_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM job_materials WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
    return [
        {field: row[field] for field in MATERIAL_SNAPSHOT_FIELDS if field in row.keys()}
        for row in rows
    ]


def current_materials_fingerprint(conn, job_id: int) -> str:
    return materials_fingerprint(_material_rows(conn, job_id))


def capture(conn, job_id: int) -> dict | None:
    """The bid's proposal, job fields and material lines right now, ready to
    store as a version; None when the bid has no proposal yet."""
    found = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
    if found is None:
        return None
    row = dict(found)
    proposal = _loads(row.get("proposal_data"))
    if not isinstance(proposal, dict) or not proposal:
        return None
    job_fields = job_fields_from_row(row)
    materials = _material_rows(conn, int(job_id))
    bundles = [bundle for bundle in proposal.get("bundles") or [] if isinstance(bundle, dict)]
    return {
        "job_id": int(job_id),
        "proposal": proposal,
        "job_fields": job_fields,
        "materials": materials,
        "materials_fingerprint": materials_fingerprint(materials),
        "content_hash": content_hash(proposal, job_fields),
        "proposal_hash": proposal_hash(proposal),
        "grand_total": _money(proposal.get("grand_total")),
        "bundle_count": len(bundles),
        "sql_version": int(row.get("version") or 0),
        "proposal_rev": int(row.get("proposal_rev") or 0),
    }


# ── Writing versions ──────────────────────────────────────────────────────────
def _ensure_write_transaction(conn) -> None:
    # version_no = MAX + 1 is only safe while holding the write lock.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def latest_version(conn, job_id: int) -> dict | None:
    found = conn.execute(
        """SELECT id, version_no, created_at, content_hash, materials_fingerprint, artifact_id
           FROM proposal_versions WHERE job_id = ? ORDER BY version_no DESC LIMIT 1""",
        (int(job_id),),
    ).fetchone()
    return dict(found) if found else None


def _actor_fields(created_by, created_by_user_id, contributors):
    if created_by is None:
        actor = audit.current_actor()
        created_by = actor["username"] or f"system:{actor['source']}"
        created_by_user_id = actor["user_id"]
        if contributors is None:
            contributors = [actor["username"]] if actor["username"] else []
    unique: list[str] = []
    seen: set[str] = set()
    for name in contributors or []:
        name = str(name or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            unique.append(name)
    return created_by, created_by_user_id, unique


def store(
    conn,
    captured: dict,
    reason: str,
    *,
    dedupe: bool = True,
    match_materials: bool = False,
    created_by: str | None = None,
    created_by_user_id: int | None = None,
    contributors: list[str] | None = None,
    artifact_id: int | None = None,
    restored_from_version_id: int | None = None,
    label: str | None = None,
) -> tuple[int, bool]:
    """Save ``captured`` (from ``capture``) as the bid's next version.

    Returns (version id, created). With ``dedupe`` (the default), when the
    bid's latest version has the same content (and, with ``match_materials``,
    the same material lines) nothing is saved and that version's id comes
    back with created=False. Runs in the caller's transaction; the caller
    commits. Who saved it defaults to the person making the request.
    """
    if reason not in REASONS:
        raise ValueError(f"Unknown proposal version reason: {reason!r}")
    _ensure_write_transaction(conn)
    job_id = int(captured["job_id"])
    latest = latest_version(conn, job_id)
    if dedupe and latest is not None and latest["content_hash"] == captured["content_hash"] and (
        not match_materials or latest["materials_fingerprint"] == captured["materials_fingerprint"]
    ):
        return int(latest["id"]), False
    created_by, created_by_user_id, contributors = _actor_fields(created_by, created_by_user_id, contributors)
    version_no = int((latest or {}).get("version_no") or 0) + 1
    cur = conn.execute(
        """INSERT INTO proposal_versions (
               job_id, version_no, created_at, created_by, created_by_user_id, contributors, reason,
               proposal_data, job_fields, materials_snapshot, materials_fingerprint, grand_total,
               bundle_count, content_hash, proposal_hash, sql_version, proposal_rev, artifact_id,
               restored_from_version_id, label)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id, version_no, audit.iso_ms(audit.utc_now()), created_by, created_by_user_id,
            json.dumps(contributors), reason,
            sqlite3.Binary(_pack(captured["proposal"])), canonical_json(captured["job_fields"]),
            sqlite3.Binary(_pack(captured["materials"])), captured["materials_fingerprint"],
            captured["grand_total"], captured["bundle_count"], captured["content_hash"],
            captured["proposal_hash"], captured["sql_version"], captured["proposal_rev"],
            artifact_id, restored_from_version_id, clean_label(label) if label else None,
        ),
    )
    return int(cur.lastrowid), True


def snapshot(conn, job_id: int, reason: str, **options) -> int | None:
    """Capture the bid now and save it as a version (see ``store``). Returns
    the version id (a new one, or the latest when nothing changed), or None
    when the bid has no proposal."""
    captured = capture(conn, job_id)
    if captured is None:
        return None
    version_id, _created = store(conn, captured, reason, **options)
    return version_id


def link_artifact(conn, version_id: int | None, artifact_id: int | None) -> None:
    """Point a version at the PDF printed from it (the newest print wins)."""
    if version_id is None or artifact_id is None:
        return
    conn.execute("UPDATE proposal_versions SET artifact_id = ? WHERE id = ?", (int(artifact_id), int(version_id)))


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def clean_label(label) -> str | None:
    """A version name as saved: trimmed, one line, at most 120 characters;
    None clears the name. ValueError when it's too long."""
    if label is None:
        return None
    text = " ".join(_CONTROL_CHARS.sub(" ", str(label)).split())
    if not text:
        return None
    if len(text) > LABEL_MAX_CHARS:
        raise ValueError(f"A version name can be at most {LABEL_MAX_CHARS} characters.")
    return text


def set_label(conn, job_id: int, version_id: int, label) -> None:
    cur = conn.execute(
        "UPDATE proposal_versions SET label = ? WHERE id = ? AND job_id = ?",
        (clean_label(label), int(version_id), int(job_id)),
    )
    if cur.rowcount == 0:
        raise VersionNotFoundError()


def label_loader(job_id: int):
    """An entity_write loader for one version's name."""
    def load(conn, version_id):
        found = conn.execute(
            "SELECT version_no, label FROM proposal_versions WHERE id = ? AND job_id = ?",
            (int(version_id), int(job_id)),
        ).fetchone()
        return {"version_no": found["version_no"], "label": found["label"]} if found else None
    return load


# ── Reading versions ──────────────────────────────────────────────────────────
_LIST_COLUMNS = (
    "v.id, v.job_id, v.version_no, v.created_at, v.created_by, v.created_by_user_id, v.contributors, "
    "v.reason, v.label, v.grand_total, v.bundle_count, v.artifact_id, v.restored_from_version_id, "
    "v.content_hash, v.proposal_hash, v.materials_fingerprint, v.sql_version, v.proposal_rev, "
    "u.display_name AS created_by_display"
)


def _person_name(username, display) -> str:
    username = str(username or "").strip()
    if username.startswith("system:"):
        return "System"
    return display or username


def _display_names(conn, usernames) -> dict[str, str]:
    names = [name for name in {str(name).lower() for name in usernames if name}]
    if not names:
        return {}
    rows = conn.execute(
        f"SELECT username, display_name FROM users WHERE LOWER(username) IN ({', '.join('?' for _ in names)})",
        names,
    ).fetchall()
    return {row["username"].lower(): row["display_name"] or row["username"] for row in rows}


def _sent_events(conn, job_id: int) -> dict[int, list[dict]]:
    """{version id: [the "sent" bid events that point at it]}, oldest first."""
    sent: dict[int, list[dict]] = {}
    rows = conn.execute(
        "SELECT id, created_at, details FROM bid_events WHERE job_id = ? AND event_type = 'sent' ORDER BY id",
        (int(job_id),),
    ).fetchall()
    for row in rows:
        details = _loads(row["details"], {}) or {}
        if not isinstance(details, dict):
            continue
        try:
            version_id = int(details.get("proposal_version_id"))
        except (TypeError, ValueError):
            continue
        pdf = details.get("pdf") if isinstance(details.get("pdf"), dict) else {}
        sent.setdefault(version_id, []).append({
            "event_id": row["id"],
            "sent_on": details.get("sent_on") or str(row["created_at"] or "")[:10] or None,
            "sent_to": details.get("sent_to") or details.get("gc_name") or None,
            "artifact_id": pdf.get("artifact_id"),
            "proposal_changed_since_pdf": bool(details.get("proposal_changed_since_pdf")),
        })
    return sent


def _item(row, names: dict[str, str], current_hash: str | None, sent: dict[int, list[dict]] | None = None) -> dict:
    contributors = _loads(row["contributors"], []) or []
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "version_no": row["version_no"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "created_by_name": _person_name(row["created_by"], row["created_by_display"]),
        "contributors": contributors,
        "contributor_names": [names.get(str(name).lower(), name) for name in contributors],
        "reason": row["reason"],
        "label": row["label"],
        "grand_total": row["grand_total"],
        "bundle_count": row["bundle_count"],
        "artifact_id": row["artifact_id"],
        "restored_from_version_id": row["restored_from_version_id"],
        "matches_current": current_hash is not None and row["content_hash"] == current_hash,
        # "Sent" bid events that point at this version (what went to the GC).
        "sent": (sent or {}).get(int(row["id"]), []),
    }


def _current_hash(conn, job_id: int) -> str | None:
    captured = capture(conn, job_id)
    return captured["content_hash"] if captured else None


def list_versions(job_id: int) -> list[dict]:
    """A bid's versions, newest first."""
    conn = models._get_conn()
    try:
        rows = conn.execute(
            f"""SELECT {_LIST_COLUMNS} FROM proposal_versions v
                LEFT JOIN users u ON u.username = v.created_by
                WHERE v.job_id = ? ORDER BY v.version_no DESC""",
            (int(job_id),),
        ).fetchall()
        names = _display_names(conn, [name for row in rows for name in _loads(row["contributors"], []) or []])
        current = _current_hash(conn, job_id)
        sent = _sent_events(conn, job_id)
        return [_item(row, names, current, sent) for row in rows]
    finally:
        conn.close()


def _version_row(conn, job_id: int, version_id: int, *, full: bool = False):
    extra = ", v.proposal_data, v.job_fields, v.materials_snapshot" if full else ""
    found = conn.execute(
        f"""SELECT {_LIST_COLUMNS}{extra} FROM proposal_versions v
            LEFT JOIN users u ON u.username = v.created_by
            WHERE v.job_id = ? AND v.id = ?""",
        (int(job_id), int(version_id)),
    ).fetchone()
    if found is None:
        raise VersionNotFoundError()
    return found


def get_item(job_id: int, version_id: int, conn=None) -> dict:
    """One version's list entry (no proposal)."""
    own = conn is None
    conn = conn or models._get_conn()
    try:
        row = _version_row(conn, job_id, version_id)
        names = _display_names(conn, _loads(row["contributors"], []) or [])
        return _item(row, names, _current_hash(conn, job_id), _sent_events(conn, job_id))
    finally:
        if own:
            conn.close()


def get_version(job_id: int, version_id: int, *, include_materials: bool = False) -> dict:
    """One version with its proposal_data and job_fields (and material lines
    when asked), plus whether the bid's material lines changed since."""
    conn = models._get_conn()
    try:
        row = _version_row(conn, job_id, version_id, full=True)
        names = _display_names(conn, _loads(row["contributors"], []) or [])
        captured = capture(conn, job_id)
        item = _item(row, names, captured["content_hash"] if captured else None, _sent_events(conn, job_id))
        item["proposal_data"] = _unpack(row["proposal_data"], {})
        item["job_fields"] = _loads(row["job_fields"], {}) or {}
        current_materials = (
            captured["materials_fingerprint"] if captured else current_materials_fingerprint(conn, job_id)
        )
        item["materials_changed_since"] = bool(row["materials_fingerprint"]) and row["materials_fingerprint"] != current_materials
        if include_materials:
            item["materials"] = _unpack(row["materials_snapshot"], [])
        return item
    finally:
        conn.close()


def version_state(job_id: int, version_id: int) -> dict:
    """{proposal, job_fields, materials_fingerprint, version} of one version."""
    conn = models._get_conn()
    try:
        row = _version_row(conn, job_id, version_id, full=True)
        return {
            "proposal": _unpack(row["proposal_data"], {}) or {},
            "job_fields": _loads(row["job_fields"], {}) or {},
            "materials_fingerprint": row["materials_fingerprint"],
            "version": {"id": row["id"], "version_no": row["version_no"], "label": row["label"],
                        "reason": row["reason"], "created_at": row["created_at"]},
        }
    finally:
        conn.close()


def current_state(job_id: int) -> dict:
    """{proposal, job_fields, materials_fingerprint} of the bid right now."""
    conn = models._get_conn()
    try:
        captured = capture(conn, job_id)
        if captured is not None:
            return {"proposal": captured["proposal"], "job_fields": captured["job_fields"],
                    "materials_fingerprint": captured["materials_fingerprint"]}
        found = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
        return {
            "proposal": {},
            "job_fields": job_fields_from_row(dict(found)) if found else {},
            "materials_fingerprint": current_materials_fingerprint(conn, job_id),
        }
    finally:
        conn.close()


# ── Comparing ─────────────────────────────────────────────────────────────────
MAX_DIFF_CHANGES = 2000


def _diff_doc(state: dict) -> dict:
    return {
        "proposal": proposal_content(state.get("proposal")),
        "job_fields": _content_value(state.get("job_fields") or {}),
    }


def _bundle_row_lists(doc: dict) -> list[tuple[str, list]]:
    """(name, rows) of every list of rows inside the doc's bundles
    (materials, sundry_items, labor_items, ...)."""
    found = []
    for bundle in (doc.get("proposal") or {}).get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        for key, value in bundle.items():
            if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
                found.append((key, value))
    return found


def _align_bundle_row_ids(before_doc: dict, after_doc: dict) -> None:
    """Rows inside a bundle only got uids and line keys with stable ids, so
    an older version's rows may have none. They say which row is which, not
    what the proposal says: rows are lined up by them only when every such
    row on both sides has one, and they (and row bookkeeping) never show as
    changes. The bundles' own uids stay, so bundles still match up."""
    lists = _bundle_row_lists(before_doc) + _bundle_row_lists(after_doc)
    keep: dict[str, set[str]] = {}
    for name, rows in lists:
        present = {key for key in stable_ids.IDENTITY_KEYS if all(not audit._blank(row.get(key)) for row in rows)}
        keep[name] = keep[name] & present if name in keep else present
    for name, rows in lists:
        for index, row in enumerate(rows):
            rows[index] = {
                key: value for key, value in row.items()
                if key not in stable_ids.ROW_META_COLUMNS
                and (key not in stable_ids.IDENTITY_KEYS or key in keep[name])
            }


def diff_states(before: dict, after: dict) -> dict:
    """{changes, summary} from ``before`` to ``after`` (states from
    version_state / current_state). Changes are audit-style
    ({path, op, before, after, derived}) under /proposal/... and
    /job_fields/...; bundles are matched by uid."""
    before_doc, after_doc = _diff_doc(before), _diff_doc(after)
    _align_bundle_row_ids(before_doc, after_doc)
    changes = audit.diff(before_doc, after_doc, entity_type="job")
    added: set[str] = set()
    removed: set[str] = set()
    touched: set[str] = set()
    order_changed = False
    for change in changes:
        parts = audit.split_path(change.get("path"))
        if len(parts) < 3 or parts[:2] != ["proposal", "bundles"]:
            continue
        key = parts[2]
        if key == "_order":
            order_changed = True
        elif len(parts) == 3 and change.get("op") == "add":
            added.add(key)
        elif len(parts) == 3 and change.get("op") == "remove":
            removed.add(key)
        else:
            touched.add(key)
    before_proposal = before.get("proposal") or {}
    after_proposal = after.get("proposal") or {}
    summary = {
        "bundles_added": len(added),
        "bundles_removed": len(removed),
        "bundles_changed": len(touched - added - removed),
        "bundle_order_changed": order_changed,
        "grand_total_before": _money(before_proposal.get("grand_total")),
        "grand_total_after": _money(after_proposal.get("grand_total")),
        "job_fields_changed": sorted({
            audit.split_path(change["path"])[1] for change in changes
            if audit.split_path(change.get("path"))[:1] == ["job_fields"] and len(audit.split_path(change["path"])) > 1
        }),
        "materials_changed": bool(before.get("materials_fingerprint")) and bool(after.get("materials_fingerprint"))
        and before.get("materials_fingerprint") != after.get("materials_fingerprint"),
        "change_count": len(changes),
    }
    truncated = len(changes) > MAX_DIFF_CHANGES
    return {"changes": changes[:MAX_DIFF_CHANGES], "summary": summary, "truncated": truncated}


# ── Restoring ─────────────────────────────────────────────────────────────────
def restorable_proposal(version_proposal: dict, current_proposal: dict | None) -> dict:
    """The version's proposal as it goes back in: print details and save
    bookkeeping dropped (the restore recomputes them), bundles keep their
    uids (one missing takes the matching current bundle's uid, else a new one)."""
    restored = {
        key: json.loads(canonical_json(value))
        for key, value in (version_proposal or {}).items()
        if key not in RESTORE_DROPPED_KEYS
    }
    bundles = restored.get("bundles")
    if isinstance(bundles, list):
        stable_ids.carry_bundle_uids((current_proposal or {}).get("bundles"), bundles)
    return restored


# ── Edit bursts (run by the audit sweeper) ────────────────────────────────────
# History actions that change what a version shows: proposal edits and the
# job header (tax, GPM, Textura, header fields, exclusions).
BURST_ACTIONS: tuple[str, ...] = ("proposal.save", "job.update", "job.exclusions.update")
BURST_QUIET_SECONDS = 120
BURST_MAX_SECONDS = 30 * 60
# How far back the sweeper looks for edits nobody has saved a version of
# (covers a machine that stopped mid-edit and started again later).
BURST_LOOKBACK = timedelta(days=7)
SWEEPER_ACTOR = "system:proposal_versions"

# job id -> newest edit time already handled (content matched the latest
# version), so an unchanged bid isn't re-read every sweep.
_burst_checked: dict[int, str] = {}
_burst_lock = threading.Lock()


def _burst_candidates(conn, now: datetime) -> list[dict]:
    placeholders = ", ".join("?" for _ in BURST_ACTIONS)
    rows = conn.execute(
        f"""SELECT a.job_id AS job_id, MIN(a.ts_first) AS first_edit, MAX(a.ts) AS last_edit,
                   (SELECT MAX(v.created_at) FROM proposal_versions v WHERE v.job_id = a.job_id) AS last_version
            FROM audit_log a
            WHERE a.ts >= ? AND a.job_id IS NOT NULL AND a.action IN ({placeholders})
              AND a.ts > COALESCE((SELECT MAX(v.created_at) FROM proposal_versions v WHERE v.job_id = a.job_id), '')
            GROUP BY a.job_id""",
        (audit.iso_ms(now - BURST_LOOKBACK), *BURST_ACTIONS),
    ).fetchall()
    return [dict(row) for row in rows]


def _burst_is_due(candidate: dict, now: datetime) -> bool:
    last_edit = audit.parse_ts(candidate["last_edit"])
    if last_edit is None:
        return False
    if (now - last_edit).total_seconds() >= BURST_QUIET_SECONDS:
        return True
    starts = [audit.parse_ts(candidate["first_edit"]), audit.parse_ts(candidate.get("last_version"))]
    started = max((when for when in starts if when is not None), default=None)
    return started is not None and (now - started).total_seconds() >= BURST_MAX_SECONDS


def burst_editors(conn, job_id: int, since: str | None) -> tuple[list[dict], dict | None]:
    """Everyone who edited the proposal or job header after ``since`` (in the
    order they started), and the one who edited last."""
    placeholders = ", ".join("?" for _ in BURST_ACTIONS)
    rows = conn.execute(
        f"""SELECT id, actor_username, actor_user_id, ts_first, ts FROM audit_log
            WHERE job_id = ? AND action IN ({placeholders}) AND ts > ?
            ORDER BY ts_first, id""",
        (int(job_id), *BURST_ACTIONS, since or ""),
    ).fetchall()
    people: dict[str, dict] = {}

    def note(username, user_id, first, last):
        if not username:
            return
        key = str(username).lower()
        person = people.setdefault(key, {"username": username, "user_id": user_id, "first": first, "last": last})
        person["first"] = min(person["first"], first)
        person["last"] = max(person["last"], last)
        if person["user_id"] is None:
            person["user_id"] = user_id

    ids = [row["id"] for row in rows]
    for row in rows:
        note(row["actor_username"], row["actor_user_id"], row["ts_first"], row["ts"])
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        for actor in conn.execute(
            f"""SELECT username, user_id, first_ts, last_ts FROM audit_log_actors
                WHERE audit_id IN ({', '.join('?' for _ in chunk)})""",
            chunk,
        ).fetchall():
            note(actor["username"], actor["user_id"], actor["first_ts"], actor["last_ts"])
    ordered = sorted(people.values(), key=lambda person: person["first"])
    last = max(people.values(), key=lambda person: person["last"]) if people else None
    return ordered, last


def snapshot_edit_burst(job_id: int) -> int | None:
    """Save an 'edit_burst' version of one bid now (its own transaction).
    Returns the new version id, or None when nothing differed from the latest."""
    conn = models._get_conn()
    committed = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        captured = capture(conn, job_id)
        if captured is None:
            conn.rollback()
            committed = True
            return None
        latest = latest_version(conn, job_id)
        editors, last = burst_editors(conn, job_id, (latest or {}).get("created_at"))
        version_id, created = store(
            conn, captured, "edit_burst",
            created_by=(last or {}).get("username") or SWEEPER_ACTOR,
            created_by_user_id=(last or {}).get("user_id"),
            contributors=[person["username"] for person in editors],
        )
        conn.commit()
        committed = True
        return version_id if created else None
    except BaseException:
        if not committed:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        raise
    finally:
        conn.close()


def sweep_edit_bursts(now: datetime | None = None) -> list[int]:
    """Save an 'edit_burst' version of every bid whose proposal or header
    editing went quiet (2 minutes) or has run 30 minutes since its last
    version. Returns the new version ids. Safe to run often: a bid whose
    content matches its latest version is only re-checked after new edits."""
    now = now or audit.utc_now()
    conn = models._get_conn()
    try:
        candidates = _burst_candidates(conn, now)
    finally:
        conn.close()
    created: list[int] = []
    for candidate in candidates:
        job_id = int(candidate["job_id"])
        with _burst_lock:
            if _burst_checked.get(job_id) == candidate["last_edit"]:
                continue
        if not _burst_is_due(candidate, now):
            continue
        version_id = snapshot_edit_burst(job_id)
        if version_id is not None:
            created.append(version_id)
        with _burst_lock:
            _burst_checked[job_id] = candidate["last_edit"]
            if len(_burst_checked) > 5000:
                _burst_checked.pop(next(iter(_burst_checked)))
    return created


def reset_burst_memory() -> None:
    """Forget which bids were already checked (tests)."""
    with _burst_lock:
        _burst_checked.clear()


def register_sweeper() -> None:
    """Run sweep_edit_bursts after every audit idle-group sweep."""
    audit.register_sweep_hook(sweep_edit_bursts)


# ── Setup ─────────────────────────────────────────────────────────────────────
def init_versions(conn) -> int:
    """Create the table (safe every start) and give every bid that has a
    proposal but no versions its 'baseline' version. Returns how many."""
    conn.executescript(SCHEMA_SQL)
    rows = conn.execute(
        """SELECT j.id FROM jobs j
           WHERE j.proposal_data IS NOT NULL AND TRIM(j.proposal_data) NOT IN ('', 'null', '{}')
             AND NOT EXISTS (SELECT 1 FROM proposal_versions v WHERE v.job_id = j.id)
           ORDER BY j.id"""
    ).fetchall()
    if not rows:
        return 0
    count = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            job_id = int(row["id"])
            if latest_version(conn, job_id) is not None:
                continue
            captured = capture(conn, job_id)
            if captured is None:
                continue
            store(conn, captured, "baseline", dedupe=False, created_by=MIGRATION_ACTOR, contributors=[])
            count += 1
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    if count:
        print(f"[proposal_versions] Saved an original version of {count} existing proposal(s)")
    return count
