"""
FastAPI application for the Standard Interiors Bid Tool.
"""

import asyncio
import copy
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from collections import deque
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

try:
    import fcntl
except ImportError:  # Windows dev machines have no fcntl.
    fcntl = None

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Body, Depends
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection

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
    record_imported_file, list_imported_files, record_job_artifact, list_job_artifacts,
    log_activity, get_activity, add_comment, get_comments,
    create_quote_request, list_quote_requests, update_quote_request, delete_quote_request,
    _normalize_product, _get_conn,
    import_price_book, search_price_book, match_price_book, get_price_book_summary,
    list_rules, get_rule, create_rule, update_rule, delete_rule,
    archive_rule, list_rule_versions,
    list_ruleset_versions, get_ruleset_version, rollback_ruleset_version,
    get_active_rules, seed_rules_registry_defaults,
    create_calculation_run, save_calculation_traces, complete_calculation_run,
    list_calculation_runs, get_latest_completed_calculation_run, get_calculation_traces,
    get_first_calculation_run_started_at,
    record_material_price_decision, list_material_price_decisions,
    upsert_golden_job, get_golden_job_for_source, get_golden_replay,
    save_golden_replay, list_golden_replays_for_job, list_golden_replays_for_version,
    get_latest_golden_replay_for_version,
    JOB_ESTIMATE_HEADER_FIELDS,
    seed_default_users, authenticate_user, create_session, get_session, get_session_user,
    delete_session, list_online_users, set_current_user, reset_current_user,
    set_audit_context, reset_audit_context, DB_PATH,
    SESSION_LIFETIME_DAYS, session_id_for_token, set_audit_session, insert_labor_catalog_entry,
    merge_vendors,
    UserAdminError, create_user, ensure_admin_user, list_users_for_admin, remove_user,
    restore_user, reset_user_pin, update_user, list_admin_log,
    list_bid_tracker_jobs, get_bid_tracker_job, list_bid_events, save_bid_tracking,
    get_latest_job_artifact, get_job_artifact,
    clean_delete_reason, restore_job, list_deleted_jobs,
)
from bid_tracker import (
    BID_STATUSES, DECIDED_BID_STATUSES, FIELD_LABELS as BID_FIELD_LABELS,
    MAX_FUTURE_SENT_DAYS, MAX_NOTE_LENGTH, MAX_REASON_LENGTH, MAX_SHORT_TEXT_LENGTH,
    POSTABLE_BID_EVENT_TYPES,
    clean_sent_to, clean_text, clean_tracking_fields, decorate_bid_row,
    effective_bid_status, parse_date, parse_money, resolve_today,
    status_change_updates, summarize_bids,
)
from rfms_parser import infer_material_type_fallback, label_uploaded_lines, merge_reupload_materials, parse_rfms
from quote_parser import (
    MAX_QUOTE_FILE_BYTES,
    parse_quote_file,
    quote_multipass_audit_contract,
    set_openai_config,
)
from dropbox_scanner import match_folder
from sundry_calc import calculate_sundries_for_materials
from labor_calc import LABOR_RULES, calculate_labor_for_materials, labor_line_values, load_labor_catalog, load_labor_catalog_from_pdf, get_labor_catalog
from bid_assembler import assemble_bid
from pdf_generator import generate_bid_pdf, generate_proposal_pdf
from proposal_bundler import generate_proposal_data
from proposal_totals import effective_bundle_total, normalize_proposal_totals
from material_pricing import (
    is_piece_priced_transition,
    material_pricing_context,
    order_qty_holds_sticks as _shared_order_qty_holds_sticks,
    order_qty_is_lf as _shared_order_qty_is_lf,
    transition_pieces as _shared_transition_pieces,
)
from quote_evidence import find_verified_quote_price_conflicts, normalize_quote_unit
from reproducibility import (
    DEFAULT_TOLERANCE,
    apply_accepted_bundle_structure,
    apply_accepted_numeric_edits,
    make_golden_snapshot,
    replay_golden_job,
)
from config import WASTE_FACTORS, SUNDRY_RULES, FREIGHT_RATES, LABOR_QTY_RULES, EXCLUSIONS_TEMPLATE, STAIR_SUNDRY_KITS
from config import QUOTE_EMAILS_ENABLED, QUOTE_EMAILS_OFF_DETAIL
from email_agent import compose_quote_request, send_email, generate_quote_request_text
from ai_client import AIError, DEFAULT_MODEL, MODEL_OPTIONS, chat_complete, get_provider_info
from inbox_monitor import InboxMonitor
from audit_engine import AuditTraceBuilder
import audit
from audit import AuditBackstopMiddleware, audit_route, no_audit, system_context
from job_writes import JobWriteError, resolve_job_ref
# Deleted bids are read-only: every change to one is refused with 410.
from job_writes import JobDeletedError, deleted_bid_info, deleted_bid_message, deleted_job_row
# Changes that touch several bids at once (vendor merge) take each bid's lock.
from job_writes import JobBusyError, LOCK_WAIT_SECONDS, job_lock
# Bid writes (jobs, bid tracking, uploads, materials, bid, proposal): locked,
# versioned and audited through job_write / entity_write.
from job_writes import (
    JobNotFoundError, ProposalConflictError,
    entity_write, job_write, load_job_snapshot, create_job as create_job_row,
    update_job_fields, set_proposal_data, set_bid_data,
)
from build_info import build_manifest_for_snapshot, get_build_info
from readiness import evaluate_job_readiness, is_valid_material_classification, proposal_math_errors, proposal_check_message
from readiness import (
    CLICK_REGENERATE, GRAND_TOTAL_MISMATCH, JOB_FIELD_LABELS, NO_BID_YET, REVIEW_STEP,
    amount_word, plain_list, totals_changed_message,
)
# Line pricing shared by every materials path, and compare-and-swap saves for
# slow steps (AI quote matching, vendor detection, price estimates).
from pricing_rows import (
    apply_material_patches, conflict_note, material_patch, normalize_material_row, patches_from_rows,
)
# Stable ids: material uids, sundry/labor line keys, proposal bundle uids.
import stable_ids
# Proposal versions: saved copies of the proposal to compare and restore.
import proposal_versions

# ── Deleted bids are read-only ───────────────────────────────────────────────
# Write routes with {job_id} in the path that still work on a deleted bid.
DELETED_JOB_WRITE_ROUTES = frozenset({"/api/jobs/{job_id}/restore"})


def _deleted_job_error(job_ref: str) -> JobDeletedError | None:
    db_id = resolve_job_ref(job_ref)
    row = deleted_job_row(db_id) if db_id is not None else None
    return JobDeletedError.for_row(row) if row else None


async def _refuse_writes_to_deleted_jobs(connection: HTTPConnection) -> None:
    """A change to a deleted bid gets 410 "This bid was deleted by X on DATE...".

    An app-wide dependency, so it runs before every POST/PUT/PATCH/DELETE
    route with {job_id} in its path and no route can forget it. Changes that
    reach a bid another way (PUT /api/quotes/{id}, ...) are refused by
    job_write / entity_write. Reads (GET) are left to the route: most answer
    404 for a deleted bid; ?include_deleted=1 and the history still work.
    """
    if connection.scope.get("type") != "http" or connection.scope.get("method") not in audit.WRITE_METHODS:
        return
    job_ref = str(connection.path_params.get("job_id") or "").strip()
    if not job_ref:
        return
    if getattr(connection.scope.get("route"), "path", None) in DELETED_JOB_WRITE_ROUTES:
        return
    error = await run_in_threadpool(_deleted_job_error, job_ref)
    if error is not None:
        raise error


# ── App Setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="SI Bid Tool", version="1.0.0", dependencies=[Depends(_refuse_writes_to_deleted_jobs)])

SESSION_COOKIE = "si_session"
# The only /api paths that work without logging in.
PUBLIC_API_PATHS = frozenset({"/api/auth/login", "/api/auth/me", "/api/system/build"})

# Web pages allowed to call the API from another address and to open live
# (websocket) connections. Override with ALLOWED_ORIGINS, comma separated.
DEFAULT_ALLOWED_ORIGINS = (
    "https://si-bid-tool.fly.dev",
    "https://si-bid-stg-20260714-c0fa.fly.dev",
    "http://localhost:5173",
    "http://localhost:8000",
)
ALLOWED_ORIGINS = tuple(
    origin.strip().rstrip("/")
    for origin in (os.environ.get("ALLOWED_ORIGINS") or ",".join(DEFAULT_ALLOWED_ORIGINS)).split(",")
    if origin.strip()
)
# Websocket close code for "not logged in" (or a page from another site).
WS_CLOSE_LOGGED_OUT = 4401
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")

# HTTP requests being handled right now (key -> (audit context, start time))
# and the last few that finished ((audit context, start, end)). Lets a stalled
# event loop say what was running. Event loop only.
_requests_in_flight: dict[object, tuple[dict, float]] = {}
_requests_finished: deque = deque(maxlen=50)


def _route_label(scope) -> str:
    """"POST /api/jobs/{job_id}/upload-rfms" once FastAPI has matched the route, else the raw path."""
    template = getattr(scope.get("route"), "path", None) or scope.get("path") or ""
    return f"{scope.get('method') or 'WS'} {template}"


def _client_ip(conn: HTTPConnection) -> str:
    # Fly's proxy sets Fly-Client-IP to the real caller address.
    forwarded = (conn.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return (conn.headers.get("fly-client-ip") or forwarded or (conn.client.host if conn.client else ""))[:64]


async def _close_websocket_logged_out(scope, receive, send) -> None:
    """Accept, then close with 4401, so the browser actually gets the code.

    A close sent before accepting never reaches the page: uvicorn turns it
    into an HTTP 403 and the browser only reports code 1006, the same as a
    dropped network, so the page would keep reconnecting instead of showing
    the login screen. Starlette's TestClient passes a pre-accept close code
    straight through, so tests can't tell the two apart; check against a real
    server when changing this.
    """
    message = await receive()
    if message.get("type") != "websocket.connect":
        return  # the browser already went away
    # A browser that asked for a subprotocol drops a reply that names none.
    subprotocols = scope.get("subprotocols") or []
    accept = {"type": "websocket.accept"}
    if subprotocols:
        accept["subprotocol"] = subprotocols[0]
    await send(accept)
    await send({"type": "websocket.close", "code": WS_CLOSE_LOGGED_OUT, "reason": "Please log in."})


class RequireLoginMiddleware:
    """Every /api/* request needs a logged-in user, except PUBLIC_API_PATHS.

    One plain ASGI middleware guards all API routes (including ones added
    later), while the React app and its static files stay public. The user is
    available to handlers as ``request.state.user`` and to ``log_activity``
    through ``models.get_current_user()``; the request id, session and caller
    address through ``models.get_audit_context()``.

    Websockets under /api/ also need a page from ALLOWED_ORIGINS (otherwise
    the handshake is refused: the browser sees a failed connection) and the
    login cookie (otherwise the socket is accepted and then closed with code
    4401, so the page knows to show the login screen). Every /api/ HTTP
    response carries an X-Request-Id header.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path") or ""
        if scope["type"] not in ("http", "websocket") or not (path == "/api" or path.startswith("/api/")):
            await self.app(scope, receive, send)
            return

        is_websocket = scope["type"] == "websocket"
        conn = HTTPConnection(scope)
        request_id = (conn.headers.get("fly-request-id") or "").strip()
        if not _REQUEST_ID_RE.fullmatch(request_id):
            request_id = uuid.uuid4().hex

        if is_websocket and (conn.headers.get("origin") or "").rstrip("/") not in ALLOWED_ORIGINS:
            # Stops a page on another site opening a live connection with
            # someone's login cookie. Closing before accepting refuses the
            # handshake (uvicorn answers HTTP 403); no close code is needed.
            await send({"type": "websocket.close", "code": WS_CLOSE_LOGGED_OUT})
            return

        token = conn.cookies.get(SESSION_COOKIE)
        user, session_id = await run_in_threadpool(get_session, token) if token else (None, None)
        if user is None and (is_websocket or path not in PUBLIC_API_PATHS):
            if is_websocket:
                await _close_websocket_logged_out(scope, receive, send)
            else:
                response = JSONResponse(status_code=401, content={"detail": "Please log in."},
                                        headers={"X-Request-Id": request_id})
                await response(scope, receive, send)
            return

        scope["state"] = {
            **(scope.get("state") or {}),
            "user": user,
            "session_id": session_id,
            "request_id": request_id,
        }
        audit_context = {
            "request_id": request_id,
            "source": "websocket" if is_websocket else "http",
            "session_id": session_id,
            "client_ip": _client_ip(conn),
            # Worked out when read: FastAPI matches the route after this runs.
            "route": lambda: _route_label(scope),
        }
        user_token = set_current_user(user)
        audit_token = set_audit_context(audit_context)
        try:
            if is_websocket:
                await self.app(scope, receive, send)
            else:
                await self._call_http(scope, receive, send, request_id, audit_context)
        finally:
            reset_audit_context(audit_token)
            reset_current_user(user_token)

    async def _call_http(self, scope, receive, send, request_id, audit_context):
        response_started = False

        async def send_with_request_id(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                MutableHeaders(scope=message)["X-Request-Id"] = request_id
            await send(message)

        flight_key = object()
        began = time.monotonic()
        _requests_in_flight[flight_key] = (audit_context, began)
        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Same plain 500 Starlette sends, plus the request id so a failure
            # someone reports can be found in the logs.
            if not response_started:
                print(f"[request {request_id}] {_route_label(scope)} failed with an unexpected error")
                response = PlainTextResponse("Internal Server Error", status_code=500,
                                             headers={"X-Request-Id": request_id})
                await response(scope, receive, send)
            raise
        finally:
            _requests_in_flight.pop(flight_key, None)
            _requests_finished.append((audit_context, began, time.monotonic()))


# Added first so it sits inside RequireLoginMiddleware and can see the request's
# audit context: flags write routes that changed data without an audit entry
# (a 500 instead when AUDIT_STRICT=1). See audit.AuditBackstopMiddleware.
app.add_middleware(AuditBackstopMiddleware)

# Added before CORS so CORS stays the outer layer and still answers preflights.
app.add_middleware(RequireLoginMiddleware)


@app.exception_handler(JobWriteError)
async def _job_write_error(request: Request, err: JobWriteError):
    # Not found / deleted / someone else saved first / busy, from job_writes.
    return JSONResponse(status_code=err.status_code, content={"detail": err.message, **err.info})

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)

def _match_price_book(material: dict) -> dict | None:
    """Match a material to a price_book_items entry (e.g. Schluter catalog).

    Looks for Schluter product references in the description like:
      "Schluter - Schiene #AE-100" -> product_line=SCHIENE, item_no=AE 100
      "Schluter - Reno-TK"         -> product_line=RENO-TK, default AE finish
      "Schluter - Jolly"           -> product_line=JOLLY, default AE finish
    Returns dict with unit_price (per LF), vendor, price_source.
    """
    desc = (material.get("description") or "")
    if "schluter" not in desc.lower():
        return None

    import re
    from models import _get_conn
    conn = _get_conn()
    try:
        # Extract product line and optional item number
        # "Schluter - Schiene #AE-100" -> line="Schiene", item="AE-100"
        # "Schluter - Reno-TK - Transition" -> line="Reno-TK", item=None
        m = re.search(r'schluter\s*[-–—]\s*([\w][\w-]*?)(?:\s*#([\w-]+)|\s)', desc, re.IGNORECASE)
        if not m:
            return None

        product_line = m.group(1).upper()  # SCHIENE, RENO-TK, JOLLY, FINEC, etc.
        raw_item = (m.group(2) or "").upper()  # AE-100, empty, etc.

        row = None
        if raw_item:
            # Normalize: "AE-100" -> "AE 100" (DB uses space separator)
            item_normalized = re.sub(r'[-]', ' ', raw_item).strip()
            row = conn.execute(
                "SELECT net_price, length FROM price_book_items WHERE UPPER(product_line)=? AND UPPER(REPLACE(TRIM(item_no), '-', ' '))=?",
                (product_line, item_normalized)
            ).fetchone()

        if not row:
            # Fallback: match product_line with anodized aluminum finish (default for SI)
            row = conn.execute(
                "SELECT net_price, length FROM price_book_items WHERE UPPER(product_line)=? AND material_finish LIKE '%anodized%' ORDER BY net_price ASC LIMIT 1",
                (product_line,)
            ).fetchone()

        if not row:
            return None

        net_price = row[0]  # price per stick
        length_str = row[1] or ""
        # Parse stick length: "2.5 m - 8' 2-1/2" length" -> ~8.2 LF
        stick_lf = 8.208  # default Schluter stick length (2.5m)
        lf_match = re.search(r"(\d+)'\s*(\d+)?", length_str)
        if lf_match:
            feet = int(lf_match.group(1))
            inches = int(lf_match.group(2)) if lf_match.group(2) else 0
            stick_lf = feet + inches / 12.0

        price_per_lf = round(net_price / stick_lf, 4)
        return {
            "unit_price": price_per_lf,
            "stick_price": net_price,
            "stick_lf": stick_lf,
            "vendor": "Schluter",
            "price_source": "price_book",
        }
    finally:
        conn.close()


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


_artifact_default = "/data/artifacts" if os.path.isdir("/data") else os.path.join(os.path.dirname(__file__), "artifacts")
ARTIFACT_ROOT = os.environ.get("ARTIFACT_ROOT", _artifact_default)
MAX_RFMS_FILE_BYTES = 50 * 1024 * 1024
UPLOAD_DIR = os.path.join(ARTIFACT_ROOT, "shared", "uploads")
PDF_DIR = os.path.join(ARTIFACT_ROOT, "shared", "pdfs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)


def _safe_artifact_name(name: str) -> str:
    """Keep uploaded artifact names inside the intended job directory."""
    import re as _re
    clean = os.path.basename(name or "artifact")
    return _re.sub(r"[^A-Za-z0-9._-]+", "_", clean) or "artifact"


def _job_artifact_dir(job_id: int, kind: str) -> str:
    path = os.path.join(ARTIFACT_ROOT, str(job_id), kind)
    os.makedirs(path, exist_ok=True)
    return path


def _job_upload_path(job_id: int, filename: str, prefix: str) -> str:
    return os.path.join(_job_artifact_dir(job_id, "uploads"), f"{prefix}_{_safe_artifact_name(filename)}")


def _job_pdf_path(job_id: int, kind: str) -> str:
    """A new, unique place for a PDF of this job: {kind}_{job_id}_{UTC time}_{8 random}.pdf.

    Every print gets its own file, so earlier PDFs and their receipts stay as
    they were. Write through _draft_job_pdf / _publish_job_pdf (temp file,
    then os.replace) so a half-written PDF is never served. To read the
    current PDF use _latest_job_pdf.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{kind}_{job_id}_{stamp}_{uuid.uuid4().hex[:8]}.pdf"
    return os.path.join(_job_artifact_dir(job_id, "pdfs"), name)


@lru_cache(maxsize=512)
def _file_hash_for_stat(
    path: str,
    size: int,
    modified_ns: int,
    changed_ns: int,
) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _file_hash(path: str) -> str | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return _file_hash_for_stat(
        os.path.realpath(path),
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _record_artifact(job_id: int, path: str, artifact_kind: str) -> None:
    """Persist a receipt for a durable file after it has been written."""
    digest = _file_hash(path)
    if not digest:
        return
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    record_job_artifact(
        job_id,
        artifact_kind,
        os.path.relpath(path, ARTIFACT_ROOT),
        digest,
        size,
    )


def _require_artifact_receipt(job_id: int, path: str, artifact_kind: str) -> None:
    """Reject a download when its durable receipt is missing or no longer matches."""
    expected_path = os.path.relpath(path, ARTIFACT_ROOT)
    receipt = next(
        (
            item for item in list_job_artifacts(job_id)
            if item.get("artifact_kind") == artifact_kind
            and item.get("artifact_path") == expected_path
        ),
        None,
    )
    if not receipt:
        raise HTTPException(
            status_code=409,
            detail="This PDF wasn't saved properly. Make the PDF again, then download it.",
        )
    if _file_hash(path) != receipt.get("file_hash"):
        raise HTTPException(
            status_code=409,
            detail="This PDF file was changed or damaged after it was made. Make the PDF again, then download it.",
        )


# PDFs are written here first, then moved into the job's folder (same disk,
# so the move is atomic). Kept out of the job folders so a crash never leaves
# a half-written file among a job's artifacts.
PDF_TEMP_DIR = os.path.join(ARTIFACT_ROOT, "shared", "tmp")
os.makedirs(PDF_TEMP_DIR, exist_ok=True)
PDF_ARTIFACT_KINDS = ("proposal_pdf", "bid_pdf")


def _draft_job_pdf(job_id: int, kind: str, write) -> dict:
    """Write a new PDF with ``write(temp_path)``; returns the draft (final path,
    temp path, sha256, size) for _publish_job_pdf. Nothing is visible yet."""
    final_path = _job_pdf_path(job_id, kind)
    temp_path = os.path.join(PDF_TEMP_DIR, f".{os.path.basename(final_path)}.{uuid.uuid4().hex[:8]}.part")
    try:
        write(temp_path)
        digest = hashlib.sha256()
        with open(temp_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        size = os.path.getsize(temp_path)
    except BaseException:
        _discard_job_pdf({"temp_path": temp_path})
        raise
    return {"path": final_path, "temp_path": temp_path, "sha256": digest.hexdigest(), "size": size}


def _discard_job_pdf(draft: dict | None) -> None:
    temp_path = (draft or {}).get("temp_path")
    if temp_path:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass
        except OSError as err:
            print(f"[artifacts] Couldn't remove the unused PDF draft {temp_path}: {err}")


def _publish_job_pdf(job_id: int, draft: dict, artifact_kind: str, *, conn,
                     grand_total=None, proposal_version_id: int | None = None) -> int:
    """Move a drafted PDF into place and save its receipt; returns the receipt id.

    Call it inside the job_write that saves what the PDF shows (pass tx.conn),
    so the receipt, the saved data and the history entry go in together.
    """
    os.replace(draft["temp_path"], draft["path"])
    draft["temp_path"] = None
    try:
        total = round(float(grand_total), 2) if grand_total is not None else None
    except (TypeError, ValueError):
        total = None
    return record_job_artifact(
        job_id, artifact_kind, os.path.relpath(draft["path"], ARTIFACT_ROOT), draft["sha256"], draft["size"],
        grand_total=total, proposal_version_id=proposal_version_id, conn=conn,
    )


def _latest_job_pdf(job_id: int, artifact_kind: str) -> tuple[str, dict] | None:
    """The newest printed PDF of this kind: (full path, receipt), or None."""
    receipt = get_latest_job_artifact(job_id, artifact_kind)
    relative_path = (receipt or {}).get("artifact_path") or ""
    if not receipt or not _checked_artifact_path(relative_path):
        return None
    # Joined (not resolved), so os.path.relpath(path, ARTIFACT_ROOT) gives
    # back the recorded path even when ARTIFACT_ROOT sits behind a symlink.
    return os.path.join(ARTIFACT_ROOT, relative_path), receipt


def _checked_artifact_path(relative_path: str) -> str | None:
    """Resolve a recorded relative path only when it stays inside artifact storage."""
    if not relative_path:
        return None
    artifact_root = os.path.realpath(ARTIFACT_ROOT)
    candidate = os.path.realpath(os.path.join(artifact_root, relative_path))
    try:
        if os.path.commonpath([artifact_root, candidate]) != artifact_root:
            return None
    except ValueError:
        return None
    return candidate


def _imported_artifact_is_verified(imported: dict, artifact_kind: str | None = None) -> bool:
    """Only successfully parsed imports with intact durable bytes qualify as evidence."""
    if artifact_kind and imported.get("artifact_kind") != artifact_kind:
        return False
    path = _checked_artifact_path(imported.get("artifact_path") or "")
    expected_hash = str(imported.get("file_hash") or "").strip()
    return bool(
        path
        and expected_hash
        and os.path.isfile(path)
        and _file_hash(path) == expected_hash
    )


def _file_is_durably_imported(job_id: int, file_hash: str) -> bool:
    """Deduplicate only when the successful import still has verified source bytes."""
    return any(
        item.get("file_hash") == file_hash and _imported_artifact_is_verified(item)
        for item in list_imported_files(job_id)
    )


def _persist_automated_quote_evidence(
    job_id: int,
    temp_files: list[str],
    filenames: list[str],
    parsed_indexes: set[int],
    source: str,
) -> None:
    """Copy temporary inbox artifacts to durable job storage before cleanup."""
    for index, temp_path in enumerate(temp_files):
        digest = _file_hash(temp_path)
        if not digest:
            continue
        original_name = filenames[index] if index < len(filenames) else os.path.basename(temp_path)
        durable_name = f"{digest[:12]}_{original_name or 'vendor_quote'}"
        durable_path = _job_upload_path(job_id, durable_name, "quote")
        if not os.path.exists(durable_path):
            shutil.copy2(temp_path, durable_path)
        _record_artifact(job_id, durable_path, "vendor_quote")
        if index in parsed_indexes:
            record_imported_file(
                job_id,
                original_name or "vendor_quote",
                digest,
                os.path.getsize(durable_path),
                source=source,
                artifact_path=os.path.relpath(durable_path, ARTIFACT_ROOT),
                artifact_kind="vendor_quote",
            )


def _job_artifact_manifest(job_id: int) -> list[dict]:
    root = os.path.join(ARTIFACT_ROOT, str(job_id))
    manifest = []
    if not os.path.isdir(root):
        return manifest
    for current_root, _, names in os.walk(root):
        for name in sorted(names):
            path = os.path.join(current_root, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            manifest.append({
                "path": os.path.relpath(path, root),
                "size": size,
                "sha256": _file_hash(path),
            })
    known = {item.get("path") for item in manifest}
    for receipt in list_job_artifacts(job_id):
        rel_from_artifact_root = receipt.get("artifact_path") or ""
        path = os.path.join(ARTIFACT_ROOT, rel_from_artifact_root)
        rel_from_job = os.path.relpath(path, root) if path.startswith(root + os.sep) else None
        if rel_from_job and rel_from_job not in known and os.path.isfile(path):
            manifest.append({
                "path": rel_from_job,
                "size": receipt.get("file_size") or 0,
                "sha256": receipt.get("file_hash"),
            })
    return manifest


_VENDOR_EVIDENCE_SOURCES = {"vendor_quote", "vendor_quote_override"}


def _price_decision_matches_material(decision: dict, material: dict) -> bool:
    """Return true only while an immutable decision still describes this row."""
    if not isinstance(decision, dict) or not isinstance(material, dict):
        return False
    try:
        same_material = int(decision.get("material_id")) == int(material.get("id"))
    except (TypeError, ValueError):
        return False
    if not same_material:
        return False
    decision_type = str(decision.get("decision") or "").strip().lower()
    source = str(material.get("price_source") or "").strip().lower()
    expected_source = "vendor_quote_override" if decision_type == "keep_accepted" else "vendor_quote"
    return bool(
        decision_type in {"keep_accepted", "use_quote"}
        and source == expected_source
        and str(decision.get("source_hash") or "").strip()
        == str(material.get("quote_source_hash") or "").strip()
        and normalize_quote_unit(decision.get("material_unit"))
        == normalize_quote_unit(material.get("unit"))
        and abs(
            (_as_number(decision.get("resolved_price")) or 0)
            - (_as_number(material.get("unit_price")) or 0)
        ) <= 0.005
    )


def _active_price_decisions_for_materials(job_id: int, materials: list[dict]) -> list[dict]:
    by_id = {
        str(material.get("id")): material
        for material in (materials or [])
        if isinstance(material, dict) and material.get("id") is not None
    }
    return [
        decision
        for decision in list_material_price_decisions(job_id, active_only=True)
        if _price_decision_matches_material(
            decision,
            by_id.get(str(decision.get("material_id"))) or {},
        )
    ]


def _artifact_readiness(
    job_id: int,
    proposal_pdf_path: str,
    materials: list[dict] | None = None,
) -> tuple[str, str, list[str]]:
    """Verify durable source and PDF receipts without changing the job."""
    failures = []
    warnings = []
    def add_failure(message: str) -> None:
        if message not in failures:
            failures.append(message)

    imported_files = list_imported_files(job_id)
    for imported in imported_files:
        label = imported.get("file_name") or "source file"
        relative_path = imported.get("artifact_path") or ""
        if not relative_path:
            warnings.append(f"{label}: uploaded before files were kept, so there's no saved copy")
            continue
        path = _checked_artifact_path(relative_path)
        if not path or not os.path.isfile(path):
            add_failure(f"{label}: the saved copy is missing. Upload the file again")
            continue
        expected_hash = imported.get("file_hash")
        if expected_hash and _file_hash(path) != expected_hash:
            add_failure(f"{label}: the saved copy was changed or damaged. Upload the file again")

    artifact_receipts = list_job_artifacts(job_id)
    # Every print is kept, but only the newest PDF of each kind counts here:
    # a past print that went missing can't be fixed by printing again (Past
    # PDFs says so for that one file when someone tries to download it).
    # The latest proposal PDF is checked on its own further down.
    checked_pdf_kinds: set = {"proposal_pdf"}
    for receipt in artifact_receipts:  # newest first
        kind = receipt.get("artifact_kind")
        if kind in PDF_ARTIFACT_KINDS:
            if kind in checked_pdf_kinds:
                continue
            checked_pdf_kinds.add(kind)
        relative_path = receipt.get("artifact_path") or ""
        path = _checked_artifact_path(relative_path)
        if kind == "bid_pdf":
            if not path or not os.path.isfile(path):
                add_failure("The latest bid PDF file is missing. Make the bid PDF again")
            elif receipt.get("file_hash") and _file_hash(path) != receipt.get("file_hash"):
                add_failure("The latest bid PDF file was changed or damaged. Make the bid PDF again")
            continue
        label = {
            "vendor_quote": "A vendor quote file",
            "rfms": "A takeoff file",
        }.get(kind, "A saved file")
        if not path or not os.path.isfile(path):
            add_failure(f"{label} saved with this bid is missing")
            continue
        expected_hash = receipt.get("file_hash")
        if expected_hash and _file_hash(path) != expected_hash:
            add_failure(f"{label} saved with this bid was changed or damaged")

    has_rfms_evidence = any(
        _imported_artifact_is_verified(item, "rfms")
        for item in imported_files
    )
    if materials and not has_rfms_evidence:
        warnings.append("No saved copy of the RFMS takeoff file")

    vendor_priced = [
        material
        for material in (materials or [])
        if isinstance(material, dict)
        and str(material.get("price_source") or "").strip().lower() in _VENDOR_EVIDENCE_SOURCES
    ]
    valid_decisions = _active_price_decisions_for_materials(job_id, materials or [])
    valid_decisions_by_material = {
        str(decision.get("material_id")): decision
        for decision in valid_decisions
    }
    verified_vendor_hashes = {
        str(item.get("file_hash") or "").strip()
        for item in imported_files
        if _imported_artifact_is_verified(item, "vendor_quote")
    }
    missing_quote_source = []
    missing_quote_artifact = []
    for material in vendor_priced:
        label = material.get("item_code") or material.get("description") or "material"
        source = str(material.get("price_source") or "").strip().lower()
        source_hash = str(material.get("quote_source_hash") or "").strip()
        if not source_hash:
            missing_quote_source.append(str(label))
        elif source_hash not in verified_vendor_hashes:
            missing_quote_artifact.append(str(label))
        elif (
            source == "vendor_quote_override"
            and str(material.get("id")) not in valid_decisions_by_material
        ):
            add_failure(f"{label}: the kept vendor price has no reviewer decision on file. Review that price again")
    if missing_quote_source:
        labels = ", ".join(missing_quote_source[:5])
        suffix = "..." if len(missing_quote_source) > 5 else ""
        add_failure(
            f"{len(missing_quote_source)} material(s) priced from a vendor quote don't say which quote file "
            f"the price came from: {labels}{suffix}"
        )
    if missing_quote_artifact:
        labels = ", ".join(missing_quote_artifact[:5])
        suffix = "..." if len(missing_quote_artifact) > 5 else ""
        add_failure(
            f"{len(missing_quote_artifact)} material(s) priced from a vendor quote don't match a saved quote file: "
            f"{labels}{suffix}"
        )

    # proposal_pdf_path is the latest printed proposal (_latest_job_pdf), or
    # "" when none was printed yet.
    expected_pdf_rel = os.path.relpath(proposal_pdf_path, ARTIFACT_ROOT) if proposal_pdf_path else None
    pdf_receipt = next(
        (
            item for item in artifact_receipts
            if item.get("artifact_kind") == "proposal_pdf"
            and item.get("artifact_path") == expected_pdf_rel
        ),
        None,
    )
    if not proposal_pdf_path or not os.path.isfile(proposal_pdf_path):
        add_failure("The proposal PDF file is missing. Make the PDF again")
    elif not pdf_receipt:
        add_failure("The proposal PDF wasn't saved properly. Make the PDF again")
    elif _file_hash(proposal_pdf_path) != pdf_receipt.get("file_hash"):
        add_failure("The proposal PDF file was changed or damaged. Make the PDF again")

    if failures:
        return "fail", "Some files saved with this bid are missing or damaged.", failures
    if warnings:
        return "warn", "Some older uploads have no saved copy. Nothing to do unless you need the original file.", warnings
    return "pass", "All files saved with this bid are intact.", []


def _find_incoming_quote_job(job_reference, subject: str) -> int | None:
    reference = str(job_reference or "").strip()
    if reference:
        direct = load_job(reference)
        if direct:
            return direct["id"]
    search_term = reference or str(subject or "")[:80]
    if not search_term:
        return None
    results = search_all(search_term)
    jobs = results.get("jobs") or []
    normalized = "".join(character.lower() for character in search_term if character.isalnum())
    exact = [
        item for item in jobs
        if normalized and normalized in {
            "".join(character.lower() for character in str(item.get("project_name") or "") if character.isalnum()),
            "".join(character.lower() for character in str(item.get("slug") or "") if character.isalnum()),
        }
    ]
    if len(exact) == 1:
        return exact[0]["id"]
    if len(jobs) == 1 and len(normalized) >= 6:
        return jobs[0]["id"]
    if jobs:
        print(f"[InboxMonitor] Ambiguous job match for '{search_term}'; leaving the email unread")
    return None


def _ingest_automated_quote(
    *,
    job_reference=None,
    temp_files=None,
    vendor_email=None,
    filenames=None,
    subject="",
    source: str,
    simulated: bool = False,
) -> bool:
    """Persist, parse, and import one automated vendor response idempotently.

    Runs on the inbox monitor / test-mode watcher thread: its history entries
    are by System (source inbox_monitor or sim_watcher) and share one id, the
    way a request's entries do.
    """
    context_token = set_audit_context({
        "request_id": uuid.uuid4().hex,
        "source": "system",
        "session_id": None,
        "client_ip": None,
        "route": "simulated vendor quote" if simulated else "vendor quote email",
    })
    try:
        with system_context("sim_watcher" if simulated else "inbox_monitor",
                            subject=str(subject or "")[:200], vendor_email=vendor_email):
            return _import_automated_quote(
                job_reference=job_reference,
                temp_files=temp_files,
                vendor_email=vendor_email,
                filenames=filenames,
                subject=subject,
                source=source,
                simulated=simulated,
            )
    finally:
        reset_audit_context(context_token)


def _import_automated_quote(
    *,
    job_reference=None,
    temp_files=None,
    vendor_email=None,
    filenames=None,
    subject="",
    source: str,
    simulated: bool = False,
) -> bool:
    temp_files = temp_files or []
    filenames = filenames or []
    job_id = _find_incoming_quote_job(job_reference, subject)
    log_prefix = "SimWatcher" if simulated else "InboxMonitor"
    if not job_id:
        print(f"[{log_prefix}] No matching job for: {job_reference or subject}")
        return False

    # Preserve the original evidence before any AI call. A failed parse stays
    # unread/retryable, while the estimator still has the source artifact.
    _persist_automated_quote_evidence(
        job_id,
        temp_files,
        filenames,
        set(),
        source=source,
    )

    all_products = []
    parsed_indexes = set()
    already_imported = set()
    parse_failures = []
    for index, file_path in enumerate(temp_files):
        digest = _file_hash(file_path)
        if digest and _file_is_durably_imported(job_id, digest):
            already_imported.add(index)
            continue
        try:
            products = parse_quote_file(file_path, strict=True)
            if products:
                filename = filenames[index] if index < len(filenames) else os.path.basename(file_path)
                for product in products:
                    product["file_name"] = filename
                    product["_source_hash"] = digest
                all_products.extend(products)
                parsed_indexes.add(index)
            else:
                parse_failures.append(file_path)
        except Exception as exc:
            parse_failures.append(file_path)
            print(f"[{log_prefix}] Error parsing {file_path}: {exc}")

    if parse_failures:
        print(
            f"[{log_prefix}] {len(parse_failures)} quote source(s) did not parse; "
            "no pricing changes were saved and the message will remain unread"
        )
        return False

    if not all_products:
        if temp_files and len(already_imported) == len(temp_files):
            return True
        print(f"[{log_prefix}] No products extracted from: {str(subject)[:60]}")
        return False

    vendor_name = all_products[0].get("vendor", vendor_email or "Unknown")
    file_names_str = ", ".join(filenames[:3]) if filenames else "email"
    sim_prefix = "[SIM] " if simulated else ""
    activity_summary = (
        f"{sim_prefix}Auto-imported quote from {vendor_name} via {'test mode' if simulated else 'email monitor'}"
    )

    _save_quote_products(job_id, all_products, filenames, action="quotes.auto_import")
    # The matching (AI included) runs without holding the bid.
    matched, loaded_materials, priced_materials = _match_quotes_to_materials(job_id, all_products)
    with job_write(job_id, action="quotes.auto_import", scopes=("materials",), summary=activity_summary) as tx:
        tx.force_record()
        saved = _save_step_results(tx, loaded_materials, priced_materials)
        if saved["conflicts"]:
            tx.set_summary(activity_summary + conflict_note(saved["conflicts"]))
        _learn_vendor_prices(tx.conn, job_id, all_products)
    _link_upload_to_requests(job_id, all_products)
    # Marked imported only after the pricing is saved, so a failure is retried.
    _persist_automated_quote_evidence(
        job_id,
        temp_files,
        filenames,
        parsed_indexes,
        source=source,
    )

    create_notification(
        job_id,
        "quote_received",
        f"{sim_prefix}Quote received from {vendor_name} - {len(all_products)} products parsed, "
        f"{matched} auto-matched ({file_names_str})",
    )
    log_activity(
        job_id,
        "agent_quote_imported",
        activity_summary,
        {"vendor": vendor_name, "products": len(all_products), "matched": matched, "sim": simulated},
    )
    print(f"[{log_prefix}] Imported {len(all_products)} products for job #{job_id} from {vendor_name}")
    return True


_inbox_monitor: InboxMonitor | None = None
_sim_watcher = None  # SimFolderWatcher instance (lazy import to avoid circular)


def _start_sim_watcher():
    """Start the SimFolderWatcher if vendor quote test mode is enabled."""
    global _sim_watcher
    settings = get_settings()
    test_mode = str(settings.get("vendor_quote_test_mode", "false")).lower() == "true"

    # Stop existing watcher if running
    if _sim_watcher and _sim_watcher.is_running:
        _sim_watcher.stop()
        _sim_watcher = None

    if not QUOTE_EMAILS_ENABLED or not test_mode:
        return

    from sim_email import SimFolderWatcher

    def on_sim_quote_received(*, job_reference=None, temp_files=None, vendor_email=None,
                              filenames=None, subject=""):
        """Callback for sim watcher — same pipeline as InboxMonitor."""
        return _ingest_automated_quote(
            job_reference=job_reference,
            temp_files=temp_files,
            vendor_email=vendor_email,
            filenames=filenames,
            subject=subject,
            source="simulator",
            simulated=True,
        )

    _sim_watcher = SimFolderWatcher(on_quote_received=on_sim_quote_received)
    _sim_watcher.start()


def _start_inbox_monitor():
    """Start the inbox monitor if email automation is enabled."""
    global _inbox_monitor
    import json as _json
    settings = get_settings()
    # Don't start real inbox monitor when quote emails are off or in test mode
    if not QUOTE_EMAILS_ENABLED or str(settings.get("vendor_quote_test_mode", "false")).lower() == "true":
        if _inbox_monitor and _inbox_monitor.is_running:
            _inbox_monitor.stop()
        _inbox_monitor = None
        return
    if settings.get("email_automation_enabled") != "true":
        if _inbox_monitor and _inbox_monitor.is_running:
            _inbox_monitor.stop()
        _inbox_monitor = None
        return
    try:
        config = _json.loads(settings.get("email_config", "{}"))
    except Exception:
        if _inbox_monitor and _inbox_monitor.is_running:
            _inbox_monitor.stop()
        _inbox_monitor = None
        return
    imap_host = config.get("imap_host")
    imap_port = int(config.get("imap_port", 993))
    email_addr = config.get("email_address")
    email_pass = config.get("email_password")
    if not all([imap_host, email_addr, email_pass]):
        if _inbox_monitor and _inbox_monitor.is_running:
            _inbox_monitor.stop()
        _inbox_monitor = None
        return

    def on_quote_received(*, job_reference=None, temp_files=None, vendor_email=None,
                          filenames=None, subject=""):
        """Callback when inbox monitor detects a vendor response.
        Signature matches InboxMonitor._process_email kwargs."""
        return _ingest_automated_quote(
            job_reference=job_reference,
            temp_files=temp_files,
            vendor_email=vendor_email,
            filenames=filenames,
            subject=subject,
            source="email_monitor",
        )

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
    _take_single_process_lock()
    init_db()
    # Anything the seeds add or change goes in the history as "System"
    # (server startup); a seed that finds nothing to do records nothing.
    with system_context("startup"):
        _run_off_event_loop(_seed_on_startup)
    _start_inbox_monitor()
    _start_sim_watcher()


def _seed_on_startup():
    if seed_default_users():
        print("[seed] Created the shared 'test' login")
    _seed_admin_from_env()
    _apply_openai_config()
    _seed_company_rates()
    _seed_rules_registry()
    _auto_import_price_books()


def _run_off_event_loop(fn):
    """Run blocking startup work to the end. entity_write refuses to run on
    the event loop (sync startup handlers are called on it), so the work goes
    to a worker thread, with this context (who is acting) copied over."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn()
    import concurrent.futures
    import contextvars
    context = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="startup") as pool:
        return pool.submit(context.run, fn).result()


# ── One app process only ─────────────────────────────────────────────────────
# Live editing keeps shared state in memory, so the app must run as exactly
# one process on one machine. A second process started against the same
# database folder (e.g. a second uvicorn worker) can't take this lock and says
# so loudly in the logs. It keeps running so nobody is locked out.
SINGLE_PROCESS_OK = True
_single_process_lock_file = None


def _take_single_process_lock() -> bool:
    global SINGLE_PROCESS_OK, _single_process_lock_file
    if _single_process_lock_file is not None:
        return True  # This process already holds it (startup ran again).
    if fcntl is None:
        print("[single-process] File locks aren't available on this computer; skipped the one-process check")
        return True
    lock_path = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), ".collab.lock")
    try:
        lock_file = open(lock_path, "a+")
    except OSError as err:
        SINGLE_PROCESS_OK = False
        print(f"[single-process] ERROR: couldn't open {lock_path} ({err}); can't check this is the only app process")
        return False
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        SINGLE_PROCESS_OK = False
        print("!" * 78)
        print(f"[single-process] ERROR: another app process already holds {lock_path}.")
        print("[single-process] The bid tool must run as ONE process on ONE machine, or live edits can be lost.")
        print("!" * 78)
        return False
    lock_file.truncate(0)
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    _single_process_lock_file = lock_file
    SINGLE_PROCESS_OK = True
    return True


# ── Event loop watch ─────────────────────────────────────────────────────────
# Every live connection shares one event loop, so a handler that blocks it
# freezes everyone. Log each stall longer than EVENT_LOOP_STALL_MS with the
# requests that were running, so the slow code can be found.
EVENT_LOOP_CHECK_SECONDS = 0.5
EVENT_LOOP_STALL_MS = 200
# One watch per running event loop (tests can start the app more than once).
_event_loop_watch_tasks: dict[asyncio.AbstractEventLoop, asyncio.Task] = {}


async def _watch_event_loop() -> None:
    while True:
        started = time.monotonic()
        await asyncio.sleep(EVENT_LOOP_CHECK_SECONDS)
        now = time.monotonic()
        stall_ms = (now - started - EVENT_LOOP_CHECK_SECONDS) * 1000
        if stall_ms <= EVENT_LOOP_STALL_MS:
            continue
        # Suspects: requests still running plus any that finished during the
        # stall (a blocking handler usually finishes before this wakes up).
        # Requests quicker than the threshold can't have caused it; longest first.
        suspects = [(now - began, "running ", context) for context, began in _requests_in_flight.values()]
        suspects += [(ended - began, "", context) for context, began, ended in _requests_finished if ended >= started]
        suspects = sorted(
            (entry for entry in suspects if entry[0] * 1000 >= EVENT_LOOP_STALL_MS),
            key=lambda entry: entry[0], reverse=True,
        )
        described = ", ".join(
            f"{context['route']()} [{context['request_id']}] {label}{seconds:.1f}s"
            for seconds, label, context in suspects[:5]
        )
        if len(suspects) > 5:
            described += f" and {len(suspects) - 5} more"
        print(f"[event_loop] Stalled for {stall_ms:.0f} ms. Requests at the time: {described or 'none'}")


@app.on_event("startup")
async def _start_event_loop_watch():
    loop = asyncio.get_running_loop()
    task = _event_loop_watch_tasks.get(loop)
    if task is None or task.done():
        _event_loop_watch_tasks[loop] = asyncio.create_task(_watch_event_loop())


@app.on_event("shutdown")
async def _stop_event_loop_watch():
    task = _event_loop_watch_tasks.pop(asyncio.get_running_loop(), None)
    if task is not None:
        task.cancel()


# Closes grouped history entries once nobody has edited them for a while.
@app.on_event("startup")
async def _start_audit_sweeper():
    # After each sweep, save a proposal version of bids whose editing went quiet.
    proposal_versions.register_sweeper()
    audit.start_sweeper()


@app.on_event("shutdown")
async def _stop_audit_sweeper():
    audit.stop_sweeper()


def _seed_admin_from_env():
    """Set up the first admin from Fly secrets ADMIN_USERNAME / ADMIN_PIN.

    Creates ADMIN_USERNAME as an admin with ADMIN_PIN when it doesn't exist.
    An existing login is only made an active admin again when there are no
    active admins left, so removing it on the Users page sticks across
    restarts. An existing PIN is never replaced, so changing the PIN in the
    app sticks too. The PIN is never printed.
    """
    username = (os.environ.get("ADMIN_USERNAME") or "").strip()
    pin = (os.environ.get("ADMIN_PIN") or "").strip()
    if not username and not pin:
        return
    if not username or not pin:
        print("[seed] Set both ADMIN_USERNAME and ADMIN_PIN to create the admin login; skipped")
        return
    try:
        changes = ensure_admin_user(username, pin, os.environ.get("ADMIN_DISPLAY_NAME", ""))
    except UserAdminError as err:
        # err.message describes the rule that failed, never the PIN itself.
        print(f"[seed] Admin login from ADMIN_USERNAME not set up: {err.message}")
        return
    if changes:
        why = "" if "created" in changes else " (there were no active admins)"
        print(f"[seed] Admin login '{username}': {', '.join(changes)}{why}")


def _auto_import_price_books():
    """Auto-import price books from JSON files on startup if DB is empty."""
    summary = get_price_book_summary()
    if any(s["vendor"] == "Schluter" for s in summary):
        return  # Already imported
    json_path = os.path.join(os.path.dirname(__file__), "schluter_prices.json")
    if os.path.exists(json_path):
        import json as _json
        with open(json_path) as f:
            items = _json.load(f)
        count = _import_price_book_audited("Schluter", items, discount_pct=0.55, category="transitions")
        print(f"Auto-imported Schluter price book: {count} items (45% of list)")


def _seed_rules_registry():
    """Seed hard estimating rules if they are not already in the registry."""
    result = _seed_rules_audited()
    if result.get("inserted"):
        print(f"[seed] Seeded {result['inserted']} estimating rules")


# ── Pydantic Models ──────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    project_name: str
    gc_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    tax_rate: float = 0.0
    gpm_pct: float = 0.0
    unit_count: int = 0
    tub_shower_count: int = 0
    salesperson: Optional[str] = None
    notes: Optional[str] = None
    architect: Optional[str] = None
    designer: Optional[str] = None
    textura_fee: int = 0
    # Optional Estimate PDF header fields (see models.JOB_ESTIMATE_HEADER_FIELDS)
    quote_number: Optional[str] = None
    customer_po: Optional[str] = None
    contract_number: Optional[str] = None
    salesperson2: Optional[str] = None
    customer_account: Optional[str] = None
    customer_address: Optional[str] = None
    customer_city: Optional[str] = None
    customer_state: Optional[str] = None
    customer_zip: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_fax: Optional[str] = None
    site_phone: Optional[str] = None
    site_contact: Optional[str] = None


class MaterialUpdate(BaseModel):
    materials: list[dict]
    base_source_fingerprint: Optional[str] = None
    deletion_reasons: dict[str, str] = Field(default_factory=dict)


class VendorPriceConflictResolutionRequest(BaseModel):
    decision: str
    source_hash: str
    quote_price: float
    quote_unit: str
    accepted_price: float
    reviewer_name: str
    reason: str


class NotesUpdate(BaseModel):
    notes: str = ""


class JobDeleteRequest(BaseModel):
    # Why the bid is being deleted (required, 1-500 characters).
    reason: str = ""


class BulkDeleteRequest(BaseModel):
    ids: list[int | str] = Field(default_factory=list)
    job_ids: list[int | str] = Field(default_factory=list)  # older name for ids
    reason: str = ""


class SettingsUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    multi_pass_count: Optional[int] = None
    email_automation_enabled: Optional[str] = None
    email_config: Optional[str] = None
    bid_folder_path: Optional[str] = None
    vendor_quote_test_mode: Optional[str] = None


class RuleCreate(BaseModel):
    rule_id: str
    name: str
    category: str = ""
    stage: str = ""
    status: str = "draft"
    priority: int = 0
    condition_json: Optional[dict] = None
    action_json: Optional[dict] = None
    source: str = ""
    description: str = ""
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    version: int = 1
    implementation_ref: str = ""
    test_ref: str = ""
    notes: str = ""
    changed_by: Optional[str] = None
    change_note: Optional[str] = None


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    condition_json: Optional[dict] = None
    action_json: Optional[dict] = None
    source: Optional[str] = None
    description: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    version: Optional[int] = None
    implementation_ref: Optional[str] = None
    test_ref: Optional[str] = None
    notes: Optional[str] = None
    changed_by: Optional[str] = None
    change_note: Optional[str] = None


class RuleChangeMeta(BaseModel):
    changed_by: Optional[str] = None
    change_note: Optional[str] = None


class RuleDraftRequest(BaseModel):
    lesson_text: str
    changed_by: Optional[str] = "Josh"


class RulesetRollbackRequest(BaseModel):
    changed_by: Optional[str] = "Josh"
    change_note: Optional[str] = None


class GoldenBaselineRequest(BaseModel):
    jr_quote_id: Optional[str] = ""
    target_totals: Optional[dict] = None
    target_bundles: Optional[list[dict]] = None
    tolerance: Optional[dict] = None
    notes: Optional[str] = ""
    reviewer_name: Optional[str] = ""


class GoldenReplayRequest(BaseModel):
    mode: str = "baseline"


# ── Routes ────────────────────────────────────────────────────────────────────

def _rule_with_engine_contract(rule: dict, build: dict | None = None) -> dict:
    build = build or get_build_info()
    item = dict(rule or {})
    implementation_ref = str(item.get("implementation_ref") or item.get("source") or "").strip()
    implementation_path = implementation_ref.split("#", 1)[0].split(":", 1)[0]
    implementation_file = os.path.basename(implementation_path)
    implementation_hash = (build.get("engine_files") or {}).get(implementation_file)
    contribution_payload = {
        "rule_id": item.get("rule_id"),
        "rule_version": item.get("version"),
        "implementation_ref": implementation_ref,
        "test_ref": item.get("test_ref"),
        "implementation_hash": implementation_hash,
        "config_fingerprint": build.get("config_fingerprint"),
    }
    item["rule_version"] = item.get("version")
    item["engine_config_fingerprint_contribution"] = hashlib.sha256(
        json.dumps(contribution_payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    runtime_reference_verified = bool(implementation_ref and implementation_hash)
    item["calculation_contract"] = "implemented" if runtime_reference_verified else "metadata_only"
    item["runtime_implementation_referenced"] = runtime_reference_verified
    item["registry_effect"] = "metadata_only"
    return item


def _ruleset_with_engine_contract(ruleset: dict | None) -> dict | None:
    if not ruleset:
        return ruleset
    result = dict(ruleset)
    snapshot = dict(result.get("snapshot") or {})
    build = get_build_info()
    snapshot["rules"] = [_rule_with_engine_contract(rule, build) for rule in (snapshot.get("rules") or [])]
    snapshot["engine_fingerprint"] = build.get("engine_fingerprint")
    snapshot["config_fingerprint"] = build.get("config_fingerprint")
    result["snapshot"] = snapshot
    result["engine_fingerprint"] = build.get("engine_fingerprint")
    result["config_fingerprint"] = build.get("config_fingerprint")
    return result


# ── History for shared data (settings, catalogs, vendors, rules) ─────────────
# entity_write compares what a loader returns before and after a change, so
# each loader shapes its data for readable history paths ("/unit_price",
# "/email_config/smtp_host"). API keys, passwords and PINs are hidden by name
# in audit.prepare_changes, so loaders don't need to drop them.

# Entity id for a whole list (a catalog upload or clear); single rows use their id.
WHOLE_LIST = "all"
# Entity id for changes to the whole estimating rules registry.
RULES_REGISTRY = "registry"


def _person_name() -> str:
    """Who is making this change, as people see it (display name, or "System")."""
    return audit.current_actor()["display"]


def _count(n: int, singular: str, plural: str | None = None) -> str:
    """"1 entry", "3 entries" for history summaries."""
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _row_loader(table: str, key: str = "id", drop: tuple[str, ...] = ()):
    """Loader for one row of ``table`` (None once it's deleted)."""
    def load(conn, entity_id):
        row = conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (entity_id,)).fetchone()
        return None if row is None else {k: v for k, v in dict(row).items() if k not in drop}
    return load


def _list_loader(table: str, *, where: str = "", drop: tuple[str, ...] = ()):
    """Loader for a whole list that is replaced or cleared at once. Replaces
    are keyed upserts (models.upsert_keyed_rows) that keep a row's id, so rows
    are matched by id and the history shows each changed field, added row and
    deleted row ("/entries/12/cost")."""
    def load(conn, entity_id):
        sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + " ORDER BY id"
        rows = conn.execute(sql, (entity_id,) if where else ()).fetchall()
        return {"entries": [{k: v for k, v in dict(row).items() if k not in drop} for row in rows]}
    return load


_load_labor_catalog_entry = _row_loader("labor_catalog")
_load_labor_catalog = _list_loader("labor_catalog")
_load_price_list_entry = _row_loader("price_list")
_load_price_list = _list_loader("price_list")
_load_price_book = _list_loader("price_book_items", where="vendor = ?", drop=("vendor",))
_load_notification = _row_loader("notifications")


def _load_company_rate(conn, rate_type):
    row = conn.execute("SELECT data FROM company_rates WHERE rate_type = ?", (rate_type,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["data"])
    except (TypeError, ValueError):
        return {"data": row["data"]}


# What the Settings page changes (other app_settings rows are bookkeeping),
# with the names history summaries use.
SETTING_LABELS = {
    "openai_api_key": "OpenAI API key",
    "anthropic_api_key": "Anthropic API key",
    "openai_model": "AI model",
    "multi_pass_count": "quote reading passes",
    "email_automation_enabled": "email automation",
    "email_config": "mailbox settings",
    "bid_folder_path": "bid folder",
    "vendor_quote_test_mode": "vendor quote test mode",
}
AUDITED_SETTINGS = tuple(SETTING_LABELS)


def _load_settings(conn, _entity_id):
    placeholders = ", ".join("?" for _ in AUDITED_SETTINGS)
    settings = {
        row["key"]: row["value"]
        for row in conn.execute(f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})", AUDITED_SETTINGS)
    }
    raw = settings.get("email_config")
    if raw:
        # Compared field by field, so the mailbox password inside is hidden by name.
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = None
        settings["email_config"] = parsed if isinstance(parsed, dict) else {
            # Not readable as settings: note that it changed, never what it says.
            "unreadable": True, "fingerprint": hashlib.sha256(str(raw).encode("utf-8")).hexdigest()[:12],
        }
    return settings


def _load_vendor(conn, vendor_id):
    row = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    if row is None:
        return None
    vendor = {k: v for k, v in dict(row).items() if k not in ("created_at", "updated_at")}
    vendor["price_count"] = conn.execute(
        "SELECT COUNT(*) FROM vendor_prices WHERE vendor_id = ?", (vendor_id,)
    ).fetchone()[0]
    return vendor


def _load_quote_request(conn, request_id):
    row = conn.execute("SELECT * FROM quote_requests WHERE id = ?", (request_id,)).fetchone()
    if row is None:
        return None
    quote_request = dict(row)
    try:
        quote_request["material_ids"] = json.loads(quote_request.get("material_ids") or "[]")
    except (TypeError, ValueError):
        pass
    return quote_request


def _rule_view(row) -> dict:
    rule = {k: v for k, v in dict(row).items() if k not in ("created_at", "updated_at")}
    for field in ("condition_json", "action_json"):
        try:
            rule[field] = json.loads(rule.get(field) or "{}")
        except (TypeError, ValueError):
            pass
    return rule


def _load_rule(conn, rule_id):
    row = conn.execute("SELECT * FROM estimating_rules WHERE rule_id = ?", (rule_id,)).fetchone()
    return None if row is None else _rule_view(row)


def _load_rules_registry(conn, _entity_id):
    """Every rule, keyed by rule_id ("/<rule_id>/status" in the history)."""
    return {
        row["rule_id"]: _rule_view(row)
        for row in conn.execute("SELECT * FROM estimating_rules ORDER BY rule_id").fetchall()
    }


def _max_id(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0])


def _added_rows(conn, table: str, after_id: int, columns: tuple[str, ...], path: str) -> list[dict]:
    """"add" changes for the rows put into ``table`` after id ``after_id`` (imports)."""
    rows = conn.execute(
        f"SELECT id, {', '.join(columns)} FROM {table} WHERE id > ? ORDER BY id", (after_id,)
    ).fetchall()
    return [
        {"path": f"{path}/{row['id']}", "op": "add", "before": None, "after": {c: row[c] for c in columns}}
        for row in rows
    ]


# ── Log in / log out ─────────────────────────────────────────────────────────

LOGIN_FAILURE_DELAY_SECONDS = 1.0
# PINs are short, so guessing is capped: after this many tries in the window a
# username (or one network address) gets "too many tries" without the PIN
# being checked. The per-address cap is higher because an office shares one.
LOGIN_TRY_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_TRIES_PER_USERNAME = 5
LOGIN_MAX_TRIES_PER_ADDRESS = 20
LOGIN_MAX_PIN_CHECKS_AT_ONCE = 2    # each PIN check is deliberately slow CPU work
LOGIN_TOO_MANY_TRIES = "Too many wrong tries. Wait a few minutes, then try again."

# key ("user:<name>" / "ip:<address>") -> monotonic times of recent tries.
# Only touched from the event loop, so no lock is needed. Kept in memory: the
# app runs as one process, and a restart simply resets the counts.
_login_tries: dict[str, list[float]] = {}
_pin_check_gate: tuple | None = None   # (event loop, semaphore)


def _login_try_keys(username: str, request: Request) -> tuple[str, str]:
    # Fly's proxy sets Fly-Client-IP to the real caller address.
    address = request.headers.get("fly-client-ip") or (request.client.host if request.client else "")
    return (
        "user:" + (username or "").strip().lower()[:64],
        "ip:" + ((address or "").strip()[:64] or "unknown"),
    )


def _recent_login_tries(key: str, now: float) -> list[float]:
    tries = [t for t in _login_tries.get(key, ()) if now - t < LOGIN_TRY_WINDOW_SECONDS]
    if tries:
        _login_tries[key] = tries
    else:
        _login_tries.pop(key, None)
    return tries


def _prune_login_tries(now: float) -> None:
    if len(_login_tries) > 5000:
        for key in list(_login_tries):
            _recent_login_tries(key, now)


def _pin_check_semaphore() -> asyncio.Semaphore:
    """Cap how many slow PIN checks run at once so logins can't hog the CPU."""
    global _pin_check_gate
    loop = asyncio.get_running_loop()
    if _pin_check_gate is None or _pin_check_gate[0] is not loop:
        _pin_check_gate = (loop, asyncio.Semaphore(LOGIN_MAX_PIN_CHECKS_AT_ONCE))
    return _pin_check_gate[1]


class LoginRequest(BaseModel):
    username: str = ""
    pin: str | int = ""


def _request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    # Fly terminates HTTPS at its proxy and forwards plain HTTP to the app.
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",")[0].strip().lower() == "https"


# New for each run of the server, so the tags below can't be turned back into
# what was typed (a PIN typed into the username box is only a few digits).
_UNKNOWN_USERNAME_KEY = os.urandom(32)


def _attempted_username(conn, username) -> dict:
    """How the history names the username someone typed at login.

    Everyone logged in can read the history, and people sometimes type
    their PIN into the username box, so only a username that really exists
    is kept. Anything else is "a username no one has" plus a short tag that
    is the same for the same text (until the server restarts), so repeated
    tries can be linked without storing what was typed.

    Returns {"username", "tag", "user_key"}: user_key replaces the typed text
    in the "user:<name>" login-lock key."""
    typed = str(username or "").strip()
    if not typed:
        return {"username": None, "tag": None, "user_key": "user:"}
    row = conn.execute("SELECT username FROM users WHERE username = ?", (typed[:256],)).fetchone()
    if row is not None:
        return {"username": row["username"], "tag": None, "user_key": "user:" + row["username"].lower()}
    tag = hmac.new(_UNKNOWN_USERNAME_KEY, typed.lower().encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    return {"username": None, "tag": tag, "user_key": f"user:unknown-{tag}"}


def _record_login_failed(username: str, address: str) -> None:
    """History entry for a wrong username or PIN: the username (only if it
    exists, see _attempted_username) and where from. Never the PIN."""
    with audit.write_transaction() as conn:
        typed = _attempted_username(conn, username)
        if typed["username"]:
            entity_id = typed["username"]
            summary = f"Wrong username or PIN for '{typed['username']}'"
            extra = {"attempted_username": typed["username"], "ip": address}
        elif typed["tag"]:
            entity_id = f"unknown-{typed['tag']}"
            summary = "Tried to log in with a username no one has"
            extra = {"unknown_username_tag": typed["tag"], "ip": address}
        else:
            entity_id = None
            summary = "Tried to log in without a username"
            extra = {"ip": address}
        audit.record(
            conn,
            action="auth.login_failed",
            entity_type="session",
            entity_id=entity_id,
            summary=summary,
            extra=extra,
        )


# Every refused try while a username (or address) is locked joins one entry,
# so someone hammering the login can't flood the history.
_LOGIN_THROTTLED_GROUP = audit.GroupPolicy(idle_s=LOGIN_TRY_WINDOW_SECONDS, max_s=LOGIN_TRY_WINDOW_SECONDS)


def _record_login_throttled(username: str, address: str, locked_key: str) -> None:
    """History entry for a login turned away for too many wrong tries.
    ``locked_key`` is the lock that applied ("user:<typed name>" or
    "ip:<address>"); the typed name is only kept if it is a real username."""
    by_address = locked_key.startswith("ip:")
    with audit.write_transaction() as conn:
        typed = _attempted_username(conn, username)
        if typed["username"]:
            name = f"'{typed['username']}'"
            extra = {"attempted_username": typed["username"]}
        elif typed["tag"]:
            name = "a username no one has"
            extra = {"unknown_username_tag": typed["tag"]}
        else:
            name = "no username"
            extra = {}
        if by_address:
            summary = f"Too many wrong tries from {address}: turned away a login as {name}"
        else:
            summary = f"Too many wrong tries for {name}: turned away a login"
        audit.record(
            conn,
            action="auth.login_throttled",
            entity_type="session",
            entity_id=locked_key if by_address else typed["user_key"],
            summary=summary,
            group=_LOGIN_THROTTLED_GROUP,
            extra={**extra, "ip": address, "locked": "address" if by_address else "username"},
        )


async def _record_login_problem(recorder, *args) -> None:
    """Write a wrong-PIN / too-many-tries entry. If the database is busy the
    person still gets the right answer (401 / 429); the error is logged."""
    try:
        await run_in_threadpool(recorder, *args)
    except Exception as err:
        print(f"[audit] ERROR: couldn't add a failed login to the history: {err}")


def _start_login_session(user: dict, old_token: str | None) -> str:
    """End the browser's old session (if any), start a new one and add the
    login to the history, in one transaction. Returns the new cookie token."""
    user_token = set_current_user(user)  # the entry names the person who just logged in
    try:
        with audit.write_transaction() as conn:
            if old_token:
                delete_session(old_token, conn=conn)
            token = create_session(user["id"], conn=conn)
            set_audit_session(session_id_for_token(token, conn=conn))
            audit.record(
                conn,
                action="auth.login",
                entity_type="session",
                entity_id=user["username"],
                summary="Logged in",
            )
        return token
    finally:
        reset_current_user(user_token)


@app.post("/api/auth/login")
@audit_route("auth.login", "auth.login_failed", "auth.login_throttled")
async def api_auth_login(body: LoginRequest, request: Request):
    now = time.monotonic()
    _prune_login_tries(now)
    user_key, address_key = _login_try_keys(body.username, request)
    address = address_key[len("ip:"):]
    user_tries = _recent_login_tries(user_key, now)
    address_tries = _recent_login_tries(address_key, now)
    if len(user_tries) >= LOGIN_MAX_TRIES_PER_USERNAME or len(address_tries) >= LOGIN_MAX_TRIES_PER_ADDRESS:
        oldest = min(
            user_tries[0] if len(user_tries) >= LOGIN_MAX_TRIES_PER_USERNAME else now,
            address_tries[0] if len(address_tries) >= LOGIN_MAX_TRIES_PER_ADDRESS else now,
        )
        wait_seconds = max(1, int(LOGIN_TRY_WINDOW_SECONDS - (now - oldest)) + 1)
        locked_key = user_key if len(user_tries) >= LOGIN_MAX_TRIES_PER_USERNAME else address_key
        await _record_login_problem(_record_login_throttled, body.username, address, locked_key)
        raise HTTPException(status_code=429, detail=LOGIN_TOO_MANY_TRIES,
                            headers={"Retry-After": str(wait_seconds)})
    # Count this try before checking the PIN, so a burst of requests sent at
    # the same moment is capped too.
    _login_tries.setdefault(user_key, []).append(now)
    _login_tries.setdefault(address_key, []).append(now)

    async with _pin_check_semaphore():
        user = await run_in_threadpool(authenticate_user, body.username, body.pin)
    if not user:
        await _record_login_problem(_record_login_failed, body.username, address)
        # Slow down guessing a little without tying up a worker thread.
        await asyncio.sleep(LOGIN_FAILURE_DELAY_SECONDS)
        raise HTTPException(status_code=401, detail="That username and PIN don't match. Try again.")
    # Right PIN: clear this username's wrong tries and hand back this try's
    # slot for the address, so people sharing an office connection aren't
    # held up by each other's successful logins.
    _login_tries.pop(user_key, None)
    address_tries = _login_tries.get(address_key)
    if address_tries and now in address_tries:
        address_tries.remove(now)
    token = await run_in_threadpool(_start_login_session, user, request.cookies.get(SESSION_COOKIE))
    response = JSONResponse(content=user)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_LIFETIME_DAYS * 24 * 60 * 60,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_request_is_https(request),
    )
    return response


@app.get("/api/auth/me")
def api_auth_me(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return user


@app.post("/api/auth/logout")
@audit_route("auth.logout")
def api_auth_logout(request: Request):
    user = getattr(request.state, "user", None) or {}
    with audit.write_transaction() as conn:
        delete_session(request.cookies.get(SESSION_COOKIE), conn=conn)
        audit.record(conn, action="auth.logout", entity_type="session",
                     entity_id=user.get("username"), summary="Logged out")
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_request_is_https(request),
    )
    return response


@app.get("/api/auth/online")
def api_auth_online():
    """People who used the tool in the last 15 minutes."""
    return list_online_users()


# ── People (admins only) ─────────────────────────────────────────────────────
# Add and remove people who can log in. Every route checks the caller is an
# admin; the login middleware has already turned away anyone logged out.

def _require_admin(request: Request, message: str = "Only admins can add or remove people.") -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in.")
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail=message)
    return user


def _clear_login_tries(username: str) -> None:
    """Forget someone's wrong PIN tries, e.g. after an admin gives them a new PIN."""
    _login_tries.pop("user:" + (username or "").strip().lower()[:64], None)


class AdminUserCreate(BaseModel):
    username: str = ""
    display_name: str = ""
    pin: str | int = ""
    is_admin: bool = False


class AdminPinReset(BaseModel):
    pin: str | int = ""


class AdminUserUpdate(BaseModel):
    display_name: Optional[str] = None
    is_admin: Optional[bool] = None


@app.get("/api/admin/users")
def api_admin_list_users(request: Request):
    _require_admin(request)
    return list_users_for_admin()


# People changes are written to admin_log and to the audit trail in the same
# transaction (models._log_admin_action). A change that changes nothing (say,
# restoring someone who is already active) writes neither.

@app.post("/api/admin/users")
@audit_route("user.create")
def api_admin_add_user(body: AdminUserCreate, request: Request):
    admin = _require_admin(request)
    try:
        return create_user(body.username, body.pin, body.display_name, is_admin=body.is_admin, actor=admin)
    except UserAdminError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message)


@app.post("/api/admin/users/{username}/remove")
@audit_route("user.remove")
def api_admin_remove_user(username: str, request: Request):
    admin = _require_admin(request)
    try:
        user, sessions_ended = remove_user(username, admin)
    except UserAdminError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message)
    audit.note_checked()  # already removed: nothing to record
    return {**user, "sessions_ended": sessions_ended}


# async so the wrong-try counts (event-loop only) can be cleared safely.
@app.post("/api/admin/users/{username}/restore")
@audit_route("user.restore")
async def api_admin_restore_user(username: str, request: Request):
    admin = _require_admin(request)
    try:
        user = await run_in_threadpool(restore_user, username, admin)
    except UserAdminError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message)
    audit.note_checked()  # already active: nothing to record
    _clear_login_tries(user["username"])
    return user


@app.post("/api/admin/users/{username}/reset-pin")
@audit_route("user.reset_pin")
async def api_admin_reset_pin(username: str, body: AdminPinReset, request: Request):
    admin = _require_admin(request)
    try:
        user, sessions_ended = await run_in_threadpool(
            reset_user_pin, username, body.pin, admin, request.cookies.get(SESSION_COOKIE)
        )
    except UserAdminError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message)
    _clear_login_tries(user["username"])
    return {**user, "sessions_ended": sessions_ended}


@app.patch("/api/admin/users/{username}")
@audit_route("user.rename", "user.make_admin", "user.remove_admin")
def api_admin_update_user(username: str, body: AdminUserUpdate, request: Request):
    admin = _require_admin(request)
    try:
        user = update_user(username, admin, display_name=body.display_name, is_admin=body.is_admin)
    except UserAdminError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message)
    audit.note_checked()  # same name and admin rights as before: nothing to record
    return user


@app.get("/api/admin/log")
def api_admin_log(request: Request, limit: int = 50):
    """Recent people changes: who added, removed or changed whom, and when."""
    _require_admin(request)
    return list_admin_log(limit)


@app.get("/api/system/build")
def api_system_build():
    """Return the deployed build and engine identity used for trust checks."""
    return get_build_info()


def _vendor_import_idempotency_status() -> dict:
    required_columns = {
        "job_quotes": "source_hash",
        "vendor_prices": "source_hash",
    }
    required_indexes = {
        "idx_job_quotes_source_product",
        "idx_vendor_prices_source_product",
    }
    missing = []
    conn = _get_conn()
    try:
        for table, column in required_columns.items():
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in columns:
                missing.append(f"{table}.{column}")
        indexes = set()
        for table in required_columns:
            for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
                if int(row["unique"] or 0):
                    indexes.add(row["name"])
        missing.extend(sorted(required_indexes - indexes))
    finally:
        conn.close()
    return {
        "verified": not missing,
        "mechanism": "source_hash_database_uniqueness",
        "missing": missing,
    }


def _vendor_price_provenance_status() -> dict:
    required = {"quote_source_hash", "quote_file_name"}
    conn = _get_conn()
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_materials)").fetchall()}
    finally:
        conn.close()
    missing = sorted(required - columns)
    return {"verified": not missing, "missing": missing}


def _vendor_price_decision_status() -> dict:
    required = {
        "job_id", "material_id", "decision", "accepted_price_before",
        "resolved_price", "quote_price", "source_hash", "reason",
        "reviewer_name", "created_at", "superseded_at",
    }
    conn = _get_conn()
    try:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(material_price_decisions)").fetchall()
        }
    finally:
        conn.close()
    missing = sorted(required - columns)
    return {"verified": not missing, "missing": missing}


@app.get("/api/system/vendor-ingestion")
def api_system_vendor_ingestion():
    """Return non-secret health evidence for vendor-pricing ingestion."""
    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    provider = get_provider_info(api_key)
    test_mode = QUOTE_EMAILS_ENABLED and str(settings.get("vendor_quote_test_mode", "false")).lower() == "true"
    automation_enabled = QUOTE_EMAILS_ENABLED and str(settings.get("email_automation_enabled", "false")).lower() == "true"
    monitor_running = bool(_inbox_monitor and _inbox_monitor.is_running)
    simulator_running = bool(_sim_watcher and _sim_watcher.is_running)
    idempotency = _vendor_import_idempotency_status()
    provenance = _vendor_price_provenance_status()
    decisions = _vendor_price_decision_status()
    if (
        not idempotency["verified"]
        or not provenance["verified"]
        or not decisions["verified"]
        or not provider.get("available")
    ):
        status = "blocked"
    elif test_mode and not simulator_running:
        status = "warning"
    elif automation_enabled and not test_mode and not monitor_running:
        status = "warning"
    else:
        status = "ready"
    try:
        multi_pass_count = max(1, min(5, int(settings.get("multi_pass_count", "2"))))
    except (TypeError, ValueError):
        multi_pass_count = 2
    return {
        "status": status,
        "ai_parser": {
            "available": bool(provider.get("available")),
            "provider": provider.get("provider"),
            "model": settings.get("openai_model", "gpt-5-mini"),
            "multi_pass_count": multi_pass_count,
            "multi_pass_disagreement_policy": "reject_without_pricing_writes",
            "semantic_duplicate_policy": "merge_explicit_code_punctuation_or_unambiguous_name_similarity",
            "image_only_pdf_vision": True,
        },
        "email_monitor": {
            "quote_emails_enabled": QUOTE_EMAILS_ENABLED,
            "enabled": automation_enabled,
            "running": monitor_running,
            "simulator_running": simulator_running,
            "test_mode": test_mode,
            "retry_failed_unread": True,
            "idempotency": idempotency["mechanism"],
            "idempotency_verified": idempotency["verified"],
            "idempotency_missing": idempotency["missing"],
            "job_match": "stable_subject_tag_then_unambiguous_project_match",
            "parse_failure_policy": "no_pricing_writes_until_every_selected_source_parses",
        },
        "dropbox_import": {
            "mode": "browser_folder_picker",
            "source_scope": "local_synced_folder",
            "cloud_connector_configured": False,
            "automatic_sync": False,
            "requires_user_action": True,
            "structured_csv_contract": "named_columns_without_ai",
            "supported_extensions": [".eml", ".msg", ".pdf", ".txt", ".csv", ".xlsx"],
            "max_file_mb": MAX_QUOTE_FILE_BYTES // (1024 * 1024),
        },
        "durable_artifact_root": ARTIFACT_ROOT,
        "pricing_evidence": {
            "per_material_source_receipts": provenance["verified"],
            "source_fields": ["quote_source_hash", "quote_file_name"],
            "readiness_requires_exact_hash": True,
            "missing_fields": provenance["missing"],
            "auditable_conflict_decisions": decisions["verified"],
            "decision_missing_fields": decisions["missing"],
        },
    }

@app.get("/api/rules")
def api_list_rules(category: str = None, stage: str = None, status: str = None):
    """List hard estimating rules with optional category/stage/status filters."""
    rules = list_rules(category=category, stage=stage, status=status)
    build = get_build_info()
    return {"rules": [_rule_with_engine_contract(rule, build) for rule in rules], "count": len(rules)}


@app.get("/api/rules/active")
def api_get_active_rules(stage: str = None, category: str = None, as_of: str = None):
    """List currently active estimating rules for audit/calculation consumers."""
    rules = get_active_rules(stage=stage, category=category, as_of=as_of)
    build = get_build_info()
    return {"rules": [_rule_with_engine_contract(rule, build) for rule in rules], "count": len(rules)}


def _rules_registry_contract() -> dict:
    active = get_active_rules()
    gaps = [
        rule.get("rule_id")
        for rule in active
        if not str(rule.get("implementation_ref") or "").strip()
        or not str(rule.get("test_ref") or "").strip()
    ]
    return {
        "mode": "metadata_with_implementation_refs",
        "status": "warning" if gaps else "pass",
        "implementation_gaps": gaps,
        "active_rule_count": len(active),
        "calculation_behavior": "engine_code_and_config",
        "registry_changes_are_metadata_only": True,
        "behavior_change_signal": "engine_and_config_fingerprints",
    }


def _seed_rules_audited(overwrite: bool = False) -> dict:
    """Seed the built-in rules with one history entry listing what changed
    (none when every built-in rule was already there)."""
    with entity_write("ruleset", RULES_REGISTRY, _load_rules_registry, "rules.seed") as tx:
        result = seed_rules_registry_defaults(overwrite=overwrite, changed_by=_person_name(), conn=tx.conn)
        done = [f"{result[key]} {label}" for key, label in (
            ("inserted", "added"), ("updated", "overwritten"), ("corrected", "corrected"),
            ("contract_backfilled", "given code and test references"),
        ) if result.get(key)]
        tx.set_summary("Built-in estimating rules: " + (", ".join(done) or "no changes"))
        tx.extra.update({"overwrite": bool(overwrite), **result})
    return result


@app.post("/api/rules/seed")
@audit_route("rules.seed")
def api_seed_rules(overwrite: bool = False):
    """Seed built-in hard estimating rules."""
    return _seed_rules_audited(overwrite)


@app.get("/api/rulesets")
def api_list_rulesets(limit: int = 25):
    """List whole-registry ruleset versions."""
    versions = list_ruleset_versions(limit=limit)
    current = versions[0] if versions else None
    return {
        "versions": versions,
        "current": current,
        "current_version": current["version"] if current else None,
        "count": len(versions),
        "contract": _rules_registry_contract(),
    }


@app.get("/api/rulesets/{version}")
def api_get_ruleset(version: int):
    """Fetch a whole-registry ruleset snapshot."""
    ruleset = get_ruleset_version(version)
    if not ruleset:
        raise HTTPException(status_code=404, detail="Ruleset version not found")
    return _ruleset_with_engine_contract(ruleset)


@app.post("/api/rulesets/{version}/rollback")
@audit_route("ruleset.rollback")
def api_rollback_ruleset(version: int, body: Optional[RulesetRollbackRequest] = None):
    """Restore rules to a previous whole-registry snapshot as a new ruleset version."""
    body = body or RulesetRollbackRequest()
    change_note = body.change_note or f"Rolled registry back to ruleset v{version}."
    try:
        with entity_write(
            "ruleset", RULES_REGISTRY, _load_rules_registry, "ruleset.rollback",
            summary=f"Rolled the estimating rules back to rule set v{version}",
            extra={"rolled_back_to": version, "change_note": change_note},
        ) as tx:
            new_version = rollback_ruleset_version(
                version, changed_by=_person_name(), change_note=change_note, conn=tx.conn,
            )
            tx.extra["new_version"] = new_version
            tx.force_record()  # a new rule set version is saved even if no rule changed
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "status": "ok",
        "rolled_back_to": version,
        "new_version": new_version,
        "current": get_ruleset_version(new_version),
    }


@app.post("/api/rules/draft-from-lesson")
@no_audit("AI draft only: returns a suggested rule and saves nothing")
def api_draft_rule_from_lesson(body: RuleDraftRequest):
    """Use AI to turn a spoken/plain-English lesson into a rule draft."""
    lesson = (body.lesson_text or "").strip()
    if len(lesson) < 8:
        raise HTTPException(status_code=400, detail="Tell me a little more about the rule.")

    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    provider = get_provider_info(api_key)
    if not provider["available"]:
        raise HTTPException(status_code=400, detail="AI is not configured. Add an API key in Settings first.")

    import json as _json
    import re as _re

    system_msg = """You turn spoken estimating lessons into draft rules for a commercial flooring bid platform.
Return ONLY valid JSON. Do not include markdown.

Output shape:
{
  "rule_id": "custom.short.stable.id",
  "name": "Short human name",
  "category": "material|pricing|labor|sundry|freight|tax|proposal|classification|audit",
  "stage": "classification|pricing|sundry|labor|proposal|audit|rfms_parse|quote_parse|sundry_calc|labor_calc|proposal_generate",
  "status": "draft",
  "priority": 10,
  "description": "What Josh wants this to do.",
  "condition_json": {},
  "action_json": {},
  "source": "Josh spoken lesson",
  "notes": "Important assumptions or examples.",
  "change_note": "Initial spoken lesson from Josh.",
  "assumptions": [],
  "needs_review": true
}

Rules:
- Use status "draft" unless the lesson is extremely precise.
- Never claim the app already enforces the rule.
- Use condition_json for WHEN the rule applies.
- Use action_json for WHAT should happen.
- Keep JSON simple and readable for a human reviewer.
- If the spoken lesson is ambiguous, preserve the ambiguity in notes/assumptions instead of inventing specifics."""

    user_msg = f"""Josh said this rule out loud:

{lesson}

Draft the rule fields for the registry. Use a stable rule_id starting with custom."""

    try:
        raw = chat_complete(
            system=system_msg,
            user=user_msg,
            api_key=api_key,
            model=model,
            json_mode=True,
        )
        parsed = _json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not draft rule: {e}")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=500, detail="AI returned an invalid rule draft.")

    def _slug(value: str) -> str:
        value = _re.sub(r"[^a-z0-9]+", ".", (value or "").lower()).strip(".")
        return value[:72] or "spoken.lesson"

    name = str(parsed.get("name") or lesson[:80]).strip()
    rule_id = str(parsed.get("rule_id") or "").strip()
    if not rule_id.startswith("custom."):
        rule_id = f"custom.{_slug(rule_id or name)}"

    condition_json = parsed.get("condition_json")
    action_json = parsed.get("action_json")
    if not isinstance(condition_json, dict):
        condition_json = {"spoken_condition": str(condition_json or lesson)}
    if not isinstance(action_json, dict):
        action_json = {"spoken_action": str(action_json or "Needs review")}

    try:
        priority = int(parsed.get("priority") or 10)
    except (TypeError, ValueError):
        priority = 10

    return {
        "draft": {
            "rule_id": rule_id,
            "name": name,
            "category": str(parsed.get("category") or "material").strip() or "material",
            "stage": str(parsed.get("stage") or "classification").strip() or "classification",
            "status": "draft",
            "priority": priority,
            "description": str(parsed.get("description") or lesson).strip(),
            "condition_json": condition_json,
            "action_json": action_json,
            "source": str(parsed.get("source") or "Josh spoken lesson").strip(),
            "implementation_ref": "",
            "test_ref": "",
            "notes": str(parsed.get("notes") or "").strip(),
            # Saving the rule records the logged-in person whatever this says.
            "changed_by": _person_name(),
            "change_note": str(parsed.get("change_note") or "Initial spoken lesson from Josh.").strip(),
        },
        "assumptions": parsed.get("assumptions") if isinstance(parsed.get("assumptions"), list) else [],
        "needs_review": bool(parsed.get("needs_review", True)),
        "transcript": lesson,
    }


@app.get("/api/rules/{rule_id}/versions")
def api_get_rule_versions(rule_id: str):
    """List all saved versions for a rule."""
    rule = get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    versions = list_rule_versions(rule_id)
    build = get_build_info()
    contracted_versions = []
    for version in versions:
        item = dict(version)
        item["snapshot"] = _rule_with_engine_contract(item.get("snapshot") or {}, build)
        contracted_versions.append(item)
    return {"rule": _rule_with_engine_contract(rule, build), "versions": contracted_versions, "count": len(versions)}


@app.get("/api/rules/{rule_id}")
def api_get_rule(rule_id: str):
    """Get a single estimating rule."""
    rule = get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return _rule_with_engine_contract(rule)


# Rule versions record the logged-in person as changed_by (a changed_by sent
# by the page is ignored), and each change also gets an audit entry.

@app.post("/api/rules")
@audit_route("rule.create")
def api_create_rule(body: RuleCreate):
    """Create a hard estimating rule."""
    data = body.model_dump()
    data["condition_json"] = data.get("condition_json") or {}
    data["action_json"] = data.get("action_json") or {}
    data["changed_by"] = _person_name()
    try:
        with entity_write("rule", None, _load_rule, "rule.create",
                          extra={"change_note": data.get("change_note") or "Rule created."}) as tx:
            rule_id = create_rule(data, conn=tx.conn)
            tx.entity_id = rule_id
            tx.set_summary(f"Added rule {rule_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Rule already exists")
    return _rule_with_engine_contract(get_rule(rule_id))


@app.put("/api/rules/{rule_id}")
@audit_route("rule.update")
def api_update_rule(rule_id: str, body: RuleUpdate):
    """Update a hard estimating rule. Each edit creates a new version."""
    updates = body.model_dump(exclude_unset=True)
    updates.pop("changed_by", None)
    changed_by = _person_name()
    change_note = updates.pop("change_note", None) or "Rule updated from registry."
    if updates.get("name") is None and "name" in updates:
        raise HTTPException(status_code=400, detail="name cannot be null")
    for key in ("category", "stage", "status", "source", "description", "implementation_ref", "test_ref", "notes"):
        if updates.get(key) is None and key in updates:
            updates[key] = ""
    for key in ("priority", "version"):
        if updates.get(key) is None and key in updates:
            raise HTTPException(status_code=400, detail=f"{key} cannot be null")
    if "condition_json" in updates and updates["condition_json"] is None:
        updates["condition_json"] = {}
    if "action_json" in updates and updates["action_json"] is None:
        updates["action_json"] = {}
    if not updates:
        raise HTTPException(status_code=400, detail="No rule fields supplied")
    try:
        with entity_write("rule", rule_id, _load_rule, "rule.update",
                          summary=f"Changed rule {rule_id}", extra={"change_note": change_note}) as tx:
            updated = update_rule(rule_id, updates, changed_by=changed_by, change_note=change_note, conn=tx.conn)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="Rule not found")
    return _rule_with_engine_contract(get_rule(rule_id))


def _archive_rule_audited(rule_id: str, change_note: str) -> bool:
    with entity_write("rule", rule_id, _load_rule, "rule.archive",
                      summary=f"Archived rule {rule_id}", extra={"change_note": change_note}) as tx:
        return archive_rule(rule_id, changed_by=_person_name(), change_note=change_note, conn=tx.conn)


@app.post("/api/rules/{rule_id}/archive")
@audit_route("rule.archive")
def api_archive_rule(rule_id: str, body: Optional[RuleChangeMeta] = None):
    """Archive a rule without erasing its history."""
    body = body or RuleChangeMeta()
    if not _archive_rule_audited(rule_id, body.change_note or "Rule archived from registry."):
        raise HTTPException(status_code=404, detail="Rule not found")
    return _rule_with_engine_contract(get_rule(rule_id))


@app.delete("/api/rules/{rule_id}")
@audit_route("rule.archive")
def api_delete_rule(rule_id: str):
    """Archive a hard estimating rule. History is preserved for old bids."""
    if not _archive_rule_audited(rule_id, "Rule archived."):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"message": "Rule archived", "rule": _rule_with_engine_contract(get_rule(rule_id))}


@app.get("/api/jobs")
def api_list_jobs():
    """List all jobs (deleted bids left out: see /api/jobs/deleted)."""
    return list_jobs()


# Registered before /api/jobs/{job_id} so "deleted" isn't read as a job id.
@app.get("/api/jobs/deleted")
def api_list_deleted_jobs():
    """Deleted bids, most recently deleted first: who deleted each one, when, why and its saved total.

    Anyone logged in can look; only an admin can restore one.
    """
    return list_deleted_jobs()


@app.get("/api/jobs/match")
def api_match_job(q: str = ""):
    """Fuzzy-match an email subject or project reference to a job.
    Used by the local quote agent to find which job a vendor email belongs to."""
    if not q or len(q) < 3:
        return {"job_id": None, "project_name": None, "gc_name": None, "score": 0}

    # Clean the query — strip RE:, FW:, [EXT], etc.
    import re as _re
    cleaned = _re.sub(r"^(re|fw|fwd|ext|\[ext\])[\s:]+", "", q, flags=_re.IGNORECASE).strip()
    cleaned = _re.sub(r"^(quote\s*request|pricing|price\s*list|proposal)\s*[-:–—]\s*", "", cleaned, flags=_re.IGNORECASE).strip()

    # Search using existing search_all
    results = search_all(cleaned[:80])
    jobs_found = results.get("jobs", [])
    if jobs_found:
        best = jobs_found[0]
        return {
            "job_id": best["id"],
            "project_name": best.get("project_name", ""),
            "gc_name": best.get("gc_name", ""),
            "score": 0.8,
        }

    # Try word-level matching against all jobs
    all_jobs = list_jobs()
    cleaned_lower = cleaned.lower()
    cleaned_words = set(_re.sub(r"[^a-z0-9\s]", "", cleaned_lower).split())

    best_job = None
    best_score = 0
    for job in all_jobs:
        name = (job.get("project_name") or "").lower()
        gc = (job.get("gc_name") or "").lower()
        combined_words = set(_re.sub(r"[^a-z0-9\s]", "", f"{gc} {name}").split())
        if not combined_words or not cleaned_words:
            continue
        overlap = cleaned_words & combined_words
        score = len(overlap) / max(len(cleaned_words), 1)
        if name in cleaned_lower or cleaned_lower in name:
            score += 0.3
        if score > best_score:
            best_score = score
            best_job = job

    if best_job and best_score >= 0.3:
        return {
            "job_id": best_job["id"],
            "project_name": best_job.get("project_name", ""),
            "gc_name": best_job.get("gc_name", ""),
            "score": round(best_score, 2),
        }

    return {"job_id": None, "project_name": None, "gc_name": None, "score": 0}


@app.post("/api/jobs")
@audit_route("job.create")
def api_create_job(job: JobCreate):
    """Create a new job."""
    summary = f"Job '{job.project_name}' created"
    try:
        with entity_write("job", None, load_job_snapshot, "job.create", summary=summary) as tx:
            job_id = create_job_row(tx.conn, job.model_dump())
            tx.entity_id = tx.job_id = job_id
            log_activity(job_id, "job_created", summary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    created = load_job(job_id)
    return {"id": job_id, "slug": created.get("slug", ""), "message": "Job created"}


def _resolve_job_id(job_id: str, include_deleted: bool = False) -> int:
    """Resolve a job_id string (could be slug or numeric ID) to a numeric DB id.

    A deleted bid is "not found" (404, saying who deleted it and when) unless
    ``include_deleted``. Changes to a deleted bid never get this far: they are
    refused with 410 first (_refuse_writes_to_deleted_jobs).
    """
    db_id = resolve_job_ref(job_id)
    if db_id is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not include_deleted:
        row = deleted_job_row(db_id)
        if row is not None:
            raise JobNotFoundError(deleted_bid_message(row), **deleted_bid_info(row))
    return db_id


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str, include_deleted: bool = False):
    """Get job details by ID or slug.

    ``?include_deleted=1`` also returns a deleted bid (read-only), with its
    deleted_at, deleted_by (and deleted_by_name) and delete_reason.
    """
    db_id = _resolve_job_id(job_id, include_deleted=include_deleted)
    job = load_job(db_id, include_deleted=include_deleted)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("deleted_at"):
        job["deleted_by_name"] = deleted_bid_info(job)["deleted_by_name"]
    job["materials_source_fingerprint"] = _materials_source_fingerprint(job.get("materials") or [])
    # Known prices are read-only suggestions. Opening a job must never change
    # accepted source data or stale an existing proposal audit.
    _enrich_known_prices(job)
    return job


def _enrich_known_prices(job: dict):
    """Add transient price suggestions without mutating persisted job inputs."""
    materials = job.get("materials", [])
    applied_count = 0
    if not materials:
        return 0
    price_list = get_price_list_entries()

    # Build a map of normalized vendor prices (latest price per product)
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT vp.product_normalized, vp.unit_price, vp.vendor_name, vp.unit,
                   vp.created_at AS latest_date
            FROM vendor_prices vp
            WHERE vp.unit_price > 0
              AND vp.id = (
                  SELECT newest.id
                  FROM vendor_prices newest
                  WHERE newest.product_normalized = vp.product_normalized
                    AND newest.unit_price > 0
                  ORDER BY newest.created_at DESC, newest.id DESC
                  LIMIT 1
              )
            ORDER BY vp.created_at DESC
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
            mat["known_unit_price"] = pl_match["unit_price"]
            mat["known_price_source"] = "price_list"
            mat["known_price_vendor"] = pl_match.get("vendor", "")
            applied_count += 1
            continue

        # Check vendor price history
        normalized = _normalize_product(item_code or description)
        if normalized and len(normalized) >= 3:
            for key, vp in vendor_map.items():
                if normalized in key or key in normalized:
                    order_qty = mat.get("order_qty") or mat.get("installed_qty") or 1
                    mat["known_price"] = round(vp["unit_price"] * order_qty, 2)
                    mat["known_unit_price"] = vp["unit_price"]
                    mat["known_price_source"] = "vendor_history"
                    mat["known_price_vendor"] = vp.get("vendor_name", "")
                    applied_count += 1
                    break

    return applied_count


def _job_delete_snapshot(conn, db_id: int, row: dict) -> dict:
    """What a bid held just before it is deleted: counts and totals for the history entry."""
    counts = {}
    for label, table in (
        ("materials", "job_materials"), ("sundries", "job_sundries"), ("labor", "job_labor"),
        ("bundles", "job_bundles"), ("quotes", "job_quotes"), ("comments", "job_comments"),
        ("activity", "job_activity"), ("bid_events", "bid_events"), ("imported_files", "imported_files"),
    ):
        try:
            counts[label] = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE job_id=?", (db_id,)).fetchone()[0])
        except sqlite3.Error:
            continue
    material_cost = conn.execute(
        "SELECT COALESCE(SUM(extended_cost), 0) FROM job_materials WHERE job_id=?", (db_id,)
    ).fetchone()[0]

    def saved_total(raw):
        try:
            data = json.loads(raw) if isinstance(raw, str) and raw else raw
            total = (data or {}).get("grand_total") if isinstance(data, dict) else None
            return round(float(total), 2) if total is not None else None
        except (TypeError, ValueError):
            return None

    proposal_total = saved_total(row.get("proposal_data"))
    bid_total = saved_total(row.get("bid_data"))
    return {
        "project_name": row.get("project_name"),
        "slug": row.get("slug"),
        "gc_name": row.get("gc_name"),
        "bid_status": row.get("bid_status"),
        "version": row.get("version"),
        "counts": counts,
        "material_cost": round(float(material_cost or 0), 2),
        "proposal_total": proposal_total,
        "bid_total": bid_total,
        "grand_total": proposal_total if proposal_total is not None else bid_total,
    }


def _clean_delete_reason(reason) -> str:
    try:
        return clean_delete_reason(reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _delete_job_audited(job_ref, reason: str) -> int:
    """Delete (hide) one bid, recording what it held, who deleted it and why.

    Nothing is removed: the bid, its PDFs and its history stay, and an admin
    can restore it. Raises JobNotFoundError, or JobDeletedError (410) if it
    was already deleted. Returns the bid's id.
    """
    with job_write(job_ref, action="job.delete", scopes=("job", "tracking")) as tx:
        snapshot = _job_delete_snapshot(tx.conn, tx.job_id, tx.row)
        total = snapshot["grand_total"]
        material_count = snapshot["counts"].get("materials", 0)
        details = [f"{material_count} material{'' if material_count == 1 else 's'}"]
        if total is not None:
            details.append(f"total ${total:,.2f}")
        summary = f"Deleted bid '{snapshot['project_name'] or tx.job_id}' ({', '.join(details)}). Reason: {reason}"
        tx.set_summary(summary)
        tx.extra["deleted"] = snapshot
        tx.extra["reason"] = reason
        tx.force_record()
        if not delete_job(tx.job_id, reason=reason, deleted_by=audit.actor_label(), conn=tx.conn):
            raise JobDeletedError.for_row(tx.row, tx.conn)  # job_write already refuses deleted bids
        log_activity(tx.job_id, "job_deleted", summary, {"reason": reason})
    return tx.job_id


@app.post("/api/jobs/bulk-delete")
@audit_route("job.delete")
def api_bulk_delete(body: BulkDeleteRequest):
    """Delete (hide) several bids with one reason. Each bid gets its own history
    entry; they share the request id. Bids already deleted or not found are
    listed and skipped."""
    reason = _clean_delete_reason(body.reason)
    refs: list = []
    for ref in [*body.ids, *body.job_ids]:
        ref = str(ref).strip()
        if ref and ref not in refs:
            refs.append(ref)
    if not refs:
        raise HTTPException(status_code=400, detail="Pick at least one bid to delete.")
    deleted_ids, not_found, already_deleted = [], [], []
    for ref in refs:
        try:
            deleted_ids.append(_delete_job_audited(ref, reason))
        except JobNotFoundError:
            not_found.append(ref)
        except JobDeletedError:
            already_deleted.append(ref)
    audit.note_checked()  # none deleted still counts as handled
    return {
        "deleted": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "not_found": not_found,
        "already_deleted": already_deleted,
    }


@app.delete("/api/jobs/{job_id}")
@audit_route("job.delete")
def api_delete_job(job_id: str, body: Optional[JobDeleteRequest] = None):
    """Delete (hide) a bid by ID or slug. Body: {"reason": "..."} (required).

    The bid moves to Deleted bids: it disappears from lists, search and the
    bid tracker, can't be changed (410), and an admin can restore it.
    """
    reason = _clean_delete_reason((body or JobDeleteRequest()).reason)
    db_id = _resolve_job_id(job_id)
    _delete_job_audited(db_id, reason)
    return {"message": "Bid deleted", "id": db_id}


@app.post("/api/jobs/{job_id}/restore")
@audit_route("job.restore")
def api_restore_job(job_id: str, request: Request):
    """Bring back a deleted bid (admins only). Returns the job."""
    _require_admin(request, "Only an admin can restore a deleted bid.")
    db_id = _resolve_job_id(job_id, include_deleted=True)
    with job_write(db_id, action="job.restore", scopes=("job", "tracking"), allow_deleted=True) as tx:
        if not tx.row.get("deleted_at"):
            raise HTTPException(status_code=409, detail="This bid isn't deleted, so there's nothing to restore.")
        info = deleted_bid_info(tx.row, tx.conn)
        was = f"deleted by {info['deleted_by_name']}"
        when = audit.parse_ts(tx.row.get("deleted_at"))
        if when:
            was += f" on {when:%b} {when.day}, {when.year}"
        if tx.row.get("delete_reason"):
            was += f": {tx.row['delete_reason']}"
        summary = f"Restored bid '{tx.row.get('project_name') or tx.job_id}' ({was})"
        tx.set_summary(summary)
        tx.extra["restored"] = {key: info[key] for key in ("deleted_at", "deleted_by", "delete_reason")}
        restore_job(tx.job_id, conn=tx.conn)
        log_activity(tx.job_id, "job_restored", summary)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/duplicate")
@audit_route("job.duplicate")
def api_duplicate_job(job_id: str):
    """Duplicate a job and all its materials."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
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
        "gpm_pct": job.get("gpm_pct", 0),
        "unit_count": job.get("unit_count", 0),
        "tub_shower_count": job.get("tub_shower_count", 0),
        "salesperson": job.get("salesperson"),
        "notes": job.get("notes"),
        "exclusions": job.get("exclusions"),
        "markup_pct": job.get("markup_pct", 0),
        "architect": job.get("architect"),
        "designer": job.get("designer"),
        "textura_fee": job.get("textura_fee", 0),
    }
    # Customer and site details carry over; the copy gets its own quote,
    # PO and contract numbers.
    for field in JOB_ESTIMATE_HEADER_FIELDS:
        if field not in ("quote_number", "customer_po", "contract_number"):
            new_job[field] = job.get(field)

    # Copy materials (strip id, job_id, uid and row bookkeeping: the copies
    # are new lines with their own uids)
    materials = job.get("materials", [])
    copied = []
    for m in materials:
        mat = {k: v for k, v in m.items() if k not in ("id", "job_id", "uid", *stable_ids.ROW_META_COLUMNS)}
        copied.append(mat)

    summary = f"Duplicated from '{job['project_name']}'"
    with entity_write(
        "job", None, load_job_snapshot, "job.duplicate",
        summary=summary, extra={"source_job_id": job["id"]},
    ) as tx:
        new_id = create_job_row(tx.conn, new_job)
        tx.entity_id = tx.job_id = new_id
        if copied:
            save_materials(new_id, copied, conn=tx.conn)
        log_activity(new_id, "job_created", summary, {"source_job_id": job["id"]})

    created = load_job(new_id)
    return {"id": new_id, "slug": created.get("slug", "")}


@app.put("/api/jobs/{job_id}/notes")
@audit_route("job.notes.update")
def api_update_notes(job_id: str, body: NotesUpdate):
    """Update job notes."""
    db_id = _resolve_job_id(job_id)
    with job_write(
        db_id, action="job.notes.update", scopes=("job",), field_path="/notes",
        group=audit.TEXT_EDITS, summary="Notes updated",
    ) as tx:
        update_job_fields(tx.conn, db_id, {"notes": body.notes})
        log_activity(db_id, "notes_updated", "Notes updated")
    return {"message": "Notes saved"}


class JobUpdate(BaseModel):
    markup_pct: Optional[float] = None
    gpm_pct: Optional[float] = None
    project_name: Optional[str] = None
    gc_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    tax_rate: Optional[float] = None
    unit_count: Optional[int] = None
    tub_shower_count: Optional[int] = None
    salesperson: Optional[str] = None
    notes: Optional[str] = None
    architect: Optional[str] = None
    designer: Optional[str] = None
    textura_fee: Optional[int] = None
    # Estimate PDF header fields; send "" to clear one.
    quote_number: Optional[str] = None
    customer_po: Optional[str] = None
    contract_number: Optional[str] = None
    salesperson2: Optional[str] = None
    customer_account: Optional[str] = None
    customer_address: Optional[str] = None
    customer_city: Optional[str] = None
    customer_state: Optional[str] = None
    customer_zip: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_fax: Optional[str] = None
    site_phone: Optional[str] = None
    site_contact: Optional[str] = None

@app.put("/api/jobs/{job_id}")
@audit_route("job.update")
def api_update_job(job_id: str, body: JobUpdate):
    """Update job fields."""
    db_id = _resolve_job_id(job_id)
    updates = body.model_dump(exclude_none=True)
    try:
        # A form save: quick re-saves of the same field(s) join one history entry.
        with job_write(db_id, action="job.update", scopes=("job",), group=audit.NUMBER_EDITS) as tx:
            changes = {}
            for key, val in updates.items():
                old_val = tx.row.get(key)
                if old_val != val:
                    changes[key] = {"old": old_val, "new": val}
            # "" and None read the same in the history, so the summary names real changes only.
            real_changes = [key for key, change in changes.items() if not audit.values_equal(change["old"], change["new"])]
            if real_changes:
                tx.set_summary(f"Updated {', '.join(real_changes)}")
            update_job_fields(tx.conn, db_id, updates)
            if changes:
                changed_keys = ", ".join(changes.keys())
                log_activity(db_id, "job_updated", f"Updated {changed_keys}", {"changes": changes})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Job updated"}


# ── Bid Tracker ──────────────────────────────────────────────────────────────
# Replaces JobRunner's bid register: status, due date, estimator and follow-ups
# for every job, plus a history of who did what and when. Nothing is emailed.


class BidTrackingUpdate(BaseModel):
    """Only the fields sent are changed; send "" or null to clear one."""
    bid_status: Optional[str] = None
    bid_due_date: Optional[str] = None
    bid_due_time: Optional[str] = None
    estimator: Optional[str] = None
    next_follow_up_date: Optional[str] = None
    won_lost_reason: Optional[str] = None
    awarded_amount: Optional[float | str] = None
    note: Optional[str] = None
    today: Optional[str] = None  # the person's local date, YYYY-MM-DD


class BidEventCreate(BaseModel):
    event_type: str
    note: Optional[str] = None
    sent_to: Optional[str | list[str]] = None      # sent: names / emails
    gc_name: Optional[str] = None                  # sent: which GC it went to
    sent_on: Optional[str] = None                  # sent: date sent, default today
    next_follow_up_date: Optional[str] = None      # sent / follow_up
    reason: Optional[str] = None                   # won / lost
    awarded_amount: Optional[float | str] = None   # won / lost
    today: Optional[str] = None                    # the person's local date


def _request_username(request: Request) -> str | None:
    user = getattr(request.state, "user", None) or {}
    return user.get("username")


def _bid_tracking_payload(db_id: int, today: date) -> dict:
    row = get_bid_tracker_job(db_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "today": today.isoformat(),
        "statuses": list(BID_STATUSES),
        "tracking": decorate_bid_row(row, today),
        "events": list_bid_events(db_id),
    }


def _current_bid_tracking(db_id: int) -> dict:
    row = get_bid_tracker_job(db_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return row


def _bid_money_text(amount) -> str:
    return f"${amount:,.2f}" if isinstance(amount, (int, float)) else ""


def _bid_send_evidence(db_id: int) -> dict:
    """Which saved proposal and which printed PDF were current when the bid went out."""
    evidence: dict = {}
    job = load_job(db_id) or {}
    proposal = job.get("proposal_data")
    if isinstance(proposal, dict) and proposal.get("bundles"):
        evidence["proposal_revision"] = proposal.get("_server_revision")
        pdf_total = (proposal.get("pdf_totals") or {}).get("grand_total")
        if pdf_total is not None:
            evidence["pdf_total"] = pdf_total
    # The exact printed PDF (every print is kept; download it by this id).
    pdf = get_latest_job_artifact(db_id, "proposal_pdf")
    if pdf:
        evidence["pdf"] = {
            "artifact_id": pdf["id"],
            "file_hash": pdf["file_hash"],
            "file_size": pdf["file_size"],
            "created_at": pdf["created_at"],
            "grand_total": pdf.get("grand_total"),
            "proposal_version_id": pdf.get("proposal_version_id"),
        }
    return evidence


@app.get("/api/bid-tracker")
def api_bid_tracker(today: Optional[str] = None):
    """Every job as a bid, with due-date / follow-up flags and the summary counts."""
    local_today = resolve_today(today)
    bids = [decorate_bid_row(row, local_today) for row in list_bid_tracker_jobs()]
    return {
        "today": local_today.isoformat(),
        "statuses": list(BID_STATUSES),
        "summary": summarize_bids(bids, local_today),
        "bids": bids,
    }


@app.get("/api/jobs/{job_id}/bid-tracking")
def api_get_bid_tracking(job_id: str, today: Optional[str] = None):
    """One job's bid tracking fields and history."""
    db_id = _resolve_job_id(job_id)
    return _bid_tracking_payload(db_id, resolve_today(today))


@app.get("/api/jobs/{job_id}/bid-events")
def api_list_bid_events(job_id: str):
    """One job's bid history, newest first."""
    db_id = _resolve_job_id(job_id)
    return list_bid_events(db_id)


@app.patch("/api/jobs/{job_id}/bid-tracking")
@audit_route("bid.status", "bid.sent", "bid.tracking.update", "bid.note")
def api_update_bid_tracking(job_id: str, body: BidTrackingUpdate, request: Request):
    """Change status, due date, estimator or next follow-up; records who changed what."""
    db_id = _resolve_job_id(job_id)
    given = body.model_dump(exclude_unset=True)
    try:
        today = resolve_today(given.pop("today", None))
        note = clean_text(given.pop("note", None), MAX_NOTE_LENGTH, "Note")
        fields = clean_tracking_fields(given)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    current = _current_bid_tracking(db_id)
    old_status, _ = effective_bid_status(current["bid_status"], current["material_count"])
    new_status = fields.pop("bid_status", None)

    updates: dict = {}
    changes: dict = {}
    for column, value in fields.items():
        if current.get(column) != value:
            updates[column] = value
            changes[column] = {"old": current.get(column), "new": value}

    details: dict = {}
    if new_status and new_status != old_status:
        updates["bid_status"] = new_status
        updates.update(status_change_updates(old_status, new_status, today, fields))
        details.update({"from": old_status, "to": new_status})
    elif new_status and current["bid_status"] != new_status:
        # Confirming the shown default status: store it, nothing to report.
        updates["bid_status"] = new_status
    if changes:
        details["changes"] = changes
    if note:
        details["note"] = note

    if details.get("to") == "Sent":
        # Setting the status to Sent is the same as "Mark as sent": record the
        # send (today, the GC and the saved bid total) so the tracker shows
        # when it went out. Other fields changed alongside get their own entry.
        sent_details = {
            "sent_to": None,
            "gc_name": current["gc_name"] or None,
            "sent_on": today.isoformat(),
            "bid_total": current["bid_total"],
            **_bid_send_evidence(db_id),
            "from": old_status,
        }
        if note:
            sent_details["note"] = note
        events = [("note", {"changes": changes})] if changes else []
        events.append(("sent", sent_details))
    else:
        events = [("status_change" if "to" in details else "note", details)] if details else []

    # (activity action, summary, detail) for the bid's activity list; the
    # summary also names the history entry.
    activity = None
    action = "bid.tracking.update"
    if details.get("to") == "Sent":
        action = "bid.sent"
        total = _bid_money_text(current["bid_total"])
        gc_text = f" to {current['gc_name']}" if current["gc_name"] else ""
        activity = ("bid_sent",
                    f"Bid marked as sent{gc_text}" + (f" ({total})" if total else ""),
                    {"gc_name": current["gc_name"], "bid_total": current["bid_total"],
                     **({"changes": changes} if changes else {})})
    elif "to" in details:
        action = "bid.status"
        activity = ("bid_status_changed", f"Bid status changed from {old_status} to {new_status}",
                    {"changes": changes} if changes else None)
    elif changes:
        labels = ", ".join(BID_FIELD_LABELS.get(column, column).lower() for column in changes)
        activity = ("bid_tracking_updated", f"Bid tracking updated: {labels}", {"changes": changes})
    elif note:
        action = "bid.note"
        activity = ("bid_note_added", "Bid note added", None)

    if updates or events:
        with job_write(db_id, action=action, scopes=("tracking",),
                       summary=activity[1] if activity else None) as tx:
            _link_sent_version(tx, events)
            save_bid_tracking(db_id, updates, events, _request_username(request), conn=tx.conn)
            if activity:
                log_activity(db_id, *activity)
    else:
        audit.note_checked(db_id)  # nothing to change
    return _bid_tracking_payload(db_id, today)


@app.post("/api/jobs/{job_id}/bid-events")
@audit_route("bid.sent", "bid.follow_up", "bid.note", "bid.won", "bid.lost")
def api_add_bid_event(job_id: str, body: BidEventCreate, request: Request):
    """Log that the bid was sent, a follow-up, a note, or that it was won or lost."""
    db_id = _resolve_job_id(job_id)
    event_type = str(body.event_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if event_type not in POSTABLE_BID_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"event_type must be one of: {', '.join(POSTABLE_BID_EVENT_TYPES)}.",
        )
    given = body.model_fields_set
    current = _current_bid_tracking(db_id)
    old_status, _ = effective_bid_status(current["bid_status"], current["material_count"])

    explicit: dict = {}   # tracking fields this event sets directly
    details: dict = {}
    new_status = None
    try:
        today = resolve_today(body.today)
        note = clean_text(body.note, MAX_NOTE_LENGTH, "Note")
        if event_type == "sent":
            sent_on = parse_date(body.sent_on, "Sent on") or today.isoformat()
            if date.fromisoformat(sent_on) > today + timedelta(days=MAX_FUTURE_SENT_DAYS):
                raise ValueError("Sent on can't be in the future.")
            details = {
                "sent_to": clean_sent_to(body.sent_to),
                "gc_name": clean_text(body.gc_name, MAX_SHORT_TEXT_LENGTH, "GC") or current["gc_name"] or None,
                "sent_on": sent_on,
                "bid_total": current["bid_total"],
                **_bid_send_evidence(db_id),
            }
            if "next_follow_up_date" in given:
                explicit["next_follow_up_date"] = parse_date(body.next_follow_up_date, "Next follow-up")
                details["next_follow_up_date"] = explicit["next_follow_up_date"]
            new_status = "Sent"
        elif event_type == "follow_up":
            if "next_follow_up_date" in given:
                explicit["next_follow_up_date"] = parse_date(body.next_follow_up_date, "Next follow-up")
                details["next_follow_up_date"] = explicit["next_follow_up_date"]
            if not note and not explicit.get("next_follow_up_date"):
                raise ValueError("Add a note about the follow-up or a next follow-up date.")
        elif event_type == "note":
            if not note:
                raise ValueError("Type a note first.")
        else:  # won / lost
            new_status = "Won" if event_type == "won" else "Lost"
            reason = clean_text(body.reason, MAX_REASON_LENGTH, "Reason")
            amount = parse_money(body.awarded_amount, "Awarded amount")
            if new_status == old_status:
                # Marked won/lost again (say, to add a note): keep the saved
                # reason and amount unless a new one was typed.
                if reason:
                    explicit["won_lost_reason"] = reason
                if amount is not None:
                    explicit["awarded_amount"] = amount
            else:
                explicit["won_lost_reason"] = reason
                explicit["awarded_amount"] = amount
            details = {
                "reason": explicit.get("won_lost_reason", current["won_lost_reason"]),
                "awarded_amount": explicit.get("awarded_amount", current["awarded_amount"]),
                "bid_total": current["bid_total"],
            }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if note:
        details["note"] = note
    updates = dict(explicit)
    if new_status:
        if new_status != old_status:
            details["from"] = old_status
            updates.update(status_change_updates(old_status, new_status, today, explicit))
        if new_status in DECIDED_BID_STATUSES and not current.get("won_lost_at") and "won_lost_at" not in updates:
            updates["won_lost_at"] = today.isoformat()
        updates["bid_status"] = new_status

    if event_type == "sent":
        who = details.get("sent_to") or details.get("gc_name") or "the GC"
        total = _bid_money_text(details.get("bid_total"))
        activity = ("bid_sent", f"Bid sent to {who}" + (f" ({total})" if total else ""),
                    {"sent_to": details.get("sent_to"), "gc_name": details.get("gc_name"),
                     "bid_total": details.get("bid_total")})
    elif event_type in ("won", "lost"):
        amount = _bid_money_text(details.get("awarded_amount"))
        activity = (f"bid_{event_type}", f"Bid {event_type}" + (f" ({amount})" if amount else ""),
                    {"reason": details.get("reason"), "awarded_amount": details.get("awarded_amount")})
    elif event_type == "follow_up":
        activity = ("bid_follow_up", "Bid follow-up logged", None)
    else:
        activity = ("bid_note_added", "Bid note added", None)

    # The tracking fields, the bid event, the activity row and the history
    # entry are saved together.
    with job_write(db_id, action=f"bid.{event_type}", scopes=("tracking",), summary=activity[1]) as tx:
        events = [(event_type, details)]
        _link_sent_version(tx, events)
        save_bid_tracking(db_id, updates, events, _request_username(request), conn=tx.conn)
        log_activity(db_id, *activity)
    return _bid_tracking_payload(db_id, today)


@app.post("/api/jobs/{job_id}/upload-rfms")
@audit_route("rfms.upload")
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

    # Parsing, AI labelling and saving block, so they run off the event loop.
    return await run_in_threadpool(_upload_rfms_files, job_id, files)


def _upload_rfms_files(job_id: str, files: list[UploadFile]) -> dict:
    db_id = _resolve_job_id(job_id)

    all_materials_raw = []
    rfms_job_info = {}
    imported_uploads = []
    ai_statuses = []

    for file in files:
        if os.path.splitext(file.filename or "")[1].lower() != ".xlsx":
            raise HTTPException(status_code=400, detail=f"RFMS file '{file.filename}' must be an .xlsx workbook.")
        content = file.file.read(MAX_RFMS_FILE_BYTES + 1)
        if len(content) > MAX_RFMS_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"RFMS file '{file.filename}' exceeds the {MAX_RFMS_FILE_BYTES // (1024 * 1024)} MB limit.",
            )
        file_hash = hashlib.sha256(content).hexdigest()
        file_path = _job_upload_path(db_id, f"{file_hash[:12]}_{file.filename}", "rfms")
        with open(file_path, "wb") as f:
            f.write(content)
        _record_artifact(db_id, file_path, "rfms")

        try:
            result = parse_rfms(file_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse RFMS file '{file.filename}': {e}")
        imported_uploads.append((file.filename, file_hash, len(content), file_path))
        if result.get("ai_classification"):
            ai_statuses.append(result["ai_classification"])

        # Use job info from first file that has it
        file_job_info = result.get("job_info", {})
        if not rfms_job_info and any(file_job_info.values()):
            rfms_job_info = file_job_info

        # Detect area_type from filename: "common area(s)" or "amenity" → common, else unit
        fname_lower = (file.filename or "").lower()
        area_type = "common" if ("common area" in fname_lower or "amenity" in fname_lower or "common_area" in fname_lower) else "unit"
        for mat in result.get("materials", []):
            mat["area_type"] = area_type
        all_materials_raw.extend(result.get("materials", []))

    # Give the newly parsed lines their final codes before any merge, so a
    # re-parsed line always gets the same code. On a re-upload a line that
    # replaces a saved line keeps the saved line's code (merge_reupload_materials),
    # so saved codes are not renamed. Lines that share a code (e.g. the same
    # label in the units and common-area files) are kept and given their own
    # code, never silently dropped.
    label_uploaded_lines(all_materials_raw)
    new_lines = []
    for m in all_materials_raw:
        new_lines.append({
            "item_code": m.get("item_code"),
            "description": m.get("description"),
            "material_type": m.get("material_type", "unknown"),
            "ai_confidence": m.get("ai_confidence"),
            "installed_qty": m.get("qty", 0),
            "unit": m.get("unit"),
            "area_type": m.get("area_type", "unit"),
            "tack_strip_lf": m.get("tack_strip_lf", 0),
            "seam_tape_lf": m.get("seam_tape_lf", 0),
            "pad_sy": m.get("pad_sy", 0),
            "is_mosaic": m.get("is_mosaic", False),
            "is_penny_hex": m.get("is_penny_hex", False),
            "crack_isolation_sf": m.get("crack_isolation_sf", 0),
        })

    file_names = [f.filename for f in files if hasattr(f, 'filename')]
    # Import receipts, the header fields, the merged lines and the activity
    # rows are saved together, with one history entry.
    with job_write(db_id, action="rfms.upload", scopes=("job", "materials")) as tx:
        tx.force_record()
        # The proposal and the lines it was priced from as they are before this
        # upload; kept as a version below if the upload changes the lines.
        before_upload = proposal_versions.capture(tx.conn, db_id)
        tx.extra["files"] = [
            {"file_name": filename, "file_hash": file_hash, "file_size": file_size}
            for filename, file_hash, file_size, _ in imported_uploads
        ]
        for filename, file_hash, file_size, file_path in imported_uploads:
            record_imported_file(
                db_id,
                filename,
                file_hash,
                file_size,
                source="rfms",
                artifact_path=os.path.relpath(file_path, ARTIFACT_ROOT),
                artifact_kind="rfms",
                conn=tx.conn,
            )

        # Update job info from RFMS if available
        update_job_fields(tx.conn, db_id, {
            field: rfms_job_info[field]
            for field in ("project_name", "gc_name", "address", "city", "state", "zip")
            if rfms_job_info.get(field)
        })

        # The saved lines are read under the bid's lock, so a change saved
        # while the files were being parsed is merged instead of lost.
        existing_materials = [
            dict(row)
            for row in tx.conn.execute(
                "SELECT * FROM job_materials WHERE job_id=? ORDER BY id", (db_id,)
            ).fetchall()
        ]
        materials, dropped_saved_lines = _rfms_priced_materials(existing_materials, new_lines)
        material_ids = save_materials(db_id, materials, conn=tx.conn)
        if before_upload is not None and (
            proposal_versions.current_materials_fingerprint(tx.conn, db_id) != before_upload["materials_fingerprint"]
        ):
            tx.proposal_version_id, _ = proposal_versions.store(
                tx.conn, before_upload, "rfms_upload", match_materials=True,
            )

        # Attach IDs and uids to returned materials
        for mat, mid, uid in zip(materials, material_ids, material_ids.uids):
            mat["id"] = mid
            mat["uid"] = uid

        log_activity(db_id, "rfms_uploaded", f"Uploaded {len(file_names)} RFMS file(s), {len(materials)} materials parsed", {"files": file_names, "material_count": len(materials)})
        removed_materials = [
            {
                "item_code": em.get("item_code"),
                "description": em.get("description"),
                "area_type": em.get("area_type") or "unit",
                "extended_cost": em.get("extended_cost"),
            }
            for em in dropped_saved_lines
        ]
        if removed_materials:
            log_activity(
                db_id,
                "rfms_lines_removed",
                f"Re-upload removed {len(removed_materials)} saved line(s) the revised takeoff no longer has",
                {"files": file_names, "lines": removed_materials},
            )

    ai_classification = _combine_ai_classification(ai_statuses)
    if ai_classification["total"] and ai_classification["message"]:
        log_activity(db_id, "rfms_ai_not_used", ai_classification["message"], ai_classification)

    updated_job = load_job(db_id) or {}
    return {
        "job_id": db_id,
        "slug": updated_job.get("slug"),
        "job_info": rfms_job_info,
        "materials": materials,
        "removed_materials": removed_materials,
        "ai_classification": ai_classification,
    }


def _combine_ai_classification(statuses: list[dict]) -> dict:
    """One summary of whether AI sorted the takeoff lines, across all uploaded files."""
    statuses = [st for st in statuses if st.get("total")]
    classified = sum(st.get("classified", 0) for st in statuses)
    total = sum(st.get("total", 0) for st in statuses)
    ai_used = bool(statuses) and all(st.get("ai_used") for st in statuses)
    messages = [st["message"] for st in statuses if st.get("message")]
    if not messages:
        message = None
    elif len(statuses) == 1:
        message = messages[0]
    elif classified == 0:
        message = messages[0]
    else:
        message = (f"AI sorted {classified} of {total} materials. The rest were filled in by rules. "
                   "Please check the Type column.")
    return {
        "ai_used": ai_used,
        "model": next((st["model"] for st in statuses if st.get("model")), None),
        "classified": classified,
        "total": total,
        "message": message,
    }


def _rfms_priced_materials(existing_materials: list[dict], new_lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge freshly parsed RFMS lines onto the saved lines and price them.

    Returns (materials to save, saved lines the revised takeoff dropped).
    Reads company rates, the price list and price books; writes nothing.
    """
    # Re-upload onto a job with saved lines: each new line replaces the saved
    # line with the same description and area (new qty; saved id, code, price,
    # vendor, quote, labor and fixture fields). Saved lines of an area the
    # upload covers that it no longer has (changed or removed in the revised
    # takeoff, or surplus duplicates) are dropped; saved lines of other areas
    # stay; new lines are added. Deterministic, so uploading the same takeoff
    # again never adds lines.
    dropped_saved_lines: list[dict] = []
    if existing_materials:
        print(f"[rfms_upload] Job has {len(existing_materials)} existing materials, merging by description and area")
        merged_raw = merge_reupload_materials(existing_materials, new_lines, dropped=dropped_saved_lines)
    else:
        merged_raw = new_lines

    # Load waste factors from DB (falls back to config defaults)
    import json as _json
    _waste_data = get_company_rate("waste_factors")
    _waste_factors = _json.loads(_waste_data) if _waste_data else WASTE_FACTORS

    # Load price list for auto-pricing
    _price_list = get_price_list_entries()

    # A line priced by the stick (transition rule, price book, or a typed stick
    # price on an EA line) must keep stick pricing on the new LF, or it would
    # bill the new LF times the stick price. Picked by pricing evidence, not
    # material type: the classifier types a Schluter profile by its adjacent
    # floor (wall_tile, floor_tile, vct, ...), and the price book prices those
    # by the stick with unit EA. Each merged line knows the saved line it came from.
    prior_piece_lines: dict[int, dict] = {}
    for em in existing_materials:
        if (_as_number(em.get("unit_price")) or 0) <= 0:
            continue
        source = str(em.get("price_source") or "").strip().lower()
        is_transition = (em.get("material_type") or "").strip().lower() == "transitions"
        is_ea = str(em.get("unit") or "").strip().upper() == "EA"
        ea_sticks = is_ea and not _order_qty_is_lf(em, em.get("order_qty"))
        stick_product = is_transition or any(
            name in f"{em.get('vendor') or ''} {em.get('description') or ''}".lower()
            for name in ("schluter", "silver pin")
        )
        if source in ("price_book", "default_rule") and (is_transition or is_ea):
            prior_piece_lines[id(em)] = em
        elif source == "manual" and ea_sticks and stick_product:
            prior_piece_lines[id(em)] = em

    # Apply waste factors to the final merged list
    materials = []
    for m in merged_raw:
        material_type = m.get("material_type", "unknown")
        waste_pct = _waste_factors.get(material_type, 0)
        installed_qty = m.get("installed_qty", m.get("qty", 0))
        order_qty = installed_qty * (1 + waste_pct)

        # Auto-price from internal price list and price books
        unit_price = m.get("unit_price") or 0
        vendor = m.get("vendor") or ""
        price_source = m.get("price_source")
        saved_line = m.get("_existing")
        prior = prior_piece_lines.get(id(saved_line)) if saved_line is not None else None
        if not (
            prior
            and abs((_as_number(unit_price) or 0) - (_as_number(prior.get("unit_price")) or 0)) <= 0.005
        ):
            prior = None
        if not unit_price and _price_list:
            matched = _match_price_list(m, _price_list)
            if matched:
                unit_price = matched["unit_price"]
                vendor = matched.get("vendor", "")
                price_source = "price_list"
        # Check price_book_items (e.g. Schluter catalog)
        # Schluter products come in 8' sticks — round up to full sticks
        unit_override = None
        if not unit_price:
            pb_match = _match_price_book(m)
            if pb_match:
                import math
                stick_price = pb_match.get("stick_price", 0)
                stick_lf = pb_match.get("stick_lf", 8.208)
                sticks_needed = math.ceil(order_qty / stick_lf) if order_qty > 0 else 0
                vendor = pb_match.get("vendor", "")
                price_source = pb_match.get("price_source", "price_book")
                # Price by full sticks rounded up
                order_qty = sticks_needed
                unit_price = stick_price
                unit_override = "EA"

        # Set quote_status for unpriced materials
        quote_status = m.get("quote_status")
        if unit_price and not m.get("unit_price"):
            quote_status = None  # priced just now; a saved "needs price" no longer applies
        if not unit_price and not quote_status:
            quote_status = "needs_quote" if QUOTE_EMAILS_ENABLED else "needs_price"

        unit = unit_override or m.get("unit")
        pricing_qty = round(order_qty, 2)
        carried = {}
        if saved_line is not None:
            # Labor, fixture and quote/freight evidence of the saved line.
            carried = {
                field: m.get(field)
                for field in (
                    "fixture_count", "labor_rate_lf", "labor_catalog",
                    "quote_source_hash", "quote_file_name",
                    "freight_per_unit", "freight_source",
                )
                if m.get(field) is not None
            }
        if prior:
            # Keep stick pricing on the new LF (same rule as api_update_materials).
            price_source = prior.get("price_source")
            quote_status = prior.get("quote_status")
            vendor = vendor or prior.get("vendor") or ""
            carried.update({
                "fixture_count": prior.get("fixture_count") or 0,
                "labor_rate_lf": prior.get("labor_rate_lf") or 0,
                "labor_catalog": prior.get("labor_catalog"),
            })
            pricing_qty = _transition_pieces(order_qty, vendor, carried["fixture_count"])
            unit = prior.get("unit") or unit
            if str(unit or "").strip().upper() == "EA":
                order_qty = pricing_qty

        materials.append({
            # A line that replaces (or keeps) a saved line keeps its id, so its
            # reviewer price decisions stay attached (save_materials retains ids).
            **({"id": saved_line.get("id")} if saved_line is not None and saved_line.get("id") is not None else {}),
            **carried,
            "item_code": m.get("item_code"),
            "description": m.get("description"),
            "material_type": material_type,
            "installed_qty": round(installed_qty, 2),
            "unit": unit,
            "waste_pct": waste_pct,
            "order_qty": round(order_qty, 2),
            "vendor": vendor,
            "unit_price": unit_price,
            "extended_cost": round(unit_price * pricing_qty, 2),
            "ai_confidence": m.get("ai_confidence"),
            "quote_status": quote_status,
            "price_source": price_source,
            "area_type": m.get("area_type", "unit"),
            "tack_strip_lf": m.get("tack_strip_lf", 0),
            "seam_tape_lf": m.get("seam_tape_lf", 0),
            "pad_sy": m.get("pad_sy", 0),
            "is_mosaic": m.get("is_mosaic", False),
            "is_penny_hex": m.get("is_penny_hex", False),
            "crack_isolation_sf": m.get("crack_isolation_sf", 0),
        })

    # With quote emails off, apply the configured transition rules and the
    # Schluter price book now, so only lines with no configured price are left
    # for the estimator to type. Deterministic matches only: an AI-picked price
    # is not a configured price, so those lines stay "Needs price".
    # With quote emails on, the original quote-first order is kept (vendor
    # quote, then transition defaults, then price book at quote upload).
    if not QUOTE_EMAILS_ENABLED:
        unpriced_transitions = [
            i for i, m in enumerate(materials)
            if (m.get("material_type") or "").lower() == "transitions"
            and (_as_number(m.get("unit_price")) or 0) <= 0
        ]
        if unpriced_transitions:
            _apply_transition_defaults(materials, unpriced_transitions)
            still_unpriced = [i for i in unpriced_transitions if (_as_number(materials[i].get("unit_price")) or 0) <= 0]
            if still_unpriced:
                _price_book_match(materials, still_unpriced, allow_ai=False)

    return materials, dropped_saved_lines


def _apply_fob_freight(mat: dict, prod: dict, freight_rates: dict | None = None):
    """When vendor freight is FOB (we pay shipping), apply internal freight rates
    based on material type. CPT/carpet tile uses cpt_tile rate, LVT uses lvt rate."""
    freight_val = prod.get("freight") or ""
    if not isinstance(freight_val, str) or "fob" not in freight_val.lower():
        return  # Not FOB — freight is either included or a dollar amount

    mat_type = (mat.get("material_type") or "").lower()
    unit = (mat.get("unit") or "").upper()
    description = (mat.get("description") or "").lower()

    # Determine freight rate from the editable company table, with config as the
    # startup fallback. This same table is snapshotted for golden replay.
    freight_rates = freight_rates if isinstance(freight_rates, dict) else FREIGHT_RATES
    rate = None
    if mat_type in ("carpet_tile", "cpt", "cpt_tile") or "carpet tile" in description or "cpt" in (mat.get("item_code") or "").lower():
        rate = freight_rates.get("cpt_tile", 1.25)  # per SY
    elif mat_type in ("lvt", "unit_lvt") or "lvt" in description or "lvt" in (mat.get("item_code") or "").lower() or "vinyl plank" in description:
        # Determine LVT thickness from description
        if "5mm" in description or "4.5mm" in description or "5.0mm" in description:
            rate = freight_rates.get("lvt_5mm", 0.25)  # per SF
        else:
            rate = freight_rates.get("lvt_2mm", 0.11)  # per SF
    elif mat_type in ("broadloom",) or "broadloom" in description:
        rate = freight_rates.get("broadloom", 0.65)  # per SY

    if rate is not None:
        mat["freight_per_unit"] = rate
        mat["freight_source"] = "internal_rate"
        print(f"[freight] FOB detected for {mat.get('item_code', '?')} — applied internal rate ${rate}/{unit}")


def _save_step_results(tx, loaded: list[dict], changed: list[dict] | None, *, depends_on=None) -> dict:
    """Save what a slow step (quote matching, a price estimate, new waste
    rules) changed on the lines it loaded, as compare-and-swap patches
    (pricing_rows): each changed line is saved only if it still has the values
    the step read. A line someone changed or removed meanwhile keeps their
    change and comes back as a conflict (also noted in the history entry).
    Run inside job_write. Returns {"applied": [...], "conflicts": [...]}."""
    if changed is None:
        return {"applied": [], "conflicts": []}
    options = {} if depends_on is None else {"depends_on": depends_on}
    return apply_material_patches(tx, patches_from_rows(loaded, changed, **options))


def _priced_lines_skipped(loaded: list[dict], priced: list[dict] | None, conflicts: list[dict]) -> int:
    """How many of the lines a matching step priced (its unit price or price
    source changed) were skipped as conflicts, so they aren't reported as matched."""
    if not conflicts or not priced:
        return 0
    loaded_by_id = {str(row.get("id")): row for row in loaded or [] if isinstance(row, dict)}
    priced_ids = {
        str(row.get("id"))
        for row in priced
        if isinstance(row, dict) and str(row.get("id")) in loaded_by_id
        and any(
            not audit.values_equal(row.get(field), loaded_by_id[str(row.get("id"))].get(field))
            for field in ("unit_price", "price_source")
        )
    }
    return sum(1 for conflict in conflicts if str(conflict.get("material_id")) in priced_ids)


def _auto_match_quotes(job_id: int, products: list[dict]) -> dict:
    """Match parsed quote products to the job's materials and save the prices.

    The matching (AI included) runs first without holding the bid; only the
    changed fields are then saved, under the bid's lock, with a history entry,
    and only on lines nobody changed meanwhile.
    Returns {"matched": n, "applied": [...], "conflicts": [...]}.
    """
    matched, loaded, priced = _match_quotes_to_materials(job_id, products)
    result = {"matched": matched, "applied": [], "conflicts": []}
    if priced is not None:
        with job_write(job_id, action="quotes.auto_match", scopes=("materials",),
                       summary=_quote_match_summary(matched)) as tx:
            result.update(_save_step_results(tx, loaded, priced))
            if result["conflicts"]:
                result["matched"] = max(0, matched - _priced_lines_skipped(loaded, priced, result["conflicts"]))
                tx.set_summary(_quote_match_summary(result["matched"]) + conflict_note(result["conflicts"]))
    return result


def _quote_match_summary(matched: int) -> str:
    return f"Auto-priced {matched} material{'' if matched == 1 else 's'} from vendor quotes and price rules"


def _match_quotes_to_materials(job_id: int, products: list[dict]) -> tuple[int, list[dict], list[dict] | None]:
    """Try to match parsed quote products to existing materials.
    Phase 1: exact item_code matching (fast, no AI).
    Phase 2: AI fuzzy matching for remaining unmatched items.

    Saves nothing. Returns (matches, the materials as loaded, the materials
    with the new prices, or None when nothing changed)."""
    job = load_job(job_id)
    if not job:
        return 0, [], None
    materials = job.get("materials", [])
    if not materials:
        return 0, [], None
    loaded = copy.deepcopy(materials)

    matched = 0
    updated = False
    matched_mat_indices = set()
    matched_prod_indices = set()
    freight_rates = (get_all_company_rates().get("freight_rates") or FREIGHT_RATES)

    unit_mismatches: list[str] = []

    # Phase 1: Fast matching — item_code AND description-based product identifiers
    # Extract searchable identifiers from material descriptions.
    # e.g. "Interface - Woven Gradience - WG100 - 108051 Onyx" → ["wg100", "108051", "woven gradience"]
    import re as _re

    def _extract_vendor_from_desc(description: str) -> str:
        """Extract vendor name from RFMS description.
        RFMS format: '(Standard) - T-200 - Arizona Tile - Flash - Ivory...'
        The vendor name is typically the part after the item code, before the product line.
        Only returns a vendor if the description has the standard ' - ' delimited format
        with at least 3 parts (code - vendor - product)."""
        parts = [p.strip() for p in description.split(" - ") if p.strip()]
        if len(parts) < 3:
            return ""  # Not enough parts for code - vendor - product format
        # Skip option prefixes and item codes to find the vendor name
        for part in parts:
            clean = part.strip()
            # Skip option prefixes like (Standard), (Premium), (Alternate)
            if _re.match(r'^\(', clean):
                continue
            # Skip item codes like CPT-200, T-202, F103, LVT-200, B-101, TS-100
            if _re.match(r'^[A-Z]{1,4}-?\d{1,4}', clean):
                continue
            # Skip numeric-only parts
            if _re.match(r'^\d+', clean):
                continue
            # This should be the vendor name
            return clean.lower()
        return ""

    def _extract_identifiers(description: str) -> list[str]:
        """Extract product line identifiers from a material description.
        Splits on ' - ' delimiters and returns meaningful tokens."""
        parts = [p.strip().lower() for p in description.split(" - ") if p.strip()]
        identifiers = []
        for part in parts:
            # Skip the vendor name (first part) and very short/generic tokens
            if len(part) < 2:
                continue
            identifiers.append(part)
            # Also extract individual alphanumeric codes (WG100, 108051, etc.)
            codes = _re.findall(r'[a-z]*\d+[a-z]*\d*', part)
            identifiers.extend(codes)
        return identifiers

    # Generic words that should NOT count as meaningful matches on their own
    GENERIC_WORDS = {
        "tile", "carpet", "floor", "flooring", "interface", "mohawk", "shaw",
        "matte", "glossy", "polished", "honed", "satin", "brushed",  # finishes
        "black", "white", "grey", "gray", "brown", "beige", "cream", "ivory",  # colors
        "wall", "base", "trim", "edge", "cove", "corner",  # generic parts
        "custom", "standard", "premium", "commercial", "residential",
        "rubber", "vinyl", "porcelain", "ceramic", "glass", "stone", "marble",
        "daltile", "johnsonite", "schluter", "mannington",  # vendor names
        "rectangular", "square", "round", "linear", "straight",
        "size", "type", "style", "color", "finish", "series",
    }

    # Also collect ALL quote products across the DB for this job (not just current upload)
    # so we can score against the full universe of quotes
    conn = _get_conn()
    try:
        all_quotes = conn.execute(
            """SELECT id, product_name, vendor, unit_price, unit, file_name, source_hash,
                      freight, lead_time, notes
               FROM job_quotes
               WHERE job_id=?
               ORDER BY CASE WHEN source_hash IS NOT NULL AND source_hash != '' THEN 0 ELSE 1 END,
                        id DESC""",
            (job_id,),
        ).fetchall()
    finally:
        conn.close()
    all_quote_products = [dict(q) for q in all_quotes] if all_quotes else products
    verified_quote_hashes = {
        str(item.get("file_hash") or "").strip()
        for item in list_imported_files(job_id)
        if _imported_artifact_is_verified(item, "vendor_quote")
    }
    current_quote_hashes = {
        str(product.get("source_hash") or product.get("_source_hash") or "").strip()
        for product in products
        if isinstance(product, dict)
    }
    allowed_provenance_hashes = (verified_quote_hashes | current_quote_hashes) - {""}

    def _configured_transition_default(mat: dict) -> bool:
        """With quote emails off, transition rules / price book are applied at RFMS
        upload. A matching vendor quote still replaces them, as it did when those
        defaults only ran after the quote phases below."""
        return (
            not QUOTE_EMAILS_ENABLED
            and (mat.get("material_type") or "").strip().lower() == "transitions"
            and str(mat.get("quote_status") or "").strip().lower() == "price_book"
            and str(mat.get("price_source") or "").strip().lower() in {"default_rule", "price_book"}
        )

    for mat_idx, mat in enumerate(materials):
        existing_price = _as_number(mat.get("unit_price")) or 0
        provenance_only = (
            existing_price > 0
            and str(mat.get("price_source") or "").strip().lower() == "vendor_quote"
        )
        if existing_price > 0 and not provenance_only and not _configured_transition_default(mat):
            continue
        item_code = (mat.get("item_code") or "").strip().lower()
        description = (mat.get("description") or "").strip().lower()
        if not item_code and not description:
            continue

        # Build list of identifiers to match against
        mat_identifiers = _extract_identifiers(description)

        # Extract vendor name from RFMS description for hard filtering
        # e.g. "(Standard) - T-200 - Arizona Tile - Flash" → "arizona tile"
        rfms_vendor = _extract_vendor_from_desc(mat.get("description") or "")

        # Score ALL products and pick the best match instead of first-match-wins
        best_score = 0
        best_prod = None
        best_prod_idx = None

        # Use all_quote_products for scoring (includes previous uploads)
        scoring_products = all_quote_products if all_quote_products else products

        for prod_idx, prod in enumerate(scoring_products):
            if prod.get("error"):
                continue
            unit_price = prod.get("unit_price", 0)
            if not unit_price:
                continue
            source_hash = prod.get("source_hash") or prod.get("_source_hash")
            if provenance_only:
                product_price = _as_number(unit_price)
                if (
                    not source_hash
                    or str(source_hash) not in allowed_provenance_hashes
                    or product_price is None
                    or abs(product_price - existing_price) > 0.005
                ):
                    continue
            prod_name = (prod.get("product_name") or "").strip().lower()
            prod_desc = (prod.get("description") or "").strip().lower()
            prod_vendor = (prod.get("vendor") or "").strip().lower()
            prod_text = f"{prod_name} {prod_desc}"

            # HARD FILTER: If RFMS description names a vendor, only match quotes
            # from that vendor. "T-200 - Arizona Tile - Flash" must match Arizona Tile
            # quotes, never Metropolitan Floors or anyone else.
            # Vendor aliases: parent companies own subsidiaries (Daltile=Marazzi, etc.)
            _VENDOR_ALIASES = {
                "marazzi": ["daltile"],
                "flor": ["interface"], "interface": ["flor"],
                "mohawk": ["daltile", "marazzi"], "daltile": ["marazzi", "mohawk"],
            }
            if rfms_vendor and len(rfms_vendor) >= 3:
                vendor_match = False
                # Direct match
                if rfms_vendor in prod_vendor or prod_vendor in rfms_vendor:
                    vendor_match = True
                # Check aliases (e.g. Marazzi material can match Daltile quote)
                if not vendor_match:
                    aliases = _VENDOR_ALIASES.get(rfms_vendor, [])
                    for alias in aliases:
                        if alias in prod_vendor or prod_vendor in alias:
                            vendor_match = True
                            break
                # Also check product name/file for vendor name
                prod_file = (prod.get("file_name") or "").lower()
                if rfms_vendor in prod_file:
                    vendor_match = True
                if not vendor_match:
                    continue  # SKIP — wrong vendor, don't even score

            score = 0

            # Check 1: item_code in product name/desc (strong signal: +10)
            if item_code and len(item_code) >= 3:
                if item_code in prod_name or item_code in prod_desc:
                    score += 10

            # Check 2: product identifiers from description match quote product
            if mat_identifiers:
                for ident in mat_identifiers:
                    if len(ident) >= 3 and ident in prod_text:
                        # Weight by specificity: codes with digits worth more
                        if _re.search(r'\d', ident):
                            score += 5  # alphanumeric codes like "d617", "wg100"
                        elif ident not in GENERIC_WORDS and len(ident) >= 4:
                            score += 2  # meaningful product names
                        elif ident not in GENERIC_WORDS:
                            score += 1

            # Check 3: quote product name found in material description
            if prod_name and len(prod_name) >= 4:
                prod_parts = [p.strip() for p in prod_name.split(" - ") if len(p.strip()) >= 3]
                for pp in prod_parts:
                    if pp in description:
                        score += 3

                # Individual significant words from product name
                prod_words = [w for w in _re.findall(r'[a-z]+\d*\S*', prod_name) if len(w) >= 4]
                desc_words = set(_re.findall(r'[a-z]+\d*\S*', description))
                for pw in prod_words:
                    if pw in desc_words and pw not in GENERIC_WORDS:
                        score += 2

            # Check 4: Word-level overlap scoring
            desc_tokens = set(_re.findall(r'[a-z]+', description))
            prod_tokens = set(_re.findall(r'[a-z]+', prod_text))
            meaningful_overlap = (desc_tokens & prod_tokens) - GENERIC_WORDS - {"and", "the", "for", "with"}
            meaningful_overlap = {w for w in meaningful_overlap if len(w) >= 4}
            score += len(meaningful_overlap)

            # Check 5: Dimension/size match (e.g. "1x1", "12x24", "4x12")
            desc_dims = set(_re.findall(r'(\d+)\s*["\']?\s*x\s*["\']?\s*(\d+)', description))
            prod_dims = set(_re.findall(r'(\d+)\s*["\']?\s*x\s*["\']?\s*(\d+)', prod_text))
            if desc_dims and prod_dims and desc_dims & prod_dims:
                score += 3

            best_source_hash = (best_prod or {}).get("source_hash") or (best_prod or {}).get("_source_hash")
            if score > best_score or (score == best_score and source_hash and not best_source_hash):
                best_score = score
                best_prod = prod
                best_prod_idx = prod_idx

        # Require a minimum score of 3 to accept a match (prevents single generic word matches)
        if best_score >= 3 and best_prod and not _quote_unit_matches(best_prod, mat):
            unit_mismatches.append(_unit_mismatch_note(best_prod, mat))
            continue
        if best_score >= 3 and best_prod:
            if provenance_only:
                mat["quote_source_hash"] = best_prod.get("source_hash") or best_prod.get("_source_hash")
                mat["quote_file_name"] = best_prod.get("file_name")
                mat["quote_status"] = mat.get("quote_status") or "quoted"
                matched += 1
                updated = True
                matched_mat_indices.add(mat_idx)
                continue
            mat["unit_price"] = best_prod["unit_price"]
            mat["vendor"] = best_prod.get("vendor", "")
            mat["quote_status"] = "quoted"
            mat["price_source"] = "vendor_quote"
            mat["quote_source_hash"] = best_prod.get("source_hash") or best_prod.get("_source_hash")
            mat["quote_file_name"] = best_prod.get("file_name")
            # If freight is FOB, apply internal freight rates by material type
            _apply_fob_freight(mat, best_prod, freight_rates)
            order_qty = mat.get("order_qty", 0)
            mat["extended_cost"] = round(order_qty * mat["unit_price"], 2)
            matched += 1
            updated = True
            matched_mat_indices.add(mat_idx)

    # Phase 2: AI fuzzy matching for remaining unmatched
    unmatched_mats = [(i, m) for i, m in enumerate(materials) if i not in matched_mat_indices and (not m.get("unit_price") or m["unit_price"] == 0)]
    unmatched_prods = [(i, p) for i, p in enumerate(products) if i not in matched_prod_indices and not p.get("error") and p.get("unit_price")]

    if unmatched_mats and unmatched_prods:
        ai_matched, ai_match_error = _ai_match_quotes(unmatched_mats, unmatched_prods)
        if ai_match_error:
            log_activity(job_id, "quote_ai_match_failed",
                         ai_match_error + " Type prices on the lines still marked Needs price.")
        for mat_idx, prod_idx in ai_matched:
            mat = materials[mat_idx]
            prod = products[prod_idx]
            if not _quote_unit_matches(prod, mat):
                unit_mismatches.append(_unit_mismatch_note(prod, mat))
                continue
            mat["unit_price"] = prod["unit_price"]
            mat["vendor"] = prod.get("vendor", "")
            mat["quote_status"] = "quoted"
            mat["price_source"] = "vendor_quote"
            mat["quote_source_hash"] = prod.get("source_hash") or prod.get("_source_hash")
            mat["quote_file_name"] = prod.get("file_name")
            _apply_fob_freight(mat, prod, freight_rates)
            order_qty = mat.get("order_qty", 0)
            mat["extended_cost"] = round(order_qty * mat["unit_price"], 2)
            matched += 1
            updated = True

    # Phase 3: Apply transition default rules (Carpet→LVT = Silver Pin, etc.)
    if unit_mismatches:
        log_activity(
            job_id, "quote_unit_mismatch",
            f"{len(unit_mismatches)} quote price(s) weren't used because the unit didn't match the line. "
            "Type those prices by hand: " + "; ".join(unit_mismatches[:5]),
            {"lines": unit_mismatches},
        )
    still_unpriced = [i for i, m in enumerate(materials) if i not in matched_mat_indices and (not m.get("unit_price") or m["unit_price"] == 0)]
    if still_unpriced:
        td_matched = _apply_transition_defaults(materials, still_unpriced)
        if td_matched > 0:
            matched += td_matched
            updated = True

    # Phase 4: Price book matching for remaining unpriced materials
    # Check if any unpriced materials match a vendor price book (e.g. Schluter transitions)
    still_unpriced2 = [i for i, m in enumerate(materials) if i not in matched_mat_indices and (not m.get("unit_price") or m["unit_price"] == 0)]
    if not QUOTE_EMAILS_ENABLED:
        # Same as RFMS upload with quote emails off: deterministic price-book
        # matches on transitions only. An AI-picked price is not a configured
        # price, so those lines stay "Needs price" for the estimator to type.
        still_unpriced2 = [
            i for i in still_unpriced2
            if (materials[i].get("material_type") or "").strip().lower() == "transitions"
        ]
    if still_unpriced2:
        pb_matched = _price_book_match(materials, still_unpriced2, allow_ai=QUOTE_EMAILS_ENABLED)
        if pb_matched > 0:
            matched += pb_matched
            updated = True

    # Phase 5: Apply labor rates to all Schluter transitions (even those matched by vendor quotes)
    for mat in materials:
        if (mat.get("vendor") or "").lower() == "schluter" and not mat.get("labor_rate_lf"):
            desc = (mat.get("description") or "").lower()
            is_premium = any(line in desc for line in SCHLUTER_PREMIUM_LABOR_LINES)
            mat["labor_rate_lf"] = SCHLUTER_LABOR_RATE_PREMIUM if is_premium else SCHLUTER_LABOR_RATE_DEFAULT
            mat["labor_catalog"] = "Schluter Schiene"
            updated = True

    # Also try to link to open quote requests
    _link_upload_to_requests(job_id, products)

    return matched, loaded, (materials if updated else None)


def _quote_unit_matches(prod: dict, mat: dict) -> bool:
    """A quote price is copied onto a line only when both use the same unit
    (or either unit is unknown). A per-SF price on an SY line would be 9x off."""
    prod_unit = normalize_quote_unit(prod.get("unit"))
    mat_unit = normalize_quote_unit(mat.get("unit"))
    return not prod_unit or not mat_unit or prod_unit == mat_unit


def _unit_mismatch_note(prod: dict, mat: dict) -> str:
    return (f"{mat.get('item_code') or mat.get('description') or 'A line'}: the quote price is per "
            f"{normalize_quote_unit(prod.get('unit'))} but the line is in {normalize_quote_unit(mat.get('unit'))}")


def _ai_match_quotes(unmatched_mats: list, unmatched_prods: list) -> tuple[list, str | None]:
    """Use AI to fuzzy-match vendor products to job materials.

    Returns (pairs, error): error is a plain-English note when the AI could
    not do the matching, so the caller can tell the estimator.
    """
    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")

    provider = get_provider_info(api_key)
    if not provider["available"]:
        return [], "AI is not set up, so quote lines were matched by exact code only."

    try:
        import json

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

Return ONLY a JSON object with a "matches" key: {{"matches": [{{"material": "M0", "product": "P0", "confidence": 0.95}}]}}
Return {{"matches": []}} if no confident matches."""

        raw = chat_complete(
            system="You are a commercial flooring product matching assistant. Return JSON only.",
            user=prompt,
            api_key=api_key,
            model=model,
            json_mode=True,
        )
        result = json.loads(raw)

        # Parse result
        matches_raw = result if isinstance(result, list) else result.get("matches", result.get("results", result.get("data", [])))
        if not isinstance(matches_raw, list):
            matches_raw = []

        pairs = []
        for m in matches_raw:
            try:
                if float(m.get("confidence", 0)) < 0.8:
                    continue
                mat_local_idx = int(str(m.get("material", "")).replace("M", ""))
                prod_local_idx = int(str(m.get("product", "")).replace("P", ""))
                if 0 <= mat_local_idx < len(unmatched_mats) and 0 <= prod_local_idx < len(unmatched_prods):
                    pairs.append((unmatched_mats[mat_local_idx][0], unmatched_prods[prod_local_idx][0]))
            except (AttributeError, TypeError, ValueError, IndexError):
                continue

        return pairs, None
    except AIError as e:
        print(f"AI quote matching failed (non-fatal): {e.reason}: {e}")
        return [], f"AI quote matching didn't run: {e.user_message}"
    except Exception as e:
        print(f"AI quote matching failed (non-fatal): {e}")
        return [], "AI quote matching didn't run this time."


# ─── Transition Default Rules ───────────────────────────────────────────────
# These rules define the default product, price, and labor rate for each
# transition type. Applied BEFORE AI/price-book matching so they take priority.
TRANSITION_DEFAULTS = [
    {
        "match": "carpet to lvt",  # substring match on description
        "product": "Silver Pin Metal",
        "vendor": "Silver Pin Metal",
        "price_per_piece": 7.94,
        "stick_length_lf": 12.0,
        "labor_rate_lf": 0,  # no install labor for pin metal
        "labor_catalog": "",
        "price_source": "default_rule",
    },
    {
        "match": "vertical exposed edge",
        "product": "Schluter Jolly J 100 AE",
        "vendor": "Schluter",
        "price_per_piece": 9.78,  # Jolly J 100 AE net
        "stick_length_lf": 8.0 + 2.0 / 12.0,  # 8'-2"
        "labor_rate_lf": 0.50,
        "labor_catalog": "Schluter Schiene",
        "price_source": "price_book",
    },
    {
        "match": "tile to lvt",
        "product": "Schluter Reno-U AEU 100",
        "vendor": "Schluter",
        "price_per_piece": 12.15,  # Reno-U AEU 100 net
        "stick_length_lf": 8.0 + 2.0 / 12.0,
        "labor_rate_lf": 0.50,
        "labor_catalog": "Schluter Schiene",
        "price_source": "price_book",
    },
    {
        "match": "tile to carpet",  # tile to CPT
        "match_alt": "tile to cpt",
        "product": "Schluter Reno-TK AETK 100",
        "vendor": "Schluter",
        "price_per_piece": 12.80,  # Reno-TK AETK 100 net
        "stick_length_lf": 8.0 + 2.0 / 12.0,
        "labor_rate_lf": 0.50,
        "labor_catalog": "Schluter Schiene",
        "price_source": "price_book",
    },
]

# Catch-all default for any transition not matched by specific rules above.
# Generic transitions (Carpet to Tile, Carpet to VCT, @Courtyard, etc.)
# default to Schluter Reno-TK AE 100.
TRANSITION_CATCHALL = {
    "product": "Schluter Reno-TK AETK 100",
    "vendor": "Schluter",
    "price_per_piece": 12.80,  # Reno-TK AETK 100 net
    "stick_length_lf": 8.0 + 2.0 / 12.0,
    "labor_rate_lf": 0.50,
    "labor_catalog": "Schluter Schiene",
    "price_source": "price_book",
}

# Schluter labor rate exceptions: Dilex, Rondec, Quadec = $1.07/LF (all others = $0.50/LF)
SCHLUTER_LABOR_RATE_DEFAULT = 0.50
SCHLUTER_LABOR_RATE_PREMIUM = 1.07
SCHLUTER_PREMIUM_LABOR_LINES = {"dilex", "rondec", "quadec"}


def _apply_transition_defaults(materials: list[dict], unpriced_indices: list[int]) -> int:
    """Apply default transition product/pricing rules BEFORE AI matching.
    Returns number of materials matched."""
    import math
    matched = 0

    for mat_idx in unpriced_indices:
        mat = materials[mat_idx]
        mat_type = (mat.get("material_type") or "").lower()
        if mat_type != "transitions":
            continue

        description = (mat.get("description") or "").lower()
        order_qty_lf = _transition_order_lf(mat)
        fixture_count = mat.get("fixture_count", 0) or 0

        # Check each rule
        for rule in TRANSITION_DEFAULTS:
            match_str = rule["match"]
            match_alt = rule.get("match_alt", "")
            if match_str in description or (match_alt and match_alt in description):
                price_per_piece = rule["price_per_piece"]
                stick_lf = rule["stick_length_lf"]

                # Calculate pieces
                if rule["vendor"] == "Schluter":
                    pieces = _calc_schluter_pieces(order_qty_lf, fixture_count, stick_lf)
                else:
                    pieces = math.ceil(order_qty_lf / stick_lf) if order_qty_lf > 0 else 0

                mat["unit_price"] = price_per_piece
                mat["vendor"] = rule["vendor"]
                mat["price_source"] = rule["price_source"]
                mat["quote_status"] = "price_book"
                mat["extended_cost"] = round(pieces * price_per_piece, 2)
                _store_transition_sticks(mat, pieces)

                # Set labor rate
                labor_rate = rule["labor_rate_lf"]
                mat["labor_rate_lf"] = labor_rate
                mat["labor_catalog"] = rule.get("labor_catalog", "")

                matched += 1
                break  # first matching rule wins
        else:
            # No specific rule matched — skip named Schluter products (they'll match via price book)
            # For generic transitions, apply catch-all default (Reno-TK AE 100)
            if "schluter" not in description:
                rule = TRANSITION_CATCHALL
                stick_lf = rule["stick_length_lf"]
                pieces = _calc_schluter_pieces(order_qty_lf, fixture_count, stick_lf)
                mat["unit_price"] = rule["price_per_piece"]
                mat["vendor"] = rule["vendor"]
                mat["price_source"] = rule["price_source"]
                mat["quote_status"] = "price_book"
                mat["extended_cost"] = round(pieces * rule["price_per_piece"], 2)
                _store_transition_sticks(mat, pieces)
                mat["labor_rate_lf"] = rule["labor_rate_lf"]
                mat["labor_catalog"] = rule["labor_catalog"]
                matched += 1

        # If no rule matched but it's a named Schluter product, apply labor rates
        if (mat.get("vendor") or "").lower() == "schluter" and not mat.get("labor_rate_lf"):
            is_premium = any(line in description for line in SCHLUTER_PREMIUM_LABOR_LINES)
            mat["labor_rate_lf"] = SCHLUTER_LABOR_RATE_PREMIUM if is_premium else SCHLUTER_LABOR_RATE_DEFAULT
            mat["labor_catalog"] = "Schluter Schiene"

    return matched


def _calc_schluter_pieces(order_qty_lf: float, fixture_count: int, piece_lf: float) -> int:
    """Calculate number of Schluter pieces needed.
    If fixture_count is set, each fixture needs full pieces per side (no splicing across fixtures).
    E.g. 200 showers at 7'-6" each side: each side = 1 piece, 2 sides = 2 pieces/fixture = 400 total.
    Without fixture_count, just divides total LF by piece length."""
    import math
    if order_qty_lf <= 0:
        return 0
    if fixture_count and fixture_count > 0:
        # Fixture-based: each fixture needs full pieces, can't reuse leftover across fixtures
        # Assume 2 sides per fixture (tub/shower has left + right)
        sides = 2
        lf_per_side = order_qty_lf / (fixture_count * sides)
        pieces_per_side = math.ceil(lf_per_side / piece_lf)
        return fixture_count * sides * pieces_per_side
    else:
        return math.ceil(order_qty_lf / piece_lf)


def _transition_pieces(order_qty_lf: float, vendor: str | None, fixture_count) -> int:
    """Whole sticks for a piece-priced transition line (Silver Pin=12', Schluter=8'2").
    Same rule as the materials editor's transitionPiecesFromLf; shared with the
    bid assembler, proposal waste re-apply and audits via material_pricing."""
    return _shared_transition_pieces(order_qty_lf, vendor, fixture_count)


def _order_qty_is_lf(mat: dict, order_qty) -> bool:
    """True when order_qty equals the line's LF figure, installed_qty x (1 + waste_pct).
    The old editor reset order_qty to that LF value on every edit, even on EA
    transition lines, so on an EA line such a value is LF, not a stick count."""
    return _shared_order_qty_is_lf(mat, order_qty)


def _transition_order_lf(mat: dict) -> float:
    """LF to count sticks from when a configured stick price is applied.
    An EA transition row that already stores sticks (e.g. one whose price was
    cleared) keeps its LF only as installed_qty x (1 + waste_pct); any other
    row keeps LF in order_qty."""
    if (
        (mat.get("material_type") or "").strip().lower() == "transitions"
        and _shared_order_qty_holds_sticks(mat)
    ):
        installed_qty = _as_number(mat.get("installed_qty")) or 0
        waste_pct = _as_number(mat.get("waste_pct")) or 0
        return round(installed_qty * (1 + waste_pct), 2)
    return _as_number(mat.get("order_qty")) or 0


def _store_transition_sticks(mat: dict, pieces) -> None:
    """An EA transition row stores the sticks it is billed for as its order_qty,
    as PUT /materials, the bid assembler and the materials editor expect."""
    if (
        (mat.get("material_type") or "").strip().lower() == "transitions"
        and str(mat.get("unit") or "").strip().upper() == "EA"
    ):
        mat["order_qty"] = pieces


def _price_book_match(materials: list[dict], unpriced_indices: list[int], allow_ai: bool = True) -> int:
    """Match unpriced materials against vendor price books (e.g. Schluter).
    Only matches when description explicitly contains a Schluter product line name
    as a whole word AND has additional identifying info (item number, size, etc.).
    allow_ai=False skips the AI fallback, so low-confidence lines stay unpriced."""
    import re as _re

    # Known Schluter product lines — only match as whole words to avoid false positives
    # e.g. "deco" must not match "decorative", "trep" must not match "trepidation"
    SCHLUTER_LINES = [
        "schiene", "reno-t", "reno-tk", "reno-u", "reno-v", "reno-ramp",
        "jolly", "ditra", "kerdi", "kerdi-band", "kerdi-board",
        "dilex-ahka", "dilex-ahk", "dilex", "quadec", "rondec", "trep-e", "trep-b", "trep-s",
        "trep-fl", "trep-ek", "trep-se", "trep-tap",
    ]
    # Compile whole-word patterns (avoid substring matches like "deco" in "decorative")
    SCHLUTER_PATTERNS = {
        line: _re.compile(r'\b' + _re.escape(line) + r'\b', _re.IGNORECASE)
        for line in SCHLUTER_LINES
    }

    matched = 0
    ai_candidates = []
    for mat_idx in unpriced_indices:
        mat = materials[mat_idx]
        description = (mat.get("description") or "").lower()
        item_code = (mat.get("item_code") or "").lower()
        mat_type = (mat.get("material_type") or "").lower()

        # STRICT GATE: Only match if material is a known Schluter-applicable type
        # OR the description explicitly says "schluter"
        is_schluter_type = mat_type in ("transitions", "waterproofing", "tread_riser")
        has_schluter_name = "schluter" in description

        if not is_schluter_type and not has_schluter_name:
            # For unknown types (no AI classification), require "schluter" in description
            # Do NOT fall through to product line name matching — too many false positives
            continue

        # Try to find the product line and item number in the description
        # Descriptions look like: "Schluter SCHIENE A 100 AE" or "RENO-TK ETK 80"
        best_match = None
        best_score = 0

        for line, pattern in SCHLUTER_PATTERNS.items():
            if pattern.search(description):
                # Found a product line as a whole word — search the price book
                results = match_price_book(line.upper())
                if not results:
                    results = match_price_book(line.upper().replace("-", ""))
                if not results:
                    continue

                # Try to narrow down by item number or size from description
                for pb_item in results:
                    score = 1  # base score for product line match
                    pb_item_lower = pb_item["item_no"].lower()

                    # Check if the item number appears in the description
                    if pb_item_lower and pb_item_lower in description:
                        score += 5  # strong match

                    # Check size match
                    if pb_item["size_mm"] and pb_item["size_mm"] in description:
                        score += 2
                    if pb_item["size_inches"] and pb_item["size_inches"] in description:
                        score += 2

                    # Check material/finish match
                    finish_lower = pb_item["material_finish"].lower()
                    if finish_lower and any(w in description for w in finish_lower.split() if len(w) > 3):
                        score += 1

                    if score > best_score:
                        best_score = score
                        best_match = pb_item

        if best_match and best_score >= 3:
            # Apply price book net price (already discounted)
            # Schluter transitions are sold per PIECE (each piece = 8'-2" = 8.1667 LF)
            import math
            SCHLUTER_PIECE_LF = 8.0 + 2.0 / 12.0  # 8'-2" = 8.1667 LF
            price_per_piece = best_match["net_price"]
            order_qty_lf = _transition_order_lf(mat)
            fixture_count = mat.get("fixture_count", 0) or 0
            pieces_needed = _calc_schluter_pieces(order_qty_lf, fixture_count, SCHLUTER_PIECE_LF)
            mat["unit_price"] = price_per_piece
            mat["vendor"] = "Schluter"
            mat["quote_status"] = "price_book"
            mat["price_source"] = "price_book"
            mat["extended_cost"] = round(pieces_needed * price_per_piece, 2)
            _store_transition_sticks(mat, pieces_needed)
            # Apply labor rate
            is_premium = any(line in description for line in SCHLUTER_PREMIUM_LABOR_LINES)
            mat["labor_rate_lf"] = SCHLUTER_LABOR_RATE_PREMIUM if is_premium else SCHLUTER_LABOR_RATE_DEFAULT
            mat["labor_catalog"] = "Schluter Schiene"
            matched += 1
        elif (is_schluter_type or has_schluter_name) and (not best_match or best_score < 3):
            # No rule-based match or low-confidence match — queue for AI matching
            ai_candidates.append(mat_idx)

    # Phase 2: AI matching for remaining Schluter materials
    if ai_candidates and allow_ai:
        ai_matched = _ai_price_book_match(materials, ai_candidates)
        matched += ai_matched

    return matched


def _ai_price_book_match(materials: list[dict], candidate_indices: list[int]) -> int:
    """Use AI to match Schluter materials to the price book when rule-based matching fails."""
    import json as _json

    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    provider = get_provider_info(api_key)
    if not provider["available"]:
        return 0

    # Group candidates by detected product line to minimize AI calls
    # Gather all price book entries for relevant product lines
    all_pb_items = search_price_book("", vendor="Schluter")
    if not all_pb_items:
        return 0

    # Build material list for AI
    mat_lines = []
    for i, idx in enumerate(candidate_indices):
        mat = materials[idx]
        desc = mat.get("description", "")
        unit = mat.get("unit", "")
        mat_lines.append(f"M{i}: {desc} (unit: {unit})")

    # Build price book summary grouped by product line
    pb_by_line = {}
    for pb in all_pb_items:
        line = pb["product_line"]
        if line not in pb_by_line:
            pb_by_line[line] = []
        pb_by_line[line].append(pb)

    pb_lines = []
    for line, items in sorted(pb_by_line.items()):
        # Show a sample of items per line to keep prompt reasonable
        samples = items[:8]
        for s in samples:
            pb_lines.append(
                f"  {line} | {s['item_no']} | {s['material_finish']} | "
                f"size: {s.get('size_inches', '')} | ${s['net_price']}/{s.get('unit', 'length')}"
            )
        if len(items) > 8:
            pb_lines.append(f"  ... and {len(items) - 8} more {line} items")

    prompt = f"""Match these Schluter transition materials to the correct product from our Schluter price book.

Materials to match:
{chr(10).join(mat_lines)}

Schluter Price Book:
{chr(10).join(pb_lines)}

Rules:
- Match based on product line (Reno-TK, Reno-Ramp, Dilex, Schiene, etc.), material/finish, and size
- DEFAULT: Unless the description explicitly specifies a different finish or size, always default to AE (satin anodized aluminum) finish and 100 (10mm / 3/8") size. This is standard estimating practice.
- Only use a different finish (ATGB, ATG, AK, etc.) if the description explicitly calls it out in the finish schedule
- If size is not specified, use 100 (10mm)
- If the exact product line is not in the price book, check if a similar or parent product line exists (e.g. DILEX-AHKA may relate to DECO or JOLLY). If nothing similar exists, return no match for that material
- Only match if you are confident the product line and material type are correct

Return JSON: {{"matches": [{{"material": "M0", "item_no": "AETK 80", "product_line": "RENO-TK", "net_price": 9.80, "confidence": 0.9, "reason": "Reno-TK anodized aluminum 5/16 inch"}}]}}
Return {{"matches": []}} for any materials you cannot confidently match."""

    try:
        # Sanitize prompt to avoid encoding issues on Windows
        prompt = prompt.encode("ascii", errors="replace").decode("ascii")

        raw = chat_complete(
            system="You are a Schluter product matching expert for commercial flooring. Return JSON only.",
            user=prompt,
            api_key=api_key,
            model=model,
            json_mode=True,
        )
        result = _json.loads(raw)
        matches_raw = result if isinstance(result, list) else result.get("matches", [])
        if not isinstance(matches_raw, list):
            matches_raw = []

        matched = 0
        for m in matches_raw:
            conf = m.get("confidence", 0)
            if conf < 0.7:
                continue
            mat_ref = m.get("material", "")
            try:
                local_idx = int(mat_ref.replace("M", ""))
                mat_idx = candidate_indices[local_idx]
            except (ValueError, IndexError):
                continue

            net_price = m.get("net_price", 0)
            if not net_price or net_price <= 0:
                continue

            mat = materials[mat_idx]
            # Schluter transitions are sold per PIECE (each piece = 8'-2" = 8.1667 LF)
            import math
            SCHLUTER_PIECE_LF = 8.0 + 2.0 / 12.0  # 8'-2" = 8.1667 LF
            price_per_piece = net_price
            order_qty_lf = _transition_order_lf(mat)
            fixture_count = mat.get("fixture_count", 0) or 0
            pieces_needed = _calc_schluter_pieces(order_qty_lf, fixture_count, SCHLUTER_PIECE_LF)
            mat["unit_price"] = price_per_piece
            mat["vendor"] = "Schluter"
            mat["quote_status"] = "price_book"
            mat["price_source"] = "price_book"
            mat["extended_cost"] = round(pieces_needed * price_per_piece, 2)
            _store_transition_sticks(mat, pieces_needed)
            # Apply labor rate
            desc_lower = (mat.get("description") or "").lower()
            is_premium = any(line in desc_lower for line in SCHLUTER_PREMIUM_LABOR_LINES)
            mat["labor_rate_lf"] = SCHLUTER_LABOR_RATE_PREMIUM if is_premium else SCHLUTER_LABOR_RATE_DEFAULT
            mat["labor_catalog"] = "Schluter Schiene"
            matched += 1
            print(f"[price_book] AI matched: {mat.get('description', '')[:60]} -> {m.get('product_line')} {m.get('item_no')} ${net_price}/pc x {pieces_needed}pc")

        return matched
    except Exception as e:
        print(f"[price_book] AI matching error: {e}")
        return 0


def _link_upload_to_requests(job_id: int, products: list[dict]):
    """Detect which open quote requests match uploaded vendor quotes.
    Returns list of matched requests for frontend confirmation."""
    if not QUOTE_EMAILS_ENABLED:
        return []
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


def _quote_upload_outcomes(
    before_materials: list[dict],
    before_verified_vendor_hashes: set[str],
    after_materials: list[dict],
    after_verified_vendor_hashes: set[str],
) -> dict:
    """Separate exact receipt repairs from newly priced quote matches."""
    before_by_id = {
        str(material.get("id")): material
        for material in before_materials
        if isinstance(material, dict) and material.get("id") is not None
    }
    provenance_repaired_items = []
    quote_price_matched_items = []
    for material in after_materials:
        if not isinstance(material, dict) or material.get("id") is None:
            continue
        before = before_by_id.get(str(material.get("id")))
        if not before:
            continue
        before_price = _as_number(before.get("unit_price")) or 0
        after_price = _as_number(material.get("unit_price")) or 0
        before_hash = str(before.get("quote_source_hash") or "").strip()
        after_hash = str(material.get("quote_source_hash") or "").strip()
        before_vendor_quote = str(before.get("price_source") or "").strip().lower() == "vendor_quote"
        after_vendor_quote = str(material.get("price_source") or "").strip().lower() == "vendor_quote"
        before_receipt_verified = bool(before_hash and before_hash in before_verified_vendor_hashes)
        after_receipt_verified = bool(after_hash and after_hash in after_verified_vendor_hashes)
        label = material.get("item_code") or material.get("description") or f"Material {material.get('id')}"
        if (
            before_vendor_quote
            and before_price > 0
            and not before_receipt_verified
            and after_vendor_quote
            and after_receipt_verified
            and abs(after_price - before_price) <= 0.005
        ):
            provenance_repaired_items.append(str(label))
        if (
            before_price <= 0
            and after_price > 0
            and after_vendor_quote
            and after_receipt_verified
        ):
            quote_price_matched_items.append(str(label))
    return {
        "quote_price_matched": len(quote_price_matched_items),
        "quote_price_matched_items": quote_price_matched_items,
        "provenance_repaired": len(provenance_repaired_items),
        "provenance_repaired_items": provenance_repaired_items,
    }


def _save_quote_products(db_id: int, products: list[dict], file_names: list[str], *, action: str) -> list[int]:
    """Save parsed quote lines for a bid, with a history entry listing the new lines."""
    with job_write(db_id, action=action, scopes=()) as tx:
        ids = save_quotes(db_id, products, conn=tx.conn)
        if ids:
            placeholders = ",".join("?" for _ in ids)
            rows = [
                dict(row)
                for row in tx.conn.execute(
                    f"""SELECT id, product_name, vendor, unit_price, unit, description, file_name,
                               freight, lead_time, notes, source_hash
                        FROM job_quotes WHERE id IN ({placeholders}) ORDER BY id""",
                    ids,
                ).fetchall()
            ]
            tx.add_changes(audit.diff({"quotes": []}, {"quotes": rows}, entity_type="job"))
            where = f" from {', '.join(file_names[:3])}" if file_names else ""
            tx.set_summary(f"Saved {len(ids)} vendor quote line{'' if len(ids) == 1 else 's'}{where}")
    return ids


def _learn_vendor_prices(conn, job_id: int, products: list[dict]) -> int:
    """Add a bid's quoted prices to the shared vendor price history, with a
    history entry of its own. Run inside job_write, with tx.conn."""
    def snapshot() -> list[dict]:
        return [
            dict(row)
            for row in conn.execute(
                """SELECT id, product_name, vendor_name, unit_price, unit, freight_per_unit, file_name
                   FROM vendor_prices WHERE job_id=? ORDER BY id""",
                (job_id,),
            ).fetchall()
        ]

    known_vendor_ids = {row[0] for row in conn.execute("SELECT id FROM vendors").fetchall()}
    before = snapshot()
    count = save_vendor_prices_from_quotes(job_id, products, conn=conn)
    after = snapshot()
    new_vendors = [
        dict(row)
        for row in conn.execute("SELECT id, name FROM vendors ORDER BY id").fetchall()
        if row["id"] not in known_vendor_ids
    ]
    changes = audit.diff({"vendor_prices": before}, {"vendor_prices": after}, entity_type="vendor_prices")
    changes += audit.diff({"vendors": []}, {"vendors": new_vendors}, entity_type="vendor_prices")
    if changes:
        summary = f"Added {count} price{'' if count == 1 else 's'} from this bid's quotes to the vendor price history"
        if new_vendors:
            summary += f" and {len(new_vendors)} new vendor{'' if len(new_vendors) == 1 else 's'}"
        audit.record(
            conn,
            action="vendor_prices.learn",
            entity_type="vendor_prices",
            job_id=job_id,
            summary=summary,
            changes=changes,
        )
    return count


@app.post("/api/jobs/{job_id}/upload-quotes")
@audit_route("quotes.upload", "vendor_prices.learn")
def api_upload_quotes(job_id: str, files: list[UploadFile] = File(...)):
    """Upload vendor quote files, parse them, return pricing."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    before_materials = [
        copy.deepcopy(material)
        for material in (job.get("materials") or [])
        if isinstance(material, dict)
    ]
    before_verified_vendor_hashes = {
        str(item.get("file_hash") or "").strip()
        for item in list_imported_files(db_id)
        if _imported_artifact_is_verified(item, "vendor_quote")
    }

    import hashlib as _hashlib

    # Ensure AI config is loaded (key may have been added since server start)
    _apply_openai_config()

    all_products = []
    skipped_files = []
    file_errors = []
    parsed_files = []
    for upload in files:
        content = upload.file.read(MAX_QUOTE_FILE_BYTES + 1)
        if len(content) > MAX_QUOTE_FILE_BYTES:
            file_errors.append({
                "file": upload.filename,
                "error": f"File exceeds the {MAX_QUOTE_FILE_BYTES // (1024 * 1024)} MB limit.",
            })
            continue

        # Dedup: check file hash before parsing
        file_hash = _hashlib.sha256(content).hexdigest()
        if _file_is_durably_imported(db_id, file_hash):
            skipped_files.append(upload.filename)
            continue

        file_path = _job_upload_path(db_id, f"{file_hash[:12]}_{upload.filename}", "quote")
        with open(file_path, "wb") as f:
            f.write(content)
        _record_artifact(db_id, file_path, "vendor_quote")

        try:
            products = parse_quote_file(file_path, strict=True)
            for p in products:
                p["file_name"] = upload.filename
                p["_source_hash"] = file_hash
            all_products.extend(products)
            if not products:
                file_errors.append({"file": upload.filename, "error": "No pricing products were extracted."})
            if products:
                parsed_files.append({
                    "file_name": upload.filename,
                    "file_hash": file_hash,
                    "file_size": len(content),
                    "artifact_path": os.path.relpath(file_path, ARTIFACT_ROOT),
                })
        except Exception as e:
            file_errors.append({"error": str(e), "file": upload.filename})

    if file_errors:
        detail = "; ".join(f"{item['file']}: {item['error']}" for item in file_errors[:5])
        raise HTTPException(
            status_code=422,
            detail=(
                "No vendor pricing was changed because every selected source must parse successfully. "
                f"{detail}"
            ),
        )

    file_names = [u.filename for u in files if hasattr(u, 'filename')]
    vendors_found = list(set(p.get("vendor", "Unknown") for p in all_products if p.get("vendor")))

    # Persist quotes to DB
    _save_quote_products(db_id, all_products, file_names, action="quotes.upload")

    # Match prices to materials. The matching (AI included) runs without
    # holding the bid; its changes are saved below.
    auto_matched, loaded_materials, priced_materials = _match_quotes_to_materials(db_id, all_products)

    # Detect matching quote requests (don't auto-link — frontend will confirm)
    linked_requests = _link_upload_to_requests(db_id, all_products)

    # The matched prices, the vendor price history and the import receipts are
    # saved together, so a source is only marked imported once all of its
    # pricing is saved.
    with job_write(db_id, action="quotes.upload", scopes=("materials",)) as tx:
        tx.force_record()
        # Only on lines nobody changed while the quotes were being matched.
        price_conflicts = _save_step_results(tx, loaded_materials, priced_materials)["conflicts"]
        # A matched line someone changed meanwhile kept their change: it
        # doesn't count as auto-matched.
        auto_matched = max(0, auto_matched - _priced_lines_skipped(loaded_materials, priced_materials, price_conflicts))

        # Save to vendor pricing database
        _learn_vendor_prices(tx.conn, db_id, all_products)

        for parsed_file in parsed_files:
            record_imported_file(
                db_id,
                parsed_file["file_name"],
                parsed_file["file_hash"],
                parsed_file["file_size"],
                source="manual",
                artifact_path=parsed_file["artifact_path"],
                artifact_kind="vendor_quote",
                conn=tx.conn,
            )

        after_materials = [
            dict(row)
            for row in tx.conn.execute(
                "SELECT * FROM job_materials WHERE job_id=? ORDER BY id", (db_id,)
            ).fetchall()
        ]
        after_imports = [
            dict(row)
            for row in tx.conn.execute(
                "SELECT file_hash, artifact_path, artifact_kind FROM imported_files WHERE job_id=?", (db_id,)
            ).fetchall()
        ]
        after_verified_vendor_hashes = {
            str(item.get("file_hash") or "").strip()
            for item in after_imports
            if _imported_artifact_is_verified(item, "vendor_quote")
        }
        upload_outcomes = _quote_upload_outcomes(
            before_materials,
            before_verified_vendor_hashes,
            after_materials,
            after_verified_vendor_hashes,
        )

        activity_detail = {
            "files": file_names,
            "vendors": vendors_found,
            "product_count": len(all_products),
            "auto_matched": auto_matched,
            "provenance_repaired": upload_outcomes["provenance_repaired"],
            "quote_price_matched": upload_outcomes["quote_price_matched"],
        }
        log_activity(
            db_id,
            "quotes_uploaded",
            (
                f"Uploaded {len(file_names)} quote file(s), {len(all_products)} products, "
                f"{upload_outcomes['quote_price_matched']} prices matched, "
                f"{upload_outcomes['provenance_repaired']} receipts repaired"
                + conflict_note(price_conflicts)
            ),
            activity_detail,
        )

    refreshed = load_job(db_id) or {}
    return {
        "products": refreshed.get("quotes") or [],
        "parsed_products": all_products,
        "auto_matched": auto_matched,
        **upload_outcomes,
        "linked_requests": linked_requests,
        "skipped_files": skipped_files,
        "file_errors": file_errors,
        # Lines someone changed while the quotes were being matched: their
        # change was kept and the quote price was not saved on them.
        "conflicts": price_conflicts,
    }


@app.get("/api/jobs/{job_id}/imported-files")
def api_imported_files(job_id: str):
    """List all files that have been imported for this job (for dedup)."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return list_imported_files(job["id"])


_QUOTE_AUDIT_COLUMNS = (
    "id, product_name, vendor, unit_price, unit, description, file_name, "
    "freight, lead_time, notes, source_hash"
)


@app.delete("/api/jobs/{job_id}/quotes")
@audit_route("quotes.clear")
def api_clear_quotes(job_id: str):
    """Clear all parsed quotes for a job."""
    db_id = _resolve_job_id(job_id)
    with job_write(db_id, action="quotes.clear", scopes=(), summary="All vendor quotes cleared") as tx:
        cleared = [
            dict(row)
            for row in tx.conn.execute(
                f"SELECT {_QUOTE_AUDIT_COLUMNS} FROM job_quotes WHERE job_id=? ORDER BY id", (db_id,)
            ).fetchall()
        ]
        delete_quotes(db_id, conn=tx.conn)
        tx.add_changes(audit.diff({"quotes": cleared}, {"quotes": []}, entity_type="job"))
        log_activity(db_id, "quotes_cleared", "All vendor quotes cleared")
    return {"message": "Quotes cleared"}


@app.put("/api/quotes/{quote_id}")
@audit_route("quotes.update", "quotes.auto_match")
def api_update_quote(quote_id: int, body: dict = Body(...)):
    """Update a single quote entry and re-match against materials."""
    job_id = get_quote_job_id(quote_id)
    if not job_id:
        raise HTTPException(status_code=404, detail="Quote not found")
    summary = f"Quote #{quote_id} updated"
    with job_write(job_id, action="quotes.update", scopes=(), summary=summary,
                   group=audit.NUMBER_EDITS, field_path=f"/quotes/{quote_id}") as tx:
        def quote_row():
            row = tx.conn.execute(
                f"SELECT {_QUOTE_AUDIT_COLUMNS} FROM job_quotes WHERE id=?", (quote_id,)
            ).fetchone()
            return dict(row) if row else None

        before = quote_row()
        update_quote(quote_id, body, conn=tx.conn)
        tx.add_changes(audit.diff(before, quote_row(), f"/quotes/{quote_id}", entity_type="job"))
        log_activity(job_id, "quote_updated", summary)
    # Re-run auto-match so the updated price flows to materials
    job = load_job(job_id)
    conflicts = []
    if job:
        quotes = job.get("quotes", [])
        conflicts = _auto_match_quotes(job_id, quotes)["conflicts"]
    return {"ok": True, "conflicts": conflicts}


# ── Dropbox Scanner Endpoints ────────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/match-dropbox-folder")
@no_audit("read-only: matches folder names the browser sends and saves nothing")
def api_match_dropbox_folder(job_id: str, body: dict = Body(...)):
    """Fuzzy-match job project name against a list of folder names from the browser.
    The browser reads the local Dropbox folder via File System Access API and sends folder names here.
    """
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    folder_names = body.get("folder_names", [])
    if not folder_names:
        return {"folder_found": False, "folder_name": None, "score": 0}

    result = match_folder(
        job.get("project_name", ""),
        job.get("gc_name", ""),
        folder_names,
    )

    if not result:
        return {"folder_found": False, "folder_name": None, "score": 0}

    return {"folder_found": True, "folder_name": result["folder_name"], "score": result["score"]}


@app.post("/api/jobs/{job_id}/calculate")
@audit_route("bid.calculate")
def api_calculate(job_id: str):
    """Run sundry + labor calculators, return results."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])

    # Stamp job-level counts for sundry calculations and Schluter fixture counts
    unit_count = job.get("unit_count", 0) or 0
    tub_shower_count = job.get("tub_shower_count", 0) or 0
    for mat in materials:
        mtype = mat.get("material_type", "")
        desc = (mat.get("description") or "").lower()
        if mtype == "backsplash":
            mat["unit_count"] = unit_count
        if mtype == "tub_shower_surround":
            mat["tub_shower_total"] = tub_shower_count
        # Schluter transitions at tub/shower surrounds get fixture_count from tub_shower_count
        # This enables _calc_schluter_pieces to compute pieces per fixture (2 sides each)
        if "schluter" in desc and ("tub" in desc or "shower" in desc or "surround" in desc or "rr" in desc or "wash" in desc):
            mat["fixture_count"] = tub_shower_count

    # Calculate sundries
    trace = AuditTraceBuilder(job["id"])

    sundries = calculate_sundries_for_materials(materials, trace=trace)

    # Calculate labor
    labor_items = calculate_labor_for_materials(materials, trace=trace)

    summary = f"Calculated {len(sundries)} sundries and {len(labor_items)} labor items"
    with job_write(job["id"], action="bid.calculate", scopes=("sundries", "labor"), summary=summary) as tx:
        tx.force_record()
        save_sundries(job["id"], sundries, conn=tx.conn)
        save_labor(job["id"], labor_items, conn=tx.conn)
        log_activity(job["id"], "bid_calculated", summary)

    run_id = create_calculation_run(
        job["id"],
        "bid_calculation",
        metadata=_audit_metadata({"endpoint": "calculate"}),
    )
    trace_count = save_calculation_traces(job["id"], run_id, trace.records)
    complete_calculation_run(run_id, summary=trace.summary())

    return {
        "sundries": sundries,
        "labor": labor_items,
        "audit": {"run_id": run_id, "trace_count": trace_count, "summary": trace.summary()},
    }


# Fields the materials table works out from the one typed into; they don't
# make an autosave a multi-field edit.
_MATERIAL_FOLLOW_FIELDS = {
    "installed_qty": ("order_qty",),
    "waste_pct": ("order_qty",),
    "unit_price": ("price_source", "quote_status"),
}
# Typed text; every other material field is a number or a dropdown.
_MATERIAL_TEXT_FIELDS = frozenset({"item_code", "description", "vendor"})


def _material_edit_group(saved_rows: list[dict], incoming_rows: list[dict]):
    """When a materials save changes one field of one saved line (the autosave
    after typing in a cell), return (history field path, grouping policy,
    summary) so quick re-saves of that cell join one history entry.
    Otherwise (None, None, None)."""
    saved = {str(row.get("id")): row for row in saved_rows or [] if row.get("id") is not None}
    incoming_ids = set()
    edited = []
    for material in incoming_rows or []:
        if not isinstance(material, dict) or material.get("id") is None or str(material.get("id")) not in saved:
            return None, None, None  # a new line
        incoming_ids.add(str(material["id"]))
        base = saved[str(material["id"])]
        fields = [
            key for key, value in material.items()
            # Identity and row bookkeeping aren't edits (a client's copy of
            # row_version / updated_at can be older than the saved line's).
            if key in base and key not in ("id", "job_id", "uid", *stable_ids.ROW_META_COLUMNS) and value is not None
            and key not in audit.DERIVED_KEYS and not audit.values_equal(base.get(key), value)
        ]
        for key in list(fields):
            for follower in _MATERIAL_FOLLOW_FIELDS.get(key, ()):
                if follower in fields:
                    fields.remove(follower)
        edited.extend((base, key, material[key]) for key in fields)
    if incoming_ids != set(saved) or len(edited) != 1:
        return None, None, None
    base, field, value = edited[0]
    policy = audit.TEXT_EDITS if field in _MATERIAL_TEXT_FIELDS else audit.NUMBER_EDITS
    label = base.get("item_code") or base.get("description") or f"line {base.get('id')}"
    return (
        # History paths name material lines by uid (job_writes.snapshot_job).
        f"/materials/{audit.escape_path_key(base.get('uid') or base['id'])}/{field}",
        policy,
        f"Changed {field.replace('_', ' ')} on {label}",
    )


@app.put("/api/jobs/{job_id}/materials")
@audit_route("materials.update")
def api_update_materials(job_id: str, body: MaterialUpdate):
    """Update materials (edited pricing, waste, etc.)."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    deletion_reasons = {
        str(key): str(value or "").strip()
        for key, value in (body.deletion_reasons or {}).items()
    }

    def deletion_key(material: dict) -> str:
        return str(material.get("item_code") or material.get("id") or "")

    edit_path, edit_policy, edit_summary = _material_edit_group(job.get("materials") or [], body.materials)
    deleted_materials = []
    with job_write(job["id"], action="materials.update", scopes=("materials",),
                   group=edit_policy, field_path=edit_path, summary=edit_summary) as tx:
        conn = tx.conn
        current_materials = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM job_materials WHERE job_id=? ORDER BY id",
                (job["id"],),
            ).fetchall()
        ]
        current_fingerprint = _materials_source_fingerprint(current_materials)
        if (
            body.base_source_fingerprint
            and body.base_source_fingerprint != current_fingerprint
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Someone changed these materials in another tab or on another computer after you "
                    "opened them, so your last change was not saved. Reload the page to see their "
                    "version, then make your change again."
                ),
            )

        existing = {material["id"]: material for material in current_materials}
        incoming_ids = {
            str(material.get("id"))
            for material in body.materials
            if material.get("id") is not None
        }
        deleted_materials = [
            material for material in existing.values()
            if str(material.get("id")) not in incoming_ids
        ]
        missing_deletion_reasons = [
            deletion_key(material)
            for material in deleted_materials
            if not deletion_reasons.get(deletion_key(material))
        ]
        if missing_deletion_reasons:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A reason is required before removing takeoff materials: "
                    f"{', '.join(missing_deletion_reasons[:5])}."
                ),
            )

        # Each line is merged onto the saved line and priced by the shared
        # rule (pricing_rows.normalize_material_row).
        recounted_transitions = []
        updated = [
            normalize_material_row(existing.get(material.get("id"), {}), material, recounted=recounted_transitions)
            for material in body.materials
        ]

        material_ids = save_materials(job["id"], updated, conn=conn)
        for material, material_id in zip(updated, material_ids):
            material["id"] = material_id
        persisted_materials = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM job_materials WHERE job_id=? ORDER BY id",
                (job["id"],),
            ).fetchall()
        ]
        source_fingerprint = _materials_source_fingerprint(persisted_materials)

        # Activity rows go in the same transaction; the first one names the
        # history entry unless a single cell edit already did.
        if deleted_materials:
            log_activity(
                job["id"],
                "materials_deleted",
                f"Removed {len(deleted_materials)} takeoff material(s) with estimator reasons",
                {
                    "deletions": [
                        {
                            "material_key": deletion_key(material),
                            "description": material.get("description"),
                            "reason": deletion_reasons.get(deletion_key(material)),
                        }
                        for material in deleted_materials
                    ],
                },
            )
        log_activity(job["id"], "materials_updated", f"Updated pricing for {len(body.materials)} materials")
        if recounted_transitions:
            print(f"[materials] Recounted sticks on {len(recounted_transitions)} EA transition line(s): {recounted_transitions}")
            log_activity(
                job["id"],
                "transition_sticks_recounted",
                f"Recounted Schluter/Silver Pin sticks on {len(recounted_transitions)} saved EA line(s); review the before/after totals",
                {"lines": recounted_transitions},
            )

    # Keep read-only price suggestions visible after an autosave without
    # including them in the durable source fingerprint.
    response_job = {"materials": persisted_materials}
    _enrich_known_prices(response_job)
    response_materials = response_job["materials"]

    return {
        "materials": response_materials,
        "materials_source_fingerprint": source_fingerprint,
    }


@app.get("/api/jobs/{job_id}/price-decisions")
def api_get_material_price_decisions(job_id: str):
    """Return immutable vendor-price review history for a job."""
    db_id = _resolve_job_id(job_id)
    if not load_job(db_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "decisions": list_material_price_decisions(db_id),
        "active_decisions": list_material_price_decisions(db_id, active_only=True),
    }


@app.post("/api/jobs/{job_id}/materials/{material_id}/quote-conflict")
@audit_route("materials.price_decision")
def api_resolve_material_price_conflict(
    job_id: str,
    material_id: int,
    body: VendorPriceConflictResolutionRequest,
):
    """Resolve one verified quote conflict without discarding its evidence."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    decision_type = str(body.decision or "").strip().lower()
    reviewer = str(body.reviewer_name or "").strip()
    reason = str(body.reason or "").strip()
    source_hash = str(body.source_hash or "").strip().lower()
    quote_unit = normalize_quote_unit(body.quote_unit)
    if decision_type not in {"use_quote", "keep_accepted"}:
        raise HTTPException(status_code=400, detail="Choose either the verified quote or the accepted price.")
    if len(reviewer) < 2:
        raise HTTPException(status_code=400, detail="Enter the estimator or reviewer name.")
    if len(reason) < 5:
        raise HTTPException(status_code=400, detail="Enter a short reason for this price decision.")
    if len(source_hash) != 64 or any(character not in "0123456789abcdef" for character in source_hash):
        raise HTTPException(status_code=400, detail="The selected quote receipt is not a valid SHA-256 source.")
    if not math.isfinite(body.quote_price) or body.quote_price <= 0:
        raise HTTPException(status_code=400, detail="The verified quote price must be positive.")
    if not math.isfinite(body.accepted_price) or body.accepted_price <= 0:
        raise HTTPException(status_code=400, detail="The accepted price must be positive.")

    proposal = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    deleted_reasons = proposal.get("deleted_material_reasons")
    if not isinstance(deleted_reasons, dict):
        deleted_reasons = {}
    deleted_codes = {
        str(code)
        for code in (proposal.get("deleted_material_codes") or [])
        if code and str(deleted_reasons.get(str(code)) or "").strip()
    }
    active_materials = [
        material
        for material in (job.get("materials") or [])
        if isinstance(material, dict) and _job_material_key(material) not in deleted_codes
    ]
    verified_hashes = {
        str(item.get("file_hash") or "").strip()
        for item in list_imported_files(db_id)
        if _imported_artifact_is_verified(item, "vendor_quote")
    }
    conflicts = find_verified_quote_price_conflicts(
        active_materials,
        job.get("quotes") or [],
        verified_hashes,
    )
    conflict = next(
        (
            row for row in conflicts
            if str(row.get("material_id")) == str(material_id)
            and str(row.get("source_hash") or "").strip().lower() == source_hash
            and abs((_as_number(row.get("quote_price")) or 0) - body.quote_price) <= 0.005
            and abs((_as_number(row.get("accepted_price")) or 0) - body.accepted_price) <= 0.005
            and normalize_quote_unit(row.get("quote_unit")) == quote_unit
        ),
        None,
    )
    if not conflict:
        raise HTTPException(
            status_code=409,
            detail="This price was already reviewed or has changed. Reload the page and look at it again.",
        )

    action_label = "used the verified quote" if decision_type == "use_quote" else "kept the accepted price"
    with job_write(db_id, action="materials.price_decision", scopes=("materials",)) as tx:
        conn = tx.conn
        current_row = conn.execute(
            "SELECT * FROM job_materials WHERE id=? AND job_id=?",
            (material_id, db_id),
        ).fetchone()
        if not current_row:
            raise HTTPException(status_code=404, detail="Material not found")
        current = dict(current_row)
        current_price = _as_number(current.get("unit_price")) or 0
        if abs(current_price - body.accepted_price) > 0.005:
            raise HTTPException(
                status_code=409,
                detail="The material price changed while this decision was open. Refresh and review it again.",
            )

        resolved_price = conflict["quote_price"] if decision_type == "use_quote" else current_price
        resolved_source = "vendor_quote" if decision_type == "use_quote" else "vendor_quote_override"
        resolved_status = "quoted" if decision_type == "use_quote" else "accepted_override"
        candidate = {
            **current,
            "unit_price": resolved_price,
            "price_source": resolved_source,
            "quote_status": resolved_status,
            "quote_source_hash": source_hash,
            "quote_file_name": conflict.get("source_file") or "",
        }
        resolved_extended_cost = (
            material_pricing_context(candidate)["expected_cost"]
            if decision_type == "use_quote"
            else (_as_number(current.get("extended_cost")) or 0)
        )
        conn.execute(
            """UPDATE job_materials
               SET unit_price=?, extended_cost=?, price_source=?, quote_status=?,
                   quote_source_hash=?, quote_file_name=?
               WHERE id=? AND job_id=?""",
            (
                round(resolved_price, 2), round(resolved_extended_cost, 2),
                resolved_source, resolved_status, source_hash,
                conflict.get("source_file") or "", material_id, db_id,
            ),
        )
        decision = record_material_price_decision(
            db_id,
            material_id,
            item_code=str(current.get("item_code") or current.get("description") or ""),
            decision=decision_type,
            accepted_price_before=round(current_price, 2),
            resolved_price=round(resolved_price, 2),
            material_unit=normalize_quote_unit(current.get("unit")),
            quote_price=round(conflict["quote_price"], 2),
            quote_unit=conflict["quote_unit"],
            source_hash=source_hash,
            source_file=conflict.get("source_file") or "",
            reason=reason,
            reviewer_name=reviewer,
            conn=conn,
        )
        tx.add_changes(audit.diff(
            {"material_price_decisions": []}, {"material_price_decisions": [decision]}, entity_type="job",
        ))
        log_activity(
            db_id,
            "vendor_price_decision",
            f"{reviewer} {action_label} for {conflict.get('item_code') or material_id}",
            {
                "decision_id": decision["id"],
                "material_id": material_id,
                "item_code": conflict.get("item_code"),
                "decision": decision_type,
                "accepted_price_before": round(current_price, 2),
                "resolved_price": round(resolved_price, 2),
                "quote_price": round(conflict["quote_price"], 2),
                "source_hash": source_hash,
                "source_file": conflict.get("source_file") or "",
                "reason": reason,
            },
            user=reviewer,
        )
    updated_job = load_job(db_id)
    return {
        "decision": decision,
        "material": next(
            (material for material in (updated_job.get("materials") or []) if material.get("id") == material_id),
            None,
        ),
        "materials_source_fingerprint": _materials_source_fingerprint(updated_job.get("materials") or []),
        "readiness": _evaluate_job_readiness(updated_job),
    }


@app.post("/api/jobs/{job_id}/materials/by-id/{material_id}/estimate-price")
@audit_route("materials.ai_estimate")
def api_estimate_price_by_id(job_id: str, material_id: int):
    """Use AI to estimate one material line's unit price (the line with this id)."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    material = next((m for m in job.get("materials") or [] if m.get("id") == material_id), None)
    if material is None:
        raise HTTPException(
            status_code=404,
            detail="That line isn't in this bid's takeoff anymore (someone may have removed it).",
        )
    return _estimate_material_price(job, material)


@app.post("/api/jobs/{job_id}/materials/{material_idx}/estimate-price")
@audit_route("materials.ai_estimate")
def api_estimate_price(job_id: str, material_idx: int):
    """Use AI to estimate a material's unit price based on its description.

    Older form that names the line by its place in the list. The place is
    turned into the line's id when the list is read, so the estimate is saved
    on that line (and only if nobody changed its price meanwhile) even if lines
    are added or removed while the AI is working."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])
    if material_idx < 0 or material_idx >= len(materials):
        raise HTTPException(status_code=404, detail="Material not found")
    return _estimate_material_price(job, materials[material_idx])


def _estimate_material_price(job: dict, material: dict) -> dict:
    """Ask the AI for a unit price for one line (without holding the bid),
    then save it as a compare-and-swap patch: only if the line still has the
    price, quantities and description the AI was given. Otherwise the other
    person's change is kept, the skipped estimate is noted in the history and
    the caller gets a 409 saying what happened."""
    m = copy.deepcopy(material)
    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")

    provider = get_provider_info(api_key)
    if not provider["available"]:
        raise HTTPException(status_code=400, detail="No AI API key configured (set OpenAI or ANTHROPIC_API_KEY)")

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
        raw = chat_complete(
            system="You are a commercial flooring estimator. Return only valid JSON.",
            user=prompt,
            api_key=api_key,
            model=model,
            json_mode=True,
        )
        result = _json.loads(raw)
        estimated_price = float(result.get("estimated_price", 0))
        confidence = float(result.get("confidence", 0.5))
        reasoning = result.get("reasoning", "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI estimation failed: {e}")

    # The AI call ran without holding the bid. The new price (with order qty
    # and extended cost worked out by the shared pricing rule) is saved only
    # if the line still has the values the AI was given.
    label = m.get("item_code") or m.get("description") or "material"
    patch = material_patch(
        material,
        {
            "unit_price": round(estimated_price, 2),
            "price_source": "ai_estimate",
            "order_qty": round((m.get("installed_qty", 0) or 0) * (1 + (m.get("waste_pct", 0) or 0)), 2),
        },
        normalize=True,
    )
    summary = f"AI estimated price for {label}: ${estimated_price:.2f}/{m.get('unit', 'unit')}"
    with job_write(job["id"], action="materials.ai_estimate", scopes=("materials",), summary=summary,
                   extra={"confidence": confidence, "reasoning": reasoning,
                          "material_id": material.get("id"), "material_uid": material.get("uid")}) as tx:
        saved = apply_material_patches(tx, [patch])
        if saved["conflicts"]:
            tx.set_summary(f"AI price estimate for {label} not saved: someone changed the line meanwhile")
        else:
            log_activity(job["id"], "ai_estimate", summary)
        current = tx.conn.execute(
            "SELECT * FROM job_materials WHERE id=? AND job_id=?", (material.get("id"), job["id"]),
        ).fetchone()
    if saved["conflicts"]:
        raise HTTPException(status_code=409, detail=saved["conflicts"][0]["message"])

    return {
        "estimated_price": estimated_price,
        "confidence": confidence,
        "reasoning": reasoning,
        "material": dict(current) if current else m,
    }


@app.post("/api/jobs/{job_id}/generate-bid")
@audit_route("bid.generate")
def api_generate_bid(job_id: str):
    """Assemble bid + generate PDF, return bid data."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _validate_bid_job_ready(job)

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
        "gpm_pct": job.get("gpm_pct", 0),
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
    bid_audit = _record_bid_audit(job["id"], bid_data)

    # Persist full bid data to job record (bundles + totals)
    bid_persist = {
        "bundles": bid_data["bundles"],
        "subtotal": bid_data["subtotal"],
        "markup_pct": bid_data["markup_pct"],
        "markup_amount": bid_data["markup_amount"],
        "gpm_pct": bid_data.get("gpm_pct", 0),
        "gpm_profit": bid_data.get("gpm_profit", 0),
        "total_cost": bid_data.get("total_cost", 0),
        "tax_rate": bid_data["tax_rate"],
        "tax_amount": bid_data["tax_amount"],
        "grand_total": bid_data["grand_total"],
        "exclusions": bid_data.get("exclusions", []),
        "audit": {
            "run_id": bid_audit["run"]["id"],
            "trace_count": bid_audit["trace_count"],
            "summary": bid_audit["run"].get("summary", {}),
            "ruleset_version": bid_audit["run"].get("metadata", {}).get("ruleset_version"),
        },
        "pdf_audit_run_id": bid_audit["run"]["id"],
        "pdf_ruleset_version": bid_audit["run"].get("metadata", {}).get("ruleset_version"),
        "pdf_source_fingerprint": _bid_source_fingerprint(job),
        "pdf_totals": {
            "subtotal": bid_data["subtotal"],
            "tax_amount": bid_data["tax_amount"],
            "grand_total": bid_data["grand_total"],
            "total_cost": bid_data.get("total_cost", 0),
            "gpm_profit": bid_data.get("gpm_profit", 0),
            "markup_amount": bid_data.get("markup_amount", 0),
        },
    }
    bundle_count = len(bid_data.get("bundles", []))
    grand_total = bid_data.get("grand_total", 0)
    summary = f"Bid generated: {bundle_count} bundles, total ${grand_total:,.2f}"
    # Draw the PDF first (into a temp file), then save the bundles, the bid
    # data (only those; the rest of the bid is untouched) and the new PDF's
    # receipt together. Every print is kept as its own file.
    draft = _draft_job_pdf(job["id"], "bid", lambda path: generate_bid_pdf(copy.deepcopy(bid_data), path))
    try:
        with job_write(job["id"], action="bid.generate", scopes=("bundles", "bid"), summary=summary) as tx:
            tx.force_record()
            save_bundles(job["id"], bid_data["bundles"], conn=tx.conn)
            set_bid_data(tx.conn, job["id"], bid_persist)
            log_activity(job["id"], "bid_generated", summary, {"bundle_count": bundle_count, "grand_total": grand_total})
            artifact_id = _publish_job_pdf(job["id"], draft, "bid_pdf", conn=tx.conn, grand_total=grand_total)
            tx.extra["pdf"] = {"artifact_id": artifact_id, "file_hash": draft["sha256"]}
    finally:
        _discard_job_pdf(draft)

    bid_data["audit"] = bid_persist["audit"]
    bid_data["pdf_artifact_id"] = artifact_id
    return bid_data


@app.delete("/api/jobs/{job_id}/bid")
@audit_route("bid.clear")
def api_clear_bid(job_id: str):
    """Clear saved bid data for a job."""
    db_id = _resolve_job_id(job_id)
    with job_write(db_id, action="bid.clear", scopes=("bundles", "bid"), summary="Bid data cleared") as tx:
        set_bid_data(tx.conn, db_id, None)
        # Clear bundles too
        save_bundles(db_id, [], conn=tx.conn)
        log_activity(db_id, "bid_cleared", "Bid data cleared")
    return {"message": "Bid cleared"}


@app.get("/api/jobs/{job_id}/bid.pdf")
def api_download_bid_pdf(job_id: str):
    """Download the generated bid PDF."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _validate_bid_pdf_download_ready(job)
    # The latest print; earlier ones are under /artifacts.
    latest = _latest_job_pdf(job["id"], "bid_pdf")
    if not latest or not os.path.exists(latest[0]):
        raise HTTPException(status_code=404, detail="PDF not found. Generate bid first.")
    pdf_path = latest[0]
    _require_artifact_receipt(job["id"], pdf_path, "bid_pdf")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"bid_{job_id}.pdf",
    )


# ── Proposal Endpoints ─────────────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/proposal/rewrite-descriptions")
@no_audit("AI draft only: returns suggested descriptions and saves nothing")
async def api_rewrite_descriptions(job_id: str, request: Request):
    """Use AI to rewrite bundle descriptions in professional proposal style."""
    raw_body = await request.body()
    return await run_in_threadpool(_rewrite_descriptions, job_id, raw_body)


def _rewrite_descriptions(job_id: str, raw_body: bytes) -> dict:
    from description_agent import rewrite_bundle_descriptions

    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    body = json.loads(raw_body)
    bundles = body.get("bundles", [])
    if not bundles:
        raise HTTPException(status_code=400, detail="No bundles provided")

    try:
        descriptions = rewrite_bundle_descriptions(bundles, job)
    except AIError as e:
        raise HTTPException(status_code=502, detail=f"{e.user_message} Nothing was changed.")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not descriptions:
        raise HTTPException(status_code=502, detail="The AI didn't rewrite any bundles. Nothing was changed. Click Rewrite to try again.")
    return {"descriptions": descriptions}


@app.get("/api/jobs/{job_id}/proposal/bundles")
def api_get_proposal_bundles(job_id: str):
    """Load saved proposal editor state (bundles, notes, terms, etc.)."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    pd = job.get("proposal_data")
    if pd and isinstance(pd, dict) and pd.get("bundles"):
        return pd
    return {"bundles": [], "notes": [], "terms": [], "exclusions": []}


# ── Calculation Audit Endpoints ─────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/audit/runs")
def api_get_calculation_runs(job_id: str, limit: int = 20):
    """List calculation audit runs for a job."""
    db_id = _resolve_job_id(job_id)
    return {"runs": list_calculation_runs(db_id, limit=limit)}


@app.get("/api/jobs/{job_id}/audit")
def api_get_latest_calculation_audit(job_id: str, limit: int = 1000, scope: Optional[str] = None):
    """Fetch the latest audit, optionally limited to accepted-proposal work."""
    db_id = _resolve_job_id(job_id)
    if scope not in (None, "", "proposal"):
        raise HTTPException(status_code=400, detail="Unsupported audit scope")
    if scope == "proposal":
        run = get_latest_completed_calculation_run(
            db_id,
            {"proposal_editor_save", "proposal_generation", "bid_calculation"},
        )
    else:
        runs = list_calculation_runs(db_id, limit=1)
        run = runs[0] if runs else None
    traces = []
    if run:
        traces = get_calculation_traces(db_id, run_id=run["id"], limit=limit)
        if run.get("run_type") in ("proposal_manual_save", "proposal_editor_save"):
            prior = get_latest_completed_calculation_run(
                db_id,
                {"proposal_generation", "bid_calculation"},
            )
            if prior:
                remaining = max(limit - len(traces), 0)
                if remaining:
                    traces.extend(get_calculation_traces(db_id, run_id=prior["id"], limit=remaining))
    return {
        "run": run,
        "traces": traces,
        "events": traces,
        "audit": run.get("summary", {}) if run else {},
    }


@app.get("/api/jobs/{job_id}/audit/trace")
def api_get_calculation_trace(
    job_id: str,
    run_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_key: Optional[str] = None,
    limit: int = 1000,
):
    """Fetch calculation trace rows. Defaults to the latest run for the job."""
    db_id = _resolve_job_id(job_id)
    selected_run_id = run_id
    run = None
    if selected_run_id is None:
        runs = list_calculation_runs(db_id, limit=10)
        if runs:
            run = runs[0]
            selected_run_id = run["id"]
    elif selected_run_id is not None:
        runs = [r for r in list_calculation_runs(db_id, limit=100) if r["id"] == selected_run_id]
        run = runs[0] if runs else None

    traces = []
    if selected_run_id is not None:
        traces = get_calculation_traces(
            db_id,
            run_id=selected_run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_key=entity_key,
            limit=limit,
        )
        if run and run.get("run_type") in ("proposal_manual_save", "proposal_editor_save") and not any([run_id, entity_type, entity_id, entity_key]):
            prior = get_latest_completed_calculation_run(
                db_id,
                {"proposal_generation", "bid_calculation"},
            )
            if prior:
                remaining = max(limit - len(traces), 0)
                if remaining:
                    traces.extend(get_calculation_traces(db_id, run_id=prior["id"], limit=remaining))
    return {"run": run, "traces": traces}


@app.get("/api/jobs/{job_id}/audit/runs/{run_id}/trace")
def api_get_calculation_run_trace(
    job_id: str,
    run_id: int,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_key: Optional[str] = None,
    limit: int = 1000,
):
    """Fetch calculation trace rows for a specific run."""
    db_id = _resolve_job_id(job_id)
    traces = get_calculation_traces(
        db_id,
        run_id=run_id,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_key=entity_key,
        limit=limit,
    )
    return {"run_id": run_id, "traces": traces}


@app.post("/api/rules/audit-harness")
@no_audit("read-only check: runs rule probes in memory and saves nothing")
def api_rules_audit_harness_probe(body: Optional[dict] = Body(default=None)):
    """Small UI probe for rules/audit visibility; full harness lives in scripts/."""
    body = body or {}
    job_ref = body.get("job_id")
    stage = body.get("stage")
    category = body.get("category")
    field = body.get("field")
    rules = get_active_rules(stage=stage if stage not in ("", "all") else None,
                             category=category if category not in ("", "all") else None)
    response = {
        "status": "ok",
        "rule_count": len(rules),
        "rules": rules[:25],
        "note": "Full deployed harness: scripts/rules_audit_harness.py --base-url <fly-url>",
    }
    recovery_hash = "a" * 64
    recovery_probe = _quote_upload_outcomes(
        [
            {"id": 1, "item_code": "RECEIPT", "unit_price": 5.25, "price_source": "vendor_quote"},
            {"id": 2, "item_code": "NEW-PRICE", "unit_price": 0, "price_source": None},
            {"id": 3, "item_code": "PRICE-CHANGED", "unit_price": 5.25, "price_source": "vendor_quote"},
        ],
        set(),
        [
            {"id": 1, "item_code": "RECEIPT", "unit_price": 5.25, "price_source": "vendor_quote", "quote_source_hash": recovery_hash},
            {"id": 2, "item_code": "NEW-PRICE", "unit_price": 8.75, "price_source": "vendor_quote", "quote_source_hash": recovery_hash},
            {"id": 3, "item_code": "PRICE-CHANGED", "unit_price": 5.26, "price_source": "vendor_quote", "quote_source_hash": recovery_hash},
        ],
        {recovery_hash},
    )
    response["quote_receipt_recovery_contract"] = {
        "status": "pass" if (
            recovery_probe["provenance_repaired"] == 1
            and recovery_probe["provenance_repaired_items"] == ["RECEIPT"]
            and recovery_probe["quote_price_matched"] == 1
            and recovery_probe["quote_price_matched_items"] == ["NEW-PRICE"]
        ) else "fail",
        "result": recovery_probe,
    }
    conflict_probe = find_verified_quote_price_conflicts(
        [
            {"id": 1, "item_code": "T-100", "unit_price": 5.82, "unit": "SF", "price_source": "manual"},
            {"id": 2, "item_code": "ST-100", "unit_price": 13.75, "unit": "SF", "price_source": "vendor_quote"},
            {"id": 3, "item_code": "T-108", "unit_price": 4.65, "unit": "SF", "price_source": "vendor_quote", "quote_source_hash": recovery_hash},
        ],
        [
            {"product_name": "T-100 - Cornerstone", "unit_price": 6.06, "unit": "SF", "source_hash": recovery_hash, "file_name": "ergon.eml"},
            {"product_name": "ST-100 - Slab", "unit_price": 13.75, "unit": "SF", "source_hash": recovery_hash, "file_name": "slab.eml"},
            {"product_name": "T-108 - Stonehenge", "unit_price": 4.90, "unit": "SF", "source_hash": recovery_hash, "file_name": "ergon.eml"},
        ],
        {recovery_hash},
    )
    response["quote_price_conflict_contract"] = {
        "status": "pass" if (
            len(conflict_probe) == 1
            and conflict_probe[0]["item_code"] == "T-100"
            and conflict_probe[0]["delta"] == 0.24
            and conflict_probe[0]["accepted_source"] == "manual"
        ) else "fail",
        "result": conflict_probe,
    }
    response["quote_multipass_contract"] = quote_multipass_audit_contract()
    transition_cases = {
        "lf_to_sticks": {
            "material_type": "transitions", "price_source": "price_book",
            "vendor": "Schluter", "unit": "EA", "order_qty": 212,
            "installed_qty": 212, "waste_pct": 0,
            "fixture_count": 0, "unit_price": 7.94, "extended_cost": 206.44,
        },
        "stored_pieces": {
            "material_type": "transitions", "price_source": "price_book",
            "vendor": "Schluter", "unit": "EA", "order_qty": 5,
            "fixture_count": 0, "unit_price": 9.78, "extended_cost": 48.90,
        },
        "corrupted": {
            "material_type": "transitions", "price_source": "price_book",
            "vendor": "Schluter", "unit": "EA", "order_qty": 34,
            "installed_qty": 34, "waste_pct": 0,
            "fixture_count": 0, "unit_price": 9.78, "extended_cost": 40.00,
        },
    }
    transition_results = {
        name: material_pricing_context(case)
        for name, case in transition_cases.items()
    }
    transition_ok = (
        transition_results["lf_to_sticks"]["basis"] == "transition_sticks"
        and transition_results["lf_to_sticks"]["expected_cost"] == 206.44
        and transition_results["stored_pieces"]["basis"] == "stored_transition_pieces"
        and transition_results["stored_pieces"]["expected_cost"] == 48.90
        and transition_results["corrupted"]["expected_cost"] == 48.90
        and transition_results["corrupted"]["expected_cost"]
        != transition_cases["corrupted"]["extended_cost"]
    )
    response["transition_pricing_contract"] = {
        "status": "pass" if transition_ok else "fail",
        "result": transition_results,
    }
    classification_cases = {
        "CPT-110": (
            "CPT-110 - 1'7.75\" - 1'7.75\" - Carpet Tile",
            "cpt_tile",
        ),
        "T-111": (
            "T-111 - Marazzi - Moroccan Concrete - 12x24 - Wall Tile",
            "wall_tile",
        ),
        "T-112": (
            "T-112 - Jamie Beckwith - Trowel - 3x9 - Porcelain Wall Tile",
            "wall_tile",
        ),
        "Transition (LVT to Tile)": (
            "Transition (LVT to Tile)",
            "transitions",
        ),
        "Vertical Exposed Edge Trim": (
            "Vertical Exposed Edge Trim @L-5 RR",
            "transitions",
        ),
    }
    classification_results = {
        item_code: {
            "expected": expected,
            "actual": infer_material_type_fallback(item_code, description),
        }
        for item_code, (description, expected) in classification_cases.items()
    }
    response["classification_fallback_contract"] = {
        "status": "pass" if all(
            item["actual"] == item["expected"]
            for item in classification_results.values()
        ) else "fail",
        "result": classification_results,
    }
    exact_cent_proposal = {
        "tax_rate": 0.10,
        "gpm_pct": 0,
        "subtotal": 100.0,
        "tax_amount": 10.0,
        "grand_total": 110.0,
        "gpm_profit": 0,
        "gpm_labor": 0,
        "gpm_material": 0,
        "manual_adjustment": 0,
        "textura_fee": 0,
        "textura_amount": 0,
        "bundles": [{
            "bundle_name": "Exact-cent contract",
            "is_derived": True,
            "material_cost": 100.0,
            "sundry_cost": 0,
            "labor_cost": 0,
            "freight_cost": 0,
            "gpm_labor_adder": 0,
            "gpm_material_adder": 0,
            "gpm_adder": 0,
            "taxable": 100.0,
            "tax_amount": 10.0,
            "total_price": 110.0,
            "materials": [],
            "sundry_items": [],
            "labor_items": [],
        }],
    }
    exact_cent_errors = proposal_math_errors(exact_cent_proposal)
    one_cent_drift = copy.deepcopy(exact_cent_proposal)
    one_cent_drift["grand_total"] = 110.01
    one_cent_errors = proposal_math_errors(one_cent_drift)
    expected_cent_error = GRAND_TOTAL_MISMATCH
    response["proposal_cent_arithmetic_contract"] = {
        "status": "pass" if not exact_cent_errors and expected_cent_error in one_cent_errors else "fail",
        "result": {
            "exact_cent_errors": exact_cent_errors,
            "one_cent_errors": one_cent_errors,
        },
    }
    labor_qty, labor_cost = labor_line_values(1229.704, 3.48)
    response["labor_line_rounding_contract"] = {
        "status": "pass" if labor_qty == 1229.70 and labor_cost == 4279.36 else "fail",
        "result": {
            "source_quantity": 1229.704,
            "stored_quantity": labor_qty,
            "rate": 3.48,
            "extended_cost": labor_cost,
            "visible_formula_cost": round(labor_qty * 3.48, 2),
        },
    }
    labor_base = {
        "tax_rate": 0,
        "gpm_pct": 0,
        "textura_fee": 0,
        "bundles": [{
            "bundle_name": "Labor identity contract",
            "materials": [{"item_code": "SM-TEST"}],
            "sundry_items": [],
            "labor_items": [{
                "material_id": 1,
                "labor_description": "New calculated labor rule",
                "qty": 100,
                "unit": "SF",
                "rate": 0.75,
                "extended_cost": 75,
            }],
            "material_cost": 0,
            "sundry_cost": 0,
            "labor_cost": 75,
            "freight_cost": 0,
            "installed_qty": 100,
            "unit": "SF",
        }],
    }
    drift_accepted = copy.deepcopy(labor_base)
    drift_accepted["bundles"][0]["labor_items"][0].update({
        "labor_description": "Old calculated labor rule",
        "rate": 0.50,
        "extended_cost": 50,
    })
    drift_result = copy.deepcopy(labor_base)
    apply_accepted_numeric_edits(drift_result, drift_accepted)

    manual_accepted = copy.deepcopy(labor_base)
    manual_accepted["bundles"][0]["labor_items"][0].update({
        "rate": 0.50,
        "extended_cost": 50,
        "is_manual": True,
    })
    manual_result = copy.deepcopy(labor_base)
    apply_accepted_numeric_edits(manual_result, manual_accepted)
    drift_lines = drift_result["bundles"][0]["labor_items"]
    manual_lines = manual_result["bundles"][0]["labor_items"]
    labor_identity_ok = (
        len(drift_lines) == 1
        and drift_lines[0].get("labor_description") == "New calculated labor rule"
        and drift_result["bundles"][0].get("labor_cost") == 75.0
        and len(manual_lines) == 1
        and manual_lines[0].get("is_manual") is True
        and manual_result["bundles"][0].get("labor_cost") == 50.0
    )
    response["accepted_labor_identity_contract"] = {
        "status": "pass" if labor_identity_ok else "fail",
        "result": {
            "rule_drift_lines": drift_lines,
            "rule_drift_labor_cost": drift_result["bundles"][0].get("labor_cost"),
            "explicit_manual_lines": manual_lines,
            "explicit_manual_labor_cost": manual_result["bundles"][0].get("labor_cost"),
        },
    }
    sundry_base = {
        "tax_rate": 0,
        "gpm_pct": 0,
        "textura_fee": 0,
        "bundles": [{
            "bundle_name": "Sundry identity contract",
            "materials": [{"item_code": "SM-TEST"}],
            "sundry_items": [{
                "material_id": 1,
                "sundry_name": "New calculated sundry rule",
                "qty": 10,
                "unit": "SF",
                "unit_price": 2,
                "extended_cost": 20,
            }],
            "labor_items": [],
            "material_cost": 0,
            "sundry_cost": 20,
            "labor_cost": 0,
            "freight_cost": 0,
            "installed_qty": 10,
            "unit": "SF",
        }],
    }
    sundry_drift_accepted = copy.deepcopy(sundry_base)
    sundry_drift_accepted["bundles"][0]["sundry_items"][0].update({
        "sundry_name": "Old calculated sundry rule",
        "unit_price": 1,
        "extended_cost": 10,
    })
    sundry_drift_result = copy.deepcopy(sundry_base)
    apply_accepted_numeric_edits(sundry_drift_result, sundry_drift_accepted)

    sundry_manual_accepted = copy.deepcopy(sundry_base)
    sundry_manual_accepted["bundles"][0]["sundry_items"].append({
        "material_id": 1,
        "sundry_name": "Estimator allowance",
        "qty": 3,
        "unit": "EA",
        "unit_price": 4,
        "extended_cost": 12,
        "is_manual_price": True,
    })
    sundry_manual_result = copy.deepcopy(sundry_base)
    apply_accepted_numeric_edits(sundry_manual_result, sundry_manual_accepted)
    sundry_drift_lines = sundry_drift_result["bundles"][0]["sundry_items"]
    sundry_manual_lines = sundry_manual_result["bundles"][0]["sundry_items"]
    sundry_identity_ok = (
        len(sundry_drift_lines) == 1
        and sundry_drift_lines[0].get("sundry_name") == "New calculated sundry rule"
        and sundry_drift_result["bundles"][0].get("sundry_cost") == 20.0
        and len(sundry_manual_lines) == 2
        and any(
            line.get("sundry_name") == "Estimator allowance"
            and line.get("is_manual_price") is True
            for line in sundry_manual_lines
        )
        and sundry_manual_result["bundles"][0].get("sundry_cost") == 32.0
    )
    response["accepted_sundry_identity_contract"] = {
        "status": "pass" if sundry_identity_ok else "fail",
        "result": {
            "rule_drift_lines": sundry_drift_lines,
            "rule_drift_sundry_cost": sundry_drift_result["bundles"][0].get("sundry_cost"),
            "explicit_manual_lines": sundry_manual_lines,
            "explicit_manual_sundry_cost": sundry_manual_result["bundles"][0].get("sundry_cost"),
        },
    }
    if field:
        response["field"] = field
    if job_ref:
        db_id = _resolve_job_id(str(job_ref))
        runs = list_calculation_runs(db_id, limit=1)
        response["latest_run"] = runs[0] if runs else None
        response["trace_count"] = 0
        if runs:
            traces = get_calculation_traces(db_id, run_id=runs[0]["id"], limit=1000)
            response["trace_count"] = len(traces)
            matching = [t for t in traces if not field or t.get("output_field") == field]
            response["field_trace"] = matching[-1] if matching else None
            response["field_trace_count"] = len(matching)
            response["sample_traces"] = (matching or traces)[:10]
            response["summary"] = {
                "run_type": runs[0].get("run_type"),
                "field": field,
                "field_found": bool(matching),
                "formula": (matching[-1].get("formula") if matching else None),
                "result": (matching[-1].get("result") if matching else None),
                "source": (matching[-1].get("source") if matching else None),
                "rule_id": (matching[-1].get("rule_id") if matching else None),
            }
    return response


def _accepted_bundle_options(proposal: dict | None) -> list[dict]:
    return [
        {
            "bundle_name": str(bundle.get("bundle_name") or "").strip(),
            "accepted_total": effective_bundle_total(bundle),
        }
        for bundle in ((proposal or {}).get("bundles") or [])
        if isinstance(bundle, dict) and str(bundle.get("bundle_name") or "").strip()
    ]


def _validated_jr_bundle_targets(raw_targets: list[dict] | None, proposal: dict) -> list[dict]:
    if not raw_targets:
        return []
    options = _accepted_bundle_options(proposal)
    accepted_names = {row["bundle_name"] for row in options}
    accepted_order = [row["bundle_name"] for row in options]
    targets_by_name: dict[str, dict] = {}
    for index, raw in enumerate(raw_targets):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"JR bundle target {index + 1} must be an object.")
        bundle_name = str(raw.get("bundle_name") or "").strip()
        if not bundle_name:
            raise HTTPException(status_code=400, detail=f"JR bundle target {index + 1} is missing a bundle name.")
        if bundle_name not in accepted_names:
            raise HTTPException(status_code=400, detail=f"JR bundle target '{bundle_name}' does not match an accepted proposal bundle.")
        if bundle_name in targets_by_name:
            raise HTTPException(status_code=400, detail=f"JR bundle target '{bundle_name}' was entered more than once.")
        target_total = _as_money_number(raw.get("target_total"))
        if target_total is None or target_total < 0:
            raise HTTPException(status_code=400, detail=f"JR bundle target '{bundle_name}' must have a non-negative total.")
        source_page = raw.get("source_page")
        if source_page in (None, ""):
            source_page = None
        else:
            try:
                source_page = int(source_page)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"JR bundle target '{bundle_name}' has an invalid source page.") from exc
            if source_page <= 0:
                raise HTTPException(status_code=400, detail=f"JR bundle target '{bundle_name}' source page must be positive.")
        targets_by_name[bundle_name] = {
            "bundle_name": bundle_name,
            "jr_label": str(raw.get("jr_label") or bundle_name).strip()[:300] or bundle_name,
            "target_total": target_total,
            "source_page": source_page,
            "notes": str(raw.get("notes") or "").strip()[:1000],
        }
    return [targets_by_name[name] for name in accepted_order if name in targets_by_name]


def _public_golden_job(golden: dict | None) -> dict | None:
    if not golden:
        return None
    snapshot = golden.get("snapshot") or {}
    return {
        "id": golden.get("id"),
        "version_id": golden.get("version_id"),
        "version_number": golden.get("version_number"),
        "immutable": bool(golden.get("immutable")),
        "source_job_id": golden.get("source_job_id"),
        "name": golden.get("name"),
        "jr_quote_id": golden.get("jr_quote_id"),
        "target_totals": snapshot.get("target_totals") or golden.get("target_totals") or {},
        "target_bundles": snapshot.get("target_bundles") or [],
        "accepted_totals": snapshot.get("accepted_totals") or {},
        "tolerance": golden.get("tolerance") or snapshot.get("tolerance") or DEFAULT_TOLERANCE,
        "ruleset_version": golden.get("ruleset_version"),
        "source_fingerprint": golden.get("source_fingerprint"),
        "engine_fingerprint": golden.get("engine_fingerprint") or (snapshot.get("build") or {}).get("engine_fingerprint"),
        "artifact_manifest": golden.get("artifact_manifest") or snapshot.get("artifact_manifest") or [],
        "reviewer_name": golden.get("reviewer_name", ""),
        "notes": golden.get("notes"),
        "status": golden.get("status"),
        "created_at": golden.get("created_at"),
        "updated_at": golden.get("updated_at"),
    }


def _public_replay(replay: dict | None, include_generated: bool = False) -> dict | None:
    if not replay:
        return None
    result = {
        "id": replay.get("id"),
        "golden_job_id": replay.get("golden_job_id"),
        "golden_version_id": replay.get("golden_version_id"),
        "source_job_id": replay.get("source_job_id"),
        "mode": replay.get("mode"),
        "status": replay.get("status"),
        "summary": replay.get("summary") or {},
        "diff": replay.get("diff") or {},
        "audit_run_id": replay.get("audit_run_id"),
        "created_at": replay.get("created_at"),
    }
    if include_generated:
        result["generated_proposal"] = replay.get("generated_proposal") or {}
    return result


def _golden_replay_statuses(
    job_id: int,
    current_source_fingerprint: str | None = None,
    current_engine_fingerprint: str | None = None,
) -> dict:
    golden = get_golden_job_for_source(job_id)
    if not golden:
        return {
            "overall": None,
            "verification": None,
            "current": None,
            "current_drift_classification": None,
            "source_matches": None,
        }
    active_version_id = golden.get("version_id")
    baseline = get_latest_golden_replay_for_version(job_id, active_version_id, "baseline") if active_version_id else None
    current = get_latest_golden_replay_for_version(job_id, active_version_id, "current") if active_version_id else None
    if not baseline:
        verification = "not_replayed"
    else:
        summary = baseline.get("summary") or {}
        if baseline.get("status") == "pass" and summary.get("raw_engine_status", summary.get("engine_status")) == "pass":
            verification = "golden_verified"
        elif baseline.get("status") == "incomparable" or summary.get("status") == "incomparable":
            verification = "incomparable"
        else:
            verification = "fail"

    baseline_source_fingerprint = ((golden.get("snapshot") or {}).get("proposal_source_fingerprint") or "").strip()
    baseline_engine_fingerprint = (
        golden.get("engine_fingerprint")
        or ((golden.get("snapshot") or {}).get("build") or {}).get("engine_fingerprint")
        or ""
    ).strip()
    source_matches = None
    if baseline_source_fingerprint and current_source_fingerprint:
        source_matches = baseline_source_fingerprint == current_source_fingerprint
        if not source_matches:
            verification = "stale"
    engine_incomparable = (
        not baseline_engine_fingerprint
        or (current_engine_fingerprint and baseline_engine_fingerprint != current_engine_fingerprint)
    )
    if verification in ("golden_verified", "stale") and engine_incomparable:
        verification = "incomparable"
    elif verification == "golden_verified" and not baseline_source_fingerprint:
        verification = "incomparable"

    current_status = current.get("status") if current else None
    current_drift_classification = ((current or {}).get("summary") or {}).get("drift_classification")
    if verification == "stale":
        overall = "drift"
    elif verification != "golden_verified":
        overall = verification
    elif current_status == "warn" and current_drift_classification == "metadata_only":
        overall = "metadata_changed"
    elif current_status in ("warn", "fail", "incomparable"):
        overall = "drift"
    else:
        overall = "golden_verified"
    return {
        "overall": overall,
        "verification": verification,
        "current": current_status,
        "current_drift_classification": current_drift_classification,
        "source_matches": source_matches,
    }


def _golden_readiness_status(job_id: int) -> str | None:
    """Backward-compatible combined golden status for job list consumers."""
    job = load_job(job_id)
    proposal = (job or {}).get("proposal_data") if isinstance((job or {}).get("proposal_data"), dict) else {}
    fingerprint = _proposal_source_fingerprint(job, proposal) if job else None
    return _golden_replay_statuses(job_id, fingerprint, get_build_info().get("engine_fingerprint"))["overall"]


def _active_golden_replays(job_id: int, golden: dict | None, limit: int = 50) -> list[dict]:
    """Return replay evidence only for the currently active immutable version."""
    if not golden:
        return []
    active_version_id = golden.get("version_id")
    if not active_version_id:
        return []
    return list_golden_replays_for_version(job_id, active_version_id, limit=limit)


def _readiness_trust_summary(
    job: dict,
    *,
    proposal: dict,
    latest_run: dict | None,
    build: dict,
    ruleset_version: int | None,
) -> dict:
    golden = get_golden_job_for_source(job["id"])
    replays = _active_golden_replays(job["id"], golden, limit=50)
    active_version_id = (golden or {}).get("version_id")
    current_replay = get_latest_golden_replay_for_version(job["id"], active_version_id, "current") if active_version_id else None
    latest_replay = current_replay or (replays[0] if replays else None)

    deleted_reasons = proposal.get("deleted_material_reasons")
    if not isinstance(deleted_reasons, dict):
        deleted_reasons = {}
    deleted_codes = {
        str(code)
        for code in (proposal.get("deleted_material_codes") or [])
        if code and str(deleted_reasons.get(str(code)) or "").strip()
    }
    active_materials = [
        material for material in (job.get("materials") or [])
        if isinstance(material, dict) and _job_material_key(material) not in deleted_codes
    ]
    unknown_count = sum(
        1 for material in active_materials
        if not is_valid_material_classification(material.get("material_type"))
    )
    low_confidence_count = 0
    for material in active_materials:
        confidence = _as_number(material.get("ai_confidence"))
        price_source = str(material.get("price_source") or "").strip().lower()
        if (
            (confidence is not None and confidence < 0.75)
            or price_source in {"ai_estimate", "vendor_history"}
            or (_as_number(material.get("unit_price")) or 0) > 0 and not price_source
        ):
            low_confidence_count += 1

    # Typed prices are the normal path for lines with no configured price,
    # so they are counted separately from overrides of a vendor quote.
    manual_price_count = sum(
        1 for material in active_materials
        if str(material.get("price_source") or "").strip().lower() == "manual"
    )
    manual_override_count = sum(
        1 for material in active_materials
        if str(material.get("price_source") or "").strip().lower() == "vendor_quote_override"
    )
    for bundle in (proposal.get("bundles") or []):
        if not isinstance(bundle, dict):
            continue
        manual_override_count += int(bundle.get("price_override") is not None)
        manual_override_count += int(bundle.get("freight_override") is not None)
        manual_override_count += sum(
            1 for material in (bundle.get("materials") or [])
            if isinstance(material, dict) and material.get("freight_is_manual")
        )
        manual_override_count += sum(
            1 for sundry in (bundle.get("sundry_items") or [])
            if isinstance(sundry, dict) and sundry.get("is_manual_price")
        )
        manual_override_count += sum(
            1 for labor in (bundle.get("labor_items") or [])
            if isinstance(labor, dict) and (labor.get("is_manual") or labor.get("is_stair_labor"))
        )
        manual_override_count += len(bundle.get("deleted_labor_keys") or [])

    imported_receipts = list_imported_files(job["id"])
    verified_imports = [
        item for item in imported_receipts
        if _imported_artifact_is_verified(item)
    ]
    verified_vendor_hashes = {
        str(item.get("file_hash") or "").strip()
        for item in imported_receipts
        if _imported_artifact_is_verified(item, "vendor_quote")
    }
    vendor_quote_materials = [
        material for material in active_materials
        if str(material.get("price_source") or "").strip().lower() in _VENDOR_EVIDENCE_SOURCES
    ]
    valid_price_decisions = _active_price_decisions_for_materials(job["id"], active_materials)
    valid_price_decisions_by_material = {
        str(decision.get("material_id")): decision
        for decision in valid_price_decisions
    }
    verified_vendor_quote_materials = [
        material for material in vendor_quote_materials
        if str(material.get("quote_source_hash") or "").strip() in verified_vendor_hashes
        and (
            str(material.get("price_source") or "").strip().lower() == "vendor_quote"
            or str(material.get("id")) in valid_price_decisions_by_material
        )
    ]
    referenced_quote_files = {
        str(quote.get("file_name") or "").strip()
        for quote in (job.get("quotes") or [])
        if isinstance(quote, dict) and str(quote.get("file_name") or "").strip()
    }
    referenced_quote_files.update(
        str(material.get("quote_file_name") or "").strip()
        for material in vendor_quote_materials
        if str(material.get("quote_file_name") or "").strip()
    )
    quote_source_files_needed = sorted({
        str(item.get("file_name") or "").strip()
        for item in imported_receipts
        if str(item.get("file_name") or "").strip() in referenced_quote_files
        and not _imported_artifact_is_verified(item)
    })
    missing_vendor_receipt_count = len(vendor_quote_materials) - len(verified_vendor_quote_materials)
    vendor_price_conflicts = find_verified_quote_price_conflicts(
        active_materials,
        job.get("quotes") or [],
        verified_vendor_hashes,
    )
    vendor_price_overrides = [
        {
            "decision_id": decision.get("id"),
            "material_id": decision.get("material_id"),
            "item_code": decision.get("item_code") or "material",
            "accepted_price": _as_money_number(decision.get("resolved_price")),
            "accepted_unit": decision.get("material_unit"),
            "quote_price": _as_money_number(decision.get("quote_price")),
            "quote_unit": decision.get("quote_unit"),
            "delta": round(
                (_as_number(decision.get("quote_price")) or 0)
                - (_as_number(decision.get("resolved_price")) or 0),
                2,
            ),
            "source_hash": decision.get("source_hash"),
            "source_file": decision.get("source_file"),
            "reason": decision.get("reason"),
            "reviewer_name": decision.get("reviewer_name"),
            "created_at": decision.get("created_at"),
            "status": "accepted_override",
        }
        for decision in valid_price_decisions
        if str(decision.get("decision") or "").strip().lower() == "keep_accepted"
    ]

    artifact_receipts = list_job_artifacts(job["id"])
    pdf_receipt = next(
        (item for item in artifact_receipts if item.get("artifact_kind") == "proposal_pdf"),
        None,
    )
    replay_summary = (latest_replay or {}).get("summary") or {}
    replay_diff = (latest_replay or {}).get("diff") or {}
    replay_bundle_rows = replay_diff.get("jr_bundles") or replay_diff.get("bundles") or []
    largest_deltas = [
        {
            "bundle_name": row.get("bundle_name"),
            "delta": row.get("delta"),
            "status": row.get("status"),
            "target_source": row.get("target_source") or ("jr" if replay_diff.get("jr_bundles") else "accepted_proposal"),
        }
        for row in sorted(
            [row for row in replay_bundle_rows if isinstance(row, dict)],
            key=lambda row: abs(_as_number(row.get("delta")) or 0),
            reverse=True,
        )[:3]
    ]
    target_totals = ((golden or {}).get("snapshot") or {}).get("target_totals") or (golden or {}).get("target_totals") or {}

    return {
        "last_audit_at": (latest_run or {}).get("completed_at") or (latest_run or {}).get("started_at"),
        "last_pdf_at": proposal.get("pdf_generated_at") or (pdf_receipt or {}).get("created_at"),
        "ruleset_version": ruleset_version,
        "build_commit": build.get("commit"),
        "build_tag": build.get("tag"),
        "engine_fingerprint": build.get("engine_fingerprint"),
        "config_fingerprint": build.get("config_fingerprint"),
        "golden_baseline_version": (golden or {}).get("version_number"),
        "jr_target_total": _as_money_number(target_totals.get("grand_total")),
        "accepted_proposal_total": _as_money_number(proposal.get("grand_total")),
        "replay_total": _as_money_number((replay_summary.get("generated_totals") or {}).get("grand_total")),
        "replay_mode": (latest_replay or {}).get("mode"),
        "replay_status": (latest_replay or {}).get("status"),
        "largest_deltas": largest_deltas,
        "manual_override_count": manual_override_count,
        "manual_price_count": manual_price_count,
        "unknown_material_count": unknown_count,
        "low_confidence_material_count": low_confidence_count,
        "labor_catalog_count": len(get_labor_catalog_entries()),
        "artifact_count": len(artifact_receipts),
        "verified_source_count": len(verified_imports),
        "unverified_source_count": len(imported_receipts) - len(verified_imports),
        "vendor_quote_material_count": len(vendor_quote_materials),
        "verified_vendor_quote_material_count": len(verified_vendor_quote_materials),
        "missing_vendor_receipt_count": missing_vendor_receipt_count,
        "vendor_price_conflict_count": len(vendor_price_conflicts),
        "vendor_price_conflicts": vendor_price_conflicts[:20],
        "vendor_price_override_count": len(vendor_price_overrides),
        "vendor_price_overrides": vendor_price_overrides[:20],
        "quote_source_files_needed": quote_source_files_needed,
        "evidence_recovery_needed": bool(missing_vendor_receipt_count or quote_source_files_needed or vendor_price_conflicts),
        "vendor_source_mode": "browser_local_sync_folder",
        "vendor_source_automatic_sync": False,
        "vendor_source_requires_user_action": True,
        "vendor_source_status": (
            "blocked"
            if missing_vendor_receipt_count or quote_source_files_needed or vendor_price_conflicts
            else ("reviewed_overrides" if vendor_price_overrides else "verified")
        ),
        "source_fingerprint": proposal.get("audit_source_fingerprint"),
    }


def _evaluate_job_readiness(job: dict) -> dict:
    proposal = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    # The calculation the saved bid points to: a newer one nothing points to
    # (a Regenerate the editor didn't apply) left the bid as it was.
    latest_run = _proposal_run(job["id"], proposal)
    # A bid saved before an app update only needs the automatic recheck when
    # its PDF is made; this read never recalculates or writes anything.
    proposal_check = _proposal_check_status(job, proposal, latest_run)
    pdf_ready = False
    pdf_message = None
    latest_pdf = _latest_job_pdf(job["id"], "proposal_pdf")
    pdf_path = latest_pdf[0] if latest_pdf else ""
    if not pdf_path or not os.path.exists(pdf_path):
        pdf_message = PDF_NOT_MADE_YET
    else:
        try:
            _validate_proposal_pdf_download_ready(job)
            pdf_ready = True
        except HTTPException as exc:
            pdf_message = str(exc.detail)

    artifact_status, artifact_message, artifact_items = _artifact_readiness(
        job["id"],
        pdf_path,
        job.get("materials") or [],
    )
    proposal_source_ok = bool(proposal.get("bundles"))
    proposal_source_message = None
    if proposal_source_ok:
        try:
            _validate_proposal_body_matches_job_source(job, proposal)
        except HTTPException as exc:
            proposal_source_ok = False
            proposal_source_message = str(exc.detail)
    else:
        proposal_source_message = NO_BID_YET

    proposal_fingerprint = _proposal_source_fingerprint(job, proposal)
    build = get_build_info()
    ruleset_version = _current_ruleset_version()
    golden_statuses = _golden_replay_statuses(
        job["id"],
        proposal_fingerprint,
        build.get("engine_fingerprint"),
    )
    return evaluate_job_readiness(
        job,
        latest_run=latest_run,
        current_ruleset_version=ruleset_version,
        pdf_ready=pdf_ready,
        pdf_message=pdf_message,
        proposal_source_fingerprint=proposal_fingerprint,
        proposal_source_ok=proposal_source_ok,
        proposal_source_message=proposal_source_message,
        artifact_status=artifact_status,
        artifact_message=artifact_message,
        artifact_items=artifact_items,
        golden_status=golden_statuses["overall"],
        golden_verification_status=golden_statuses["verification"],
        current_replay_status=golden_statuses["current"],
        current_replay_drift_classification=golden_statuses["current_drift_classification"],
        labor_catalog_count=len(get_labor_catalog_entries()),
        labor_required_types=set(LABOR_RULES),
        build=build,
        proposal_check=proposal_check,
        trust_summary=_readiness_trust_summary(
            job,
            proposal=proposal,
            latest_run=latest_run,
            build=build,
            ruleset_version=ruleset_version,
        ),
    )


@app.get("/api/jobs/{job_id}/readiness")
def api_get_job_readiness(job_id: str):
    """Return non-mutating readiness checks for an estimator's current bid."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _evaluate_job_readiness(job)


@app.get("/api/jobs/{job_id}/reproducibility")
def api_get_job_reproducibility(job_id: str):
    """Return golden baseline and recent replay status for a job."""
    db_id = _resolve_job_id(job_id)
    golden = get_golden_job_for_source(db_id)
    replays = list_golden_replays_for_job(db_id, limit=50)
    active_replays = _active_golden_replays(db_id, golden, limit=50)
    latest_active = active_replays[0] if active_replays else None
    active_version_id = (golden or {}).get("version_id")
    baseline_replay = get_latest_golden_replay_for_version(db_id, active_version_id, "baseline") if active_version_id else None
    current_replay = get_latest_golden_replay_for_version(db_id, active_version_id, "current") if active_version_id else None
    job = load_job(db_id)
    proposal = (job or {}).get("proposal_data") if isinstance((job or {}).get("proposal_data"), dict) else {}
    source_fingerprint = _proposal_source_fingerprint(job, proposal) if job else None
    statuses = _golden_replay_statuses(
        db_id,
        source_fingerprint,
        get_build_info().get("engine_fingerprint"),
    )
    return {
        "golden_job": _public_golden_job(golden),
        "latest_replay": _public_replay(latest_active),
        "baseline_replay": _public_replay(baseline_replay),
        "current_replay": _public_replay(current_replay),
        "comparison_status": statuses["overall"] or ("not_replayed" if golden else "not_captured"),
        "current_drift_classification": statuses["current_drift_classification"],
        "live_source_matches_baseline": statuses["source_matches"],
        "replays": [_public_replay(replay) for replay in replays[:10]],
        "active_version_replays": [_public_replay(replay) for replay in active_replays[:10]],
        "accepted_bundles": _accepted_bundle_options(proposal),
        "default_tolerance": DEFAULT_TOLERANCE,
    }


def _golden_baseline_for_audit(conn, source_job_id):
    """A bid's golden baseline as the history shows it (the snapshot itself is too big)."""
    row = conn.execute(
        """SELECT g.id, g.jr_quote_id, g.target_totals_json, g.tolerance_json, g.ruleset_version,
                  g.source_fingerprint, g.notes, g.status, g.current_version_id,
                  v.version_number, v.reviewer_name
           FROM golden_jobs g LEFT JOIN golden_job_versions v ON v.id = g.current_version_id
           WHERE g.source_job_id=?""",
        (source_job_id,),
    ).fetchone()
    if not row:
        return None
    baseline = dict(row)
    for column, key in (("target_totals_json", "target_totals"), ("tolerance_json", "tolerance")):
        raw = baseline.pop(column, None)
        try:
            baseline[key] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            baseline[key] = raw
    return baseline


def _golden_replay_for_audit(conn, replay_id):
    row = conn.execute(
        """SELECT id, golden_job_id, golden_version_id, source_job_id, mode, status, audit_run_id
           FROM golden_job_replays WHERE id=?""",
        (replay_id,),
    ).fetchone()
    return dict(row) if row else None


def _golden_refusal(reason: str) -> str:
    """Why the golden baseline can't be captured, in the estimator's words."""
    return f"Can't capture the golden baseline yet. {reason}"


@app.post("/api/jobs/{job_id}/reproducibility/baseline")
@audit_route("golden.capture", "proposal.audit_refresh")
def api_capture_golden_baseline(job_id: str, body: GoldenBaselineRequest):
    """Capture the current accepted proposal as this job's golden baseline.

    A bid saved before an app update is rechecked first, as making its PDF
    does (_recheck_saved_proposal)."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not str(body.jr_quote_id or "").strip():
        raise HTTPException(status_code=400, detail="Enter the Job Runner quote ID before capturing the golden baseline.")
    if not str(body.reviewer_name or "").strip():
        raise HTTPException(status_code=400, detail="Enter the reviewer name before capturing the golden baseline.")

    missing = _required_job_field_gaps(job)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=_golden_refusal(
                f"Fill in the {plain_list([JOB_FIELD_LABELS.get(field, field) for field in missing])} on the job. "
                "Click Edit job details at the top of the page."
            ),
        )

    proposal_data = job.get("proposal_data")
    if not isinstance(proposal_data, dict) or not proposal_data.get("bundles"):
        raise HTTPException(status_code=409, detail=_golden_refusal(NO_BID_YET))
    nonpositive_bundles = [
        bundle.get("bundle_name") or "bundle"
        for bundle in proposal_data.get("bundles") or []
        if isinstance(bundle, dict) and (effective_bundle_total(bundle) <= 0)
    ]
    if nonpositive_bundles:
        one = len(nonpositive_bundles) == 1
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(
                f"{plain_list(nonpositive_bundles)} {'has' if one else 'have'} a $0 price. "
                f"Give {'it' if one else 'each one'} a price on {REVIEW_STEP}."
            ),
        )
    arithmetic_errors = proposal_math_errors(proposal_data)
    if arithmetic_errors:
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(f"Some numbers on the bid don't add up ({arithmetic_errors[0]}) {CLICK_REGENERATE}"),
        )
    try:
        _validate_proposal_body_matches_job_source(job, proposal_data)
    except HTTPException as exc:
        raise HTTPException(status_code=409, detail=_golden_refusal(str(exc.detail))) from exc

    # The same check as the page's "Before you send this bid" card.
    check_status = _proposal_check_status(job, proposal_data)
    if check_status["kind"] not in ("current", "tool_updated"):
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(f"{proposal_check_message(check_status)[1]} Then capture it again."),
        )

    raw_deleted_codes = {str(code) for code in (proposal_data.get("deleted_material_codes") or []) if code}
    deleted_reasons = proposal_data.get("deleted_material_reasons")
    if not isinstance(deleted_reasons, dict):
        deleted_reasons = {}
    deleted_codes = {
        code for code in raw_deleted_codes
        if str(deleted_reasons.get(code) or "").strip()
    }
    missing_deletion_reasons = sorted(raw_deleted_codes - deleted_codes)
    if missing_deletion_reasons:
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(f"Give a reason for each deleted material. Type it on each deleted line on {REVIEW_STEP}."),
        )
    deleted_bundle_names = {str(name) for name in (proposal_data.get("deleted_bundles") or []) if name}
    deleted_bundle_reasons = proposal_data.get("deleted_bundle_reasons")
    if not isinstance(deleted_bundle_reasons, dict):
        deleted_bundle_reasons = {}
    if any(not str(deleted_bundle_reasons.get(name) or "").strip() for name in deleted_bundle_names):
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(f"Give a reason for each deleted bundle on {REVIEW_STEP}."),
        )
    accepted_material_codes = {
        _job_material_key(material)
        for bundle in (proposal_data.get("bundles") or [])
        if isinstance(bundle, dict)
        for material in (bundle.get("materials") or [])
        if isinstance(material, dict) and _job_material_key(material)
    }
    contradictory_deleted_codes = sorted(raw_deleted_codes & accepted_material_codes)
    if contradictory_deleted_codes:
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(
                f"Some materials are deleted but still show on the bid. Click Regenerate on {REVIEW_STEP} to clean this up."
            ),
        )
    for bundle in proposal_data.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        deleted_labor_reasons = bundle.get("deleted_labor_reasons")
        if not isinstance(deleted_labor_reasons, dict):
            deleted_labor_reasons = {}
        if any(not str(deleted_labor_reasons.get(key) or "").strip() for key in (bundle.get("deleted_labor_keys") or [])):
            raise HTTPException(
                status_code=409,
                detail=_golden_refusal(f"Give a reason for each deleted labor line on {REVIEW_STEP}."),
            )
    active_materials = [
        material for material in (job.get("materials") or [])
        if isinstance(material, dict) and _job_material_key(material) not in deleted_codes
    ]
    missing_from_proposal = [
        material.get("item_code") or material.get("description") or "material"
        for material in active_materials
        if not _job_material_key(material)
        or _job_material_key(material) not in accepted_material_codes
    ]
    if missing_from_proposal:
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(
                f"{plain_list(missing_from_proposal)} {'is' if len(missing_from_proposal) == 1 else 'are'} in the "
                f"job's materials but not on the bid. Click Regenerate on {REVIEW_STEP} to add them, or delete "
                "them there with a reason."
            ),
        )
    unknown = [
        m.get("item_code") or m.get("description") or "material"
        for m in active_materials
        if not is_valid_material_classification(m.get("material_type"))
    ]
    unpriced = [m.get("item_code") or m.get("description") or "material" for m in active_materials if _as_number(m.get("unit_price")) is None or _as_number(m.get("unit_price")) <= 0]
    if unknown or unpriced:
        issues = []
        if unknown:
            issues.append(f"pick a type for {plain_list(unknown)}")
        if unpriced:
            issues.append(f"type a price for {plain_list(unpriced)}")
        todo = " and ".join(issues)
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(f"{todo[:1].upper()}{todo[1:]} on the Takeoff & Pricing step."),
        )

    if check_status["kind"] == "tool_updated":
        # Only the app (or its rates) changed since the bid was saved: recheck
        # it now, as making the PDF does, then capture the rechecked bid.
        job = _recheck_saved_proposal(job)
        proposal_data = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
        check_status = _proposal_check_status(job, proposal_data, preview=False)
        if check_status["kind"] not in ("current", "tool_updated"):
            raise HTTPException(
                status_code=409,
                detail=_golden_refusal(f"{proposal_check_message(check_status)[1]} Then capture it again."),
            )
    current_proposal_fingerprint = _proposal_source_fingerprint(job, proposal_data)

    # The calculation the saved bid points to (not a newer one nothing uses).
    run = _proposal_run(job["id"], proposal_data)
    proposal_audit = proposal_data.get("audit") if isinstance(proposal_data.get("audit"), dict) else {}
    try:
        audit_receipt_matches = bool(run) and int(proposal_audit.get("run_id")) == int(run["id"])
    except (TypeError, ValueError):
        audit_receipt_matches = False
    if not audit_receipt_matches:
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(
                f"This bid's numbers need to be saved again. Click Generate PDF on {REVIEW_STEP}, "
                "then capture it again."
            ),
        )
    _ensure_audit_calculator_current(run, label="Golden baseline")

    capture_trust = _readiness_trust_summary(
        job,
        proposal=proposal_data,
        latest_run=run,
        build=get_build_info(),
        ruleset_version=_current_ruleset_version(),
    )
    unresolved_vendor_evidence = (
        int(capture_trust.get("missing_vendor_receipt_count") or 0)
        + int(capture_trust.get("vendor_price_conflict_count") or 0)
        + len(capture_trust.get("quote_source_files_needed") or [])
    )
    if unresolved_vendor_evidence:
        raise HTTPException(
            status_code=409,
            detail=_golden_refusal(
                'Vendor quote prices need attention. Click Fix quote prices on the "Before you send this bid" '
                "card, then capture it again."
            ),
        )

    target_totals = {}
    for key, value in (body.target_totals or {}).items():
        if value in (None, ""):
            continue
        number = _as_money_number(value)
        if number is None or number < 0:
            raise HTTPException(status_code=400, detail=f"Job Runner total '{key}' must be a non-negative number.")
        target_totals[key] = number
    if target_totals.get("grand_total") is None or target_totals["grand_total"] <= 0:
        raise HTTPException(status_code=400, detail="Enter a positive Job Runner grand total before capturing the golden baseline.")
    target_bundles = _validated_jr_bundle_targets(body.target_bundles, proposal_data)

    raw_tolerance = body.tolerance or {}
    unknown_tolerance_fields = sorted(set(raw_tolerance) - set(DEFAULT_TOLERANCE))
    if unknown_tolerance_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tolerance field(s): {', '.join(unknown_tolerance_fields)}.",
        )
    tolerance = dict(DEFAULT_TOLERANCE)
    for key, value in raw_tolerance.items():
        number = _as_number(value)
        if number is None or number < 0:
            raise HTTPException(status_code=400, detail=f"Tolerance '{key}' must be a non-negative number.")
        tolerance[key] = number
    for scope in ("proposal", "bundle"):
        if tolerance[f"{scope}_warn_abs"] < tolerance[f"{scope}_pass_abs"]:
            raise HTTPException(
                status_code=400,
                detail=f"{scope.title()} warning tolerance must be at least its pass tolerance.",
            )

    ruleset = _ruleset_with_engine_contract(get_ruleset_version())
    config_snapshot = {
        "waste_factors": WASTE_FACTORS,
        "sundry_rules": SUNDRY_RULES,
        "freight_rates": FREIGHT_RATES,
        "labor_qty_rules": LABOR_QTY_RULES,
        "stair_sundry_kits": STAIR_SUNDRY_KITS,
    }
    snapshot, fingerprint = make_golden_snapshot(
        job=job,
        company_rates=get_all_company_rates(),
        labor_catalog=get_labor_catalog_entries(),
        ruleset=ruleset,
        target_totals=target_totals,
        target_bundles=target_bundles,
        tolerance=tolerance,
        build=build_manifest_for_snapshot(),
        artifact_manifest=_job_artifact_manifest(job["id"]),
        config_snapshot=config_snapshot,
        proposal_source_fingerprint=current_proposal_fingerprint,
    )
    engine_fingerprint = build_manifest_for_snapshot().get("engine_fingerprint", "")
    artifact_manifest = _job_artifact_manifest(job["id"])
    with entity_write("golden_job", job["id"], _golden_baseline_for_audit, "golden.capture",
                      summary="Captured golden reproducibility baseline", job_id=job["id"]) as tx:
        golden = upsert_golden_job(
            source_job_id=job["id"],
            name=job.get("project_name") or f"Job {job['id']}",
            jr_quote_id=body.jr_quote_id or "",
            target_totals=target_totals,
            tolerance=snapshot.get("tolerance") or DEFAULT_TOLERANCE,
            snapshot=snapshot,
            ruleset_version=(ruleset or {}).get("version"),
            source_fingerprint=fingerprint,
            notes=body.notes or "",
            reviewer_name=body.reviewer_name or "",
            engine_fingerprint=engine_fingerprint,
            artifact_manifest=artifact_manifest,
            rules_registry_snapshot=ruleset or {},
            config_snapshot=config_snapshot,
            status="active",
            conn=tx.conn,
        )
        tx.force_record()  # a re-capture of identical figures is still a new baseline version
        log_activity(
            job["id"],
            "golden_baseline_captured",
            "Captured golden reproducibility baseline",
            {"golden_job_id": golden["id"], "jr_quote_id": body.jr_quote_id, "source_fingerprint": fingerprint},
        )
    return {
        "golden_job": _public_golden_job(golden),
        "latest_replay": None,
        "baseline_replay": None,
        "current_replay": None,
        "comparison_status": "not_replayed",
        "current_drift_classification": None,
        "replays": [],
        "active_version_replays": [],
        "accepted_bundles": _accepted_bundle_options(proposal_data),
        "default_tolerance": DEFAULT_TOLERANCE,
    }


@app.post("/api/jobs/{job_id}/reproducibility/replay")
@audit_route("golden.replay")
def api_replay_golden_job(job_id: str, body: GoldenReplayRequest):
    """Run a non-mutating golden replay and persist the replay report."""
    db_id = _resolve_job_id(job_id)
    golden = get_golden_job_for_source(db_id)
    if not golden:
        raise HTTPException(status_code=404, detail="No golden baseline exists for this job yet.")

    mode = (body.mode or "baseline").lower().strip()
    if mode not in ("baseline", "current"):
        raise HTTPException(status_code=400, detail="Replay mode must be 'baseline' or 'current'.")

    result, trace = replay_golden_job(
        golden_job=golden,
        mode=mode,
        current_company_rates=get_all_company_rates(),
        current_labor_catalog=get_labor_catalog_entries(),
        current_ruleset=_ruleset_with_engine_contract(get_ruleset_version()),
        current_config_snapshot={
            "waste_factors": WASTE_FACTORS,
            "sundry_rules": SUNDRY_RULES,
            "freight_rates": FREIGHT_RATES,
            "labor_qty_rules": LABOR_QTY_RULES,
            "stair_sundry_kits": STAIR_SUNDRY_KITS,
        },
    )
    run_id = create_calculation_run(
        db_id,
        "golden_replay",
        source="system",
        metadata=_audit_metadata({
            "endpoint": "reproducibility/replay",
            "golden_job_id": golden["id"],
            "golden_version_id": golden.get("version_id"),
            "mode": mode,
            "status": result["summary"]["status"],
            "source_fingerprint": golden.get("source_fingerprint"),
        }),
    )
    for record in trace._records:
        record["run_id"] = run_id
    trace_count = save_calculation_traces(db_id, run_id, trace.records)
    summary = dict(result["summary"])
    summary["trace_count"] = trace_count
    complete_calculation_run(run_id, summary=summary)

    activity_summary = f"Golden replay {mode} finished: {summary['status'].upper()}"
    with entity_write("golden_replay", None, _golden_replay_for_audit, "golden.replay",
                      summary=activity_summary, job_id=db_id) as tx:
        replay = save_golden_replay(
            golden_job_id=golden["id"],
            source_job_id=db_id,
            mode=mode,
            status=summary["status"],
            summary=summary,
            diff=result["diff"],
            generated_proposal=result["proposal"],
            audit_run_id=run_id,
            golden_version_id=golden.get("version_id"),
            conn=tx.conn,
        )
        tx.entity_id = replay["id"]
        log_activity(
            db_id,
            "golden_replay_ran",
            activity_summary,
            {"golden_job_id": golden["id"], "replay_id": replay["id"], "mode": mode, "status": summary["status"]},
        )
    return _public_replay(replay, include_generated=False)


@app.get("/api/reproducibility/replays/{replay_id}")
def api_get_golden_replay(replay_id: int):
    """Return a full golden replay report."""
    replay = get_golden_replay(replay_id)
    if not replay:
        raise HTTPException(status_code=404, detail="Replay not found")
    return _public_replay(replay, include_generated=True)


def _as_number(value):
    try:
        if value is None or value == "":
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return round(number, 4)
    except (TypeError, ValueError):
        return None


def _as_money_number(value):
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    return _as_number(value)


def _job_material_key(material: dict) -> str:
    return str(
        material.get("item_code")
        or material.get("id")
        or material.get("material_id")
        or ""
    )


def _audit_metadata(extra: dict = None) -> dict:
    """Attach visible rules metadata and the calculator identity to an audit."""
    metadata = dict(extra or {})
    build = get_build_info()
    metadata.update({
        "engine_fingerprint": build.get("engine_fingerprint"),
        "config_fingerprint": build.get("config_fingerprint"),
        **_calculator_data_fingerprints(),
    })
    ruleset = get_ruleset_version()
    if ruleset:
        metadata.update({
            "ruleset_version": ruleset.get("version"),
            "ruleset_rule_count": ruleset.get("rule_count"),
            "ruleset_active_count": ruleset.get("active_count"),
            "ruleset_created_at": ruleset.get("created_at"),
        })
    return metadata


def _current_ruleset_version() -> int | None:
    ruleset = get_ruleset_version()
    return ruleset.get("version") if ruleset else None


def _ensure_audit_calculator_current(run: dict | None, *, label: str) -> None:
    """Require proof from the running calculator, not a metadata-only rules edit."""
    build = get_build_info()
    metadata = (run or {}).get("metadata") or {}
    expected_engine = build.get("engine_fingerprint")
    expected_config = build.get("config_fingerprint")
    run_engine = metadata.get("engine_fingerprint")
    run_config = metadata.get("config_fingerprint")
    if not run_engine or not run_config or run_engine != expected_engine or run_config != expected_config:
        # ``label`` names the caller for logs only; estimators get one plain fix.
        raise HTTPException(
            status_code=409,
            detail=f"This bid was last saved with an older version of the app. {CLICK_REGENERATE}",
        )


# What a saved calculation was made with: the app version (engine/config) and
# the rates and labor prices edited in the app. A deploy or a rate edit changes
# these without changing the bid itself.
_CALCULATOR_IDENTITY_KEYS = (
    "engine_fingerprint", "config_fingerprint",
    "company_rates_fingerprint", "labor_catalog_fingerprint",
)


def _current_calculator_identity() -> dict:
    build = get_build_info()
    return {
        "engine_fingerprint": build.get("engine_fingerprint"),
        "config_fingerprint": build.get("config_fingerprint"),
        **_calculator_data_fingerprints(),
    }


def _run_calculator_identity(run: dict | None) -> dict | None:
    """The identity a calculation run was made with, or None when the run
    predates app-version fingerprints (it can't be recreated then). Rates and
    labor fingerprints missing from an older run count as unchanged."""
    metadata = (run or {}).get("metadata") or {}
    if not metadata.get("engine_fingerprint") or not metadata.get("config_fingerprint"):
        return None
    current = None
    identity = {}
    for key in _CALCULATOR_IDENTITY_KEYS:
        value = metadata.get(key)
        if not value:
            current = current or _current_calculator_identity()
            value = current.get(key)
        identity[key] = value
    return identity


def _fingerprint_payload(payload) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _materials_source_fingerprint(materials: list[dict]) -> str:
    """Fingerprint only durable material fields used by pricing and calculation."""
    fields = (
        "id", "item_code", "description", "material_type", "installed_qty", "unit",
        "waste_pct", "order_qty", "vendor", "unit_price", "extended_cost",
        "ai_confidence", "quote_status", "price_source", "quote_source_hash",
        "quote_file_name", "freight_per_unit", "freight_source", "fixture_count",
        "labor_rate_lf", "labor_catalog",
        "tack_strip_lf", "seam_tape_lf", "pad_sy", "area_type", "is_mosaic",
        "is_penny_hex", "crack_isolation_sf", "weld_rod_lf",
    )
    return _fingerprint_payload([
        {field: material.get(field) for field in fields}
        for material in materials
        if isinstance(material, dict)
    ])


def _calculator_data_fingerprints() -> dict:
    """Fingerprint mutable rate inputs that live outside the source job."""
    return {
        "company_rates_fingerprint": _fingerprint_payload(get_all_company_rates()),
        "labor_catalog_fingerprint": _fingerprint_payload(get_labor_catalog_entries()),
    }


def _job_source_snapshot(job: dict) -> dict:
    return {
        "project_name": job.get("project_name"),
        "gc_name": job.get("gc_name"),
        "address": job.get("address"),
        "city": job.get("city"),
        "state": job.get("state"),
        "zip": job.get("zip"),
        "tax_rate": job.get("tax_rate", 0),
        "gpm_pct": job.get("gpm_pct", 0),
        "markup_pct": job.get("markup_pct", 0),
        "unit_count": job.get("unit_count", 0),
        "tub_shower_count": job.get("tub_shower_count", 0),
        "salesperson": job.get("salesperson"),
        "exclusions": job.get("exclusions"),
        "textura_fee": job.get("textura_fee", 0),
    }


def _line_snapshot(items: list[dict], fields: tuple[str, ...]) -> list[dict]:
    rows = []
    for item in items or []:
        if isinstance(item, dict):
            rows.append({field: item.get(field) for field in fields})
    return rows


def _bid_source_fingerprint(job: dict, *, identity: dict | None = None) -> str:
    """``identity`` recreates the fingerprint as an older app version or older
    rates made it (see _run_calculator_identity); default is the running app."""
    build, data_fingerprints = _fingerprint_identity_parts(identity)
    return _fingerprint_payload({
        "fingerprint_schema": 4,
        "job": _job_source_snapshot(job),
        "materials": _line_snapshot(job.get("materials", []), (
            "id", "item_code", "description", "material_type", "installed_qty",
            "unit", "waste_pct", "order_qty", "unit_price", "extended_cost",
            "vendor", "price_source", "quote_status", "ai_confidence",
            "quote_source_hash", "quote_file_name", "freight_per_unit", "freight_source",
            "fixture_count", "labor_rate_lf", "labor_catalog", "tack_strip_lf",
            "seam_tape_lf", "pad_sy", "area_type",
            "is_mosaic", "is_penny_hex", "crack_isolation_sf", "weld_rod_lf",
        )),
        "sundries": _line_snapshot(job.get("sundries", []), (
            "id", "material_id", "sundry_name", "qty", "unit", "unit_price",
            "extended_cost", "freight_cost",
        )),
        "labor": _line_snapshot(job.get("labor", []), (
            "id", "material_id", "labor_description", "qty", "unit", "rate", "extended_cost",
        )),
        "material_price_decisions": _line_snapshot(job.get("material_price_decisions", []), (
            "id", "material_id", "item_code", "decision", "accepted_price_before",
            "resolved_price", "material_unit", "quote_price", "quote_unit",
            "source_hash", "source_file", "reason", "reviewer_name", "created_at",
        )),
        "engine_fingerprint": build.get("engine_fingerprint"),
        "config_fingerprint": build.get("config_fingerprint"),
        **data_fingerprints,
    })


def _fingerprint_identity_parts(identity: dict | None) -> tuple[dict, dict]:
    if identity is None:
        return get_build_info(), _calculator_data_fingerprints()
    return (
        {"engine_fingerprint": identity.get("engine_fingerprint"), "config_fingerprint": identity.get("config_fingerprint")},
        {
            "company_rates_fingerprint": identity.get("company_rates_fingerprint"),
            "labor_catalog_fingerprint": identity.get("labor_catalog_fingerprint"),
        },
    )


def _proposal_source_fingerprint(job: dict, proposal_data: dict | None = None, *, identity: dict | None = None) -> str:
    """``identity``: as for _bid_source_fingerprint."""
    proposal_data = proposal_data if isinstance(proposal_data, dict) else (job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {})
    build, data_fingerprints = _fingerprint_identity_parts(identity)
    return _fingerprint_payload({
        "fingerprint_schema": 4,
        "job": _job_source_snapshot(job),
        "materials": _line_snapshot(job.get("materials", []), (
            "id", "item_code", "description", "material_type", "installed_qty",
            "unit", "waste_pct", "order_qty", "unit_price", "extended_cost",
            "vendor", "price_source", "quote_status", "ai_confidence",
            "quote_source_hash", "quote_file_name", "freight_per_unit", "freight_source",
            "fixture_count", "labor_rate_lf", "labor_catalog", "tack_strip_lf",
            "seam_tape_lf", "pad_sy", "area_type",
            "is_mosaic", "is_penny_hex", "crack_isolation_sf", "weld_rod_lf",
        )),
        "proposal": {
            # Uids, line keys and row bookkeeping say which bundle or line is
            # which, not what the proposal says: they don't change the fingerprint.
            "bundles": stable_ids.without_identity(proposal_data.get("bundles", [])),
            "notes": proposal_data.get("notes", []),
            "terms": proposal_data.get("terms", []),
            "exclusions": proposal_data.get("exclusions", []),
            "tax_rate": proposal_data.get("tax_rate", 0),
            "gpm_pct": proposal_data.get("gpm_pct", 0),
            "textura_fee": proposal_data.get("textura_fee", 0),
            "subtotal": proposal_data.get("subtotal", 0),
            "tax_amount": proposal_data.get("tax_amount", 0),
            "grand_total": proposal_data.get("grand_total", 0),
            "gpm_profit": proposal_data.get("gpm_profit", 0),
            "gpm_labor": proposal_data.get("gpm_labor", 0),
            "gpm_material": proposal_data.get("gpm_material", 0),
            "manual_adjustment": proposal_data.get("manual_adjustment", 0),
            "textura_amount": proposal_data.get("textura_amount", 0),
            "deleted_bundles": proposal_data.get("deleted_bundles", []),
            "deleted_bundle_reasons": proposal_data.get("deleted_bundle_reasons", {}),
            "deleted_material_codes": proposal_data.get("deleted_material_codes", []),
            "deleted_material_reasons": proposal_data.get("deleted_material_reasons", {}),
        },
        "sundries": _line_snapshot(job.get("sundries", []), (
            "id", "material_id", "sundry_name", "qty", "unit", "unit_price",
            "extended_cost", "freight_cost",
        )),
        "labor": _line_snapshot(job.get("labor", []), (
            "id", "material_id", "labor_description", "qty", "unit", "rate", "extended_cost",
        )),
        "material_price_decisions": _line_snapshot(job.get("material_price_decisions", []), (
            "id", "material_id", "item_code", "decision", "accepted_price_before",
            "resolved_price", "material_unit", "quote_price", "quote_unit",
            "source_hash", "source_file", "reason", "reviewer_name", "created_at",
        )),
        "engine_fingerprint": build.get("engine_fingerprint"),
        "config_fingerprint": build.get("config_fingerprint"),
        **data_fingerprints,
    })


def _latest_completed_run(job_id: int, run_types: set[str]) -> dict | None:
    return get_latest_completed_calculation_run(job_id, run_types)


def _completed_run_by_id(job_id: int, run_id) -> dict | None:
    """One of the job's completed calculation runs, with its metadata."""
    try:
        run_id = int(run_id)
    except (TypeError, ValueError):
        return None
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM calculation_runs WHERE id=? AND job_id=? AND status='completed'",
            (run_id, int(job_id)),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    run = dict(row)
    for src, dest in (("metadata_json", "metadata"), ("summary_json", "summary")):
        raw = run.pop(src, None)
        try:
            run[dest] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            run[dest] = raw
    return run


def _proposal_run(job_id: int, proposal: dict | None) -> dict | None:
    """The calculation the saved bid's numbers come from (its audit run). A
    newer run nothing points to (a Regenerate the editor didn't apply, a
    recheck that lost a race) left the bid as it was, so it isn't the bid's.
    A bid saved without an audit run falls back to the job's latest run."""
    audit_info = (proposal or {}).get("audit")
    run = _completed_run_by_id(job_id, audit_info.get("run_id")) if isinstance(audit_info, dict) else None
    return run or _latest_completed_run(job_id, _PROPOSAL_RUN_TYPES)


# ── What the job said when the bid was made ──────────────────────────────────
# Job details the PDF prints in its header. The PDF reads them from the job
# when it is made, so changing one never changes a number on the bid.
_PRINT_ONLY_JOB_FIELDS = ("project_name", "gc_name", "address", "city", "state", "zip", "salesperson", "exclusions")
_PRINT_ONLY_WORDS = {
    "project_name": "project name", "gc_name": "general contractor", "address": "address",
    "city": "city", "state": "state", "zip": "ZIP code", "salesperson": "salesperson",
    "exclusions": "exclusions",
}
# Job details the bid's numbers are made from. The bid keeps its own tax rate,
# GPM and Textura fee (typed on the Review & Generate step; Regenerate keeps
# them); the counts and the sundry and labor lines reach it through Regenerate.
_BID_OWN_JOB_FIELDS = ("tax_rate", "gpm_pct", "textura_fee")
_REGENERATE_JOB_FIELDS = ("unit_count", "tub_shower_count", "markup_pct")
_SOURCE_SUNDRY_FIELDS = ("material_id", "sundry_name", "qty", "unit", "unit_price", "extended_cost", "freight_cost")
_SOURCE_LABOR_FIELDS = ("material_id", "labor_description", "qty", "unit", "rate", "extended_cost")


def _bid_source_job(job: dict, *, run_id=None, guessed: bool = False) -> dict:
    """The job values a bid's numbers are made from. Saved on the proposal as
    ``source_job`` when a generation makes the numbers, carried by later saves,
    and compared with the job by _proposal_check_status."""
    source = {field: job.get(field) or 0 for field in (*_BID_OWN_JOB_FIELDS, *_REGENERATE_JOB_FIELDS)}
    source["sundries"] = _fingerprint_payload(_line_snapshot(job.get("sundries", []), _SOURCE_SUNDRY_FIELDS))
    source["labor"] = _fingerprint_payload(_line_snapshot(job.get("labor", []), _SOURCE_LABOR_FIELDS))
    source["run_id"] = run_id
    if guessed:
        # Saved before bids kept this: see _legacy_source_job.
        source["guessed"] = True
    return source


def _is_source_job(value) -> bool:
    return isinstance(value, dict) and bool(value.get("sundries")) and bool(value.get("labor"))


def _same_job_input(left, right) -> bool:
    return abs((_as_number(left) or 0) - (_as_number(right) or 0)) < 1e-9


def _legacy_source_job(job: dict, proposal: dict, *, unchanged: bool) -> dict:
    """``source_job`` for a bid saved before bids kept one: the job as it is
    now, except that when the job may have changed since the bid was saved
    (``unchanged`` false) its tax rate, GPM and Textura fee are taken to have
    been the bid's own (``guessed``: only the difference is known). Earlier
    changes to the counts or the sundry and labor lines can't be told."""
    source = _bid_source_job(job, guessed=not unchanged)
    if not unchanged:
        for field in _BID_OWN_JOB_FIELDS:
            source[field] = proposal.get(field) or 0
    return source


def _stored_fingerprint_holds(job: dict, proposal: dict, run: dict | None) -> bool:
    """True when nothing but the app, its rates or the details only the PDF
    prints changed since the bid's fingerprint was saved."""
    stored = proposal.get("audit_source_fingerprint")
    if not stored:
        return False
    stamped = proposal.get("audit_source_job")
    as_saved = {**job, **stamped} if isinstance(stamped, dict) else job
    current_identity = _current_calculator_identity()
    if stored == _proposal_source_fingerprint(as_saved, proposal, identity=current_identity):
        return True
    run_identity = _run_calculator_identity(run)
    return bool(
        run_identity is not None and run_identity != current_identity
        and stored == _proposal_source_fingerprint(as_saved, proposal, identity=run_identity)
    )


def _proposal_source_job(job: dict, proposal: dict, run: dict | None = None) -> dict:
    """The saved bid's ``source_job`` (a copy), or the estimate for an older bid."""
    if _is_source_job(proposal.get("source_job")):
        return copy.deepcopy(proposal["source_job"])
    if run is None:
        run = _proposal_run(job["id"], proposal)
    return _legacy_source_job(job, proposal, unchanged=_stored_fingerprint_holds(job, proposal, run))


def _job_changes_since_bid(job: dict, proposal: dict, source_job: dict) -> list[dict]:
    """What changed in the job since the bid's numbers were made from it and
    isn't on the bid yet. A tax rate, GPM or Textura fee the bid already uses
    is fine (the estimator typed it on the Review & Generate step)."""
    changes = []
    for field in _REGENERATE_JOB_FIELDS:
        before, after = source_job.get(field), job.get(field) or 0
        if not _same_job_input(before, after):
            changes.append({"field": field, "before": before, "after": after, "fix": "regenerate"})
    current = _bid_source_job(job)
    for part in ("sundries", "labor"):
        if source_job.get(part) and source_job.get(part) != current[part]:
            changes.append({"field": part, "fix": "regenerate"})
    for field in _BID_OWN_JOB_FIELDS:
        before, after, bid = source_job.get(field), job.get(field) or 0, proposal.get(field) or 0
        if not _same_job_input(before, after) and not _same_job_input(bid, after):
            changes.append({"field": field, "before": before, "after": after, "bid": bid, "fix": "bid"})
    return changes


def _saved_source_job(job: dict, previous: dict, body: dict) -> dict:
    """``source_job`` for a proposal save. The editor sends back the one from a
    Regenerate it applied; it is taken from that generation's run (only a newer
    generation than the saved one), so an old tab can't bring back an older
    one. Otherwise the saved bid's is kept. A tax rate, GPM or Textura fee the
    estimator changes in this save takes the job's value as it is now: they
    chose the bid's value with the job in front of them."""
    previous = previous if isinstance(previous, dict) else {}
    prior = previous.get("source_job") if _is_source_job(previous.get("source_job")) else None
    source = None
    incoming = body.get("source_job") if isinstance(body.get("source_job"), dict) else {}
    incoming_run = _as_number(incoming.get("run_id"))
    prior_run = _as_number((prior or {}).get("run_id"))
    if incoming_run is not None and (prior_run is None or incoming_run > prior_run):
        run = _completed_run_by_id(job["id"], incoming_run)
        made = ((run or {}).get("metadata") or {}).get("source_job")
        if run and run.get("run_type") == "proposal_generation" and _is_source_job(made):
            source = {**made, "run_id": int(incoming_run)}
    if source is None:
        if prior:
            source = copy.deepcopy(prior)
        elif previous.get("bundles"):
            source = _proposal_source_job(job, previous)
        else:
            source = _bid_source_job(job)  # the first save: made from the job as it is now
    if previous.get("bundles"):
        for field in _BID_OWN_JOB_FIELDS:
            if not _same_job_input(body.get(field), previous.get(field)):
                source[field] = job.get(field) or 0
    return source


def _stamp_proposal_source(job: dict, proposal: dict, *, source_job: dict | None = None) -> None:
    """Record on a proposal about to be saved what it was checked against: the
    job details now and the fingerprint, and ``source_job`` when given (else
    the proposal keeps its own)."""
    if source_job is not None:
        proposal["source_job"] = source_job
    proposal["audit_source_job"] = _job_source_snapshot(job)
    proposal["audit_source_fingerprint"] = _proposal_source_fingerprint(job, proposal)


def _print_details_changed(job: dict, stamped) -> list[str]:
    """Plain words for the header details the PDF prints that differ from
    ``stamped`` (the job details saved with the proposal)."""
    if not isinstance(stamped, dict):
        return []
    now = _job_source_snapshot(job)
    return [
        _PRINT_ONLY_WORDS[field] for field in _PRINT_ONLY_JOB_FIELDS
        if str(stamped.get(field) or "").strip() != str(now.get(field) or "").strip()
    ]


# ── Saved bid numbers check after an app update ──────────────────────────────
# Every deploy (and every rate or labor price edit) changes what the saved
# calculations were made with, even though the bid itself didn't change. Such
# a bid is rechecked automatically with the running app when its PDF is made
# (_recheck_saved_proposal); only a recheck that changes the numbers, or a job
# that really changed, needs the estimator.
_PROPOSAL_RUN_TYPES = {"proposal_editor_save", "proposal_generation"}
_RECHECK_TOTAL_FIELDS = (
    "subtotal", "tax_amount", "grand_total", "gpm_profit", "gpm_labor",
    "gpm_material", "manual_adjustment", "textura_amount",
)
_RECHECK_BUNDLE_FIELDS = (
    "material_cost", "sundry_cost", "labor_cost", "freight_cost", "gpm_labor_adder",
    "gpm_material_adder", "gpm_adder", "taxable", "tax_amount", "total_price",
)
_RECHECK_SUMMARY = "Rechecked the bid's numbers with the latest version of the tool"


def _cents(value) -> int:
    return int(round((_as_money_number(value) or 0) * 100))


def _printed_bundle_amounts(bundle: dict) -> dict:
    """The bundle amounts the PDF prints (typed overrides win)."""
    amounts = {field: bundle.get(field) for field in _RECHECK_BUNDLE_FIELDS}
    if bundle.get("freight_override") is not None:
        amounts["freight_cost"] = bundle.get("freight_override")
    if bundle.get("price_override") is not None:
        amounts["total_price"] = bundle.get("price_override")
    return amounts


def _proposal_recheck(proposal: dict) -> dict:
    """Recalculate a saved bid's totals with the running app. Writes nothing.

    ``changed`` is true when any printed amount would move by a cent or more.
    """
    recomputed = copy.deepcopy(proposal)
    normalize_proposal_totals(recomputed)
    changes = [
        amount_word(field) for field in _RECHECK_TOTAL_FIELDS
        if _cents(proposal.get(field)) != _cents(recomputed.get(field))
    ]
    old_bundles = [bundle for bundle in (proposal.get("bundles") or []) if isinstance(bundle, dict)]
    new_bundles = [bundle for bundle in (recomputed.get("bundles") or []) if isinstance(bundle, dict)]
    for index, (old, new) in enumerate(zip(old_bundles, new_bundles)):
        before, after = _printed_bundle_amounts(old), _printed_bundle_amounts(new)
        name = old.get("bundle_name") or f"Bundle {index + 1}"
        changes.extend(
            f"{name} {amount_word(field)}" for field in _RECHECK_BUNDLE_FIELDS
            if _cents(before[field]) != _cents(after[field])
        )
    return {
        "recomputed": recomputed,
        "changed": bool(changes),
        "changes": changes,
        "old_total": _as_money_number(proposal.get("grand_total")) or 0,
        "new_total": _as_money_number(recomputed.get("grand_total")) or 0,
    }


def _proposal_check_status(job: dict, proposal: dict | None = None, run: dict | None = None,
                           *, preview: bool = True) -> dict:
    """Whether the saved bid's numbers check is current. Writes nothing.

    ``kind``: "current"; "tool_updated" (only the app, its rates or its labor
    prices changed since the bid was saved: rechecked automatically when the
    PDF is made); "totals_changed" (that recheck would change the numbers:
    ``old_total``/``new_total``, only with ``preview``); "job_changed" (with
    ``changes`` from _job_changes_since_bid, or ``detail`` naming a changed
    material); "not_saved"; or "no_proposal". ``run`` defaults to the run the
    saved bid points to (_proposal_run).

    Details only the PDF prints (address, salesperson, ...) are read from the
    job when the PDF is made: changing them doesn't change the bid.
    """
    if proposal is None:
        proposal = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    if not proposal.get("bundles"):
        return {"kind": "no_proposal"}
    if run is None:
        run = _proposal_run(job["id"], proposal)
    if not run:
        return {"kind": "not_saved"}
    fingerprint_holds = _stored_fingerprint_holds(job, proposal, run)
    if _is_source_job(proposal.get("source_job")):
        source_job = proposal["source_job"]
    else:
        source_job = _legacy_source_job(job, proposal, unchanged=fingerprint_holds)
    changes = _job_changes_since_bid(job, proposal, source_job)
    if changes or not fingerprint_holds:
        # A changed material the bid copies is named first (recalculating the
        # materials also redoes the sundry and labor lines). Anything else
        # that isn't in ``changes`` is a detail only the PDF prints or a price
        # decision: neither moves a number.
        try:
            _validate_proposal_body_matches_job_source(job, proposal)
        except HTTPException as exc:
            return {"kind": "job_changed", "detail": str(exc.detail)}
    if changes:
        return {"kind": "job_changed", "changes": changes, "guessed": bool(source_job.get("guessed"))}
    run_identity = _run_calculator_identity(run)
    if run_identity is not None and run_identity == _current_calculator_identity():
        return {"kind": "current"}
    if preview:
        recheck = _proposal_recheck(proposal)
        if recheck["changed"]:
            return {
                "kind": "totals_changed",
                "old_total": recheck["old_total"],
                "new_total": recheck["new_total"],
                "changes": recheck["changes"],
            }
    return {"kind": "tool_updated"}


def _recheck_saved_proposal(job: dict) -> dict:
    """Recheck a saved bid's numbers with the running app and save the result.

    Only for a bid whose job and proposal didn't change since it was saved
    (see _proposal_check_status "tool_updated"). Records the same audit a
    proposal save records, for the saved proposal, as a system recheck by the
    requesting user. Raises 409 naming the old and new total when the numbers
    would change. Returns the reloaded job.
    """
    saved = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    recheck = _proposal_recheck(saved)
    if recheck["changed"]:
        raise HTTPException(status_code=409, detail=totals_changed_message(recheck["old_total"], recheck["new_total"]))
    try:
        _validate_proposal_pdf_download_ready(job)
        pdf_was_current = True
    except HTTPException:
        pdf_was_current = False
    audit_result = _record_proposal_editor_audit(
        job["id"], saved, recheck["recomputed"], endpoint="proposal/audit-refresh", source="system",
    )
    audit_trace = audit_result.get("audit_trace")
    if not audit_trace:
        raise HTTPException(status_code=409, detail=f"This bid's numbers couldn't be rechecked. {CLICK_REGENERATE}")
    refreshed = copy.deepcopy(saved)
    refreshed["audit"] = {
        "run_id": audit_trace["run"]["id"],
        "trace_count": audit_result["trace_count"],
        "summary": audit_trace.get("audit", {}),
    }
    _stamp_proposal_source(job, refreshed, source_job=_proposal_source_job(job, saved))
    if pdf_was_current:
        # No number moved, so the PDF made from the bid still prints it.
        refreshed["pdf_audit_run_id"] = audit_trace["run"]["id"]
        refreshed["pdf_source_fingerprint"] = refreshed["audit_source_fingerprint"]
    try:
        with system_context("proposal_audit_refresh", run_id=audit_trace["run"]["id"]):
            with job_write(job["id"], action="proposal.audit_refresh", scopes=("proposal",),
                           summary=_RECHECK_SUMMARY) as tx:
                tx.force_record()
                set_proposal_data(tx.conn, job["id"], refreshed, expected_rev=int(job.get("proposal_rev") or 0))
    except ProposalConflictError:
        # Saved again meanwhile; that save recorded its own check. This one's
        # run belongs to no saved bid: mark it so it is never taken for one.
        complete_calculation_run(audit_trace["run"]["id"], status="superseded", summary=audit_trace.get("audit") or {})
    fresh = load_job(job["id"])
    if not fresh:
        raise HTTPException(status_code=404, detail="Job not found")
    return fresh


def _required_job_field_gaps(job: dict) -> list[str]:
    missing = []
    for field in ("project_name", "gc_name", "salesperson"):
        if not str(job.get(field) or "").strip():
            missing.append(field)
    return missing


def _validate_bid_job_ready(job: dict) -> None:
    """Block bid/PDF generation when the bid cannot be trusted."""
    missing = _required_job_field_gaps(job)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot generate bid PDF until required job fields are filled: {', '.join(missing)}.",
        )

    materials = [m for m in (job.get("materials") or []) if isinstance(m, dict)]
    if not materials:
        raise HTTPException(status_code=400, detail="Cannot generate bid PDF until materials are loaded.")

    unpriced = [
        m.get("item_code") or m.get("description") or f"material {index + 1}"
        for index, m in enumerate(materials)
        if _as_number(m.get("unit_price")) is None or _as_number(m.get("unit_price")) <= 0
    ]
    if unpriced:
        sample = ", ".join(str(item) for item in unpriced[:5])
        suffix = "..." if len(unpriced) > 5 else ""
        raise HTTPException(
            status_code=409,
            detail=f"Cannot generate bid PDF until all materials have prices. Type the price on the material line for: {sample}{suffix}",
        )

    unknown = [
        m.get("item_code") or m.get("description") or f"material {index + 1}"
        for index, m in enumerate(materials)
        if not is_valid_material_classification(m.get("material_type"))
    ]
    if unknown:
        sample = ", ".join(str(item) for item in unknown[:5])
        suffix = "..." if len(unknown) > 5 else ""
        raise HTTPException(
            status_code=409,
            detail=f"Cannot generate bid PDF until unknown material types are classified. Unknown: {sample}{suffix}",
        )


def _validate_bid_pdf_download_ready(job: dict) -> None:
    """Reject old bid PDFs after the job or bid audit has changed."""
    _validate_bid_job_ready(job)
    bid_data = job.get("bid_data")
    if not isinstance(bid_data, dict) or not bid_data.get("pdf_audit_run_id"):
        raise HTTPException(status_code=409, detail="No bid PDF has been made for this job yet. Make the bid PDF first.")
    out_of_date = "The job changed after this bid PDF was made. Make the bid PDF again, then download it."
    latest = _latest_completed_run(job["id"], {"bid_pdf_generation"})
    if not latest or int(latest["id"]) != int(bid_data.get("pdf_audit_run_id")):
        raise HTTPException(status_code=409, detail=out_of_date)
    stored = bid_data.get("pdf_source_fingerprint")
    current_identity = _current_calculator_identity()
    if stored != _bid_source_fingerprint(job, identity=current_identity):
        # A PDF made before an app update (or a rate edit) still counts when
        # the job itself didn't change.
        run_identity = _run_calculator_identity(latest)
        if not (
            stored and run_identity and run_identity != current_identity
            and stored == _bid_source_fingerprint(job, identity=run_identity)
        ):
            raise HTTPException(status_code=409, detail=out_of_date)
    traces = get_calculation_traces(job["id"], run_id=latest["id"], entity_type="bid", entity_key="bid", limit=200)
    by_field = {trace.get("output_field"): trace for trace in traces}
    totals = bid_data.get("pdf_totals") or {}
    for field in ("subtotal", "tax_amount", "grand_total", "total_cost", "gpm_profit", "markup_amount"):
        try:
            _trace_result_matches(by_field.get(field), totals.get(field), label=f"bid {amount_word(field)}")
        except HTTPException:
            raise HTTPException(status_code=409, detail=out_of_date) from None


def _record_bid_audit(job_id: int, bid_data: dict) -> dict:
    """Persist audit rows for every displayed bid total."""
    trace = AuditTraceBuilder(job_id, default_source="bid_assembler")

    def _money(value) -> float:
        try:
            return round(float(value or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    bundles = [b for b in (bid_data.get("bundles") or []) if isinstance(b, dict)]
    bundle_components = []
    for index, bundle in enumerate(bundles):
        bundle_name = bundle.get("bundle_name") or f"bundle:{index}"
        component = {
            "bundle_name": bundle_name,
            "material_cost": _money(bundle.get("material_cost")),
            "sundry_cost": _money(bundle.get("sundry_cost")),
            "labor_cost": _money(bundle.get("labor_cost")),
            "freight_cost": _money(bundle.get("freight_cost")),
            "gpm_labor_adder": _money(bundle.get("gpm_labor_adder")),
            "gpm_material_adder": _money(bundle.get("gpm_material_adder")),
            "gpm_adder": _money(bundle.get("gpm_adder")),
            "total_price": _money(bundle.get("total_price")),
        }
        bundle_components.append(component)
        for field, value in component.items():
            if field == "bundle_name":
                continue
            inputs = {"bundle_name": bundle_name, "bundle_index": index}
            if field == "material_cost":
                inputs.update({
                    "order_qty": _money(bundle.get("order_qty")),
                    "unit_price": _money(bundle.get("unit_price")),
                    "waste_pct": bundle.get("waste_pct"),
                })
                formula = "order_qty * unit_price"
                if (
                    bundle.get("pricing_qty") is not None
                    and abs(_money(bundle.get("pricing_qty")) - _money(bundle.get("order_qty"))) > 0.005
                ):
                    # Stick-priced transition: sticks counted from the LF order qty
                    inputs["pricing_qty"] = _money(bundle.get("pricing_qty"))
                    inputs["pricing_unit"] = bundle.get("pricing_unit")
                    formula = "pricing_qty * unit_price"
            elif field == "freight_cost":
                inputs.update({
                    "order_qty": _money(bundle.get("order_qty")),
                    "freight_rate": _money(bundle.get("freight_rate")),
                })
                formula = "order_qty * freight_rate"
            elif field == "total_price":
                inputs.update({
                    "material_cost": component["material_cost"],
                    "sundry_cost": component["sundry_cost"],
                    "labor_cost": component["labor_cost"],
                    "freight_cost": component["freight_cost"],
                    "gpm_adder": component["gpm_adder"],
                })
                formula = "material_cost + sundry_cost + labor_cost + freight_cost + gpm_adder"
            elif field == "gpm_adder":
                inputs.update({
                    "gpm_labor_adder": component["gpm_labor_adder"],
                    "gpm_material_adder": component["gpm_material_adder"],
                })
                formula = "gpm_labor_adder + gpm_material_adder"
            else:
                inputs[field] = value
                formula = f"bundle.{field}"
            trace.record(
                entity_type="bid_bundle",
                entity_key=bundle_name,
                output_field=field,
                formula=formula,
                inputs=inputs,
                result=value,
                rule_id=f"bid_assembler:bundle:{field}",
                source="bid_assembler",
            )

    def _bundle_values(field: str) -> list[dict]:
        return [{"bundle_name": b["bundle_name"], "value": b.get(field, 0)} for b in bundle_components]

    total_material = _money(sum(b.get("material_cost", 0) for b in bundle_components))
    total_sundry = _money(sum(b.get("sundry_cost", 0) for b in bundle_components))
    total_labor = _money(sum(b.get("labor_cost", 0) for b in bundle_components))
    total_freight = _money(sum(b.get("freight_cost", 0) for b in bundle_components))
    total_gpm_labor = _money(sum(b.get("gpm_labor_adder", 0) for b in bundle_components))
    total_gpm_material = _money(sum(b.get("gpm_material_adder", 0) for b in bundle_components))
    subtotal = _money(bid_data.get("subtotal"))
    markup_amount = _money(bid_data.get("markup_amount"))
    tax_amount = _money(bid_data.get("tax_amount"))
    grand_total = _money(bid_data.get("grand_total"))

    proposal_specs = [
        ("material_cost", "sum(bundle.material_cost)", total_material, {"bundles": _bundle_values("material_cost")}),
        ("sundry_cost", "sum(bundle.sundry_cost)", total_sundry, {"bundles": _bundle_values("sundry_cost")}),
        ("labor_cost", "sum(bundle.labor_cost)", total_labor, {"bundles": _bundle_values("labor_cost")}),
        ("freight_cost", "sum(bundle.freight_cost)", total_freight, {"bundles": _bundle_values("freight_cost")}),
        ("total_cost", "sum(bundle.total_price before profit)", _money(bid_data.get("total_cost")), {
            "material_cost": total_material,
            "sundry_cost": total_sundry,
            "labor_cost": total_labor,
            "freight_cost": total_freight,
        }),
        ("gpm_profit", "total_cost / (1 - gpm_pct) - total_cost", _money(bid_data.get("gpm_profit")), {
            "total_cost": _money(bid_data.get("total_cost")),
            "gpm_pct": bid_data.get("gpm_pct", 0),
        }),
        ("gpm_labor", "sum(bundle.gpm_labor_adder)", total_gpm_labor, {"bundles": _bundle_values("gpm_labor_adder")}),
        ("gpm_material", "sum(bundle.gpm_material_adder)", total_gpm_material, {"bundles": _bundle_values("gpm_material_adder")}),
        ("subtotal", "sum(bundle.total_price)", subtotal, {"bundles": _bundle_values("total_price")}),
        ("markup_amount", "subtotal * markup_pct", markup_amount, {
            "subtotal": subtotal,
            "markup_pct": bid_data.get("markup_pct", 0),
        }),
        ("tax_amount", "taxable * tax_rate", tax_amount, {
            "tax_rate": bid_data.get("tax_rate", 0),
            "taxable_components": ["material_cost", "sundry_cost", "freight_cost", "gpm_material_adder"],
            "markup_amount": markup_amount,
        }),
        ("grand_total", "subtotal + markup_amount + tax_amount", grand_total, {
            "subtotal": subtotal,
            "markup_amount": markup_amount,
            "tax_amount": tax_amount,
        }),
    ]
    for field, formula, result, inputs in proposal_specs:
        trace.record(
            entity_type="bid",
            entity_id=job_id,
            entity_key="bid",
            output_field=field,
            formula=formula,
            inputs=inputs,
            result=result,
            rule_id=f"bid_assembler:{field}",
            source="bid_assembler",
        )

    run_id = create_calculation_run(
        job_id,
        "bid_pdf_generation",
        source="system",
        metadata=_audit_metadata({"endpoint": "generate-bid"}),
    )
    for record in trace._records:
        record["run_id"] = run_id
    trace_count = save_calculation_traces(job_id, run_id, trace.records)
    complete_calculation_run(run_id, summary=trace.summary())
    run = list_calculation_runs(job_id, limit=1)[0]
    return {"run": run, "trace_count": trace_count}


def _record_proposal_editor_audit(job_id: int, previous: dict, current: dict, *,
                                  endpoint: str = "proposal/bundles/save", source: str = "user") -> dict:
    """Persist a complete audit receipt for the currently displayed proposal.

    A proposal save calls it with the defaults; the automatic recheck after an
    app update (_recheck_saved_proposal) passes its own endpoint and source."""
    previous = previous or {}
    current = current or {}
    trace = AuditTraceBuilder(job_id, default_source="proposal_editor")

    def _money(value) -> float:
        try:
            return round(float(value or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    def _bundle_freight(bundle: dict) -> float:
        return _money(bundle.get("freight_override") if bundle.get("freight_override") is not None else bundle.get("freight_cost"))

    bundles = [b for b in (current.get("bundles") or []) if isinstance(b, dict)]
    bundle_components = []
    for index, bundle in enumerate(bundles):
        bundle_components.append({
            "bundle_name": bundle.get("bundle_name") or f"bundle:{index}",
            "material_cost": _money(bundle.get("material_cost")),
            "sundry_cost": _money(bundle.get("sundry_cost")),
            "labor_cost": _money(bundle.get("labor_cost")),
            "freight_cost": _bundle_freight(bundle),
            "gpm_labor_adder": _money(bundle.get("gpm_labor_adder")),
            "gpm_material_adder": _money(bundle.get("gpm_material_adder")),
            "gpm_adder": _money(bundle.get("gpm_adder")),
            "taxable": _money(bundle.get("taxable")),
            "tax_amount": _money(bundle.get("tax_amount")),
            "calculated_total": _money(bundle.get("total_price")),
            "total_price": _money(bundle.get("price_override") if bundle.get("price_override") is not None else bundle.get("total_price")),
            "price_override": bundle.get("price_override"),
        })
    totals = {
        "material_cost": _money(sum(_money(b.get("material_cost")) for b in bundles)),
        "sundry_cost": _money(sum(_money(b.get("sundry_cost")) for b in bundles)),
        "labor_cost": _money(sum(_money(b.get("labor_cost")) for b in bundles)),
        "freight_cost": _money(sum(_bundle_freight(b) for b in bundles)),
        "gpm_profit": _money(current.get("gpm_profit")),
        "gpm_labor": _money(current.get("gpm_labor")),
        "gpm_material": _money(current.get("gpm_material")),
        "manual_adjustment": _money(current.get("manual_adjustment")),
        "subtotal": _money(current.get("subtotal")),
        "tax_amount": _money(current.get("tax_amount")),
        "textura_amount": _money(current.get("textura_amount")),
        "grand_total": _money(current.get("grand_total")),
    }
    totals["total_cost"] = _money(
        totals["material_cost"] + totals["sundry_cost"] + totals["labor_cost"] + totals["freight_cost"]
    )

    component_values = {
        field: [{"bundle_name": b["bundle_name"], "value": b[field]} for b in bundle_components]
        for field in ("material_cost", "sundry_cost", "labor_cost", "freight_cost", "tax_amount", "total_price")
    }
    proposal_trace_specs = [
        ("material_cost", "sum(bundle.material_cost)", {"bundles": component_values["material_cost"]}),
        ("sundry_cost", "sum(bundle.sundry_cost)", {"bundles": component_values["sundry_cost"]}),
        ("labor_cost", "sum(bundle.labor_cost)", {"bundles": component_values["labor_cost"]}),
        ("freight_cost", "sum(bundle.freight_override ?? bundle.freight_cost)", {"bundles": component_values["freight_cost"]}),
        ("total_cost", "material_cost + sundry_cost + labor_cost + freight_cost", {
            "material_cost": totals["material_cost"],
            "sundry_cost": totals["sundry_cost"],
            "labor_cost": totals["labor_cost"],
            "freight_cost": totals["freight_cost"],
        }),
        ("gpm_profit", "total_cost / (1 - gpm_pct) - total_cost", {
            "total_cost": totals["total_cost"],
            "gpm_pct": current.get("gpm_pct", 0),
        }),
        ("gpm_labor", "gpm_profit * 0.9793", {"gpm_profit": totals["gpm_profit"], "split_pct": 0.9793}),
        ("gpm_material", "gpm_profit - gpm_labor", {
            "gpm_profit": totals["gpm_profit"],
            "gpm_labor": totals["gpm_labor"],
        }),
        ("manual_adjustment", "sum(effective bundle total - calculated bundle total)", {
            "bundles": [
                {"bundle_name": bundle["bundle_name"], "calculated": bundle["calculated_total"], "effective": bundle["total_price"]}
                for bundle in bundle_components
            ],
        }),
        ("subtotal", "sum(effective bundle totals) - tax_amount", {
            "manual_adjustment": totals["manual_adjustment"],
            "tax_amount": totals["tax_amount"],
        }),
        ("tax_amount", "sum(bundle.tax_amount)", {
            "tax_rate": current.get("tax_rate", 0),
            "bundles": component_values["tax_amount"],
        }),
        ("textura_amount", "min((subtotal + tax_amount) * 0.0022, 5000) when enabled else 0", {
            "textura_fee": current.get("textura_fee", 0),
            "subtotal": totals["subtotal"],
            "tax_amount": totals["tax_amount"],
            "cap": 5000,
            "rate": 0.0022,
        }),
        ("grand_total", "subtotal + tax_amount + textura_amount", {
            "subtotal": totals["subtotal"],
            "tax_amount": totals["tax_amount"],
            "textura_amount": totals["textura_amount"],
        }),
    ]

    for field, formula, inputs in proposal_trace_specs:
        trace.record(
            entity_type="proposal",
            entity_id=job_id,
            entity_key="proposal",
            output_field=field,
            formula=formula,
            inputs=inputs,
            result=totals[field],
            rule_id=f"proposal_editor:{field}",
            source="proposal_editor",
        )

    for index, bundle in enumerate(bundles):
        bundle_name = bundle.get("bundle_name") or f"bundle:{index}"
        freight = _bundle_freight(bundle)
        bundle_total = _money(bundle.get("price_override") if bundle.get("price_override") is not None else bundle.get("total_price"))
        component = bundle_components[index] if index < len(bundle_components) else {}
        bundle_values = {
            "material_cost": _money(bundle.get("material_cost")),
            "sundry_cost": _money(bundle.get("sundry_cost")),
            "labor_cost": _money(bundle.get("labor_cost")),
            "freight_cost": freight,
            "gpm_labor_adder": _money(bundle.get("gpm_labor_adder")),
            "gpm_material_adder": _money(bundle.get("gpm_material_adder")),
            "gpm_adder": _money(bundle.get("gpm_adder")),
            "taxable": _money(bundle.get("taxable")),
            "tax_amount": _money(bundle.get("tax_amount")),
            "total_price": bundle_total,
        }
        for field, value in bundle_values.items():
            inputs = {"bundle_name": bundle_name, "bundle_index": index}
            if field in ("gpm_adder", "total_price", "tax_amount"):
                inputs.update({
                    "material_cost": component.get("material_cost"),
                    "sundry_cost": component.get("sundry_cost"),
                    "labor_cost": component.get("labor_cost"),
                    "freight_cost": component.get("freight_cost"),
                    "gpm_labor_adder": component.get("gpm_labor_adder"),
                    "gpm_material_adder": component.get("gpm_material_adder"),
                    "gpm_adder": component.get("gpm_adder"),
                    "taxable": component.get("taxable"),
                    "tax_amount": component.get("tax_amount"),
                    "price_override": component.get("price_override"),
                })
            elif field == "freight_cost":
                inputs.update({
                    "freight_cost": _money(bundle.get("freight_cost")),
                    "freight_override": bundle.get("freight_override"),
                })
            else:
                inputs[field] = value
            trace.record(
                entity_type="bundle",
                entity_key=bundle_name,
                output_field=field,
                formula={
                    "freight_cost": "freight_override if present else freight_cost",
                    "total_price": "price_override if present else material_cost + sundry_cost + labor_cost + freight_cost + gpm_adder + tax_amount",
                    "gpm_adder": "gpm_labor_adder + gpm_material_adder",
                    "tax_amount": "taxable * tax_rate",
                }.get(field, f"bundle.{field}"),
                inputs=inputs,
                result=value,
                rule_id=f"proposal_editor:bundle:{field}",
                source="proposal_editor",
            )

        for material_index, material in enumerate(bundle.get("materials") or []):
            if not isinstance(material, dict):
                continue
            pricing = material_pricing_context(material)
            trace.record(
                entity_type="material",
                entity_id=material.get("id") or material.get("material_id"),
                entity_key=material.get("item_code") or material.get("description"),
                output_field="extended_cost",
                formula=pricing["formula"],
                inputs={
                    "bundle_name": bundle_name,
                    "bundle_index": index,
                    "line_index": material_index,
                    **pricing["inputs"],
                    "pricing_basis": pricing["basis"],
                    "pricing_quantity": pricing["pricing_quantity"],
                    "pricing_unit": pricing["pricing_unit"],
                },
                result=_money(material.get("extended_cost")),
                rule_id=f"proposal_editor:material:{material.get('material_type', '')}:extended_cost",
                source=material.get("price_source") or "proposal_editor",
            )

        for sundry_index, sundry in enumerate(bundle.get("sundry_items") or []):
            if not isinstance(sundry, dict):
                continue
            qty = _money(sundry.get("qty"))
            unit_price = _money(sundry.get("unit_price"))
            material_id = sundry.get("material_id")
            sundry_name = sundry.get("sundry_name") or "sundry"
            trace.record(
                entity_type="sundry",
                entity_id=material_id,
                entity_key=f"{material_id}:{sundry_name}",
                output_field="extended_cost",
                formula="qty * unit_price",
                inputs={
                    "bundle_name": bundle_name,
                    "bundle_index": index,
                    "line_index": sundry_index,
                    "qty": qty,
                    "unit_price": unit_price,
                    "unit": sundry.get("unit"),
                },
                result=_money(sundry.get("extended_cost")),
                rule_id=f"proposal_editor:sundry:{sundry_name}",
                source="proposal_editor",
            )

        for labor_index, labor in enumerate(bundle.get("labor_items") or []):
            if not isinstance(labor, dict):
                continue
            qty = _money(labor.get("qty"))
            rate = _money(labor.get("rate"))
            material_id = labor.get("material_id")
            labor_description = labor.get("labor_description") or "labor"
            trace.record(
                entity_type="labor",
                entity_id=material_id,
                entity_key=f"{material_id}:{labor_description}",
                output_field="extended_cost",
                formula="qty * rate",
                inputs={
                    "bundle_name": bundle_name,
                    "bundle_index": index,
                    "line_index": labor_index,
                    "qty": qty,
                    "rate": rate,
                    "unit": labor.get("unit"),
                },
                result=_money(labor.get("extended_cost")),
                rule_id=f"proposal_editor:labor:{labor.get('unit', '')}",
                source="proposal_editor",
            )

    manual_trace_count = 0
    for field in ("tax_rate", "gpm_pct", "textura_fee"):
        old = _as_number(previous.get(field))
        new = _as_number(current.get(field))
        if old != new:
            trace.manual_override(
                entity_type="proposal",
                entity_id=job_id,
                entity_key="proposal",
                output_field=field,
                prior_value=previous.get(field),
                value=current.get(field),
                note="Estimator changed a proposal calculation input.",
            )
            manual_trace_count += 1

    previous_bundles = previous.get("bundles") or []
    previous_by_name = {
        b.get("bundle_name"): b for b in previous_bundles
        if isinstance(b, dict) and b.get("bundle_name")
    }
    for index, bundle in enumerate(current.get("bundles") or []):
        if not isinstance(bundle, dict):
            continue
        bundle_name = bundle.get("bundle_name") or f"bundle:{index}"
        prior = previous_by_name.get(bundle.get("bundle_name"))
        if prior is None and index < len(previous_bundles):
            prior = previous_bundles[index] if isinstance(previous_bundles[index], dict) else {}
        prior = prior or {}

        for field in ("price_override", "freight_override"):
            prior_value = prior.get(field)
            value = bundle.get(field)
            if value is not None or prior_value is not None:
                trace.manual_override(
                    entity_type="bundle",
                    entity_key=bundle_name,
                    output_field=field,
                    prior_value=prior_value,
                    value=value,
                    note="Accepted bundle override is active." if value is not None else "Estimator cleared the accepted bundle override.",
                )
                manual_trace_count += 1

        prior_materials = {
            str(item.get("item_code") or item.get("id") or item.get("material_id") or ""): item
            for item in (prior.get("materials") or []) if isinstance(item, dict)
        }
        for material in (bundle.get("materials") or []):
            if not isinstance(material, dict) or not material.get("freight_is_manual"):
                continue
            material_key = str(material.get("item_code") or material.get("id") or material.get("material_id") or "")
            prior_material = prior_materials.get(material_key) or {}
            trace.manual_override(
                entity_type="material",
                entity_id=material.get("id") or material.get("material_id"),
                entity_key=material.get("item_code") or material.get("description"),
                output_field="freight_per_unit",
                prior_value=prior_material.get("freight_per_unit"),
                value=material.get("freight_per_unit"),
                note="Accepted material freight override is active.",
            )
            manual_trace_count += 1

        prior_sundries = {
            f"{item.get('material_id')}:{item.get('sundry_name') or 'sundry'}": item
            for item in (prior.get("sundry_items") or []) if isinstance(item, dict)
        }
        for sundry in (bundle.get("sundry_items") or []):
            if not isinstance(sundry, dict) or not sundry.get("is_manual_price"):
                continue
            sundry_key = f"{sundry.get('material_id')}:{sundry.get('sundry_name') or 'sundry'}"
            prior_sundry = prior_sundries.get(sundry_key) or {}
            trace.manual_override(
                entity_type="sundry",
                entity_id=sundry.get("material_id"),
                entity_key=sundry_key,
                output_field="extended_cost",
                prior_value=prior_sundry.get("extended_cost"),
                value=sundry.get("extended_cost"),
                note="Accepted sundry price override is active.",
            )
            manual_trace_count += 1

        prior_labor = {
            str(item.get("manual_source_key") or f"{item.get('material_id')}:{item.get('labor_description') or 'labor'}"): item
            for item in (prior.get("labor_items") or []) if isinstance(item, dict)
        }
        for labor in (bundle.get("labor_items") or []):
            if not isinstance(labor, dict) or not (labor.get("is_manual") or labor.get("is_stair_labor")):
                continue
            source_key = str(labor.get("manual_source_key") or f"{labor.get('material_id')}:{labor.get('labor_description') or 'labor'}")
            prior_line = prior_labor.get(source_key) or {}
            labor_description = labor.get("labor_description") or "labor"
            trace.manual_override(
                entity_type="labor",
                entity_id=labor.get("material_id"),
                entity_key=f"{labor.get('material_id')}:{labor_description}",
                output_field="extended_cost",
                prior_value=prior_line.get("extended_cost"),
                value=labor.get("extended_cost"),
                note="Accepted manual labor line is active.",
            )
            manual_trace_count += 1

        for deleted_key in (bundle.get("deleted_labor_keys") or []):
            trace.manual_override(
                entity_type="bundle",
                entity_key=bundle_name,
                output_field="deleted_labor",
                prior_value=(prior.get("deleted_labor_reasons") or {}).get(deleted_key),
                value=(bundle.get("deleted_labor_reasons") or {}).get(deleted_key),
                note=f"Generated labor line remains deleted: {deleted_key}",
            )
            manual_trace_count += 1

    if not trace.records:
        return {"trace_count": 0, "manual_trace_count": 0, "audit_trace": None}

    run_id = create_calculation_run(
        job_id,
        "proposal_editor_save",
        source=source,
        metadata=_audit_metadata({"endpoint": endpoint}),
    )
    for record in trace._records:
        record["run_id"] = run_id
    trace_count = save_calculation_traces(job_id, run_id, trace.records)
    complete_calculation_run(run_id, summary=trace.summary())
    # This run by id: the job's newest run may be another save's by now, and
    # the saved bid points to this one (proposal["audit"]["run_id"]).
    run = _completed_run_by_id(job_id, run_id) or list_calculation_runs(job_id, limit=1)[0]
    return {
        "trace_count": trace_count,
        "manual_trace_count": manual_trace_count,
        "audit_trace": {"run": run, "traces": get_calculation_traces(job_id, run_id=run_id, limit=2000), "events": trace.records, "audit": trace.summary()},
    }


def _append_proposal_totals_snapshot(trace: AuditTraceBuilder, job_id: int, proposal: dict) -> None:
    """Append final editor-style proposal totals to a generation audit run."""
    if not isinstance(proposal, dict):
        return

    normalize_proposal_totals(proposal)
    if not trace:
        return

    def _money(value) -> float:
        try:
            return round(float(value or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    def _float(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _freight(bundle: dict) -> float:
        return _money(bundle.get("freight_override") if bundle.get("freight_override") is not None else bundle.get("freight_cost"))

    bundles = [b for b in (proposal.get("bundles") or []) if isinstance(b, dict)]
    tax_rate = _float(proposal.get("tax_rate"))
    gpm_pct = _float(proposal.get("gpm_pct"))

    material_total = _money(sum(_money(b.get("material_cost")) for b in bundles))
    sundry_total = _money(sum(_money(b.get("sundry_cost")) for b in bundles))
    labor_total = _money(sum(_money(b.get("labor_cost")) for b in bundles))
    freight_total = _money(sum(_freight(b) for b in bundles))
    total_cost = _money(material_total + sundry_total + labor_total + freight_total)

    gpm_profit = _money(proposal.get("gpm_profit"))
    gpm_labor = _money(proposal.get("gpm_labor"))
    gpm_material = _money(proposal.get("gpm_material"))

    bundle_rows = []
    for index, bundle in enumerate(bundles):
        bundle_name = bundle.get("bundle_name") or f"bundle:{index}"
        freight = _freight(bundle)
        row = {
            "bundle_name": bundle_name,
            "bundle_index": index,
            "material_cost": _money(bundle.get("material_cost")),
            "sundry_cost": _money(bundle.get("sundry_cost")),
            "labor_cost": _money(bundle.get("labor_cost")),
            "freight_cost": freight,
            "gpm_labor_adder": bundle["gpm_labor_adder"],
            "gpm_material_adder": bundle["gpm_material_adder"],
            "gpm_adder": bundle["gpm_adder"],
            "taxable": bundle["taxable"],
            "tax_amount": bundle["tax_amount"],
            "calculated_total": _money(bundle.get("total_price")),
            "total_price": effective_bundle_total(bundle),
            "price_override": bundle.get("price_override"),
        }
        bundle_rows.append(row)

    tax_amount = _money(proposal.get("tax_amount"))
    subtotal = _money(proposal.get("subtotal"))
    manual_adjustment = _money(proposal.get("manual_adjustment"))
    textura_enabled = 1 if proposal.get("textura_fee") else 0
    textura_amount = _money(proposal.get("textura_amount"))
    grand_total = _money(proposal.get("grand_total"))

    def _bundle_values(field: str) -> list[dict]:
        return [{"bundle_name": row["bundle_name"], "value": row[field]} for row in bundle_rows]

    proposal_specs = [
        ("material_cost", "sum(bundle.material_cost)", {"bundles": _bundle_values("material_cost")}, material_total),
        ("sundry_cost", "sum(bundle.sundry_cost)", {"bundles": _bundle_values("sundry_cost")}, sundry_total),
        ("labor_cost", "sum(bundle.labor_cost)", {"bundles": _bundle_values("labor_cost")}, labor_total),
        ("freight_cost", "sum(bundle.freight_override ?? bundle.freight_cost)", {"bundles": _bundle_values("freight_cost")}, freight_total),
        ("total_cost", "material_cost + sundry_cost + labor_cost + freight_cost", {
            "material_cost": material_total,
            "sundry_cost": sundry_total,
            "labor_cost": labor_total,
            "freight_cost": freight_total,
        }, total_cost),
        ("gpm_profit", "total_cost / (1 - gpm_pct) - total_cost", {"total_cost": total_cost, "gpm_pct": gpm_pct}, gpm_profit),
        ("gpm_labor", "gpm_profit * 0.9793", {"gpm_profit": gpm_profit, "split_pct": 0.9793}, gpm_labor),
        ("gpm_material", "gpm_profit - gpm_labor", {"gpm_profit": gpm_profit, "gpm_labor": gpm_labor}, gpm_material),
        ("manual_adjustment", "sum(effective bundle total - calculated bundle total)", {
            "bundles": [
                {"bundle_name": row["bundle_name"], "calculated": row["calculated_total"], "effective": row["total_price"]}
                for row in bundle_rows
            ],
        }, manual_adjustment),
        ("subtotal", "sum(effective bundle totals) - tax_amount", {"manual_adjustment": manual_adjustment, "tax_amount": tax_amount}, subtotal),
        ("tax_amount", "sum(bundle.tax_amount)", {"tax_rate": tax_rate, "bundles": _bundle_values("tax_amount")}, tax_amount),
        ("textura_amount", "min((subtotal + tax_amount) * 0.0022, 5000) when enabled else 0", {
            "textura_fee": textura_enabled,
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "rate": 0.0022,
            "cap": 5000,
        }, textura_amount),
        ("grand_total", "subtotal + tax_amount + textura_amount", {
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "textura_amount": textura_amount,
        }, grand_total),
    ]
    for field, formula, inputs, result in proposal_specs:
        trace.record(
            entity_type="proposal",
            entity_id=job_id,
            entity_key="proposal",
            output_field=field,
            formula=formula,
            inputs=inputs,
            result=result,
            rule_id=f"proposal_generation:{field}",
            source="proposal_generation",
        )

    for row in bundle_rows:
        for field in (
            "material_cost", "sundry_cost", "labor_cost", "freight_cost",
            "gpm_labor_adder", "gpm_material_adder", "gpm_adder",
            "taxable", "tax_amount", "total_price",
        ):
            inputs = {"bundle_name": row["bundle_name"], "bundle_index": row["bundle_index"]}
            if field in ("gpm_adder", "tax_amount", "total_price"):
                inputs.update(row)
            elif field == "freight_cost":
                inputs.update({"freight_cost": row["freight_cost"], "price_override": row.get("price_override")})
            else:
                inputs[field] = row[field]
            trace.record(
                entity_type="bundle",
                entity_key=row["bundle_name"],
                output_field=field,
                formula={
                    "freight_cost": "freight_override if present else freight_cost",
                    "gpm_adder": "gpm_labor_adder + gpm_material_adder",
                    "tax_amount": "taxable * tax_rate",
                    "total_price": "price_override if present else material_cost + sundry_cost + labor_cost + freight_cost + gpm_adder + tax_amount",
                }.get(field, f"bundle.{field}"),
                inputs=inputs,
                result=row[field],
                rule_id=f"proposal_generation:bundle:{field}",
                source="proposal_generation",
            )


@app.put("/api/jobs/{job_id}/proposal/bundles")
@app.post("/api/jobs/{job_id}/proposal/bundles/save")
@audit_route("proposal.save")
async def api_save_proposal_bundles(job_id: str, request: Request):
    """Auto-save proposal editor state (bundles, notes, terms, GPM, etc.)."""
    raw_body = await request.body()
    return await run_in_threadpool(_save_proposal_bundles, job_id, raw_body)


# A proposal save that finds another save landed first (proposal_rev moved)
# re-runs its checks against the newer proposal. Every retry means another
# save made progress, so it ends in "ok", "stale_ignored" or a real conflict
# from another tab; this limit only stops a bid that never stops saving.
_PROPOSAL_SAVE_RETRY_SECONDS = 30
_STALE_PROPOSAL_DETAIL = (
    "Someone saved this proposal in another tab or on another computer after you opened it, "
    "so your last change was not saved. Reload the page to see their version, then make your change again."
)


def _nonnegative_int(value, default: int = 0) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return default


def _stored_proposal(raw) -> dict:
    """proposal_data from a jobs row (JSON text) as a dict."""
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _proposal_save_check(stored: dict, body: dict) -> dict:
    """Compare an incoming proposal save with the stored proposal.

    ``verdict`` is "ok"; "stale" (an older save from the same browser tab
    arrived after a newer one, so it is ignored); or "conflict" (another tab
    or person saved since this copy was loaded)."""
    stored = stored or {}
    incoming_session_id = str(body.get("client_session_id") or "").strip()
    incoming_edit_version = _nonnegative_int(body.get("client_edit_version"))
    incoming_save_sequence = _nonnegative_int(body.get("client_save_sequence"))
    stored_session_id = str(stored.get("_client_session_id") or "").strip()
    stored_edit_version = _nonnegative_int(stored.get("_client_edit_version"))
    stored_save_sequence = _nonnegative_int(stored.get("_client_save_sequence"))
    stored_server_revision = _nonnegative_int(stored.get("_server_revision"))
    incoming_base_revision = _nonnegative_int(body.get("base_server_revision"), default=-1)
    same_client_session = bool(incoming_session_id and incoming_session_id == stored_session_id)
    if same_client_session and (
        incoming_save_sequence < stored_save_sequence or incoming_edit_version < stored_edit_version
    ):
        verdict = "stale"
    elif (
        incoming_session_id
        and not same_client_session
        and "base_server_revision" in body
        and incoming_base_revision != stored_server_revision
    ):
        verdict = "conflict"
    else:
        verdict = "ok"
    return {
        "verdict": verdict,
        "incoming_session_id": incoming_session_id,
        "incoming_edit_version": incoming_edit_version,
        "incoming_save_sequence": incoming_save_sequence,
        "stored_server_revision": stored_server_revision,
    }


def _stale_proposal_save_result(stored: dict) -> dict:
    return {
        "status": "stale_ignored",
        "stale_save_ignored": True,
        "manual_trace_count": 0,
        "trace_count": 0,
        "audit_trace": None,
        "audit": None,
        "proposal_data": stored,
    }


def _proposal_layout_changed(previous: dict, current: dict, changes: list[dict]) -> bool:
    """True when this save added, removed or moved bundles (or rows inside them).

    Such a save doesn't join an open history entry, and it closes the open
    ones so later edits start fresh. Bundles with uids are named by uid in
    the history ("/proposal/bundles/b_1a2b3c4d/description_text"), so only
    adding, removing or reordering them counts. Rows still named by position
    ("/proposal/bundles/b_1a2b3c4d/labor_items/2") can become a different row
    after one is added or removed, so that counts too.
    """
    before = [bundle for bundle in (previous or {}).get("bundles") or [] if isinstance(bundle, dict)]
    after = [bundle for bundle in (current or {}).get("bundles") or [] if isinstance(bundle, dict)]
    if len(before) != len(after):
        return True
    before_uids = [stable_ids.clean_uid(bundle.get("uid")) for bundle in before]
    after_uids = [stable_ids.clean_uid(bundle.get("uid")) for bundle in after]
    if all(before_uids) and all(after_uids):
        if before_uids != after_uids:
            return True
    else:
        # Bundles named by position: one renamed bundle keeps its place; two
        # or more names changing at once is a reorder (or looks just like one).
        renamed = sum(1 for old, new in zip(before, after) if old.get("bundle_name") != new.get("bundle_name"))
        if renamed > 1:
            return True
    for change in changes:
        if change.get("op") not in ("add", "remove"):
            continue
        parts = audit.split_path(change.get("path"))
        if len(parts) >= 3 and parts[:2] == ["proposal", "bundles"] and parts[-1].isdigit():
            return True
    return False


def _proposal_edit_group(changes: list[dict]) -> audit.GroupPolicy:
    """Autosaves while typing join one history entry: text edits stay open
    longer than number edits."""
    edited = [change for change in changes if not change.get("derived")] or changes
    if edited and all(
        change.get("op") == "lines" or isinstance(change.get("after"), str) or isinstance(change.get("before"), str)
        for change in edited
    ):
        return audit.TEXT_EDITS
    return audit.NUMBER_EDITS


def _save_proposal_bundles(job_id: str, raw_body: bytes):
    db_id = _resolve_job_id(job_id)
    body = json.loads(raw_body)
    # The stale-copy checks run against the stored proposal, and the save only
    # goes through if nobody saved since (checked again under the bid's lock).
    # If someone did, the checks run again against their save. Losing that
    # race is never itself a conflict: only the checks decide on a 409.
    give_up_at = time.monotonic() + _PROPOSAL_SAVE_RETRY_SECONDS
    while True:
        job = load_job(db_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        base_proposal_rev = int(job.get("proposal_rev") or 0)
        result = _try_save_proposal_bundles(db_id, job, body, base_proposal_rev)
        if result is not None:
            return result
        if time.monotonic() >= give_up_at:
            raise JobBusyError()


def _try_save_proposal_bundles(db_id: int, job: dict, body: dict, base_proposal_rev: int) -> dict | None:
    """One save attempt; None when another save landed after ``job`` was
    loaded and passed the checks, so this save must be rebuilt on top of it."""
    previous_proposal_data = job.get("proposal_data") or {}
    check = _proposal_save_check(previous_proposal_data, body)
    if check["verdict"] == "stale":
        audit.note_checked(db_id)  # nothing saved
        return _stale_proposal_save_result(previous_proposal_data)
    if check["verdict"] == "conflict":
        raise HTTPException(status_code=409, detail=_STALE_PROPOSAL_DETAIL)
    incoming_session_id = check["incoming_session_id"]
    incoming_edit_version = check["incoming_edit_version"]
    incoming_save_sequence = check["incoming_save_sequence"]
    stored_server_revision = check["stored_server_revision"]
    # Bundles keep the uid the client sent back; one without (a new bundle,
    # or a client that doesn't know uids) takes the uid of the saved bundle it
    # matches, else a new one. A copy: a retry starts from the client's bundles.
    bundles = copy.deepcopy(body.get("bundles", []))
    stable_ids.carry_bundle_uids(previous_proposal_data.get("bundles"), bundles)
    proposal_data = {
        "bundles": bundles,
        "notes": body.get("notes", []),
        "terms": body.get("terms", []),
        "exclusions": body.get("exclusions", []),
        "tax_rate": body.get("tax_rate", 0),
        "gpm_pct": body.get("gpm_pct", 0),
        "textura_fee": body.get("textura_fee", 0),
        "subtotal": body.get("subtotal", 0),
        "tax_amount": body.get("tax_amount", 0),
        "grand_total": body.get("grand_total", 0),
        "gpm_profit": body.get("gpm_profit", 0),
        "gpm_labor": body.get("gpm_labor", 0),
        "gpm_material": body.get("gpm_material", 0),
        "manual_adjustment": body.get("manual_adjustment", 0),
        "textura_amount": body.get("textura_amount", 0),
        "deleted_bundles": body.get("deleted_bundles", []),
        "deleted_bundle_reasons": body.get("deleted_bundle_reasons", {}),
        "deleted_material_codes": body.get("deleted_material_codes", []),
        "deleted_material_reasons": body.get("deleted_material_reasons", {}),
        "audit": body.get("audit", {}),
        "_client_session_id": incoming_session_id,
        "_client_edit_version": incoming_edit_version,
        "_client_save_sequence": incoming_save_sequence,
        "_server_revision": stored_server_revision + 1,
    }
    normalize_proposal_totals(proposal_data)
    # The job values the numbers were made from carry over from the saved bid
    # (a job change stays flagged until it reaches the bid), or come from a
    # Regenerate the editor applied.
    _stamp_proposal_source(job, proposal_data,
                           source_job=_saved_source_job(job, previous_proposal_data, body))
    audit_result = _record_proposal_editor_audit(job["id"], previous_proposal_data, proposal_data)
    if audit_result.get("audit_trace"):
        proposal_data["audit"] = {
            "run_id": audit_result["audit_trace"]["run"]["id"],
            "trace_count": audit_result["trace_count"],
            "summary": audit_result["audit_trace"].get("audit", {}),
        }
    changes = audit.diff(previous_proposal_data, proposal_data, "/proposal", entity_type="job")
    described = audit.describe_changes(changes, "proposal")
    summary = f"Edited the proposal ({described[:1].lower()}{described[1:]})" if changes else "Saved the proposal"
    if _proposal_layout_changed(previous_proposal_data, proposal_data, changes):
        group = None
    else:
        group = _proposal_edit_group(changes)
    landed_first = None  # the newer stored proposal, when another save got in first
    try:
        with job_write(db_id, action="proposal.save", scopes=("proposal",),
                       group=group, summary=summary) as tx:
            if int(tx.row.get("proposal_rev") or 0) != base_proposal_rev:
                # Another save landed after this one loaded the proposal. Check
                # against it here, under the bid's lock, so an older save from
                # the same tab is dropped now instead of being retried.
                landed_first = _stored_proposal(tx.row.get("proposal_data"))
                if _proposal_save_check(landed_first, body)["verdict"] == "conflict":
                    raise HTTPException(status_code=409, detail=_STALE_PROPOSAL_DETAIL)
            else:
                set_proposal_data(tx.conn, db_id, proposal_data, expected_rev=base_proposal_rev)
    except ProposalConflictError:
        return None
    if landed_first is not None:
        if _proposal_save_check(landed_first, body)["verdict"] == "stale":
            return _stale_proposal_save_result(landed_first)
        return None  # still the newest edit: rebuild it on top of the other save
    return {
        "status": "ok",
        "manual_trace_count": audit_result.get("manual_trace_count", 0),
        "trace_count": audit_result.get("trace_count", 0),
        "audit_trace": audit_result.get("audit_trace"),
        "audit": audit_result.get("audit_trace"),
        "proposal_data": proposal_data,
    }


def _whole_floats_as_int(value):
    """Return a copy with whole-number floats as ints (0.0 -> 0) for value comparison."""
    if isinstance(value, dict):
        return {key: _whole_floats_as_int(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_whole_floats_as_int(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _raise_unless_proposal_check_ok(status: dict) -> None:
    """409 in plain words unless the saved bid is current or only needs the
    automatic recheck after an app update."""
    if status.get("kind") in ("current", "tool_updated"):
        return
    raise HTTPException(status_code=409, detail=proposal_check_message(status)[1])


def _body_matches_saved_proposal(job: dict, body: dict, saved_proposal: dict) -> bool:
    # Browsers serialize whole-number floats without ".0", so compare by value.
    identity = _current_calculator_identity()
    return (
        _proposal_source_fingerprint(job, _whole_floats_as_int(body), identity=identity)
        == _proposal_source_fingerprint(job, _whole_floats_as_int(saved_proposal), identity=identity)
    )


_PDF_NOT_SAVED_BID = (
    f"The bid you're printing doesn't match the last saved bid. Wait until {REVIEW_STEP} "
    "shows Saved, then click Generate PDF again."
)


def _validate_proposal_pdf_ready(job: dict, body: dict) -> None:
    """Reject PDF generation when required header data or current audit is missing.

    A bid saved before an app update (or a rate or labor price edit) is
    rechecked here with the running app and saved as a system recheck; the
    recheck updates ``job`` and ``body["audit"]`` in place so the caller
    prints and saves the rechecked bid.
    """
    missing = _required_job_field_gaps(job)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Fill in the {plain_list([JOB_FIELD_LABELS.get(field, field) for field in missing])} on the job "
                "before making the PDF. Click Edit job details at the top of the page."
            ),
        )

    saved_proposal = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    check_status = _proposal_check_status(job, saved_proposal)
    _raise_unless_proposal_check_ok(check_status)
    if not _body_matches_saved_proposal(job, body, saved_proposal):
        raise HTTPException(status_code=409, detail=_PDF_NOT_SAVED_BID)

    raw_deleted_codes = {str(code) for code in (body.get("deleted_material_codes") or []) if code}
    deleted_material_reasons = body.get("deleted_material_reasons")
    if not isinstance(deleted_material_reasons, dict):
        deleted_material_reasons = {}
    missing_material_reasons = [
        code for code in sorted(raw_deleted_codes)
        if not str(deleted_material_reasons.get(code) or "").strip()
    ]
    if missing_material_reasons:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Give a reason for each deleted material before making the PDF: {plain_list(missing_material_reasons)}. "
                f"Type it on each deleted line on {REVIEW_STEP}."
            ),
        )

    deleted_bundle_names = {str(name) for name in (body.get("deleted_bundles") or []) if name}
    deleted_bundle_reasons = body.get("deleted_bundle_reasons")
    if not isinstance(deleted_bundle_reasons, dict):
        deleted_bundle_reasons = {}
    missing_bundle_reasons = sorted(
        name for name in deleted_bundle_names
        if not str(deleted_bundle_reasons.get(name) or "").strip()
    )
    if missing_bundle_reasons:
        raise HTTPException(
            status_code=409,
            detail=f"Give a reason for each deleted bundle before making the PDF: {plain_list(missing_bundle_reasons)}.",
        )

    accepted_codes = {
        _job_material_key(material)
        for bundle in (body.get("bundles") or [])
        if isinstance(bundle, dict)
        for material in (bundle.get("materials") or [])
        if isinstance(material, dict) and _job_material_key(material)
    }
    both = sorted(raw_deleted_codes & accepted_codes)
    if both:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{plain_list(both)} {'is' if len(both) == 1 else 'are'} deleted but still on the bid. "
                f"{CLICK_REGENERATE}"
            ),
        )

    for bundle in body.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        reasons = bundle.get("deleted_labor_reasons")
        if not isinstance(reasons, dict):
            reasons = {}
        if any(not str(reasons.get(key) or "").strip() for key in (bundle.get("deleted_labor_keys") or [])):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Give a reason for each deleted labor line in {bundle.get('bundle_name') or 'this bundle'} "
                    "before making the PDF."
                ),
            )

    active_materials = [
        material for material in (job.get("materials") or [])
        if isinstance(material, dict) and _job_material_key(material) not in raw_deleted_codes
    ]
    unknown = [
        material.get("item_code") or material.get("description") or "material"
        for material in active_materials
        if not is_valid_material_classification(material.get("material_type"))
    ]
    unpriced = [
        material.get("item_code") or material.get("description") or "material"
        for material in active_materials
        if _as_number(material.get("unit_price")) is None or _as_number(material.get("unit_price")) <= 0
    ]
    if unknown or unpriced:
        issues = []
        if unknown:
            issues.append(f"pick a type for {plain_list(unknown)}")
        if unpriced:
            issues.append(f"type a price for {plain_list(unpriced)}")
        raise HTTPException(
            status_code=409,
            detail=f"Before making the PDF, {' and '.join(issues)} on the Takeoff & Pricing step.",
        )

    arithmetic_errors = proposal_math_errors(body)
    if arithmetic_errors:
        raise HTTPException(
            status_code=409,
            detail=f"Some numbers on the bid don't add up ({arithmetic_errors[0]}) {CLICK_REGENERATE}",
        )

    if check_status["kind"] == "tool_updated":
        # Only the app (or its rates) changed since the bid was saved: recheck
        # it now, then carry on with the rechecked bid.
        fresh = _recheck_saved_proposal(job)
        job.clear()
        job.update(fresh)
        saved_proposal = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
        _raise_unless_proposal_check_ok(_proposal_check_status(job, saved_proposal, preview=False))
        if not _body_matches_saved_proposal(job, body, saved_proposal):
            raise HTTPException(status_code=409, detail=_PDF_NOT_SAVED_BID)
        if isinstance(saved_proposal.get("audit"), dict):
            body["audit"] = copy.deepcopy(saved_proposal["audit"])
    # The saved bid's own calculation, not a newer one nothing points to.
    run = _proposal_run(job["id"], saved_proposal)
    if not run:
        raise HTTPException(status_code=409, detail=f"This bid's numbers haven't been saved yet. {CLICK_REGENERATE}")
    _ensure_audit_calculator_current(run, label="Proposal PDF")
    _validate_proposal_body_matches_job_source(job, body)
    traces = get_calculation_traces(job["id"], run_id=run["id"], limit=5000)
    proposal_traces = [
        trace for trace in traces
        if trace.get("entity_type") == "proposal" and trace.get("entity_key") == "proposal"
    ]
    by_field = {}
    for trace in proposal_traces:
        by_field[trace.get("output_field")] = trace
    required = ["subtotal", "tax_amount", "grand_total", "gpm_profit", "gpm_labor", "gpm_material", "manual_adjustment", "textura_amount"]
    missing_traces = [field for field in required if field not in by_field]
    if missing_traces:
        raise HTTPException(
            status_code=409,
            detail=f"The bid's saved numbers are incomplete. {CLICK_REGENERATE}",
        )
    for field in required:
        _trace_result_matches(by_field[field], body.get(field), label=f"the bid's {amount_word(field)}")
    _validate_proposal_body_against_trace(body, traces)


def _trace_result_matches(trace: dict | None, expected, *, label: str) -> None:
    """``label`` is plain words for the amount ("the bid's total", "Lobby labor line 2")."""
    if not trace:
        raise HTTPException(status_code=409, detail=f"The saved numbers for {label} are missing. {CLICK_REGENERATE}")
    expected_value = _as_number(expected)
    trace_value = _as_number(trace.get("result_value"))
    if expected_value is None:
        raise HTTPException(status_code=409, detail=f"{label[:1].upper()}{label[1:]} is not a valid number. {CLICK_REGENERATE}")
    if trace_value is None:
        raise HTTPException(status_code=409, detail=f"The saved numbers for {label} are missing. {CLICK_REGENERATE}")
    if abs(expected_value - trace_value) > 0.02:
        raise HTTPException(
            status_code=409,
            detail=f"{label[:1].upper()}{label[1:]} doesn't match the last saved bid. {CLICK_REGENERATE}",
        )


def _find_trace(
    traces: list[dict],
    *,
    entity_type: str,
    output_field: str,
    entity_key: str = None,
    entity_id=None,
    bundle_index: int = None,
    line_index: int = None,
) -> dict | None:
    matches = [
        trace for trace in traces
        if trace.get("entity_type") == entity_type and trace.get("output_field") == output_field
    ]
    if entity_key is not None:
        matches = [trace for trace in matches if str(trace.get("entity_key") or "") == str(entity_key)]
    if entity_id is not None:
        matches = [trace for trace in matches if str(trace.get("entity_id") or "") == str(entity_id)]
    if bundle_index is not None:
        traces_with_index = [trace for trace in matches if "bundle_index" in (trace.get("inputs") or {})]
        if traces_with_index:
            matches = [
                trace for trace in traces_with_index
                if (trace.get("inputs") or {}).get("bundle_index") == bundle_index
            ]
    if line_index is not None:
        traces_with_index = [trace for trace in matches if "line_index" in (trace.get("inputs") or {})]
        if traces_with_index:
            matches = [
                trace for trace in traces_with_index
                if (trace.get("inputs") or {}).get("line_index") == line_index
            ]
    return matches[-1] if matches else None


def _validate_proposal_body_against_trace(body: dict, traces: list[dict]) -> None:
    """Make sure every bundle/line number sent to the PDF has a matching trace."""
    bundles = [b for b in (body.get("bundles") or []) if isinstance(b, dict)]
    for bundle_index, bundle in enumerate(bundles):
        bundle_name = bundle.get("bundle_name") or f"bundle:{bundle_index}"
        bundle_fields = {
            "material_cost": bundle.get("material_cost"),
            "sundry_cost": bundle.get("sundry_cost"),
            "labor_cost": bundle.get("labor_cost"),
            "freight_cost": bundle.get("freight_override") if bundle.get("freight_override") is not None else bundle.get("freight_cost"),
            "gpm_labor_adder": bundle.get("gpm_labor_adder"),
            "gpm_material_adder": bundle.get("gpm_material_adder"),
            "gpm_adder": bundle.get("gpm_adder"),
            "taxable": bundle.get("taxable"),
            "tax_amount": bundle.get("tax_amount"),
            "total_price": bundle.get("price_override") if bundle.get("price_override") is not None else bundle.get("total_price"),
        }
        for field, expected in bundle_fields.items():
            trace = _find_trace(
                traces,
                entity_type="bundle",
                output_field=field,
                entity_key=bundle_name,
                bundle_index=bundle_index,
            )
            _trace_result_matches(trace, expected, label=f"the {amount_word(field)} of {bundle_name}")

        for line_index, material in enumerate(bundle.get("materials") or []):
            if not isinstance(material, dict):
                continue
            trace = _find_trace(
                traces,
                entity_type="material",
                output_field="extended_cost",
                entity_key=material.get("item_code") or material.get("description"),
                entity_id=material.get("id") or material.get("material_id"),
                bundle_index=bundle_index,
                line_index=line_index,
            )
            _trace_result_matches(trace, material.get("extended_cost"), label=f"{bundle_name}, material line {line_index + 1}")

        for line_index, sundry in enumerate(bundle.get("sundry_items") or []):
            if not isinstance(sundry, dict):
                continue
            material_id = sundry.get("material_id")
            sundry_name = sundry.get("sundry_name") or "sundry"
            trace = _find_trace(
                traces,
                entity_type="sundry",
                output_field="extended_cost",
                entity_key=f"{material_id}:{sundry_name}",
                entity_id=material_id,
                bundle_index=bundle_index,
                line_index=line_index,
            )
            _trace_result_matches(trace, sundry.get("extended_cost"), label=f"{bundle_name}, sundry line {line_index + 1}")

        for line_index, labor in enumerate(bundle.get("labor_items") or []):
            if not isinstance(labor, dict):
                continue
            material_id = labor.get("material_id")
            labor_description = labor.get("labor_description") or "labor"
            trace = _find_trace(
                traces,
                entity_type="labor",
                output_field="extended_cost",
                entity_key=f"{material_id}:{labor_description}",
                entity_id=material_id,
                bundle_index=bundle_index,
                line_index=line_index,
            )
            _trace_result_matches(trace, labor.get("extended_cost"), label=f"{bundle_name}, labor line {line_index + 1}")


# Plain words for the material fields a bid copies from the job.
_MATERIAL_FIELD_WORDS = {
    "item_code": "item code", "material_type": "type", "installed_qty": "quantity",
    "waste_pct": "waste %", "order_qty": "order quantity", "unit_price": "price",
    "extended_cost": "cost", "price_source": "price source", "quote_status": "quote status",
    "ai_confidence": "type", "quote_source_hash": "quote file", "quote_file_name": "quote file",
    "freight_per_unit": "freight", "freight_source": "freight", "fixture_count": "fixture count",
    "labor_rate_lf": "labor rate", "labor_catalog": "labor price", "tack_strip_lf": "tack strip",
    "seam_tape_lf": "seam tape", "pad_sy": "pad", "area_type": "area type",
    "is_mosaic": "mosaic setting", "is_penny_hex": "penny hex setting",
    "crack_isolation_sf": "crack isolation", "weld_rod_lf": "weld rod",
}


def _material_changed_detail(label: str, field: str) -> str:
    word = _MATERIAL_FIELD_WORDS.get(field, str(field).replace("_", " "))
    return f"The {word} of {label} changed after this bid was made. {CLICK_REGENERATE}"


def _validate_proposal_body_matches_job_source(job: dict, body: dict) -> None:
    """Reject stale proposal bodies after material source edits."""
    def _is_synthetic_material(material: dict) -> bool:
        identifiers = (
            material.get("item_code"),
            material.get("id"),
            material.get("material_id"),
        )
        return any(str(value or "").startswith("synthetic_") for value in identifiers)

    deleted_codes = {str(code) for code in (body.get("deleted_material_codes") or []) if code}
    current_by_id = {}
    current_by_code = {}
    for material in job.get("materials", []) or []:
        if not isinstance(material, dict):
            continue
        if _is_synthetic_material(material):
            continue
        if material.get("id") is not None:
            current_by_id[str(material.get("id"))] = material
        if material.get("item_code"):
            current_by_code[str(material.get("item_code"))] = material

    seen = set()
    compare_fields = (
        "item_code", "description", "material_type", "installed_qty", "unit", "waste_pct", "order_qty",
        "vendor", "unit_price", "extended_cost", "price_source", "quote_status",
        "ai_confidence", "quote_source_hash", "quote_file_name", "freight_per_unit",
        "freight_source", "fixture_count", "labor_rate_lf", "labor_catalog",
        "tack_strip_lf", "seam_tape_lf",
        "pad_sy", "area_type", "is_mosaic", "is_penny_hex",
        "crack_isolation_sf", "weld_rod_lf",
    )
    text_fields = {
        "item_code", "description", "material_type", "unit", "vendor",
        "price_source", "quote_status", "quote_source_hash", "quote_file_name",
        "freight_source", "labor_catalog", "area_type",
    }

    for bundle in body.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        for material in bundle.get("materials") or []:
            if not isinstance(material, dict):
                continue
            if _is_synthetic_material(material):
                continue
            item_code = str(material.get("item_code") or "")
            current = None
            if material.get("id") is not None:
                current = current_by_id.get(str(material.get("id")))
            if current is None and material.get("material_id") is not None:
                current = current_by_id.get(str(material.get("material_id")))
            if current is None and item_code:
                current = current_by_code.get(item_code)
            if current is None:
                raise HTTPException(
                    status_code=409,
                    detail=f"{item_code or 'A material'} is on the bid but is no longer in the job's materials. {CLICK_REGENERATE}",
                )

            seen.add(str(current.get("id")))
            label = item_code or current.get("description") or f"material {current.get('id')}"
            for field in compare_fields:
                # Per-material freight may be an accepted proposal edit. It is
                # fingerprinted and audited with the proposal, so comparing it
                # to the raw job-material value would incorrectly block a valid
                # PDF after the estimator explicitly changed freight.
                if field == "freight_per_unit" and material.get("freight_is_manual"):
                    continue
                current_value = current.get(field)
                body_value = material.get(field)
                if field in text_fields:
                    if str(current_value or "") != str(body_value or ""):
                        raise HTTPException(status_code=409, detail=_material_changed_detail(label, field))
                    continue
                current_number = _as_number(current_value)
                body_number = _as_number(body_value)
                if current_number is not None or body_number is not None:
                    if abs((current_number or 0) - (body_number or 0)) > 0.02:
                        raise HTTPException(status_code=409, detail=_material_changed_detail(label, field))
                elif str(current_value or "") != str(body_value or ""):
                    raise HTTPException(status_code=409, detail=_material_changed_detail(label, field))

    missing = []
    for material in job.get("materials", []) or []:
        if not isinstance(material, dict):
            continue
        if _is_synthetic_material(material):
            continue
        item_code = str(material.get("item_code") or "")
        if _job_material_key(material) in deleted_codes:
            continue
        material_id = str(material.get("id"))
        if material_id and material_id not in seen:
            missing.append(item_code or material.get("description") or material_id)
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{plain_list(missing)} {'is' if len(missing) == 1 else 'are'} in the job's materials but not "
                f"on the bid. {CLICK_REGENERATE}"
            ),
        )


PDF_NOT_MADE_YET = f"No PDF has been made for this bid yet. Click Generate PDF on {REVIEW_STEP}."
PDF_OUT_OF_DATE = f"The bid changed after this PDF was made. Click Generate PDF on {REVIEW_STEP} to make a new one."


def _pdf_out_of_date_detail(job: dict, proposal_data: dict, stored, identities) -> str:
    """PDF_OUT_OF_DATE, or which header details changed when only details the
    PDF prints (address, salesperson, ...) changed since it was made."""
    stamped = proposal_data.get("audit_source_job")
    changed = _print_details_changed(job, stamped)
    if changed and stored:
        as_saved = {**job, **stamped}
        if any(
            identity and stored == _proposal_source_fingerprint(as_saved, proposal_data, identity=identity)
            for identity in identities
        ):
            return (
                f"The job's {plain_list(changed)} changed after this PDF was made. "
                f"Click Generate PDF on {REVIEW_STEP} to make a new one."
            )
    return PDF_OUT_OF_DATE


def _validate_proposal_pdf_download_ready(job: dict) -> None:
    """Reject old proposal PDFs after the bid or required job fields change.

    A PDF made before an app update (or a rate or labor price edit) still
    counts while the bid itself is unchanged."""
    missing = _required_job_field_gaps(job)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Fill in the {plain_list([JOB_FIELD_LABELS.get(field, field) for field in missing])} on the job "
                "before downloading the PDF. Click Edit job details at the top of the page."
            ),
        )
    proposal_data = job.get("proposal_data")
    if not isinstance(proposal_data, dict) or not proposal_data.get("pdf_audit_run_id"):
        raise HTTPException(status_code=409, detail=PDF_NOT_MADE_YET)
    # The saved bid's own calculation: a Regenerate the editor didn't apply
    # left the bid, and so its PDF, as they were.
    latest = _proposal_run(job["id"], proposal_data)
    if not latest or int(latest["id"]) != int(proposal_data.get("pdf_audit_run_id")):
        raise HTTPException(status_code=409, detail=PDF_OUT_OF_DATE)
    stored = proposal_data.get("pdf_source_fingerprint")
    current_identity = _current_calculator_identity()
    if stored != _proposal_source_fingerprint(job, proposal_data, identity=current_identity):
        run_identity = _run_calculator_identity(latest)
        if not (
            stored and run_identity and run_identity != current_identity
            and stored == _proposal_source_fingerprint(job, proposal_data, identity=run_identity)
        ):
            raise HTTPException(
                status_code=409,
                detail=_pdf_out_of_date_detail(job, proposal_data, stored, (current_identity, run_identity)),
            )
    traces = get_calculation_traces(
        job["id"],
        run_id=latest["id"],
        entity_type="proposal",
        entity_key="proposal",
        limit=200,
    )
    by_field = {trace.get("output_field"): trace for trace in traces}
    totals = proposal_data.get("pdf_totals") or {}
    for field in ("subtotal", "tax_amount", "grand_total", "gpm_profit", "gpm_labor", "gpm_material", "manual_adjustment", "textura_amount"):
        try:
            _trace_result_matches(by_field.get(field), totals.get(field), label=f"the bid's {amount_word(field)}")
        except HTTPException:
            raise HTTPException(status_code=409, detail=PDF_OUT_OF_DATE) from None


@app.post("/api/jobs/{job_id}/proposal/generate")
@audit_route("proposal.generate")
def api_generate_proposal(job_id: str):
    """Auto-bundle materials into proposal line items.

    Preserves AI-rewritten bundle names and descriptions from prior runs
    by snapshotting them keyed on material item_code before regeneration,
    then re-applying after.
    """
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    trace = AuditTraceBuilder(job["id"])

    # ── Snapshot existing rewrites so Regenerate doesn't destroy them ──────
    # Key by the first material's item_code per bundle.
    existing_rewrites: dict[str, dict] = {}
    existing_by_codes: dict[tuple[str, ...], list[dict]] = {}
    existing_pd = job.get("proposal_data") or {}
    has_saved_accepted_proposal = bool(existing_pd.get("bundles"))
    # Regenerate keeps the bid's own tax rate, GPM and Textura fee, so what the
    # job said about them stays as the saved bid had it (read before the
    # sundry and labor lines are redone below).
    kept_source = _proposal_source_job(job, existing_pd) if has_saved_accepted_proposal else None
    # A first generation is saved only if nobody saved a proposal meanwhile.
    base_proposal_rev = int(job.get("proposal_rev") or 0)
    for b in (existing_pd.get("bundles") or []):
        mats = b.get("materials") or []
        if not mats:
            continue
        codes = tuple(sorted(
            str(m.get("item_code") or m.get("id") or m.get("material_id"))
            for m in mats
            if m.get("item_code") or m.get("id") or m.get("material_id")
        ))
        if codes:
            existing_by_codes.setdefault(codes, []).append(b)
        key = str(mats[0].get("item_code") or mats[0].get("id") or mats[0].get("material_id") or "").strip()
        if not key:
            continue
        existing_rewrites[key] = {
            "bundle_name": b.get("bundle_name"),
            "description_text": b.get("description_text"),
        }

    # ── Carry forward deleted-bundle / deleted-material-code flags ─────────
    # Users mark these via the UI's delete action; they must survive regenerate.
    deleted_bundle_names = set(existing_pd.get("deleted_bundles") or [])
    raw_deleted_bundle_reasons = existing_pd.get("deleted_bundle_reasons")
    deleted_bundle_reasons = dict(raw_deleted_bundle_reasons) if isinstance(raw_deleted_bundle_reasons, dict) else {}
    deleted_material_codes = set(existing_pd.get("deleted_material_codes") or [])
    raw_deleted_reasons = existing_pd.get("deleted_material_reasons")
    deleted_material_reasons = dict(raw_deleted_reasons) if isinstance(raw_deleted_reasons, dict) else {}

    # Always recalculate sundries and labor to reflect latest rules/flags
    materials = job.get("materials", [])
    loaded_materials = copy.deepcopy(materials)
    unit_count = job.get("unit_count", 0) or 0
    tub_shower_count = job.get("tub_shower_count", 0) or 0

    # Re-apply current waste rules to materials so rule changes propagate.
    # Skip piece-priced EA items (Schluter sticks) whose order_qty isn't waste-based.
    import json as _json
    _waste_data = get_company_rate("waste_factors")
    _waste_factors = _json.loads(_waste_data) if _waste_data else WASTE_FACTORS
    waste_touched = False
    for mat in materials:
        mtype = mat.get("material_type", "")
        new_waste = _waste_factors.get(mtype)
        if new_waste is None:
            continue
        mat_unit = (mat.get("unit") or "").upper()
        if mat_unit == "EA" and mtype != "sound_mat":
            continue  # Piece-counted materials — waste doesn't apply to order_qty
        old_waste = mat.get("waste_pct", 0) or 0
        if abs(new_waste - old_waste) < 1e-6:
            continue
        installed_qty = mat.get("installed_qty", 0) or 0
        mat["waste_pct"] = new_waste
        mat["order_qty"] = round(installed_qty * (1 + new_waste), 2)
        unit_price = mat.get("unit_price", 0) or 0
        if is_piece_priced_transition(mat):
            # Rule/price-book transitions are priced per stick; this (non-EA) row
            # keeps order_qty in LF, so bill the sticks for the new LF, never LF x stick price.
            pieces = _transition_pieces(mat["order_qty"], mat.get("vendor"), mat.get("fixture_count", 0))
            mat["extended_cost"] = round(pieces * unit_price, 2)
            cost_formula = "transition_pieces(order_qty, vendor, fixture_count) * unit_price"
            cost_inputs = {
                "order_qty": mat["order_qty"],
                "vendor": mat.get("vendor") or "",
                "fixture_count": mat.get("fixture_count", 0) or 0,
                "piece_count": pieces,
                "unit_price": unit_price,
            }
        else:
            mat["extended_cost"] = round(mat["order_qty"] * unit_price, 2)
            cost_formula = "order_qty * unit_price"
            cost_inputs = {"order_qty": mat["order_qty"], "unit_price": unit_price}
        trace.record(
            entity_type="material",
            entity_id=mat.get("id"),
            entity_key=mat.get("item_code"),
            output_field="order_qty",
            formula="installed_qty * (1 + waste_pct)",
            inputs={"installed_qty": installed_qty, "waste_pct": new_waste, "old_waste_pct": old_waste},
            result=mat["order_qty"],
            rule_id=f"waste_factor:{mtype}",
            source="waste_factors",
        )
        trace.record(
            entity_type="material",
            entity_id=mat.get("id"),
            entity_key=mat.get("item_code"),
            output_field="extended_cost",
            formula=cost_formula,
            inputs=cost_inputs,
            result=mat["extended_cost"],
            rule_id=f"material:{mtype}:extended_cost",
            source=mat.get("price_source") or "waste_factors",
        )
        waste_touched = True

    # Stamp job-level counts onto materials so sundry_calc can use them
    for mat in materials:
        mtype = mat.get("material_type", "")
        if mtype == "backsplash":
            mat["unit_count"] = unit_count
        if mtype == "tub_shower_surround":
            mat["tub_shower_total"] = tub_shower_count  # total tubs/showers on job

    sundries = labor_items = None
    if materials:
        sundries = calculate_sundries_for_materials(materials, trace=trace)
        labor_items = calculate_labor_for_materials(materials, trace=trace)
    # The new waste figures, sundries and labor are saved together. Only the
    # waste fields this step changed are written onto the lines, and only on
    # lines nobody changed meanwhile (compare-and-swap).
    with job_write(db_id, action="proposal.generate", scopes=("materials", "sundries", "labor"),
                   summary="Recalculated waste, sundries and labor for the proposal") as tx:
        if has_saved_accepted_proposal:
            # Keep the accepted proposal as a version before regenerate reworks it.
            tx.proposal_version_id = proposal_versions.snapshot(tx.conn, db_id, "before_regenerate")
        if waste_touched:
            waste_conflicts = _save_step_results(tx, loaded_materials, materials)["conflicts"]
            if waste_conflicts:
                tx.set_summary("Recalculated waste, sundries and labor for the proposal" + conflict_note(waste_conflicts))
        if sundries is not None:
            save_sundries(db_id, sundries, conn=tx.conn)
            save_labor(db_id, labor_items, conn=tx.conn)
    if materials:
        # Reload job with freshly calculated sundries/labor
        job = load_job(db_id)

    current_company_rates = get_all_company_rates()
    # Bundles copy the lines they hold; the lines' row bookkeeping
    # (row_version, updated_at, updated_by) is not part of the proposal.
    bundle_source = {
        **job,
        **{part: [stable_ids.without_row_meta(row) for row in job.get(part) or []]
           for part in ("materials", "sundries", "labor")},
    }
    proposal = generate_proposal_data(
        job["id"],
        bundle_source,
        trace=trace,
        freight_rates_override=current_company_rates.get("freight_rates") or FREIGHT_RATES,
    )

    # ── Re-apply snapshotted rewrites where item_codes match ───────────────
    for b in proposal.get("bundles", []):
        mats = b.get("materials") or []
        if not mats:
            continue
        codes = tuple(sorted(
            str(m.get("item_code") or m.get("id") or m.get("material_id"))
            for m in mats
            if m.get("item_code") or m.get("id") or m.get("material_id")
        ))
        candidates = existing_by_codes.get(codes, [])
        named_candidates = [candidate for candidate in candidates if candidate.get("bundle_name") == b.get("bundle_name")]
        exact = named_candidates[0] if len(named_candidates) == 1 else (candidates[0] if len(candidates) == 1 else None)
        key = str(mats[0].get("item_code") or mats[0].get("id") or mats[0].get("material_id") or "").strip()
        rw = exact if codes else existing_rewrites.get(key)
        if rw:
            if rw.get("bundle_name"):
                b["bundle_name"] = rw["bundle_name"]
            if rw.get("description_text"):
                b["description_text"] = rw["description_text"]
        if exact:
            for field in ("price_override", "freight_override", "stair_count", "stair_labor_type"):
                if exact.get(field) is not None:
                    b[field] = exact[field]

    # Each new bundle keeps the uid of the saved bundle it matches (same
    # materials and name, same materials, ...); the others get new ones.
    stable_ids.carry_bundle_uids(existing_pd.get("bundles"), proposal.get("bundles"))

    # Carry deletion lists back so the FE save can persist them.
    # The shared normalizer below recalculates totals once after these flags and
    # any exact-match accepted overrides have been restored.
    if deleted_bundle_names or deleted_material_codes:
        proposal["deleted_bundles"] = sorted(deleted_bundle_names)
        proposal["deleted_bundle_reasons"] = deleted_bundle_reasons
        proposal["deleted_material_codes"] = sorted(deleted_material_codes)
        proposal["deleted_material_reasons"] = deleted_material_reasons
        trace.record(
            entity_type="proposal",
            entity_id=job["id"],
            entity_key="proposal",
            output_field="bundle_count",
            formula="filter generated bundles by deleted_bundles and deleted_material_codes before totals",
            inputs={
                "deleted_bundles": sorted(deleted_bundle_names),
                "deleted_material_codes": sorted(deleted_material_codes),
            },
            result=len(proposal.get("bundles") or []),
            rule_id="proposal:deleted_bundle_filter",
            source="proposal_bundler",
        )

    for field in ("notes", "terms", "exclusions"):
        if field in existing_pd:
            proposal[field] = list(existing_pd.get(field) or [])
    accepted_structure_count = apply_accepted_bundle_structure(proposal, existing_pd) if has_saved_accepted_proposal else 0
    if accepted_structure_count:
        trace.record(
            entity_type="proposal",
            entity_id=job["id"],
            entity_key="proposal",
            output_field="accepted_structural_edits",
            formula="rebuild accepted bundle order/grouping from raw engine bundles without copying accepted totals",
            inputs={"accepted_proposal_present": True},
            result=accepted_structure_count,
            rule_id="proposal:accepted_bundle_structure",
            source="proposal_regeneration",
        )
    accepted_edit_count = apply_accepted_numeric_edits(proposal, existing_pd) if has_saved_accepted_proposal else 0
    if accepted_edit_count:
        trace.record(
            entity_type="proposal",
            entity_id=job["id"],
            entity_key="proposal",
            output_field="accepted_numeric_edits",
            formula="reapply explicit estimator inputs and overrides after raw bundle generation",
            inputs={"accepted_proposal_present": True},
            result=accepted_edit_count,
            rule_id="proposal:accepted_numeric_edits",
            source="proposal_regeneration",
        )
    # Rebuilt bundles took their accepted bundle's uid; make sure every bundle
    # has one and no two share one.
    stable_ids.carry_bundle_uids([], proposal.get("bundles"))

    _append_proposal_totals_snapshot(trace, job["id"], proposal)

    # What the job said when these numbers were made. Kept on the run too: the
    # editor sends it back when it applies this Regenerate (_saved_source_job).
    made_from = _bid_source_job(job)
    if kept_source:
        for field in _BID_OWN_JOB_FIELDS:
            made_from[field] = kept_source.get(field) or 0
        if kept_source.get("guessed"):
            made_from["guessed"] = True
    run_id = create_calculation_run(
        job["id"],
        "proposal_generation",
        metadata=_audit_metadata({"endpoint": "proposal/generate", "source_job": made_from}),
    )
    trace_count = save_calculation_traces(job["id"], run_id, trace.records)
    summary = trace.summary()
    complete_calculation_run(run_id, summary=summary)
    proposal["audit"] = {
        "run_id": run_id,
        "trace_count": trace_count,
        "summary": summary,
    }
    _stamp_proposal_source(job, proposal, source_job={**made_from, "run_id": run_id})
    # A regenerate must never overwrite the accepted proposal before the UI has
    # merged its full manual structure and saved it. Initial generation is safe
    # to persist immediately because there is no accepted proposal yet.
    if not has_saved_accepted_proposal:
        try:
            prior_revision = max(0, int(existing_pd.get("_server_revision") or 0))
        except (TypeError, ValueError):
            prior_revision = 0
        proposal["_server_revision"] = prior_revision + 1
        bundle_count = len(proposal.get("bundles") or [])
        grand_total = _as_number(proposal.get("grand_total")) or 0
        try:
            with job_write(db_id, action="proposal.generate", scopes=("proposal",),
                           summary=f"Generated the proposal: {bundle_count} bundles, total ${grand_total:,.2f}") as tx:
                set_proposal_data(tx.conn, db_id, proposal, expected_rev=base_proposal_rev)
                tx.proposal_version_id = proposal_versions.snapshot(tx.conn, db_id, "generate")
        except ProposalConflictError:
            raise HTTPException(
                status_code=409,
                detail="Someone saved this proposal while it was being generated. Reload the job and generate it again.",
            )
    return proposal


@app.post("/api/jobs/{job_id}/proposal/pdf")
@audit_route("proposal.pdf", "proposal.audit_refresh")
async def api_generate_proposal_pdf(job_id: str, request: Request):
    """Generate proposal PDF from edited bundle data."""
    raw_body = await request.body()
    return await run_in_threadpool(_generate_proposal_pdf, job_id, raw_body)


def _generate_proposal_pdf(job_id: str, raw_body: bytes) -> dict:
    import json as _json
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    body = json.loads(raw_body)
    _validate_proposal_pdf_ready(job, body)
    # Build proposal data from the edited bundles sent by frontend
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
        "salesperson": job.get("salesperson") or "Standard Interiors",
    }
    # Estimate header fields (Quote # falls back to the job id in the PDF).
    for field in JOB_ESTIMATE_HEADER_FIELDS:
        job_info[field] = str(job.get(field) or "").strip()
    # The header 'Date' box is the quote's date, which stays the same on every
    # re-print: a stored quote date, else the first proposal generation, else
    # the job's creation. The PDF uses the print date only if none is set.
    job_info["quote_date"] = (
        str(job.get("quote_date") or "").strip()
        or get_first_calculation_run_started_at(job["id"], {"proposal_generation"})
        or str(job.get("created_at") or "").strip()
    )
    # The job's own "X is excluded at this time" lines print with the notes.
    try:
        job_exclusions = _json.loads(job.get("exclusions") or "[]")
    except (TypeError, ValueError):
        job_exclusions = []
    job_info["excluded_at_this_time"] = [
        str(line).strip() for line in (job_exclusions if isinstance(job_exclusions, list) else [])
        if str(line or "").strip()
    ]

    # The printed bundles keep their uids (the saved bundle's uid when the
    # client didn't send one), so the saved proposal keeps its identities.
    bundles = body.get("bundles", [])
    stable_ids.carry_bundle_uids((job.get("proposal_data") or {}).get("bundles"), bundles)
    proposal_data = {
        "job_info": job_info,
        "bundles": bundles,
        "subtotal": body.get("subtotal", 0),
        "tax_rate": body.get("tax_rate", 0),
        "tax_amount": body.get("tax_amount", 0),
        "grand_total": body.get("grand_total", 0),
        "gpm_pct": body.get("gpm_pct", 0),
        "gpm_profit": body.get("gpm_profit", 0),
        "gpm_labor": body.get("gpm_labor", 0),
        "gpm_material": body.get("gpm_material", 0),
        "manual_adjustment": body.get("manual_adjustment", 0),
        "textura_fee": body.get("textura_fee", 0),
        "textura_amount": body.get("textura_amount", 0),
        "notes": body.get("notes", []),
        "terms": body.get("terms", []),
        "exclusions": body.get("exclusions", []),
        "deleted_bundles": body.get("deleted_bundles", []),
        "deleted_bundle_reasons": body.get("deleted_bundle_reasons", {}),
        "deleted_material_codes": body.get("deleted_material_codes", []),
        "deleted_material_reasons": body.get("deleted_material_reasons", {}),
        "audit": body.get("audit", (job.get("proposal_data") or {}).get("audit", {})),
        "_client_session_id": body.get("_client_session_id") or (job.get("proposal_data") or {}).get("_client_session_id", ""),
        "_client_edit_version": body.get("_client_edit_version") or (job.get("proposal_data") or {}).get("_client_edit_version", 0),
        "_client_save_sequence": body.get("_client_save_sequence") or (job.get("proposal_data") or {}).get("_client_save_sequence", 0),
        "_server_revision": (job.get("proposal_data") or {}).get("_server_revision", 0),
        "pdf_generated_at": datetime.now(timezone.utc).isoformat(),
    }
    saved_before_pdf = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    _stamp_proposal_source(job, proposal_data, source_job=_proposal_source_job(job, saved_before_pdf))
    pdf_run = _proposal_run(job["id"], proposal_data)
    if pdf_run:
        proposal_data["pdf_audit_run_id"] = pdf_run["id"]
        proposal_data["pdf_ruleset_version"] = (pdf_run.get("metadata") or {}).get("ruleset_version")
        proposal_data["pdf_source_fingerprint"] = _proposal_source_fingerprint(job, proposal_data)
        proposal_data["pdf_totals"] = {
            "subtotal": body.get("subtotal", 0),
            "tax_amount": body.get("tax_amount", 0),
            "grand_total": body.get("grand_total", 0),
            "gpm_profit": body.get("gpm_profit", 0),
            "gpm_labor": body.get("gpm_labor", 0),
            "gpm_material": body.get("gpm_material", 0),
            "manual_adjustment": body.get("manual_adjustment", 0),
            "textura_amount": body.get("textura_amount", 0),
        }

    # Draw the PDF into a temp file first. It only becomes the job's latest
    # PDF (new file + receipt) if the proposal it prints is saved too.
    draft = _draft_job_pdf(job["id"], "proposal", lambda path: generate_proposal_pdf(proposal_data, path))

    # Save proposal data to job, only if nobody saved the proposal while the
    # PDF was being made (that PDF would print an older proposal).
    summary = f"Proposal generated: {len(proposal_data['bundles'])} bundles, total ${proposal_data['grand_total']:,.2f}"
    try:
        with job_write(job["id"], action="proposal.pdf", scopes=("proposal",), summary=summary,
                       extra={"pdf": {"file_hash": draft["sha256"]}}) as tx:
            tx.force_record()
            set_proposal_data(tx.conn, job["id"], proposal_data, expected_rev=int(job.get("proposal_rev") or 0))
            log_activity(job["id"], "proposal_generated", summary,
                         {"bundle_count": len(proposal_data["bundles"]), "grand_total": proposal_data["grand_total"]})
            # The version this PDF prints (the latest one when nothing changed
            # since); the version and the PDF receipt point at each other.
            version_id = proposal_versions.snapshot(tx.conn, job["id"], "pdf")
            artifact_id = _publish_job_pdf(job["id"], draft, "proposal_pdf", conn=tx.conn,
                                           grand_total=proposal_data.get("grand_total"),
                                           proposal_version_id=version_id)
            proposal_versions.link_artifact(tx.conn, version_id, artifact_id)
            tx.proposal_version_id = version_id
            tx.extra["pdf"]["artifact_id"] = artifact_id
            tx.extra["pdf"]["proposal_version_id"] = version_id
    except ProposalConflictError:
        raise HTTPException(
            status_code=409,
            detail="Cannot generate PDF because the proposal was saved again while the PDF was being made. Try again.",
        )
    finally:
        _discard_job_pdf(draft)

    return {"status": "ok", "pdf_url": f"/api/jobs/{job_id}/proposal.pdf", "artifact_id": artifact_id,
            "proposal_version_id": version_id}


@app.get("/api/jobs/{job_id}/proposal.pdf")
def api_download_proposal_pdf(job_id: str):
    """Download the generated proposal PDF."""
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _validate_proposal_pdf_download_ready(job)
    # The latest print; earlier ones are under /artifacts.
    latest = _latest_job_pdf(job["id"], "proposal_pdf")
    if not latest or not os.path.exists(latest[0]):
        raise HTTPException(status_code=404, detail="PDF not found. Generate proposal first.")
    pdf_path = latest[0]
    _require_artifact_receipt(job["id"], pdf_path, "proposal_pdf")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{job['project_name']} Proposal.pdf",
    )


# ── Printed PDFs (every print is kept) ───────────────────────────────────────
_PDF_KIND_LABELS = {"proposal_pdf": "Proposal", "bid_pdf": "Bid"}


def _artifact_person(username) -> str:
    username = str(username or "").strip()
    if not username:
        return ""
    return "System" if username.startswith("system:") else username


def _pdf_artifact_item(job_id: int, receipt: dict, latest_ids: set) -> dict:
    path = _checked_artifact_path(receipt.get("artifact_path") or "")
    return {
        "id": receipt["id"],
        "kind": receipt["artifact_kind"],
        "label": _PDF_KIND_LABELS.get(receipt["artifact_kind"], receipt["artifact_kind"]),
        "created_at": receipt.get("created_at"),
        "created_by": receipt.get("created_by"),
        "created_by_name": receipt.get("created_by_name") or _artifact_person(receipt.get("created_by")),
        "grand_total": receipt.get("grand_total"),
        "proposal_version_id": receipt.get("proposal_version_id"),
        "sha256": receipt.get("file_hash"),
        "size": receipt.get("file_size"),
        "request_id": receipt.get("request_id"),
        "is_latest": receipt["id"] in latest_ids,
        # The file is gone from storage (its download says so too). Checked
        # without reading the file; a damaged file shows when downloaded.
        "file_missing": not (path and os.path.isfile(path)),
        "download_url": f"/api/jobs/{job_id}/artifacts/{receipt['id']}/download",
    }


@app.get("/api/jobs/{job_id}/artifacts")
def api_list_job_artifacts(job_id: str, kind: Optional[str] = None, include_deleted: bool = False):
    """Every printed PDF of a bid, newest first. ``kind`` = proposal_pdf or bid_pdf (default both).

    /proposal.pdf and /bid.pdf keep serving the latest of each kind.
    """
    db_id = _resolve_job_id(job_id, include_deleted=include_deleted)
    kind = (kind or "").strip() or None
    if kind is not None and kind not in PDF_ARTIFACT_KINDS:
        raise HTTPException(status_code=400, detail="kind must be proposal_pdf or bid_pdf.")
    receipts = [
        receipt for receipt in list_job_artifacts(db_id, kind)
        if receipt.get("artifact_kind") in PDF_ARTIFACT_KINDS
    ]
    latest_ids: set = set()
    seen_kinds: set = set()
    for receipt in receipts:  # newest first
        if receipt["artifact_kind"] not in seen_kinds:
            seen_kinds.add(receipt["artifact_kind"])
            latest_ids.add(receipt["id"])
    return [_pdf_artifact_item(db_id, receipt, latest_ids) for receipt in receipts]


@app.get("/api/jobs/{job_id}/artifacts/{artifact_id}/download")
def api_download_job_artifact(job_id: str, artifact_id: int, include_deleted: bool = False):
    """Download one printed PDF exactly as it was printed (checked against its saved hash)."""
    db_id = _resolve_job_id(job_id, include_deleted=include_deleted)
    receipt = get_job_artifact(db_id, artifact_id)
    if not receipt or receipt.get("artifact_kind") not in PDF_ARTIFACT_KINDS:
        raise HTTPException(status_code=404, detail="That PDF isn't in this bid's print history.")
    path = _checked_artifact_path(receipt.get("artifact_path") or "")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="This PDF's file is missing from storage.")
    if _file_hash(path) != receipt.get("file_hash"):
        raise HTTPException(
            status_code=409,
            detail="This PDF no longer matches the copy that was printed, so it can't be downloaded.",
        )
    conn = _get_conn()
    try:
        found = conn.execute("SELECT project_name FROM jobs WHERE id=?", (db_id,)).fetchone()
    finally:
        conn.close()
    printed_on = str(receipt.get("created_at") or "")[:10]
    label = _PDF_KIND_LABELS.get(receipt["artifact_kind"], "PDF")
    name = f"{(found['project_name'] if found else '') or f'Job {db_id}'} {label}"
    if printed_on:
        name += f" {printed_on}"
    return FileResponse(path, media_type="application/pdf", filename=f"{name} ({artifact_id}).pdf")


# ── Proposal versions ────────────────────────────────────────────────────────
# Saved copies of the proposal (proposal_versions.py): anyone logged in can
# list, preview, compare, name and restore them.
class ProposalVersionLabel(BaseModel):
    label: Optional[str] = None


_VERSION_NOT_FOUND = "That version isn't in this bid's proposal history."
# A restore that finds another save landed first tries again on top of it.
_RESTORE_RETRY_SECONDS = 30


def _proposal_version_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except proposal_versions.VersionNotFoundError:
        raise HTTPException(status_code=404, detail=_VERSION_NOT_FOUND)


def _link_sent_version(tx, events) -> None:
    """A "sent" event records the proposal version that went out.

    When a proposal PDF was made, that PDF is what went out, so the event
    points at the version the PDF was printed from (and says so when the
    proposal changed after that PDF). With no PDF, the proposal as it is now
    is saved as a "sent" version (or the latest version, when nothing changed).
    """
    for event_type, details in events:
        if event_type != "sent":
            continue
        version_id = None
        pdf = details.get("pdf") if isinstance(details.get("pdf"), dict) else {}
        pdf_version_id = pdf.get("proposal_version_id")
        if pdf_version_id is not None:
            printed = tx.conn.execute(
                "SELECT id, content_hash FROM proposal_versions WHERE id = ? AND job_id = ?",
                (pdf_version_id, tx.job_id),
            ).fetchone()
            if printed is not None:
                version_id = int(printed["id"])
                now = proposal_versions.capture(tx.conn, tx.job_id)
                details["proposal_changed_since_pdf"] = bool(
                    now is not None and now["content_hash"] != printed["content_hash"]
                )
        if version_id is None:
            version_id = proposal_versions.snapshot(tx.conn, tx.job_id, "sent")
        if version_id is not None:
            details["proposal_version_id"] = version_id
            tx.proposal_version_id = version_id


@app.get("/api/jobs/{job_id}/proposal/versions")
def api_list_proposal_versions(job_id: str, include_deleted: bool = False):
    """Saved versions of the bid's proposal, newest first."""
    db_id = _resolve_job_id(job_id, include_deleted=include_deleted)
    return proposal_versions.list_versions(db_id)


@app.get("/api/jobs/{job_id}/proposal/versions/{version_id}")
def api_get_proposal_version(job_id: str, version_id: int, include_deleted: bool = False,
                             include_materials: bool = False):
    """One version with its proposal_data and job_fields (``include_materials=1``
    adds the material lines it was priced from)."""
    db_id = _resolve_job_id(job_id, include_deleted=include_deleted)
    return _proposal_version_call(
        proposal_versions.get_version, db_id, version_id, include_materials=include_materials,
    )


@app.get("/api/jobs/{job_id}/proposal/versions/{version_id}/diff")
def api_diff_proposal_version(job_id: str, version_id: int, against: str = "current",
                              include_deleted: bool = False):
    """What changed from this version to the current proposal
    (``against=current``) or to another version (``against=<version id>``)."""
    db_id = _resolve_job_id(job_id, include_deleted=include_deleted)
    before = _proposal_version_call(proposal_versions.version_state, db_id, version_id)
    target = str(against or "current").strip().lower()
    if target == "current":
        after = proposal_versions.current_state(db_id)
    else:
        try:
            other_id = int(target)
        except ValueError:
            raise HTTPException(status_code=400, detail="Compare with 'current' or another version's id.")
        after = _proposal_version_call(proposal_versions.version_state, db_id, other_id)
    result = proposal_versions.diff_states(before, after)
    result["version_id"] = version_id
    result["against"] = target
    return result


@app.patch("/api/jobs/{job_id}/proposal/versions/{version_id}")
@audit_route("proposal.version_label")
def api_label_proposal_version(job_id: str, version_id: int, body: ProposalVersionLabel):
    """Name a version (or clear its name with an empty label)."""
    db_id = _resolve_job_id(job_id)
    try:
        label = proposal_versions.clean_label(body.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    with entity_write("proposal_version", version_id, proposal_versions.label_loader(db_id),
                      "proposal.version_label", job_id=db_id) as tx:
        if tx.before is None:
            raise HTTPException(status_code=404, detail=_VERSION_NOT_FOUND)
        number = tx.before["version_no"]
        tx.set_summary(f'Named proposal version {number} "{label}"' if label
                       else f"Removed the name of proposal version {number}")
        proposal_versions.set_label(tx.conn, db_id, version_id, label)
        tx.proposal_version_id = version_id
    return proposal_versions.get_item(db_id, version_id)


@app.post("/api/jobs/{job_id}/proposal/versions/{version_id}/restore")
@audit_route("proposal.restore")
def api_restore_proposal_version(job_id: str, version_id: int):
    """Put an older version of the proposal back (anyone logged in can).

    The current proposal is kept as a version first ("before_restore"), and
    the restored proposal is saved as a new version ("restore"), so nothing
    is lost. Bundles keep their uids; totals and the audit receipt are worked
    out again. Returns {job, version (the new one), ...}.
    """
    db_id = _resolve_job_id(job_id)
    source = _proposal_version_call(proposal_versions.version_state, db_id, version_id)
    give_up_at = time.monotonic() + _RESTORE_RETRY_SECONDS
    while True:
        result = _try_restore_proposal_version(db_id, version_id, source)
        if result is not None:
            break
        if time.monotonic() >= give_up_at:
            raise JobBusyError()
    return {"job": api_get_job(str(db_id)), **result}


def _try_restore_proposal_version(db_id: int, version_id: int, source: dict) -> dict | None:
    """One restore attempt; None when another save landed after the proposal
    was read, so it must run again on top of that save."""
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    base_proposal_rev = int(job.get("proposal_rev") or 0)
    current = job.get("proposal_data") if isinstance(job.get("proposal_data"), dict) else {}
    restored = proposal_versions.restorable_proposal(source["proposal"], current)
    normalize_proposal_totals(restored)
    info = source["version"]
    now_state = proposal_versions.current_state(db_id)
    notes = {
        "restored_from_version_id": version_id,
        "materials_changed_since": bool(source.get("materials_fingerprint"))
        and source.get("materials_fingerprint") != now_state.get("materials_fingerprint"),
        # Job fields are not part of a restore (only the proposal is): these
        # differ between the version and the bid now.
        "job_fields_differ": sorted(
            key for key in set(source.get("job_fields") or {}) | set(now_state.get("job_fields") or {})
            if not audit.values_equal((source.get("job_fields") or {}).get(key), (now_state.get("job_fields") or {}).get(key))
        ),
    }
    if proposal_versions.proposal_hash(restored) == proposal_versions.proposal_hash(current):
        audit.note_checked(db_id)  # already the current proposal: nothing to save
        return {"version": proposal_versions.get_item(db_id, version_id), "unchanged": True,
                "before_restore_version_id": None, **notes}

    audit_result = _record_proposal_editor_audit(db_id, current, restored)
    if audit_result.get("audit_trace"):
        restored["audit"] = {
            "run_id": audit_result["audit_trace"]["run"]["id"],
            "trace_count": audit_result["trace_count"],
            "summary": audit_result["audit_trace"].get("audit", {}),
        }
    # The restored numbers were made from the job as the version saw it (an
    # older version didn't keep that: its own tax rate, GPM and Textura fee).
    version_source = (source.get("proposal") or {}).get("source_job")
    _stamp_proposal_source(job, restored, source_job=(
        copy.deepcopy(version_source) if _is_source_job(version_source)
        else _legacy_source_job(job, restored, unchanged=False)
    ))
    name = f' "{info["label"]}"' if info.get("label") else ""
    summary = f"Restored proposal version {info['version_no']}{name}"
    try:
        with job_write(db_id, action="proposal.restore", scopes=("proposal",), summary=summary,
                       extra={"restored_from": {"version_id": version_id, "version_no": info["version_no"],
                                                "label": info.get("label"), "reason": info.get("reason")}}) as tx:
            if int(tx.row.get("proposal_rev") or 0) != base_proposal_rev:
                raise ProposalConflictError()
            tx.force_record()
            # Keep what's there now, then put the version back.
            before_id = proposal_versions.snapshot(tx.conn, db_id, "before_restore")
            stored = _stored_proposal(tx.row.get("proposal_data"))
            # A new server revision and a session no browser tab has: other
            # open editors get "reload" instead of saving over the restore.
            restored["_server_revision"] = _nonnegative_int(stored.get("_server_revision")) + 1
            restored["_client_session_id"] = f"restore-{uuid.uuid4().hex[:12]}"
            restored["_client_edit_version"] = 0
            restored["_client_save_sequence"] = 0
            set_proposal_data(tx.conn, db_id, restored, expected_rev=base_proposal_rev)
            restore_id = proposal_versions.snapshot(
                tx.conn, db_id, "restore", dedupe=False, restored_from_version_id=version_id,
            )
            tx.proposal_version_id = restore_id
            tx.extra["before_restore_version_id"] = before_id
            tx.extra["restore_version_id"] = restore_id
    except ProposalConflictError:
        return None
    return {
        "version": proposal_versions.get_item(db_id, restore_id),
        "unchanged": False,
        "before_restore_version_id": before_id,
        **notes,
    }


@app.post("/api/labor-catalog/upload")
@audit_route("labor_catalog.upload")
def api_upload_labor_catalog(file: UploadFile = File(...)):
    """Upload labor catalog (Excel or PDF)."""
    file_path = os.path.join(UPLOAD_DIR, f"labor_catalog_{file.filename}")
    with open(file_path, "wb") as f:
        content = file.file.read()
        f.write(content)

    ext = os.path.splitext(file.filename)[1].lower()
    # Read the file first (a PDF goes through AI), then save it in one audited step.
    try:
        if ext == ".pdf":
            settings = get_settings()
            api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
            model = settings.get("openai_model", "gpt-5-mini")
            catalog = load_labor_catalog_from_pdf(file_path, api_key=api_key, model=model, save=False)
        elif ext in (".xlsx", ".xls"):
            catalog = load_labor_catalog(file_path, save=False)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Upload .pdf or .xlsx")
    except HTTPException:
        raise
    except AIError as e:
        raise HTTPException(status_code=400, detail=f"{e.user_message} Nothing was changed.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse labor catalog: {e}")

    # Saving replaces the whole catalog, so refuse a read that looks incomplete.
    if not catalog:
        raise HTTPException(status_code=400, detail="No labor rates were found in that file. Nothing was changed.")
    current_count = len(get_labor_catalog_entries())
    if ext == ".pdf" and current_count and len(catalog) < current_count / 2:
        raise HTTPException(
            status_code=400,
            detail=(f"That file gave only {len(catalog)} labor rates, but the catalog has {current_count}. "
                    "Nothing was changed. Check the file, or upload the catalog as Excel."),
        )

    with entity_write("labor_catalog", WHOLE_LIST, _load_labor_catalog, "labor_catalog.upload",
                      summary=f"Uploaded the labor catalog from {file.filename} ({_count(len(catalog), 'entry', 'entries')})",
                      extra={"file_name": file.filename}) as tx:
        save_labor_catalog_entries(catalog, conn=tx.conn)
    return {"message": "Labor catalog loaded", "entries": len(catalog)}


# ── Exclusions ────────────────────────────────────────────────────────────────

class ExclusionsUpdate(BaseModel):
    exclusions: list[str]


@app.put("/api/jobs/{job_id}/exclusions")
@audit_route("job.exclusions.update")
def api_update_exclusions(job_id: str, body: ExclusionsUpdate):
    """Update job-specific exclusions list."""
    db_id = _resolve_job_id(job_id)
    excl_count = len(body.exclusions) if body.exclusions else 0
    summary = f"Updated exclusions ({excl_count} items)"
    with job_write(db_id, action="job.exclusions.update", scopes=("exclusions",), field_path="/exclusions",
                   group=audit.TEXT_EDITS, summary=summary) as tx:
        update_job_fields(tx.conn, db_id, {"exclusions": json.dumps(body.exclusions)})
        log_activity(db_id, "exclusions_updated", summary)
    return {"message": "Exclusions saved", "exclusions": body.exclusions}


@app.get("/api/jobs/{job_id}/exclusions")
def api_get_exclusions(job_id: str):
    """Get job exclusions (custom or defaults)."""
    import json as _json
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
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
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
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


@app.get("/api/labor-catalog/stairs")
def api_get_stair_labor():
    """Get stair-related labor catalog entries."""
    catalog = get_labor_catalog()
    stair_entries = [e for e in catalog if 'stair' in (e.get('description') or '').lower()]
    return {"entries": stair_entries}


def _labor_entry_name(entry: dict | None) -> str:
    entry = entry or {}
    return str(entry.get("description") or entry.get("labor_type") or "an entry")


@app.post("/api/labor-catalog/entry")
@audit_route("labor_catalog.create")
def api_insert_labor_catalog_entry(body: dict):
    """Insert a single labor catalog entry; returns the new entry id."""
    with entity_write("labor_catalog", None, _load_labor_catalog_entry, "labor_catalog.create",
                      summary=f"Added '{_labor_entry_name(body)}' to the labor catalog") as tx:
        new_id = insert_labor_catalog_entry(body, conn=tx.conn)
        tx.entity_id = new_id
    return {"id": new_id}


@app.put("/api/labor-catalog/{entry_id}")
@audit_route("labor_catalog.update")
def api_update_labor_catalog_entry(entry_id: int, body: dict):
    """Update a single labor catalog entry."""
    # A form save: quick re-saves of the same entry join one history entry.
    with entity_write("labor_catalog", entry_id, _load_labor_catalog_entry, "labor_catalog.update",
                      audit.NUMBER_EDITS,
                      summary=f"Changed '{_labor_entry_name(body)}' in the labor catalog") as tx:
        found = update_labor_catalog_entry(entry_id, body, conn=tx.conn)
    if not found:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Entry updated"}


@app.delete("/api/labor-catalog/{entry_id}")
@audit_route("labor_catalog.delete")
def api_delete_labor_catalog_entry(entry_id: int):
    """Delete a single labor catalog entry."""
    with entity_write("labor_catalog", entry_id, _load_labor_catalog_entry, "labor_catalog.delete") as tx:
        found = delete_labor_catalog_entry(entry_id, conn=tx.conn)
        tx.set_summary(f"Removed '{_labor_entry_name(tx.before)}' from the labor catalog")
    if not found:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Entry deleted"}


@app.delete("/api/labor-catalog")
@audit_route("labor_catalog.clear")
def api_clear_labor_catalog():
    """Clear all labor catalog entries."""
    with entity_write("labor_catalog", WHOLE_LIST, _load_labor_catalog, "labor_catalog.clear") as tx:
        clear_labor_catalog(conn=tx.conn)
        tx.set_summary(f"Cleared the labor catalog ({_count(len(tx.before['entries']), 'entry', 'entries')})")
    return {"message": "Labor catalog cleared"}


@app.get("/api/stair-sundry-kits")
def api_get_stair_sundry_kits():
    """Get stair sundry kit definitions (ratios per stair)."""
    return {"kits": STAIR_SUNDRY_KITS}


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
            with entity_write("company_rates", rate_type, _load_company_rate, "company_rates.seed",
                              summary=f"Added the default {rate_type.replace('_', ' ')}") as tx:
                save_company_rate(rate_type, _json.dumps(default_data), conn=tx.conn)
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
@audit_route("company_rates.update")
def api_update_company_rate(rate_type: str, body: CompanyRateUpdate):
    """Update a company rate."""
    import json as _json
    if rate_type not in ("sundry_rules", "waste_factors", "freight_rates", "sundry_prices"):
        raise HTTPException(status_code=400, detail=f"Invalid rate type: {rate_type}")
    # A table of numbers saved as people edit: quick re-saves join one entry.
    with entity_write("company_rates", rate_type, _load_company_rate, "company_rates.update",
                      audit.NUMBER_EDITS, summary=f"Changed {rate_type.replace('_', ' ')}") as tx:
        save_company_rate(rate_type, _json.dumps(body.data), conn=tx.conn)
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
@audit_route("price_list.create")
def api_add_price_list_entry(body: PriceListEntry):
    """Add a single price list entry."""
    with entity_write("price_list", None, _load_price_list_entry, "price_list.create",
                      summary=f"Added '{body.product_name}' to the price list") as tx:
        entry_id = add_price_list_entry(body.model_dump(), conn=tx.conn)
        tx.entity_id = entry_id
    return {"id": entry_id, "message": "Entry added"}


@app.put("/api/price-list/{entry_id}")
@audit_route("price_list.update")
def api_update_price_list_entry(entry_id: int, body: PriceListEntry):
    """Update a price list entry."""
    # A form save: quick re-saves of the same entry join one history entry.
    with entity_write("price_list", entry_id, _load_price_list_entry, "price_list.update", audit.NUMBER_EDITS,
                      summary=f"Changed '{body.product_name}' in the price list") as tx:
        found = update_price_list_entry(entry_id, body.model_dump(), conn=tx.conn)
    if not found:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Entry updated"}


@app.delete("/api/price-list/{entry_id}")
@audit_route("price_list.delete")
def api_delete_price_list_entry(entry_id: int):
    """Delete a price list entry."""
    with entity_write("price_list", entry_id, _load_price_list_entry, "price_list.delete") as tx:
        found = delete_price_list_entry(entry_id, conn=tx.conn)
        if found:
            tx.set_summary(f"Removed '{(tx.before or {}).get('product_name') or 'an entry'}' from the price list")
    if not found:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Entry deleted"}


class PriceListBulkUpload(BaseModel):
    entries: list[dict]


def _replace_price_list_audited(entries: list[dict], action: str, summary: str, extra: dict | None = None) -> None:
    with entity_write("price_list", WHOLE_LIST, _load_price_list, action, summary=summary, extra=extra) as tx:
        save_price_list_entries(entries, conn=tx.conn)


@app.post("/api/price-list/bulk")
@audit_route("price_list.replace")
def api_bulk_upload_price_list(body: PriceListBulkUpload):
    """Replace all price list entries (bulk upload)."""
    _replace_price_list_audited(body.entries, "price_list.replace",
                                f"Replaced the price list ({_count(len(body.entries), 'entry', 'entries')})")
    return {"message": "Price list updated", "count": len(body.entries)}


@app.delete("/api/price-list")
@audit_route("price_list.clear")
def api_clear_price_list():
    """Clear all price list entries."""
    with entity_write("price_list", WHOLE_LIST, _load_price_list, "price_list.clear") as tx:
        clear_price_list(conn=tx.conn)
        tx.set_summary(f"Cleared the price list ({_count(len(tx.before['entries']), 'entry', 'entries')})")
    return {"message": "Price list cleared"}


@app.post("/api/price-list/upload")
@audit_route("price_list.upload")
def api_upload_price_list(file: UploadFile = File(...)):
    """Upload price list from CSV or Excel file."""
    import json as _json
    file_path = os.path.join(UPLOAD_DIR, f"price_list_{file.filename}")
    with open(file_path, "wb") as f:
        content = file.file.read()
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

    _replace_price_list_audited(entries, "price_list.upload",
                                f"Uploaded the price list from {file.filename} ({_count(len(entries), 'entry', 'entries')})",
                                {"file_name": file.filename})
    return {"message": "Price list uploaded", "count": len(entries)}


def _parse_price_list_pdf(file_path: str, api_key: str = None, model: str = None) -> list[dict]:
    """Parse a price list PDF using AI."""
    if model is None:
        settings = get_settings()
        model = settings.get("openai_model", "gpt-5-mini")
    import pdfplumber

    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    text = "\n".join(text_parts)
    if not text.strip():
        return []

    import json as _json

    system_msg = """You are parsing a material price list for a flooring/interiors company.
Extract every product/material entry into a JSON array.

For each entry, extract:
- product_name: the product name or description
- material_type: the flooring type if identifiable (e.g. "unit_lvt", "unit_carpet_no_pattern", "floor_tile", etc.)
- unit: the unit of measure (SF, SY, LF, EA, etc.)
- unit_price: the price per unit as a number
- vendor: the vendor/manufacturer if shown
- notes: any additional notes

Return JSON: {"entries": [{"product_name": "...", "material_type": "...", "unit": "...", "unit_price": 0.00, "vendor": "...", "notes": "..."}, ...]}"""

    raw = chat_complete(
        system=system_msg,
        user=text,
        api_key=api_key,
        model=model,
        json_mode=True,
    )
    parsed = _json.loads(raw)
    return parsed.get("entries", [])


# ── Settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def api_get_settings():
    """Get app settings (API key is masked)."""
    settings = get_settings()
    # Mask API keys for display
    raw_key = settings.get("openai_api_key", "")
    if raw_key and len(raw_key) > 8:
        masked = raw_key[:4] + "•" * (len(raw_key) - 8) + raw_key[-4:]
    elif raw_key:
        masked = "•" * len(raw_key)
    else:
        masked = ""

    anthropic_key = settings.get("anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key and len(anthropic_key) > 8:
        anthropic_masked = anthropic_key[:4] + "•" * (len(anthropic_key) - 8) + anthropic_key[-4:]
    elif anthropic_key:
        anthropic_masked = "•" * len(anthropic_key)
    else:
        anthropic_masked = ""

    provider = get_provider_info(raw_key)
    return {
        "openai_api_key_set": bool(raw_key),
        "openai_api_key_masked": masked,
        "anthropic_api_key_set": bool(anthropic_key),
        "anthropic_api_key_masked": anthropic_masked,
        "openai_model": settings.get("openai_model", DEFAULT_MODEL),
        "model_options": MODEL_OPTIONS,
        "openai_key_on_server": bool(os.environ.get("OPENAI_API_KEY")),
        "multi_pass_count": int(settings.get("multi_pass_count", "2")),
        "email_automation_enabled": settings.get("email_automation_enabled", "false"),
        "email_config": settings.get("email_config", ""),
        "bid_folder_path": settings.get("bid_folder_path", ""),
        "ai_provider": provider["provider"],
        "ai_available": provider["available"],
        "vendor_quote_test_mode": settings.get("vendor_quote_test_mode", "false"),
        "quote_emails_enabled": QUOTE_EMAILS_ENABLED,
    }


@app.post("/api/settings")
@audit_route("settings.update")
def api_update_settings(body: SettingsUpdate):
    """Update app settings. The history shows which settings changed; API
    keys and the mailbox password show only as "changed" (audit redaction)."""
    updates = {}
    if body.openai_api_key is not None:
        updates["openai_api_key"] = body.openai_api_key
    if body.anthropic_api_key is not None:
        updates["anthropic_api_key"] = body.anthropic_api_key
    if body.openai_model is not None:
        allowed = {option["id"] for option in MODEL_OPTIONS}
        # Saving the model that is already stored is always fine, even if it
        # has since left the list, so other settings can still be saved.
        allowed.add(get_settings().get("openai_model", DEFAULT_MODEL))
        if body.openai_model not in allowed:
            names = ", ".join(option["label"] for option in MODEL_OPTIONS)
            raise HTTPException(status_code=400, detail=f"Pick one of these AI models: {names}.")
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
    if body.bid_folder_path is not None:
        updates["bid_folder_path"] = body.bid_folder_path
    if body.vendor_quote_test_mode is not None:
        updates["vendor_quote_test_mode"] = body.vendor_quote_test_mode
    if not updates:
        audit.note_checked()  # nothing sent, nothing saved
    if updates:
        # A form: quick re-saves join one history entry.
        with entity_write("settings", "app", _load_settings, "settings.update", audit.NUMBER_EDITS) as tx:
            stored = {row["key"]: row["value"] for row in tx.conn.execute("SELECT key, value FROM app_settings")}
            changed = [key for key, value in updates.items() if stored.get(key) != str(value)]
            save_settings(updates, conn=tx.conn)
            if changed:
                tx.set_summary("Changed settings: " + ", ".join(SETTING_LABELS.get(key, key) for key in changed))
        # Apply API key and model to quote parser
        settings = get_settings()
        _apply_openai_config(settings)
        # Restart inbox monitor if email settings changed
        if body.email_automation_enabled is not None or body.email_config is not None:
            _start_inbox_monitor()
        # Restart sim watcher if test mode changed
        if body.vendor_quote_test_mode is not None:
            _start_sim_watcher()
            _start_inbox_monitor()  # Re-evaluate: stop real monitor if test mode on
    return {"message": "Settings updated", **api_get_settings()}


@app.post("/api/settings/test-ai")
@no_audit("AI connection check only: sends one tiny request and saves nothing")
def api_test_ai(body: dict | None = Body(default=None)):
    """Check that the key and the chosen model really answer, for the Settings page."""
    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    stored_model = settings.get("openai_model", DEFAULT_MODEL)
    model = (body or {}).get("model") or stored_model
    if model not in {option["id"] for option in MODEL_OPTIONS} | {stored_model}:
        raise HTTPException(status_code=400, detail="Pick one of the listed AI models to test.")
    started = time.monotonic()
    try:
        raw = chat_complete(
            system="Return JSON only.",
            user='Return exactly {"ok": true}',
            api_key=api_key,
            model=model,
            json_mode=True,
        )
        ok = json.loads(raw).get("ok") is True
    except AIError as exc:
        return {"ok": False, "model": model, "message": exc.user_message}
    except (ValueError, AttributeError):
        return {"ok": False, "model": model, "message": "The AI answered, but not in the expected format. Try again."}
    seconds = round(time.monotonic() - started, 1)
    if not ok:
        return {"ok": False, "model": model, "message": "The AI answered, but not in the expected format. Try again."}
    return {"ok": True, "model": model, "seconds": seconds, "message": f"Working: {model} answered in {seconds} s."}


def _apply_openai_config(settings: dict = None):
    """Apply stored AI settings to the quote parser and ai_client."""
    if settings is None:
        settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")
    passes = int(settings.get("multi_pass_count", "2"))

    # If Anthropic key is stored in settings, set it in the environment
    # so ai_client.py can detect it as a fallback
    anthropic_key = settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = anthropic_key

    provider = get_provider_info(api_key)
    print(f"[ai_config] provider={provider['provider']}, openai_key={'set' if api_key else 'MISSING'}, "
          f"anthropic_key={'set' if anthropic_key else 'MISSING'}, model={model}, passes={passes}")
    set_openai_config(api_key=api_key, model=model, num_passes=passes)


# ── Vendor Pricing Intelligence ───────────────────────────────────────────────

@app.get("/api/vendors")
def api_list_vendors():
    return list_vendors()


@app.get("/api/vendors/{vendor_id}")
def api_get_vendor(vendor_id: int):
    v = get_vendor(vendor_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v


def _vendor_name(vendor: dict | None, fallback: str = "a vendor") -> str:
    return str((vendor or {}).get("name") or fallback)


def _create_vendor_audited(data: dict) -> dict:
    with entity_write("vendor", None, _load_vendor, "vendor.create",
                      summary=f"Added vendor {_vendor_name(data)}") as tx:
        vendor = create_vendor(data, conn=tx.conn)
        tx.entity_id = vendor["id"]
    return vendor


def _update_vendor_audited(vendor_id: int, data: dict) -> None:
    # A contact form: quick re-saves of the same vendor join one history entry.
    with entity_write("vendor", vendor_id, _load_vendor, "vendor.update", audit.NUMBER_EDITS) as tx:
        update_vendor(vendor_id, data, conn=tx.conn)
        tx.set_summary(f"Changed vendor {_vendor_name(tx.before or data)}")


@app.post("/api/vendors")
@audit_route("vendor.create")
async def api_create_vendor(request: Request):
    data = await request.json()
    try:
        vendor = await run_in_threadpool(_create_vendor_audited, data)
        return vendor
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/vendors/{vendor_id}")
@audit_route("vendor.update")
async def api_update_vendor(vendor_id: int, request: Request):
    data = await request.json()
    await run_in_threadpool(_update_vendor_audited, vendor_id, data)
    return {"ok": True}


@app.delete("/api/vendors/{vendor_id}")
@audit_route("vendor.delete")
def api_delete_vendor(vendor_id: int):
    with entity_write("vendor", vendor_id, _load_vendor, "vendor.delete") as tx:
        deleted = delete_vendor(vendor_id, conn=tx.conn)
        if deleted:
            prices = (tx.before or {}).get("price_count") or 0
            tx.set_summary(f"Deleted vendor {_vendor_name(tx.before)}"
                           + (f" and its {_count(prices, 'saved price')}" if prices else ""))
    if deleted:
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Vendor not found")


def _merge_vendors_audited(keep_id: int, merge_ids: list[int]) -> None:
    """Merge vendors into ``keep_id``: one history entry on the kept vendor,
    plus one on each bid whose materials now carry the kept vendor's name.
    Those bids are changed under their own locks and get a new version."""
    others = [mid for mid in dict.fromkeys(merge_ids) if mid != keep_id]
    conn = _get_conn()
    try:
        names = {
            row["id"]: row["name"]
            for row in conn.execute(
                f"SELECT id, name FROM vendors WHERE id IN ({', '.join('?' for _ in [keep_id, *others])})",
                [keep_id, *others],
            ).fetchall()
        }
        merged_names = [names[mid] for mid in others if mid in names]
        job_ids = sorted({
            row["job_id"]
            for row in conn.execute(
                f"SELECT DISTINCT job_id FROM job_materials WHERE vendor IN ({', '.join('?' for _ in merged_names)})",
                merged_names,
            ).fetchall()
        }) if merged_names else []
    finally:
        conn.close()
    if keep_id not in names:
        raise HTTPException(status_code=404, detail="Vendor not found")
    keep_name = names[keep_id]

    held = []
    try:
        for job_id in job_ids:  # always in id order, so two merges can't wait on each other
            lock = job_lock(job_id)
            if not lock.acquire(timeout=LOCK_WAIT_SECONDS):
                raise JobBusyError()
            held.append(lock)
        with entity_write(
            "vendor", keep_id, _load_vendor, "vendor.merge",
            summary=f"Merged {', '.join(merged_names) or 'no other vendors'} into {keep_name}",
        ) as tx:
            merged = {mid: _load_vendor(tx.conn, mid) for mid in others}
            merged = {mid: vendor for mid, vendor in merged.items() if vendor}
            renamed = tx.conn.execute(
                f"SELECT id, uid, job_id, vendor FROM job_materials WHERE vendor IN ({', '.join('?' for _ in merged_names)})",
                merged_names,
            ).fetchall() if merged_names else []
            merge_vendors(keep_id, merge_ids, conn=tx.conn)
            tx.add_changes([
                {"path": f"/merged_vendors/{mid}", "op": "remove", "before": vendor, "after": None}
                for mid, vendor in merged.items()
            ])
            by_job: dict[int, list] = {}
            for row in renamed:
                by_job.setdefault(row["job_id"], []).append(row)
            now, who = audit.iso_ms(audit.utc_now()), audit.actor_label()
            for job_id, rows in sorted(by_job.items()):
                tx.conn.execute(
                    "UPDATE jobs SET version = COALESCE(version, 0) + 1, updated_at = ?, updated_by = ? WHERE id = ?",
                    (now, who, job_id),
                )
                audit.record(
                    tx.conn,
                    action="vendor.merge",
                    entity_type="job",
                    entity_id=job_id,
                    job_id=job_id,
                    summary=f"Vendor merged: {_count(len(rows), 'material')} now say {keep_name}",
                    changes=[
                        {"path": f"/materials/{audit.escape_path_key(row['uid'] or row['id'])}/vendor", "op": "replace",
                         "before": row["vendor"], "after": keep_name}
                        for row in rows
                    ],
                    extra={"vendor_id": keep_id},
                )
            tx.extra.update({"merged_vendor_ids": sorted(merged), "bids_changed": sorted(by_job)})
    finally:
        for lock in reversed(held):
            lock.release()


@app.post("/api/vendors/merge")
@audit_route("vendor.merge")
def api_merge_vendors(body: dict):
    keep_id = body.get("keep_id")
    merge_ids = body.get("merge_ids", [])
    if not keep_id or not merge_ids:
        raise HTTPException(status_code=400, detail="keep_id and merge_ids required")
    try:
        keep_id = int(keep_id)
        merge_ids = [int(mid) for mid in merge_ids]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="keep_id and merge_ids must be vendor numbers")
    _merge_vendors_audited(keep_id, merge_ids)
    return {"ok": True}


@app.get("/api/vendor-prices")
def api_search_vendor_prices(vendor: str = None, product: str = None, limit: int = 50):
    return search_vendor_prices(vendor, product, limit)


@app.post("/api/vendor-prices/import")
@audit_route("vendor_prices.import")
def api_import_vendor_prices(file: UploadFile = File(...)):
    """Bulk import vendor prices from CSV. Accepts partial data - only product_name and unit_price required."""
    contents = file.file.read()
    text = contents.decode('utf-8-sig')  # handle BOM
    # The history lists each new price (and any vendor the import added).
    with entity_write("vendor_price", None, lambda conn, entity_id: None, "vendor_prices.import") as tx:
        last_vendor, last_price = _max_id(tx.conn, "vendors"), _max_id(tx.conn, "vendor_prices")
        result = import_vendor_prices_csv(text, conn=tx.conn)
        tx.add_changes(_added_rows(tx.conn, "vendors", last_vendor, ("name",), "/vendors"))
        tx.add_changes(_added_rows(
            tx.conn, "vendor_prices", last_price, ("product_name", "vendor_name", "unit_price", "unit"), "/vendor_prices",
        ))
        tx.set_summary(f"Imported {_count(result['imported'], 'vendor price')} from {file.filename}")
        tx.extra.update({"file_name": file.filename, "imported": result["imported"], "rows_skipped": len(result["errors"])})
    return result


@app.get("/api/materials/price-history")
def api_price_history(item_code: str = None, product: str = None, exclude_job: int = None):
    return get_price_history(item_code, product, exclude_job)


# ── Quote Requests ───────────────────────────────────────────────────────────

def _require_quote_emails():
    """Reject quote-email endpoints while QUOTE_EMAILS_ENABLED is off."""
    if not QUOTE_EMAILS_ENABLED:
        raise HTTPException(status_code=410, detail=QUOTE_EMAILS_OFF_DETAIL)


@app.post("/api/jobs/{job_id}/quote-requests")
@audit_route("quote_request.create")
async def api_create_quote_request(job_id: str, request: Request):
    raw_body = await request.body()
    return await run_in_threadpool(_create_quote_request, job_id, raw_body)


def _create_quote_request(job_id: str, raw_body: bytes):
    _require_quote_emails()
    db_id = _resolve_job_id(job_id)
    data = json.loads(raw_body)
    vendor_name = data.get("vendor_name", "").strip()
    if not vendor_name:
        raise HTTPException(status_code=400, detail="vendor_name is required")
    status = data.get("status", "draft")
    sent_at = data.get("sent_at")
    # Shows in the bid's history too (job_id).
    with entity_write("quote_request", None, _load_quote_request, "quote_request.create", job_id=db_id,
                      summary=f"Made a quote request for {vendor_name}") as tx:
        qr = create_quote_request(
            job_id=db_id,
            vendor_name=vendor_name,
            material_ids=data.get("material_ids", []),
            request_text=data.get("request_text", ""),
            vendor_id=data.get("vendor_id"),
            status=status,
            sent_at=sent_at,
            conn=tx.conn,
        )
        tx.entity_id = qr["id"]
    return qr


@app.get("/api/jobs/{job_id}/quote-requests")
def api_list_quote_requests(job_id: str):
    db_id = _resolve_job_id(job_id)
    return list_quote_requests(db_id)


def _update_quote_request_audited(request_id: int, data: dict) -> None:
    # Only the quote request's own fields ("conn" would reach the database layer).
    fields = {key: value for key, value in data.items() if isinstance(key, str) and key != "conn"}
    with entity_write("quote_request", request_id, _load_quote_request, "quote_request.update",
                      audit.NUMBER_EDITS) as tx:
        tx.job_id = (tx.before or {}).get("job_id")
        update_quote_request(request_id, conn=tx.conn, **fields)
        tx.set_summary(f"Updated the quote request for {(tx.before or {}).get('vendor_name') or 'a vendor'}")


@app.put("/api/quote-requests/{request_id}")
@audit_route("quote_request.update")
async def api_update_quote_request(request_id: int, request: Request):
    _require_quote_emails()
    data = await request.json()
    await run_in_threadpool(_update_quote_request_audited, request_id, data)
    return {"ok": True}


@app.delete("/api/quote-requests/{request_id}")
@audit_route("quote_request.delete")
def api_delete_quote_request(request_id: int):
    _require_quote_emails()
    with entity_write("quote_request", request_id, _load_quote_request, "quote_request.delete") as tx:
        tx.job_id = (tx.before or {}).get("job_id")
        deleted = delete_quote_request(request_id, conn=tx.conn)
        tx.set_summary(f"Deleted the quote request for {(tx.before or {}).get('vendor_name') or 'a vendor'}")
    if deleted:
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
@audit_route("materials.detect_vendors")
def api_detect_vendors(job_id: str):
    """Hybrid vendor detection: memory + regex + AI.

    1. MEMORY: Check vendor_prices history and vendors table for known names/aliases
    2. REGEX: Extract candidate from description structure (no hardcoded names)
    3. FUZZY MATCH: Match regex candidate against memory (handles typos)
    4. AI: For unresolved items, ask AI with evidence requirement
    5. VALIDATE: Cross-check AI results — reject if evidence doesn't appear in description
    6. RETRY: Focused single-item AI call for any conflicts
    """
    _require_quote_emails()
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = job.get("materials", [])
    if not materials:
        audit.note_checked(db_id)  # nothing to look at, nothing saved
        return {"vendors": {}, "materials": []}
    # The lines as they were when this started: only lines nobody changed
    # while the AI was working get the vendor it found (compare-and-swap).
    loaded_materials = copy.deepcopy(materials)

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

    provider = get_provider_info(api_key)
    if provider["available"]:
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
            raw = chat_complete(
                system="You are a commercial flooring industry expert.",
                user=prompt,
                api_key=api_key,
                model=model,
                json_mode=True,
            )
            result = json.loads(raw)

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

    def learn_vendor_products(conn) -> list[dict]:
        # ── Learning: save new vendor-product associations for future jobs ──
        # When AI fills in or corrects a vendor, learn the association
        learned = []
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
                        cur = conn.execute("""
                            INSERT INTO vendor_prices (product_name, product_normalized, vendor_name, vendor_id, job_id, unit_price, unit, quote_date, notes, created_at)
                            VALUES (?, ?, ?, ?, ?, 0, '', datetime('now'), 'Auto-learned from AI vendor detection', datetime('now'))
                        """, (product_name, normalized, m["vendor"], vendor_id["id"] if vendor_id else None, db_id))
                        learned.append({
                            "path": f"/learned_vendor_products/{cur.lastrowid}", "op": "add", "before": None,
                            "after": {"product_name": product_name, "vendor_name": m["vendor"]}, "derived": True,
                        })
        return learned

    # Save the vendor names found (only on lines nobody changed meanwhile)
    # and the learned pairs, in one audited step.
    with job_write(db_id, action="materials.detect_vendors", scopes=("materials",)) as tx:
        tx.conn.execute("SAVEPOINT learn_vendor_products")
        try:
            tx.add_changes(learn_vendor_products(tx.conn))
        except Exception as e:
            # Learning is a bonus: the vendor names still save without it.
            tx.conn.execute("ROLLBACK TO SAVEPOINT learn_vendor_products")
            print(f"Learning save failed: {e}")
        finally:
            tx.conn.execute("RELEASE SAVEPOINT learn_vendor_products")
        # Each found vendor is saved only if the line still has the vendor,
        # description and item code it had when this started.
        vendor_patches = [
            material_patch(before, {"vendor": after.get("vendor")}, depends_on=("description", "item_code"))
            for before, after in zip(loaded_materials, materials)
            if before.get("id") is not None and (after.get("vendor") or None) != (before.get("vendor") or None)
        ]
        result = apply_material_patches(tx, vendor_patches)
        saved = sum(1 for item in result["applied"] if item["fields"])
        conflicts = result["conflicts"]
        tx.set_summary(
            (f"Found vendors for {_count(saved, 'material')}" if saved else "Learned vendor names for future bids")
            + conflict_note(conflicts)
        )

    return {
        "vendor_groups": vendor_groups,
        "total_detected": sum(1 for m in materials if m.get("vendor")),
        "resolved_by": {
            "memory": sum(1 for v in method_log.values() if v in ("regex+memory", "product_history")),
            "existing": sum(1 for v in method_log.values() if v == "existing"),
            "ai": ai_resolved,
            "ai_corrected": ai_corrected,
        },
        # Lines someone changed while the vendors were being looked up: their
        # change was kept and the vendor found was not saved on them.
        "conflicts": conflicts,
    }


@app.post("/api/jobs/{job_id}/generate-quote-text")
@no_audit("AI draft only: returns suggested email text and saves nothing")
async def api_generate_quote_text(job_id: str, request: Request):
    """Use AI to generate professional quote request text for a vendor."""
    raw_body = await request.body()
    return await run_in_threadpool(_generate_quote_text, job_id, raw_body)


def _generate_quote_text(job_id: str, raw_body: bytes) -> dict:
    _require_quote_emails()
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = json.loads(raw_body)
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

    provider = get_provider_info(api_key)
    if not provider["available"]:
        raise HTTPException(status_code=400, detail="No AI API key configured (set OpenAI or ANTHROPIC_API_KEY)")

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
        text = chat_complete(
            system="You are a professional flooring estimator composing vendor emails.",
            user=prompt,
            api_key=api_key,
            model=model,
        ).strip()
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI quote text generation failed: {str(e)}")


@app.post("/api/jobs/{job_id}/suggest-vendors")
@no_audit("AI suggestions only: returns suggested vendors and saves nothing")
async def api_suggest_vendors(job_id: str, request: Request):
    """AI suggests which vendor to contact for unassigned materials based on history."""
    raw_body = await request.body()
    return await run_in_threadpool(_suggest_vendors, job_id, raw_body)


def _suggest_vendors(job_id: str, raw_body: bytes) -> dict:
    _require_quote_emails()
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = json.loads(raw_body)
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

    provider = get_provider_info(api_key)
    if not provider["available"]:
        raise HTTPException(status_code=400, detail="No AI API key configured (set OpenAI or ANTHROPIC_API_KEY)")

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
        raw = chat_complete(
            system="You are a commercial flooring industry expert.",
            user=prompt,
            api_key=api_key,
            model=model,
            json_mode=True,
        )
        result = json.loads(raw)
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
@no_audit("AI suggestions only: returns suggested contact details and saves nothing")
async def api_suggest_vendor_contacts(request: Request):
    """Use AI to suggest contact info for vendors."""
    _require_quote_emails()
    data = await request.json()
    return await run_in_threadpool(_suggest_vendor_contacts, data)


def _suggest_vendor_contacts(data) -> dict:
    vendor_names = data.get("vendor_names", [])
    if not vendor_names:
        return {"suggestions": []}

    settings = get_settings()
    api_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    model = settings.get("openai_model", "gpt-5-mini")

    provider = get_provider_info(api_key)
    if not provider["available"]:
        raise HTTPException(status_code=400, detail="No AI API key configured (set OpenAI or ANTHROPIC_API_KEY)")

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
        raw = chat_complete(
            system="You are a commercial flooring industry expert.",
            user=prompt,
            api_key=api_key,
            model=model,
            json_mode=True,
        )
        result = json.loads(raw)
        suggestions = result if isinstance(result, list) else result.get("suggestions", result.get("vendors", []))
        return {"suggestions": suggestions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI vendor suggestion failed: {str(e)}")


# ── Notifications ────────────────────────────────────────────────────────────

@app.get("/api/notifications")
def api_get_notifications(unread_only: bool = True):
    return get_notifications(unread_only)


@app.put("/api/notifications/{notification_id}/read")
@audit_route("notification.read")
def api_mark_notification_read(notification_id: int):
    # Only who has seen what, so it works for a deleted bid's notifications too.
    with entity_write("notification", notification_id, _load_notification, "notification.read",
                      allow_deleted=True) as tx:
        mark_notification_read(notification_id, conn=tx.conn)
        tx.job_id = (tx.before or {}).get("job_id")
        message = (tx.before or {}).get("message")
        tx.set_summary(f"Marked a notification as read: {message}" if message else "Marked a notification as read")
    return {"ok": True}


# ── Activity & Comments ──────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/activity")
def api_get_activity(job_id: str):
    db_id = _resolve_job_id(job_id)
    job = load_job(db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return get_activity(job["id"])


@app.get("/api/jobs/{job_id}/comments")
def api_get_comments(job_id: str, include_deleted: bool = False):
    """A bid's comments, newest first. ``?include_deleted=1`` also reads a
    deleted bid's comments (new comments on it are refused)."""
    db_id = _resolve_job_id(job_id, include_deleted=include_deleted)
    job = load_job(db_id, include_deleted=include_deleted)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return get_comments(job["id"])


class CommentCreate(BaseModel):
    text: str

def _comment_for_audit(conn, comment_id):
    row = conn.execute("SELECT id, job_id, text, user FROM job_comments WHERE id=?", (comment_id,)).fetchone()
    return dict(row) if row else None


@app.post("/api/jobs/{job_id}/comments")
@audit_route("comment.add")
def api_add_comment(job_id: str, body: CommentCreate):
    db_id = _resolve_job_id(job_id)
    with entity_write("comment", None, _comment_for_audit, "comment.add",
                      summary="Comment added", job_id=db_id) as tx:
        comment = add_comment(db_id, body.text, conn=tx.conn)
        tx.entity_id = comment["id"]
        log_activity(db_id, "comment_added", "Comment added", {"text": body.text})
    return comment


# ── Price Book Endpoints ─────────────────────────────────────────────────────


@app.get("/api/price-book")
def api_price_book_summary():
    """Get summary of all imported price books."""
    return get_price_book_summary()


def _import_price_book_audited(vendor: str, items: list[dict], discount_pct: float, category: str = "") -> int:
    """Replace one vendor's price book, with a history entry listing the rows
    that changed (none when the same book is imported again)."""
    with entity_write("price_book", vendor, _load_price_book, "price_book.import",
                      summary=f"Imported the {vendor} price book ({_count(len(items), 'item')})",
                      extra={"discount_pct": discount_pct, "category": category}) as tx:
        return import_price_book(vendor, items, discount_pct, category, conn=tx.conn)


@app.post("/api/price-book/import")
@audit_route("price_book.import")
def api_import_price_book(body: dict = Body(...)):
    """Import a vendor price book from JSON data.
    Body: {vendor, discount_pct, items: [{product_line, item_no, ...}]}
    """
    vendor = body.get("vendor")
    discount_pct = body.get("discount_pct", 0)
    items = body.get("items", [])
    category = body.get("category", "")
    if not vendor or not items:
        raise HTTPException(status_code=400, detail="vendor and items required")
    count = _import_price_book_audited(vendor, items, discount_pct, category)
    return {"imported": count, "vendor": vendor}


@app.get("/api/price-book/search")
def api_search_price_book(q: str = "", vendor: str = None):
    """Search price book items."""
    if not q:
        return []
    return search_price_book(q, vendor)


@app.post("/api/price-book/import-schluter")
@audit_route("price_book.import")
def api_import_schluter():
    """Import the pre-parsed Schluter price book (schluter_prices.json)."""
    json_path = os.path.join(os.path.dirname(__file__), "schluter_prices.json")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="schluter_prices.json not found. Run parse_schluter.py first.")
    import json as _json
    with open(json_path) as f:
        items = _json.load(f)
    count = _import_price_book_audited("Schluter", items, discount_pct=0.55, category="transitions")
    return {"imported": count, "vendor": "Schluter", "discount": "45% of list (55% off)"}


# ── Vendor Quote Test Mode / Simulation ──────────────────────────────────────

@app.get("/api/sim/status")
def api_sim_status():
    """Check if vendor quote test mode is active."""
    settings = get_settings()
    test_mode = QUOTE_EMAILS_ENABLED and str(settings.get("vendor_quote_test_mode", "false")).lower() == "true"
    watcher_active = _sim_watcher is not None and _sim_watcher.is_running if _sim_watcher else False
    return {
        "test_mode": test_mode,
        "watcher_active": watcher_active,
        "quote_emails_enabled": QUOTE_EMAILS_ENABLED,
    }


@app.post("/api/jobs/{job_id}/send-quote-email")
@audit_route("quote_request.email")
async def api_send_quote_email(job_id: str, request: Request):
    """Send a vendor quote request email via SMTP.

    In test mode: routes to localhost:2525 (PowerShell relay → Vendor Simulator)
    In production: routes to real SMTP server → real vendor
    """
    raw_body = await request.body()
    return await run_in_threadpool(_send_quote_email, job_id, raw_body)


def _send_quote_email(job_id: str, raw_body: bytes) -> dict:
    _require_quote_emails()
    db_id = _resolve_job_id(job_id)
    if not db_id:
        raise HTTPException(status_code=404, detail="Job not found")

    body = json.loads(raw_body)
    vendor_name = body.get("vendor_name", "").strip()
    vendor_email = body.get("vendor_email", "").strip()
    subject = body.get("subject", "").strip()
    email_body = body.get("body", "").strip()
    material_ids = body.get("material_ids", [])
    vendor_id = body.get("vendor_id")

    if not vendor_name or not vendor_email:
        raise HTTPException(status_code=400, detail="vendor_name and vendor_email are required")
    if not subject:
        job = load_job(db_id)
        subject = f"Request for Pricing — {job.get('project_name', 'Project')}"
    job_tag = f"[SI Job {db_id}]"
    if job_tag.lower() not in subject.lower():
        subject = f"{subject} {job_tag}"

    # Get SMTP config based on test mode
    settings = get_settings()
    from sim_email import get_smtp_config, sim_send_quote
    smtp_config = get_smtp_config(settings)

    try:
        sim_send_quote(
            job_id=db_id,
            vendor_name=vendor_name,
            vendor_email=vendor_email,
            subject=subject,
            body=email_body,
            smtp_config=smtp_config,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")

    # Create quote_request record (same as existing Mark Sent flow). One
    # history entry on the bid: the activity text below is its summary.
    test_mode = str(settings.get("vendor_quote_test_mode", "false")).lower() == "true"
    with entity_write("quote_request", None, _load_quote_request, "quote_request.email", job_id=db_id,
                      extra={"vendor_email": vendor_email, "subject": subject, "test_mode": test_mode}) as tx:
        qr = create_quote_request(
            job_id=db_id,
            vendor_name=vendor_name,
            material_ids=material_ids,
            request_text=email_body,
            vendor_id=vendor_id,
            status="sent",
            sent_at=body.get("sent_at") or __import__("datetime").datetime.utcnow().isoformat(),
            conn=tx.conn,
        )
        tx.entity_id = qr["id"]
        log_activity(db_id, "quote_email_sent",
                     f"{'[SIM] ' if test_mode else ''}Quote email sent to {vendor_name} ({vendor_email})",
                     {"vendor": vendor_name, "vendor_email": vendor_email, "test_mode": test_mode})

    return {"status": "sent", "quote_request": qr, "test_mode": test_mode}


# ── Audit trail (read) ───────────────────────────────────────────────────────
# Who changed what, for everything. Open to everyone who is logged in.
# Filters: job_id (id or slug), entity_type, entity_id, actor (username, or
# "system"), action ("bid" also matches "bid.sent", ...), since/until (a date
# or ISO time, UTC), q (text search). Newest first; pass next_before_id back
# as before_id for the next page.

def _audit_query_filters(**raw) -> dict:
    job_ref = raw.pop("job_id", None)
    try:
        filters = audit.clean_filters(**raw)
    except audit.AuditQueryError as err:
        raise HTTPException(status_code=400, detail=str(err))
    if job_ref not in (None, ""):
        # A number is used as is, so history of a bid that's gone still shows.
        job_id = int(job_ref) if str(job_ref).strip().isdigit() else resolve_job_ref(job_ref)
        filters["job_id"] = job_id if job_id is not None else -1  # unknown slug: nothing matches
    return filters


@app.get("/api/audit")
def api_audit_list(
    job_id: Optional[str] = None, entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    actor: Optional[str] = None, action: Optional[str] = None, since: Optional[str] = None,
    until: Optional[str] = None, q: Optional[str] = None, before_id: Optional[int] = None,
    limit: int = audit.DEFAULT_PAGE_SIZE,
):
    filters = _audit_query_filters(job_id=job_id, entity_type=entity_type, entity_id=entity_id,
                                   actor=actor, action=action, since=since, until=until, q=q)
    return audit.query_entries(filters, before_id=before_id, limit=limit)


# Registered before /api/audit/{audit_id} so "export.csv" isn't read as an id.
@app.get("/api/audit/export.csv")
def api_audit_export(
    job_id: Optional[str] = None, entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    actor: Optional[str] = None, action: Optional[str] = None, since: Optional[str] = None,
    until: Optional[str] = None, q: Optional[str] = None,
):
    filters = _audit_query_filters(job_id=job_id, entity_type=entity_type, entity_id=entity_id,
                                   actor=actor, action=action, since=since, until=until, q=q)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    return StreamingResponse(
        audit.iter_export_csv(filters),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bid-tool-history-{stamp}.csv"'},
    )


@app.get("/api/audit/{audit_id}")
def api_audit_entry(audit_id: int):
    entry = audit.get_entry(audit_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="History entry not found")
    return entry


@app.get("/api/jobs/{job_id}/history")
def api_job_history(
    job_id: str, entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    actor: Optional[str] = None, action: Optional[str] = None, since: Optional[str] = None,
    until: Optional[str] = None, q: Optional[str] = None, before_id: Optional[int] = None,
    limit: int = audit.DEFAULT_PAGE_SIZE,
):
    """One bid's history (id or slug). A numeric id works even once the bid is gone."""
    if not job_id.strip().isdigit() and resolve_job_ref(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    filters = _audit_query_filters(job_id=job_id, entity_type=entity_type, entity_id=entity_id,
                                   actor=actor, action=action, since=since, until=until, q=q)
    return audit.query_entries(filters, before_id=before_id, limit=limit)


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
        # If the file exists in static dir, serve it directly. Resolve the path
        # first and only serve files that really sit inside the static folder,
        # so "..", an encoded leading slash or a symlink can't reach the
        # database or any other file on the server.
        if full_path:
            static_root = os.path.realpath(_static_root)
            try:
                file_path = os.path.realpath(os.path.join(static_root, full_path))
                inside_static = os.path.commonpath([static_root, file_path]) == static_root
            except (ValueError, OSError):  # e.g. a NUL byte in the path
                inside_static = False
            if inside_static and os.path.isfile(file_path):
                return FileResponse(file_path)
        # Otherwise serve index.html for client-side routing
        return FileResponse(os.path.join(_static_root, "index.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
