"""
FastAPI application for the Standard Interiors Bid Tool.
"""

import os
import shutil
import tempfile
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import (
    init_db, save_job, load_job, list_jobs,
    save_materials, save_sundries, save_labor, save_bundles,
)
from rfms_parser import parse_rfms
from quote_parser import parse_quote_file
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


class MaterialUpdate(BaseModel):
    materials: list[dict]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def api_list_jobs():
    """List all jobs."""
    return list_jobs()


@app.post("/api/jobs")
def api_create_job(job: JobCreate):
    """Create a new job."""
    job_id = save_job(job.model_dump())
    return {"id": job_id, "message": "Job created"}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: int):
    """Get job details with all materials, sundries, labor, bundles."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/upload-rfms")
async def api_upload_rfms(job_id: int, file: UploadFile = File(...)):
    """Upload RFMS pivot table, parse it, return materials."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Save uploaded file
    file_path = os.path.join(UPLOAD_DIR, f"rfms_{job_id}_{file.filename}")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        result = parse_rfms(file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse RFMS file: {e}")

    # Update job info from RFMS if available
    rfms_job_info = result.get("job_info", {})
    job_update = {
        "id": job_id,
        "project_name": rfms_job_info.get("project_name", job["project_name"]),
        "gc_name": rfms_job_info.get("gc_name", job.get("gc_name")),
        "address": rfms_job_info.get("address", job.get("address")),
        "city": rfms_job_info.get("city", job.get("city")),
        "state": rfms_job_info.get("state", job.get("state")),
        "zip": rfms_job_info.get("zip", job.get("zip")),
        "tax_rate": job.get("tax_rate", 0),
        "unit_count": job.get("unit_count", 0),
        "salesperson": job.get("salesperson"),
    }
    save_job(job_update)

    # Prepare materials with waste factors
    materials = []
    for m in result.get("materials", []):
        material_type = m.get("material_type", "unknown")
        waste_pct = WASTE_FACTORS.get(material_type, 0)
        installed_qty = m.get("qty", 0)
        order_qty = installed_qty * (1 + waste_pct)

        materials.append({
            "item_code": m.get("item_code"),
            "description": m.get("description"),
            "material_type": material_type,
            "installed_qty": installed_qty,
            "unit": m.get("unit"),
            "waste_pct": waste_pct,
            "order_qty": round(order_qty, 2),
            "vendor": "",
            "unit_price": 0,
            "extended_cost": 0,
        })

    material_ids = save_materials(job_id, materials)

    # Attach IDs to returned materials
    for mat, mid in zip(materials, material_ids):
        mat["id"] = mid

    return {"job_info": rfms_job_info, "materials": materials}


@app.post("/api/jobs/{job_id}/upload-quotes")
async def api_upload_quotes(job_id: int, files: list[UploadFile] = File(...)):
    """Upload vendor quote files, parse them, return pricing."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    all_products = []
    for upload in files:
        file_path = os.path.join(UPLOAD_DIR, f"quote_{job_id}_{upload.filename}")
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
def api_calculate(job_id: int):
    """Run sundry + labor calculators, return results."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])

    # Calculate sundries
    sundries = calculate_sundries_for_materials(materials)
    save_sundries(job_id, sundries)

    # Calculate labor
    labor_items = calculate_labor_for_materials(materials)
    save_labor(job_id, labor_items)

    return {"sundries": sundries, "labor": labor_items}


@app.put("/api/jobs/{job_id}/materials")
def api_update_materials(job_id: int, body: MaterialUpdate):
    """Update materials (edited pricing, waste, etc.)."""
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Recalculate order qty and extended cost
    updated = []
    for m in body.materials:
        waste_pct = m.get("waste_pct", 0)
        installed_qty = m.get("installed_qty", 0)
        unit_price = m.get("unit_price", 0)
        order_qty = installed_qty * (1 + waste_pct)
        extended_cost = order_qty * unit_price

        m["order_qty"] = round(order_qty, 2)
        m["extended_cost"] = round(extended_cost, 2)
        updated.append(m)

    material_ids = save_materials(job_id, updated)
    for mat, mid in zip(updated, material_ids):
        mat["id"] = mid

    return {"materials": updated}


@app.post("/api/jobs/{job_id}/generate-bid")
def api_generate_bid(job_id: int):
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
    save_bundles(job_id, bid_data["bundles"])

    # Generate PDF
    pdf_path = os.path.join(PDF_DIR, f"bid_{job_id}.pdf")
    generate_bid_pdf(bid_data, pdf_path)

    return bid_data


@app.get("/api/jobs/{job_id}/bid.pdf")
def api_download_bid_pdf(job_id: int):
    """Download the generated bid PDF."""
    pdf_path = os.path.join(PDF_DIR, f"bid_{job_id}.pdf")
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


# ── Static Files (React frontend) ────────────────────────────────────────────
# Check both dev path (../frontend/dist) and Docker path (./static)
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
elif os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
