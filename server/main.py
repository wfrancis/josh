"""
FastAPI application for the Standard Interiors Bid Tool.
"""

import csv
import io
import os
import shutil
import tempfile
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import (
    init_db, save_job, load_job, list_jobs, delete_job,
    save_materials, save_sundries, save_labor, save_bundles,
    save_quotes, delete_quotes, search_all,
    get_settings, save_settings,
    save_labor_catalog_entries, get_labor_catalog_entries,
    save_price_list_entries, add_price_list_entry, update_price_list_entry,
    delete_price_list_entry, get_price_list_entries,
    get_company_rate, save_company_rate, get_all_company_rates,
)
from rfms_parser import parse_rfms, ai_merge_materials
from quote_parser import parse_quote_file, set_openai_config
from sundry_calc import calculate_sundries_for_materials
from labor_calc import calculate_labor_for_materials, load_labor_catalog, load_labor_catalog_from_pdf, get_labor_catalog
from bid_assembler import assemble_bid
from pdf_generator import generate_bid_pdf
from config import WASTE_FACTORS, SUNDRY_RULES, FREIGHT_RATES, LABOR_QTY_RULES, EXCLUSIONS_TEMPLATE

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


@app.on_event("startup")
def startup():
    init_db()
    _apply_openai_config()
    _seed_company_rates()


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
    return {"id": job_id, "slug": created.get("slug", ""), "message": "Job created"}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    """Get job details by ID or slug."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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
    return {"id": new_id, "slug": created.get("slug", "")}


@app.put("/api/jobs/{job_id}/notes")
def api_update_notes(job_id: str, body: NotesUpdate):
    """Update job notes."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["notes"] = body.notes
    save_job(job)
    return {"message": "Notes saved"}


class JobUpdate(BaseModel):
    markup_pct: Optional[float] = None
    project_name: Optional[str] = None
    gc_name: Optional[str] = None
    tax_rate: Optional[float] = None
    unit_count: Optional[int] = None
    salesperson: Optional[str] = None

@app.put("/api/jobs/{job_id}")
def api_update_job(job_id: str, body: JobUpdate):
    """Update job fields."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    updates = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        job[key] = val
    save_job(job)
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

        materials.append({
            "item_code": m.get("item_code"),
            "description": m.get("description"),
            "material_type": material_type,
            "installed_qty": installed_qty,
            "unit": m.get("unit"),
            "waste_pct": waste_pct,
            "order_qty": round(order_qty, 2),
            "vendor": vendor,
            "unit_price": unit_price,
            "extended_cost": round(unit_price * round(order_qty, 2), 2),
            "ai_confidence": m.get("ai_confidence"),
        })

    material_ids = save_materials(db_id, materials)

    # Attach IDs to returned materials
    for mat, mid in zip(materials, material_ids):
        mat["id"] = mid

    return {"job_info": rfms_job_info, "materials": materials}


def _auto_match_quotes(job_id: int, products: list[dict]) -> int:
    """Try to match parsed quote products to existing materials by item_code."""
    job = load_job(job_id)
    if not job:
        return 0
    materials = job.get("materials", [])
    if not materials:
        return 0

    matched = 0
    updated = False
    for mat in materials:
        if mat.get("unit_price", 0) > 0:
            continue  # Already priced, don't overwrite
        item_code = (mat.get("item_code") or "").strip().lower()
        description = (mat.get("description") or "").strip().lower()
        if not item_code and not description:
            continue

        for prod in products:
            if prod.get("error") or not prod.get("unit_price"):
                continue
            prod_name = (prod.get("product_name") or "").strip().lower()
            prod_desc = (prod.get("description") or "").strip().lower()

            # Match if item_code appears in product name/description
            match = False
            if item_code and len(item_code) >= 3:
                if item_code in prod_name or item_code in prod_desc:
                    match = True

            if match:
                mat["unit_price"] = prod["unit_price"]
                mat["vendor"] = prod.get("vendor", "")
                order_qty = mat.get("order_qty", 0)
                mat["extended_cost"] = round(order_qty * mat["unit_price"], 2)
                matched += 1
                updated = True
                break

    if updated:
        save_materials(job_id, materials)

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

    return {"products": all_products, "auto_matched": auto_matched}


@app.delete("/api/jobs/{job_id}/quotes")
def api_clear_quotes(job_id: str):
    """Clear all parsed quotes for a job."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    delete_quotes(job["id"])
    return {"message": "Quotes cleared"}


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

        # Trust order_qty from frontend if provided and > 0
        frontend_order_qty = m.get("order_qty")
        if frontend_order_qty and frontend_order_qty > 0:
            order_qty = frontend_order_qty
        else:
            order_qty = installed_qty * (1 + waste_pct)

        extended_cost = order_qty * unit_price

        merged["order_qty"] = round(order_qty, 2)
        merged["extended_cost"] = round(extended_cost, 2)
        updated.append(merged)

    material_ids = save_materials(job["id"], updated)
    for mat, mid in zip(updated, material_ids):
        mat["id"] = mid

    return {"materials": updated}


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
    if updates:
        save_settings(updates)
        # Apply API key and model to quote parser
        settings = get_settings()
        _apply_openai_config(settings)
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
        # If the file exists in static dir, serve it directly
        file_path = os.path.join(_static_root, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        # Otherwise serve index.html for client-side routing (no cache so deploys are instant)
        return FileResponse(os.path.join(_static_root, "index.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
