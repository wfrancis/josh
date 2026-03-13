"""
FastAPI application for the Standard Interiors Bid Tool.
"""

import os
import shutil
import tempfile
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import (
    init_db, save_job, load_job, list_jobs, delete_job,
    save_materials, save_sundries, save_labor, save_bundles,
    get_settings, save_settings,
)
from rfms_parser import parse_rfms, ai_merge_materials
from quote_parser import parse_quote_file, set_openai_config
from sundry_calc import calculate_sundries_for_materials
from labor_calc import calculate_labor_for_materials, load_labor_catalog
from bid_assembler import assemble_bid
from pdf_generator import generate_bid_pdf
from config import WASTE_FACTORS

# ── App Setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="SI Bid Tool", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
PDF_DIR = os.path.join(os.path.dirname(__file__), "generated_pdfs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)


@app.on_event("startup")
def startup():
    init_db()
    _apply_openai_config()


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


@app.put("/api/jobs/{job_id}/notes")
def api_update_notes(job_id: str, body: NotesUpdate):
    """Update job notes."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["notes"] = body.notes
    save_job(job)
    return {"message": "Notes saved"}


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

    # Apply waste factors to the final merged list
    materials = []
    for m in merged_raw:
        material_type = m.get("material_type", "unknown")
        waste_pct = WASTE_FACTORS.get(material_type, 0)
        installed_qty = m.get("installed_qty", m.get("qty", 0))
        order_qty = installed_qty * (1 + waste_pct)

        materials.append({
            "item_code": m.get("item_code"),
            "description": m.get("description"),
            "material_type": material_type,
            "installed_qty": installed_qty,
            "unit": m.get("unit"),
            "waste_pct": waste_pct,
            "order_qty": round(order_qty, 2),
            "vendor": m.get("vendor", ""),
            "unit_price": m.get("unit_price", 0),
            "extended_cost": round(m.get("unit_price", 0) * round(order_qty, 2), 2),
        })

    material_ids = save_materials(db_id, materials)

    # Attach IDs to returned materials
    for mat, mid in zip(materials, material_ids):
        mat["id"] = mid

    return {"job_info": rfms_job_info, "materials": materials}


@app.post("/api/jobs/{job_id}/upload-quotes")
async def api_upload_quotes(job_id: str, files: list[UploadFile] = File(...)):
    """Upload vendor quote files, parse them, return pricing."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    all_products = []
    for upload in files:
        file_path = os.path.join(UPLOAD_DIR, f"quote_{job['id']}_{upload.filename}")
        with open(file_path, "wb") as f:
            content = await upload.read()
            f.write(content)

        try:
            products = parse_quote_file(file_path)
            all_products.extend(products)
        except Exception as e:
            all_products.append({"error": str(e), "file": upload.filename})

    return {"products": all_products}


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

        waste_pct = merged.get("waste_pct", 0)
        installed_qty = merged.get("installed_qty", 0)
        unit_price = merged.get("unit_price", 0)
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
    }

    bid_data = assemble_bid(job_info, materials, sundries, labor_items)

    # Save bundles
    save_bundles(job["id"], bid_data["bundles"])

    # Generate PDF
    pdf_path = os.path.join(PDF_DIR, f"bid_{job['id']}.pdf")
    generate_bid_pdf(bid_data, pdf_path)

    return bid_data


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
    """Upload labor catalog Excel file."""
    file_path = os.path.join(UPLOAD_DIR, f"labor_catalog_{file.filename}")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        catalog = load_labor_catalog(file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse labor catalog: {e}")

    return {"message": "Labor catalog loaded", "entries": len(catalog)}


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
        "multi_pass_count": int(settings.get("multi_pass_count", "3")),
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
    passes = int(settings.get("multi_pass_count", "3"))
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
