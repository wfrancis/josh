"""
Every change to a bid goes through ``job_write``; changes to anything else
(vendors, price lists, settings, people, ...) go through ``entity_write``.

    with job_write(job_id, action="job.update", summary="Changed the city") as tx:
        update_job_fields(tx.conn, tx.job_id, {"city": "Austin"})

``job_write``:

1. refuses to run on the event loop (it blocks: call it from a ``def``
   route or through ``run_in_threadpool``);
2. takes the bid's lock, so two saves of the same bid never interleave;
3. opens one connection and takes the database write lock (BEGIN IMMEDIATE);
4. snapshots the bid before and after the block (only the listed ``scopes``)
   and diffs the two;
5. if anything changed: bumps ``jobs.version``, sets ``updated_at`` /
   ``updated_by`` and writes one audit entry (grouped when ``group`` is given);
6. commits, then runs the after-commit hooks (live updates) while still
   holding the bid's lock, then lets go.

An error inside the block rolls everything back, the audit entry included.
Don't nest job_write / entity_write, and don't open other connections that
write inside the block: use ``tx.conn`` (``log_activity`` already does).
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

import audit
import models
from models import BID_TRACKING_COLUMNS, JOB_ESTIMATE_HEADER_FIELDS

# How long a save waits for another save of the same bid before giving up.
LOCK_WAIT_SECONDS = 60


# ── Errors (main.py turns these into HTTP responses) ─────────────────────────
class JobWriteError(Exception):
    status_code = 400
    default_message = "That change couldn't be saved."

    def __init__(self, message: str | None = None, **info):
        self.message = message or self.default_message
        self.info = info
        super().__init__(self.message)


class JobNotFoundError(JobWriteError, LookupError):
    status_code = 404
    default_message = "Job not found"


class JobDeletedError(JobWriteError):
    status_code = 410
    default_message = "This bid was deleted, so it can't be changed. An admin can restore it."


class VersionConflictError(JobWriteError):
    status_code = 409
    default_message = "Someone else changed this bid while you were editing. Reload to see their changes."


class ProposalConflictError(JobWriteError):
    status_code = 409
    default_message = "Someone else saved this proposal while you were editing. Reload to see their changes."


class JobBusyError(JobWriteError):
    status_code = 503
    default_message = "This bid is busy saving another change. Try again in a moment."


# ── Locks ─────────────────────────────────────────────────────────────────────
_job_locks: dict[int, threading.Lock] = {}
_entity_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def job_lock(job_id) -> threading.Lock:
    """The lock for one bid (the same Lock object every time)."""
    with _locks_guard:
        return _job_locks.setdefault(int(job_id), threading.Lock())


def _entity_lock(entity_type: str) -> threading.Lock:
    with _locks_guard:
        return _entity_locks.setdefault(str(entity_type), threading.Lock())


def _assert_off_event_loop(name: str) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # a worker thread (or no event loop at all): fine
    raise RuntimeError(
        f"{name} blocks and must not run on the event loop. Make the route a plain `def`, "
        "or call it through run_in_threadpool."
    )


def _assert_not_nested(name: str) -> None:
    if audit.active_write() is not None:
        raise RuntimeError(
            f"{name} can't run inside another job_write/entity_write on the same thread "
            "(it would wait forever for the database write lock). Use tx.conn instead."
        )


def _acquire(lock: threading.Lock) -> None:
    if not lock.acquire(timeout=LOCK_WAIT_SECONDS):
        raise JobBusyError()


# ── Snapshots ─────────────────────────────────────────────────────────────────
# What a job_write compares before and after. "job" is the header fields,
# "tracking" the bid tracker fields; the rest are the named parts of a bid.
ALL_SCOPES = ("job", "tracking", "exclusions", "materials", "sundries", "labor", "bundles", "proposal", "bid")
# Bookkeeping columns: never diffed.
_JOB_META_COLUMNS = frozenset({"id", "created_at", "version", "updated_at", "updated_by", "proposal_rev"})
# Columns covered by their own scope.
_JOB_SCOPED_COLUMNS = frozenset({"proposal_data", "bid_data", "exclusions", *BID_TRACKING_COLUMNS})


def _loads_or_text(raw):
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _rows(conn, sql: str, job_id: int, drop: tuple[str, ...]) -> list[dict]:
    return [
        {key: value for key, value in dict(row).items() if key not in drop}
        for row in conn.execute(sql, (job_id,)).fetchall()
    ]


def _check_scopes(scopes) -> tuple[str, ...]:
    scopes = tuple(scopes)
    unknown = set(scopes) - set(ALL_SCOPES)
    if unknown:
        raise ValueError(f"Unknown job_write scope(s): {', '.join(sorted(unknown))}")
    return scopes


def snapshot_job(conn, job_id: int, scopes=ALL_SCOPES, *, row: dict | None = None) -> dict | None:
    """The parts of a bid named in ``scopes`` as one dict, shaped for audit
    paths: header fields at the top ("/notes"), materials keyed by id
    ("/materials/12/unit_price"), the proposal under "/proposal"."""
    scopes = _check_scopes(scopes)
    if row is None:
        found = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if found is None:
            return None
        row = dict(found)
    snapshot: dict = {}
    if "job" in scopes:
        for key, value in row.items():
            if key not in _JOB_META_COLUMNS and key not in _JOB_SCOPED_COLUMNS:
                snapshot[key] = value
    if "tracking" in scopes:
        for column in BID_TRACKING_COLUMNS:
            snapshot[column] = row.get(column)
    if "exclusions" in scopes:
        snapshot["exclusions"] = _loads_or_text(row.get("exclusions"))
    if "materials" in scopes:
        snapshot["materials"] = _rows(
            conn, "SELECT * FROM job_materials WHERE job_id = ? ORDER BY id", job_id, ("job_id",),
        )
    # Sundry, labor and bundle rows are deleted and re-inserted on every
    # save, so their ids mean nothing; rows are matched by content instead.
    if "sundries" in scopes:
        snapshot["sundries"] = _rows(
            conn, "SELECT * FROM job_sundries WHERE job_id = ? ORDER BY id", job_id, ("job_id", "id"),
        )
    if "labor" in scopes:
        snapshot["labor"] = _rows(
            conn, "SELECT * FROM job_labor WHERE job_id = ? ORDER BY id", job_id, ("job_id", "id"),
        )
    if "bundles" in scopes:
        snapshot["bundles"] = _rows(
            conn, "SELECT * FROM job_bundles WHERE job_id = ? ORDER BY id", job_id, ("job_id", "id"),
        )
    if "proposal" in scopes:
        snapshot["proposal"] = _loads_or_text(row.get("proposal_data"))
    if "bid" in scopes:
        snapshot["bid"] = _loads_or_text(row.get("bid_data"))
    return snapshot


def resolve_job_ref(job_ref, conn=None) -> int | None:
    """A job's numeric id from an id or slug (deleted-but-kept bids included), or None."""
    if job_ref is None:
        return None
    if isinstance(job_ref, int) or (isinstance(job_ref, str) and job_ref.strip().isdigit()):
        job_id = int(job_ref)
        sql, params = "SELECT id FROM jobs WHERE id = ?", (job_id,)
    else:
        sql, params = "SELECT id FROM jobs WHERE slug = ?", (str(job_ref).strip(),)
    own = conn is None
    conn = conn or models._get_conn()
    try:
        found = conn.execute(sql, params).fetchone()
        return int(found[0]) if found else None
    finally:
        if own:
            conn.close()


# ── Write transactions ────────────────────────────────────────────────────────
class _WriteTx:
    """What the block of a job_write / entity_write can use and set."""

    def __init__(self, conn, *, action: str, summary: str | None, field_path: str | None, extra: dict | None):
        self.conn = conn
        self.action = action
        self.summary = summary
        self.field_path = field_path
        self.extra: dict = dict(extra or {})
        self.changes: list[dict] = []
        self.audit_id: int | None = None
        self.changed = False
        self._extra_changes: list[dict] = []
        self._force = False
        self._hooks: list = []

    def set_summary(self, summary: str) -> None:
        self.summary = summary

    def add_changes(self, changes) -> None:
        """Changes the snapshots can't see (e.g. uploaded files, quotes)."""
        self._extra_changes.extend(dict(change) for change in changes or [])

    def force_record(self) -> None:
        """Write the audit entry even if nothing in the snapshots changed
        (an event such as "PDF generated")."""
        self._force = True

    def after_commit(self, hook) -> None:
        """Run ``hook()`` after the commit, while the lock is still held."""
        self._hooks.append(hook)

    def note_activity(self, action: str, summary: str, detail=None) -> None:
        # Called by log_activity inside this block: its text becomes the summary.
        if not self.summary and summary:
            self.summary = summary
        notes = self.extra.setdefault("activity", [])
        if len(notes) < 20:
            notes.append({"action": action, "summary": summary})

    def _run_hooks(self) -> None:
        for hook in self._hooks:
            try:
                hook()
            except Exception as err:
                print(f"[job_write] After-save step failed: {err}")


class JobWriteTx(_WriteTx):
    def __init__(self, conn, job_id: int, row: dict, before: dict, **kwargs):
        super().__init__(conn, **kwargs)
        self.job_id = job_id
        self.row = row            # the jobs row before the change
        self.before = before      # snapshot before the change
        self.version = int(row.get("version") or 0)
        self.new_version = self.version


class EntityWriteTx(_WriteTx):
    def __init__(self, conn, entity_type: str, entity_id, before, job_id=None, **kwargs):
        super().__init__(conn, **kwargs)
        self.entity_type = entity_type
        self.entity_id = entity_id  # set this inside the block when creating
        self.job_id = job_id
        self.before = before


def _rollback(conn) -> None:
    try:
        conn.rollback()
    except sqlite3.Error:
        pass
    audit.discard_pending(conn)


def _changes_with_flags(changes: list[dict], entity_type: str) -> list[dict]:
    flagged = []
    for change in changes:
        change = dict(change)
        change.setdefault("derived", audit.is_derived_path(str(change.get("path") or ""), entity_type))
        flagged.append(change)
    return flagged


@contextmanager
def job_write(
    job_id,
    *,
    action: str,
    summary: str | None = None,
    scopes=ALL_SCOPES,
    group: audit.GroupPolicy | None = None,
    expected_version: int | None = None,
    allow_deleted: bool = False,
    field_path: str | None = None,
    extra: dict | None = None,
):
    """Change one bid under its lock, with version bump and audit entry.

    ``job_id`` is the numeric id or slug. ``expected_version``: refuse with
    VersionConflictError (409) if the bid's version moved. ``field_path``
    (e.g. "/notes") names the field for grouping; by default it's the
    common path of the changed (non-derived) fields.
    """
    _assert_off_event_loop("job_write")
    _assert_not_nested("job_write")
    scopes = _check_scopes(scopes)
    db_id = resolve_job_ref(job_id)
    if db_id is None:
        raise JobNotFoundError()
    lock = job_lock(db_id)
    _acquire(lock)
    try:
        conn = models._get_conn()
        committed = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            found = conn.execute("SELECT * FROM jobs WHERE id = ?", (db_id,)).fetchone()
            if found is None:
                raise JobNotFoundError()
            row = dict(found)
            if row.get("deleted_at") and not allow_deleted:
                raise JobDeletedError()
            version = int(row.get("version") or 0)
            if expected_version is not None and int(expected_version) != version:
                raise VersionConflictError(current_version=version)
            before = snapshot_job(conn, db_id, scopes, row=row)
            tx = JobWriteTx(conn, db_id, row, before, action=action, summary=summary,
                            field_path=field_path, extra=extra)
            audit.push_active_write(tx)
            try:
                yield tx
            finally:
                audit.pop_active_write(tx)
            _finish_job_write(tx, scopes, group)
            conn.commit()
            committed = True
            audit.after_commit(conn)
            tx._run_hooks()
        except BaseException:
            if not committed:
                _rollback(conn)
            raise
        finally:
            conn.close()
    finally:
        lock.release()


def _finish_job_write(tx: JobWriteTx, scopes, group) -> None:
    after = snapshot_job(tx.conn, tx.job_id, scopes)
    if after is None:
        # The block deleted the bid; record what it held.
        after = {}
    changes = audit.diff(tx.before, after, entity_type="job") + _changes_with_flags(tx._extra_changes, "job")
    tx.changes = changes
    if changes:
        tx.conn.execute(
            "UPDATE jobs SET version = COALESCE(version, 0) + 1, updated_at = ?, updated_by = ? WHERE id = ?",
            (audit.iso_ms(audit.utc_now()), audit.actor_label(), tx.job_id),
        )
        tx.new_version = tx.version + 1
        tx.changed = True
    if not changes and not tx._force:
        audit.note_checked(tx.job_id)
        return
    edited = [change["path"] for change in changes if not change.get("derived")]
    field_path = tx.field_path or audit.common_path(edited or [change["path"] for change in changes])
    tx.audit_id = audit.record(
        tx.conn,
        action=tx.action,
        entity_type="job",
        entity_id=tx.job_id,
        job_id=tx.job_id,
        summary=tx.summary or audit.describe_changes(changes, "bid"),
        changes=changes,
        field_path=field_path,
        group=group,
        extra=tx.extra or None,
    )


@contextmanager
def entity_write(
    entity_type: str,
    entity_id,
    loader,
    action: str,
    group: audit.GroupPolicy | None = None,
    *,
    summary: str | None = None,
    job_id=None,
    field_path: str | None = None,
    extra: dict | None = None,
):
    """Change something that isn't a bid (vendor, price list row, setting,
    person, ...) under a per-type lock, with an audit entry.

    ``loader(conn, entity_id)`` returns the entity as a dict (None if it
    doesn't exist); it runs before and after the block. When creating, pass
    ``entity_id=None`` and set ``tx.entity_id`` inside the block.
    """
    _assert_off_event_loop("entity_write")
    _assert_not_nested("entity_write")
    lock = _entity_lock(entity_type)
    _acquire(lock)
    try:
        conn = models._get_conn()
        committed = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            before = loader(conn, entity_id) if entity_id is not None else None
            tx = EntityWriteTx(conn, entity_type, entity_id, before, job_id=job_id, action=action,
                               summary=summary, field_path=field_path, extra=extra)
            audit.push_active_write(tx)
            try:
                yield tx
            finally:
                audit.pop_active_write(tx)
            after = loader(conn, tx.entity_id) if tx.entity_id is not None else None
            changes = audit.diff(before, after, tx.field_path or "", entity_type=entity_type)
            changes += _changes_with_flags(tx._extra_changes, entity_type)
            tx.changes = changes
            tx.changed = bool(changes)
            if changes or tx._force:
                if before is None and after is not None:
                    default_summary = f"Added {entity_type.replace('_', ' ')}"
                elif after is None and before is not None:
                    default_summary = f"Deleted {entity_type.replace('_', ' ')}"
                else:
                    default_summary = audit.describe_changes(changes, entity_type.replace("_", " "))
                # Like job_write: the field edited (common path of the edited
                # changes), so quick re-saves only group with edits to the
                # same field. Adding or deleting the whole thing names no field.
                field_path = tx.field_path
                if field_path is None and before is not None and after is not None and changes:
                    field_path = audit.common_path(audit.edited_paths(changes))
                tx.audit_id = audit.record(
                    conn,
                    action=action,
                    entity_type=entity_type,
                    entity_id=tx.entity_id,
                    job_id=tx.job_id,
                    summary=tx.summary or default_summary,
                    changes=changes,
                    field_path=field_path,
                    group=group,
                    extra=tx.extra or None,
                )
            else:
                audit.note_checked(tx.job_id)
            conn.commit()
            committed = True
            audit.after_commit(conn)
            tx._run_hooks()
        except BaseException:
            if not committed:
                _rollback(conn)
            raise
        finally:
            conn.close()
    finally:
        lock.release()


# ── Targeted setters (use inside job_write / entity_write, with tx.conn) ─────
# Header fields a save may change. Bid tracking fields are listed too (the
# bid tracker routes write them); version, blobs and ids are not.
JOB_FIELD_COLUMNS: tuple[str, ...] = (
    "project_name", "gc_name", "address", "city", "state", "zip", "tax_rate", "gpm_pct",
    "unit_count", "tub_shower_count", "salesperson", "notes", "exclusions", "markup_pct",
    "architect", "designer", "textura_fee", *JOB_ESTIMATE_HEADER_FIELDS,
)
UPDATABLE_JOB_COLUMNS = frozenset(JOB_FIELD_COLUMNS) | frozenset(BID_TRACKING_COLUMNS)


def _column_value(column: str, value):
    if column == "exclusions" and isinstance(value, (list, tuple)):
        return json.dumps(list(value))
    return value


def update_job_fields(conn, job_id: int, updates: dict) -> list[str]:
    """Set some of a bid's own fields. Only UPDATABLE_JOB_COLUMNS are allowed.
    Renaming the project also renames its slug. Returns the columns changed."""
    unknown = set(updates) - UPDATABLE_JOB_COLUMNS
    if unknown:
        raise ValueError(f"These bid fields can't be changed this way: {', '.join(sorted(unknown))}")
    if not updates:
        return []
    found = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if found is None:
        raise JobNotFoundError()
    current = dict(found)
    values = {column: _column_value(column, value) for column, value in updates.items()}
    changed = {column: value for column, value in values.items() if not audit.values_equal(current.get(column), value)}
    if not changed:
        return []
    if "project_name" in changed:
        name = str(changed["project_name"] or "").strip()
        if not name:
            raise ValueError("Project name can't be blank.")
        changed["slug"] = models._make_unique_slug(conn, models._slugify(name), exclude_id=job_id)
    columns = list(changed)
    conn.execute(
        f"UPDATE jobs SET {', '.join(f'{column} = ?' for column in columns)} WHERE id = ?",
        [changed[column] for column in columns] + [job_id],
    )
    return [column for column in columns if column != "slug"]


def create_job(conn, data: dict) -> int:
    """Insert a new bid from its header fields; returns the new id.

    Use inside ``entity_write("job", None, load_job_snapshot, "job.create")``
    and set ``tx.entity_id = tx.job_id = new_id``.
    """
    name = str(data.get("project_name") or "").strip()
    if not name:
        raise ValueError("Project name can't be blank.")
    # Other keys (materials, ids, ...) are ignored; add those separately.
    values = {column: _column_value(column, data.get(column)) for column in JOB_FIELD_COLUMNS}
    for column, default in (("tax_rate", 0), ("gpm_pct", 0), ("unit_count", 0), ("tub_shower_count", 0),
                            ("markup_pct", 0), ("textura_fee", 0)):
        if values.get(column) is None:
            values[column] = default
    values["project_name"] = name
    values = {column: value for column, value in values.items() if value is not None}
    values["slug"] = models._make_unique_slug(conn, models._slugify(name))
    values["created_at"] = datetime.now().isoformat()  # same local-clock format as save_job
    values["updated_at"] = audit.iso_ms(audit.utc_now())
    values["updated_by"] = audit.actor_label()
    columns = list(values)
    cur = conn.execute(
        f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [values[column] for column in columns],
    )
    return int(cur.lastrowid)


def load_job_snapshot(conn, job_id, scopes=ALL_SCOPES) -> dict | None:
    """An entity_write loader for bids (e.g. when creating one)."""
    if job_id is None:
        return None
    return snapshot_job(conn, int(job_id), scopes)


def set_proposal_data(conn, job_id: int, proposal_data, expected_rev: int | None = None) -> int:
    """Save the proposal. With ``expected_rev``, only if nobody saved since
    (compare-and-swap on jobs.proposal_rev), else ProposalConflictError.
    Returns the new proposal_rev."""
    payload = proposal_data if isinstance(proposal_data, str) or proposal_data is None else json.dumps(proposal_data)
    if expected_rev is None:
        cur = conn.execute(
            "UPDATE jobs SET proposal_data = ?, proposal_rev = COALESCE(proposal_rev, 0) + 1 WHERE id = ?",
            (payload, job_id),
        )
    else:
        cur = conn.execute(
            """UPDATE jobs SET proposal_data = ?, proposal_rev = COALESCE(proposal_rev, 0) + 1
               WHERE id = ? AND COALESCE(proposal_rev, 0) = ?""",
            (payload, job_id, int(expected_rev)),
        )
    found = conn.execute("SELECT COALESCE(proposal_rev, 0) FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if found is None:
        raise JobNotFoundError()
    if cur.rowcount == 0:
        raise ProposalConflictError(current_rev=int(found[0]))
    return int(found[0])


def set_bid_data(conn, job_id: int, bid_data) -> None:
    """Save (or clear, with None) the generated bid."""
    payload = bid_data if isinstance(bid_data, str) or bid_data is None else json.dumps(bid_data)
    cur = conn.execute("UPDATE jobs SET bid_data = ? WHERE id = ?", (payload, job_id))
    if cur.rowcount == 0:
        raise JobNotFoundError()


_META_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def patch_proposal_pdf_meta(conn, job_id: int, meta: dict) -> None:
    """Set top-level keys in the saved proposal (PDF time, totals, ...) in
    place with json_set, without rewriting the rest or bumping proposal_rev."""
    if not meta:
        return
    parts, params = [], []
    for key, value in meta.items():
        if not _META_KEY_RE.fullmatch(str(key)):
            raise ValueError(f"Not a proposal field name: {key!r}")
        parts.append(f"'$.{key}', json(?)")
        params.append(json.dumps(value, default=str))
    cur = conn.execute(
        f"""UPDATE jobs SET proposal_data = json_set(
                CASE WHEN json_valid(proposal_data) THEN proposal_data ELSE '{{}}' END,
                {', '.join(parts)})
            WHERE id = ?""",
        params + [job_id],
    )
    if cur.rowcount == 0:
        raise JobNotFoundError()
