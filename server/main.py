"""
FastAPI application for the Standard Interiors Bid Tool.
"""

import csv
import io
import os
import shutil
import tempfile
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Body
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import (
    init_db, save_job, load_job, list_jobs, delete_job,
    save_materials, save_sundries, save_labor, save_bundles,
    save_quotes, delete_quotes, update_quote, get_quote_job_id, search_all,
    get_settings, save_settings,
    save_labor_catalog_entries, get_labor_catalog_entries,
    update_labor_catalog_entry, delete_labor_catalog_entry,
    clear_labor_catalog, clear_price_list,
    save_price_list_entries, add_price_list_entry, update_price_list_entry,
    delete_price_list_entry, get_price_list_entries,
    get_company_rate, save_company_rate, get_all_company_rates,
    get_or_create_vendor, save_vendor_prices_from_quotes,
    list_vendors, get_vendor, update_vendor, search_vendor_prices,
    create_vendor, delete_vendor,
    get_price_history, import_vendor_prices_csv,
    create_notification, get_notifications, mark_notification_read,
    log_activity, get_activity, add_comment, get_comments,
    create_quote_request, list_quote_requests, update_quote_request, delete_quote_request,
    _normalize_product, _get_conn,
)
from rfms_parser import parse_rfms, ai_merge_materials
from quote_parser import parse_quote_file, set_openai_config
from sundry_calc import calculate_sundries_for_materials
from labor_calc import calculate_labor_for_materials, load_labor_catalog, load_labor_catalog_from_pdf, get_labor_catalog
from bid_assembler import assemble_bid
from pdf_generator import generate_bid_pdf
from config import WASTE_FACTORS, SUNDRY_RULES, FREIGHT_RATES, LABOR_QTY_RULES, EXCLUSIONS_TEMPLATE
from email_agent import compose_quote_request, send_email, generate_quote_request_text
from inbox_monitor import InboxMonitor

# ── App Setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="SI Bid Tool", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _match_price_list(material: dict, price_list: list[dict]) -> dict | None:
    """Match a material to a price list entry by item_code, description, or material_type."""
    item_code = (material.get("item_code") or "").strip().lower()
    description = (material.get("description") or "").strip().lower()
    material_type = (material.get("material_type") or "").strip().lower()

    # Pass 1: exact item_code match against product_name
    if item_code and len(item_code) >= 3:
        for entry in price_list:
            entry_name = (entry.get("product_name") or "").strip().lower()
            if item_code == entry_name or item_code in entry_name or entry_name in item_code:
                return entry

    # Pass 2: description substring match
    if description and len(description) >= 5:
        for entry in price_list:
            entry_name = (entry.get("product_name") or "").strip().lower()
            if entry_name and len(entry_name) >= 5:
                if entry_name in description or description in entry_name:
                    return entry

    # Pass 3: material_type match (weakest, gives generic pricing)
    if material_type:
        for entry in price_list:
            if (entry.get("material_type") or "").strip().lower() == material_type:
                return entry

    return None


UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
PDF_DIR = os.path.join(os.path.dirname(__file__), "generated_pdfs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)


_inbox_monitor: InboxMonitor | None = None


def _start_inbox_monitor():
    """Start the inbox monitor if email automation is enabled."""
    global _inbox_monitor
    import json as _json
    settings = get_settings()
    if settings.get("email_automation_enabled") != "true":
        return
    try:
        config = _json.loads(settings.get("email_config", "{}"))
    except Exception:
        return
    imap_host = config.get("imap_host")
    imap_port = int(config.get("imap_port", 993))
    email_addr = config.get("email_address")
    email_pass = config.get("email_password")
    if not all([imap_host, email_addr, email_pass]):
        return

    def on_quote_received(temp_files, sender_email, subject):
        """Callback when inbox monitor detects a vendor response."""
        for fpath in temp_files:
            try:
                products = parse_quote_file(fpath)
                if not products:
                    continue
                # Try to find the job by project name from subject
                from models import search_all
                results = search_all(subject[:50])
                if results.get("jobs"):
                    job_id = results["jobs"][0]["id"]
                    save_quotes(job_id, products)
                    from models import _auto_match_quotes
                    matched = _auto_match_quotes(job_id)
                    save_vendor_prices_from_quotes(job_id, products)
                    vendor_name = products[0].get("vendor", sender_email)
                    create_notification(
                        job_id, "quote_received",
                        f"Quote received from {vendor_name} — {len(products)} products parsed, {matched} auto-matched"
                    )
            except Exception as e:
                print(f"[InboxMonitor] Error processing {fpath}: {e}")

    if _inbox_monitor and _inbox_monitor.is_running:
        _inbox_monitor.stop()

    _inbox_monitor = InboxMonitor(
        imap_config={
            "host": imap_host,
            "port": imap_port,
            "username": email_addr,
            "password": email_pass,
            "use_ssl": imap_port == 993,
        },
        on_quote_received=on_quote_received,
        poll_interval=300,
    )
    _inbox_monitor.start()
    print(f"[InboxMonitor] Started monitoring {email_addr}")


@app.on_event("startup")
def startup():
    init_db()
    _apply_openai_config()
    _seed_company_rates()
    _start_inbox_monitor()


# ── Pydantic Models ──────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    project_name: str
    gc_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    tax_rate: float = 0.0
    unit_count: int = 0
    salesperson: Optional[str] = None
    notes: Optional[str] = None
    architect: Optional[str] = None
    designer: Optional[str] = None


class MaterialUpdate(BaseModel):
    materials: list[dict]


class NotesUpdate(BaseModel):
    notes: str = ""


class BulkDeleteRequest(BaseModel):
    job_ids: list[int]


class SettingsUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    multi_pass_count: Optional[int] = None
    email_automation_enabled: Optional[str] = None
    email_config: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def api_list_jobs():
    """List all jobs."""
    return list_jobs()


@app.post("/api/jobs")
def api_create_job(job: JobCreate):
    """Create a new job."""
    job_id = save_job(job.model_dump())
    created = load_job(job_id)
    log_activity(job_id, "job_created", f"Job '{body.project_name}' created")
    return {"id": job_id, "slug": created.get("slug", ""), "message": "Job created"}


def _resolve_job_id(job_id: str) -> int:
    """Resolve a job_id string (could be slug or numeric ID) to a numeric DB id."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job["id"]


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    """Get job details by ID or slug."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Enrich materials with known prices from price list and vendor history
    applied = _enrich_known_prices(job)
    if applied:
        save_materials(job["id"], job["materials"])
    return job


def _enrich_known_prices(job: dict):
    """Add known_price field to each material from price list and vendor price history.
    Auto-applies prices to unpriced materials. Returns count of newly applied prices."""
    materials = job.get("materials", [])
    applied_count = 0
    if not materials:
        return 0
    price_list = get_price_list_entries()

    # Build a map of normalized vendor prices (latest price per product)
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT product_normalized, unit_price, vendor_name, unit,
                   MAX(created_at) as latest_date
            FROM vendor_prices
            WHERE unit_price > 0
            GROUP BY product_normalized
            ORDER BY latest_date DESC
        """).fetchall()
        vendor_map = {r["product_normalized"]: dict(r) for r in rows}
    finally:
        conn.close()

    for mat in materials:
        if mat.get("unit_price") and mat["unit_price"] > 0:
            continue  # already has a price, skip

        item_code = (mat.get("item_code") or "").strip().lower()
        description = (mat.get("description") or "").strip().lower()

        # Check price list first
        pl_match = _match_price_list(mat, price_list)
        if pl_match and pl_match.get("unit_price"):
            order_qty = mat.get("order_qty") or mat.get("installed_qty") or 1
            mat["known_price"] = round(pl_match["unit_price"] * order_qty, 2)
            mat["known_price_source"] = "price_list"
            mat["known_price_vendor"] = pl_match.get("vendor", "")
            # Auto-apply known price to material
            mat["unit_price"] = pl_match["unit_price"]
            mat["extended_cost"] = mat["known_price"]
            mat["price_source"] = "price_list"
            mat["vendor"] = pl_match.get("vendor", mat.get("vendor", ""))
            mat["quote_status"] = "quoted"
            applied_count += 1
            continue

        # Check vendor price history
        normalized = _normalize_product(item_code or description)
        if normalized and len(normalized) >= 3:
            for key, vp in vendor_map.items():
                if normalized in key or key in normalized:
                    order_qty = mat.get("order_qty") or mat.get("installed_qty") or 1
                    mat["known_price"] = round(vp["unit_price"] * order_qty, 2)
                    mat["known_price_source"] = "vendor_history"
                    mat["known_price_vendor"] = vp.get("vendor_name", "")
                    # Auto-apply known price to material
                    mat["unit_price"] = vp["unit_price"]
                    mat["extended_cost"] = mat["known_price"]
                    mat["price_source"] = "vendor_quote"
                    # Only set vendor from price match if material doesn't already have one
                    if not mat.get("vendor"):
                        mat["vendor"] = vp.get("vendor_name", "")
                    mat["quote_status"] = "quoted"
                    applied_count += 1
                    break

    return applied_count


@app.post("/api/jobs/bulk-delete")
def api_bulk_delete(body: BulkDeleteRequest):
    """Delete multiple jobs."""
    deleted = 0
    for jid in body.job_ids:
        if delete_job(jid):
            deleted += 1
    return {"deleted": deleted}


@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: str):
    """Delete a job by ID or slug and all related data."""
    if not delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"message": "Job deleted"}


@app.post("/api/jobs/{job_id}/duplicate")
def api_duplicate_job(job_id: str):
    """Duplicate a job and all its materials."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Create new job with same fields
    new_job = {
        "project_name": job["project_name"] + " (Copy)",
        "gc_name": job.get("gc_name"),
        "address": job.get("address"),
        "city": job.get("city"),
        "state": job.get("state"),
        "zip": job.get("zip"),
        "tax_rate": job.get("tax_rate", 0),
        "unit_count": job.get("unit_count", 0),
        "salesperson": job.get("salesperson"),
        "notes": job.get("notes"),
        "exclusions": job.get("exclusions"),
        "architect": job.get("architect"),
        "designer": job.get("designer"),
    }
    new_id = save_job(new_job)

    # Copy materials (strip id and job_id)
    materials = job.get("materials", [])
    copied = []
    for m in materials:
        mat = {k: v for k, v in m.items() if k not in ("id", "job_id")}
        copied.append(mat)
    if copied:
        save_materials(new_id, copied)

    created = load_job(new_id)
    log_activity(new_id, "job_created", f"Duplicated from '{job['project_name']}'", {"source_job_id": job["id"]})
    return {"id": new_id, "slug": created.get("slug", "")}


@app.put("/api/jobs/{job_id}/notes")
def api_update_notes(job_id: str, body: NotesUpdate):
    """Update job notes."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["notes"] = body.notes
    save_job(job)
    log_activity(job["id"], "notes_updated", "Notes updated")
    return {"message": "Notes saved"}


class JobUpdate(BaseModel):
    markup_pct: Optional[float] = None
    project_name: Optional[str] = None
    gc_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    tax_rate: Optional[float] = None
    unit_count: Optional[int] = None
    salesperson: Optional[str] = None
    notes: Optional[str] = None
    architect: Optional[str] = None
    designer: Optional[str] = None

@app.put("/api/jobs/{job_id}")
def api_update_job(job_id: str, body: JobUpdate):
    """Update job fields."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    updates = body.model_dump(exclude_none=True)
    changes = {}
    for key, val in updates.items():
        old_val = job.get(key)
        if old_val != val:
            changes[key] = {"old": old_val, "new": val}
    for key, val in updates.items():
        job[key] = val
    save_job(job)
    if changes:
        changed_keys = ", ".join(changes.keys())
        log_activity(job["id"], "job_updated", f"Updated {changed_keys}", {"changes": changes})
    return {"message": "Job updated"}


@app.post("/api/jobs/{job_id}/upload-rfms")
async def api_upload_rfms(job_id: str, request: Request, files: list[UploadFile] = File(default=None)):
    """Upload one or more RFMS pivot tables, parse them, return merged materials."""
    # Debug: log what we received
    ct = request.headers.get("content-type", "")
    print(f"[rfms_upload] Content-Type: {ct}")
    print(f"[rfms_upload] files param: {files}, type: {type(files)}")

    # If 'files' field is missing, try reading from the raw form
    if not files:
        form = await request.form()
        print(f"[rfms_upload] Raw form keys: {list(form.keys())}")
        files = form.getlist("files") or form.getlist("file")
        print(f"[rfms_upload] Extracted files: {files}")
        if not files:
            raise HTTPException(status_code=422, detail=f"No files received. Form keys: {list(form.keys())}")

    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db_id = job["id"]

    all_materials_raw = []
    rfms_job_info = {}

    for file in files:
        # Save uploaded file
        file_path = os.path.join(UPLOAD_DIR, f"rfms_{db_id}_{file.filename}")
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        try:
            result = parse_rfms(file_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse RFMS file '{file.filename}': {e}")

        # Use job info from first file that has it
        file_job_info = result.get("job_info", {})
        if not rfms_job_info and any(file_job_info.values()):
            rfms_job_info = file_job_info

        all_materials_raw.extend(result.get("materials", []))

    # Update job info from RFMS if available
    job_update = {
        "id": db_id,
        "project_name": rfms_job_info.get("project_name") or job["project_name"],
        "gc_name": rfms_job_info.get("gc_name") or job.get("gc_name"),
        "address": rfms_job_info.get("address") or job.get("address"),
        "city": rfms_job_info.get("city") or job.get("city"),
        "state": rfms_job_info.get("state") or job.get("state"),
        "zip": rfms_job_info.get("zip") or job.get("zip"),
        "tax_rate": job.get("tax_rate", 0),
        "unit_count": job.get("unit_count", 0),
        "salesperson": job.get("salesperson"),
        "notes": job.get("notes"),
        "architect": job.get("architect"),
        "designer": job.get("designer"),
    }
    save_job(job_update)

    # AI merge if job already has materials, otherwise use raw parsed
    existing_materials = job.get("materials", [])
    if existing_materials:
        print(f"[rfms_upload] Job has {len(existing_materials)} existing materials, running AI merge")
        merged_raw = ai_merge_materials(existing_materials, all_materials_raw)
    else:
        # First upload — just use the parsed materials directly
        merged_raw = []
        for m in all_materials_raw:
            merged_raw.append({
                "item_code": m.get("item_code"),
                "description": m.get("description"),
                "material_type": m.get("material_type", "unknown"),
                "installed_qty": m.get("qty", 0),
                "unit": m.get("unit"),
            })

    # Load waste factors from DB (falls back to config defaults)
    import json as _json
    _waste_data = get_company_rate("waste_factors")
    _waste_factors = _json.loads(_waste_data) if _waste_data else WASTE_FACTORS

    # Load price list for auto-pricing
    _price_list = get_price_list_entries()

    # Apply waste factors to the final merged list
    materials = []
    for m in merged_raw:
        material_type = m.get("material_type", "unknown")
        waste_pct = _waste_factors.get(material_type, 0)
        installed_qty = m.get("installed_qty", m.get("qty", 0))
        order_qty = installed_qty * (1 + waste_pct)

        # Auto-price from internal price list
        unit_price = m.get("unit_price", 0)
        vendor = m.get("vendor", "")
        if not unit_price and _price_list:
            matched = _match_price_list(m, _price_list)
            if matched:
                unit_price = matched["unit_price"]
                vendor = matched.get("vendor", "")

        # Set quote_status for unpriced materials
        quote_status = m.get("quote_status")
        if not unit_price and not quote_status:
            quote_status = "needs_quote"

        materials.append({
            "item_code": m.get("item_code"),
            "description": m.get("description"),
            "material_type": material_type,
            "installed_qty": round(installed_qty, 2),
            "unit": m.get("unit"),
            "waste_pct": waste_pct,
            "order_qty": round(order_qty, 2),
            "vendor": vendor,
            "unit_price": unit_price,
            "extended_cost": round(unit_price * round(order_qty, 2), 2),
            "ai_confidence": m.get("ai_confidence"),
            "quote_status": quote_status,
        })

    material_ids = save_materials(db_id, materials)

    # Attach IDs to returned materials
    for mat, mid in zip(materials, material_ids):
        mat["id"] = mid

    file_names = [f.filename for f in files if hasattr(f, 'filename')]
    log_activity(db_id, "rfms_uploaded", f"Uploaded {len(file_names)} RFMS file(s), {len(materials)} materials parsed", {"files": file_names, "material_count": len(materials)})

    return {"job_info": rfms_job_info, "materials": materials}


def _auto_match_quotes(job_id: int, products: list[dict]) -> int:
    """Try to match parsed quote products to existing materials.
    Phase 1: exact item_code matching (fast, no AI).
    Phase 2: AI fuzzy matching for remaining unmatched items."""
    job = load_job(job_id)
    if not job:
        return 0
    materials = job.get("materials", [])
    if not materials:
        return 0

    matched = 0
    updated = False
    matched_mat_indices = set()
    matched_prod_indices = set()

    # Phase 1: Fast exact item_code matching
    for mat_idx, mat in enumerate(materials):
        if mat.get("unit_price") and mat["unit_price"] > 0:
            continue  # already priced
        item_code = (mat.get("item_code") or "").strip().lower()
        description = (mat.get("description") or "").strip().lower()
        if not item_code and not description:
            continue

        for prod_idx, prod in enumerate(products):
            if prod_idx in matched_prod_indices:
                continue
            if prod.get("error") or not prod.get("unit_price"):
                continue
            prod_name = (prod.get("product_name") or "").strip().lower()
            prod_desc = (prod.get("description") or "").strip().lower()

            match = False
            if item_code and len(item_code) >= 3:
                if item_code in prod_name or item_code in prod_desc:
                    match = True

            if match:
                mat["unit_price"] = prod["unit_price"]
                mat["vendor"] = prod.get("vendor", "")
                mat["quote_status"] = "quoted"
                mat["price_source"] = "vendor_quote"
                order_qty = mat.get("order_qty", 0)
                mat["extended_cost"] = round(order_qty * mat["unit_price"], 2)
                matched += 1
                updated = True
                matched_mat_indices.add(mat_idx)
                matched_prod_indices.add(prod_idx)
                break

    # Phase 2: AI fuzzy matching for remaining unmatched
    unmatched_mats = [(i, m) for i, m in enumerate(materials) if i not in matched_mat_indices and (not m.get("unit_price") or m["unit_price"] == 0)]
    unmatched_prods = [(i, p) for i, p in enumerate(products) if i not in matched_prod_indices and not p.get("error") and p.get("unit_price")]

    if unmatched_mats and unmatched_prods:
        ai_matched = _ai_match_quotes(unmatched_mats, unmatched_prods)
        for mat_idx, prod_idx in ai_matched:
            mat = materials[mat_idx]
            prod = products[prod_idx]
            mat["unit_price"] = prod["unit_price"]
            mat["vendor"] = prod.get("vendor", "")
            mat["quote_status"] = "quoted"
            mat["price_source"] = "vendor_quote"
            order_qty = mat.get("order_qty", 0)
            mat["extended_cost"] = round(order_qty * mat["unit_price"], 2)
            matched += 1
            updated = True

    if updated:
        save_materials(job_id, materials)

    # Also try to link to open quote requests
    _link_upload_to_requests(job_id, products)

    return matched


def _ai_match_quotes(unmatched_mats: list, unmatched_prods: list) -> list:
    """Use AI to fuzzy-match vendor products to job materials."""
    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    if not api_key:
        return []

    try:
        import openai, json
        client = openai.OpenAI(api_key=api_key)

        mat_lines = []
        for i, (idx, m) in enumerate(unmatched_mats):
            mat_lines.append(f"M{i}: [{m.get('item_code', '')}] {m.get('description', '')} (type: {m.get('material_type', '')})")

        prod_lines = []
        for i, (idx, p) in enumerate(unmatched_prods):
            prod_lines.append(f"P{i}: {p.get('product_name', '')} — {p.get('description', '')} (vendor: {p.get('vendor', '')}, ${p.get('unit_price', 0)}/{p.get('unit', 'unit')})")

        prompt = f"""Match vendor-quoted products to our job materials. These are commercial flooring products.

Our unmatched materials:
{chr(10).join(mat_lines)}

Vendor quoted products:
{chr(10).join(prod_lines)}

Match products to materials based on: brand name, product line, color, style number, dimensions.
Only match if you are 80%+ confident they are the same product.

Return ONLY a JSON array: [{{"material": "M0", "product": "P0", "confidence": 0.95}}]
Return empty array [] if no confident matches."""

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)

        # Parse result
        matches_raw = result if isinstance(result, list) else result.get("matches", result.get("results", result.get("data", [])))
        if not isinstance(matches_raw, list):
            matches_raw = []

        pairs = []
        for m in matches_raw:
            conf = m.get("confidence", 0)
            if conf < 0.8:
                continue
            mat_ref = m.get("material", "")
            prod_ref = m.get("product", "")
            try:
                mat_local_idx = int(mat_ref.replace("M", ""))
                prod_local_idx = int(prod_ref.replace("P", ""))
                if 0 <= mat_local_idx < len(unmatched_mats) and 0 <= prod_local_idx < len(unmatched_prods):
                    pairs.append((unmatched_mats[mat_local_idx][0], unmatched_prods[prod_local_idx][0]))
            except (ValueError, IndexError):
                continue

        return pairs
    except Exception as e:
        print(f"AI quote matching failed (non-fatal): {e}")
        return []


def _link_upload_to_requests(job_id: int, products: list[dict]):
    """Detect which open quote requests match uploaded vendor quotes.
    Returns list of matched requests for frontend confirmation."""
    requests = list_quote_requests(job_id)
    if not requests:
        return []

    # Detect vendors and file names from uploaded products
    upload_vendors = {}  # vendor_lower -> {vendor, file_name}
    for p in products:
        v = (p.get("vendor") or "").strip()
        if v:
            upload_vendors[v.lower()] = {
                "vendor": v,
                "file_name": p.get("file_name", ""),
            }

    if not upload_vendors:
        return []

    import re
    def _normalize_vendor(name):
        """Normalize vendor name for fuzzy matching: lowercase, strip punctuation, collapse spaces."""
        return re.sub(r'[^a-z0-9 ]', '', name.lower()).strip()

    matched = []
    for req in requests:
        if req.get("received_at"):
            continue  # already marked received
        req_vendor = _normalize_vendor(req.get("vendor_name") or "")
        for uv_lower, uv_info in upload_vendors.items():
            uv_norm = _normalize_vendor(uv_lower)
            if req_vendor in uv_norm or uv_norm in req_vendor or req_vendor == uv_norm:
                matched.append({
                    "request_id": req["id"],
                    "vendor_name": req.get("vendor_name", ""),
                    "sent_at": req.get("sent_at", ""),
                    "response_file": uv_info.get("file_name", ""),
                })
                break

    return matched


@app.post("/api/jobs/{job_id}/upload-quotes")
async def api_upload_quotes(job_id: str, files: list[UploadFile] = File(...)):
    """Upload vendor quote files, parse them, return pricing."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db_id = job["id"]

    all_products = []
    for upload in files:
        file_path = os.path.join(UPLOAD_DIR, f"quote_{db_id}_{upload.filename}")
        with open(file_path, "wb") as f:
            content = await upload.read()
            f.write(content)

        try:
            products = parse_quote_file(file_path)
            for p in products:
                p["file_name"] = upload.filename
            all_products.extend(products)
        except Exception as e:
            all_products.append({"error": str(e), "file": upload.filename})

    # Persist quotes to DB
    save_quotes(db_id, all_products)

    # Auto-match prices to materials
    auto_matched = _auto_match_quotes(db_id, all_products)

    # Save to vendor pricing database
    save_vendor_prices_from_quotes(db_id, all_products)

    # Detect matching quote requests (don't auto-link — frontend will confirm)
    linked_requests = _link_upload_to_requests(db_id, all_products)

    file_names = [u.filename for u in files if hasattr(u, 'filename')]
    vendors_found = list(set(p.get("vendor", "Unknown") for p in all_products if p.get("vendor")))
    log_activity(db_id, "quotes_uploaded", f"Uploaded {len(file_names)} quote file(s), {len(all_products)} products, {auto_matched} auto-matched", {"files": file_names, "vendors": vendors_found, "product_count": len(all_products), "auto_matched": auto_matched})

    return {"products": all_products, "auto_matched": auto_matched, "linked_requests": linked_requests}


@app.delete("/api/jobs/{job_id}/quotes")
def api_clear_quotes(job_id: str):
    """Clear all parsed quotes for a job."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    delete_quotes(job["id"])
    log_activity(job["id"], "quotes_cleared", "All vendor quotes cleared")
    return {"message": "Quotes cleared"}


@app.put("/api/quotes/{quote_id}")
def api_update_quote(quote_id: int, body: dict = Body(...)):
    """Update a single quote entry and re-match against materials."""
    job_id = get_quote_job_id(quote_id)
    if not job_id:
        raise HTTPException(status_code=404, detail="Quote not found")
    update_quote(quote_id, body)
    # Re-run auto-match so the updated price flows to materials
    job = load_job(job_id)
    if job:
        quotes = job.get("quotes", [])
        _auto_match_quotes(job_id, quotes)
    log_activity(job_id, "quote_updated", f"Quote #{quote_id} updated")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/calculate")
def api_calculate(job_id: str):
    """Run sundry + labor calculators, return results."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])

    # Calculate sundries
    sundries = calculate_sundries_for_materials(materials)
    save_sundries(job["id"], sundries)

    # Calculate labor
    labor_items = calculate_labor_for_materials(materials)
    save_labor(job["id"], labor_items)

    log_activity(job["id"], "bid_calculated", f"Calculated {len(sundries)} sundries and {len(labor_items)} labor items")

    return {"sundries": sundries, "labor": labor_items}


@app.put("/api/jobs/{job_id}/materials")
def api_update_materials(job_id: str, body: MaterialUpdate):
    """Update materials (edited pricing, waste, etc.)."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Build lookup of existing materials by id
    existing = {m["id"]: m for m in job.get("materials", [])}

    # Merge incoming updates with existing data
    updated = []
    for m in body.materials:
        base = existing.get(m.get("id"), {})
        merged = {**base, **{k: v for k, v in m.items() if v is not None}}

        # If user changed the type, mark as human-verified
        if m.get("material_type") and base.get("material_type") != m.get("material_type"):
            merged["ai_confidence"] = 1.0

        waste_pct = merged.get("waste_pct", 0)
        installed_qty = merged.get("installed_qty", 0)
        unit_price = merged.get("unit_price", 0)

        # Always recompute order_qty from source values to avoid rounding drift
        order_qty = installed_qty * (1 + waste_pct)
        extended_cost = order_qty * unit_price

        merged["order_qty"] = round(order_qty, 2)
        merged["extended_cost"] = round(extended_cost, 2)
        updated.append(merged)

    material_ids = save_materials(job["id"], updated)
    for mat, mid in zip(updated, material_ids):
        mat["id"] = mid

    log_activity(job["id"], "materials_updated", f"Updated pricing for {len(body.materials)} materials")

    return {"materials": updated}


@app.post("/api/jobs/{job_id}/materials/{material_idx}/estimate-price")
def api_estimate_price(job_id: str, material_idx: int):
    """Use AI to estimate a material's unit price based on its description."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])
    if material_idx < 0 or material_idx >= len(materials):
        raise HTTPException(status_code=404, detail="Material not found")

    m = materials[material_idx]
    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")

    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")

    import openai
    import json as _json

    # Check price history and price list for existing data to inform the estimate
    history = get_price_history(item_code=m.get("item_code"), product=m.get("description"))
    price_list = get_price_list_entries()
    price_list_match = None
    item_code_lower = (m.get("item_code") or "").lower()
    desc_lower = (m.get("description") or "").lower()
    for entry in price_list:
        ename = (entry.get("product_name") or "").lower()
        if item_code_lower and item_code_lower in ename:
            price_list_match = entry
            break
        if desc_lower and ename and ename in desc_lower:
            price_list_match = entry
            break

    # Build context for AI
    context_lines = []
    if history.get("records"):
        context_lines.append(f"Price history: min=${history['min']}, max=${history['max']}, avg=${history['avg']}")
        latest = history["latest"]
        if latest:
            context_lines.append(f"Latest quote: ${latest.get('unit_price')} from {latest.get('vendor_name', 'unknown')} ({latest.get('created_at', '')})")
    if price_list_match:
        context_lines.append(f"Internal price list: ${price_list_match.get('unit_price')} per {price_list_match.get('unit', 'unit')}")

    history_context = "\n".join(context_lines) if context_lines else "No historical pricing data available."

    client = openai.OpenAI(api_key=api_key)

    prompt = f"""Estimate the unit price for this flooring/interior material.
Return JSON: {{"estimated_price": <number>, "confidence": <0-1>, "reasoning": "<brief>"}}

Material: {m.get('description', '')}
Item Code: {m.get('item_code', '')}
Type: {m.get('material_type', '')}
Unit: {m.get('unit', '')}
Order Qty: {m.get('order_qty', 0)}

Historical Data:
{history_context}

If historical data is available, weight it heavily in your estimate. Otherwise, base your estimate on typical commercial flooring/interior material pricing.
The price should be per {m.get('unit', 'unit')}. Be conservative — estimate on the higher side."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a commercial flooring estimator. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        result = _json.loads(response.choices[0].message.content)
        estimated_price = float(result.get("estimated_price", 0))
        confidence = float(result.get("confidence", 0.5))
        reasoning = result.get("reasoning", "")

        # Update the material with the AI estimate
        m["unit_price"] = round(estimated_price, 2)
        m["price_source"] = "ai_estimate"
        m["order_qty"] = round(m.get("installed_qty", 0) * (1 + m.get("waste_pct", 0)), 2)
        m["extended_cost"] = round(m["order_qty"] * m["unit_price"], 2)
        materials[material_idx] = m
        save_materials(job["id"], materials)

        log_activity(job["id"], "ai_estimate",
                     f"AI estimated price for {m.get('item_code', m.get('description', 'material'))}: ${estimated_price:.2f}/{m.get('unit', 'unit')}")

        return {
            "estimated_price": estimated_price,
            "confidence": confidence,
            "reasoning": reasoning,
            "material": m,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI estimation failed: {e}")


@app.post("/api/jobs/{job_id}/generate-bid")
def api_generate_bid(job_id: str):
    """Assemble bid + generate PDF, return bid data."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])
    sundries = job.get("sundries", [])
    labor_items = job.get("labor", [])

    # Build job_info dict for assembler
    job_info = {
        "id": job["id"],
        "project_name": job["project_name"],
        "gc_name": job.get("gc_name"),
        "address": job.get("address"),
        "city": job.get("city"),
        "state": job.get("state"),
        "zip": job.get("zip"),
        "tax_rate": job.get("tax_rate", 0),
        "unit_count": job.get("unit_count", 0),
        "salesperson": job.get("salesperson"),
        "markup_pct": job.get("markup_pct", 0),
    }

    # Parse job-specific exclusions (stored as JSON string)
    import json as _json
    custom_exclusions = None
    raw_exclusions = job.get("exclusions")
    if raw_exclusions:
        try:
            custom_exclusions = _json.loads(raw_exclusions)
        except (ValueError, TypeError):
            pass

    bid_data = assemble_bid(job_info, materials, sundries, labor_items, exclusions=custom_exclusions)

    # Save bundles
    save_bundles(job["id"], bid_data["bundles"])

    # Persist full bid data to job record (bundles + totals)
    bid_persist = {
        "bundles": bid_data["bundles"],
        "subtotal": bid_data["subtotal"],
        "markup_pct": bid_data["markup_pct"],
        "markup_amount": bid_data["markup_amount"],
        "tax_rate": bid_data["tax_rate"],
        "tax_amount": bid_data["tax_amount"],
        "grand_total": bid_data["grand_total"],
        "exclusions": bid_data.get("exclusions", []),
    }
    job["bid_data"] = _json.dumps(bid_persist)
    save_job(job)

    # Generate PDF
    pdf_path = os.path.join(PDF_DIR, f"bid_{job['id']}.pdf")
    generate_bid_pdf(bid_data, pdf_path)

    bundle_count = len(bid_data.get("bundles", []))
    grand_total = bid_data.get("grand_total", 0)
    log_activity(job["id"], "bid_generated", f"Bid generated: {bundle_count} bundles, total ${grand_total:,.2f}", {"bundle_count": bundle_count, "grand_total": grand_total})

    return bid_data


@app.delete("/api/jobs/{job_id}/bid")
def api_clear_bid(job_id: str):
    """Clear saved bid data for a job."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["bid_data"] = None
    save_job(job)
    # Clear bundles too
    save_bundles(job["id"], [])
    log_activity(job["id"], "bid_cleared", "Bid data cleared")
    return {"message": "Bid cleared"}


@app.get("/api/jobs/{job_id}/bid.pdf")
def api_download_bid_pdf(job_id: str):
    """Download the generated bid PDF."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    pdf_path = os.path.join(PDF_DIR, f"bid_{job['id']}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found. Generate bid first.")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"bid_{job_id}.pdf",
    )


@app.post("/api/labor-catalog/upload")
async def api_upload_labor_catalog(file: UploadFile = File(...)):
    """Upload labor catalog (Excel or PDF)."""
    file_path = os.path.join(UPLOAD_DIR, f"labor_catalog_{file.filename}")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    ext = os.path.splitext(file.filename)[1].lower()
    try:
        if ext == ".pdf":
            settings = get_settings()
            api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
            model = settings.get("openai_model", "gpt-5-mini")
            catalog = load_labor_catalog_from_pdf(file_path, api_key=api_key, model=model)
        elif ext in (".xlsx", ".xls"):
            catalog = load_labor_catalog(file_path)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Upload .pdf or .xlsx")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse labor catalog: {e}")

    return {"message": "Labor catalog loaded", "entries": len(catalog)}


# ── Exclusions ────────────────────────────────────────────────────────────────

class ExclusionsUpdate(BaseModel):
    exclusions: list[str]


@app.put("/api/jobs/{job_id}/exclusions")
def api_update_exclusions(job_id: str, body: ExclusionsUpdate):
    """Update job-specific exclusions list."""
    import json as _json
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["exclusions"] = _json.dumps(body.exclusions)
    save_job(job)
    excl_count = len(body.exclusions) if body.exclusions else 0
    log_activity(job["id"], "exclusions_updated", f"Updated exclusions ({excl_count} items)")
    return {"message": "Exclusions saved", "exclusions": body.exclusions}


@app.get("/api/jobs/{job_id}/exclusions")
def api_get_exclusions(job_id: str):
    """Get job exclusions (custom or defaults)."""
    import json as _json
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    raw = job.get("exclusions")
    if raw:
        try:
            return {"exclusions": _json.loads(raw), "is_custom": True}
        except (ValueError, TypeError):
            pass
    return {"exclusions": EXCLUSIONS_TEMPLATE, "is_custom": False}


# ── Materials Export ──────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/materials/export")
def api_export_materials(job_id: str):
    """Export materials as CSV download."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])
    if not materials:
        raise HTTPException(status_code=400, detail="No materials to export")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Item Code", "Description", "Material Type", "Install Qty", "Unit",
        "Waste %", "Order Qty", "Unit Price", "Extended Cost"
    ])
    for m in materials:
        writer.writerow([
            m.get("item_code", ""),
            m.get("description", ""),
            m.get("material_type", ""),
            m.get("installed_qty", 0),
            m.get("unit", ""),
            f"{(m.get('waste_pct', 0) * 100):.0f}%",
            m.get("order_qty", 0),
            m.get("unit_price", 0),
            m.get("extended_cost", 0),
        ])

    output.seek(0)
    slug = job.get("slug", f"job-{job['id']}")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{slug}-materials.csv"'}
    )


# ── Labor Catalog ────────────────────────────────────────────────────────────

@app.get("/api/labor-catalog")
def api_get_labor_catalog():
    """Get the currently loaded labor catalog entries."""
    catalog = get_labor_catalog()
    return {"entries": catalog, "count": len(catalog)}


@app.put("/api/labor-catalog/{entry_id}")
def api_update_labor_catalog_entry(entry_id: int, body: dict):
    """Update a single labor catalog entry."""
    if not update_labor_catalog_entry(entry_id, body):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Entry updated"}


@app.delete("/api/labor-catalog/{entry_id}")
def api_delete_labor_catalog_entry(entry_id: int):
    """Delete a single labor catalog entry."""
    if not delete_labor_catalog_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Entry deleted"}


@app.delete("/api/labor-catalog")
def api_clear_labor_catalog():
    """Clear all labor catalog entries."""
    clear_labor_catalog()
    return {"message": "Labor catalog cleared"}


@app.get("/api/search")
def api_search(q: str = ""):
    """Global search across jobs and materials."""
    if not q or len(q) < 2:
        return {"jobs": [], "materials": []}
    return search_all(q)


# ── Company Rates ────────────────────────────────────────────────────────────

def _seed_company_rates():
    """Seed company rates from config.py defaults if not yet in DB."""
    import json as _json
    for rate_type, default_data in [
        ("sundry_rules", SUNDRY_RULES),
        ("waste_factors", WASTE_FACTORS),
        ("freight_rates", FREIGHT_RATES),
    ]:
        existing = get_company_rate(rate_type)
        if existing is None:
            save_company_rate(rate_type, _json.dumps(default_data))
            print(f"[seed] Seeded {rate_type} from config.py defaults")


@app.get("/api/company-rates")
def api_get_all_company_rates():
    """Get all company rates."""
    return get_all_company_rates()


@app.get("/api/company-rates/{rate_type}")
def api_get_company_rate(rate_type: str):
    """Get a specific company rate (sundry_rules, waste_factors, freight_rates)."""
    import json as _json
    data = get_company_rate(rate_type)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Rate type '{rate_type}' not found")
    return {"rate_type": rate_type, "data": _json.loads(data)}


class CompanyRateUpdate(BaseModel):
    data: dict


@app.put("/api/company-rates/{rate_type}")
def api_update_company_rate(rate_type: str, body: CompanyRateUpdate):
    """Update a company rate."""
    import json as _json
    if rate_type not in ("sundry_rules", "waste_factors", "freight_rates"):
        raise HTTPException(status_code=400, detail=f"Invalid rate type: {rate_type}")
    save_company_rate(rate_type, _json.dumps(body.data))
    return {"message": f"{rate_type} updated"}


# ── Price List ───────────────────────────────────────────────────────────────

@app.get("/api/price-list")
def api_get_price_list():
    """Get all price list entries."""
    entries = get_price_list_entries()
    return {"entries": entries, "count": len(entries)}


class PriceListEntry(BaseModel):
    product_name: str
    material_type: Optional[str] = ""
    unit: Optional[str] = ""
    unit_price: Optional[float] = 0
    vendor: Optional[str] = ""
    notes: Optional[str] = ""


@app.post("/api/price-list")
def api_add_price_list_entry(body: PriceListEntry):
    """Add a single price list entry."""
    entry_id = add_price_list_entry(body.model_dump())
    return {"id": entry_id, "message": "Entry added"}


@app.put("/api/price-list/{entry_id}")
def api_update_price_list_entry(entry_id: int, body: PriceListEntry):
    """Update a price list entry."""
    if not update_price_list_entry(entry_id, body.model_dump()):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Entry updated"}


@app.delete("/api/price-list/{entry_id}")
def api_delete_price_list_entry(entry_id: int):
    """Delete a price list entry."""
    if not delete_price_list_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Entry deleted"}


class PriceListBulkUpload(BaseModel):
    entries: list[dict]


@app.post("/api/price-list/bulk")
def api_bulk_upload_price_list(body: PriceListBulkUpload):
    """Replace all price list entries (bulk upload)."""
    save_price_list_entries(body.entries)
    return {"message": "Price list updated", "count": len(body.entries)}


@app.delete("/api/price-list")
def api_clear_price_list():
    """Clear all price list entries."""
    clear_price_list()
    return {"message": "Price list cleared"}


@app.post("/api/price-list/upload")
async def api_upload_price_list(file: UploadFile = File(...)):
    """Upload price list from CSV or Excel file."""
    import json as _json
    file_path = os.path.join(UPLOAD_DIR, f"price_list_{file.filename}")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    ext = os.path.splitext(file.filename)[1].lower()
    entries = []

    if ext == ".csv":
        with open(file_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entries.append({
                    "product_name": row.get("product_name", row.get("Product Name", row.get("name", ""))),
                    "material_type": row.get("material_type", row.get("Material Type", row.get("type", ""))),
                    "unit": row.get("unit", row.get("Unit", "")),
                    "unit_price": float(row.get("unit_price", row.get("Unit Price", row.get("price", 0))) or 0),
                    "vendor": row.get("vendor", row.get("Vendor", "")),
                    "notes": row.get("notes", row.get("Notes", "")),
                })
    elif ext in (".xlsx", ".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb[wb.sheetnames[0]]
        headers = [str(c.value or "").strip().lower() for c in ws[1]]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            row_dict = dict(zip(headers, row))
            entries.append({
                "product_name": str(row_dict.get("product_name", row_dict.get("product name", row_dict.get("name", ""))) or ""),
                "material_type": str(row_dict.get("material_type", row_dict.get("material type", row_dict.get("type", ""))) or ""),
                "unit": str(row_dict.get("unit", "") or ""),
                "unit_price": float(row_dict.get("unit_price", row_dict.get("unit price", row_dict.get("price", 0))) or 0),
                "vendor": str(row_dict.get("vendor", "") or ""),
                "notes": str(row_dict.get("notes", "") or ""),
            })
        wb.close()
    elif ext == ".pdf":
        # Parse price list PDF using AI
        settings = get_settings()
        api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
        model = settings.get("openai_model", "gpt-5-mini")
        entries = _parse_price_list_pdf(file_path, api_key, model)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Upload .csv, .xlsx, or .pdf")

    if not entries:
        raise HTTPException(status_code=400, detail="No entries found in uploaded file")

    save_price_list_entries(entries)
    return {"message": "Price list uploaded", "count": len(entries)}


def _parse_price_list_pdf(file_path: str, api_key: str = None, model: str = "gpt-5-mini") -> list[dict]:
    """Parse a price list PDF using AI."""
    import pdfplumber
    from openai import OpenAI

    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    text = "\n".join(text_parts)
    if not text.strip():
        return []

    client_kwargs = {}
    if api_key:
        client_kwargs["api_key"] = api_key
    client = OpenAI(**client_kwargs)

    import json as _json
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": """You are parsing a material price list for a flooring/interiors company.
Extract every product/material entry into a JSON array.

For each entry, extract:
- product_name: the product name or description
- material_type: the flooring type if identifiable (e.g. "unit_lvt", "unit_carpet_no_pattern", "floor_tile", etc.)
- unit: the unit of measure (SF, SY, LF, EA, etc.)
- unit_price: the price per unit as a number
- vendor: the vendor/manufacturer if shown
- notes: any additional notes

Return JSON: {"entries": [{"product_name": "...", "material_type": "...", "unit": "...", "unit_price": 0.00, "vendor": "...", "notes": "..."}, ...]}"""},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
    )
    parsed = _json.loads(response.choices[0].message.content)
    return parsed.get("entries", [])


# ── Settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def api_get_settings():
    """Get app settings (API key is masked)."""
    settings = get_settings()
    # Mask the API key for display
    raw_key = settings.get("openai_api_key", "")
    if raw_key and len(raw_key) > 8:
        masked = raw_key[:4] + "•" * (len(raw_key) - 8) + raw_key[-4:]
    elif raw_key:
        masked = "•" * len(raw_key)
    else:
        masked = ""
    return {
        "openai_api_key_set": bool(raw_key),
        "openai_api_key_masked": masked,
        "openai_model": settings.get("openai_model", "gpt-5-mini"),
        "multi_pass_count": int(settings.get("multi_pass_count", "2")),
        "email_automation_enabled": settings.get("email_automation_enabled", "false"),
        "email_config": settings.get("email_config", ""),
    }


@app.post("/api/settings")
def api_update_settings(body: SettingsUpdate):
    """Update app settings."""
    updates = {}
    if body.openai_api_key is not None:
        updates["openai_api_key"] = body.openai_api_key
    if body.openai_model is not None:
        if body.openai_model not in ("gpt-5-mini", "gpt-5.4"):
            raise HTTPException(status_code=400, detail="Invalid model. Choose gpt-5-mini or gpt-5.4")
        updates["openai_model"] = body.openai_model
    if body.multi_pass_count is not None:
        if body.multi_pass_count < 1 or body.multi_pass_count > 5:
            raise HTTPException(status_code=400, detail="Multi-pass count must be between 1 and 5")
        updates["multi_pass_count"] = str(body.multi_pass_count)
    # Email automation settings
    if body.email_automation_enabled is not None:
        updates["email_automation_enabled"] = body.email_automation_enabled
    if body.email_config is not None:
        updates["email_config"] = body.email_config
    if updates:
        save_settings(updates)
        # Apply API key and model to quote parser
        settings = get_settings()
        _apply_openai_config(settings)
        # Restart inbox monitor if email settings changed
        if body.email_automation_enabled is not None or body.email_config is not None:
            _start_inbox_monitor()
    return {"message": "Settings updated", **api_get_settings()}


def _apply_openai_config(settings: dict = None):
    """Apply stored OpenAI settings to the quote parser."""
    if settings is None:
        settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    passes = int(settings.get("multi_pass_count", "2"))
    print(f"[openai_config] api_key={'set' if api_key else 'MISSING'}, model={model}, passes={passes}")
    set_openai_config(api_key=api_key, model=model, num_passes=passes)


# ── Vendor Pricing Intelligence ───────────────────────────────────────────────

@app.get("/api/vendors")
async def api_list_vendors():
    return list_vendors()


@app.get("/api/vendors/{vendor_id}")
async def api_get_vendor(vendor_id: int):
    v = get_vendor(vendor_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v


@app.post("/api/vendors")
async def api_create_vendor(request: Request):
    data = await request.json()
    try:
        vendor = create_vendor(data)
        return vendor
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/vendors/{vendor_id}")
async def api_update_vendor(vendor_id: int, request: Request):
    data = await request.json()
    update_vendor(vendor_id, data)
    return {"ok": True}


@app.delete("/api/vendors/{vendor_id}")
async def api_delete_vendor(vendor_id: int):
    if delete_vendor(vendor_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Vendor not found")


@app.get("/api/vendor-prices")
async def api_search_vendor_prices(vendor: str = None, product: str = None, limit: int = 50):
    return search_vendor_prices(vendor, product, limit)


@app.post("/api/vendor-prices/import")
async def api_import_vendor_prices(file: UploadFile = File(...)):
    """Bulk import vendor prices from CSV. Accepts partial data - only product_name and unit_price required."""
    contents = await file.read()
    text = contents.decode('utf-8-sig')  # handle BOM
    result = import_vendor_prices_csv(text)
    return result


@app.get("/api/materials/price-history")
async def api_price_history(item_code: str = None, product: str = None, exclude_job: int = None):
    return get_price_history(item_code, product, exclude_job)


# ── Quote Requests ───────────────────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/quote-requests")
async def api_create_quote_request(job_id: str, request: Request):
    db_id = _resolve_job_id(job_id)
    data = await request.json()
    vendor_name = data.get("vendor_name", "").strip()
    if not vendor_name:
        raise HTTPException(status_code=400, detail="vendor_name is required")
    status = data.get("status", "draft")
    sent_at = data.get("sent_at")
    qr = create_quote_request(
        job_id=db_id,
        vendor_name=vendor_name,
        material_ids=data.get("material_ids", []),
        request_text=data.get("request_text", ""),
        vendor_id=data.get("vendor_id"),
        status=status,
        sent_at=sent_at,
    )
    return qr


@app.get("/api/jobs/{job_id}/quote-requests")
async def api_list_quote_requests(job_id: str):
    db_id = _resolve_job_id(job_id)
    return list_quote_requests(db_id)


@app.put("/api/quote-requests/{request_id}")
async def api_update_quote_request(request_id: int, request: Request):
    data = await request.json()
    update_quote_request(request_id, **data)
    return {"ok": True}


@app.delete("/api/quote-requests/{request_id}")
async def api_delete_quote_request(request_id: int):
    if delete_quote_request(request_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Quote request not found")


# ── AI: Vendor Detection & Quote Text ────────────────────────────────────────

def _build_vendor_memory() -> dict:
    """Build vendor knowledge from DB history — no hardcoded lists.

    Returns:
      - known_names: vendor names from vendors table
      - aliases: lowercase name → canonical name (shortest/cleanest wins)
      - product_hints: product_normalized → vendor_name
    """
    conn = _get_conn()
    try:
        vendors = conn.execute("SELECT id, name FROM vendors").fetchall()
        vendor_id_map = {v["id"]: v["name"] for v in vendors}

        # Build alias map: prefer shorter names as canonical
        # e.g., "Daltile" (7 chars) beats "Dal-Tile" (8 chars)
        aliases = {}
        def _add_alias(name_str: str, canonical: str):
            """Register a name and its cleaned variants, don't overwrite existing."""
            for v in {name_str.lower(), name_str.lower().replace("-", "").replace(" ", "")}:
                if v not in aliases:
                    aliases[v] = canonical

        # Shorter names first → they become canonical
        for v in sorted(vendors, key=lambda v: (len(v["name"]), v["name"])):
            name = v["name"]
            # If cleaned form already maps somewhere, use THAT as canonical
            # (so "Dal-Tile" → cleaned "daltile" → already maps to "Daltile")
            canonical = aliases.get(name.lower().replace("-", "").replace(" ", ""), name)
            _add_alias(name, canonical)

        # Learn from vendor_prices (same vendor_id, different name strings)
        vp_names = conn.execute("""
            SELECT DISTINCT vendor_id, vendor_name FROM vendor_prices
            WHERE vendor_id IS NOT NULL AND vendor_name IS NOT NULL
        """).fetchall()
        for vp in vp_names:
            raw_canonical = vendor_id_map.get(vp["vendor_id"])
            if raw_canonical:
                # Resolve through existing aliases
                canonical = aliases.get(raw_canonical.lower().replace("-", "").replace(" ", ""), raw_canonical)
                _add_alias(vp["vendor_name"], canonical)

        # Product hints: which vendor historically supplies which products
        product_hints = {}
        for row in conn.execute("""
            SELECT product_normalized, vendor_name, COUNT(*) as cnt
            FROM vendor_prices
            WHERE product_normalized IS NOT NULL AND vendor_name IS NOT NULL
            GROUP BY product_normalized, vendor_name ORDER BY cnt DESC
        """).fetchall():
            pn = row["product_normalized"]
            if pn and pn not in product_hints:
                product_hints[pn] = row["vendor_name"]

        # Vendor catalog: what products each vendor sells (for AI context)
        vendor_catalog = {}
        for row in conn.execute("""
            SELECT vendor_name, product_name
            FROM vendor_prices
            WHERE vendor_name IS NOT NULL AND product_name IS NOT NULL
            ORDER BY vendor_name, product_name
        """).fetchall():
            vn = row["vendor_name"]
            # Resolve through aliases
            canonical = aliases.get(vn.lower().replace("-", "").replace(" ", ""), vn)
            vendor_catalog.setdefault(canonical, []).append(row["product_name"])

        return {
            "known_names": [v["name"] for v in vendors],
            "aliases": aliases,
            "product_hints": product_hints,
            "vendor_catalog": vendor_catalog,
        }
    finally:
        conn.close()


def _fuzzy_match_vendor(text: str, aliases: dict, threshold: int = 2) -> str | None:
    """Match text against known vendor aliases. Handles case, punctuation, typos, substrings."""
    if not text or len(text) < 2:
        return None
    t = text.lower().strip()

    # 1. Exact / cleaned match
    if t in aliases:
        return aliases[t]
    t_clean = t.replace("-", "").replace(".", "").replace(",", "").replace(" ", "")
    for alias, canonical in aliases.items():
        if t_clean == alias.replace("-", "").replace(".", "").replace(",", "").replace(" ", ""):
            return canonical

    # 2. Substring (one contains the other, min 4 chars)
    if len(t) >= 4:
        for alias, canonical in aliases.items():
            if len(alias) >= 4 and (alias in t or t in alias):
                return canonical

    # 3. Levenshtein for typos (e.g., "Dalitle" ↔ "daltile")
    if len(t) >= 5:
        best, best_dist = None, threshold + 1
        for alias, canonical in aliases.items():
            if len(alias) < 4 or abs(len(alias) - len(t)) > threshold:
                continue
            # Inline Levenshtein
            s1, s2 = (t, alias) if len(t) >= len(alias) else (alias, t)
            prev = list(range(len(s2) + 1))
            for i, c1 in enumerate(s1):
                curr = [i + 1]
                for j, c2 in enumerate(s2):
                    curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
                prev = curr
            if prev[-1] <= threshold and prev[-1] < best_dist:
                best, best_dist = canonical, prev[-1]
        if best:
            return best
    return None


def _quick_regex_extract(description: str) -> list[str]:
    """Extract vendor candidates from dash-separated material descriptions.
    No hardcoded vendor names — pure structural parsing.

    "F109 - Interface - Breakout - ..." → ["Interface"]
    "(Scheme A) Daltile - Modern Hearth - ..." → ["Daltile"]
    "Schluter - Dilex-AHKA Cove - ..." → ["Schluter"]
    """
    import re
    if not description:
        return []
    desc = re.sub(r'^\(Scheme\s+[^)]+\)\s*', '', description.strip())
    segments = [s.strip() for s in desc.split(' - ') if s.strip()]
    candidates = []

    # "ItemCode - Vendor - Product - ..." (3+ segments, first is a code)
    if len(segments) >= 3 and re.match(r'^[A-Za-z0-9/]{1,20}$', segments[0]):
        candidates.append(segments[1])

    # "Vendor - Product - ..." (first segment IS the vendor)
    if len(segments) >= 2:
        first = segments[0]
        if (2 <= len(first) <= 50
            and not re.match(r'^[A-Z]\d+$', first)
            and not re.match(r'^[\d"\'x\s.]+$', first)
            and not first.lower().startswith(('transition', 'horizontal', 'vertical'))
            and first not in candidates):
            candidates.append(first)

    return candidates


@app.post("/api/jobs/{job_id}/detect-vendors")
async def api_detect_vendors(job_id: str):
    """Hybrid vendor detection: memory + regex + AI.

    1. MEMORY: Check vendor_prices history and vendors table for known names/aliases
    2. REGEX: Extract candidate from description structure (no hardcoded names)
    3. FUZZY MATCH: Match regex candidate against memory (handles typos)
    4. AI: For unresolved items, ask AI with evidence requirement
    5. VALIDATE: Cross-check AI results — reject if evidence doesn't appear in description
    6. RETRY: Focused single-item AI call for any conflicts
    """
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])
    if not materials:
        return {"vendors": {}, "materials": []}

    import json

    # ── Build vendor memory from DB history ──
    memory = _build_vendor_memory()
    aliases = memory["aliases"]
    known_names = memory["known_names"]
    product_hints = memory["product_hints"]
    vendor_catalog = memory["vendor_catalog"]

    vendor_groups = {}
    needs_ai = []  # indices still unresolved after regex+memory
    method_log = {}  # track how each was resolved for debugging

    for i, m in enumerate(materials):
        desc = m.get("description", "")

        # Step 1: Try regex extraction + fuzzy match against memory
        candidates = _quick_regex_extract(desc)
        resolved = False
        best_candidate = ""
        for candidate in candidates:
            matched = _fuzzy_match_vendor(candidate, aliases)
            if matched:
                materials[i]["vendor"] = matched
                vendor_groups.setdefault(matched, []).append(i)
                method_log[i] = "regex+memory"
                resolved = True
                break
            if not best_candidate:
                best_candidate = candidate
        if resolved:
            continue
        if best_candidate:
            # Candidate extracted but not in memory — send to AI for confirmation
            materials[i]["_regex_candidate"] = best_candidate

        # Step 2: Check product hints from vendor_prices history
        item_code = (m.get("item_code") or "").strip()
        normalized = _normalize_product(item_code or desc)
        if normalized and normalized in product_hints:
            hint_vendor = product_hints[normalized]
            canonical = _fuzzy_match_vendor(hint_vendor, aliases) or hint_vendor
            # Only use product hint if no regex candidate contradicts it
            if not best_candidate or best_candidate.lower() in canonical.lower() or canonical.lower() in best_candidate.lower():
                materials[i]["vendor"] = canonical
                vendor_groups.setdefault(canonical, []).append(i)
                method_log[i] = "product_history"
                continue

        # Step 3: If material already has a vendor set, normalize it through memory
        if m.get("vendor"):
            normalized_vendor = _fuzzy_match_vendor(m["vendor"], aliases) or m["vendor"]
            materials[i]["vendor"] = normalized_vendor
            vendor_groups.setdefault(normalized_vendor, []).append(i)
            method_log[i] = "existing"
            continue

        # Unresolved — need AI
        needs_ai.append({
            "index": i,
            "item_code": item_code,
            "description": desc,
            "material_type": m.get("material_type", ""),
            "regex_candidate": materials[i].pop("_regex_candidate", ""),
        })

    # ── AI pass: verify fast-pass results + resolve unknowns ──
    ai_resolved = 0
    ai_corrected = 0

    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")

    if api_key:
        import openai
        client = openai.OpenAI(api_key=api_key)

        # Send ALL materials to AI — fast-pass results shown as "pre-assigned"
        # AI's job: confirm correct ones, correct wrong ones, fill in unknowns
        mat_lines = []
        for i, m in enumerate(materials):
            desc = m.get("description", "")
            item_code = (m.get("item_code") or "").strip()
            vendor = m.get("vendor", "")
            method = method_log.get(i, "")
            regex_cand = m.pop("_regex_candidate", "")
            line = f'{i}. [{item_code}] {desc}'
            if vendor:
                line += f'  [pre-assigned: {vendor} via {method}]'
            elif regex_cand:
                line += f'  [regex candidate: {regex_cand}]'
            else:
                line += '  [UNASSIGNED]'
            mat_lines.append(line)

        # Build vendor catalog context for AI
        catalog_lines = []
        for vname, products in sorted(vendor_catalog.items()):
            # Deduplicate and limit to 10 products per vendor
            unique = list(dict.fromkeys(products))[:10]
            catalog_lines.append(f"  {vname}: {', '.join(unique)}")
        catalog_ctx = "\n".join(catalog_lines) if catalog_lines else "  (no price history yet)"

        prompt = (
            f"You are a commercial flooring industry expert reviewing vendor assignments for a material list.\n\n"
            f"KNOWN VENDORS AND WHAT THEY SELL:\n{catalog_ctx}\n\n"
            f"Other known vendors (no price history yet): "
            f"{', '.join(n for n in known_names if n not in vendor_catalog) or 'None'}\n\n"
            f"MATERIALS TO REVIEW:\n"
            f"{chr(10).join(mat_lines)}\n\n"
            f"YOUR JOB:\n"
            f"1. VERIFY pre-assigned vendors — if the description clearly says a different vendor, CORRECT it\n"
            f"2. FILL IN unassigned items — identify vendor from the description\n"
            f"3. CHECK CONSISTENCY — if 5 items are 'Interface - Woven Gradience' and 1 similar item got assigned differently, flag it\n"
            f"4. USE PRODUCT KNOWLEDGE — match product names/styles to known vendor catalogs above\n"
            f"5. SKIP genuinely generic items (transitions, trims with no vendor name, TBD specs)\n\n"
            f"RULES:\n"
            f"- Description is the source of truth. Format is usually 'ItemCode - VendorName - Product - ...'\n"
            f"- Only OVERRIDE a pre-assigned vendor if you have clear evidence it's wrong\n"
            f"- Include 'evidence': exact text from the description proving the vendor\n"
            f"- For corrections, set 'correction': true and explain WHY in 'reason'\n\n"
            f'Return JSON: {{"results": [{{"index": 0, "vendor": "Name", "evidence": "exact text", "correction": false, "reason": ""}}]}}\n'
            f"Only include items where you're adding a vendor OR correcting a wrong one. Skip confirmed-correct items."
        )

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            result = json.loads(resp.choices[0].message.content)

            detections = result if isinstance(result, list) else next(
                (result[k] for k in ("results", "vendors", "detections", "materials", "data")
                 if k in result and isinstance(result[k], list)), []
            )

            for det in detections:
                idx = det.get("index", -1)
                vendor = (det.get("vendor") or "").strip()
                evidence = (det.get("evidence") or "").strip().lower()
                is_correction = det.get("correction", False)

                if not vendor or idx < 0 or idx >= len(materials):
                    continue

                # Validate: evidence must appear in description
                desc_lower = (materials[idx].get("description") or "").lower()
                vl = vendor.lower()
                evidence_ok = (not evidence or evidence in desc_lower
                               or vl in desc_lower or vl.replace("-", "") in desc_lower.replace("-", ""))

                if not evidence_ok:
                    continue  # AI claim doesn't check out — keep fast-pass result

                canonical = _fuzzy_match_vendor(vendor, aliases) or vendor
                old_vendor = materials[idx].get("vendor", "")

                if is_correction and old_vendor:
                    # AI is overriding fast-pass — remove from old group
                    if old_vendor in vendor_groups and idx in vendor_groups[old_vendor]:
                        vendor_groups[old_vendor].remove(idx)
                        if not vendor_groups[old_vendor]:
                            del vendor_groups[old_vendor]
                    materials[idx]["vendor"] = canonical
                    vendor_groups.setdefault(canonical, []).append(idx)
                    method_log[idx] = "ai_corrected"
                    ai_corrected += 1
                elif not old_vendor:
                    # Filling in an unassigned item
                    materials[idx]["vendor"] = canonical
                    vendor_groups.setdefault(canonical, []).append(idx)
                    method_log[idx] = "ai"
                    ai_resolved += 1

        except Exception as e:
            print(f"AI vendor detection failed: {e}")

    # Clean up any leftover regex candidates
    for m in materials:
        m.pop("_regex_candidate", None)

    # ── Learning: save new vendor-product associations for future jobs ──
    # When AI fills in or corrects a vendor, learn the association
    conn = _get_conn()
    try:
        for i, m in enumerate(materials):
            if method_log.get(i) in ("ai", "ai_corrected") and m.get("vendor"):
                item_code = (m.get("item_code") or "").strip()
                desc = m.get("description", "")
                product_name = desc[:100] if desc else item_code
                normalized = _normalize_product(item_code or desc)
                if normalized:
                    # Check if this product-vendor pair already exists
                    existing = conn.execute(
                        "SELECT id FROM vendor_prices WHERE product_normalized=? AND vendor_name=? LIMIT 1",
                        (normalized, m["vendor"])
                    ).fetchone()
                    if not existing:
                        vendor_id = conn.execute(
                            "SELECT id FROM vendors WHERE name=? LIMIT 1", (m["vendor"],)
                        ).fetchone()
                        conn.execute("""
                            INSERT INTO vendor_prices (product_name, product_normalized, vendor_name, vendor_id, job_id, unit_price, unit, quote_date, notes, created_at)
                            VALUES (?, ?, ?, ?, ?, 0, '', datetime('now'), 'Auto-learned from AI vendor detection', datetime('now'))
                        """, (product_name, normalized, m["vendor"], vendor_id["id"] if vendor_id else None, db_id))
        conn.commit()
    except Exception as e:
        print(f"Learning save failed: {e}")
    finally:
        conn.close()

    # Save updated vendor fields
    save_materials(db_id, materials)

    return {
        "vendor_groups": vendor_groups,
        "total_detected": sum(1 for m in materials if m.get("vendor")),
        "resolved_by": {
            "memory": sum(1 for v in method_log.values() if v in ("regex+memory", "product_history")),
            "existing": sum(1 for v in method_log.values() if v == "existing"),
            "ai": ai_resolved,
            "ai_corrected": ai_corrected,
        },
    }


@app.post("/api/jobs/{job_id}/generate-quote-text")
async def api_generate_quote_text(job_id: str, request: Request):
    """Use AI to generate professional quote request text for a vendor."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = await request.json()
    vendor_name = data.get("vendor_name", "")
    material_indices = data.get("material_indices", [])
    is_follow_up = data.get("follow_up", False)
    days_since_sent = data.get("days_since_sent", 0)

    materials = job.get("materials", [])
    selected = [materials[i] for i in material_indices if 0 <= i < len(materials)]

    # For follow-ups, we don't need materials selected
    if not selected and not is_follow_up:
        raise HTTPException(status_code=400, detail="No materials selected")

    # Get past vendor prices for context
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT product_name, unit_price, unit, created_at
               FROM vendor_prices WHERE vendor_name LIKE ? AND unit_price > 0
               ORDER BY created_at DESC LIMIT 20""",
            (f"%{vendor_name}%",)
        ).fetchall()
        past_prices = [dict(r) for r in rows]
    finally:
        conn.close()

    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")

    import openai
    client = openai.OpenAI(api_key=api_key)

    mat_lines = []
    for i, m in enumerate(selected, 1):
        qty = round((m.get("order_qty") or m.get("installed_qty") or 0) * 100) / 100
        desc = m.get("description", m.get("item_code", "Unknown"))
        item_code = m.get("item_code", "")
        unit = m.get("unit", "")
        mat_lines.append(f"{i}. {desc}\n   Item: {item_code} | Qty: {qty:,.2f} {unit}")

    location_parts = [job.get("address"), job.get("city"), job.get("state"), job.get("zip")]
    location = ", ".join(p for p in location_parts if p)

    past_context = ""
    if past_prices:
        past_context = f"\n\nPast pricing from {vendor_name} (for reference, DO NOT include in the email):\n"
        for pp in past_prices[:5]:
            past_context += f"  - {pp['product_name']}: ${pp['unit_price']}/{pp.get('unit', 'unit')} ({pp.get('created_at', '')[:10]})\n"

    if is_follow_up:
        prompt = f"""Write a polite but firm follow-up email to {vendor_name} regarding a Request for Pricing we sent {days_since_sent} days ago.

Project: {job.get('project_name', '')}
Location: {location}
GC: {job.get('gc_name', '')}

Requirements:
- Reference the original request sent {days_since_sent} days ago
- Politely ask for a status update on pricing
- Mention we need pricing to complete our bid
- Be professional, concise, and not passive-aggressive
- Do NOT include subject line, greeting name, or signature — just the body text
- Keep it to 3-4 sentences"""
    else:
        prompt = f"""Write a professional Request for Pricing email body for a commercial flooring project.
This is being sent to {vendor_name}.

Project: {job.get('project_name', '')}
Architect: {job.get('architect', '')}
Designer: {job.get('designer', '')}
Location: {location}
GC: {job.get('gc_name', '')}

Materials requiring pricing ({len(selected)} items):
{chr(10).join(mat_lines)}
{past_context}

Write a clean, professional email body. Requirements:
- Number each material for easy reference
- Include quantities and units
- Ask for: unit pricing, freight/delivery, lead times, and quote validity period
- Be professional but not overly formal — this is a normal vendor relationship
- Use proper flooring industry terminology
- Keep it concise — vendors receive many of these
- Do NOT include subject line, greeting name, or signature — just the body text
- Start with a brief intro about the project"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content.strip()
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI quote text generation failed: {str(e)}")


@app.post("/api/jobs/{job_id}/suggest-vendors")
async def api_suggest_vendors(job_id: str, request: Request):
    """AI suggests which vendor to contact for unassigned materials based on history."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = await request.json()
    material_indices = data.get("material_indices", [])
    materials = job.get("materials", [])
    unassigned = []
    for i in material_indices:
        if 0 <= i < len(materials):
            m = materials[i]
            unassigned.append({
                "index": i,
                "item_code": m.get("item_code", ""),
                "description": m.get("description", ""),
                "material_type": m.get("material_type", ""),
            })

    if not unassigned:
        return {"suggestions": []}

    # Build vendor history context from vendor_prices
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT vendor_name, product_name, product_normalized, unit_price, unit
               FROM vendor_prices
               WHERE unit_price > 0
               ORDER BY created_at DESC LIMIT 200"""
        ).fetchall()
        vendor_history = {}
        for r in rows:
            vn = r["vendor_name"]
            if vn not in vendor_history:
                vendor_history[vn] = []
            if len(vendor_history[vn]) < 10:
                vendor_history[vn].append(r["product_name"])
    finally:
        conn.close()

    known_vendors = list_vendors()
    vendor_summary = []
    for v in known_vendors:
        products = vendor_history.get(v["name"], [])
        vendor_summary.append(f"- {v['name']}: {', '.join(products[:5]) if products else 'no quote history'}")

    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")

    import openai
    client = openai.OpenAI(api_key=api_key)

    prompt = f"""You are a commercial flooring industry expert. Given these unassigned materials and our vendor history, suggest which vendor to contact for each material.

Unassigned materials:
{chr(10).join(f'{m["index"]}. [{m["item_code"]}] {m["description"]} (type: {m["material_type"]})' for m in unassigned)}

Known vendors and what they've quoted before:
{chr(10).join(vendor_summary) if vendor_summary else 'No vendor history yet.'}

For each material, suggest the most likely vendor based on:
1. Product name/brand recognition (e.g., "Johnsonite" in the name = Johnsonite vendor)
2. Material type (carpet tile → Interface/Shaw, LVT → Shaw/Mannington, rubber base → Johnsonite)
3. Past vendor history matches

Return ONLY a JSON array: [{{"material_index": 0, "suggested_vendor": "Vendor Name", "reason": "brief reason"}}]
If you cannot suggest a vendor, omit that material from the array."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        import json
        result = json.loads(response.choices[0].message.content)
        if isinstance(result, list):
            suggestions = result
        else:
            suggestions = []
            for key in ("suggestions", "results", "data", "result", "materials"):
                if key in result and isinstance(result[key], list):
                    suggestions = result[key]
                    break
            if not suggestions and all(k.isdigit() for k in result.keys()):
                suggestions = [v for _, v in sorted(result.items(), key=lambda x: int(x[0]))]

        return {"suggestions": suggestions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI vendor suggestion failed: {str(e)}")


@app.post("/api/vendors/suggest-contacts")
async def api_suggest_vendor_contacts(request: Request):
    """Use AI to suggest contact info for vendors."""
    data = await request.json()
    vendor_names = data.get("vendor_names", [])
    if not vendor_names:
        return {"suggestions": []}

    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")

    import openai
    client = openai.OpenAI(api_key=api_key)

    prompt = f"""You are a commercial flooring industry expert. For each flooring manufacturer/vendor listed below,
provide helpful contact information and suggestions for finding a sales rep.

Vendors:
{chr(10).join(f'- {name}' for name in vendor_names)}

For each vendor, provide:
1. Their website URL (if a well-known manufacturer)
2. How to find a local sales rep (e.g., "visit interface.com/find-a-rep")
3. A general contact email if publicly known
4. What products they're known for (e.g., "carpet tile", "LVT", "rubber base")
5. Any helpful notes for a flooring estimator

Return ONLY a JSON array:
[{{"vendor": "Name", "website": "url", "find_rep_url": "url or instruction", "general_email": "email or empty", "products": "what they sell", "notes": "helpful tip"}}]"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        import json
        result = json.loads(response.choices[0].message.content)
        suggestions = result if isinstance(result, list) else result.get("suggestions", result.get("vendors", []))
        return {"suggestions": suggestions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI vendor suggestion failed: {str(e)}")


# ── Notifications ────────────────────────────────────────────────────────────

@app.get("/api/notifications")
async def api_get_notifications(unread_only: bool = True):
    return get_notifications(unread_only)


@app.put("/api/notifications/{notification_id}/read")
async def api_mark_notification_read(notification_id: int):
    mark_notification_read(notification_id)
    return {"ok": True}


# ── Activity & Comments ──────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/activity")
def api_get_activity(job_id: str):
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return get_activity(job["id"])


@app.get("/api/jobs/{job_id}/comments")
def api_get_comments(job_id: str):
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return get_comments(job["id"])


class CommentCreate(BaseModel):
    text: str

@app.post("/api/jobs/{job_id}/comments")
def api_add_comment(job_id: str, body: CommentCreate):
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    comment = add_comment(job["id"], body.text)
    log_activity(job["id"], "comment_added", "Comment added", {"text": body.text})
    return comment


# ── Static Files (React frontend) ────────────────────────────────────────────
# Check both dev path (../frontend/dist) and Docker path (./static)
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
static_dir = os.path.join(os.path.dirname(__file__), "static")
_static_root = frontend_dist if os.path.isdir(frontend_dist) else static_dir if os.path.isdir(static_dir) else None

if _static_root:
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=os.path.join(_static_root, "assets")), name="assets")

    # SPA catch-all: serve index.html for any non-API route
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Return 404 for undefined API routes instead of SPA HTML
        if full_path.startswith("api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        # If the file exists in static dir, serve it directly
        file_path = os.path.join(_static_root, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        # Otherwise serve index.html for client-side routing
        return FileResponse(os.path.join(_static_root, "index.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
