"""Tests for Phase 2 history safety: soft-deleted bids and versioned PDFs.

Run either way (each test uses its own throwaway database and files):
    python3.11 -m pytest server/tests/test_soft_delete.py
    python3.11 server/tests/test_soft_delete.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)
_BOOT = tempfile.mkdtemp(prefix="soft-delete-test-")
os.environ.setdefault("DATABASE_PATH", os.path.join(_BOOT, "boot.db"))
os.environ.setdefault("ARTIFACT_ROOT", os.path.join(_BOOT, "artifacts"))

import audit  # noqa: E402
import models  # noqa: E402
from job_writes import (  # noqa: E402
    JobDeletedError, create_job, entity_write, job_write, load_job_snapshot, update_job_fields,
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fresh_db() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="soft-delete-test-"), "test.db")
    models.DB_PATH = path
    audit._clock = None
    models.init_db()
    return path


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


def _make_job(name: str) -> int:
    with entity_write("job", None, load_job_snapshot, "job.create") as tx:
        job_id = create_job(tx.conn, {"project_name": name, "gc_name": "Acme GC", "city": "Austin"})
        tx.entity_id = tx.job_id = job_id
    return job_id


def _delete(job_id: int, reason: str = "Duplicate bid") -> None:
    with job_write(job_id, action="job.delete", scopes=("job", "tracking")) as tx:
        tx.force_record()
        assert models.delete_job(tx.job_id, reason=reason, deleted_by=audit.actor_label(), conn=tx.conn)


# ── Soft delete (models / job_writes) ─────────────────────────────────────────
def test_delete_reason_is_required():
    for bad in (None, "", "   ", "x" * 501):
        try:
            models.clean_delete_reason(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    assert models.clean_delete_reason("  Lost  to  another sub ") == "Lost to another sub"


def test_soft_delete_hides_the_bid_but_keeps_everything():
    _fresh_db()
    with _as_user("josh", "Josh"):
        kept = _make_job("Keep Tower")
        gone = _make_job("Gone Tower")
        models.save_quotes(gone, [{"product_name": "Tile", "vendor": "V", "unit_price": 2, "unit": "SF"}])
        models.create_notification(kept, "quote", "Quote in for Keep Tower")
        gone_note = models.create_notification(gone, "quote", "Quote in for Gone Tower")
        _delete(gone)
    row = _query("SELECT deleted_at, deleted_by, delete_reason FROM jobs WHERE id=?", (gone,))[0]
    assert row["deleted_at"] and row["deleted_by"] == "josh" and row["delete_reason"] == "Duplicate bid"
    assert _query("SELECT COUNT(*) AS n FROM job_quotes WHERE job_id=?", (gone,))[0]["n"] == 1  # no cascade
    assert models.load_job(gone) is None and models.load_job(gone, include_deleted=True)["id"] == gone
    assert {job["id"] for job in models.list_jobs()} == {kept}
    assert [job["id"] for job in models.search_all("Tower")["jobs"]] == [kept]
    assert [bid["job_id"] for bid in models.list_bid_tracker_jobs()] == [kept]
    assert [note["job_id"] for note in models.get_notifications()] == [kept]
    # Marking a deleted bid's notification read still works (it isn't bid data).
    with entity_write("notification", gone_note, lambda conn, _id: None, "notification.read",
                      allow_deleted=True) as tx:
        tx.job_id = gone
        models.mark_notification_read(gone_note, conn=tx.conn)
    deleted = models.list_deleted_jobs()
    assert [(item["id"], item["deleted_by_name"], item["delete_reason"]) for item in deleted] == [
        (gone, "josh", "Duplicate bid")]
    # The delete is in the history, with the fields it set.
    entry = _query("SELECT * FROM audit_log WHERE job_id=? AND action='job.delete'", (gone,))[0]
    paths = {change["path"] for change in json.loads(entry["changes"])}
    assert {"/deleted_at", "/deleted_by", "/delete_reason"} <= paths


def test_changes_to_a_deleted_bid_are_refused_with_who_and_when():
    _fresh_db()
    models.create_user("josh", "1234", "Josh Estimator")
    with _as_user("josh", "Josh Estimator"):
        job_id = _make_job("Gone Tower")
        _delete(job_id)
    try:
        with job_write(job_id, action="job.update") as tx:
            update_job_fields(tx.conn, job_id, {"city": "Dallas"})
    except JobDeletedError as err:
        assert err.status_code == 410
        assert err.message.startswith("This bid was deleted by Josh Estimator on ")
        assert err.message.endswith(". An admin can restore it.")
        assert err.info["delete_reason"] == "Duplicate bid"
    else:
        raise AssertionError("job_write changed a deleted bid")
    # Anything saved against the bid (a comment, a quote request...) too.
    try:
        with entity_write("comment", None, lambda conn, _id: None, "comment.add", job_id=job_id) as tx:
            models.add_comment(job_id, "hello", conn=tx.conn)
    except JobDeletedError:
        pass
    else:
        raise AssertionError("entity_write saved a comment on a deleted bid")
    assert _query("SELECT COUNT(*) AS n FROM job_comments WHERE job_id=?", (job_id,))[0]["n"] == 0
    # A restore is allowed, and then changes work again.
    with job_write(job_id, action="job.restore", allow_deleted=True) as tx:
        assert models.restore_job(tx.job_id, conn=tx.conn)
    with job_write(job_id, action="job.update") as tx:
        update_job_fields(tx.conn, job_id, {"city": "Dallas"})
    assert models.load_job(job_id)["city"] == "Dallas"


def test_artifact_receipts_are_insert_only():
    _fresh_db()
    job_id = _make_job("Pdf Plaza")
    first = models.record_job_artifact(job_id, "proposal_pdf", f"{job_id}/pdfs/a.pdf", "hash-a", 10, grand_total=100)
    second = models.record_job_artifact(job_id, "proposal_pdf", f"{job_id}/pdfs/b.pdf", "hash-b", 11, grand_total=120.456)
    again = models.record_job_artifact(job_id, "proposal_pdf", f"{job_id}/pdfs/a.pdf", "hash-a", 10)
    assert first != second and again == first
    assert [item["id"] for item in models.list_job_artifacts(job_id, "proposal_pdf")] == [second, first]
    latest = models.get_latest_job_artifact(job_id, "proposal_pdf")
    assert latest["id"] == second and latest["grand_total"] == 120.46
    assert models.get_job_artifact(job_id, first)["file_hash"] == "hash-a"
    conn = sqlite3.connect(models.DB_PATH)
    try:
        conn.execute("UPDATE job_artifacts SET file_hash='x' WHERE id=?", (first,))
        raise AssertionError("a receipt was changed")
    except sqlite3.DatabaseError as err:
        assert "insert-only" in str(err)
    finally:
        conn.rollback()
        conn.close()


# ── Through the API ───────────────────────────────────────────────────────────
def test_api_soft_delete_restore_and_versioned_pdfs():
    """Delete with a reason, 410 on writes, lists, admin restore, two PDFs kept."""
    _fresh_db()
    from fastapi.testclient import TestClient
    import main

    scratch = tempfile.mkdtemp(prefix="soft-delete-artifacts-")
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
        models.create_user("alice", "4321", "Alice Admin", is_admin=True)
        models.create_user("bob", "1234", "Bob Builder")
        with TestClient(main.app) as alice, TestClient(main.app) as bob:
            assert alice.post("/api/auth/login", json={"username": "alice", "pin": "4321"}).status_code == 200
            assert bob.post("/api/auth/login", json={"username": "bob", "pin": "1234"}).status_code == 200
            job = bob.post("/api/jobs", json={"project_name": "Zebra Tower"}).json()
            job_id, slug = job["id"], job["slug"]

            assert bob.delete(f"/api/jobs/{job_id}").status_code == 400  # reason required
            r = bob.request("DELETE", f"/api/jobs/{slug}", json={"reason": "Duplicate"})
            assert r.status_code == 200, r.text
            r = bob.put(f"/api/jobs/{job_id}/notes", json={"notes": "x"})
            assert r.status_code == 410 and r.json()["detail"].startswith("This bid was deleted by Bob Builder on ")
            assert bob.post(f"/api/jobs/{job_id}/duplicate").status_code == 410
            assert bob.get(f"/api/jobs/{job_id}").status_code == 404
            full = bob.get(f"/api/jobs/{job_id}?include_deleted=1").json()
            assert full["deleted_by"] == "bob" and full["delete_reason"] == "Duplicate"
            assert job_id not in {item["id"] for item in bob.get("/api/jobs").json()}
            assert [item["id"] for item in bob.get("/api/jobs/deleted").json()] == [job_id]
            assert bob.get(f"/api/jobs/{job_id}/history").status_code == 200
            assert bob.post(f"/api/jobs/{job_id}/restore").status_code == 403
            r = alice.post(f"/api/jobs/{job_id}/restore")
            assert r.status_code == 200 and not r.json()["deleted_at"], r.text

            body = {"bundles": [{"name": "Flooring", "total": 1000}], "grand_total": 1000}
            first = bob.post(f"/api/jobs/{job_id}/proposal/pdf", json=body)
            body["grand_total"] = 1100
            second = bob.post(f"/api/jobs/{job_id}/proposal/pdf", json=body)
            assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
            items = bob.get(f"/api/jobs/{job_id}/artifacts?kind=proposal_pdf").json()
            assert [item["id"] for item in items] == [second.json()["artifact_id"], first.json()["artifact_id"]]
            assert [item["grand_total"] for item in items] == [1100, 1000]
            receipts = _query("SELECT artifact_path FROM job_artifacts WHERE job_id=? ORDER BY id", (job_id,))
            files = [os.path.join(scratch, row["artifact_path"]) for row in receipts]
            assert len(set(files)) == 2 and all(os.path.isfile(path) for path in files)
            latest = bob.get(f"/api/jobs/{job_id}/proposal.pdf")
            assert latest.status_code == 200 and latest.content == open(files[1], "rb").read()
            older = bob.get(f"/api/jobs/{job_id}/artifacts/{items[1]['id']}/download")
            assert older.status_code == 200 and older.content == open(files[0], "rb").read()
            assert not os.listdir(main.PDF_TEMP_DIR)
            assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE action='unaudited_write'")[0]["n"] == 0
    finally:
        for name, value in saved.items():
            setattr(main, name, value)


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
