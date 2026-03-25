"""
SI Quote Agent — Local background service that:
1. Monitors email for vendor quotes, saves to Dropbox, uploads to SI Bid Tool
2. Scans Dropbox Correspondence folders for existing quotes when new jobs are created

Usage:
    python si_quote_agent.py              # Run once (poll inbox + scan jobs, exit)
    python si_quote_agent.py --daemon     # Run continuously (poll every N minutes)
    python si_quote_agent.py --setup      # Interactive first-time config setup
    python si_quote_agent.py --scan-only  # Only scan Dropbox folders (skip email)
"""

import argparse
import email
import hashlib
import imaplib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

AGENT_DIR = Path(__file__).parent
CONFIG_PATH = AGENT_DIR / "config.json"
DB_PATH = AGENT_DIR / "processed.db"
LOG_PATH = AGENT_DIR / "agent.log"

# Email subject patterns that indicate a vendor quote response
QUOTE_PATTERNS = [
    re.compile(r"re:\s*.*quot", re.IGNORECASE),
    re.compile(r"re:\s*.*pric", re.IGNORECASE),
    re.compile(r"re:\s*.*standard\s+interiors", re.IGNORECASE),
    re.compile(r"price\s*list", re.IGNORECASE),
    re.compile(r"pricing\s+for", re.IGNORECASE),
    re.compile(r"quote\s*(request|response|reply|for)", re.IGNORECASE),
    re.compile(r"proposal", re.IGNORECASE),
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("si-quote-agent")

# ── Local Dedup DB ────────────────────────────────────────────────────────────


def _init_db():
    """Create the processed emails and scanned jobs tracking tables."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_emails (
            uid TEXT PRIMARY KEY,
            subject TEXT,
            sender TEXT,
            processed_at TEXT,
            job_id INTEGER,
            job_name TEXT,
            files_saved TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scanned_jobs (
            job_id INTEGER PRIMARY KEY,
            project_name TEXT,
            folder_path TEXT,
            files_uploaded INTEGER DEFAULT 0,
            scanned_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def _is_processed(uid: str) -> bool:
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("SELECT 1 FROM processed_emails WHERE uid = ?", (uid,)).fetchone()
    conn.close()
    return row is not None


def _mark_processed(uid: str, subject: str, sender: str, job_id: int = None,
                    job_name: str = None, files_saved: list = None):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT OR IGNORE INTO processed_emails (uid, subject, sender, processed_at, job_id, job_name, files_saved) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uid, subject, sender, datetime.now(timezone.utc).isoformat(),
         job_id, job_name, json.dumps(files_saved or [])),
    )
    conn.commit()
    conn.close()


def _is_job_scanned(job_id: int) -> bool:
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("SELECT 1 FROM scanned_jobs WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    return row is not None


def _mark_job_scanned(job_id: int, project_name: str, folder_path: str, files_uploaded: int):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT OR REPLACE INTO scanned_jobs (job_id, project_name, folder_path, files_uploaded, scanned_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (job_id, project_name, folder_path, files_uploaded, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


# ── Config Management ─────────────────────────────────────────────────────────


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.error(f"Config not found at {CONFIG_PATH}. Run: python si_quote_agent.py --setup")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def setup_config():
    """Interactive first-time setup."""
    print("\n=== SI Quote Agent Setup ===\n")
    config = {}

    # IMAP
    config["imap_host"] = input("IMAP host (e.g. imap.gmail.com): ").strip()
    config["imap_port"] = int(input("IMAP port [993]: ").strip() or "993")
    config["email_address"] = input("Email address: ").strip()
    config["email_password"] = input("App password: ").strip()

    # Bid folder
    default_bid = r"C:\Users\Josh Dann\Standard Interiors Dropbox\Personal Folders (1)\CP\001-Bid Folder"
    config["bid_folder_path"] = input(f"Bid folder path [{default_bid}]: ").strip() or default_bid

    # API
    config["api_url"] = input("SI Bid Tool API URL [https://si-bid-tool.fly.dev]: ").strip() or "https://si-bid-tool.fly.dev"

    # Poll interval
    config["poll_interval_minutes"] = int(input("Poll interval in minutes [5]: ").strip() or "5")

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\nConfig saved to {CONFIG_PATH}")
    print("Run: python si_quote_agent.py --daemon")


# ── Email Helpers ─────────────────────────────────────────────────────────────


def _decode_header_value(raw) -> str:
    """Decode an email header value that may be encoded."""
    if raw is None:
        return ""
    parts = decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_sender_name(from_header: str) -> str:
    """Extract just the display name or email from a From header."""
    match = re.match(r'"?([^"<]+)"?\s*<', from_header)
    if match:
        return match.group(1).strip()
    return from_header.strip()


def _extract_project_reference(subject: str) -> str:
    """Try to extract a project name from an email subject.
    Strips RE:, FW:, [EXT], etc. and returns the core subject."""
    cleaned = re.sub(r"^(re|fw|fwd|ext|\[ext\])[\s:]+", "", subject, flags=re.IGNORECASE).strip()
    # Remove "Quote Request - " or "Pricing for " prefixes
    cleaned = re.sub(r"^(quote\s*request|pricing|price\s*list|proposal)\s*[-:–—]\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _is_quote_email(subject: str) -> bool:
    """Check if an email subject matches vendor quote patterns."""
    return any(p.search(subject) for p in QUOTE_PATTERNS)


# ── Bid Folder Helpers ────────────────────────────────────────────────────────


def _find_project_folder(bid_folder: Path, project_name: str, gc_name: str = "") -> Path | None:
    """Fuzzy-match a project name to a subfolder in the bid folder."""
    if not bid_folder.exists():
        log.warning(f"Bid folder not found: {bid_folder}")
        return None

    project_lower = project_name.lower().strip()
    gc_lower = gc_name.lower().strip() if gc_name else ""

    # Remove common words for better matching
    def normalize(s):
        return re.sub(r"[^a-z0-9\s]", "", s.lower()).strip()

    best_match = None
    best_score = 0

    for entry in bid_folder.iterdir():
        if not entry.is_dir():
            continue
        folder_norm = normalize(entry.name)
        proj_norm = normalize(project_name)

        # Score based on word overlap
        proj_words = set(proj_norm.split())
        folder_words = set(folder_norm.split())
        if not proj_words:
            continue

        overlap = proj_words & folder_words
        score = len(overlap) / len(proj_words)

        # Bonus for GC name match
        if gc_lower:
            gc_words = set(normalize(gc_name).split())
            gc_overlap = gc_words & folder_words
            if gc_overlap:
                score += 0.3 * len(gc_overlap) / len(gc_words)

        # Bonus for substring containment
        if proj_norm in folder_norm or folder_norm in proj_norm:
            score += 0.2

        if score > best_score:
            best_score = score
            best_match = entry

    if best_score >= 0.4:
        return best_match
    return None


def _save_eml_to_correspondence(eml_bytes: bytes, folder: Path, sender_name: str) -> Path:
    """Save an .eml file to the Correspondence subfolder."""
    corr_folder = folder / "Correspondence"
    corr_folder.mkdir(exist_ok=True)

    # Use sender name as filename (sanitize)
    safe_name = re.sub(r'[<>:"/\\|?*]', "", sender_name).strip()
    if not safe_name:
        safe_name = "Vendor Quote"

    filepath = corr_folder / f"{safe_name}.eml"

    # Don't overwrite existing files — append a number
    if filepath.exists():
        i = 2
        while (corr_folder / f"{safe_name} ({i}).eml").exists():
            i += 1
        filepath = corr_folder / f"{safe_name} ({i}).eml"

    filepath.write_bytes(eml_bytes)
    return filepath


def _extract_pdf_attachments(msg: email.message.Message, folder: Path) -> list[Path]:
    """Extract PDF attachments from an email and save to Correspondence folder."""
    corr_folder = folder / "Correspondence"
    corr_folder.mkdir(exist_ok=True)
    saved = []

    for part in msg.walk():
        content_type = part.get_content_type()
        filename = part.get_filename()
        if filename and content_type == "application/pdf":
            safe_name = re.sub(r'[<>:"/\\|?*]', "", filename).strip()
            filepath = corr_folder / safe_name
            if not filepath.exists():
                filepath.write_bytes(part.get_payload(decode=True))
                saved.append(filepath)

    return saved


# ── SI Bid Tool API ───────────────────────────────────────────────────────────


def _api_match_job(api_url: str, subject: str) -> dict | None:
    """Call the SI Bid Tool API to match an email subject to a job."""
    try:
        resp = requests.get(f"{api_url}/api/jobs/match", params={"q": subject}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("job_id"):
                return data
    except Exception as e:
        log.warning(f"API match failed: {e}")
    return None


def _api_upload_quotes(api_url: str, job_id: int, files: list[Path]) -> dict | None:
    """Upload quote files to the SI Bid Tool API."""
    try:
        multipart = []
        for fpath in files:
            multipart.append(("files", (fpath.name, open(fpath, "rb"), "application/octet-stream")))

        resp = requests.post(
            f"{api_url}/api/jobs/{job_id}/upload-quotes",
            files=multipart,
            timeout=120,
        )

        # Close file handles
        for _, (_, fh, _) in multipart:
            fh.close()

        if resp.status_code == 200:
            return resp.json()
        else:
            log.error(f"Upload failed ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        log.error(f"Upload error: {e}")
    return None


def _api_list_jobs(api_url: str) -> list[dict]:
    """Fetch all jobs from the SI Bid Tool API."""
    try:
        resp = requests.get(f"{api_url}/api/jobs", timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.warning(f"Failed to fetch jobs: {e}")
    return []


def _fuzzy_match_job(jobs: list[dict], reference: str) -> dict | None:
    """Fuzzy match a project reference string against job list."""
    if not reference or not jobs:
        return None

    ref_lower = reference.lower()
    ref_words = set(re.sub(r"[^a-z0-9\s]", "", ref_lower).split())

    best = None
    best_score = 0

    for job in jobs:
        name = (job.get("project_name") or "").lower()
        gc = (job.get("gc_name") or "").lower()
        combined = f"{gc} {name}"
        combined_words = set(re.sub(r"[^a-z0-9\s]", "", combined).split())

        if not combined_words:
            continue

        overlap = ref_words & combined_words
        score = len(overlap) / max(len(ref_words), 1)

        # Bonus for substring match
        if name in ref_lower or ref_lower in name:
            score += 0.3

        if score > best_score:
            best_score = score
            best = job

    if best_score >= 0.3:
        return best
    return None


# ── Main Poll Loop ────────────────────────────────────────────────────────────


def poll_inbox(config: dict):
    """Connect to IMAP, find vendor quotes, process them."""
    log.info("Polling inbox...")

    try:
        if config.get("imap_port", 993) == 993:
            conn = imaplib.IMAP4_SSL(config["imap_host"], config["imap_port"])
        else:
            conn = imaplib.IMAP4(config["imap_host"], config["imap_port"])

        conn.login(config["email_address"], config["email_password"])
        conn.select("INBOX")
    except Exception as e:
        log.error(f"IMAP connection failed: {e}")
        return

    try:
        # Search for unseen emails
        status, msg_ids = conn.search(None, "UNSEEN")
        if status != "OK" or not msg_ids[0]:
            log.info("No new emails.")
            return

        uid_list = msg_ids[0].split()
        log.info(f"Found {len(uid_list)} unread emails")

        # Load jobs list for matching
        api_url = config["api_url"]
        jobs = _api_list_jobs(api_url)
        bid_folder = Path(config["bid_folder_path"])

        for uid_bytes in uid_list:
            uid = uid_bytes.decode()

            if _is_processed(uid):
                continue

            # Fetch the email
            status, data = conn.fetch(uid_bytes, "(RFC822)")
            if status != "OK":
                continue

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = _decode_header_value(msg.get("Subject", ""))
            from_header = _decode_header_value(msg.get("From", ""))
            sender_name = _extract_sender_name(from_header)

            # Check if this looks like a vendor quote
            if not _is_quote_email(subject):
                log.debug(f"Skipping non-quote email: {subject[:60]}")
                continue

            log.info(f"Quote detected: '{subject[:80]}' from {sender_name}")

            # Extract project reference from subject
            reference = _extract_project_reference(subject)

            # Try API match first, then local fuzzy match
            matched_job = _api_match_job(api_url, reference)
            if not matched_job:
                local_match = _fuzzy_match_job(jobs, reference)
                if local_match:
                    matched_job = {
                        "job_id": local_match["id"],
                        "project_name": local_match.get("project_name", ""),
                        "gc_name": local_match.get("gc_name", ""),
                    }

            if not matched_job:
                log.warning(f"No matching job for: {reference}")
                _mark_processed(uid, subject, sender_name)
                continue

            job_id = matched_job["job_id"]
            project_name = matched_job.get("project_name", "")
            gc_name = matched_job.get("gc_name", "")
            log.info(f"Matched to job #{job_id}: {project_name}")

            # Save .eml to Dropbox Correspondence folder
            files_saved = []
            project_folder = _find_project_folder(bid_folder, project_name, gc_name)
            if project_folder:
                eml_path = _save_eml_to_correspondence(raw_email, project_folder, sender_name)
                files_saved.append(str(eml_path))
                log.info(f"Saved .eml to {eml_path}")

                # Also extract PDF attachments
                pdf_paths = _extract_pdf_attachments(msg, project_folder)
                for p in pdf_paths:
                    files_saved.append(str(p))
                    log.info(f"Saved PDF attachment: {p}")
            else:
                log.warning(f"No matching bid folder for '{project_name}' — saving .eml to temp")
                # Save to a temp location and still upload
                temp_dir = AGENT_DIR / "temp"
                temp_dir.mkdir(exist_ok=True)
                eml_path = temp_dir / f"{sender_name}_{uid}.eml"
                eml_path.write_bytes(raw_email)
                files_saved.append(str(eml_path))

            # Upload to SI Bid Tool API
            upload_files = [Path(f) for f in files_saved]
            result = _api_upload_quotes(api_url, job_id, upload_files)
            if result:
                product_count = len(result.get("products", []))
                auto_matched = result.get("auto_matched", 0)
                log.info(f"Uploaded to job #{job_id}: {product_count} products, {auto_matched} auto-matched")
            else:
                log.warning(f"Upload to API failed for job #{job_id}")

            # Mark as processed
            _mark_processed(uid, subject, sender_name, job_id, project_name, files_saved)

    finally:
        try:
            conn.close()
            conn.logout()
        except Exception:
            pass


# ── Dropbox Folder Scanner (New Job Detection) ──────────────────────────────


def scan_new_jobs(config: dict):
    """Check for new jobs in the SI Bid Tool and scan their Dropbox folders
    for existing quote files (.eml, .pdf). Uploads any found files to the API."""
    api_url = config["api_url"]
    bid_folder = Path(config["bid_folder_path"])

    if not bid_folder.exists():
        log.warning(f"Bid folder not found: {bid_folder} — skipping folder scan")
        return

    jobs = _api_list_jobs(api_url)
    if not jobs:
        return

    new_jobs = [j for j in jobs if not _is_job_scanned(j["id"])]
    if not new_jobs:
        log.debug("No new jobs to scan.")
        return

    log.info(f"Found {len(new_jobs)} new job(s) to scan for existing quotes")

    for job in new_jobs:
        job_id = job["id"]
        project_name = job.get("project_name", "")
        gc_name = job.get("gc_name", "")

        if not project_name:
            _mark_job_scanned(job_id, project_name, "", 0)
            continue

        # Find matching project folder in the bid folder
        project_folder = _find_project_folder(bid_folder, project_name, gc_name)
        if not project_folder:
            log.info(f"Job #{job_id} '{project_name}': no matching bid folder found")
            _mark_job_scanned(job_id, project_name, "", 0)
            continue

        log.info(f"Job #{job_id} '{project_name}': matched folder '{project_folder.name}'")

        # Look for Correspondence subfolder first, fall back to project root
        corr_folder = project_folder / "Correspondence"
        scan_folder = corr_folder if corr_folder.exists() else project_folder

        # Collect all .eml and .pdf files (recursive)
        quote_files = []
        for fpath in scan_folder.rglob("*"):
            if fpath.is_file() and fpath.suffix.lower() in (".eml", ".pdf"):
                quote_files.append(fpath)

        if not quote_files:
            log.info(f"Job #{job_id}: no quote files in '{scan_folder}'")
            _mark_job_scanned(job_id, project_name, str(project_folder), 0)
            continue

        log.info(f"Job #{job_id}: found {len(quote_files)} quote file(s) — uploading to bid tool")

        # Upload to SI Bid Tool API
        result = _api_upload_quotes(api_url, job_id, quote_files)
        if result:
            product_count = len(result.get("products", []))
            auto_matched = result.get("auto_matched", 0)
            skipped = len(result.get("skipped_files", []))
            log.info(
                f"Job #{job_id}: uploaded {product_count} products, "
                f"{auto_matched} auto-matched, {skipped} skipped (duplicates)"
            )
        else:
            log.warning(f"Job #{job_id}: upload to API failed")

        _mark_job_scanned(job_id, project_name, str(project_folder), len(quote_files))


# ── Entry Point ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="SI Quote Agent — monitors email for vendor quotes")
    parser.add_argument("--setup", action="store_true", help="Interactive first-time config setup")
    parser.add_argument("--daemon", action="store_true", help="Run continuously (poll every N minutes)")
    parser.add_argument("--scan-only", action="store_true", help="Only scan Dropbox folders for existing quotes (skip email)")
    args = parser.parse_args()

    if args.setup:
        setup_config()
        return

    _init_db()
    config = load_config()

    if args.scan_only:
        log.info("Scan-only mode — checking for new jobs with existing quote files")
        scan_new_jobs(config)
        log.info("Done.")
    elif args.daemon:
        interval = config.get("poll_interval_minutes", 5) * 60
        log.info(f"Starting daemon mode — polling every {config.get('poll_interval_minutes', 5)} minutes")
        log.info(f"Monitoring: {config['email_address']}")
        log.info(f"Bid folder: {config['bid_folder_path']}")
        log.info(f"API: {config['api_url']}")

        while True:
            try:
                poll_inbox(config)
            except Exception as e:
                log.error(f"Poll cycle error (email): {e}")
            try:
                scan_new_jobs(config)
            except Exception as e:
                log.error(f"Poll cycle error (folder scan): {e}")
            time.sleep(interval)
    else:
        # Single poll — both email and folder scan
        poll_inbox(config)
        scan_new_jobs(config)
        log.info("Done.")


if __name__ == "__main__":
    main()
