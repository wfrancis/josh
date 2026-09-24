"""Tests for Phase 2 proposal versions (server/proposal_versions.py and the
/api/jobs/{id}/proposal/versions routes).

Run either way (each test uses its own throwaway database and files):
    python3.11 -m pytest server/tests/test_proposal_versions.py
    python3.11 server/tests/test_proposal_versions.py
"""

from __future__ import annotations

import copy
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
_BOOT = tempfile.mkdtemp(prefix="proposal-versions-test-")
os.environ.setdefault("DATABASE_PATH", os.path.join(_BOOT, "boot.db"))
os.environ.setdefault("ARTIFACT_ROOT", os.path.join(_BOOT, "artifacts"))

import audit  # noqa: E402
import models  # noqa: E402
import proposal_versions as pv  # noqa: E402
from job_writes import (  # noqa: E402
    create_job, entity_write, job_write, load_job_snapshot, set_proposal_data, update_job_fields,
)

T0 = datetime(2026, 9, 24, 14, 0, 0, tzinfo=timezone.utc)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fresh_db() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="proposal-versions-test-"), "test.db")
    models.DB_PATH = path
    audit._clock = None
    pv.reset_burst_memory()
    models.init_db()
    return path


class _Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


@contextmanager
def _clock(start: datetime = T0):
    clock = _Clock(start)
    audit._clock = clock
    try:
        yield clock
    finally:
        audit._clock = None


@contextmanager
def _as_user(username: str, display_name: str | None = None):
    token = models.set_current_user({"id": None, "username": username,
                                     "display_name": display_name or username, "is_admin": False})
    try:
        yield
    finally:
        models.reset_current_user(token)


def _query(sql: str, params=()) -> list[dict]:
    conn = models._get_conn()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _proposal(description: str = "Carpet in all units", total: float = 1000.0, *, second: bool = False) -> dict:
    bundles = [{
        "uid": "b_carpet", "bundle_name": "Carpet", "description_text": description,
        "total_price": total, "materials": [{"item_code": "CPT-1", "description": "Carpet"}],
    }]
    if second:
        bundles.append({
            "uid": "b_lvt", "bundle_name": "LVT", "description_text": "LVT in corridors",
            "total_price": 500.0, "materials": [{"item_code": "LVT-1", "description": "LVT"}],
        })
    grand_total = total + (500.0 if second else 0)
    return {"bundles": bundles, "notes": ["Price good for 30 days"], "terms": [],
            "tax_rate": 0.0825, "gpm_pct": 0.2, "grand_total": grand_total}


def _make_job(name: str = "Zebra Tower") -> int:
    with entity_write("job", None, load_job_snapshot, "job.create") as tx:
        job_id = create_job(tx.conn, {"project_name": name, "gc_name": "Acme GC", "city": "Austin",
                                      "tax_rate": 0.0825})
        tx.entity_id = tx.job_id = job_id
    return job_id


def _save_proposal(job_id: int, proposal: dict) -> None:
    with job_write(job_id, action="proposal.save", scopes=("proposal",), group=audit.TEXT_EDITS) as tx:
        set_proposal_data(tx.conn, job_id, proposal)


def _versions(job_id: int) -> list[dict]:
    return _query("SELECT * FROM proposal_versions WHERE job_id=? ORDER BY version_no", (job_id,))


# ── Content hashes ────────────────────────────────────────────────────────────
def test_content_hash_ignores_bookkeeping_print_details_and_blanks():
    fields = {"project_name": "Zebra", "tax_rate": 0.0825, "exclusions": []}
    base = _proposal()
    same = copy.deepcopy(base)
    same.update({
        "_client_session_id": "tab-1", "_server_revision": 7, "audit": {"run_id": 4},
        "audit_source_fingerprint": "abc", "pdf_generated_at": "2026-09-24T10:00:00Z",
        "job_info": {"project_name": "Zebra"}, "pdf_totals": {"grand_total": 1000},
        "pdf_audit_run_id": 3, "deleted_bundles": [], "exclusions": None,
    })
    same["grand_total"] = 1000  # a browser sends 1000 for 1000.0
    assert pv.content_hash(base, fields) == pv.content_hash(same, fields)
    changed = copy.deepcopy(base)
    changed["bundles"][0]["description_text"] = "Carpet in units and halls"
    assert pv.content_hash(base, fields) != pv.content_hash(changed, fields)
    assert pv.content_hash(base, fields) != pv.content_hash(base, {**fields, "tax_rate": 0.09})
    assert pv.proposal_hash(base) == pv.proposal_hash(same)


def test_labels_are_trimmed_and_limited():
    assert pv.clean_label("  Sent  to\nGC  ") == "Sent to GC"
    assert pv.clean_label("   ") is None and pv.clean_label(None) is None
    try:
        pv.clean_label("x" * 121)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted a 121-character name")


# ── Storing, dedupe, migration and triggers ───────────────────────────────────
def test_snapshot_dedupes_and_versions_are_kept_for_good():
    _fresh_db()
    job_id = _make_job()
    with _as_user("bob", "Bob Builder"):
        _save_proposal(job_id, _proposal())
        with job_write(job_id, action="proposal.generate", scopes=("proposal",)) as tx:
            first = pv.snapshot(tx.conn, job_id, "generate")
            again = pv.snapshot(tx.conn, job_id, "pdf")  # same content: the latest version
        assert first == again
        _save_proposal(job_id, _proposal(total=1200.0))
        with job_write(job_id, action="proposal.pdf", scopes=("proposal",)) as tx:
            second = pv.snapshot(tx.conn, job_id, "pdf")
    rows = _versions(job_id)
    assert [row["version_no"] for row in rows] == [1, 2] and second != first
    assert [row["reason"] for row in rows] == ["generate", "pdf"]
    assert rows[0]["created_by"] == "bob" and json.loads(rows[0]["contributors"]) == ["bob"]
    assert rows[1]["grand_total"] == 1200.0 and rows[1]["bundle_count"] == 1

    conn = models._get_conn()
    try:
        for sql in ("DELETE FROM proposal_versions WHERE id = ?",
                    "UPDATE proposal_versions SET reason = 'baseline' WHERE id = ?",
                    "UPDATE proposal_versions SET proposal_data = x'00' WHERE id = ?"):
            try:
                conn.execute(sql, (first,))
            except sqlite3.DatabaseError:
                conn.rollback()
                continue
            raise AssertionError(f"allowed: {sql}")
        conn.execute("UPDATE proposal_versions SET label = 'First', artifact_id = 9 WHERE id = ?", (first,))
        conn.commit()
    finally:
        conn.close()
    assert _versions(job_id)[0]["label"] == "First"


def test_baseline_version_for_existing_proposals_is_made_once():
    _fresh_db()
    job_id = _make_job()
    empty_id = _make_job("No Proposal Yet")
    conn = models._get_conn()
    try:  # a proposal saved before versions existed
        conn.execute("UPDATE jobs SET proposal_data = ? WHERE id = ?", (json.dumps(_proposal()), job_id))
        conn.commit()
        assert pv.init_versions(conn) == 1
        assert pv.init_versions(conn) == 0
    finally:
        conn.close()
    models.init_db()  # every start runs it again
    rows = _versions(job_id)
    assert len(rows) == 1 and rows[0]["reason"] == "baseline" and rows[0]["created_by"] == pv.MIGRATION_ACTOR
    assert _versions(empty_id) == []
    stored = pv.get_version(job_id, rows[0]["id"])
    assert stored["proposal_data"]["bundles"][0]["uid"] == "b_carpet"
    assert stored["job_fields"]["project_name"] == "Zebra Tower" and stored["job_fields"]["exclusions"] == []
    assert stored["created_by_name"] == "System" and stored["matches_current"] is True


def test_materials_snapshot_and_rfms_style_dedupe():
    _fresh_db()
    job_id = _make_job()
    _save_proposal(job_id, _proposal())
    line = {"item_code": "CPT-1", "description": "Carpet", "material_type": "carpet_tile",
            "installed_qty": 100, "unit": "SY", "unit_price": 20}
    with job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
        models.save_materials(job_id, [line], conn=tx.conn)
    with job_write(job_id, action="proposal.pdf", scopes=("proposal",)) as tx:
        first = pv.snapshot(tx.conn, job_id, "pdf")
    with job_write(job_id, action="rfms.upload", scopes=("materials",)) as tx:
        before = pv.capture(tx.conn, job_id)
        models.save_materials(job_id, [{**line, "installed_qty": 140}], conn=tx.conn)
        assert pv.current_materials_fingerprint(tx.conn, job_id) != before["materials_fingerprint"]
        # Same proposal, same lines as the latest version: nothing new ...
        assert pv.store(tx.conn, before, "rfms_upload", match_materials=True) == (first, False)
    with job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
        models.save_materials(job_id, [{**line, "installed_qty": 150}], conn=tx.conn)
    with job_write(job_id, action="rfms.upload", scopes=("materials",)) as tx:
        before = pv.capture(tx.conn, job_id)
        models.save_materials(job_id, [{**line, "installed_qty": 180}], conn=tx.conn)
        # ... but lines changed since the latest version: kept as a version.
        version_id, created = pv.store(tx.conn, before, "rfms_upload", match_materials=True)
    assert created
    detail = pv.get_version(job_id, version_id, include_materials=True)
    assert [row["installed_qty"] for row in detail["materials"]] == [150]
    assert detail["materials_changed_since"] is True and detail["reason"] == "rfms_upload"


# ── Edit bursts (the sweeper) ─────────────────────────────────────────────────
def test_edit_burst_version_after_two_quiet_minutes_lists_every_editor():
    _fresh_db()
    job_id = _make_job()
    with _clock() as clock:
        with _as_user("bob", "Bob Builder"):
            _save_proposal(job_id, _proposal())
        clock.advance(20)
        with _as_user("alice", "Alice Admin"):
            _save_proposal(job_id, _proposal("Carpet in units and halls"))
        clock.advance(20)
        with job_write(job_id, action="job.update", scopes=("job",), group=audit.NUMBER_EDITS) as tx:
            update_job_fields(tx.conn, job_id, {"tax_rate": 0.09})  # a system change: not an editor
        assert pv.sweep_edit_bursts(clock.advance(60)) == []  # only 60 s quiet
        assert audit.sweep_idle_groups(clock.now) >= 1  # the history groups close first
        created = pv.sweep_edit_bursts(clock.advance(61))
        assert len(created) == 1
        assert pv.sweep_edit_bursts(clock.advance(30)) == []  # nothing new since
        row = _versions(job_id)[0]
        assert row["reason"] == "edit_burst" and json.loads(row["contributors"]) == ["bob", "alice"]
        assert row["created_by"] == "alice"
        assert json.loads(row["job_fields"])["tax_rate"] == 0.09

        # Editing back to the saved content makes no new version.
        with _as_user("bob"):
            _save_proposal(job_id, _proposal())
            _save_proposal(job_id, _proposal("Carpet in units and halls"))
        assert pv.sweep_edit_bursts(clock.advance(200)) == []
        assert len(_versions(job_id)) == 1


def test_edit_burst_version_every_30_minutes_of_continuous_editing():
    _fresh_db()
    job_id = _make_job()
    with _clock() as clock:
        with _as_user("bob"):
            for minute in range(0, 31):
                _save_proposal(job_id, _proposal(f"Carpet, revision {minute}"))
                if minute < 30:
                    assert pv.sweep_edit_bursts(clock.now) == [], minute
                clock.advance(60)
        created = pv.sweep_edit_bursts(clock.now)  # last edit 60 s ago, first 31 min ago
        assert len(created) == 1
        row = _versions(job_id)[0]
        assert row["reason"] == "edit_burst"
        assert pv.get_version(job_id, row["id"])["proposal_data"]["bundles"][0]["description_text"] == "Carpet, revision 30"


# ── Through the API ───────────────────────────────────────────────────────────
def test_api_versions_generate_pdf_sent_burst_diff_label_restore():
    _fresh_db()
    from fastapi.testclient import TestClient
    import main

    scratch = tempfile.mkdtemp(prefix="proposal-versions-artifacts-")
    patched = {
        "ARTIFACT_ROOT": scratch,
        "PDF_TEMP_DIR": os.path.join(scratch, "shared", "tmp"),
        "_validate_proposal_pdf_ready": lambda job, body: None,
        "_validate_proposal_pdf_download_ready": lambda job: None,
    }
    saved = {name: getattr(main, name) for name in patched}
    for name, value in patched.items():
        setattr(main, name, value)
    os.makedirs(main.PDF_TEMP_DIR, exist_ok=True)
    try:
        with TestClient(main.app):
            pass  # startup: tables and seeds
        # Startup hooks the edit-burst check into the history sweeper.
        assert pv.sweep_edit_bursts in audit._sweep_hooks
        models.create_user("alice", "4321", "Alice Admin", is_admin=True)
        models.create_user("bob", "1234", "Bob Builder")
        with TestClient(main.app) as alice, TestClient(main.app) as bob:
            assert alice.post("/api/auth/login", json={"username": "alice", "pin": "4321"}).status_code == 200
            assert bob.post("/api/auth/login", json={"username": "bob", "pin": "1234"}).status_code == 200
            job_id = bob.post("/api/jobs", json={"project_name": "Versions Tower", "gc_name": "Acme GC"}).json()["id"]
            with job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
                models.save_materials(job_id, [
                    {"item_code": "CPT-1", "description": "Carpet tile", "material_type": "carpet_tile",
                     "installed_qty": 900, "unit": "SF", "waste_pct": 0.05, "order_qty": 945,
                     "unit_price": 3.25, "extended_cost": 3071.25},
                    {"item_code": "LVT-1", "description": "Luxury vinyl plank", "material_type": "lvt",
                     "installed_qty": 400, "unit": "SF", "waste_pct": 0.05, "order_qty": 420,
                     "unit_price": 2.5, "extended_cost": 1050.0},
                ], conn=tx.conn)
            base = f"/api/jobs/{job_id}/proposal/versions"
            assert bob.get(base).json() == []

            # First generate: saved, and kept as version 1.
            r = bob.post(f"/api/jobs/{job_id}/proposal/generate")
            assert r.status_code == 200, r.text
            generated = r.json()
            versions = bob.get(base).json()
            assert [(v["version_no"], v["reason"], v["created_by"]) for v in versions] == [(1, "generate", "bob")]
            v1 = versions[0]
            assert v1["bundle_count"] == len(generated["bundles"]) > 0 and v1["matches_current"] is True
            uids = [bundle["uid"] for bundle in generated["bundles"]]

            # Bob and Alice edit; once editing goes quiet the sweeper saves version 2.
            edited = copy.deepcopy(generated)
            edited["bundles"][0]["description_text"] = "Carpet tile in every unit, per plan A2.1"
            r = bob.put(f"/api/jobs/{job_id}/proposal/bundles", json=edited)
            assert r.status_code == 200, r.text
            edited = r.json()["proposal_data"]
            edited["notes"] = list(edited.get("notes") or []) + ["Alice: confirm corridor base"]
            r = alice.put(f"/api/jobs/{job_id}/proposal/bundles", json=edited)
            assert r.status_code == 200, r.text
            current = r.json()["proposal_data"]
            assert pv.sweep_edit_bursts(audit.utc_now() + timedelta(seconds=30)) == []
            assert len(pv.sweep_edit_bursts(audit.utc_now() + timedelta(seconds=130))) == 1
            versions = bob.get(base).json()
            v2 = versions[0]
            assert (v2["version_no"], v2["reason"]) == (2, "edit_burst")
            assert v2["contributors"] == ["bob", "alice"] and v2["contributor_names"] == ["Bob Builder", "Alice Admin"]
            assert [bundle["uid"] for bundle in bob.get(f"{base}/{v2['id']}").json()["proposal_data"]["bundles"]] == uids

            # A PDF of the unchanged proposal points at version 2; a changed one makes version 3.
            r = bob.post(f"/api/jobs/{job_id}/proposal/pdf", json=current)
            assert r.status_code == 200, r.text
            first_pdf = r.json()
            assert first_pdf["proposal_version_id"] == v2["id"]
            printed = copy.deepcopy(current)
            printed["grand_total"] = round(float(current["grand_total"]) + 100, 2)
            r = bob.post(f"/api/jobs/{job_id}/proposal/pdf", json=printed)
            assert r.status_code == 200, r.text
            second_pdf = r.json()
            versions = bob.get(base).json()
            v3 = versions[0]
            assert (v3["version_no"], v3["reason"], v3["artifact_id"]) == (3, "pdf", second_pdf["artifact_id"])
            assert versions[1]["artifact_id"] == first_pdf["artifact_id"]
            artifacts = bob.get(f"/api/jobs/{job_id}/artifacts?kind=proposal_pdf").json()
            assert {a["id"]: a["proposal_version_id"] for a in artifacts} == {
                second_pdf["artifact_id"]: v3["id"], first_pdf["artifact_id"]: v2["id"],
            }
            pdf_entry = _query("SELECT proposal_version_id FROM audit_log WHERE action='proposal.pdf' ORDER BY id DESC LIMIT 1")
            assert pdf_entry[0]["proposal_version_id"] == v3["id"]

            # Marking it sent records the version that went out (no new version).
            r = bob.post(f"/api/jobs/{job_id}/bid-events", json={"event_type": "sent", "sent_to": "estimating@acme.test"})
            assert r.status_code == 200, r.text
            sent = [event for event in r.json()["events"] if event["event_type"] == "sent"][0]
            details = sent.get("details") if isinstance(sent.get("details"), dict) else json.loads(sent.get("details") or "{}")
            assert details["proposal_version_id"] == v3["id"], sent
            assert details["pdf"]["proposal_version_id"] == v3["id"]
            assert len(bob.get(base).json()) == 3

            # Compare version 1 with now: the bundle text and the notes changed.
            r = bob.get(f"{base}/{v1['id']}/diff?against=current")
            assert r.status_code == 200, r.text
            diff = r.json()
            paths = [change["path"] for change in diff["changes"]]
            assert f"/proposal/bundles/{uids[0]}/description_text" in paths, paths
            assert "/proposal/notes" in paths
            assert diff["summary"]["bundles_changed"] >= 1 and diff["summary"]["bundles_added"] == 0
            assert diff["summary"]["grand_total_before"] == v1["grand_total"]
            assert diff["summary"]["grand_total_after"] == round(printed["grand_total"], 2)
            between = bob.get(f"{base}/{v1['id']}/diff?against={v2['id']}").json()
            assert f"/proposal/bundles/{uids[0]}/description_text" in [c["path"] for c in between["changes"]]
            assert bob.get(f"{base}/{v1['id']}/diff?against=latest").status_code == 400
            assert bob.get(f"{base}/999999/diff").status_code == 404

            # Naming a version is audited; too long a name is refused.
            r = alice.patch(f"{base}/{v1['id']}", json={"label": "  First draft  "})
            assert r.status_code == 200 and r.json()["label"] == "First draft", r.text
            assert alice.patch(f"{base}/{v1['id']}", json={"label": "x" * 121}).status_code == 400
            assert alice.patch(f"{base}/999999", json={"label": "x"}).status_code == 404
            labels = _query("SELECT actor_username, summary, proposal_version_id FROM audit_log WHERE action='proposal.version_label'")
            assert labels == [{"actor_username": "alice", "summary": 'Named proposal version 1 "First draft"',
                               "proposal_version_id": v1["id"]}]

            # An unsaved-as-version edit, then Bob restores version 1.
            later = copy.deepcopy(printed)
            later["bundles"][-1]["description_text"] = "Changed right before the restore"
            r = bob.put(f"/api/jobs/{job_id}/proposal/bundles", json=later)
            assert r.status_code == 200, r.text
            later_revision = r.json()["proposal_data"]["_server_revision"]
            r = bob.post(f"{base}/{v1['id']}/restore")
            assert r.status_code == 200, r.text
            restored = r.json()
            assert restored["unchanged"] is False and restored["restored_from_version_id"] == v1["id"]
            assert restored["version"]["reason"] == "restore" and restored["version"]["restored_from_version_id"] == v1["id"]
            job_now = restored["job"]["proposal_data"]
            original = bob.get(f"{base}/{v1['id']}").json()["proposal_data"]
            assert pv.proposal_content(job_now) == pv.proposal_content(pv.restorable_proposal(original, None))
            assert [b["uid"] for b in job_now["bundles"]] == uids
            assert "pdf_totals" not in job_now and job_now["audit_source_fingerprint"]
            versions = bob.get(base).json()
            assert [(v["version_no"], v["reason"]) for v in versions[:2]] == [(5, "restore"), (4, "before_restore")]
            assert restored["before_restore_version_id"] == versions[1]["id"]
            assert versions[0]["matches_current"] is True and versions[0]["created_by"] == "bob"
            before_restore = bob.get(f"{base}/{versions[1]['id']}").json()["proposal_data"]
            assert before_restore["bundles"][-1]["description_text"] == "Changed right before the restore"
            entry = _query("SELECT * FROM audit_log WHERE action='proposal.restore'")
            assert len(entry) == 1 and entry[0]["actor_username"] == "bob"
            assert entry[0]["proposal_version_id"] == versions[0]["id"]
            assert entry[0]["summary"] == 'Restored proposal version 1 "First draft"'
            assert any(c["path"].startswith("/proposal/") for c in json.loads(entry[0]["changes"]))
            # Restoring what's already there saves nothing.
            again = bob.post(f"{base}/{versions[0]['id']}/restore").json()
            assert again["unchanged"] is True and len(bob.get(base).json()) == 5
            # A tab still showing the old proposal can't save over the restore ...
            stale = {**copy.deepcopy(later), "client_session_id": "bobs-other-tab", "client_edit_version": 9,
                     "client_save_sequence": 9, "base_server_revision": later_revision}
            assert bob.put(f"/api/jobs/{job_id}/proposal/bundles", json=stale).status_code == 409
            # ... but an edit made after reloading saves.
            job_now["notes"] = ["After the restore"]
            r = bob.put(f"/api/jobs/{job_id}/proposal/bundles", json=job_now)
            assert r.status_code == 200 and r.json()["status"] == "ok", r.text

            # Deleted bids: versions readable with include_deleted, never changed.
            r = alice.request("DELETE", f"/api/jobs/{job_id}", json={"reason": "Test cleanup"})
            assert r.status_code == 200, r.text
            assert bob.get(base).status_code == 404
            assert len(bob.get(f"{base}?include_deleted=1").json()) == 5
            assert bob.get(f"{base}/{v1['id']}?include_deleted=1").status_code == 200
            assert bob.patch(f"{base}/{v1['id']}", json={"label": "x"}).status_code == 410
            r = bob.post(f"{base}/{v1['id']}/restore")
            assert r.status_code == 410 and r.json()["detail"].startswith("This bid was deleted by Alice Admin on ")

            assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE action='unaudited_write'")[0]["n"] == 0
    finally:
        for name, value in saved.items():
            setattr(main, name, value)


def test_api_status_sent_and_regenerate_make_versions():
    _fresh_db()
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app):
        pass
    models.create_user("bob", "1234", "Bob Builder")
    with TestClient(main.app) as bob:
        assert bob.post("/api/auth/login", json={"username": "bob", "pin": "1234"}).status_code == 200
        job_id = bob.post("/api/jobs", json={"project_name": "Status Tower"}).json()["id"]
        with job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
            models.save_materials(job_id, [
                {"item_code": "CPT-1", "description": "Carpet tile", "material_type": "carpet_tile",
                 "installed_qty": 900, "unit": "SF", "waste_pct": 0.05, "order_qty": 945,
                 "unit_price": 3.25, "extended_cost": 3071.25},
            ], conn=tx.conn)
        base = f"/api/jobs/{job_id}/proposal/versions"
        # Sent with no proposal yet: nothing to keep.
        r = bob.patch(f"/api/jobs/{job_id}/bid-tracking", json={"bid_status": "Sent"})
        assert r.status_code == 200, r.text
        assert bob.get(base).json() == []
        generated = bob.post(f"/api/jobs/{job_id}/proposal/generate").json()
        edited = copy.deepcopy(generated)
        edited["bundles"][0]["description_text"] = "Edited before a regenerate"
        assert bob.put(f"/api/jobs/{job_id}/proposal/bundles", json=edited).status_code == 200
        # Regenerate keeps the accepted proposal as a version first.
        assert bob.post(f"/api/jobs/{job_id}/proposal/generate").status_code == 200
        versions = bob.get(base).json()
        assert [(v["version_no"], v["reason"]) for v in versions] == [(2, "before_regenerate"), (1, "generate")]
        kept = bob.get(f"{base}/{versions[0]['id']}").json()["proposal_data"]
        assert kept["bundles"][0]["description_text"] == "Edited before a regenerate"
        entry = _query("SELECT proposal_version_id FROM audit_log WHERE action='proposal.generate' ORDER BY id")
        assert entry[0]["proposal_version_id"] == versions[1]["id"]
        # Status set to Sent from the tracker card: that event records the version too.
        assert bob.patch(f"/api/jobs/{job_id}/bid-tracking", json={"bid_status": "Estimating"}).status_code == 200
        r = bob.patch(f"/api/jobs/{job_id}/bid-tracking", json={"bid_status": "Sent"})
        assert r.status_code == 200, r.text
        sent = [event for event in r.json()["events"] if event["event_type"] == "sent"][0]
        details = sent.get("details") if isinstance(sent.get("details"), dict) else json.loads(sent.get("details") or "{}")
        assert details["proposal_version_id"] == versions[0]["id"]
        assert len(bob.get(base).json()) == 2
        assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE action='unaudited_write'")[0]["n"] == 0


if __name__ == "__main__":
    failures = 0
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except Exception as err:  # noqa: BLE001
            failures += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL  {name}: {err!r}")
    print(f"\n{len(tests) - failures} passed, {failures} failed")
    sys.exit(1 if failures else 0)
