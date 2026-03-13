"""
SQLite database layer using plain sqlite3 (no ORM).
Tables: jobs, job_materials, job_sundries, job_labor, job_bundles.
"""

import sqlite3
import os
import re
from datetime import datetime
from typing import Optional


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    s = text.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "si_bid_tool.db"))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                gc_name TEXT,
                address TEXT,
                city TEXT,
                state TEXT,
                zip TEXT,
                tax_rate REAL DEFAULT 0.0,
                unit_count INTEGER DEFAULT 0,
                salesperson TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                item_code TEXT,
                description TEXT,
                material_type TEXT,
                installed_qty REAL DEFAULT 0,
                unit TEXT,
                waste_pct REAL DEFAULT 0,
                order_qty REAL DEFAULT 0,
                vendor TEXT,
                unit_price REAL DEFAULT 0,
                extended_cost REAL DEFAULT 0,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS job_sundries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                material_id INTEGER,
                sundry_name TEXT,
                qty REAL DEFAULT 0,
                unit TEXT,
                unit_price REAL DEFAULT 0,
                extended_cost REAL DEFAULT 0,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (material_id) REFERENCES job_materials(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS job_labor (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                material_id INTEGER,
                labor_description TEXT,
                qty REAL DEFAULT 0,
                unit TEXT,
                rate REAL DEFAULT 0,
                extended_cost REAL DEFAULT 0,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (material_id) REFERENCES job_materials(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS job_bundles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                bundle_name TEXT,
                description_text TEXT,
                installed_qty REAL DEFAULT 0,
                unit TEXT,
                total_price REAL DEFAULT 0,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        conn.commit()
        # Migrations for existing DBs
        for col, sql in [
            ("notes", "ALTER TABLE jobs ADD COLUMN notes TEXT"),
            ("slug", "ALTER TABLE jobs ADD COLUMN slug TEXT"),
        ]:
            try:
                conn.execute(sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Backfill slugs for any jobs missing them
        rows = conn.execute("SELECT id, project_name FROM jobs WHERE slug IS NULL OR slug = ''").fetchall()
        for row in rows:
            slug = _make_unique_slug(conn, _slugify(row[1]), exclude_id=row[0])
            conn.execute("UPDATE jobs SET slug=? WHERE id=?", (slug, row[0]))
        if rows:
            conn.commit()
    finally:
        conn.close()


def _make_unique_slug(conn, base_slug: str, exclude_id: int = None) -> str:
    """Ensure slug is unique, appending -2, -3, etc. if needed."""
    slug = base_slug
    counter = 2
    while True:
        if exclude_id:
            row = conn.execute("SELECT id FROM jobs WHERE slug=? AND id!=?", (slug, exclude_id)).fetchone()
        else:
            row = conn.execute("SELECT id FROM jobs WHERE slug=?", (slug,)).fetchone()
        if not row:
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


def save_job(job_data: dict) -> int:
    """Insert or update a job. Returns the job id."""
    conn = _get_conn()
    try:
        job_id = job_data.get("id")
        slug = _slugify(job_data["project_name"])
        if job_id:
            slug = _make_unique_slug(conn, slug, exclude_id=job_id)
            conn.execute("""
                UPDATE jobs SET
                    project_name=?, gc_name=?, address=?, city=?, state=?, zip=?,
                    tax_rate=?, unit_count=?, salesperson=?, notes=?, slug=?
                WHERE id=?
            """, (
                job_data["project_name"], job_data.get("gc_name"),
                job_data.get("address"), job_data.get("city"),
                job_data.get("state"), job_data.get("zip"),
                job_data.get("tax_rate", 0), job_data.get("unit_count", 0),
                job_data.get("salesperson"), job_data.get("notes"), slug, job_id
            ))
        else:
            slug = _make_unique_slug(conn, slug)
            cur = conn.execute("""
                INSERT INTO jobs (project_name, gc_name, address, city, state, zip,
                                  tax_rate, unit_count, salesperson, notes, slug, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_data["project_name"], job_data.get("gc_name"),
                job_data.get("address"), job_data.get("city"),
                job_data.get("state"), job_data.get("zip"),
                job_data.get("tax_rate", 0), job_data.get("unit_count", 0),
                job_data.get("salesperson"), job_data.get("notes"), slug,
                datetime.now().isoformat()
            ))
            job_id = cur.lastrowid
        conn.commit()
        return job_id
    finally:
        conn.close()


def save_materials(job_id: int, materials: list[dict]) -> list[int]:
    """Save material lines for a job. Returns list of material ids."""
    conn = _get_conn()
    try:
        # Clear existing materials for this job
        conn.execute("DELETE FROM job_materials WHERE job_id=?", (job_id,))
        ids = []
        for m in materials:
            cur = conn.execute("""
                INSERT INTO job_materials
                    (job_id, item_code, description, material_type, installed_qty,
                     unit, waste_pct, order_qty, vendor, unit_price, extended_cost)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, m.get("item_code"), m.get("description"),
                m.get("material_type"), m.get("installed_qty", 0),
                m.get("unit"), m.get("waste_pct", 0), m.get("order_qty", 0),
                m.get("vendor"), m.get("unit_price", 0), m.get("extended_cost", 0)
            ))
            ids.append(cur.lastrowid)
        conn.commit()
        return ids
    finally:
        conn.close()


def save_sundries(job_id: int, sundries: list[dict]) -> None:
    """Save sundry lines for a job."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM job_sundries WHERE job_id=?", (job_id,))
        for s in sundries:
            conn.execute("""
                INSERT INTO job_sundries
                    (job_id, material_id, sundry_name, qty, unit, unit_price, extended_cost)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, s.get("material_id"), s.get("sundry_name"),
                s.get("qty", 0), s.get("unit"),
                s.get("unit_price", 0), s.get("extended_cost", 0)
            ))
        conn.commit()
    finally:
        conn.close()


def save_labor(job_id: int, labor_items: list[dict]) -> None:
    """Save labor lines for a job."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM job_labor WHERE job_id=?", (job_id,))
        for l in labor_items:
            conn.execute("""
                INSERT INTO job_labor
                    (job_id, material_id, labor_description, qty, unit, rate, extended_cost)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, l.get("material_id"), l.get("labor_description"),
                l.get("qty", 0), l.get("unit"),
                l.get("rate", 0), l.get("extended_cost", 0)
            ))
        conn.commit()
    finally:
        conn.close()


def save_bundles(job_id: int, bundles: list[dict]) -> None:
    """Save bundle lines for a job."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM job_bundles WHERE job_id=?", (job_id,))
        for b in bundles:
            conn.execute("""
                INSERT INTO job_bundles
                    (job_id, bundle_name, description_text, installed_qty, unit, total_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                job_id, b.get("bundle_name"), b.get("description_text"),
                b.get("installed_qty", 0), b.get("unit"),
                b.get("total_price", 0)
            ))
        conn.commit()
    finally:
        conn.close()


def delete_job(job_ref) -> bool:
    """Delete a job by ID or slug and all related data (cascading)."""
    conn = _get_conn()
    try:
        if isinstance(job_ref, int) or (isinstance(job_ref, str) and job_ref.isdigit()):
            cur = conn.execute("DELETE FROM jobs WHERE id=?", (int(job_ref),))
        else:
            cur = conn.execute("DELETE FROM jobs WHERE slug=?", (job_ref,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def load_job(job_ref) -> Optional[dict]:
    """Load a job by ID (int) or slug (str) with all related data."""
    conn = _get_conn()
    try:
        if isinstance(job_ref, int) or (isinstance(job_ref, str) and job_ref.isdigit()):
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (int(job_ref),)).fetchone()
        else:
            row = conn.execute("SELECT * FROM jobs WHERE slug=?", (job_ref,)).fetchone()
        if not row:
            return None
        job = dict(row)
        jid = job["id"]

        job["materials"] = [
            dict(r) for r in
            conn.execute("SELECT * FROM job_materials WHERE job_id=? ORDER BY id", (jid,)).fetchall()
        ]
        job["sundries"] = [
            dict(r) for r in
            conn.execute("SELECT * FROM job_sundries WHERE job_id=? ORDER BY id", (jid,)).fetchall()
        ]
        job["labor"] = [
            dict(r) for r in
            conn.execute("SELECT * FROM job_labor WHERE job_id=? ORDER BY id", (jid,)).fetchall()
        ]
        job["bundles"] = [
            dict(r) for r in
            conn.execute("SELECT * FROM job_bundles WHERE job_id=? ORDER BY id", (jid,)).fetchall()
        ]
        return job
    finally:
        conn.close()


def get_settings() -> dict:
    """Get all app settings as a dict."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()


def save_settings(settings: dict) -> None:
    """Save app settings (upsert)."""
    conn = _get_conn()
    try:
        for key, value in settings.items():
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value))
            )
        conn.commit()
    finally:
        conn.close()


def list_jobs() -> list[dict]:
    """List all jobs (summary with bundle count)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT j.id, j.slug, j.project_name, j.gc_name, j.salesperson, j.city, j.state, j.created_at,
                      (SELECT COUNT(*) FROM job_bundles b WHERE b.job_id = j.id) AS bundle_count
               FROM jobs j ORDER BY j.created_at DESC"""
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            # Add bundles field for frontend compatibility
            d["bundles"] = [{}] * d.pop("bundle_count", 0)
            results.append(d)
        return results
    finally:
        conn.close()
