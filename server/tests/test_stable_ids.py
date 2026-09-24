"""Tests for Phase 2 stable ids and compare-and-swap saves for the AI flows.

- material uids, sundry/labor line keys and proposal bundle uids (backfill,
  saves, regenerate);
- keyed upserts: sundry, labor and catalog saves show field-level history;
- AI flows (quote auto-match, detect-vendors, price estimates) never
  overwrite a change someone made while the AI was working.

Run either way (each test uses its own throwaway database):
    python3.11 -m pytest server/tests/test_stable_ids.py
    python3.11 server/tests/test_stable_ids.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)
_BOOT = tempfile.mkdtemp(prefix="stable-ids-test-")
os.environ.setdefault("DATABASE_PATH", os.path.join(_BOOT, "boot.db"))
os.environ.setdefault("ARTIFACT_ROOT", os.path.join(_BOOT, "artifacts"))

import audit  # noqa: E402
import models  # noqa: E402
import stable_ids  # noqa: E402
from job_writes import create_job, entity_write, job_write, load_job_snapshot  # noqa: E402
from pricing_rows import apply_material_patches, material_patch, normalize_material_row  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fresh_db() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="stable-ids-test-"), "test.db")
    models.DB_PATH = path
    audit._clock = None
    models.init_db()
    return path


@contextmanager
def _as_user(username: str):
    token = models.set_current_user({"id": None, "username": username, "display_name": username, "is_admin": False})
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


def _execute(sql: str, params=()) -> None:
    conn = models._get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _make_job(name: str = "Stable Tower") -> int:
    with entity_write("job", None, load_job_snapshot, "job.create") as tx:
        job_id = create_job(tx.conn, {"project_name": name})
        tx.entity_id = tx.job_id = job_id
    return job_id


def _material(code: str, **extra) -> dict:
    row = {
        "item_code": code, "description": f"{code} product", "material_type": "floor_tile",
        "installed_qty": 100, "unit": "SF", "waste_pct": 0.1, "order_qty": 110,
        "unit_price": 2.0, "extended_cost": 220.0,
    }
    row.update(extra)
    return row


def _last_entry(action: str) -> dict:
    [row] = _query("SELECT * FROM audit_log WHERE action=? ORDER BY id DESC LIMIT 1", (action,))
    row["changes"] = json.loads(row["changes"] or "[]")
    row["extra"] = json.loads(row["extra"] or "null") or {}
    return row


# ── Pure helpers ──────────────────────────────────────────────────────────────
def test_line_keys_number_repeats_and_follow_material_uids():
    uids = {7: "m7", 8: "m1a2b3c4d"}
    rows = [
        {"material_id": 7, "sundry_name": "Thinset"},
        {"material_id": 7, "sundry_name": " thinset "},
        {"material_id": 8, "sundry_name": "Grout"},
        {"material_id": None, "sundry_name": "Freight"},
        {"material_id": 99, "sundry_name": "Tape"},
    ]
    assert stable_ids.assign_line_keys(rows, "sundry_name", uids) == [
        "m7|thinset", "m7|thinset#2", "m1a2b3c4d|grout", "job|freight", "#99|tape",
    ]
    # Filling in next to keys already used skips them.
    assert stable_ids.assign_line_keys(rows[:1], "sundry_name", uids, taken={"m7|thinset"}) == ["m7|thinset#2"]


def test_new_uids_never_look_like_backfilled_ids():
    for _ in range(200):
        uid = stable_ids.new_material_uid()
        assert uid.startswith("m") and len(uid) == 9 and not uid[1:].isdigit()
    assert stable_ids.new_bundle_uid().startswith("b_")


def test_bundle_uid_backfill_is_deterministic_and_idempotent():
    proposal = {"bundles": [{"bundle_name": "Bath LVT"}, {"bundle_name": "Corridor CPT", "uid": "b_keep"}]}
    assert stable_ids.backfill_proposal_bundle_uids(12, proposal)
    first = proposal["bundles"][0]["uid"]
    import hashlib
    assert first == "b_" + hashlib.sha1(b"12|0|Bath LVT").hexdigest()[:10]
    assert proposal["bundles"][1]["uid"] == "b_keep"
    assert not stable_ids.backfill_proposal_bundle_uids(12, proposal)
    assert proposal["bundles"][0]["uid"] == first


def test_carry_bundle_uids_keeps_echoed_and_matches_the_rest():
    previous = [
        {"uid": "b_a", "bundle_name": "Bath", "materials": [{"item_code": "T-1"}]},
        {"uid": "b_b", "bundle_name": "Custom", "materials": []},
        {"uid": "b_c", "bundle_name": "Corridor", "materials": [{"item_code": "C-1"}, {"item_code": "C-2"}]},
    ]
    incoming = [
        {"uid": "b_a", "bundle_name": "Bath (renamed)", "materials": [{"item_code": "T-1"}]},
        {"uid": "b_a", "bundle_name": "Copy of Bath", "materials": [{"item_code": "T-1"}]},  # a copy
        {"bundle_name": "Custom", "materials": []},                                          # by name
        {"bundle_name": "Hall", "materials": [{"item_code": "C-2"}, {"item_code": "C-1"}]},  # by materials
        {"bundle_name": "Brand new", "materials": [{"item_code": "X-9"}]},
    ]
    counts = stable_ids.carry_bundle_uids(previous, incoming)
    uids = [bundle["uid"] for bundle in incoming]
    assert uids[0] == "b_a" and uids[2] == "b_b" and uids[3] == "b_c"
    assert uids[1] not in ("b_a", "b_b", "b_c") and uids[4] not in ("b_a", "b_b", "b_c")
    assert len(set(uids)) == 5
    assert counts == {"kept": 1, "matched": 2, "new": 2}


def test_normalize_material_row_prices_like_the_materials_save():
    base = _material("T-1", id=5, price_source="vendor_quote", quote_source_hash="abc", quote_status="quoted")
    merged = normalize_material_row(base, {"unit_price": 3.0, "price_source": "manual", "order_qty": None})
    assert merged["order_qty"] == 110.0 and merged["extended_cost"] == 330.0
    assert merged["quote_source_hash"] is None  # no longer a vendor quote
    stick = _material("TR-1", id=6, material_type="transitions", unit="EA", price_source="price_book",
                      vendor="Schluter", installed_qty=20, waste_pct=0, order_qty=20, unit_price=10)
    priced = normalize_material_row(stick, {"unit_price": 10})
    assert priced["order_qty"] == 3 and priced["extended_cost"] == 30.0  # 20 LF = 3 sticks of 8'2"


# ── Migration / backfill ─────────────────────────────────────────────────────
def test_backfill_fills_uids_line_keys_and_bundle_uids_once():
    _fresh_db()
    job_id = _make_job()
    conn = models._get_conn()
    try:
        # A database from before stable ids: no triggers, indexes or values.
        for name in ("job_materials_fill_uid", "job_sundries_fill_line_key", "job_labor_fill_line_key",
                     "job_materials_bump_row_version", "job_sundries_bump_row_version",
                     "job_labor_bump_row_version"):
            conn.execute(f"DROP TRIGGER {name}")
        for name in ("idx_job_materials_uid", "idx_job_sundries_line_key", "idx_job_labor_line_key"):
            conn.execute(f"DROP INDEX {name}")
        cur = conn.execute("INSERT INTO job_materials (job_id, item_code) VALUES (?, 'T-1')", (job_id,))
        material_id = cur.lastrowid
        for _ in range(2):
            conn.execute("INSERT INTO job_sundries (job_id, material_id, sundry_name, qty) VALUES (?, ?, 'Thinset', 1)",
                         (job_id, material_id))
        conn.execute("INSERT INTO job_labor (job_id, material_id, labor_description) VALUES (?, ?, 'Install tile')",
                     (job_id, material_id))
        conn.execute("UPDATE jobs SET proposal_data=? WHERE id=?",
                     (json.dumps({"bundles": [{"bundle_name": "Bath"}, {"bundle_name": "Hall"}]}), job_id))
        conn.commit()
    finally:
        conn.close()

    models.init_db()
    [material] = _query("SELECT uid FROM job_materials WHERE id=?", (material_id,))
    assert material["uid"] == f"m{material_id}"
    keys = [row["line_key"] for row in _query("SELECT line_key FROM job_sundries WHERE job_id=? ORDER BY id", (job_id,))]
    assert keys == [f"m{material_id}|thinset", f"m{material_id}|thinset#2"]
    assert _query("SELECT line_key FROM job_labor")[0]["line_key"] == f"m{material_id}|install tile"
    proposal = json.loads(_query("SELECT proposal_data FROM jobs WHERE id=?", (job_id,))[0]["proposal_data"])
    first_uids = [bundle["uid"] for bundle in proposal["bundles"]]
    assert all(uid.startswith("b_") for uid in first_uids) and len(set(first_uids)) == 2

    models.init_db()  # again: nothing changes
    proposal = json.loads(_query("SELECT proposal_data FROM jobs WHERE id=?", (job_id,))[0]["proposal_data"])
    assert [bundle["uid"] for bundle in proposal["bundles"]] == first_uids
    # Rows added some other way still get an identity.
    _execute("INSERT INTO job_materials (job_id, item_code) VALUES (?, 'T-2')", (job_id,))
    assert all(row["uid"] for row in _query("SELECT uid FROM job_materials"))


# ── Materials ─────────────────────────────────────────────────────────────────
def test_save_materials_keeps_uids_and_versions_only_changed_rows():
    _fresh_db()
    job_id = _make_job()
    with _as_user("alice"), job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
        saved = models.save_materials(job_id, [_material("T-1"), _material("T-2", uid="mclient01")], conn=tx.conn)
    assert saved.uids[1] == "mclient01" and saved.uids[0].startswith("m") and len(saved) == 2
    assert sorted(saved.diff["added"]) == sorted(saved.uids)
    rows = {row["item_code"]: row for row in _query("SELECT * FROM job_materials")}
    assert rows["T-1"]["row_version"] == 1 and rows["T-1"]["updated_by"] == "alice"

    with _as_user("bob"), job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
        again = models.save_materials(job_id, [
            {**rows["T-1"], "unit_price": 2.5},
            {**rows["T-2"]},
            _material("T-3", uid="mclient01"),  # a uid this bid already uses: gets its own
        ], conn=tx.conn)
    assert again.uids[:2] == saved.uids and again.uids[2] not in saved.uids
    assert again.diff["updated"] == {saved.uids[0]: ["unit_price"]}
    rows = {row["item_code"]: row for row in _query("SELECT * FROM job_materials")}
    assert rows["T-1"]["row_version"] == 2 and rows["T-1"]["updated_by"] == "bob"
    assert rows["T-2"]["row_version"] == 1 and rows["T-2"]["updated_by"] == "alice"
    entry = _last_entry("materials.update")
    paths = {change["path"] for change in entry["changes"]}
    assert f"/materials/{saved.uids[0]}/unit_price" in paths
    assert not any("row_version" in path or "updated_" in path for path in paths)

    # A row sent with only its uid (no id) still updates that line.
    with job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
        by_uid = models.save_materials(job_id, [
            {**{k: v for k, v in rows["T-1"].items() if k != "id"}, "unit_price": 2.75},
            rows["T-2"], rows["T-3"],
        ], conn=tx.conn)
    assert by_uid[0] == rows["T-1"]["id"] and by_uid.diff["updated"] == {saved.uids[0]: ["unit_price"]}


# ── Sundry and labor lines ────────────────────────────────────────────────────
def test_sundry_and_labor_saves_update_rows_in_place():
    _fresh_db()
    job_id = _make_job()
    with job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
        [material_id] = models.save_materials(job_id, [_material("T-1")], conn=tx.conn)
    sundries = [
        {"material_id": material_id, "sundry_name": "thinset", "qty": 4, "unit": "bag", "unit_price": 15, "extended_cost": 60},
        {"material_id": material_id, "sundry_name": "grout", "qty": 2, "unit": "bag", "unit_price": 30, "extended_cost": 60},
    ]
    labor = [{"material_id": material_id, "labor_description": "Install tile", "qty": 100, "unit": "SF", "rate": 3, "extended_cost": 300}]
    with job_write(job_id, action="bid.calculate", scopes=("sundries", "labor")) as tx:
        models.save_sundries(job_id, sundries, conn=tx.conn)
        models.save_labor(job_id, labor, conn=tx.conn)
    ids_before = {row["line_key"]: row["id"] for row in _query("SELECT id, line_key FROM job_sundries")}

    sundries[0] = {**sundries[0], "qty": 5, "extended_cost": 75}
    sundries.append({"material_id": material_id, "sundry_name": "sealer", "qty": 1, "unit": "gal", "unit_price": 20, "extended_cost": 20})
    del sundries[1]  # grout goes
    labor[0] = {**labor[0], "rate": 3.25, "extended_cost": 325}
    with job_write(job_id, action="bid.calculate", scopes=("sundries", "labor")) as tx:
        sundry_diff = models.save_sundries(job_id, sundries, conn=tx.conn)
        models.save_labor(job_id, labor, conn=tx.conn)
    uid = _query("SELECT uid FROM job_materials WHERE id=?", (material_id,))[0]["uid"]
    key = f"{uid}|thinset"
    assert sundry_diff == {"added": [f"{uid}|sealer"], "updated": {key: ["qty", "extended_cost"]},
                           "removed": [f"{uid}|grout"]}
    assert _query("SELECT id FROM job_sundries WHERE line_key=?", (key,))[0]["id"] == ids_before[key]
    changes = {change["path"]: change for change in _last_entry("bid.calculate")["changes"]}
    assert changes[f"/sundries/{key}/qty"]["op"] == "replace"
    assert (changes[f"/sundries/{key}/qty"]["before"], changes[f"/sundries/{key}/qty"]["after"]) == (4, 5)
    assert changes[f"/sundries/{uid}|grout"]["op"] == "remove"
    assert changes[f"/sundries/{uid}|sealer"]["op"] == "add"
    assert changes[f"/labor/{uid}|install tile/rate"]["after"] == 3.25
    assert f"/sundries/{key}" not in changes  # the line wasn't removed and re-added


# ── Compare-and-swap patches ─────────────────────────────────────────────────
def test_patch_is_skipped_when_the_line_changed_meanwhile():
    _fresh_db()
    job_id = _make_job()
    with job_write(job_id, action="materials.update", scopes=("materials",)) as tx:
        models.save_materials(job_id, [_material("T-1", unit_price=0, extended_cost=0),
                                       _material("T-2", unit_price=0, extended_cost=0)], conn=tx.conn)
    read = _query("SELECT * FROM job_materials ORDER BY id")   # what the slow step read
    patches = [material_patch(row, {"unit_price": 9.0, "price_source": "ai_estimate"}, normalize=True) for row in read]
    with job_write(job_id, action="materials.update", scopes=("materials",)) as tx:  # someone types a price
        rows = _query("SELECT * FROM job_materials ORDER BY id")
        rows[0]["unit_price"], rows[0]["price_source"] = 4.0, "manual"
        models.save_materials(job_id, rows, conn=tx.conn)
    with job_write(job_id, action="materials.ai_estimate", scopes=("materials",)) as tx:
        result = apply_material_patches(tx, patches)
    assert [conflict["item_code"] for conflict in result["conflicts"]] == ["T-1"]
    assert result["conflicts"][0]["fields"] == ["unit_price", "price_source"]
    assert [item["item_code"] for item in result["applied"]] == ["T-2"]
    prices = {row["item_code"]: (row["unit_price"], row["extended_cost"]) for row in _query("SELECT * FROM job_materials")}
    assert prices == {"T-1": (4.0, 0.0), "T-2": (9.0, 990.0)}
    entry = _last_entry("materials.ai_estimate")
    assert entry["extra"]["conflicts"][0]["item_code"] == "T-1"


# ── Through the API ───────────────────────────────────────────────────────────
def _api_clients():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app):
        pass  # startup: tables and seeds
    models.create_user("alice", "4321", "Alice Estimator")
    models.create_user("bob", "1234", "Bob Builder")
    alice, bob = TestClient(main.app), TestClient(main.app)
    alice.__enter__()
    bob.__enter__()
    assert alice.post("/api/auth/login", json={"username": "alice", "pin": "4321"}).status_code == 200
    assert bob.post("/api/auth/login", json={"username": "bob", "pin": "1234"}).status_code == 200
    return main, alice, bob


def _close(*clients):
    for client in clients:
        client.__exit__(None, None, None)


@contextmanager
def _patched(module, **values):
    saved = {name: getattr(module, name) for name in values}
    for name, value in values.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


def _put_materials(client, job_id, rows):
    response = client.put(f"/api/jobs/{job_id}/materials", json={"materials": rows})
    assert response.status_code == 200, response.text
    return response.json()["materials"]


def test_api_auto_match_keeps_a_price_typed_meanwhile():
    _fresh_db()
    main, alice, bob = _api_clients()
    try:
        job_id = alice.post("/api/jobs", json={"project_name": "Quote Plaza"}).json()["id"]
        rows = _put_materials(alice, job_id, [
            _material("CPT-1", description="Interface - Woven Gradience - WG100", material_type="cpt_tile",
                      unit="SY", unit_price=0, extended_cost=0),
            _material("CPT-2", description="Interface - Level Set - LS450", material_type="cpt_tile",
                      unit="SY", unit_price=0, extended_cost=0),
        ])
        models.save_quotes(job_id, [
            {"product_name": "Woven Gradience WG100", "vendor": "Interface", "unit_price": 25.0, "unit": "SY"},
            {"product_name": "Level Set LS450", "vendor": "Interface", "unit_price": 31.0, "unit": "SY"},
        ])
        quote_id = _query("SELECT id FROM job_quotes WHERE job_id=? ORDER BY id", (job_id,))[0]["id"]
        original = main._match_quotes_to_materials

        def match_then_someone_types(job, products):
            found = original(job, products)
            # Bob types a price on CPT-1 while the matching was running.
            current = alice.get(f"/api/jobs/{job_id}").json()["materials"]
            current[0] = {**current[0], "unit_price": 27.5, "price_source": "manual"}
            _put_materials(bob, job_id, current)
            return found

        with _patched(main, _match_quotes_to_materials=match_then_someone_types):
            response = alice.put(f"/api/quotes/{quote_id}", json={"unit_price": 25.0})
        assert response.status_code == 200, response.text
        conflicts = response.json()["conflicts"]
        assert [conflict["item_code"] for conflict in conflicts] == ["CPT-1"]
        assert "unit price" in conflicts[0]["message"]
        prices = {row["item_code"]: row for row in alice.get(f"/api/jobs/{job_id}").json()["materials"]}
        assert prices["CPT-1"]["unit_price"] == 27.5 and prices["CPT-1"]["price_source"] == "manual"
        assert prices["CPT-2"]["unit_price"] == 31.0 and prices["CPT-2"]["price_source"] == "vendor_quote"
        assert prices["CPT-1"]["uid"] == rows[0]["uid"]
        entry = _last_entry("quotes.auto_match")
        assert entry["extra"]["conflicts"][0]["item_code"] == "CPT-1" and "skipped" in entry["summary"]
        assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE action='unaudited_write'")[0]["n"] == 0
    finally:
        _close(alice, bob)


def test_api_estimate_price_by_id_and_by_position():
    _fresh_db()
    main, alice, bob = _api_clients()
    try:
        job_id = alice.post("/api/jobs", json={"project_name": "Estimate Court"}).json()["id"]
        rows = _put_materials(alice, job_id, [
            _material("T-1", unit_price=0, extended_cost=0),
            _material("T-2", unit_price=0, extended_cost=0),
        ])
        answer = {"estimated_price": 12.5, "confidence": 0.9, "reasoning": "typical tile"}
        with _patched(main, get_provider_info=lambda key: {"available": True},
                      chat_complete=lambda **kwargs: json.dumps(answer)):
            by_id = alice.post(f"/api/jobs/{job_id}/materials/by-id/{rows[1]['id']}/estimate-price")
            assert by_id.status_code == 200, by_id.text
            assert by_id.json()["material"]["item_code"] == "T-2"
            assert by_id.json()["material"]["unit_price"] == 12.5
            assert by_id.json()["material"]["extended_cost"] == 1375.0
            assert alice.post(f"/api/jobs/{job_id}/materials/by-id/999999/estimate-price").status_code == 404

            answer["estimated_price"] = 8.0
            by_position = alice.post(f"/api/jobs/{job_id}/materials/0/estimate-price")
            assert by_position.status_code == 200 and by_position.json()["material"]["item_code"] == "T-1"

            def answer_after_bob_edits(**kwargs):
                current = alice.get(f"/api/jobs/{job_id}").json()["materials"]
                current[0] = {**current[0], "unit_price": 7.0, "price_source": "manual"}
                _put_materials(bob, job_id, current)
                return json.dumps({"estimated_price": 99.0, "confidence": 0.5, "reasoning": "late"})

            with _patched(main, chat_complete=answer_after_bob_edits):
                late = alice.post(f"/api/jobs/{job_id}/materials/by-id/{rows[0]['id']}/estimate-price")
        assert late.status_code == 409 and "while this was running" in late.json()["detail"], late.text
        prices = {row["item_code"]: row["unit_price"] for row in alice.get(f"/api/jobs/{job_id}").json()["materials"]}
        assert prices == {"T-1": 7.0, "T-2": 12.5}
        entry = _last_entry("materials.ai_estimate")
        assert "not saved" in entry["summary"] and entry["extra"]["conflicts"][0]["item_code"] == "T-1"
    finally:
        _close(alice, bob)


def test_api_detect_vendors_skips_lines_changed_meanwhile():
    _fresh_db()
    main, alice, bob = _api_clients()
    try:
        job_id = alice.post("/api/jobs", json={"project_name": "Vendor Row"}).json()["id"]
        _put_materials(alice, job_id, [
            _material("F-1", description="(Standard) - F-1 - Daltile - Volume 1.0 - Gray"),
            _material("F-2", description="(Standard) - F-2 - Daltile - Volume 1.0 - White"),
        ])

        def ai_after_bob_edits(**kwargs):
            # Bob sets F-1's vendor himself while the AI is looking.
            current = alice.get(f"/api/jobs/{job_id}").json()["materials"]
            current[0] = {**current[0], "vendor": "Bob's Tile Co"}
            _put_materials(bob, job_id, current)
            return json.dumps({"results": [
                {"index": 0, "vendor": "Daltile", "evidence": "Daltile"},
                {"index": 1, "vendor": "Daltile", "evidence": "Daltile"},
            ]})

        with _patched(main, QUOTE_EMAILS_ENABLED=True, get_provider_info=lambda key: {"available": True},
                      chat_complete=ai_after_bob_edits):
            response = alice.post(f"/api/jobs/{job_id}/detect-vendors")
        assert response.status_code == 200, response.text
        assert [conflict["item_code"] for conflict in response.json()["conflicts"]] == ["F-1"]
        vendors = {row["item_code"]: row["vendor"] for row in alice.get(f"/api/jobs/{job_id}").json()["materials"]}
        assert vendors == {"F-1": "Bob's Tile Co", "F-2": "Daltile"}
    finally:
        _close(alice, bob)


def test_api_rfms_reupload_merges_onto_lines_edited_meanwhile():
    _fresh_db()
    main, alice, bob = _api_clients()
    try:
        job_id = alice.post("/api/jobs", json={"project_name": "Takeoff Terrace"}).json()["id"]
        [saved] = _put_materials(alice, job_id, [
            _material("CPT-1", description="Carpet tile A", material_type="cpt_tile", unit="SY",
                      installed_qty=100, waste_pct=0, order_qty=100, unit_price=20, extended_cost=2000,
                      price_source="manual"),
        ])

        def parse_while_bob_types(path):
            # Bob types a new price on the saved line while the file is being read.
            current = alice.get(f"/api/jobs/{job_id}").json()["materials"]
            current[0] = {**current[0], "unit_price": 22.0, "price_source": "manual", "order_qty": None}
            _put_materials(bob, job_id, current)
            return {"job_info": {}, "materials": [
                {"item_code": "CPT-1", "description": "Carpet tile A", "material_type": "cpt_tile", "qty": 150, "unit": "SY"},
                {"item_code": "CPT-2", "description": "Carpet tile B", "material_type": "cpt_tile", "qty": 50, "unit": "SY"},
            ]}

        with _patched(main, parse_rfms=parse_while_bob_types):
            response = alice.post(f"/api/jobs/{job_id}/upload-rfms",
                                  files={"files": ("units.xlsx", b"not really a workbook", "application/octet-stream")})
        assert response.status_code == 200, response.text
        lines = {row["item_code"]: row for row in alice.get(f"/api/jobs/{job_id}").json()["materials"]}
        assert lines["CPT-1"]["unit_price"] == 22.0          # Bob's price survived the re-upload
        assert lines["CPT-1"]["installed_qty"] == 150         # the new takeoff quantity
        assert lines["CPT-1"]["uid"] == saved["uid"] and lines["CPT-1"]["id"] == saved["id"]
        assert lines["CPT-2"]["uid"] and lines["CPT-2"]["uid"] != saved["uid"]
        returned = {row["item_code"]: row["uid"] for row in response.json()["materials"]}
        assert returned == {code: row["uid"] for code, row in lines.items()}
    finally:
        _close(alice, bob)


def test_api_proposal_bundle_uids_survive_saves_and_regenerate():
    _fresh_db()
    main, alice, bob = _api_clients()
    try:
        job_id = alice.post("/api/jobs", json={"project_name": "Bundle Heights"}).json()["id"]
        _put_materials(alice, job_id, [
            _material("T-1", description="Bath floor tile 12x24"),
            _material("LVT-1", description="Unit LVT plank", material_type="unit_lvt"),
        ])
        generated = alice.post(f"/api/jobs/{job_id}/proposal/generate")
        assert generated.status_code == 200, generated.text
        proposal = generated.json()
        uids = [bundle["uid"] for bundle in proposal["bundles"]]
        assert uids and all(uid.startswith("b_") for uid in uids) and len(set(uids)) == len(uids)
        saved = json.loads(_query("SELECT proposal_data FROM jobs WHERE id=?", (job_id,))[0]["proposal_data"])
        assert [bundle["uid"] for bundle in saved["bundles"]] == uids

        def save(bundles):
            body = {**proposal, "bundles": bundles}
            response = alice.post(f"/api/jobs/{job_id}/proposal/bundles/save", json=body)
            assert response.status_code == 200, response.text
            return [bundle["uid"] for bundle in response.json()["proposal_data"]["bundles"]]

        # A client that echoes uids, one that doesn't (old tab), a rename.
        assert save(proposal["bundles"]) == uids
        assert save([{k: v for k, v in bundle.items() if k != "uid"} for bundle in proposal["bundles"]]) == uids
        renamed = [dict(bundle) for bundle in proposal["bundles"]]
        renamed[0]["description_text"] = "Edited description"
        assert save(renamed) == uids
        entry = _last_entry("proposal.save")
        assert any(change["path"] == f"/proposal/bundles/{uids[0]}/description_text" for change in entry["changes"])

        regenerated = alice.post(f"/api/jobs/{job_id}/proposal/generate")
        assert regenerated.status_code == 200, regenerated.text
        assert [bundle["uid"] for bundle in regenerated.json()["bundles"]] == uids
        assert regenerated.json()["bundles"][0]["description_text"] == "Edited description"
    finally:
        _close(alice, bob)


def test_api_calculate_twice_shows_changed_sundry_fields():
    _fresh_db()
    main, alice, bob = _api_clients()
    try:
        job_id = alice.post("/api/jobs", json={"project_name": "Calc Commons"}).json()["id"]
        rows = _put_materials(alice, job_id, [_material("T-1", installed_qty=1000, order_qty=1100)])
        assert alice.post(f"/api/jobs/{job_id}/calculate").status_code == 200
        ids = {row["line_key"]: row["id"] for row in _query("SELECT id, line_key FROM job_sundries")}
        rows[0] = {**rows[0], "installed_qty": 2000, "order_qty": 2200}
        _put_materials(alice, job_id, rows)
        assert alice.post(f"/api/jobs/{job_id}/calculate").status_code == 200
        assert {row["line_key"]: row["id"] for row in _query("SELECT id, line_key FROM job_sundries")} == ids
        changes = _last_entry("bid.calculate")["changes"]
        assert changes and all(change["op"] == "replace" for change in changes)
        assert any(change["path"] == f"/sundries/{rows[0]['uid']}|thinset/qty" for change in changes)
    finally:
        _close(alice, bob)


def test_api_catalog_uploads_are_keyed_upserts():
    _fresh_db()
    main, alice, bob = _api_clients()
    try:
        entries = [
            {"product_name": "Grout", "vendor": "Custom", "unit": "bag", "unit_price": 30},
            {"product_name": "Thinset", "vendor": "Custom", "unit": "bag", "unit_price": 15},
        ]
        assert alice.post("/api/price-list/bulk", json={"entries": entries}).status_code == 200
        ids = {row["product_name"]: row["id"] for row in _query("SELECT * FROM price_list")}
        entries = [
            {"product_name": "grout", "vendor": "Custom", "unit": "BAG", "unit_price": 32},  # same key
            {"product_name": "Sealer", "vendor": "Custom", "unit": "gal", "unit_price": 20},
        ]
        assert alice.post("/api/price-list/bulk", json={"entries": entries}).status_code == 200
        rows = {row["id"]: row for row in _query("SELECT * FROM price_list")}
        assert ids["Grout"] in rows and rows[ids["Grout"]]["unit_price"] == 32 and ids["Thinset"] not in rows
        changes = {change["path"]: change for change in _last_entry("price_list.replace")["changes"]}
        assert changes[f"/entries/{ids['Grout']}/unit_price"]["after"] == 32
        assert changes[f"/entries/{ids['Thinset']}"]["op"] == "remove"
        assert any(change["op"] == "add" and change["after"]["product_name"] == "Sealer" for change in changes.values())

        book = {"vendor": "Acme", "discount_pct": 0.5,
                "items": [{"product_line": "EDGE", "item_no": "E 1", "list_price": 10, "net_price": 5},
                          {"product_line": "EDGE", "item_no": "E 2", "list_price": 12, "net_price": 6}]}
        assert alice.post("/api/price-book/import", json=book).status_code == 200
        book_ids = {row["item_no"]: row["id"] for row in _query("SELECT * FROM price_book_items WHERE vendor='Acme'")}
        book["items"][1]["net_price"] = 6.5
        assert alice.post("/api/price-book/import", json=book).status_code == 200
        assert {row["item_no"]: row["id"] for row in _query("SELECT * FROM price_book_items WHERE vendor='Acme'")} == book_ids
        changes = _last_entry("price_book.import")["changes"]
        assert [change["path"] for change in changes] == [f"/entries/{book_ids['E 2']}/net_price"]

        with entity_write("labor_catalog", "all", lambda conn, _id: {"entries": [dict(r) for r in conn.execute(
                "SELECT * FROM labor_catalog ORDER BY id")]}, "labor_catalog.upload") as tx:
            models.save_labor_catalog_entries([{"labor_type": "Tile", "description": "Floor", "unit": "SF", "cost": 3}],
                                              conn=tx.conn)
        [first] = _query("SELECT * FROM labor_catalog")
        with entity_write("labor_catalog", "all", lambda conn, _id: None, "labor_catalog.upload") as tx:
            counts = models.save_labor_catalog_entries(
                [{"labor_type": "Tile", "description": "Floor", "unit": "SF", "cost": 3.5}], conn=tx.conn)
        assert counts == {"added": 0, "updated": 1, "removed": 0, "unchanged": 0}
        assert _query("SELECT id, cost FROM labor_catalog") == [{"id": first["id"], "cost": 3.5}]
        assert _query("SELECT COUNT(*) AS n FROM audit_log WHERE action='unaudited_write'")[0]["n"] == 0
    finally:
        _close(alice, bob)


if __name__ == "__main__":
    failures = 0
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except Exception as err:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            failures += 1
            print(f"FAIL  {name}: {err!r}")
    print(f"\n{len(tests) - failures} passed, {failures} failed")
    sys.exit(1 if failures else 0)
