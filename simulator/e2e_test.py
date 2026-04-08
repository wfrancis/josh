#!/usr/bin/env python3
"""
SI Bid Tool — Automated E2E Simulator Test
Runs N iterations of the full round-trip:
  Bid Tool → SMTP → Vendor Simulator → AI Reply → Bid Tool auto-match

Requires all 3 services running:
  - Bid Tool on localhost:8000
  - Vendor Simulator on localhost:8100
  - SMTP Relay on localhost:2525
"""

import json
import sys
import time
import httpx

BID_TOOL = "http://localhost:8000"
VENDOR_SIM = "http://localhost:8100"
TIMEOUT = 120.0

# Test job templates — each iteration uses different materials/vendors
TEST_JOBS = [
    {
        "project_name": "E2E Test #1 — Medical Office Build-Out",
        "client_name": "HealthCorp",
        "materials": [
            {"id": 1, "description": "Shaw Contract Carpet Tile - Configure, Color: Shale, 24x24", "installed_qty": 3000, "unit": "SF", "area_name": "Waiting Room", "material_type": "carpet_tile"},
            {"id": 2, "description": "Daltile Porcelain Tile - Keystones D049, Color: Arctic White, 12x12", "installed_qty": 600, "unit": "SF", "area_name": "Exam Rooms", "material_type": "tile"},
        ],
        "vendors": [
            {"name": "Shaw Contract", "contact_name": "Lisa Park", "contact_email": "lisa.park@shawcontract.com"},
            {"name": "Daltile", "contact_name": "Sarah Chen", "contact_email": "sarah.chen@daltile.com"},
        ],
    },
    {
        "project_name": "E2E Test #2 — Hotel Lobby Renovation",
        "client_name": "Grand Hotels",
        "materials": [
            {"id": 1, "description": "Interface Carpet Tile - Human Nature HN830, Color: Granite, 24x24", "installed_qty": 4000, "unit": "SF", "area_name": "Lobby", "material_type": "carpet_tile"},
            {"id": 2, "description": "Johnsonite Rubber Wall Base - 6 inch Toeless, Color: Black #10", "installed_qty": 800, "unit": "LF", "area_name": "Lobby", "material_type": "base"},
        ],
        "vendors": [
            {"name": "Interface", "contact_name": "Mike Johnson", "contact_email": "mike.johnson@interface.com"},
            {"name": "Johnsonite", "contact_name": "Tom Williams", "contact_email": "tom.williams@johnsonite.com"},
        ],
    },
    {
        "project_name": "E2E Test #3 — Elementary School Corridors",
        "client_name": "USD 501",
        "materials": [
            {"id": 1, "description": "Mannington LVT - Amtico Spacia, Color: Limed Wood Natural, 12x18", "installed_qty": 5000, "unit": "SF", "area_name": "Corridors", "material_type": "lvt"},
            {"id": 2, "description": "Armstrong VCT - Standard Excelon, Color: Charcoal, 12x12", "installed_qty": 2000, "unit": "SF", "area_name": "Classrooms", "material_type": "vct"},
            {"id": 3, "description": "Roppe Rubber Wall Base - 4 inch Cove, Color: Black #100", "installed_qty": 1200, "unit": "LF", "area_name": "Corridors", "material_type": "base"},
        ],
        "vendors": [
            {"name": "Mannington", "contact_name": "Amy Roberts", "contact_email": "amy.roberts@mannington.com"},
            {"name": "Armstrong", "contact_name": "Dave Miller", "contact_email": "dave.miller@armstrong.com"},
            {"name": "Roppe", "contact_name": "Karen White", "contact_email": "karen.white@roppe.com"},
        ],
    },
    {
        "project_name": "E2E Test #4 — Law Firm 22nd Floor",
        "client_name": "Morrison & Associates",
        "materials": [
            {"id": 1, "description": "Patcraft Carpet Tile - Accents, Color: Midnight, 24x24", "installed_qty": 2800, "unit": "SF", "area_name": "Partner Offices", "material_type": "carpet_tile"},
            {"id": 2, "description": "Daltile Marble Tile - Berkshire Crema, 12x24 Polished", "installed_qty": 400, "unit": "SF", "area_name": "Reception", "material_type": "tile"},
        ],
        "vendors": [
            {"name": "Patcraft", "contact_name": "Jim Brown", "contact_email": "jim.brown@patcraft.com"},
            {"name": "Daltile", "contact_name": "Sarah Chen", "contact_email": "sarah.chen@daltile.com"},
        ],
    },
    {
        "project_name": "E2E Test #5 — Fitness Center Remodel",
        "client_name": "Peak Athletics",
        "materials": [
            {"id": 1, "description": "Ecore Athletic Rubber Flooring - Everlast II, Color: Charcoal, 4mm Roll", "installed_qty": 6000, "unit": "SF", "area_name": "Weight Room", "material_type": "sheet_rubber"},
            {"id": 2, "description": "Interface Carpet Tile - Equal Measure EM551, Color: Cobblestone, 24x24", "installed_qty": 1500, "unit": "SF", "area_name": "Lobby", "material_type": "carpet_tile"},
            {"id": 3, "description": "Johnsonite Rubber Wall Base - 4 inch Toeless, Color: Charcoal #48", "installed_qty": 500, "unit": "LF", "area_name": "All Areas", "material_type": "base"},
        ],
        "vendors": [
            {"name": "Ecore", "contact_name": "Pat Garcia", "contact_email": "pat.garcia@ecore.com"},
            {"name": "Interface", "contact_name": "Mike Johnson", "contact_email": "mike.johnson@interface.com"},
            {"name": "Johnsonite", "contact_name": "Tom Williams", "contact_email": "tom.williams@johnsonite.com"},
        ],
    },
]


def log(msg):
    print(f"  {msg}", flush=True)


def check_services():
    """Verify all 3 services are reachable."""
    try:
        r = httpx.get(f"{BID_TOOL}/api/settings", timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"FAIL: Bid Tool not reachable at {BID_TOOL}: {e}")
        return False
    try:
        r = httpx.get(f"{VENDOR_SIM}/api/status", timeout=5)
        r.raise_for_status()
        data = r.json()
        if not data.get("ai_available"):
            print(f"FAIL: Vendor Simulator has no AI provider configured")
            return False
    except Exception as e:
        print(f"FAIL: Vendor Simulator not reachable at {VENDOR_SIM}: {e}")
        return False
    return True


def ensure_vendor(v):
    """Create vendor if it doesn't exist (ignore duplicate errors)."""
    try:
        httpx.post(f"{BID_TOOL}/api/vendors",
                    json={"name": v["name"], "contact_name": v["contact_name"],
                          "contact_email": v["contact_email"]},
                    timeout=10)
    except Exception:
        pass


def run_iteration(idx, job_def):
    """Run one full E2E iteration. Returns (success, details_dict)."""
    label = f"[Iteration {idx+1}] {job_def['project_name']}"
    print(f"\n{'='*70}")
    print(f"{label}")
    print(f"{'='*70}")

    result = {
        "iteration": idx + 1,
        "project": job_def["project_name"],
        "materials": len(job_def["materials"]),
        "vendors": len(job_def["vendors"]),
        "steps": {},
    }

    # Step 1: Create job
    log("Creating job...")
    r = httpx.post(f"{BID_TOOL}/api/jobs",
                   json={"project_name": job_def["project_name"],
                         "client_name": job_def["client_name"]},
                   timeout=10)
    if r.status_code != 200:
        log(f"FAIL: Create job returned {r.status_code}: {r.text[:200]}")
        result["steps"]["create_job"] = "FAIL"
        return False, result
    job = r.json()
    job_id = job["id"]
    job_slug = job.get("slug", str(job_id))
    result["steps"]["create_job"] = f"OK (id={job_id})"
    log(f"Job #{job_id} created")

    # Step 2: Add materials
    log(f"Adding {len(job_def['materials'])} materials...")
    r = httpx.put(f"{BID_TOOL}/api/jobs/{job_id}/materials",
                  json={"materials": job_def["materials"]},
                  timeout=10)
    if r.status_code != 200:
        log(f"FAIL: Add materials returned {r.status_code}")
        result["steps"]["add_materials"] = "FAIL"
        return False, result
    result["steps"]["add_materials"] = f"OK ({len(job_def['materials'])} items)"

    # Step 3: Ensure vendors exist
    for v in job_def["vendors"]:
        ensure_vendor(v)
    result["steps"]["vendors"] = f"OK ({len(job_def['vendors'])} vendors)"

    # Step 4: Detect vendors via AI
    log("Detecting vendors (AI)...")
    r = httpx.post(f"{BID_TOOL}/api/jobs/{job_id}/detect-vendors", timeout=TIMEOUT)
    if r.status_code == 200:
        det = r.json()
        result["steps"]["detect_vendors"] = f"OK ({len(det.get('vendor_groups', []))} groups)"
    else:
        log(f"Vendor detection returned {r.status_code}, continuing with manual send...")
        result["steps"]["detect_vendors"] = "SKIPPED"

    # Step 5: Generate quote text and send for each vendor
    log("Generating and sending quote emails...")
    sent_count = 0
    for v in job_def["vendors"]:
        # Generate quote text
        r = httpx.post(f"{BID_TOOL}/api/jobs/{job_id}/generate-quote-text",
                       json={"vendor_name": v["name"],
                             "materials": [m["description"] for m in job_def["materials"]
                                           if v["name"].lower().split()[0] in m["description"].lower()]
                             or [m["description"] for m in job_def["materials"][:2]]},
                       timeout=TIMEOUT)
        quote_text = ""
        if r.status_code == 200:
            quote_text = r.json().get("text", f"Requesting pricing for {v['name']} products.")
        else:
            quote_text = f"Please provide pricing for our project: {job_def['project_name']}."

        # Send email via test mode
        mat_ids = [m["id"] for m in job_def["materials"]]
        r = httpx.post(f"{BID_TOOL}/api/jobs/{job_id}/send-quote-email",
                       json={"vendor_name": v["name"],
                             "vendor_email": v["contact_email"],
                             "subject": f"Request for Pricing — {job_def['project_name']}",
                             "body": quote_text,
                             "material_ids": mat_ids},
                       timeout=30)
        if r.status_code == 200:
            sent_count += 1
            log(f"  Sent to {v['name']} ({v['contact_email']})")
        else:
            log(f"  FAIL sending to {v['name']}: {r.status_code} {r.text[:100]}")

    result["steps"]["send_emails"] = f"OK ({sent_count}/{len(job_def['vendors'])} sent)"
    if sent_count == 0:
        return False, result

    # Step 6: Wait for vendor simulator to pick up .eml files
    log("Waiting for Vendor Simulator to pick up emails...")
    time.sleep(5)

    # Step 7: Vendor simulator Reply All (now async — poll for completion)
    log("Triggering Vendor Simulator Reply All...")
    r = httpx.post(f"{VENDOR_SIM}/api/requests/reply-all", timeout=30)
    if r.status_code != 200:
        log(f"  FAIL: Reply All returned {r.status_code}: {r.text[:200]}")
        result["steps"]["vendor_reply"] = f"FAIL ({r.status_code})"
        return False, result

    reply_data = r.json()
    total_to_process = reply_data.get("total", 0)
    if total_to_process == 0:
        log("  No pending requests to reply to")
        result["steps"]["vendor_reply"] = "FAIL (0 pending)"
        return False, result

    # Poll until reply-all completes (up to 3 min)
    log(f"  Processing {total_to_process} replies...")
    for _ in range(90):  # 90 * 2s = 3 min max
        time.sleep(2)
        try:
            sr = httpx.get(f"{VENDOR_SIM}/api/requests/reply-all/status", timeout=5)
            ps = sr.json()
            if not ps.get("running", False):
                break
            log(f"  ... {ps['processed']}/{ps['total']}")
        except Exception:
            pass

    try:
        sr = httpx.get(f"{VENDOR_SIM}/api/requests/reply-all/status", timeout=5)
        ps = sr.json()
    except Exception as e:
        log(f"  FAIL: Could not fetch reply-all status: {e}")
        result["steps"]["vendor_reply"] = f"FAIL (status fetch: {e})"
        return False, result
    result["steps"]["vendor_reply"] = f"OK ({ps['processed']} sent, {ps['errors']} errors)"
    log(f"  {ps['processed']} replies sent, {ps['errors']} errors")

    # Step 8: Wait for SimFolderWatcher to pick up and parse replies (AI parsing is slow)
    log("Waiting for Bid Tool to process replies...")
    time.sleep(15)

    # Step 9: Verify — poll job API until quotes appear (up to 60s)
    log("Verifying quotes and pricing...")
    quotes = []
    for attempt in range(12):  # 12 * 5s = 60s max
        r = httpx.get(f"{BID_TOOL}/api/jobs/{job_id}", timeout=10)
        if r.status_code == 200:
            job_data = r.json()
            quotes = job_data.get("quotes", [])
            if len(quotes) > 0:
                break
        time.sleep(5)

    if r.status_code == 200:
        materials = job_data.get("materials", [])
        priced = sum(1 for m in materials if m.get("unit_price") and m["unit_price"] > 0)
        total = sum(m.get("unit_price", 0) * m.get("installed_qty", 0) for m in materials)
        result["steps"]["quotes_received"] = f"{len(quotes)} quotes parsed"
        result["steps"]["auto_matched"] = f"{priced}/{len(materials)} materials priced (${total:,.2f})"
        result["quotes_received"] = len(quotes)
        result["priced"] = priced
        result["total_materials"] = len(materials)
        result["material_total"] = total
        log(f"  {len(quotes)} quotes received, {priced}/{len(materials)} auto-matched — ${total:,.2f}")
    else:
        result["steps"]["quotes_received"] = f"FAIL (job load returned {r.status_code})"
        return False, result

    # Success = quotes were received (full pipeline completed)
    success = len(quotes) > 0
    result["success"] = success
    return success, result


def main():
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    print("=" * 70)
    print(f"  SI Bid Tool — E2E Simulator Test ({iterations} iterations)")
    print("=" * 70)

    # Pre-flight
    print("\nPre-flight checks...")
    if not check_services():
        sys.exit(1)
    print("  All services OK\n")

    # Ensure test mode is enabled
    httpx.post(f"{BID_TOOL}/api/settings",
               json={"vendor_quote_test_mode": "true"}, timeout=10)

    results = []
    for i in range(iterations):
        job_def = TEST_JOBS[i % len(TEST_JOBS)]
        # Make project name unique per run
        unique_def = {**job_def, "project_name": f"{job_def['project_name']} (run {i+1})"}
        success, result = run_iteration(i, unique_def)
        results.append(result)

    # Summary
    print(f"\n{'='*70}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*70}")
    passed = sum(1 for r in results if r.get("success"))
    failed = len(results) - passed
    for r in results:
        status = "PASS" if r.get("success") else "FAIL"
        priced = r.get("priced", 0)
        total_mat = r.get("total_materials", 0)
        total_val = r.get("material_total", 0)
        print(f"  [{status}] Iteration {r['iteration']}: {r['project']}")
        print(f"         {priced}/{total_mat} priced — ${total_val:,.2f}")
        for step, detail in r.get("steps", {}).items():
            print(f"         {step}: {detail}")
        print()

    print(f"  {passed} passed, {failed} failed out of {len(results)} iterations")
    print(f"{'='*70}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
