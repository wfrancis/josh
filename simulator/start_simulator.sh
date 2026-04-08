#!/usr/bin/env bash
# ============================================================================
# SI Bid Tool — Simulator Launcher (macOS/Linux)
# Cross-platform alternative to start_simulator.bat (which remains for Windows).
#
# Starts: SMTP Relay (2525) + Bid Tool Server (8000) + Vendor Simulator (8100)
# Usage:  ./simulator/start_simulator.sh
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"

# ── Find Python >= 3.10 ──────────────────────────────────────────────────

PYTHON=""
for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 \
                 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 python3; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.10+ required. Install via: brew install python@3.12"
    exit 1
fi

echo "Using $($PYTHON --version) at $PYTHON"

# ── Create venv if needed ─────────────────────────────────────────────────

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# ── Install dependencies ──────────────────────────────────────────────────

echo "Installing dependencies..."
pip install -q -r "$PROJECT_ROOT/server/requirements.txt" httpx 2>&1 | tail -1

# ── Create mailbox directories ────────────────────────────────────────────

mkdir -p "$SCRIPT_DIR/mailbox/vendor_inbox/processed"
mkdir -p "$SCRIPT_DIR/mailbox/bidtool_inbox/processed"

# ── Cleanup on exit ───────────────────────────────────────────────────────

PIDS=()
cleanup() {
    echo ""
    echo "Shutting down all services..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null
    echo "All services stopped."
}
trap cleanup EXIT INT TERM

# ── 1. SMTP Relay ─────────────────────────────────────────────────────────

echo ""
echo "[1/3] Starting SMTP Relay on localhost:2525..."
python "$SCRIPT_DIR/smtp_relay.py" --port 2525 &
PIDS+=($!)
sleep 1

# ── 2. Bid Tool Server ───────────────────────────────────────────────────

echo "[2/3] Starting Bid Tool Server on http://localhost:8000..."
(cd "$PROJECT_ROOT/server" && python -m uvicorn main:app --host 127.0.0.1 --port 8000) &
PIDS+=($!)
sleep 2

# ── 3. Vendor Simulator ──────────────────────────────────────────────────

echo "[3/3] Starting Vendor Simulator on http://localhost:8100..."
(cd "$SCRIPT_DIR/vendor_app" && python -m uvicorn main:app --host 127.0.0.1 --port 8100) &
PIDS+=($!)
sleep 1

# ── Ready ──────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo "  All services running!"
echo ""
echo "  Bid Tool:         http://localhost:8000"
echo "  Vendor Simulator: http://localhost:8100"
echo "  SMTP Relay:       localhost:2525"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Open http://localhost:8000 → Settings → enable Test Mode"
echo "  2. Create a job with materials, then Request Quotes"
echo "  3. Open http://localhost:8100 to see requests arrive"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

wait
