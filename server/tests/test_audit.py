"""Tests for the audit trail core: server/audit.py and server/job_writes.py.

Run either way (each test uses its own throwaway database):
    python3.11 -m pytest server/tests/test_audit.py
    python3.11 server/tests/test_audit.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)
os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.mkdtemp(prefix="audit-test-"), "boot.db"))

import audit  # noqa: E402
import job_writes  # noqa: E402
import models  # noqa: E402
from job_writes import create_job, entity_write, job_write, load_job_snapshot, update_job_fields  # noqa: E402

T0 = datetime(2026, 9, 24, 14, 0, 0, tzinfo=timezone.utc)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fresh_db() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="audit-test-"), "test.db")
    models.DB_PATH = path
    audit._clock = None
    models.init_db()
    return path


@contextmanager
def _as_user(username: str, display_name: str | None = None, user_id: int | None = None):
    token = models.set_current_user({
        "id": user_id, "username": username, "display_name": display_name or username, "is_admin": False,
    })
    try:
        yield
    finally:
        models.reset_current_user(token)


@contextmanager
def _at(moment: datetime):
    previous = audit._clock
    audit._clock = lambda: moment
    try:
        yield
    finally:
        audit._clock = previous


def _query(sql: str, params=()) -> list[dict]:
    conn = models._get_conn()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _make_job(name: str = "Test Tower") -> int:
    with entity_write("job", None, load_job_snapshot, "job.create") as tx:
        job_id = create_job(tx.conn, {"project_name": name, "city": "Austin"})
        tx.entity_id = tx.job_id = job_id
    return job_id


def _set_notes(job_id: int, text: str, action: str = "job.notes.update", group=audit.TEXT_EDITS):
    with job_write(job_id, action=action, group=group) as tx:
        update_job_fields(tx.conn, job_id, {"notes": text})
    return tx


def _by_path(changes: list[dict]) -> dict[str, dict]:
    return {change["path"]: change for change in changes}


# ── Diff engine ───────────────────────────────────────────────────────────────
def test_diff_dicts_blank_equals_none_and_volatile_keys_ignored():
    changes = audit.diff(
        {"notes": None, "city": "Austin", "_client_save_sequence": 1, "audit": {"x": 1}, "gone": "old"},
        {"notes": "", "city": "Dallas", "_client_save_sequence": 2, "audit": {"x": 2}, "zip": "78701"},
    )
    assert changes == [
        {"path": "/city", "op": "replace", "before": "Austin", "after": "Dallas", "derived": False},
        {"path": "/gone", "op": "remove", "before": "old", "after": None, "derived": False},
        {"path": "/zip", "op": "add", "before": None, "after": "78701", "derived": False},
    ]
    assert audit.diff({"tax_rate": 1.0}, {"tax_rate": 1}) == []
    assert audit.diff({"a": 0.1 + 0.2}, {"a": 0.3}) == []
    assert audit.diff({"a": None}, {}) == []


def test_diff_rows_matched_by_id_with_derived_flags_and_order():
    before = {"materials": [
        {"id": 12, "item_code": "CPT-1", "unit_price": 4.0, "extended_cost": 40.0},
        {"id": 13, "item_code": "CPT-2", "unit_price": 1.0, "extended_cost": 5.0},
    ]}
    after = {"materials": [
        {"id": 13, "item_code": "CPT-2", "unit_price": 1.0, "extended_cost": 5.0},
        {"id": 12, "item_code": "CPT-1", "unit_price": 4.25, "extended_cost": 42.5},
        {"id": 14, "item_code": "LVT-1", "unit_price": 2.0, "extended_cost": 0},
    ]}
    changes = _by_path(audit.diff(before, after, entity_type="job"))
    assert changes["/materials/12/unit_price"]["before"] == 4.0
    assert changes["/materials/12/unit_price"]["after"] == 4.25
    assert changes["/materials/12/unit_price"]["derived"] is False
    assert changes["/materials/12/extended_cost"]["derived"] is True
    assert changes["/materials/14"]["op"] == "add"
    assert changes["/materials/14"]["after"]["item_code"] == "LVT-1"
    assert changes["/materials/_order"]["before"] == ["12", "13"]
    assert changes["/materials/_order"]["after"] == ["13", "12", "14"]
    assert "/materials/13" not in changes


def test_diff_prefers_uid_and_escapes_keys():
    before = {"proposal": {"bundles": [
        {"uid": "b_9f2c", "id": 1, "description_text": "Carpet"},
        {"uid": "b_1111", "id": 2, "description_text": "LVT"},
    ], "deleted_bundle_reasons": {"A/B": "dup"}}}
    after = {"proposal": {"bundles": [
        {"uid": "b_9f2c", "id": 99, "description_text": "Carpet tile"},
        {"uid": "b_1111", "id": 2, "description_text": "LVT"},
    ], "deleted_bundle_reasons": {"A/B": "duplicate"}}}
    changes = _by_path(audit.diff(before, after))
    assert "/proposal/bundles/b_9f2c/description_text" in changes
    assert changes["/proposal/bundles/b_9f2c/id"]["after"] == 99
    assert "/proposal/deleted_bundle_reasons/A~1B" in changes
    assert audit.split_path("/proposal/deleted_bundle_reasons/A~1B")[-1] == "A/B"


def test_diff_string_lists_give_line_ops():
    before = {"terms": ["Net 30", "Prices good for 30 days", "No sales tax on labor"]}
    after = {"terms": ["Net 30", "Prices good for 60 days", "No sales tax on labor", "Parking by others"]}
    [change] = audit.diff(before, after)
    assert change["path"] == "/terms" and change["op"] == "lines"
    assert change["before"] == before["terms"] and change["after"] == after["terms"]
    assert [hunk["op"] for hunk in change["hunks"]] == ["replace", "insert"]
    assert change["hunks"][0]["before"] == ["Prices good for 30 days"]
    assert change["hunks"][1]["after"] == ["Parking by others"]


def test_diff_rows_without_ids_line_up_by_content():
    row_a = {"sundry_name": "Tack strip", "qty": 10}
    row_b = {"sundry_name": "Seam tape", "qty": 4}
    row_c = {"sundry_name": "Glue", "qty": 2}
    changes = audit.diff({"sundries": [row_a, row_c]}, {"sundries": [row_a, row_b, row_c]}, entity_type="job")
    assert changes == [{"path": "/sundries/1", "op": "add", "before": None, "after": row_b, "derived": True}]
    changes = audit.diff({"sundries": [row_a, row_c]}, {"sundries": [row_a, {**row_c, "qty": 3}]})
    assert [(c["path"], c["before"], c["after"]) for c in changes] == [("/sundries/1/qty", 2, 3)]


def test_diff_derived_paths():
    assert audit.is_derived_path("/proposal/grand_total")
    assert audit.is_derived_path("/proposal/bundles/b_1/tax_amount")
    assert audit.is_derived_path("/proposal/pdf_totals/subtotal")
    assert audit.is_derived_path("/labor/3/qty")
    assert not audit.is_derived_path("/proposal/bundles/b_1/description_text")
    assert not audit.is_derived_path("/labor/3/qty", "labor_catalog")
    assert audit.common_path(["/materials/12/unit_price", "/materials/12/waste_pct"]) == "/materials/12"
    assert audit.common_path(["/notes", "/city"]) is None


# ── Redaction and caps ────────────────────────────────────────────────────────
def test_redaction_never_stores_secrets():
    _fresh_db()
    before = {"openai_api_key": "sk-old-secret", "openai_model": "gpt-5-mini",
              "email_config": json.dumps({"host": "imap.example.com", "password": "hunter2"})}
    after = {"openai_api_key": "sk-new-secret", "openai_model": "gpt-5-mini",
             "email_config": json.dumps({"host": "imap2.example.com", "password": "hunter3"})}
    with audit.write_transaction() as conn:
        audit_id = audit.record(conn, action="settings.update", entity_type="settings", entity_id="app",
                                summary="Changed settings", before=before, after=after,
                                extra={"pin": "1234", "note": "ok"})
    [row] = _query("SELECT * FROM audit_log WHERE id = ?", (audit_id,))
    stored = row["changes"] + (row["extra"] or "")
    for secret in ("sk-old-secret", "sk-new-secret", "hunter2", "hunter3", "1234"):
        assert secret not in stored, secret
    changes = _by_path(json.loads(row["changes"]))
    assert changes["/openai_api_key"]["after"] == {"redacted": True, "changed": True}
    assert changes["/openai_api_key"]["redacted"] is True
    assert "imap2.example.com" in changes["/email_config"]["after"]
    assert audit.is_sensitive_key("pin_hash") and audit.is_sensitive_key("smtp_password")
    assert not audit.is_sensitive_key("shipping") and not audit.is_sensitive_key("pinned")


def test_big_values_and_too_many_changes_are_capped():
    _fresh_db()
    big = "x" * 10_000
    changes = [{"path": f"/rows/{i}", "op": "replace", "before": i, "after": i + 1} for i in range(600)]
    with audit.write_transaction() as conn:
        big_id = audit.record(conn, action="test.big", entity_type="test", entity_id="1",
                              summary="big", before={"text": "small"}, after={"text": big})
        many_id = audit.record(conn, action="test.many", entity_type="test", entity_id="2",
                               summary="many", changes=changes)
    [big_row] = _query("SELECT changes FROM audit_log WHERE id = ?", (big_id,))
    [capped] = json.loads(big_row["changes"])
    assert capped["after"]["truncated"] is True
    assert capped["after"]["len"] == len(json.dumps(big))
    assert len(capped["after"]["hash"]) == 64 and capped["after"]["head"] == big[:300]
    assert capped["before"] == "small"
    item = audit.get_entry(many_id)
    assert len(item["changes"]) == 500
    assert item["extra"]["changes_truncated"]["total"] == 600


# ── Grouping ──────────────────────────────────────────────────────────────────
def test_grouping_two_editors_one_entry_then_new_entry_after_idle():
    _fresh_db()
    job_id = _make_job()
    with _at(T0), _as_user("alice", "Alice", 1):
        _set_notes(job_id, "a")
    with _at(T0 + timedelta(seconds=20)), _as_user("bob", "Bob", 2):
        _set_notes(job_id, "ab")
    with _at(T0 + timedelta(seconds=40)), _as_user("alice", "Alice", 1):
        _set_notes(job_id, "abc")

    page = audit.query_entries({"job_id": job_id, "action": "job.notes"})
    assert len(page["items"]) == 1
    [entry] = page["items"]
    assert entry["edit_count"] == 3 and entry["group_open"] is True
    assert entry["field_path"] == "/notes"
    assert entry["ts_first"] == "2026-09-24T14:00:00.000Z" and entry["ts"] == "2026-09-24T14:00:40.000Z"
    assert [(a["username"], a["edit_count"]) for a in entry["actors"]] == [("alice", 2), ("bob", 1)]
    [change] = entry["changes"]
    assert (change["path"], change["before"], change["after"]) == ("/notes", None, "abc")
    assert entry["actor_username"] == "alice"
    assert audit.query_entries({"job_id": job_id, "actor": "bob"})["items"][0]["id"] == entry["id"]

    # Idle for longer than the text policy (60 s): a new entry, the old one closes.
    with _at(T0 + timedelta(seconds=40 + 61)), _as_user("bob", "Bob", 2):
        _set_notes(job_id, "abcd")
    items = audit.query_entries({"job_id": job_id, "action": "job.notes"})["items"]
    assert len(items) == 2
    newest, oldest = items
    assert oldest["id"] == entry["id"] and oldest["group_open"] is False and oldest["net_noop"] is False
    assert newest["group_open"] is True and newest["changes"][0]["before"] == "abc"
    assert newest["seq"] > oldest["seq"]

    # The sweeper closes it once its idle time passes.
    assert audit.sweep_idle_groups(now=T0 + timedelta(seconds=40 + 61 + 30)) == 0
    assert audit.sweep_idle_groups(now=T0 + timedelta(seconds=40 + 61 + 61)) == 1
    assert audit.get_entry(newest["id"])["group_open"] is False


def test_group_that_ends_where_it_started_is_net_noop():
    _fresh_db()
    job_id = _make_job()
    with _at(T0), _as_user("alice"):
        _set_notes(job_id, "draft")
    with _at(T0 + timedelta(seconds=90)), _as_user("alice"):
        _set_notes(job_id, "draft 2")
    with _at(T0 + timedelta(seconds=100)), _as_user("alice"):
        _set_notes(job_id, "draft")
    audit.sweep_idle_groups(now=T0 + timedelta(minutes=10))
    newest = audit.query_entries({"job_id": job_id, "action": "job.notes"})["items"][0]
    assert newest["edit_count"] == 2 and newest["net_noop"] is True


def test_one_off_entry_closes_open_groups_on_the_same_bid():
    _fresh_db()
    job_id = _make_job()
    with _at(T0), _as_user("alice"):
        _set_notes(job_id, "typing")
    with _at(T0 + timedelta(seconds=5)), _as_user("bob"):
        with job_write(job_id, action="job.update") as tx:
            update_job_fields(tx.conn, job_id, {"city": "Dallas"})
    assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE group_open = 1")[0]["n"] == 0


def test_startup_closes_open_groups():
    _fresh_db()
    job_id = _make_job()
    with _as_user("alice"):
        _set_notes(job_id, "typing")
    assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE group_open = 1")[0]["n"] == 1
    models.init_db()
    assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE group_open = 1")[0]["n"] == 0


# ── Append-only triggers ──────────────────────────────────────────────────────
def _raises_db_error(sql: str, params=()) -> bool:
    conn = models._get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    except sqlite3.DatabaseError:
        return True
    finally:
        conn.close()
    return False


def test_triggers_block_delete_and_changes_to_closed_entries():
    _fresh_db()
    job_id = _make_job()
    [closed] = _query("SELECT id FROM audit_log WHERE action = 'job.create'")
    with _as_user("alice"):
        _set_notes(job_id, "typing")
    [open_row] = _query("SELECT id FROM audit_log WHERE group_open = 1")

    assert _raises_db_error("DELETE FROM audit_log WHERE id = ?", (closed["id"],))
    assert _raises_db_error("DELETE FROM audit_log")
    assert _raises_db_error("UPDATE audit_log SET summary = 'edited' WHERE id = ?", (closed["id"],))
    assert _raises_db_error("UPDATE audit_log SET action = 'other' WHERE id = ?", (open_row["id"],))
    assert _raises_db_error("DELETE FROM audit_log_actors")
    assert not _raises_db_error("UPDATE audit_log SET summary = 'still typing' WHERE id = ?", (open_row["id"],))
    assert not _raises_db_error("UPDATE audit_log SET group_open = 0 WHERE id = ?", (open_row["id"],))
    assert _raises_db_error("UPDATE audit_log SET group_open = 1 WHERE id = ?", (open_row["id"],))
    assert _raises_db_error("UPDATE audit_log_actors SET edit_count = 9 WHERE audit_id = ?", (open_row["id"],))
    assert _query("SELECT COUNT(*) AS n FROM audit_log")[0]["n"] == 2


# ── job_write ─────────────────────────────────────────────────────────────────
def test_job_write_bumps_version_and_records_changes():
    _fresh_db()
    with _as_user("alice", "Alice", 1):
        job_id = _make_job()
        with job_write(job_id, action="job.update", summary="Moved the job to Dallas") as tx:
            update_job_fields(tx.conn, job_id, {"city": "Dallas", "tax_rate": 0.0825})
    assert tx.changed and tx.version == 0 and tx.new_version == 1
    [row] = _query("SELECT version, updated_by, updated_at FROM jobs WHERE id = ?", (job_id,))
    assert row["version"] == 1 and row["updated_by"] == "alice" and row["updated_at"].endswith("Z")
    entry = audit.get_entry(tx.audit_id)
    assert entry["summary"] == "Moved the job to Dallas"
    assert entry["actor_username"] == "alice" and entry["actor_kind"] == "user"
    assert entry["job_name"] == "Test Tower"
    assert {c["path"]: (c["before"], c["after"]) for c in entry["changes"]} == {
        "/city": ("Austin", "Dallas"), "/tax_rate": (0, 0.0825),
    }


def test_job_write_with_no_change_writes_nothing():
    _fresh_db()
    job_id = _make_job()
    before = _query("SELECT COUNT(*) AS n FROM audit_log")[0]["n"]
    with job_write(job_id, action="job.update") as tx:
        update_job_fields(tx.conn, job_id, {"city": "Austin"})
    assert not tx.changed and tx.audit_id is None
    assert _query("SELECT version FROM jobs WHERE id = ?", (job_id,))[0]["version"] == 0
    assert _query("SELECT COUNT(*) AS n FROM audit_log")[0]["n"] == before


def test_job_write_rolls_back_everything_on_error():
    _fresh_db()
    job_id = _make_job()
    count = _query("SELECT COUNT(*) AS n FROM audit_log")[0]["n"]
    try:
        with job_write(job_id, action="job.update") as tx:
            update_job_fields(tx.conn, job_id, {"city": "Dallas"})
            raise ValueError("stop")
    except ValueError:
        pass
    assert _query("SELECT city, version FROM jobs WHERE id = ?", (job_id,)) == [{"city": "Austin", "version": 0}]
    assert _query("SELECT COUNT(*) AS n FROM audit_log")[0]["n"] == count
    # The lock was released: the next save works.
    with job_write(job_id, action="job.update") as tx:
        update_job_fields(tx.conn, job_id, {"city": "Houston"})
    assert tx.new_version == 1


def test_job_write_checks_expected_version_and_unknown_jobs():
    _fresh_db()
    job_id = _make_job()
    try:
        with job_write(job_id, action="job.update", expected_version=3):
            raise AssertionError("should not run")
    except job_writes.VersionConflictError as err:
        assert err.status_code == 409 and err.info == {"current_version": 0}
    try:
        with job_write(987654, action="job.update"):
            raise AssertionError("should not run")
    except job_writes.JobNotFoundError as err:
        assert err.status_code == 404
    try:
        with job_write(job_id, action="job.update"):
            with job_write(job_id, action="job.update"):
                pass
    except RuntimeError as err:
        assert "inside another" in str(err)
    else:
        raise AssertionError("nested job_write should be refused")


def test_job_write_refuses_to_run_on_the_event_loop():
    import asyncio

    _fresh_db()
    job_id = _make_job()

    async def on_loop():
        with job_write(job_id, action="job.update"):
            pass

    try:
        asyncio.run(on_loop())
    except RuntimeError as err:
        assert "event loop" in str(err)
    else:
        raise AssertionError("job_write on the event loop should be refused")


def test_update_job_fields_whitelist_and_slug():
    _fresh_db()
    job_id = _make_job()
    with job_write(job_id, action="job.update") as tx:
        try:
            update_job_fields(tx.conn, job_id, {"version": 5})
        except ValueError as err:
            assert "version" in str(err)
        else:
            raise AssertionError("version must not be settable")
        update_job_fields(tx.conn, job_id, {"project_name": "Renamed Tower", "exclusions": ["Permits"]})
    [row] = _query("SELECT slug, exclusions FROM jobs WHERE id = ?", (job_id,))
    assert row["slug"] == "renamed-tower" and json.loads(row["exclusions"]) == ["Permits"]
    changes = _by_path(audit.get_entry(tx.audit_id)["changes"])
    assert changes["/slug"]["derived"] is True and changes["/project_name"]["derived"] is False
    assert changes["/exclusions"]["op"] == "lines"


def test_proposal_compare_and_swap_and_pdf_meta():
    _fresh_db()
    job_id = _make_job()
    with job_write(job_id, action="proposal.edit") as tx:
        rev = job_writes.set_proposal_data(tx.conn, job_id, {"bundles": [], "notes": ["One"]}, expected_rev=0)
    assert rev == 1
    try:
        with job_write(job_id, action="proposal.edit") as tx:
            job_writes.set_proposal_data(tx.conn, job_id, {"bundles": [], "notes": ["Stale"]}, expected_rev=0)
    except job_writes.ProposalConflictError as err:
        assert err.info == {"current_rev": 1}
    else:
        raise AssertionError("stale proposal save should conflict")
    with job_write(job_id, action="proposal.pdf") as tx:
        job_writes.patch_proposal_pdf_meta(tx.conn, job_id, {"pdf_generated_at": "2026-09-24T14:00:00Z",
                                                              "pdf_totals": {"grand_total": 12.5}})
        tx.force_record()
    [row] = _query("SELECT proposal_data, proposal_rev FROM jobs WHERE id = ?", (job_id,))
    data = json.loads(row["proposal_data"])
    assert data["notes"] == ["One"] and data["pdf_totals"] == {"grand_total": 12.5}
    assert row["proposal_rev"] == 1
    changes = audit.get_entry(tx.audit_id)["changes"]
    # A new dict is diffed key by key, like a key going from null to a dict.
    assert [c["path"] for c in changes] == ["/proposal/pdf_totals/grand_total"] and changes[0]["derived"] is True


def test_entity_write_add_change_delete():
    _fresh_db()

    def load_vendor(conn, vendor_id):
        row = conn.execute("SELECT id, name, contact_email FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        return dict(row) if row else None

    now = datetime.now().isoformat()
    with entity_write("vendor", None, load_vendor, "vendor.create") as tx:
        cur = tx.conn.execute("INSERT INTO vendors (name, created_at, updated_at) VALUES ('Acme', ?, ?)", (now, now))
        tx.entity_id = cur.lastrowid
    vendor_id = tx.entity_id
    assert audit.get_entry(tx.audit_id)["summary"] == "Added vendor"
    with entity_write("vendor", vendor_id, load_vendor, "vendor.update") as tx:
        tx.conn.execute("UPDATE vendors SET contact_email = 'sales@acme.test' WHERE id = ?", (vendor_id,))
    assert audit.get_entry(tx.audit_id)["changes"][0]["path"] == "/contact_email"
    with entity_write("vendor", vendor_id, load_vendor, "vendor.delete") as tx:
        tx.conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
    entry = audit.get_entry(tx.audit_id)
    assert entry["summary"] == "Deleted vendor" and {c["op"] for c in entry["changes"]} == {"remove"}
    assert len(audit.query_entries({"entity_type": "vendor", "entity_id": str(vendor_id)})["items"]) == 3


# ── log_activity shim, system context, backfill ──────────────────────────────
def test_log_activity_writes_activity_and_audit():
    _fresh_db()
    job_id = _make_job()
    with _as_user("alice", "Alice", 1):
        activity_id = models.log_activity(job_id, "job_updated", "Updated city",
                                          {"changes": {"city": {"old": "Austin", "new": "Dallas"}}})
    [activity] = _query("SELECT * FROM job_activity WHERE id = ?", (activity_id,))
    assert activity["username"] == "alice" and activity["summary"] == "Updated city"
    entry = audit.query_entries({"job_id": job_id, "action": "job.update"})["items"][0]
    assert entry["summary"] == "Updated city" and entry["actor_username"] == "alice"
    assert entry["changes"] == [{"path": "/city", "op": "replace", "before": "Austin", "after": "Dallas",
                                 "derived": False}]
    assert entry["extra"]["activity_action"] == "job_updated"

    # Inside a job_write for the same bid it becomes that entry's summary.
    with _as_user("alice", "Alice", 1):
        with job_write(job_id, action="job.update") as tx:
            update_job_fields(tx.conn, job_id, {"notes": "Call GC"})
            models.log_activity(job_id, "notes_updated", "Notes updated")
    entry = audit.get_entry(tx.audit_id)
    assert entry["summary"] == "Notes updated"
    assert _query("SELECT COUNT(*) AS n FROM job_activity WHERE action = 'notes_updated'")[0]["n"] == 1
    assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE action = 'job.notes.update'")[0]["n"] == 0


def test_system_context_attribution():
    _fresh_db()
    job_id = _make_job()
    with audit.system_context("inbox_monitor", mailbox="quotes@example.com"):
        models.log_activity(job_id, "agent_quote_imported", "Auto-imported quote from Acme")
    entry = audit.query_entries({"job_id": job_id, "action": "quotes"})["items"][0]
    assert entry["source"] == "inbox_monitor" and entry["actor_kind"] == "system"
    assert entry["actor_display"] == "System" and entry["action"] == "quotes.auto_import"
    assert entry["extra"]["context"] == {"mailbox": "quotes@example.com"}
    assert audit.query_entries({"actor": "system", "job_id": job_id})["items"]


def test_backfill_copies_legacy_history_once():
    _fresh_db()
    job_id = _make_job()
    conn = models._get_conn()
    try:
        conn.execute("INSERT INTO users (username, display_name, pin_hash, created_at) VALUES "
                     "('josh', 'Josh', 'x', '2026-01-01T00:00:00+00:00')")
        conn.execute("INSERT INTO job_activity (job_id, action, summary, detail, created_at, user, username) "
                     "VALUES (?, 'bid_sent', 'Bid marked as sent to GC Co ($1,000.00)', NULL, "
                     "'2026-09-01T10:00:00.500000', 'Josh', 'josh')", (job_id,))
        conn.execute("INSERT INTO job_activity (job_id, action, summary, detail, created_at, user, username) "
                     "VALUES (?, 'job_updated', 'Updated city', ?, '2026-09-01T09:00:00', 'Josh', 'josh')",
                     (job_id, json.dumps({"changes": {"city": {"old": "A", "new": "B"}}})))
        conn.execute("INSERT INTO bid_events (job_id, event_type, created_at, username, details) "
                     "VALUES (?, 'sent', '2026-09-01T10:00:01+00:00', 'josh', ?)",
                     (job_id, json.dumps({"sent_to": None, "gc_name": "GC Co", "bid_total": 1000})))
        conn.execute("INSERT INTO admin_log (created_at, username, action, target_username, details) "
                     "VALUES ('2026-09-01T08:00:00+00:00', 'josh', 'reset_pin', 'bob', ?)",
                     (json.dumps({"sessions_ended": 1}),))
        conn.execute("DELETE FROM app_settings WHERE key = ?", (audit.BACKFILL_SETTING_KEY,))
        conn.commit()
        assert audit.backfill_legacy(conn) == 3
        assert audit.backfill_legacy(conn) == 0
    finally:
        conn.close()
    legacy = _query("SELECT * FROM audit_log WHERE source = 'legacy_import' ORDER BY id")
    assert [row["action"] for row in legacy] == ["user.reset_pin", "job.update", "bid.sent"]
    assert [row["ts"] for row in legacy] == [
        "2026-09-01T08:00:00.000Z", "2026-09-01T09:00:00.000Z", "2026-09-01T10:00:01.000Z",
    ]
    sent = legacy[2]
    assert sent["summary"] == "Bid marked as sent to GC Co ($1,000.00)" and sent["actor_display"] == "Josh"
    assert json.loads(sent["extra"])["legacy"] == {"table": "bid_events", "id": 1}
    pin = json.loads(legacy[0]["changes"])[0]
    assert pin["path"] == "/pin_hash" and pin["after"] == {"redacted": True, "changed": True}
    assert json.loads(legacy[1]["changes"])[0]["after"] == "B"


# ── Route policies and the backstop ───────────────────────────────────────────
def _backstop_app(strict: bool):
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/api/audited")
    @audit.audit_route("thing.update")
    def audited():
        with audit.write_transaction() as conn:
            audit.record(conn, action="thing.update", entity_type="thing", entity_id="1", summary="Changed thing")
        return {"ok": True}

    @app.post("/api/forgot")
    def forgot(body: dict | None = None):
        return {"ok": True}

    @app.post("/api/search")
    @audit.no_audit("read-only search")
    def search():
        return {"results": []}

    class FakeLogin:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            token = models.set_audit_context({"request_id": "req-1", "source": "http", "session_id": None,
                                              "client_ip": "1.2.3.4", "route": "POST test"})
            try:
                await self.inner(scope, receive, send)
            finally:
                models.reset_audit_context(token)

    app.add_middleware(audit.AuditBackstopMiddleware, strict=strict)
    app.add_middleware(FakeLogin)
    return app


def test_route_policies_and_backstop():
    from fastapi.testclient import TestClient

    _fresh_db()
    app = _backstop_app(strict=False)
    policies = {row["path"]: row["policy"] for row in audit.list_route_policies(app)}
    assert policies["/api/audited"] == {"kind": "audited", "actions": ["thing.update"]}
    assert policies["/api/search"] == {"kind": "no_audit", "reason": "read-only search"}
    assert policies["/api/forgot"] is None

    client = TestClient(app)
    assert client.post("/api/audited").status_code == 200
    assert client.post("/api/search").status_code == 200
    assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE action = 'unaudited_write'")[0]["n"] == 0
    body = b'{"a":1}'
    assert client.post("/api/forgot", content=body, headers={"content-type": "application/json"}).status_code == 200
    [row] = _query("SELECT * FROM audit_log WHERE action = 'unaudited_write'")
    extra = json.loads(row["extra"])
    assert row["entity_id"] == "POST test" and extra["body_bytes"] == len(body)
    assert extra["body_sha256"] == __import__("hashlib").sha256(body).hexdigest()

    strict_client = TestClient(_backstop_app(strict=True))
    response = strict_client.post("/api/forgot")
    assert response.status_code == 500 and "history" in response.json()["detail"]
    assert strict_client.post("/api/audited").status_code == 200


def test_staging_is_strict_unless_told_otherwise():
    saved = {key: os.environ.get(key) for key in ("AUDIT_STRICT", "FLY_APP_NAME")}
    try:
        os.environ.pop("AUDIT_STRICT", None)
        os.environ["FLY_APP_NAME"] = "si-bid-stg-20260714-c0fa"
        assert audit._audit_strict() is True
        os.environ["AUDIT_STRICT"] = "0"
        assert audit._audit_strict() is False
        os.environ.pop("AUDIT_STRICT")
        os.environ["FLY_APP_NAME"] = "si-bid-tool"
        assert audit._audit_strict() is False
        os.environ["AUDIT_STRICT"] = "1"
        assert audit._audit_strict() is True
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ── Review fixes: blank values, blank-to-dict diffs, grouping keys ───────────
def test_diff_empty_lists_and_dicts_are_blank():
    assert audit.values_equal(None, []) and audit.values_equal({}, "") and audit.values_equal([], {})
    assert audit.diff({"notes": None}, {"notes": [], "deleted_bundles": [], "reasons": {}}) == []
    assert audit.diff({"materials": [], "extra": {}}, {}) == []
    # A list going to empty still records the removed lines.
    [change] = audit.diff({"terms": ["Net 30"]}, {"terms": []})
    assert (change["op"], change["before"], change["after"]) == ("lines", ["Net 30"], [])
    [change] = audit.diff({"terms": ["Net 30"]}, {})
    assert (change["op"], change["before"], change["after"]) == ("lines", ["Net 30"], [])


def test_diff_blank_to_dict_is_diffed_key_by_key():
    proposal = {"grand_total": 5.0, "bundles": [{"bundle_name": "A"}, {"bundle_name": "B"}], "notes": ["n1"]}
    added = _by_path(audit.diff({"proposal": None}, {"proposal": proposal}, entity_type="job"))
    assert set(added) == {"/proposal/grand_total", "/proposal/bundles/0", "/proposal/bundles/1", "/proposal/notes"}
    assert added["/proposal/grand_total"]["op"] == "add" and added["/proposal/grand_total"]["after"] == 5.0
    assert added["/proposal/bundles/1"]["after"] == {"bundle_name": "B"}
    assert added["/proposal/notes"]["op"] == "lines"
    removed = _by_path(audit.diff({"bid": {"grand_total": 9.5, "parts": {"x": 1}}}, {"bid": ""}))
    assert removed["/bid/grand_total"]["op"] == "remove" and removed["/bid/grand_total"]["before"] == 9.5
    assert removed["/bid/parts/x"]["op"] == "remove"
    # A missing key holding a list is diffed row by row too.
    rows = audit.diff({}, {"rows": [{"id": 1, "qty": 2}]})
    assert [(c["path"], c["op"]) for c in rows] == [("/rows/1", "add")]


def test_multi_field_saves_only_group_with_the_same_fields():
    _fresh_db()
    job_id = _make_job()

    def save(values, moment):
        with _at(moment), _as_user("alice"):
            with job_write(job_id, action="job.update", scopes=("job",), group=audit.NUMBER_EDITS) as tx:
                update_job_fields(tx.conn, job_id, values)
        return tx.audit_id

    first = save({"gc_name": "Acme", "tax_rate": 0.08}, T0)
    second = save({"address": "1 Main", "zip": "80202"}, T0 + timedelta(seconds=5))
    third = save({"address": "2 Main", "zip": "80203"}, T0 + timedelta(seconds=10))
    assert first != second and second == third
    assert [c["path"] for c in audit.get_entry(first)["changes"]] == ["/gc_name", "/tax_rate"]
    entry = audit.get_entry(second)
    assert entry["edit_count"] == 2 and {c["path"] for c in entry["changes"]} == {"/address", "/zip"}


def test_group_summary_covers_every_field_it_holds():
    _fresh_db()
    with audit.write_transaction() as conn, _at(T0), _as_user("alice"):
        first = audit.record(conn, action="materials.update", entity_type="job", entity_id="7", job_id=None,
                             summary="Changed unit price on CPT-1", field_path="/materials/12",
                             changes=[{"path": "/materials/12/unit_price", "op": "replace", "before": 4, "after": 5}],
                             group=audit.NUMBER_EDITS)
    with audit.write_transaction() as conn, _at(T0 + timedelta(seconds=5)), _as_user("alice"):
        audit.record(conn, action="materials.update", entity_type="job", entity_id="7", job_id=None,
                     summary="Changed unit price on CPT-1", field_path="/materials/12",
                     changes=[{"path": "/materials/12/unit_price", "op": "replace", "before": 5, "after": 6}],
                     group=audit.NUMBER_EDITS)
    assert audit.get_entry(first)["summary"] == "Changed unit price on CPT-1"
    with audit.write_transaction() as conn, _at(T0 + timedelta(seconds=10)), _as_user("bob"):
        second = audit.record(conn, action="materials.update", entity_type="job", entity_id="7", job_id=None,
                              summary="Changed waste pct on CPT-1", field_path="/materials/12",
                              changes=[{"path": "/materials/12/waste_pct", "op": "replace", "before": 0.1, "after": 0.12}],
                              group=audit.NUMBER_EDITS)
    assert second == first
    entry = audit.get_entry(first)
    assert entry["edit_count"] == 3 and entry["summary"] == "Changed unit price and waste pct"


def test_entity_write_groups_each_field_separately():
    _fresh_db()

    def load_settings(conn, _entity_id):
        return {row["key"]: row["value"] for row in conn.execute(
            "SELECT key, value FROM app_settings WHERE key IN ('test_model', 'test_folder')")}

    def save(key, value, moment):
        with _at(moment), _as_user("alice"):
            with entity_write("settings", "app", load_settings, "settings.update", audit.NUMBER_EDITS) as tx:
                tx.conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
        return tx.audit_id

    first_model = save("test_model", "a", T0)
    first_folder = save("test_folder", "x", T0 + timedelta(seconds=1))
    model_id = save("test_model", "b", T0 + timedelta(seconds=2))
    folder_id = save("test_folder", "y", T0 + timedelta(seconds=4))
    # Each setting's quick re-saves join its own entry, never the other's.
    assert (model_id, folder_id) == (first_model, first_folder) and model_id != folder_id
    assert audit.get_entry(model_id)["summary"] == "Changed test model"
    assert audit.get_entry(model_id)["field_path"] == "/test_model"
    assert [c["path"] for c in audit.get_entry(folder_id)["changes"]] == ["/test_folder"]


if __name__ == "__main__":
    failures = 0
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except Exception as err:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {name}: {err!r}")
    print(f"\n{len(tests) - failures} passed, {failures} failed")
    sys.exit(1 if failures else 0)
