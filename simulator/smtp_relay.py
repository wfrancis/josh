#!/usr/bin/env python3
"""
SI Bid Tool — Python SMTP Relay
Cross-platform alternative to smtp_relay.ps1 (which remains for Windows users).

Lightweight SMTP listener on localhost:2525.
Routes emails to vendor_inbox/ or bidtool_inbox/ based on To: header.
"""

import argparse
import os
import re
import socketserver
import sys
from datetime import datetime
from pathlib import Path

# ── Globals (set by main()) ────────────────────────────────────────────────

MAILBOX_DIR = Path(__file__).parent / "mailbox"
VENDOR_INBOX = MAILBOX_DIR / "vendor_inbox"
BIDTOOL_INBOX = MAILBOX_DIR / "bidtool_inbox"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def route_folder(to_addr: str) -> Path:
    """Route by To: address — standard/si-bid → bidtool, else → vendor."""
    if re.search(r"(?i)standard|si-bid|si_bid", to_addr):
        return BIDTOOL_INBOX
    return VENDOR_INBOX


def save_eml(folder: Path, to_addr: str, data: str):
    """Write .eml file with UTF-8 (no BOM). Returns filename."""
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]  # yyyyMMdd_HHmmss_fff
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", to_addr).strip("_")[:50] or "unknown"
    filename = f"{ts}_{safe}.eml"
    filepath = folder / filename
    filepath.write_text(data, encoding="utf-8")
    log(f"Saved: {filename} -> {folder.name} (To: {to_addr})")
    return filename


class SMTPHandler(socketserver.StreamRequestHandler):
    """Handle one SMTP session (EHLO, MAIL FROM, RCPT TO, DATA, QUIT)."""

    def handle(self):
        remote = self.client_address
        log(f"Connection from {remote[0]}:{remote[1]}")

        self._send(b"220 localhost SI-SMTP-Relay Ready\r\n")

        mail_from = ""
        rcpt_to = []
        in_data = False
        data_lines = []

        while True:
            try:
                raw = self.rfile.readline()
            except Exception:
                break
            if not raw:
                break

            line = raw.decode("utf-8", errors="replace")

            if in_data:
                stripped = line.rstrip("\r\n")
                if stripped == ".":
                    # End of DATA
                    in_data = False
                    self._send(b"250 OK Message accepted\r\n")

                    # Undo dot-stuffing and join
                    body = ""
                    for dl in data_lines:
                        if dl.startswith(".."):
                            dl = dl[1:]
                        body += dl + "\r\n"

                    # Route and save
                    to_addr = rcpt_to[0] if rcpt_to else ""
                    folder = route_folder(to_addr)
                    save_eml(folder, to_addr, body)

                    # Reset for next message in same session
                    mail_from = ""
                    rcpt_to = []
                    data_lines = []
                else:
                    data_lines.append(stripped)
                continue

            cmd = line.strip()
            cmd_upper = cmd.upper()

            if cmd_upper.startswith("EHLO") or cmd_upper.startswith("HELO"):
                self._send(b"250-localhost\r\n")
                self._send(b"250-SIZE 10485760\r\n")
                self._send(b"250 OK\r\n")

            elif cmd_upper.startswith("MAIL FROM:"):
                mail_from = re.sub(r"(?i)MAIL FROM:\s*", "", cmd).strip("<> ")
                self._send(b"250 OK\r\n")

            elif cmd_upper.startswith("RCPT TO:"):
                addr = re.sub(r"(?i)RCPT TO:\s*", "", cmd).strip("<> ")
                rcpt_to.append(addr)
                self._send(b"250 OK\r\n")

            elif cmd_upper == "DATA":
                self._send(b"354 Start mail input; end with <CRLF>.<CRLF>\r\n")
                in_data = True
                data_lines = []

            elif cmd_upper == "QUIT":
                self._send(b"221 Bye\r\n")
                break

            elif cmd_upper == "RSET":
                mail_from = ""
                rcpt_to = []
                data_lines = []
                self._send(b"250 OK\r\n")

            elif cmd_upper == "NOOP":
                self._send(b"250 OK\r\n")

            else:
                self._send(b"500 Command not recognized\r\n")

    def _send(self, data: bytes):
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except BrokenPipeError:
            pass


class ThreadedSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    global MAILBOX_DIR, VENDOR_INBOX, BIDTOOL_INBOX

    parser = argparse.ArgumentParser(description="SI Bid Tool — Python SMTP Relay")
    parser.add_argument("--port", type=int, default=2525, help="SMTP listen port (default: 2525)")
    parser.add_argument("--mailbox-dir", default=str(Path(__file__).parent / "mailbox"),
                        help="Mailbox root directory")
    args = parser.parse_args()

    MAILBOX_DIR = Path(args.mailbox_dir)
    VENDOR_INBOX = MAILBOX_DIR / "vendor_inbox"
    BIDTOOL_INBOX = MAILBOX_DIR / "bidtool_inbox"

    # Create directories
    for d in [VENDOR_INBOX, VENDOR_INBOX / "processed",
              BIDTOOL_INBOX, BIDTOOL_INBOX / "processed"]:
        d.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("  SI Bid Tool — SMTP Relay (Python)")
    print(f"  Listening on localhost:{args.port}")
    print(f"  Vendor inbox:  {VENDOR_INBOX}")
    print(f"  BidTool inbox: {BIDTOOL_INBOX}")
    print("=" * 50)

    server = ThreadedSMTPServer(("127.0.0.1", args.port), SMTPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("SMTP Relay shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
