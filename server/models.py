"""
SQLite database layer using plain sqlite3 (no ORM).
Tables: jobs, job_materials, job_sundries, job_labor, job_bundles.
"""

import sqlite3
import os
import re
import io
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

            CREATE TABLE IF NOT EXISTS job_quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                product_name TEXT,
                vendor TEXT,
                unit_price REAL DEFAULT 0,
                unit TEXT,
                description TEXT,
                file_name TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS labor_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                labor_type TEXT NOT NULL,
                description TEXT DEFAULT '',
                cost REAL DEFAULT 0,
                retail_display TEXT DEFAULT '',
                unit TEXT DEFAULT '',
                gpm_markup REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS price_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                material_type TEXT DEFAULT '',
                unit TEXT DEFAULT '',
                unit_price REAL DEFAULT 0,
                vendor TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS company_rates (
                rate_type TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                contact_name TEXT,
                contact_title TEXT,
                contact_email TEXT,
                contact_phone TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vendor_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                unit_price REAL NOT NULL,
                vendor_id INTEGER,
                vendor_name TEXT DEFAULT '',
                job_id INTEGER,
                job_quote_id INTEGER,
                product_normalized TEXT,
                unit TEXT DEFAULT '',
                freight_per_unit REAL,
                total_per_unit REAL,
                quantity REAL,
                lead_time TEXT,
                quote_date TEXT,
                quote_valid_until TEXT,
                file_name TEXT,
                won_bid INTEGER DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE SET NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL,
                FOREIGN KEY (job_quote_id) REFERENCES job_quotes(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS imported_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size INTEGER,
                source TEXT DEFAULT 'manual',
                imported_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_imported_files_dedup
                ON imported_files(job_id, file_hash);

            CREATE TABLE IF NOT EXISTS job_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                summary TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS job_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS quote_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                vendor_id INTEGER,
                vendor_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                material_ids TEXT NOT NULL,
                request_text TEXT,
                sent_at TEXT,
                received_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS price_book_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor TEXT NOT NULL,
                product_line TEXT NOT NULL,
                item_no TEXT NOT NULL,
                material_finish TEXT DEFAULT '',
                size_mm TEXT DEFAULT '',
                size_inches TEXT DEFAULT '',
                list_price REAL NOT NULL,
                discount_pct REAL DEFAULT 0,
                net_price REAL NOT NULL,
                length TEXT DEFAULT '',
                unit TEXT DEFAULT 'length',
                category TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_price_book_vendor ON price_book_items(vendor);
            CREATE INDEX IF NOT EXISTS idx_price_book_product_line ON price_book_items(product_line);
        """)
        conn.commit()
        # Migrations for existing DBs
        for col, sql in [
            ("notes", "ALTER TABLE jobs ADD COLUMN notes TEXT"),
            ("slug", "ALTER TABLE jobs ADD COLUMN slug TEXT"),
            ("ai_confidence", "ALTER TABLE job_materials ADD COLUMN ai_confidence REAL"),
            ("exclusions", "ALTER TABLE jobs ADD COLUMN exclusions TEXT"),
            ("markup_pct", "ALTER TABLE jobs ADD COLUMN markup_pct REAL DEFAULT 0"),
            ("bid_data", "ALTER TABLE jobs ADD COLUMN bid_data TEXT"),
            ("architect", "ALTER TABLE jobs ADD COLUMN architect TEXT"),
            ("designer", "ALTER TABLE jobs ADD COLUMN designer TEXT"),
            ("quote_status", "ALTER TABLE job_materials ADD COLUMN quote_status TEXT"),
            ("quoted_at", "ALTER TABLE job_quotes ADD COLUMN quoted_at TEXT"),
            ("jq_freight", "ALTER TABLE job_quotes ADD COLUMN freight REAL"),
            ("jq_lead_time", "ALTER TABLE job_quotes ADD COLUMN lead_time TEXT"),
            ("jq_notes", "ALTER TABLE job_quotes ADD COLUMN notes TEXT"),
            ("price_source", "ALTER TABLE job_materials ADD COLUMN price_source TEXT"),
            ("activity_user", "ALTER TABLE job_activity ADD COLUMN user TEXT DEFAULT 'System'"),
            ("comment_user", "ALTER TABLE job_comments ADD COLUMN user TEXT DEFAULT 'System'"),
            ("qr_response_file", "ALTER TABLE quote_requests ADD COLUMN response_file TEXT"),
            ("qr_response_notes", "ALTER TABLE quote_requests ADD COLUMN response_notes TEXT"),
            ("gpm_pct", "ALTER TABLE jobs ADD COLUMN gpm_pct REAL DEFAULT 0"),
        ]:
            try:
                conn.execute(sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Indexes for vendor_prices
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_vendor_prices_vendor ON vendor_prices(vendor_id)",
            "CREATE INDEX IF NOT EXISTS idx_vendor_prices_product ON vendor_prices(product_normalized)",
            "CREATE INDEX IF NOT EXISTS idx_vendor_prices_job ON vendor_prices(job_id)",
            "CREATE INDEX IF NOT EXISTS idx_vendor_prices_date ON vendor_prices(quote_date)",
            "CREATE INDEX IF NOT EXISTS idx_vendors_name ON vendors(name)",
            "CREATE INDEX IF NOT EXISTS idx_job_activity_job ON job_activity(job_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_job_comments_job ON job_comments(job_id, created_at DESC)",
        ]:
            try:
                conn.execute(idx_sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass

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
    import json as _json
    conn = _get_conn()
    try:
        job_id = job_data.get("id")
        slug = _slugify(job_data["project_name"])
        # Ensure bid_data is stored as JSON string, not dict
        bid_data_val = job_data.get("bid_data")
        if isinstance(bid_data_val, dict):
            bid_data_val = _json.dumps(bid_data_val)
        if job_id:
            slug = _make_unique_slug(conn, slug, exclude_id=job_id)
            conn.execute("""
                UPDATE jobs SET
                    project_name=?, gc_name=?, address=?, city=?, state=?, zip=?,
                    tax_rate=?, unit_count=?, salesperson=?, notes=?, slug=?, exclusions=?,
                    markup_pct=?, bid_data=?, architect=?, designer=?
                WHERE id=?
            """, (
                job_data["project_name"], job_data.get("gc_name"),
                job_data.get("address"), job_data.get("city"),
                job_data.get("state"), job_data.get("zip"),
                job_data.get("tax_rate", 0), job_data.get("unit_count", 0),
                job_data.get("salesperson"), job_data.get("notes"), slug,
                job_data.get("exclusions"), job_data.get("markup_pct", 0),
                bid_data_val, job_data.get("architect"), job_data.get("designer"),
                job_id
            ))
        else:
            slug = _make_unique_slug(conn, slug)
            cur = conn.execute("""
                INSERT INTO jobs (project_name, gc_name, address, city, state, zip,
                                  tax_rate, unit_count, salesperson, notes, slug, exclusions,
                                  markup_pct, bid_data, architect, designer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_data["project_name"], job_data.get("gc_name"),
                job_data.get("address"), job_data.get("city"),
                job_data.get("state"), job_data.get("zip"),
                job_data.get("tax_rate", 0), job_data.get("unit_count", 0),
                job_data.get("salesperson"), job_data.get("notes"), slug,
                job_data.get("exclusions"), job_data.get("markup_pct", 0),
                bid_data_val, job_data.get("architect"), job_data.get("designer"),
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
                     unit, waste_pct, order_qty, vendor, unit_price, extended_cost, ai_confidence,
                     quote_status, price_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, m.get("item_code"), m.get("description"),
                m.get("material_type"), m.get("installed_qty", 0),
                m.get("unit"), m.get("waste_pct", 0), m.get("order_qty", 0),
                m.get("vendor"), m.get("unit_price", 0), m.get("extended_cost", 0),
                m.get("ai_confidence"), m.get("quote_status"), m.get("price_source")
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


def save_quotes(job_id: int, quotes: list[dict]) -> list[int]:
    """Save parsed quote products for a job. Returns list of quote ids."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM job_quotes WHERE job_id=?", (job_id,))
        ids = []
        for q in quotes:
            if q.get("error"):
                continue  # Skip error entries
            cur = conn.execute("""
                INSERT INTO job_quotes
                    (job_id, product_name, vendor, unit_price, unit, description, file_name,
                     quoted_at, freight, lead_time, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, q.get("product_name"), q.get("vendor"),
                q.get("unit_price", 0), q.get("unit"),
                q.get("description"), q.get("file_name"),
                datetime.now().isoformat(),
                q.get("freight"), q.get("lead_time"), q.get("notes")
            ))
            ids.append(cur.lastrowid)
        conn.commit()
        return ids
    finally:
        conn.close()


def update_quote(quote_id: int, data: dict) -> bool:
    """Update a single quote entry and return success."""
    conn = _get_conn()
    try:
        fields = []
        values = []
        for key in ("product_name", "vendor", "unit_price", "unit", "description"):
            if key in data:
                fields.append(f"{key}=?")
                values.append(data[key])
        if not fields:
            return False
        values.append(quote_id)
        conn.execute(f"UPDATE job_quotes SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def get_quote_job_id(quote_id: int) -> int | None:
    """Get the job_id for a quote entry."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT job_id FROM job_quotes WHERE id=?", (quote_id,)).fetchone()
        return row["job_id"] if row else None
    finally:
        conn.close()


def delete_quotes(job_id: int) -> None:
    """Delete all quotes for a job."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM job_quotes WHERE job_id=?", (job_id,))
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

        # Parse bid_data JSON if present
        import json as _json
        raw_bid = job.get("bid_data")
        if raw_bid:
            try:
                job["bid_data"] = _json.loads(raw_bid)
            except (ValueError, TypeError):
                job["bid_data"] = None

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
        job["quotes"] = [
            dict(r) for r in
            conn.execute("SELECT * FROM job_quotes WHERE job_id=? ORDER BY id", (jid,)).fetchall()
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


def search_all(query: str) -> dict:
    """Search jobs and materials by query string."""
    conn = _get_conn()
    try:
        q = f"%{query}%"
        jobs = [
            dict(r) for r in
            conn.execute(
                """SELECT id, slug, project_name, gc_name, salesperson, city, state
                   FROM jobs
                   WHERE project_name LIKE ? OR gc_name LIKE ? OR salesperson LIKE ? OR city LIKE ?
                   ORDER BY created_at DESC LIMIT 10""",
                (q, q, q, q)
            ).fetchall()
        ]
        mat_rows = conn.execute(
            """SELECT m.job_id, m.item_code, m.description, m.material_type,
                      j.project_name, j.slug
               FROM job_materials m
               JOIN jobs j ON m.job_id = j.id
               WHERE m.description LIKE ? OR m.item_code LIKE ?
               ORDER BY m.job_id DESC LIMIT 20""",
            (q, q)
        ).fetchall()
        # Group materials by job
        mat_by_job = {}
        for r in mat_rows:
            r = dict(r)
            key = r["job_id"]
            if key not in mat_by_job:
                mat_by_job[key] = {
                    "job_id": r["job_id"],
                    "project_name": r["project_name"],
                    "slug": r["slug"],
                    "matches": []
                }
            mat_by_job[key]["matches"].append({
                "item_code": r["item_code"],
                "description": r["description"],
                "material_type": r["material_type"],
            })
        return {"jobs": jobs, "materials": list(mat_by_job.values())}
    finally:
        conn.close()


# ── Labor Catalog ────────────────────────────────────────────────────────────

def save_labor_catalog_entries(entries: list[dict]) -> None:
    """Replace all labor catalog entries."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM labor_catalog")
        for e in entries:
            conn.execute("""
                INSERT INTO labor_catalog
                    (labor_type, description, cost, retail_display, unit, gpm_markup)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                e.get("labor_type", ""), e.get("description", ""),
                e.get("cost", 0), e.get("retail_display", ""),
                e.get("unit", ""), e.get("gpm_markup", 0)
            ))
        conn.commit()
    finally:
        conn.close()


def get_labor_catalog_entries() -> list[dict]:
    """Get all labor catalog entries from DB."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM labor_catalog ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_labor_catalog_entry(entry_id: int, data: dict) -> bool:
    """Update a single labor catalog entry."""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            UPDATE labor_catalog SET labor_type=?, description=?, cost=?, retail_display=?, unit=?, gpm_markup=?
            WHERE id=?
        """, (
            data.get("labor_type", ""), data.get("description", ""),
            data.get("cost", 0), data.get("retail_display", ""),
            data.get("unit", ""), data.get("gpm_markup", 0),
            entry_id
        ))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_labor_catalog_entry(entry_id: int) -> bool:
    """Delete a single labor catalog entry."""
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM labor_catalog WHERE id=?", (entry_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_labor_catalog() -> None:
    """Delete all labor catalog entries."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM labor_catalog")
        conn.commit()
    finally:
        conn.close()


def clear_price_list() -> None:
    """Delete all price list entries."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM price_list")
        conn.commit()
    finally:
        conn.close()


# ── Price List ───────────────────────────────────────────────────────────────

def save_price_list_entries(entries: list[dict]) -> None:
    """Replace all price list entries."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM price_list")
        for e in entries:
            conn.execute("""
                INSERT INTO price_list
                    (product_name, material_type, unit, unit_price, vendor, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                e.get("product_name", ""), e.get("material_type", ""),
                e.get("unit", ""), e.get("unit_price", 0),
                e.get("vendor", ""), e.get("notes", "")
            ))
        conn.commit()
    finally:
        conn.close()


def add_price_list_entry(entry: dict) -> int:
    """Add a single price list entry. Returns the id."""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            INSERT INTO price_list
                (product_name, material_type, unit, unit_price, vendor, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            entry.get("product_name", ""), entry.get("material_type", ""),
            entry.get("unit", ""), entry.get("unit_price", 0),
            entry.get("vendor", ""), entry.get("notes", "")
        ))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_price_list_entry(entry_id: int, entry: dict) -> bool:
    """Update a price list entry. Returns True if found."""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            UPDATE price_list SET
                product_name=?, material_type=?, unit=?, unit_price=?, vendor=?, notes=?
            WHERE id=?
        """, (
            entry.get("product_name", ""), entry.get("material_type", ""),
            entry.get("unit", ""), entry.get("unit_price", 0),
            entry.get("vendor", ""), entry.get("notes", ""),
            entry_id
        ))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_price_list_entry(entry_id: int) -> bool:
    """Delete a price list entry. Returns True if found."""
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM price_list WHERE id=?", (entry_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_price_list_entries() -> list[dict]:
    """Get all price list entries."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM price_list ORDER BY product_name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Company Rates ────────────────────────────────────────────────────────────

def get_company_rate(rate_type: str) -> Optional[str]:
    """Get a company rate JSON blob by type."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT data FROM company_rates WHERE rate_type=?", (rate_type,)).fetchone()
        return row["data"] if row else None
    finally:
        conn.close()


def save_company_rate(rate_type: str, data: str) -> None:
    """Save a company rate JSON blob (upsert)."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO company_rates (rate_type, data) VALUES (?, ?) "
            "ON CONFLICT(rate_type) DO UPDATE SET data=excluded.data",
            (rate_type, data)
        )
        conn.commit()
    finally:
        conn.close()


def get_all_company_rates() -> dict:
    """Get all company rates as {rate_type: parsed_json}."""
    import json as _json
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT rate_type, data FROM company_rates").fetchall()
        result = {}
        for r in rows:
            try:
                result[r["rate_type"]] = _json.loads(r["data"])
            except (ValueError, TypeError):
                result[r["rate_type"]] = r["data"]
        return result
    finally:
        conn.close()


def list_jobs() -> list[dict]:
    """List all jobs (summary with bundle count)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT j.id, j.slug, j.project_name, j.gc_name, j.salesperson, j.city, j.state, j.created_at,
                      (SELECT COUNT(*) FROM job_bundles b WHERE b.job_id = j.id) AS bundle_count,
                      (SELECT COUNT(*) FROM job_materials m WHERE m.job_id = j.id) AS material_count,
                      (SELECT COUNT(*) FROM job_materials m WHERE m.job_id = j.id AND m.unit_price > 0) AS priced_count
               FROM jobs j ORDER BY j.created_at DESC"""
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            # Add bundles field for frontend compatibility
            d["bundles"] = [{}] * d.pop("bundle_count", 0)
            # Add materials summary for status calculation
            mc = d.pop("material_count", 0)
            pc = d.pop("priced_count", 0)
            if mc > 0:
                d["materials"] = [{"unit_price": 1}] * pc + [{"unit_price": 0}] * (mc - pc)
            results.append(d)
        return results
    finally:
        conn.close()


# ── Vendor Pricing Intelligence ──────────────────────────────────────────────

def _normalize_product(name: str) -> str:
    """Normalize product name for matching."""
    s = (name or '').lower().strip()
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def get_or_create_vendor(name: str) -> int:
    """Get vendor by name or create. Returns vendor id."""
    conn = _get_conn()
    try:
        name = (name or '').strip()
        if not name:
            return None
        row = conn.execute("SELECT id FROM vendors WHERE name=?", (name,)).fetchone()
        if row:
            return row["id"]
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO vendors (name, created_at, updated_at) VALUES (?, ?, ?)",
            (name, now, now)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def save_vendor_prices_from_quotes(job_id: int, products: list[dict]) -> int:
    """Save parsed quote products to vendor_prices. Returns count saved."""
    conn = _get_conn()
    try:
        count = 0
        now = datetime.now().isoformat()
        for p in products:
            if p.get("error"):
                continue
            product_name = p.get("product_name")
            unit_price = p.get("unit_price")
            if not product_name or not unit_price:
                continue

            vendor_name = (p.get("vendor") or "").strip()
            vendor_id = None
            if vendor_name:
                # get_or_create_vendor opens its own connection, so do it outside
                pass

            product_normalized = _normalize_product(product_name)
            freight = p.get("freight")
            total = unit_price + (freight or 0)

            conn.execute("""
                INSERT INTO vendor_prices
                    (product_name, unit_price, vendor_name, job_id,
                     product_normalized, unit, freight_per_unit, total_per_unit,
                     quantity, lead_time, quote_date, file_name, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_name, unit_price, vendor_name, job_id,
                product_normalized, p.get("unit", ""), freight, total,
                p.get("quantity"), p.get("lead_time"),
                now, p.get("file_name"), p.get("notes"), now
            ))
            count += 1
        conn.commit()

        # Now link vendor_ids (separate pass to avoid nested connections)
        rows = conn.execute(
            "SELECT id, vendor_name FROM vendor_prices WHERE job_id=? AND vendor_id IS NULL AND vendor_name != ''",
            (job_id,)
        ).fetchall()
        vendor_cache = {}
        for row in rows:
            vname = row["vendor_name"]
            if vname not in vendor_cache:
                # Look up or create vendor
                vrow = conn.execute("SELECT id FROM vendors WHERE name=?", (vname,)).fetchone()
                if vrow:
                    vendor_cache[vname] = vrow["id"]
                else:
                    vnow = datetime.now().isoformat()
                    vcur = conn.execute(
                        "INSERT INTO vendors (name, created_at, updated_at) VALUES (?, ?, ?)",
                        (vname, vnow, vnow)
                    )
                    vendor_cache[vname] = vcur.lastrowid
            conn.execute("UPDATE vendor_prices SET vendor_id=? WHERE id=?",
                         (vendor_cache[vname], row["id"]))
        conn.commit()

        return count
    finally:
        conn.close()


def create_vendor(data: dict) -> dict:
    """Create a new vendor. Returns the created vendor dict."""
    conn = _get_conn()
    try:
        now = datetime.now().isoformat()
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Vendor name is required")
        # Check for existing vendor with same name
        existing = conn.execute("SELECT id FROM vendors WHERE name=?", (name,)).fetchone()
        if existing:
            raise ValueError(f"Vendor '{name}' already exists")
        cur = conn.execute(
            """INSERT INTO vendors (name, contact_name, contact_title, contact_email, contact_phone, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, data.get("contact_name", ""), data.get("contact_title", ""),
             data.get("contact_email", ""), data.get("contact_phone", ""),
             data.get("notes", ""), now, now)
        )
        conn.commit()
        vendor_id = cur.lastrowid
        row = conn.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_vendor(vendor_id: int) -> bool:
    """Delete a vendor and its associated vendor_prices."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM vendor_prices WHERE vendor_id=?", (vendor_id,))
        cur = conn.execute("DELETE FROM vendors WHERE id=?", (vendor_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def merge_vendors(keep_id: int, merge_ids: list[int]) -> bool:
    """Merge multiple vendor records into one. Reassigns vendor_prices and quote_requests, then deletes the duplicates."""
    conn = _get_conn()
    try:
        for mid in merge_ids:
            if mid == keep_id:
                continue
            conn.execute("UPDATE vendor_prices SET vendor_id=? WHERE vendor_id=?", (keep_id, mid))
            conn.execute("UPDATE quote_requests SET vendor_id=? WHERE vendor_id=?", (keep_id, mid))
            conn.execute("UPDATE job_materials SET vendor=(SELECT name FROM vendors WHERE id=?) WHERE vendor=(SELECT name FROM vendors WHERE id=?)", (keep_id, mid))
            conn.execute("DELETE FROM vendors WHERE id=?", (mid,))
        conn.commit()
        return True
    finally:
        conn.close()


def list_vendors() -> list[dict]:
    """List all vendors with last quote date."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT v.*,
                   (SELECT MAX(vp.created_at) FROM vendor_prices vp WHERE vp.vendor_id = v.id) AS last_quote_date,
                   (SELECT COUNT(*) FROM vendor_prices vp WHERE vp.vendor_id = v.id) AS price_count
            FROM vendors v
            ORDER BY v.name
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_vendor(vendor_id: int) -> dict | None:
    """Get vendor by ID with recent prices, quote stats, and request history."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
        if not row:
            return None
        vendor = dict(row)
        vendor_name = vendor["name"]

        # Price history grouped by job
        prices = conn.execute("""
            SELECT vp.*, j.project_name AS job_name
            FROM vendor_prices vp
            LEFT JOIN jobs j ON vp.job_id = j.id
            WHERE vp.vendor_id=?
            ORDER BY vp.created_at DESC
            LIMIT 100
        """, (vendor_id,)).fetchall()
        vendor["prices"] = [dict(r) for r in prices]

        # Also get prices matched by vendor name (some prices linked by name not ID)
        name_prices = conn.execute("""
            SELECT vp.*, j.project_name AS job_name
            FROM vendor_prices vp
            LEFT JOIN jobs j ON vp.job_id = j.id
            WHERE vp.vendor_name LIKE ? AND (vp.vendor_id IS NULL OR vp.vendor_id != ?)
            ORDER BY vp.created_at DESC
            LIMIT 50
        """, (f"%{vendor_name}%", vendor_id)).fetchall()
        # Merge, avoiding duplicates
        existing_ids = {p["id"] for p in vendor["prices"]}
        for p in name_prices:
            pd = dict(p)
            if pd["id"] not in existing_ids:
                vendor["prices"].append(pd)

        # Product categories summary
        categories = conn.execute("""
            SELECT product_normalized, COUNT(*) as count,
                   ROUND(AVG(unit_price), 2) as avg_price,
                   unit
            FROM vendor_prices
            WHERE vendor_id=? OR vendor_name LIKE ?
            GROUP BY product_normalized
            ORDER BY count DESC
            LIMIT 20
        """, (vendor_id, f"%{vendor_name}%")).fetchall()
        vendor["categories"] = [dict(c) for c in categories]

        # Quote request history with job names
        quote_requests = conn.execute("""
            SELECT qr.*, j.project_name AS job_name
            FROM quote_requests qr
            LEFT JOIN jobs j ON qr.job_id = j.id
            WHERE qr.vendor_id=? OR qr.vendor_name LIKE ?
            ORDER BY qr.created_at DESC
            LIMIT 30
        """, (vendor_id, f"%{vendor_name}%")).fetchall()
        vendor["quote_requests"] = [dict(qr) for qr in quote_requests]

        # KPI stats
        total_requests = len(vendor["quote_requests"])
        sent_requests = [qr for qr in vendor["quote_requests"] if qr.get("sent_at")]
        received_requests = [qr for qr in vendor["quote_requests"] if qr.get("received_at")]
        response_times = []
        for qr in vendor["quote_requests"]:
            if qr.get("sent_at") and qr.get("received_at"):
                from datetime import datetime
                try:
                    sent = datetime.fromisoformat(qr["sent_at"].replace("Z", "+00:00"))
                    recv = datetime.fromisoformat(qr["received_at"].replace("Z", "+00:00"))
                    days = (recv - sent).total_seconds() / 86400
                    response_times.append(round(days, 1))
                except:
                    pass

        vendor["stats"] = {
            "total_requests": total_requests,
            "sent_count": len(sent_requests),
            "received_count": len(received_requests),
            "response_rate": round(len(received_requests) / len(sent_requests) * 100) if sent_requests else None,
            "avg_response_days": round(sum(response_times) / len(response_times), 1) if response_times else None,
            "total_products_quoted": len(vendor["prices"]),
            "product_categories": len(vendor["categories"]),
        }

        return vendor
    finally:
        conn.close()


def update_vendor(vendor_id: int, data: dict) -> bool:
    """Update vendor contact info."""
    conn = _get_conn()
    try:
        fields = []
        values = []
        for key in ("name", "contact_name", "contact_title", "contact_email", "contact_phone", "notes"):
            if key in data:
                fields.append(f"{key}=?")
                values.append(data[key])
        if not fields:
            return False
        fields.append("updated_at=?")
        values.append(datetime.now().isoformat())
        values.append(vendor_id)
        cur = conn.execute(f"UPDATE vendors SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def search_vendor_prices(vendor: str = None, product: str = None, limit: int = 50) -> list[dict]:
    """Search vendor prices by vendor name and/or product."""
    if not vendor and not product:
        return []
    conn = _get_conn()
    try:
        clauses = []
        params = []
        if vendor:
            clauses.append("vp.vendor_name LIKE ?")
            params.append(f"%{vendor}%")
        if product:
            normalized = _normalize_product(product)
            clauses.append("vp.product_normalized LIKE ?")
            params.append(f"%{normalized}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = conn.execute(f"""
            SELECT vp.*, j.project_name AS job_name
            FROM vendor_prices vp
            LEFT JOIN jobs j ON vp.job_id = j.id
            {where}
            ORDER BY vp.created_at DESC
            LIMIT ?
        """, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_price_history(item_code: str = None, product: str = None, exclude_job_id: int = None) -> dict:
    """Get historical pricing for a product. Returns {min, max, avg, latest, records}."""
    conn = _get_conn()
    try:
        clauses = []
        params = []
        if item_code:
            normalized = _normalize_product(item_code)
            clauses.append("vp.product_normalized LIKE ?")
            params.append(f"%{normalized}%")
        if product:
            normalized = _normalize_product(product)
            clauses.append("vp.product_normalized LIKE ?")
            params.append(f"%{normalized}%")
        if exclude_job_id:
            clauses.append("vp.job_id != ?")
            params.append(exclude_job_id)
        if not clauses:
            return {"min": None, "max": None, "avg": None, "latest": None, "records": []}

        where = f"WHERE {' AND '.join(clauses)}"
        rows = conn.execute(f"""
            SELECT vp.*, j.project_name AS job_name
            FROM vendor_prices vp
            LEFT JOIN jobs j ON vp.job_id = j.id
            {where}
            ORDER BY vp.created_at DESC
            LIMIT 20
        """, params).fetchall()
        records = [dict(r) for r in rows]
        if not records:
            return {"min": None, "max": None, "avg": None, "latest": None, "records": []}

        prices = [r["unit_price"] for r in records if r.get("unit_price")]
        return {
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "avg": round(sum(prices) / len(prices), 2) if prices else None,
            "latest": records[0] if records else None,
            "records": records,
        }
    finally:
        conn.close()


def import_vendor_prices_csv(text: str) -> dict:
    """Bulk import vendor prices from CSV text. Accepts partial data."""
    import csv as _csv
    reader = _csv.DictReader(io.StringIO(text))
    conn = _get_conn()
    try:
        imported = 0
        errors = []
        for i, row in enumerate(reader, 2):
            product_name = (row.get('product_name', '') or row.get('product', '') or row.get('description', '') or '').strip()
            price_str = row.get('unit_price', '') or row.get('price', '') or row.get('cost', '') or ''

            if not product_name:
                errors.append(f"Row {i}: missing product name")
                continue
            try:
                unit_price = float(str(price_str).replace('$', '').replace(',', '').strip())
            except (ValueError, TypeError):
                errors.append(f"Row {i}: invalid price '{price_str}'")
                continue

            vendor_name = (row.get('vendor_name', '') or row.get('vendor', '') or '').strip()
            vendor_id = None
            if vendor_name:
                # Inline vendor lookup/create using same connection to avoid lock
                vrow = conn.execute("SELECT id FROM vendors WHERE name=?", (vendor_name,)).fetchone()
                if vrow:
                    vendor_id = vrow["id"]
                else:
                    now = datetime.now().isoformat()
                    cur = conn.execute(
                        "INSERT INTO vendors (name, created_at, updated_at) VALUES (?, ?, ?)",
                        (vendor_name, now, now)
                    )
                    vendor_id = cur.lastrowid

            normalized = _normalize_product(product_name)
            conn.execute("""
                INSERT INTO vendor_prices (product_name, unit_price, vendor_id, vendor_name,
                    product_normalized, unit, quantity, lead_time, notes, quote_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                product_name, unit_price, vendor_id, vendor_name or '', normalized,
                (row.get('unit', '') or '').strip(),
                float(row.get('quantity', 0) or 0) if row.get('quantity') else None,
                (row.get('lead_time', '') or '').strip() or None,
                (row.get('notes', '') or '').strip() or None,
                (row.get('quote_date', '') or '').strip() or None,
            ))
            imported += 1
        conn.commit()
        return {"imported": imported, "errors": errors}
    finally:
        conn.close()


# ── Notifications ────────────────────────────────────────────────────────────

def is_file_imported(job_id: int, file_hash: str) -> bool:
    """Check if a file with this hash has already been imported for this job."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM imported_files WHERE job_id=? AND file_hash=?",
            (job_id, file_hash)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def record_imported_file(job_id: int, file_name: str, file_hash: str,
                         file_size: int = 0, source: str = "manual"):
    """Record that a file has been imported for a job."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO imported_files (job_id, file_name, file_hash, file_size, source, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, file_name, file_hash, file_size, source, datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def list_imported_files(job_id: int) -> list[dict]:
    """List all imported files for a job."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT file_name, file_hash, file_size, source, imported_at "
            "FROM imported_files WHERE job_id=? ORDER BY imported_at DESC",
            (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_notification(job_id: int, ntype: str, message: str) -> int:
    """Create a notification. Returns notification id."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO notifications (job_id, type, message, created_at) VALUES (?, ?, ?, ?)",
            (job_id, ntype, message, datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_notifications(unread_only: bool = True) -> list[dict]:
    """Get notifications, optionally only unread."""
    conn = _get_conn()
    try:
        if unread_only:
            rows = conn.execute(
                "SELECT * FROM notifications WHERE read=0 ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_notification_read(notification_id: int) -> bool:
    """Mark a notification as read."""
    conn = _get_conn()
    try:
        cur = conn.execute("UPDATE notifications SET read=1 WHERE id=?", (notification_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Activity Log ─────────────────────────────────────────────────────────────

def log_activity(job_id: int, action: str, summary: str, detail: dict = None, user: str = "System") -> int:
    """Record an activity event for a job."""
    import json as _json
    conn = _get_conn()
    try:
        detail_str = _json.dumps(detail) if detail else None
        cur = conn.execute(
            "INSERT INTO job_activity (job_id, action, summary, detail, created_at, user) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, action, summary, detail_str, datetime.now().isoformat(), user)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_activity(job_id: int, limit: int = 50) -> list[dict]:
    """Fetch activity log for a job, newest first."""
    import json as _json
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM job_activity WHERE job_id=? ORDER BY created_at DESC LIMIT ?",
            (job_id, limit)
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("detail"):
                try:
                    d["detail"] = _json.loads(d["detail"])
                except (ValueError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


# ── Job Comments ─────────────────────────────────────────────────────────────

def add_comment(job_id: int, text: str, user: str = "System") -> dict:
    """Add a comment to a job. Returns the created comment."""
    conn = _get_conn()
    try:
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO job_comments (job_id, text, created_at, user) VALUES (?, ?, ?, ?)",
            (job_id, text, now, user)
        )
        conn.commit()
        return {"id": cur.lastrowid, "job_id": job_id, "text": text, "created_at": now, "user": user}
    finally:
        conn.close()


def get_comments(job_id: int) -> list[dict]:
    """Fetch comments for a job, newest first."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM job_comments WHERE job_id=? ORDER BY created_at DESC",
            (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------- Quote Requests ---------------

def create_quote_request(job_id: int, vendor_name: str, material_ids: list,
                         request_text: str = "", vendor_id: int = None,
                         status: str = "draft", sent_at: str = None) -> dict:
    """Create a quote request record."""
    conn = _get_conn()
    try:
        now = datetime.now().isoformat()
        import json
        cur = conn.execute(
            """INSERT INTO quote_requests (job_id, vendor_id, vendor_name, status, material_ids, request_text, sent_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, vendor_id, vendor_name, status, json.dumps(material_ids), request_text, sent_at, now)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM quote_requests WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_quote_requests(job_id: int) -> list[dict]:
    """List all quote requests for a job."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM quote_requests WHERE job_id=? ORDER BY created_at DESC",
            (job_id,)
        ).fetchall()
        import json
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["material_ids"] = json.loads(d["material_ids"])
            except (json.JSONDecodeError, TypeError):
                d["material_ids"] = []
            results.append(d)
        return results
    finally:
        conn.close()


def update_quote_request(request_id: int, **fields) -> bool:
    """Update a quote request (status, sent_at, received_at, request_text)."""
    conn = _get_conn()
    try:
        allowed = {"status", "sent_at", "received_at", "request_text", "vendor_name", "vendor_id", "material_ids", "response_file", "response_notes"}
        updates = []
        values = []
        for k, v in fields.items():
            if k in allowed:
                updates.append(f"{k}=?")
                if k == "material_ids" and isinstance(v, list):
                    import json as _json
                    values.append(_json.dumps(v))
                else:
                    values.append(v)
        if not updates:
            return False
        values.append(request_id)
        cur = conn.execute(f"UPDATE quote_requests SET {', '.join(updates)} WHERE id=?", values)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_quote_request(request_id: int) -> bool:
    """Delete a quote request."""
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM quote_requests WHERE id=?", (request_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Price Book ──────────────────────────────────────────────────────────────


def import_price_book(vendor: str, items: list[dict], discount_pct: float, category: str = "") -> int:
    """Import a vendor price book. Clears existing items for this vendor first.
    items: list of {product_line, item_no, material_finish, size_mm, size_inches, list_price, net_price, length, unit}
    Returns number of items imported."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM price_book_items WHERE vendor=?", (vendor,))
        for item in items:
            conn.execute(
                """INSERT INTO price_book_items
                   (vendor, product_line, item_no, material_finish, size_mm, size_inches,
                    list_price, discount_pct, net_price, length, unit, category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (vendor, item.get("product_line", ""), item.get("item_no", ""),
                 item.get("material_finish", ""), item.get("size_mm", ""),
                 item.get("size_inches", ""), item.get("list_price", 0),
                 discount_pct, item.get("net_price", 0),
                 item.get("length", ""), item.get("unit", "length"),
                 item.get("category", category))
            )
        conn.commit()
        return len(items)
    finally:
        conn.close()


def search_price_book(query: str, vendor: str = None) -> list[dict]:
    """Search price book items by product line or item number."""
    conn = _get_conn()
    try:
        q = f"%{query}%"
        if vendor:
            rows = conn.execute(
                "SELECT * FROM price_book_items WHERE vendor=? AND (product_line LIKE ? OR item_no LIKE ?) ORDER BY product_line, list_price",
                (vendor, q, q)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM price_book_items WHERE product_line LIKE ? OR item_no LIKE ? ORDER BY vendor, product_line, list_price",
                (q, q)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def match_price_book(product_line: str, size_mm: str = None, material_finish: str = None, vendor: str = None) -> list[dict]:
    """Find price book items matching a product line and optional size/material."""
    conn = _get_conn()
    try:
        sql = "SELECT * FROM price_book_items WHERE LOWER(product_line) = LOWER(?)"
        params = [product_line]
        if size_mm:
            sql += " AND size_mm = ?"
            params.append(size_mm)
        if material_finish:
            sql += " AND LOWER(material_finish) LIKE LOWER(?)"
            params.append(f"%{material_finish}%")
        if vendor:
            sql += " AND vendor = ?"
            params.append(vendor)
        sql += " ORDER BY list_price"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_price_book_summary() -> list[dict]:
    """Get summary of all imported price books."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT vendor, COUNT(*) as item_count, discount_pct,
                      MIN(net_price) as min_price, MAX(net_price) as max_price,
                      GROUP_CONCAT(DISTINCT product_line) as product_lines
               FROM price_book_items GROUP BY vendor"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
