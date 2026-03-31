"""
Simulation email support for vendor quote test mode.

- get_smtp_config(): returns localhost:2525 in test mode, real SMTP in production
- sim_send_quote(): sends quote request via SMTP with X-SI-Job-Id header
- SimFolderWatcher: polls bidtool_inbox/ for reply .eml files, calls on_quote_received
"""

import os
import shutil
import threading
import time
from datetime import datetime
from email import policy
from email.mime.text import MIMEText
from pathlib import Path
from typing import Callable, Optional

import email as email_lib

from email_agent import send_email

# ── Paths ────────────────────────────────────────────────────────────────────

# simulator/mailbox/ relative to project root (one level up from server/)
_PROJECT_ROOT = Path(__file__).parent.parent
VENDOR_INBOX = _PROJECT_ROOT / "simulator" / "mailbox" / "vendor_inbox"
BIDTOOL_INBOX = _PROJECT_ROOT / "simulator" / "mailbox" / "bidtool_inbox"


def _ensure_dirs():
    """Create mailbox directories if they don't exist."""
    for d in [VENDOR_INBOX, BIDTOOL_INBOX,
              VENDOR_INBOX / "processed", BIDTOOL_INBOX / "processed"]:
        d.mkdir(parents=True, exist_ok=True)


# ── SMTP Config Routing ─────────────────────────────────────────────────────

def get_smtp_config(settings: dict) -> dict:
    """Return SMTP config based on test mode.

    Test mode ON:  localhost:2525, no TLS, no auth
    Test mode OFF: real SMTP from settings
    """
    test_mode = str(settings.get("vendor_quote_test_mode", "false")).lower() == "true"

    if test_mode:
        return {
            "host": "localhost",
            "port": 2525,
            "username": "",
            "password": "",
            "use_tls": False,
        }

    # Production SMTP config from settings
    import json
    email_config = settings.get("email_config", "{}")
    if isinstance(email_config, str):
        try:
            email_config = json.loads(email_config)
        except (json.JSONDecodeError, TypeError):
            email_config = {}

    return {
        "host": email_config.get("smtp_host", settings.get("smtp_host", "")),
        "port": int(email_config.get("smtp_port", settings.get("smtp_port", 587))),
        "username": email_config.get("email_address", settings.get("smtp_username", "")),
        "password": email_config.get("email_password", settings.get("smtp_password", "")),
        "use_tls": True,
    }


# ── Send Quote via SMTP ─────────────────────────────────────────────────────

def sim_send_quote(
    job_id: int,
    vendor_name: str,
    vendor_email: str,
    subject: str,
    body: str,
    from_email: str = "estimating@standardinteriors.com",
    smtp_config: dict = None,
) -> bool:
    """Send a quote request email via SMTP.

    Adds X-SI-Job-Id header for reliable job matching on return.
    Works in both test mode (localhost:2525) and production (real SMTP).
    """
    if not smtp_config:
        smtp_config = {"host": "localhost", "port": 2525, "username": "", "password": "", "use_tls": False}

    # Build the email with custom header
    from email.mime.text import MIMEText as _MIMEText
    import smtplib

    msg = _MIMEText(body, "plain")
    msg["From"] = f"Standard Interiors <{from_email}>"
    msg["To"] = vendor_email
    msg["Subject"] = subject
    msg["X-SI-Job-Id"] = str(job_id)
    msg["Date"] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

    host = smtp_config.get("host", "")
    port = int(smtp_config.get("port", 587))
    username = smtp_config.get("username", "")
    password = smtp_config.get("password", "")
    use_tls = smtp_config.get("use_tls", True)

    if not host:
        raise ValueError("SMTP host is required")

    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.ehlo()
        if use_tls:
            server.starttls()
            server.ehlo()

    try:
        if username and password:
            server.login(username, password)
        server.sendmail(from_email, [vendor_email], msg.as_string())
    finally:
        server.quit()

    return True


# ── SimFolderWatcher ─────────────────────────────────────────────────────────

class SimFolderWatcher(threading.Thread):
    """Polls simulator/mailbox/bidtool_inbox/ for reply .eml files.

    When found, moves to processed/ and calls the on_quote_received callback —
    the same pipeline as InboxMonitor (parse → save → auto-match → notify).
    """

    def __init__(
        self,
        on_quote_received: Callable,
        poll_interval: int = 5,
        inbox_dir: Path = None,
    ):
        super().__init__(daemon=True, name="sim-folder-watcher")
        self._callback = on_quote_received
        self._interval = poll_interval
        self._inbox_dir = inbox_dir or BIDTOOL_INBOX
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
        _ensure_dirs()
        super().start()
        print(f"[SimFolderWatcher] Started — watching {self._inbox_dir}")

    def stop(self):
        with self._lock:
            self._running = False
        self.join(timeout=10)
        print("[SimFolderWatcher] Stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def run(self):
        while self._running:
            try:
                self._check_folder()
            except Exception as e:
                print(f"[SimFolderWatcher] Error: {e}")
            # Sleep in small increments so stop() is responsive
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)

    def check_now(self) -> list:
        """Manually trigger a folder check. Returns list of processed files."""
        return self._check_folder()

    def _check_folder(self) -> list:
        """Scan inbox for .eml files, process each, return filenames."""
        processed = []
        if not self._inbox_dir.exists():
            return processed

        eml_files = sorted(self._inbox_dir.glob("*.eml"))
        if not eml_files:
            return processed

        print(f"[SimFolderWatcher] Found {len(eml_files)} new .eml file(s)")

        for eml_path in eml_files:
            try:
                self._process_eml(eml_path)
                processed.append(eml_path.name)
            except Exception as e:
                print(f"[SimFolderWatcher] Error processing {eml_path.name}: {e}")

        return processed

    def _process_eml(self, eml_path: Path):
        """Process a single .eml file from the bidtool inbox."""
        # Parse the email to extract metadata
        with open(eml_path, "rb") as f:
            msg = email_lib.message_from_binary_file(f, policy=policy.default)

        subject = str(msg.get("Subject", ""))
        from_addr = str(msg.get("From", ""))
        job_id_header = msg.get("X-SI-Job-Id", "")

        print(f"[SimFolderWatcher] Processing: '{subject}' from {from_addr} (job_id={job_id_header})")

        # Move to processed/
        dest = self._inbox_dir / "processed" / eml_path.name
        shutil.move(str(eml_path), str(dest))

        # Extract vendor email from From header
        import re
        email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", from_addr)
        vendor_email = email_match.group(0) if email_match else from_addr

        # Call the callback with the same signature as InboxMonitor
        self._callback(
            job_reference=job_id_header or subject,
            temp_files=[str(dest)],
            vendor_email=vendor_email,
            filenames=[eml_path.name],
            subject=subject,
        )
