"""Build and estimating-engine identity information for trust surfaces."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


ENGINE_FILES = (
    "main.py",
    "config.py",
    "labor_calc.py",
    "sundry_calc.py",
    "proposal_bundler.py",
    "rfms_parser.py",
    "rules_registry.py",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    hashes = {}
    for name in ENGINE_FILES:
        path = root / name
        try:
            hashes[name] = _sha256_bytes(path.read_bytes())
        except OSError:
            hashes[name] = "missing"
    return hashes


def engine_fingerprint() -> str:
    payload = json.dumps(_file_hashes(), sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(payload.encode("utf-8"))


def _frontend_asset_version() -> str | None:
    root = Path(__file__).resolve().parent
    candidates = (root / "static" / "index.html", root.parent / "frontend" / "dist" / "index.html")
    for path in candidates:
        try:
            html = path.read_text(encoding="utf-8")
        except OSError:
            continue
        marker = "assets/index-"
        start = html.find(marker)
        if start >= 0:
            end = html.find('"', start)
            if end > start:
                return html[start:end]
    return None


def get_build_info() -> dict:
    """Return stable build metadata without requiring Git in the runtime image."""
    return {
        "commit": os.getenv("BUILD_COMMIT", "unknown"),
        "tag": os.getenv("BUILD_TAG", "unknown"),
        "built_at": os.getenv("BUILD_TIME", "unknown"),
        "environment": os.getenv("BUILD_ENV", "unknown"),
        "engine_fingerprint": engine_fingerprint(),
        "engine_files": _file_hashes(),
        "frontend_asset": os.getenv("FRONTEND_ASSET", _frontend_asset_version()),
    }


def build_manifest_for_snapshot() -> dict:
    """Return the build fields that belong inside a golden snapshot."""
    info = get_build_info()
    return {
        "commit": info["commit"],
        "tag": info["tag"],
        "built_at": info["built_at"],
        "environment": info["environment"],
        "engine_fingerprint": info["engine_fingerprint"],
        "frontend_asset": info["frontend_asset"],
    }
