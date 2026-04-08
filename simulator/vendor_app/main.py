"""
SI Bid Tool — Vendor Simulator
A standalone FastAPI app (port 8100) that simulates an AI-powered vendor.
Receives quote requests via .eml files and responds with realistic pricing.
"""

import json
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from email import policy
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import email as email_lib
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Paths ────────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).parent.resolve()
SIM_DB_PATH = APP_DIR / "sim_data.db"
SI_DB_PATH = (APP_DIR / "../../server/si_bid_tool.db").resolve()
VENDOR_INBOX = (APP_DIR / "../mailbox/vendor_inbox").resolve()
BIDTOOL_INBOX = (APP_DIR / "../mailbox/bidtool_inbox").resolve()
STATIC_DIR = APP_DIR / "static"

# ── AI Settings (read from SI Bid Tool DB) ───────────────────────────────────

_ai_settings: dict = {}
_ai_settings_lock = threading.Lock()


def _load_ai_settings():
    """Read API keys and model from the SI Bid Tool database.
    Returns True if at least one AI key was found."""
    global _ai_settings
    if not SI_DB_PATH.exists():
        print(f"[VendorSim] WARNING: SI Bid Tool DB not found at {SI_DB_PATH}")
        return False
    try:
        conn = sqlite3.connect(str(SI_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT key, value FROM app_settings "
            "WHERE key IN ('openai_api_key', 'openai_model', 'anthropic_api_key')"
        ).fetchall()
        conn.close()
        with _ai_settings_lock:
            _ai_settings.update({row["key"]: row["value"] for row in rows})
        provider = "Anthropic" if _ai_settings.get("anthropic_api_key") else (
            "OpenAI" if _ai_settings.get("openai_api_key") else "None"
        )
        print(f"[VendorSim] AI settings loaded — provider: {provider}, "
              f"model: {_ai_settings.get('openai_model', 'gpt-5-mini')}")
        return provider != "None"
    except Exception as e:
        print(f"[VendorSim] Error loading AI settings: {e}")
        return False


# ── Model Mapping ────────────────────────────────────────────────────────────

_ANTHROPIC_MODEL_MAP = {
    "gpt-5-mini": "claude-sonnet-4-20250514",
    "gpt-5.4": "claude-sonnet-4-20250514",
}


# ── Lightweight AI Chat Completion ───────────────────────────────────────────

def _chat_complete(system: str, user: str, json_mode: bool = False) -> str:
    """
    Call OpenAI or Anthropic API directly via httpx.
    Uses whichever key is available from SI Bid Tool settings.
    """
    with _ai_settings_lock:
        anthropic_key = _ai_settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        openai_key = _ai_settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
        model = _ai_settings.get("openai_model", "gpt-5-mini")

    if anthropic_key:
        return _anthropic_complete(anthropic_key, system, user, model, json_mode)
    elif openai_key:
        return _openai_complete(openai_key, system, user, model, json_mode)
    else:
        raise RuntimeError(
            "No AI API key available. Set openai_api_key or anthropic_api_key "
            "in SI Bid Tool Settings."
        )


def _anthropic_complete(
    api_key: str, system: str, user: str, model: str, json_mode: bool
) -> str:
    """Call Anthropic Messages API via httpx."""
    mapped_model = _ANTHROPIC_MODEL_MAP.get(model, "claude-sonnet-4-20250514")

    effective_system = system
    if json_mode:
        effective_system = (
            system
            + "\n\nIMPORTANT: Return ONLY valid JSON. No markdown, no code fences, no explanation."
        )

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": mapped_model,
            "max_tokens": 4096,
            "system": effective_system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    content = resp.json()["content"][0]["text"]

    # Strip markdown code fences if present
    if json_mode and content.startswith("```"):
        lines = content.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        elif lines[0].startswith("```"):
            lines = lines[1:]
        content = "\n".join(lines)

    return content


def _openai_complete(
    api_key: str, system: str, user: str, model: str, json_mode: bool
) -> str:
    """Call OpenAI Chat Completions API via httpx."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-type": "application/json",
        },
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── sim_data.db Setup ────────────────────────────────────────────────────────

def _init_sim_db():
    """Create the simulator database and requests table."""
    conn = sqlite3.connect(str(SIM_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eml_file TEXT,
            vendor_name TEXT,
            vendor_email TEXT,
            from_email TEXT,
            subject TEXT,
            body TEXT,
            job_id TEXT,
            materials_json TEXT,
            reply_body TEXT,
            reply_products_json TEXT,
            status TEXT DEFAULT 'pending',
            received_at TEXT,
            replied_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    print(f"[VendorSim] Database ready at {SIM_DB_PATH}")


def _get_sim_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SIM_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ── Vendor Name Extraction ───────────────────────────────────────────────────

# Known vendor domain → display name mappings
_VENDOR_DOMAINS = {
    "interface": "Interface",
    "shaw": "Shaw",
    "mohawk": "Mohawk",
    "mannington": "Mannington",
    "tarkett": "Tarkett",
    "armstrong": "Armstrong",
    "daltile": "Daltile",
    "msi": "MSI",
    "schluter": "Schluter",
    "laticrete": "Laticrete",
    "mapei": "MAPEI",
    "ardex": "Ardex",
    "johnsonite": "Johnsonite",
    "roppe": "Roppe",
    "nora": "Nora",
    "ecore": "Ecore",
    "patcraft": "Patcraft",
    "jjhaines": "J&J Haines",
    "fcifloors": "FCI Floors",
}


def _extract_vendor_name(to_email: str) -> str:
    """Extract vendor name from email address domain.
    e.g. 'rep@interface.com' -> 'Interface'
    """
    match = re.search(r"@([\w.-]+)\.", to_email.lower())
    if match:
        domain_key = match.group(1).split(".")[-1] if "." in match.group(1) else match.group(1)
        # Check known vendors
        for key, name in _VENDOR_DOMAINS.items():
            if key in domain_key:
                return name
        # Fallback: capitalize the domain
        return domain_key.capitalize()
    return "Unknown Vendor"


def _extract_email_addr(header: str) -> str:
    """Extract bare email address from a header like 'Name <addr@example.com>'."""
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", header)
    return match.group(0) if match else header


# ── VendorInboxWatcher ───────────────────────────────────────────────────────

class VendorInboxWatcher(threading.Thread):
    """Daemon thread that polls vendor_inbox/ for new .eml files,
    parses them, saves to sim_data.db, and moves to processed/."""

    def __init__(self, poll_interval: int = 3):
        super().__init__(daemon=True, name="vendor-inbox-watcher")
        self._interval = poll_interval
        self._running = False

    def run(self):
        self._running = True
        print(f"[VendorInboxWatcher] Started — watching {VENDOR_INBOX}")
        # Ensure directories exist
        for d in [VENDOR_INBOX, VENDOR_INBOX / "processed"]:
            d.mkdir(parents=True, exist_ok=True)

        while self._running:
            try:
                self._poll()
            except Exception as e:
                print(f"[VendorInboxWatcher] Error: {e}")
            # Sleep in small increments for responsive shutdown
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)

    def stop(self):
        self._running = False

    def _poll(self):
        eml_files = sorted(VENDOR_INBOX.glob("*.eml"))
        if not eml_files:
            return

        print(f"[VendorInboxWatcher] Found {len(eml_files)} new .eml file(s)")
        for eml_path in eml_files:
            try:
                self._process_eml(eml_path)
            except Exception as e:
                print(f"[VendorInboxWatcher] Error processing {eml_path.name}: {e}")

    def _process_eml(self, eml_path: Path):
        """Parse a single .eml file and save as a pending request."""
        with open(eml_path, "rb") as f:
            msg = email_lib.message_from_binary_file(f, policy=policy.default)

        from_header = str(msg.get("From", ""))
        to_header = str(msg.get("To", ""))
        subject = str(msg.get("Subject", ""))
        job_id = str(msg.get("X-SI-Job-Id", ""))

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_content()
                    break
        else:
            body = msg.get_content() if hasattr(msg, "get_content") else msg.get_payload(decode=True).decode("utf-8", errors="replace")

        from_email = _extract_email_addr(from_header)
        vendor_email = _extract_email_addr(to_header)
        vendor_name = _extract_vendor_name(to_header)

        # Try to extract materials from body (lines that look like product specs)
        materials_json = self._extract_materials(body)

        # Save to database
        conn = _get_sim_conn()
        conn.execute(
            """INSERT INTO requests
               (eml_file, vendor_name, vendor_email, from_email, subject, body,
                job_id, materials_json, status, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                eml_path.name,
                vendor_name,
                vendor_email,
                from_email,
                subject,
                body,
                job_id,
                materials_json,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        conn.close()

        # Move to processed
        dest = VENDOR_INBOX / "processed" / eml_path.name
        shutil.move(str(eml_path), str(dest))
        print(f"[VendorInboxWatcher] Saved request from {from_email} to {vendor_name} (job={job_id})")

    def _extract_materials(self, body: str) -> str:
        """Best-effort extraction of material lines from the email body."""
        materials = []
        for line in body.splitlines():
            line = line.strip()
            # Look for lines that contain quantity indicators or product-like patterns
            if re.search(r"\b(SF|SY|LF|EA|BOX|CTN|ROLL|PAIL|GAL)\b", line, re.IGNORECASE):
                materials.append(line)
            elif re.search(r"\b\d+\s*(sq\.?\s*ft|sq\.?\s*yd|linear\s*ft)\b", line, re.IGNORECASE):
                materials.append(line)
        return json.dumps(materials) if materials else "[]"


# ── Pydantic Models ──────────────────────────────────────────────────────────

class SendReplyBody(BaseModel):
    reply_body: Optional[str] = None


# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(title="SI Bid Tool — Vendor Simulator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Watcher reference
_watcher: Optional[VendorInboxWatcher] = None


_ai_retry_status = "idle"  # idle | retrying | loaded | gave_up


def _retry_ai_settings():
    """Background thread: retry loading AI settings every 5s until found."""
    global _ai_retry_status
    _ai_retry_status = "retrying"
    for attempt in range(24):  # up to 2 minutes
        time.sleep(5)
        if _load_ai_settings():
            _ai_retry_status = "loaded"
            print("[VendorSim] AI settings loaded on retry")
            return
    _ai_retry_status = "gave_up"
    print("[VendorSim] WARNING: gave up waiting for AI settings after 2 minutes")


@app.on_event("startup")
def startup():
    global _watcher
    print("=" * 60)
    print("  SI Bid Tool — Vendor Simulator")
    print("  http://localhost:8100")
    print("=" * 60)

    has_ai = _load_ai_settings()
    _init_sim_db()

    # If no AI keys yet (bid tool DB not ready), retry in background
    if not has_ai:
        print("[VendorSim] No AI keys found — will retry in background until bid tool DB is ready")
        threading.Thread(target=_retry_ai_settings, daemon=True, name="ai-settings-retry").start()

    # Ensure mailbox dirs
    for d in [VENDOR_INBOX, VENDOR_INBOX / "processed",
              BIDTOOL_INBOX, BIDTOOL_INBOX / "processed"]:
        d.mkdir(parents=True, exist_ok=True)

    _watcher = VendorInboxWatcher(poll_interval=3)
    _watcher.start()


@app.on_event("shutdown")
def shutdown():
    if _watcher:
        _watcher.stop()
    print("[VendorSim] Shutdown complete")


# ── Helper: row to dict ─────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Parse JSON fields for the response
    for field in ("materials_json", "reply_products_json"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/")
def serve_index():
    """Serve the simulator dashboard."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse(
        {"message": "Vendor Simulator API is running. Place index.html in static/ for the dashboard."},
        status_code=200,
    )


@app.get("/api/requests")
def list_requests():
    """List all quote requests, newest first."""
    conn = _get_sim_conn()
    rows = conn.execute("SELECT * FROM requests ORDER BY received_at DESC").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@app.get("/api/requests/{request_id}")
def get_request(request_id: int):
    """Get a single quote request by ID."""
    conn = _get_sim_conn()
    row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    return _row_to_dict(row)


@app.post("/api/requests/{request_id}/generate-reply")
def generate_reply(request_id: int):
    """Use AI to generate realistic vendor pricing for a quote request."""
    conn = _get_sim_conn()
    row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Request not found")

    req = dict(row)
    conn.close()

    vendor_name = req["vendor_name"] or "Unknown Vendor"
    subject = req["subject"] or ""
    body = req["body"] or ""
    materials = req["materials_json"] or "[]"

    system_prompt = f"""You are a sales representative at {vendor_name}, a commercial flooring manufacturer/distributor.
You received a quote request from a flooring contractor (Standard Interiors).
Generate a realistic vendor quote reply with commercial flooring pricing.

Your reply should include:
1. A professional email body greeting the contractor, referencing their project
2. A products array with realistic pricing

Return JSON in this exact format:
{{
  "reply_body": "Professional email reply text here...",
  "products": [
    {{
      "product_name": "Product Style Name",
      "product_spec": "Color / Pattern details",
      "unit": "SF or SY or LF or EA",
      "unit_price": 0.00,
      "lead_time": "2-3 weeks"
    }}
  ]
}}

Pricing guidelines for realism:
- Carpet tile: $8-28/SY
- Broadloom carpet: $12-45/SY
- LVT/LVP: $1.50-4.50/SF
- Porcelain floor tile: $2.00-8.00/SF
- Wall tile: $3.00-12.00/SF
- Rubber base: $0.60-1.80/LF
- Sheet rubber: $4.00-9.00/SF
- VCT: $0.60-1.20/SF
- Hardwood: $4.00-12.00/SF
- Transitions/trim: $2.50-8.00/LF

Include 2-5 products based on what was requested. Use realistic brand-appropriate style names."""

    user_msg = f"Subject: {subject}\n\nEmail body:\n{body}\n\nExtracted material lines:\n{materials}"

    try:
        raw = _chat_complete(system_prompt, user_msg, json_mode=True)
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI returned invalid JSON: {raw[:500]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI call failed: {str(e)}")

    reply_body = result.get("reply_body", "")
    products = result.get("products", [])

    # Save to database
    conn = _get_sim_conn()
    conn.execute(
        """UPDATE requests
           SET reply_body = ?, reply_products_json = ?, status = 'generated'
           WHERE id = ?""",
        (reply_body, json.dumps(products), request_id),
    )
    conn.commit()
    conn.close()

    return {"reply_body": reply_body, "products": products}


@app.post("/api/requests/{request_id}/send-reply")
def send_reply(request_id: int, payload: SendReplyBody = None):
    """Send the generated reply back to the bid tool.
    Writes .eml to bidtool_inbox/ AND tries SMTP to localhost:2525.
    """
    conn = _get_sim_conn()
    row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Request not found")

    req = dict(row)

    # Use custom reply_body if provided, otherwise use the generated one
    reply_body = (payload.reply_body if payload and payload.reply_body else req.get("reply_body")) or ""
    if not reply_body:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="No reply body available. Generate a reply first or provide reply_body.",
        )

    # Build the reply email
    vendor_email = req["vendor_email"] or "vendor@example.com"
    from_email = req["from_email"] or "estimating@standardinteriors.com"
    original_subject = req["subject"] or "Quote Request"
    job_id = req["job_id"] or ""

    reply_subject = f"Re: {original_subject}" if not original_subject.startswith("Re:") else original_subject

    # Include product table in body if we have products
    full_body = reply_body
    if req.get("reply_products_json"):
        try:
            products = json.loads(req["reply_products_json"])
            if products:
                full_body += "\n\n--- PRICING ---\n"
                for p in products:
                    name = p.get("product_name", "")
                    spec = p.get("product_spec", "")
                    unit = p.get("unit", "")
                    price = p.get("unit_price", 0)
                    lead = p.get("lead_time", "")
                    full_body += f"\n{name} — {spec}\n  ${price:.2f}/{unit}  |  Lead time: {lead}\n"
        except (json.JSONDecodeError, TypeError):
            pass

    msg = MIMEText(full_body, "plain")
    msg["From"] = f"{req['vendor_name']} <{vendor_email}>"
    msg["To"] = from_email
    msg["Subject"] = reply_subject
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    if job_id:
        msg["X-SI-Job-Id"] = str(job_id)

    eml_content = msg.as_string()

    # Write .eml directly to bidtool_inbox/ (no SMTP — avoids duplicate delivery
    # since the relay would route it right back to the same folder)
    BIDTOOL_INBOX.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_vendor = re.sub(r"[^a-zA-Z0-9_-]", "_", req["vendor_name"] or "vendor")
    eml_filename = f"{timestamp}_{safe_vendor}_reply.eml"
    eml_path = BIDTOOL_INBOX / eml_filename
    eml_path.write_text(eml_content, encoding="utf-8")
    print(f"[VendorSim] Reply .eml written to {eml_path}")

    # Update database
    conn.execute(
        """UPDATE requests
           SET reply_body = ?, status = 'sent', replied_at = ?
           WHERE id = ?""",
        (reply_body, datetime.now(timezone.utc).isoformat(), request_id),
    )
    conn.commit()
    conn.close()

    return {
        "status": "sent",
        "eml_file": eml_filename,
        "reply_subject": reply_subject,
    }


_reply_all_status = {"running": False, "processed": 0, "total": 0, "errors": 0}
_reply_all_lock = threading.Lock()


@app.post("/api/requests/reply-all")
def reply_all():
    """Generate AI reply and send for ALL pending requests (background thread)."""
    if _reply_all_status["running"]:
        return {"message": "Already processing", **_reply_all_status}

    conn = _get_sim_conn()
    rows = conn.execute(
        "SELECT id FROM requests WHERE status = 'pending' ORDER BY received_at ASC"
    ).fetchall()
    conn.close()

    if not rows:
        return {"processed": 0, "total": 0, "results": [], "message": "No pending requests"}

    ids = [row["id"] for row in rows]
    with _reply_all_lock:
        _reply_all_status.update({"running": True, "processed": 0, "total": len(ids), "errors": 0})

    def _process():
        for rid in ids:
            try:
                generate_reply(rid)
                send_reply(rid)
                with _reply_all_lock:
                    _reply_all_status["processed"] += 1
            except Exception as e:
                with _reply_all_lock:
                    _reply_all_status["processed"] += 1
                    _reply_all_status["errors"] += 1
                print(f"[VendorSim] Reply-all error for #{rid}: {e}")
        with _reply_all_lock:
            _reply_all_status["running"] = False
        print(f"[VendorSim] Reply-all complete: {_reply_all_status['processed']}/{_reply_all_status['total']}, "
              f"{_reply_all_status['errors']} errors")

    threading.Thread(target=_process, daemon=True, name="reply-all").start()
    return {"message": "Processing started", "total": len(ids)}


@app.get("/api/requests/reply-all/status")
def reply_all_status():
    """Poll progress of a reply-all operation."""
    with _reply_all_lock:
        return dict(_reply_all_status)


@app.get("/api/status")
def health_check():
    """Health check with request counts."""
    conn = _get_sim_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM requests").fetchone()["c"]
    pending = conn.execute("SELECT COUNT(*) as c FROM requests WHERE status = 'pending'").fetchone()["c"]
    generated = conn.execute("SELECT COUNT(*) as c FROM requests WHERE status = 'generated'").fetchone()["c"]
    sent = conn.execute("SELECT COUNT(*) as c FROM requests WHERE status = 'sent'").fetchone()["c"]
    conn.close()

    anthropic_key = bool(_ai_settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY"))
    openai_key = bool(_ai_settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY"))

    return {
        "status": "running",
        "watcher_active": _watcher is not None and _watcher.is_alive(),
        "ai_available": anthropic_key or openai_key,
        "ai_provider": "anthropic" if anthropic_key else ("openai" if openai_key else "none"),
        "ai_retry_status": _ai_retry_status,
        "model": _ai_settings.get("openai_model", "gpt-5-mini"),
        "counts": {
            "total": total,
            "pending": pending,
            "generated": generated,
            "sent": sent,
        },
        "paths": {
            "vendor_inbox": str(VENDOR_INBOX),
            "bidtool_inbox": str(BIDTOOL_INBOX),
            "sim_db": str(SIM_DB_PATH),
        },
    }


# ── Mount static files (after API routes so they don't shadow) ───────────────

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8100,
        reload=True,
        reload_dirs=[str(APP_DIR)],
    )
