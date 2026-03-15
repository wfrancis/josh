"""
IMAP inbox monitor for detecting vendor quote responses.
Runs as a background thread, polls inbox on interval.
Uses existing quote_parser for parsing responses.
"""

import imaplib
import email as email_lib
from email import policy
import threading
import time
import tempfile
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Callable


class InboxMonitor:
    """Monitors IMAP inbox for vendor quote responses."""

    def __init__(
        self,
        imap_config: dict,          # host, port, username, password, use_ssl
        on_quote_received: Callable, # callback(job_id, parsed_products, vendor_email, filenames)
        poll_interval: int = 300,    # 5 minutes
        subject_patterns: list[str] = None,  # patterns to match quote replies
    ):
        self._config = imap_config
        self._callback = on_quote_received
        self._interval = poll_interval
        self._subject_patterns = subject_patterns or [
            r"(?i)re:\s*.*quote\s*request",
            r"(?i)re:\s*.*pricing",
            r"(?i)quote.*(?:request|response|reply)",
            r"(?i)pricing\s+for",
            r"(?i)price\s+list",
        ]
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_check: Optional[datetime] = None
        self._lock = threading.Lock()

    def start(self):
        """Start the background monitoring thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="inbox-monitor")
            self._thread.start()

    def stop(self):
        """Stop the monitoring thread."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                self._check_inbox()
            except Exception as e:
                print(f"[InboxMonitor] Error checking inbox: {e}")
            # Sleep in small increments so stop() is responsive
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)

    def _connect(self) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
        """Connect to IMAP server and authenticate."""
        host = self._config.get("host", "")
        port = int(self._config.get("port", 993))
        username = self._config.get("username", "")
        password = self._config.get("password", "")
        use_ssl = self._config.get("use_ssl", True)

        if not host:
            raise ValueError("IMAP host is required")
        if not username or not password:
            raise ValueError("IMAP username and password are required")

        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port)
        else:
            conn = imaplib.IMAP4(host, port)

        conn.login(username, password)
        return conn

    def _check_inbox(self):
        """Check for new vendor quote emails."""
        conn = self._connect()
        try:
            conn.select("INBOX")

            # Build search criteria
            if self._last_check:
                # Search for UNSEEN emails since last check
                date_str = self._last_check.strftime("%d-%b-%Y")
                status, msg_ids = conn.search(None, "UNSEEN", f'(SINCE {date_str})')
            else:
                # First run: only get UNSEEN emails
                status, msg_ids = conn.search(None, "UNSEEN")

            if status != "OK" or not msg_ids[0]:
                self._last_check = datetime.utcnow()
                return

            id_list = msg_ids[0].split()
            print(f"[InboxMonitor] Found {len(id_list)} unseen email(s)")

            for msg_id in id_list:
                try:
                    self._process_email(conn, msg_id)
                except Exception as e:
                    print(f"[InboxMonitor] Error processing email {msg_id}: {e}")

            self._last_check = datetime.utcnow()
        finally:
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn.logout()
            except Exception:
                pass

    def _process_email(self, conn, msg_id: bytes):
        """Process a single email to see if it's a quote response."""
        # Fetch the email
        status, data = conn.fetch(msg_id, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            return

        raw_email = data[0][1]
        msg = email_lib.message_from_bytes(raw_email, policy=policy.default)

        subject = str(msg.get("Subject", ""))
        from_addr = str(msg.get("From", ""))

        # Check if subject matches any quote-related pattern
        if not self._matches_quote_pattern(subject):
            return

        print(f"[InboxMonitor] Potential quote response: '{subject}' from {from_addr}")

        # Extract vendor email address
        vendor_email = self._extract_email_address(from_addr)

        # Extract job reference from subject
        job_reference = self._extract_job_reference(subject)

        # Extract attachments
        attachments = self._extract_attachments(msg)
        temp_files = []
        filenames = []

        try:
            if attachments:
                # Save attachments to temp files for parsing
                for filename, file_data in attachments:
                    ext = os.path.splitext(filename)[1].lower() if filename else ".bin"
                    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                        tmp.write(file_data)
                        temp_files.append(tmp.name)
                        filenames.append(filename)
                    print(f"[InboxMonitor] Saved attachment: {filename}")
            else:
                # No attachments — save email body as .eml for parsing
                with tempfile.NamedTemporaryFile(suffix=".eml", delete=False) as tmp:
                    tmp.write(raw_email)
                    temp_files.append(tmp.name)
                    filenames.append("email_body.eml")
                print("[InboxMonitor] No attachments, saved email body for parsing")

            # Call the callback with temp file paths and metadata
            self._callback(
                job_reference=job_reference,
                temp_files=temp_files,
                vendor_email=vendor_email,
                filenames=filenames,
                subject=subject,
            )

            # Mark as SEEN (it was fetched as UNSEEN, IMAP auto-marks on fetch
            # but we explicitly flag it to be safe)
            conn.store(msg_id, "+FLAGS", "\\Seen")

        finally:
            # Clean up temp files
            for tf in temp_files:
                try:
                    if os.path.exists(tf):
                        os.unlink(tf)
                except Exception:
                    pass

    def _matches_quote_pattern(self, subject: str) -> bool:
        """Check if the email subject matches any quote-related pattern."""
        for pattern in self._subject_patterns:
            if re.search(pattern, subject):
                return True
        return False

    def _extract_attachments(self, msg) -> list[tuple[str, bytes]]:
        """Extract PDF/document attachments from email."""
        attachments = []
        supported_extensions = {".pdf", ".xlsx", ".xls", ".csv", ".txt", ".eml"}

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            filename = part.get_filename()
            if not filename:
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext in supported_extensions:
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append((filename, payload))

        return attachments

    def _extract_job_reference(self, subject: str) -> Optional[str]:
        """Try to extract job/project reference from email subject.

        Looks for patterns like:
          - "Re: Quote Request - Project Name"
          - "Re: [SI] Project Name - Quote Request"
          - "Pricing for Project Name"
        """
        # Strip common prefixes
        cleaned = subject.strip()
        # Remove Re:/Fwd: prefixes
        cleaned = re.sub(r"^(?:re|fwd?):\s*", "", cleaned, flags=re.IGNORECASE).strip()
        # Remove [EXT] or similar brackets
        cleaned = re.sub(r"\[(?:EXT|EXTERNAL)\]\s*:?\s*", "", cleaned, flags=re.IGNORECASE).strip()

        # Try to extract project name after common delimiters
        # "Quote Request - Project Name" or "Quote Request: Project Name"
        for sep in [" - ", ": ", " — ", " – "]:
            if sep in cleaned:
                parts = cleaned.split(sep)
                # The project name is usually after "Quote Request" or similar
                for i, part in enumerate(parts):
                    if re.search(r"(?i)quote|pricing|price", part):
                        # Return the other part(s) as the project reference
                        remaining = sep.join(parts[i + 1:]).strip()
                        if remaining:
                            return remaining
                # If no quote keyword found, return the full cleaned subject
                break

        # Fallback: return the cleaned subject as-is for fuzzy matching downstream
        return cleaned if cleaned else None

    def _extract_email_address(self, from_header: str) -> str:
        """Extract just the email address from a From header.

        Handles formats like:
          - "John Doe <john@example.com>"
          - "john@example.com"
        """
        match = re.search(r"<([^>]+)>", from_header)
        if match:
            return match.group(1).strip()
        # Might just be a bare email
        match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", from_header)
        if match:
            return match.group(0)
        return from_header.strip()

    def check_now(self):
        """Manually trigger an inbox check (for testing or on-demand)."""
        self._check_inbox()
