"""
SQLite database layer using plain sqlite3 (no ORM).
Tables: jobs, job_materials, job_sundries, job_labor, job_bundles.
"""

import sqlite3
import contextvars
import hashlib
import hmac
import os
import re
import io
import json
import math
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import stable_ids


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    s = text.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "si_bid_tool.db"))

# Optional job fields printed on the customer Estimate PDF header (JobRunner
# layout). All are free text; blank values print as empty boxes/lines.
JOB_ESTIMATE_HEADER_FIELDS: tuple[str, ...] = (
    "quote_number",
    "customer_po",
    "contract_number",
    "salesperson2",
    "customer_account",
    "customer_address",
    "customer_city",
    "customer_state",
    "customer_zip",
    "customer_phone",
    "customer_fax",
    "site_phone",
    "site_contact",
)


class _Connection(sqlite3.Connection):
    """A plain sqlite3 connection that can also carry attributes: audit.py
    queues live-update events on it until the transaction commits."""


def _get_conn() -> sqlite3.Connection:
    # Several people save at once: wait up to 15 s for another writer instead
    # of failing straight away with "database is locked".
    conn = sqlite3.connect(DB_PATH, timeout=15, factory=_Connection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA foreign_keys = ON")
    # FULL makes each commit durable even if the machine loses power mid-write.
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = _get_conn()
    try:
        # WAL lets people read while someone else is saving. The setting is
        # stored in the database file, so turning it on once is enough.
        # (It adds si_bid.db-wal / -shm files next to the database.)
        journal_mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            print(f"[db] WARNING: couldn't turn on WAL mode; journal_mode is {journal_mode}")
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
                fixture_count INTEGER DEFAULT 0,
                labor_rate_lf REAL DEFAULT 0,
                labor_catalog TEXT,
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
                source_hash TEXT,
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
                source_hash TEXT,
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
                artifact_path TEXT,
                artifact_kind TEXT DEFAULT 'source',
                imported_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_imported_files_dedup
                ON imported_files(job_id, file_hash);

            CREATE TABLE IF NOT EXISTS job_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                artifact_kind TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(job_id, artifact_kind, artifact_path),
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_job_artifacts_job ON job_artifacts(job_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS material_price_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                material_id INTEGER,
                item_code TEXT DEFAULT '',
                decision TEXT NOT NULL,
                accepted_price_before REAL NOT NULL,
                resolved_price REAL NOT NULL,
                material_unit TEXT DEFAULT '',
                quote_price REAL NOT NULL,
                quote_unit TEXT DEFAULT '',
                source_hash TEXT NOT NULL,
                source_file TEXT DEFAULT '',
                reason TEXT NOT NULL,
                reviewer_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                superseded_at TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (material_id) REFERENCES job_materials(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_material_price_decisions_job
                ON material_price_decisions(job_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_material_price_decisions_active
                ON material_price_decisions(material_id, superseded_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_material_price_decisions_one_active
                ON material_price_decisions(material_id)
                WHERE superseded_at IS NULL AND material_id IS NOT NULL;

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

            CREATE TABLE IF NOT EXISTS estimating_rules (
                rule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                priority INTEGER DEFAULT 0,
                condition_json TEXT NOT NULL DEFAULT '{}',
                action_json TEXT NOT NULL DEFAULT '{}',
                source TEXT DEFAULT '',
                description TEXT DEFAULT '',
                effective_from TEXT,
                effective_to TEXT,
                version INTEGER DEFAULT 1,
                implementation_ref TEXT DEFAULT '',
                test_ref TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_est_rules_category ON estimating_rules(category);
            CREATE INDEX IF NOT EXISTS idx_est_rules_stage ON estimating_rules(stage);
            CREATE INDEX IF NOT EXISTS idx_est_rules_status ON estimating_rules(status);

            CREATE TABLE IF NOT EXISTS estimating_rule_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                change_type TEXT NOT NULL DEFAULT 'created',
                changed_by TEXT DEFAULT '',
                change_note TEXT DEFAULT '',
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(rule_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_est_rule_versions_rule ON estimating_rule_versions(rule_id, version DESC);

            CREATE TABLE IF NOT EXISTS ruleset_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL UNIQUE,
                change_type TEXT NOT NULL DEFAULT 'changed',
                rule_id TEXT DEFAULT '',
                changed_by TEXT DEFAULT '',
                change_note TEXT DEFAULT '',
                rule_count INTEGER DEFAULT 0,
                active_count INTEGER DEFAULT 0,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ruleset_versions_version ON ruleset_versions(version DESC);

            CREATE TABLE IF NOT EXISTS calculation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'started',
                source TEXT DEFAULT 'system',
                metadata_json TEXT,
                summary_json TEXT,
                trace_count INTEGER DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS calculation_trace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                entity_key TEXT,
                output_field TEXT NOT NULL,
                formula TEXT,
                inputs_json TEXT,
                result_json TEXT,
                result_value REAL,
                rule_id TEXT,
                source TEXT,
                warnings TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES calculation_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS golden_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_job_id INTEGER NOT NULL UNIQUE,
                name TEXT NOT NULL,
                jr_quote_id TEXT DEFAULT '',
                target_totals_json TEXT NOT NULL DEFAULT '{}',
                tolerance_json TEXT NOT NULL DEFAULT '{}',
                snapshot_json TEXT NOT NULL,
                ruleset_version INTEGER,
                source_fingerprint TEXT NOT NULL DEFAULT '',
                notes TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_golden_jobs_source ON golden_jobs(source_job_id);

            CREATE TABLE IF NOT EXISTS golden_job_replays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                golden_job_id INTEGER NOT NULL,
                source_job_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                summary_json TEXT NOT NULL DEFAULT '{}',
                diff_json TEXT NOT NULL DEFAULT '{}',
                generated_proposal_json TEXT NOT NULL DEFAULT '{}',
                audit_run_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (golden_job_id) REFERENCES golden_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (source_job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (audit_run_id) REFERENCES calculation_runs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_golden_replays_job ON golden_job_replays(source_job_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_golden_replays_golden ON golden_job_replays(golden_job_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS golden_job_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                golden_job_id INTEGER NOT NULL,
                source_job_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                jr_quote_id TEXT DEFAULT '',
                target_totals_json TEXT NOT NULL DEFAULT '{}',
                tolerance_json TEXT NOT NULL DEFAULT '{}',
                snapshot_json TEXT NOT NULL,
                ruleset_version INTEGER,
                source_fingerprint TEXT NOT NULL DEFAULT '',
                engine_fingerprint TEXT NOT NULL DEFAULT '',
                artifact_manifest_json TEXT NOT NULL DEFAULT '[]',
                rules_registry_snapshot_json TEXT NOT NULL DEFAULT '{}',
                config_snapshot_json TEXT NOT NULL DEFAULT '{}',
                notes TEXT DEFAULT '',
                reviewer_name TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                superseded_at TEXT,
                UNIQUE(golden_job_id, version_number),
                FOREIGN KEY (golden_job_id) REFERENCES golden_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (source_job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_golden_versions_source ON golden_job_versions(source_job_id, version_number DESC);

            -- Sign-in: one row per person. PINs are stored only as salted hashes.
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL DEFAULT '',
                pin_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                last_seen_at TEXT
            );

            -- One row per logged-in browser. Only a hash of the cookie token is kept.
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen_at);

            -- Who added, removed or changed a login, and when. username is the
            -- admin who made the change (NULL when the server did it at startup).
            -- details is JSON and never holds a PIN.
            CREATE TABLE IF NOT EXISTS admin_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                username TEXT,
                action TEXT NOT NULL,
                target_username TEXT,
                details TEXT NOT NULL DEFAULT '{}'
            );

            -- Bid tracker history: what happened to each bid, who did it and when.
            -- details is JSON (sent to, GC, bid total at send time, note, ...).
            CREATE TABLE IF NOT EXISTS bid_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                username TEXT,
                details TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_bid_events_job ON bid_events(job_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_bid_events_type ON bid_events(event_type, job_id);
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
            ("quote_source_hash", "ALTER TABLE job_materials ADD COLUMN quote_source_hash TEXT"),
            ("quote_file_name", "ALTER TABLE job_materials ADD COLUMN quote_file_name TEXT"),
            ("activity_user", "ALTER TABLE job_activity ADD COLUMN user TEXT DEFAULT 'System'"),
            ("activity_username", "ALTER TABLE job_activity ADD COLUMN username TEXT"),
            ("comment_user", "ALTER TABLE job_comments ADD COLUMN user TEXT DEFAULT 'System'"),
            ("qr_response_file", "ALTER TABLE quote_requests ADD COLUMN response_file TEXT"),
            ("qr_response_notes", "ALTER TABLE quote_requests ADD COLUMN response_notes TEXT"),
            ("gpm_pct", "ALTER TABLE jobs ADD COLUMN gpm_pct REAL DEFAULT 0"),
            ("freight_per_unit", "ALTER TABLE job_materials ADD COLUMN freight_per_unit REAL"),
            ("freight_source", "ALTER TABLE job_materials ADD COLUMN freight_source TEXT"),
            ("proposal_data", "ALTER TABLE jobs ADD COLUMN proposal_data TEXT"),
            ("tack_strip_lf", "ALTER TABLE job_materials ADD COLUMN tack_strip_lf REAL DEFAULT 0"),
            ("seam_tape_lf", "ALTER TABLE job_materials ADD COLUMN seam_tape_lf REAL DEFAULT 0"),
            ("pad_sy", "ALTER TABLE job_materials ADD COLUMN pad_sy REAL DEFAULT 0"),
            ("area_type", "ALTER TABLE job_materials ADD COLUMN area_type TEXT DEFAULT 'unit'"),
            ("tub_shower_count", "ALTER TABLE jobs ADD COLUMN tub_shower_count INTEGER DEFAULT 0"),
            ("is_mosaic", "ALTER TABLE job_materials ADD COLUMN is_mosaic BOOLEAN DEFAULT 0"),
            ("is_penny_hex", "ALTER TABLE job_materials ADD COLUMN is_penny_hex BOOLEAN DEFAULT 0"),
            ("crack_isolation_sf", "ALTER TABLE job_materials ADD COLUMN crack_isolation_sf REAL DEFAULT 0"),
            ("sundry_freight", "ALTER TABLE job_sundries ADD COLUMN freight_cost REAL DEFAULT 0"),
            ("weld_rod_lf", "ALTER TABLE job_materials ADD COLUMN weld_rod_lf REAL DEFAULT 0"),
            ("textura_fee", "ALTER TABLE jobs ADD COLUMN textura_fee INTEGER DEFAULT 0"),
            ("rule_implementation_ref", "ALTER TABLE estimating_rules ADD COLUMN implementation_ref TEXT DEFAULT ''"),
            ("rule_test_ref", "ALTER TABLE estimating_rules ADD COLUMN test_ref TEXT DEFAULT ''"),
            ("artifact_path", "ALTER TABLE imported_files ADD COLUMN artifact_path TEXT"),
            ("artifact_kind", "ALTER TABLE imported_files ADD COLUMN artifact_kind TEXT DEFAULT 'source'"),
            ("current_version_id", "ALTER TABLE golden_jobs ADD COLUMN current_version_id INTEGER"),
            ("golden_version_id", "ALTER TABLE golden_job_replays ADD COLUMN golden_version_id INTEGER"),
            ("job_quote_source_hash", "ALTER TABLE job_quotes ADD COLUMN source_hash TEXT"),
            ("vendor_price_source_hash", "ALTER TABLE vendor_prices ADD COLUMN source_hash TEXT"),
            # Bid tracker. bid_status stays NULL on old jobs; the tracker shows
            # a default ("Estimating" once materials exist) without rewriting rows.
            ("bid_status", "ALTER TABLE jobs ADD COLUMN bid_status TEXT"),
            ("bid_due_date", "ALTER TABLE jobs ADD COLUMN bid_due_date TEXT"),
            ("bid_due_time", "ALTER TABLE jobs ADD COLUMN bid_due_time TEXT"),
            ("estimator", "ALTER TABLE jobs ADD COLUMN estimator TEXT"),
            ("next_follow_up_date", "ALTER TABLE jobs ADD COLUMN next_follow_up_date TEXT"),
            ("won_lost_at", "ALTER TABLE jobs ADD COLUMN won_lost_at TEXT"),
            ("won_lost_reason", "ALTER TABLE jobs ADD COLUMN won_lost_reason TEXT"),
            ("awarded_amount", "ALTER TABLE jobs ADD COLUMN awarded_amount REAL"),
            # Admins can add and remove people. Everyone already signed up stays a regular user.
            ("user_is_admin", "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"),
            # Every saved change to a bid bumps version (job_writes.job_write);
            # proposal_rev guards proposal saves against overwriting each other.
            ("job_version", "ALTER TABLE jobs ADD COLUMN version INTEGER NOT NULL DEFAULT 0"),
            ("job_updated_at", "ALTER TABLE jobs ADD COLUMN updated_at TEXT"),
            ("job_updated_by", "ALTER TABLE jobs ADD COLUMN updated_by TEXT"),
            ("job_proposal_rev", "ALTER TABLE jobs ADD COLUMN proposal_rev INTEGER NOT NULL DEFAULT 0"),
            *[
                (f"job_{column}", f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
                for column in JOB_ESTIMATE_HEADER_FIELDS
            ],
            # Deleting a bid only hides it (soft delete); an admin can restore it.
            ("job_deleted_at", "ALTER TABLE jobs ADD COLUMN deleted_at TEXT"),
            ("job_deleted_by", "ALTER TABLE jobs ADD COLUMN deleted_by TEXT"),
            ("job_delete_reason", "ALTER TABLE jobs ADD COLUMN delete_reason TEXT"),
            # Every printed PDF is kept (insert-only receipts): who made it,
            # in which request, from which proposal version, for what total.
            ("artifact_created_by", "ALTER TABLE job_artifacts ADD COLUMN created_by TEXT"),
            ("artifact_request_id", "ALTER TABLE job_artifacts ADD COLUMN request_id TEXT"),
            ("artifact_proposal_version_id", "ALTER TABLE job_artifacts ADD COLUMN proposal_version_id INTEGER"),
            ("artifact_grand_total", "ALTER TABLE job_artifacts ADD COLUMN grand_total REAL"),
            # Stable row ids (stable_ids.py): a material line keeps its uid for
            # life; sundry and labor lines are matched by line_key, so saves
            # update rows in place. row_version / updated_at / updated_by say
            # when and by whom each row last changed.
            ("material_uid", "ALTER TABLE job_materials ADD COLUMN uid TEXT"),
            *[
                (f"{table}_{column}", f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
                for table in ("job_materials", "job_sundries", "job_labor")
                for column, kind in (
                    ("row_version", "INTEGER NOT NULL DEFAULT 0"),
                    ("updated_at", "TEXT"),
                    ("updated_by", "TEXT"),
                )
            ],
            ("sundry_line_key", "ALTER TABLE job_sundries ADD COLUMN line_key TEXT"),
            ("labor_line_key", "ALTER TABLE job_labor ADD COLUMN line_key TEXT"),
        ]:
            try:
                conn.execute(sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Exact duplicates from an interrupted pre-index import carry the same
        # source hash and product identity. Keep the oldest evidence row so the
        # uniqueness indexes can be established without touching legacy rows
        # that predate source hashing.
        conn.execute(
            """
            DELETE FROM job_quotes
            WHERE source_hash IS NOT NULL AND source_hash != ''
              AND id NOT IN (
                  SELECT MIN(id) FROM job_quotes
                  WHERE source_hash IS NOT NULL AND source_hash != ''
                  GROUP BY job_id, source_hash, COALESCE(product_name, ''),
                           COALESCE(vendor, ''), COALESCE(unit_price, 0), COALESCE(unit, '')
              )
            """
        )
        conn.execute(
            """
            DELETE FROM vendor_prices
            WHERE source_hash IS NOT NULL AND source_hash != ''
              AND id NOT IN (
                  SELECT MIN(id) FROM vendor_prices
                  WHERE source_hash IS NOT NULL AND source_hash != ''
                  GROUP BY job_id, source_hash, COALESCE(product_name, ''),
                           COALESCE(vendor_name, ''), COALESCE(unit_price, 0), COALESCE(unit, '')
              )
            """
        )
        conn.commit()

        # Indexes for vendor_prices
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_vendor_prices_vendor ON vendor_prices(vendor_id)",
            "CREATE INDEX IF NOT EXISTS idx_vendor_prices_product ON vendor_prices(product_normalized)",
            "CREATE INDEX IF NOT EXISTS idx_vendor_prices_job ON vendor_prices(job_id)",
            "CREATE INDEX IF NOT EXISTS idx_vendor_prices_date ON vendor_prices(quote_date)",
            "CREATE INDEX IF NOT EXISTS idx_vendors_name ON vendors(name)",
            "CREATE INDEX IF NOT EXISTS idx_job_activity_job ON job_activity(job_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_job_comments_job ON job_comments(job_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_calculation_runs_job ON calculation_runs(job_id, started_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_calculation_trace_run ON calculation_trace(run_id, entity_type, output_field)",
            "CREATE INDEX IF NOT EXISTS idx_calculation_trace_job ON calculation_trace(job_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_est_rules_category ON estimating_rules(category)",
            "CREATE INDEX IF NOT EXISTS idx_est_rules_stage ON estimating_rules(stage)",
            "CREATE INDEX IF NOT EXISTS idx_est_rules_status ON estimating_rules(status)",
            "CREATE INDEX IF NOT EXISTS idx_est_rule_versions_rule ON estimating_rule_versions(rule_id, version DESC)",
            "CREATE INDEX IF NOT EXISTS idx_ruleset_versions_version ON ruleset_versions(version DESC)",
            "CREATE INDEX IF NOT EXISTS idx_golden_replays_version_mode ON golden_job_replays(source_job_id, golden_version_id, mode, created_at DESC, id DESC)",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_job_quotes_source_product
               ON job_quotes(job_id, source_hash, COALESCE(product_name, ''), COALESCE(vendor, ''), COALESCE(unit_price, 0), COALESCE(unit, ''))
               WHERE source_hash IS NOT NULL AND source_hash != ''""",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_prices_source_product
               ON vendor_prices(job_id, source_hash, COALESCE(product_name, ''), COALESCE(vendor_name, ''), COALESCE(unit_price, 0), COALESCE(unit, ''))
               WHERE source_hash IS NOT NULL AND source_hash != ''""",
            "CREATE INDEX IF NOT EXISTS idx_jobs_deleted_at ON jobs(deleted_at)",
            # PDF and file receipts are history: never rewritten once saved.
            """CREATE TRIGGER IF NOT EXISTS job_artifacts_insert_only
               BEFORE UPDATE ON job_artifacts
               BEGIN SELECT RAISE(ABORT, 'job_artifacts rows are insert-only'); END""",
        ]:
            try:
                conn.execute(idx_sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass

        _ensure_rule_history_baseline(conn)
        _ensure_ruleset_history_baseline(conn)
        _ensure_stable_row_ids(conn)

        # Backfill slugs for any jobs missing them
        rows = conn.execute("SELECT id, project_name FROM jobs WHERE slug IS NULL OR slug = ''").fetchall()
        for row in rows:
            slug = _make_unique_slug(conn, _slugify(row[1]), exclude_id=row[0])
            conn.execute("UPDATE jobs SET slug=? WHERE id=?", (slug, row[0]))
        if rows:
            conn.commit()

        # Audit trail: tables and triggers, the one-time copy of the older
        # history tables, and closing edit groups left open by the last run.
        import audit
        audit.init_audit(conn)

        # Proposal versions: the table, and an "original" version of every
        # proposal saved before versions existed (once per bid).
        import proposal_versions
        proposal_versions.init_versions(conn)
    finally:
        conn.close()


# Sundry and labor tables, with the field that names a line.
_LINE_TABLES = (("job_sundries", "sundry_name"), ("job_labor", "labor_description"))


def _material_uids(conn, job_id: int) -> dict[int, str]:
    """{material id: uid} for one bid's material lines."""
    return {
        int(row["id"]): row["uid"]
        for row in conn.execute("SELECT id, uid FROM job_materials WHERE job_id=?", (job_id,)).fetchall()
        if row["uid"]
    }


def _ensure_stable_row_ids(conn) -> None:
    """Fill in missing material uids, sundry/labor line keys and proposal
    bundle uids (databases from before stable ids), then add the uniqueness
    indexes and the triggers that keep them filled in. Runs on every start;
    once everything has an id it changes nothing."""
    conn.execute("UPDATE job_materials SET uid = 'm' || id WHERE uid IS NULL OR TRIM(uid) = ''")
    for table, name_field in _LINE_TABLES:
        job_ids = [
            row[0] for row in conn.execute(
                f"SELECT DISTINCT job_id FROM {table} WHERE line_key IS NULL OR TRIM(line_key) = ''"
            ).fetchall()
        ]
        for job_id in job_ids:
            rows = [
                dict(row) for row in conn.execute(
                    f"SELECT id, material_id, {name_field}, line_key FROM {table} WHERE job_id=? ORDER BY id",
                    (job_id,),
                ).fetchall()
            ]
            taken = {row["line_key"] for row in rows if str(row["line_key"] or "").strip()}
            missing = [row for row in rows if not str(row["line_key"] or "").strip()]
            keys = stable_ids.assign_line_keys(missing, name_field, _material_uids(conn, job_id), taken)
            for row, key in zip(missing, keys):
                conn.execute(f"UPDATE {table} SET line_key=? WHERE id=?", (key, row["id"]))
    conn.commit()

    statements = [
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_materials_uid ON job_materials(job_id, uid)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_sundries_line_key ON job_sundries(job_id, line_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_labor_line_key ON job_labor(job_id, line_key)",
        # A line added some other way still gets an identity.
        """CREATE TRIGGER IF NOT EXISTS job_materials_fill_uid AFTER INSERT ON job_materials
           WHEN NEW.uid IS NULL OR TRIM(NEW.uid) = ''
           BEGIN UPDATE job_materials SET uid = 'm' || NEW.id WHERE id = NEW.id; END""",
    ]
    for table, _name_field in _LINE_TABLES:
        statements.append(
            f"""CREATE TRIGGER IF NOT EXISTS {table}_fill_line_key AFTER INSERT ON {table}
                WHEN NEW.line_key IS NULL OR TRIM(NEW.line_key) = ''
                BEGIN UPDATE {table} SET line_key = 'row' || NEW.id WHERE id = NEW.id; END"""
        )
    for table in ("job_materials", "job_sundries", "job_labor"):
        # A row changed some other way (a direct UPDATE) still gets a new
        # row_version; who changed it isn't known there, so updated_by is cleared.
        statements.append(
            f"""CREATE TRIGGER IF NOT EXISTS {table}_bump_row_version AFTER UPDATE ON {table}
                WHEN NEW.row_version IS OLD.row_version
                BEGIN
                    UPDATE {table} SET
                        row_version = COALESCE(OLD.row_version, 0) + 1,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                        updated_by = CASE WHEN NEW.updated_by IS OLD.updated_by THEN NULL ELSE NEW.updated_by END
                    WHERE id = NEW.id;
                END"""
        )
    for sql in statements:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.DatabaseError as err:
            print(f"[db] WARNING: couldn't set up stable row ids: {err}")

    # Proposal bundles saved before uids get a deterministic uid. The JSON is
    # read in Python, not with SQLite's json functions: SQLite may run those
    # on a row whose proposal_data isn't valid JSON and stop the whole start.
    try:
        rows = conn.execute(
            "SELECT id, proposal_data FROM jobs WHERE proposal_data LIKE '%bundles%'"
        ).fetchall()
        changed = False
        for row in rows:
            try:
                proposal = json.loads(row["proposal_data"])
            except (TypeError, ValueError):
                continue
            bundles = proposal.get("bundles") if isinstance(proposal, dict) else None
            if not isinstance(bundles, list) or not any(
                isinstance(bundle, dict) and not isinstance(bundle.get("uid"), str)
                for bundle in bundles
            ):
                continue
            if stable_ids.backfill_proposal_bundle_uids(row["id"], proposal):
                conn.execute("UPDATE jobs SET proposal_data=? WHERE id=?", (json.dumps(proposal), row["id"]))
                changed = True
        if changed:
            conn.commit()
    except (sqlite3.DatabaseError, TypeError, ValueError) as err:
        conn.rollback()
        print(f"[db] WARNING: couldn't give older proposal bundles their ids: {err}")


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
        # Ensure bid_data and proposal_data are stored as JSON string, not dict
        bid_data_val = job_data.get("bid_data")
        if isinstance(bid_data_val, dict):
            bid_data_val = _json.dumps(bid_data_val)
        proposal_data_val = job_data.get("proposal_data")
        if isinstance(proposal_data_val, dict):
            proposal_data_val = _json.dumps(proposal_data_val)
        if job_id:
            slug = _make_unique_slug(conn, slug, exclude_id=job_id)
            conn.execute("""
                UPDATE jobs SET
                    project_name=?, gc_name=?, address=?, city=?, state=?, zip=?,
                    tax_rate=?, gpm_pct=?, unit_count=?, tub_shower_count=?,
                    salesperson=?, notes=?, slug=?, exclusions=?,
                    markup_pct=?, bid_data=?, architect=?, designer=?, proposal_data=?,
                    textura_fee=?
                WHERE id=?
            """, (
                job_data["project_name"], job_data.get("gc_name"),
                job_data.get("address"), job_data.get("city"),
                job_data.get("state"), job_data.get("zip"),
                job_data.get("tax_rate", 0), job_data.get("gpm_pct", 0),
                job_data.get("unit_count", 0), job_data.get("tub_shower_count", 0),
                job_data.get("salesperson"), job_data.get("notes"), slug,
                job_data.get("exclusions"), job_data.get("markup_pct", 0),
                bid_data_val, job_data.get("architect"), job_data.get("designer"),
                proposal_data_val, job_data.get("textura_fee", 0), job_id
            ))
            # Estimate header fields are optional and only written when the
            # caller sends them, so partial job dicts never blank them out.
            header_updates = [
                (column, job_data.get(column))
                for column in JOB_ESTIMATE_HEADER_FIELDS
                if column in job_data
            ]
            if header_updates:
                conn.execute(
                    f"UPDATE jobs SET {', '.join(f'{column}=?' for column, _ in header_updates)} WHERE id=?",
                    [value for _, value in header_updates] + [job_id],
                )
        else:
            slug = _make_unique_slug(conn, slug)
            cur = conn.execute("""
                INSERT INTO jobs (project_name, gc_name, address, city, state, zip,
                                  tax_rate, gpm_pct, unit_count, tub_shower_count,
                                  salesperson, notes, slug, exclusions,
                                  markup_pct, bid_data, architect, designer, proposal_data,
                                  textura_fee, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_data["project_name"], job_data.get("gc_name"),
                job_data.get("address"), job_data.get("city"),
                job_data.get("state"), job_data.get("zip"),
                job_data.get("tax_rate", 0), job_data.get("gpm_pct", 0),
                job_data.get("unit_count", 0), job_data.get("tub_shower_count", 0),
                job_data.get("salesperson"), job_data.get("notes"), slug,
                job_data.get("exclusions"), job_data.get("markup_pct", 0),
                bid_data_val, job_data.get("architect"), job_data.get("designer"),
                proposal_data_val, job_data.get("textura_fee", 0),
                datetime.now().isoformat()
            ))
            job_id = cur.lastrowid
            header_values = [
                (column, job_data.get(column))
                for column in JOB_ESTIMATE_HEADER_FIELDS
                if job_data.get(column) is not None
            ]
            if header_values:
                conn.execute(
                    f"UPDATE jobs SET {', '.join(f'{column}=?' for column, _ in header_values)} WHERE id=?",
                    [value for _, value in header_values] + [job_id],
                )
        conn.commit()
        return job_id
    finally:
        conn.close()


# Stored fields of a material line, in the order save_materials writes them
# (everything but id, job_id, uid and the row bookkeeping columns).
MATERIAL_COLUMNS = (
    "item_code", "description", "material_type", "installed_qty", "unit", "waste_pct",
    "order_qty", "vendor", "unit_price", "extended_cost", "ai_confidence", "quote_status",
    "price_source", "quote_source_hash", "quote_file_name", "freight_per_unit",
    "freight_source", "fixture_count", "labor_rate_lf", "labor_catalog",
    "tack_strip_lf", "seam_tape_lf", "pad_sy", "area_type", "is_mosaic",
    "is_penny_hex", "crack_isolation_sf", "weld_rod_lf",
)


class SavedRows(list):
    """The saved rows' ids in the order given (a plain list, so callers can
    zip them with their rows), plus what the save changed:

    - ``uids``: each saved row's uid, in the same order;
    - ``diff``: {"added": [uid], "updated": {uid: [field, ...]}, "removed": [uid]}.
    """

    def __init__(self, ids=(), uids=(), diff=None):
        super().__init__(ids)
        self.uids = list(uids)
        self.diff = diff or {"added": [], "updated": {}, "removed": []}


def _same_stored_value(a, b) -> bool:
    """Whether writing ``b`` over the stored ``a`` would change nothing."""
    if isinstance(a, bool):
        a = int(a)
    if isinstance(b, bool):
        b = int(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-9)
    return a == b


def _row_stamp() -> tuple[str, str]:
    """(updated_at, updated_by) for rows changed now by whoever is saving."""
    import audit
    return audit.iso_ms(audit.utc_now()), audit.actor_label()


def save_materials(
    job_id: int,
    materials: list[dict],
    *,
    conn: sqlite3.Connection | None = None,
) -> SavedRows:
    """Save a bid's material lines: exactly the given rows, in this order.

    A row with the id of a saved line (or, failing that, its uid) updates
    that line, which keeps its id and uid. Any other row is added, with the
    uid it brought if this bid doesn't use it yet, else a new one. Saved lines
    that aren't given are deleted. Only lines whose stored fields change are
    written; they get row_version + 1, updated_at and updated_by.

    Returns the ids in the order given (SavedRows, with .uids and .diff).
    """
    owns_connection = conn is None
    conn = conn or _get_conn()
    try:
        existing_rows = {
            int(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM job_materials WHERE job_id=?",
                (job_id,),
            ).fetchall()
        }
        existing_ids = set(existing_rows)
        id_by_uid = {row["uid"]: row_id for row_id, row in existing_rows.items() if row.get("uid")}
        taken_uids = set(id_by_uid)
        updated_at, updated_by = _row_stamp()

        def decision_identity(material: dict) -> tuple:
            try:
                unit_price = round(float(material.get("unit_price") or 0), 6)
            except (TypeError, ValueError):
                unit_price = 0.0
            price_source = str(material.get("price_source") or "").strip().lower()
            quote_hash = (
                str(material.get("quote_source_hash") or "").strip()
                if price_source in {"vendor_quote", "vendor_quote_override"}
                else ""
            )
            return (
                str(material.get("item_code") or "").strip(),
                str(material.get("unit") or "").strip().upper(),
                unit_price,
                price_source,
                quote_hash,
            )

        def material_values(material: dict) -> tuple:
            price_source = material.get("price_source")
            is_vendor_evidence = str(price_source or "").strip().lower() in {
                "vendor_quote", "vendor_quote_override",
            }
            return (
                material.get("item_code"), material.get("description"),
                material.get("material_type"), material.get("installed_qty", 0),
                material.get("unit"), material.get("waste_pct", 0),
                material.get("order_qty", 0), material.get("vendor"),
                material.get("unit_price", 0), material.get("extended_cost", 0),
                material.get("ai_confidence"), material.get("quote_status"),
                price_source,
                material.get("quote_source_hash") if is_vendor_evidence else None,
                material.get("quote_file_name") if is_vendor_evidence else None,
                material.get("freight_per_unit"),
                material.get("freight_source"), material.get("fixture_count", 0),
                material.get("labor_rate_lf", 0), material.get("labor_catalog"),
                material.get("tack_strip_lf", 0), material.get("seam_tape_lf", 0),
                material.get("pad_sy", 0), material.get("area_type", "unit"),
                1 if material.get("is_mosaic") else 0,
                1 if material.get("is_penny_hex") else 0,
                material.get("crack_isolation_sf", 0),
                material.get("weld_rod_lf", 0),
            )

        assignments = ", ".join(f"{column}=?" for column in MATERIAL_COLUMNS)
        insert_columns = ", ".join(MATERIAL_COLUMNS)
        insert_marks = ", ".join("?" for _ in MATERIAL_COLUMNS)
        ids, uids = [], []
        retained_ids = set()
        diff = {"added": [], "updated": {}, "removed": []}
        for m in materials:
            try:
                requested_id = int(m.get("id")) if m.get("id") is not None else None
            except (TypeError, ValueError):
                requested_id = None
            if requested_id not in existing_ids or requested_id in retained_ids:
                # No saved line with that id: the same line may still be
                # named by its uid (e.g. a client that only knows uids).
                requested_id = id_by_uid.get(stable_ids.clean_uid(m.get("uid")))
                if requested_id in retained_ids:
                    requested_id = None
            values = material_values(m)
            if requested_id is not None:
                existing = existing_rows[requested_id]
                if decision_identity(existing) != decision_identity(m):
                    conn.execute(
                        """UPDATE material_price_decisions
                           SET superseded_at=?
                           WHERE material_id=? AND superseded_at IS NULL""",
                        (datetime.now().isoformat(), requested_id),
                    )
                changed = [
                    column for column, value in zip(MATERIAL_COLUMNS, values)
                    if not _same_stored_value(existing.get(column), value)
                ]
                if changed:
                    conn.execute(
                        f"""UPDATE job_materials SET {assignments},
                                row_version = COALESCE(row_version, 0) + 1, updated_at=?, updated_by=?
                            WHERE id=? AND job_id=?""",
                        (*values, updated_at, updated_by, requested_id, job_id),
                    )
                    diff["updated"][existing.get("uid") or str(requested_id)] = changed
                material_id = requested_id
                uid = existing.get("uid")
            else:
                uid = stable_ids.clean_uid(m.get("uid"))
                if not uid or uid in taken_uids:
                    uid = stable_ids.new_material_uid(taken_uids)
                taken_uids.add(uid)
                cur = conn.execute(
                    f"""INSERT INTO job_materials
                            (job_id, uid, {insert_columns}, row_version, updated_at, updated_by)
                        VALUES (?, ?, {insert_marks}, 1, ?, ?)""",
                    (job_id, uid, *values, updated_at, updated_by),
                )
                material_id = int(cur.lastrowid)
                diff["added"].append(uid)
            retained_ids.add(material_id)
            ids.append(material_id)
            uids.append(uid)

        removed_ids = existing_ids - retained_ids
        diff["removed"] = [existing_rows[row_id].get("uid") or str(row_id) for row_id in sorted(removed_ids)]
        if retained_ids:
            if removed_ids:
                placeholders = ",".join("?" for _ in removed_ids)
                conn.execute(
                    f"""UPDATE material_price_decisions
                        SET superseded_at=?
                        WHERE material_id IN ({placeholders}) AND superseded_at IS NULL""",
                    (datetime.now().isoformat(), *sorted(removed_ids)),
                )
            placeholders = ",".join("?" for _ in retained_ids)
            conn.execute(
                f"DELETE FROM job_materials WHERE job_id=? AND id NOT IN ({placeholders})",
                (job_id, *sorted(retained_ids)),
            )
        else:
            conn.execute(
                """UPDATE material_price_decisions
                   SET superseded_at=?
                   WHERE job_id=? AND superseded_at IS NULL""",
                (datetime.now().isoformat(), job_id),
            )
            conn.execute("DELETE FROM job_materials WHERE job_id=?", (job_id,))
        if owns_connection:
            conn.commit()
        return SavedRows(ids, uids, diff)
    finally:
        if owns_connection:
            conn.close()


@contextmanager
def _conn_or_new(conn: sqlite3.Connection | None = None):
    """The connection to write with: the one given, else the open
    job_write/entity_write transaction on this thread (a second connection
    would wait for the write lock that transaction holds), else a new one that
    is committed and closed at the end of the block."""
    if conn is not None:
        yield conn
        return
    import audit
    active = audit.active_write()
    if active is not None:
        yield active.conn
        return
    own = _get_conn()
    try:
        yield own
        own.commit()
    finally:
        own.close()


# Stored fields of sundry and labor lines (besides job_id and line_key), with
# what a missing value is saved as.
SUNDRY_COLUMNS = ("material_id", "sundry_name", "qty", "unit", "unit_price", "extended_cost", "freight_cost")
_SUNDRY_DEFAULTS = {"qty": 0, "unit_price": 0, "extended_cost": 0, "freight_cost": 0}
LABOR_COLUMNS = ("material_id", "labor_description", "qty", "unit", "rate", "extended_cost")
_LABOR_DEFAULTS = {"qty": 0, "rate": 0, "extended_cost": 0}


def _save_keyed_lines(conn, table: str, name_field: str, columns: tuple, defaults: dict,
                      job_id: int, lines: list[dict]) -> dict:
    """Make a bid's sundry or labor lines exactly ``lines``, matched to the
    saved lines by line_key (stable_ids.assign_line_keys): a matching line is
    updated in place (only if a field changed), new lines are added and saved
    lines no longer listed are deleted.
    Returns {"added": [key], "updated": {key: [field, ...]}, "removed": [key]}."""
    lines = [line for line in lines or [] if isinstance(line, dict)]
    keys = stable_ids.assign_line_keys(lines, name_field, _material_uids(conn, job_id))
    saved: dict[str, dict] = {}
    unkeyed_ids = []
    for row in conn.execute(f"SELECT * FROM {table} WHERE job_id=? ORDER BY id", (job_id,)).fetchall():
        row = dict(row)
        if str(row.get("line_key") or "").strip():
            saved[row["line_key"]] = row
        else:
            unkeyed_ids.append(row["id"])
    updated_at, updated_by = _row_stamp()
    diff = {"added": [], "updated": {}, "removed": []}

    wanted = set(keys)
    removed = [key for key in saved if key not in wanted]
    doomed = unkeyed_ids + [saved[key]["id"] for key in removed]
    for start in range(0, len(doomed), 500):
        chunk = doomed[start:start + 500]
        conn.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?' for _ in chunk)})", chunk)
    diff["removed"] = removed

    assignments = ", ".join(f"{column}=?" for column in columns)
    for line, key in zip(lines, keys):
        values = [line.get(column, defaults.get(column)) for column in columns]
        current = saved.get(key)
        if current is None:
            conn.execute(
                f"""INSERT INTO {table} (job_id, line_key, {', '.join(columns)}, row_version, updated_at, updated_by)
                    VALUES (?, ?, {', '.join('?' for _ in columns)}, 1, ?, ?)""",
                (job_id, key, *values, updated_at, updated_by),
            )
            diff["added"].append(key)
            continue
        changed = [
            column for column, value in zip(columns, values)
            if not _same_stored_value(current.get(column), value)
        ]
        if changed:
            conn.execute(
                f"""UPDATE {table} SET {assignments},
                        row_version = COALESCE(row_version, 0) + 1, updated_at=?, updated_by=?
                    WHERE id=?""",
                (*values, updated_at, updated_by, current["id"]),
            )
            diff["updated"][key] = changed
    return diff


def save_sundries(job_id: int, sundries: list[dict], *, conn: sqlite3.Connection | None = None) -> dict:
    """Save a bid's sundry lines (keyed upsert by line_key; see _save_keyed_lines)."""
    with _conn_or_new(conn) as conn:
        return _save_keyed_lines(conn, "job_sundries", "sundry_name", SUNDRY_COLUMNS, _SUNDRY_DEFAULTS,
                                 job_id, sundries)


def save_labor(job_id: int, labor_items: list[dict], *, conn: sqlite3.Connection | None = None) -> dict:
    """Save a bid's labor lines (keyed upsert by line_key; see _save_keyed_lines)."""
    with _conn_or_new(conn) as conn:
        return _save_keyed_lines(conn, "job_labor", "labor_description", LABOR_COLUMNS, _LABOR_DEFAULTS,
                                 job_id, labor_items)


def save_bundles(job_id: int, bundles: list[dict], *, conn: sqlite3.Connection | None = None) -> None:
    """Save bundle lines for a job."""
    with _conn_or_new(conn) as conn:
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


# ── Calculation Audit Trace ─────────────────────────────────────────────────

def _json_dumps_safe(value) -> str:
    import json as _json
    try:
        return _json.dumps(value)
    except (TypeError, ValueError):
        return _json.dumps(str(value))


def create_calculation_run(
    job_id: int,
    run_type: str,
    source: str = "system",
    metadata: dict = None,
) -> int:
    """Start a calculation audit run and return its id."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO calculation_runs
                (job_id, run_type, status, source, metadata_json, started_at)
            VALUES (?, ?, 'started', ?, ?, ?)
            """,
            (
                job_id,
                run_type,
                source,
                _json_dumps_safe(metadata or {}),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def save_calculation_traces(job_id: int, run_id: int, traces: list[dict]) -> int:
    """Persist trace rows for a calculation run."""
    conn = _get_conn()
    try:
        for t in traces:
            conn.execute(
                """
                INSERT INTO calculation_trace
                    (job_id, run_id, entity_type, entity_id, entity_key,
                     output_field, formula, inputs_json, result_json,
                     result_value, rule_id, source, warnings, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    run_id,
                    t.get("entity_type"),
                    t.get("entity_id"),
                    t.get("entity_key"),
                    t.get("output_field"),
                    t.get("formula"),
                    _json_dumps_safe(t.get("inputs", {})),
                    _json_dumps_safe(t.get("result")),
                    t.get("result_value"),
                    t.get("rule_id"),
                    t.get("source"),
                    _json_dumps_safe(t.get("warnings", [])),
                    t.get("created_at") or datetime.now().isoformat(),
                ),
            )
        conn.execute(
            "UPDATE calculation_runs SET trace_count=? WHERE id=? AND job_id=?",
            (len(traces), run_id, job_id),
        )
        conn.commit()
        return len(traces)
    finally:
        conn.close()


def complete_calculation_run(
    run_id: int,
    status: str = "completed",
    summary: dict = None,
) -> None:
    """Mark a calculation audit run completed or failed."""
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE calculation_runs
            SET status=?, summary_json=?, completed_at=?
            WHERE id=?
            """,
            (
                status,
                _json_dumps_safe(summary or {}),
                datetime.now().isoformat(),
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_calculation_runs(job_id: int, limit: int = 20) -> list[dict]:
    """List calculation audit runs for a job, newest first."""
    import json as _json
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM calculation_runs
            WHERE job_id=?
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (job_id, limit),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for src, dest in (("metadata_json", "metadata"), ("summary_json", "summary")):
                raw = d.pop(src, None)
                if raw:
                    try:
                        d[dest] = _json.loads(raw)
                    except (ValueError, TypeError):
                        d[dest] = raw
                else:
                    d[dest] = {}
            results.append(d)
        return results
    finally:
        conn.close()


def get_latest_completed_calculation_run(
    job_id: int,
    run_types: set[str] | list[str] | tuple[str, ...],
) -> dict | None:
    """Return the newest completed audit run matching any requested type."""
    import json as _json

    normalized_types = sorted({str(run_type).strip() for run_type in run_types if str(run_type).strip()})
    if not normalized_types:
        return None

    placeholders = ", ".join("?" for _ in normalized_types)
    conn = _get_conn()
    try:
        row = conn.execute(
            f"""
            SELECT * FROM calculation_runs
            WHERE job_id=?
              AND status='completed'
              AND run_type IN ({placeholders})
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (job_id, *normalized_types),
        ).fetchone()
        if not row:
            return None

        result = dict(row)
        for src, dest in (("metadata_json", "metadata"), ("summary_json", "summary")):
            raw = result.pop(src, None)
            if raw:
                try:
                    result[dest] = _json.loads(raw)
                except (ValueError, TypeError):
                    result[dest] = raw
            else:
                result[dest] = {}
        return result
    finally:
        conn.close()


def get_first_calculation_run_started_at(
    job_id: int,
    run_types: set[str] | list[str] | tuple[str, ...],
) -> str | None:
    """started_at of the job's oldest completed run of any requested type."""
    normalized_types = sorted({str(run_type).strip() for run_type in run_types if str(run_type).strip()})
    if not normalized_types:
        return None

    placeholders = ", ".join("?" for _ in normalized_types)
    conn = _get_conn()
    try:
        row = conn.execute(
            f"""
            SELECT started_at FROM calculation_runs
            WHERE job_id=?
              AND status='completed'
              AND run_type IN ({placeholders})
            ORDER BY started_at ASC, id ASC
            LIMIT 1
            """,
            (job_id, *normalized_types),
        ).fetchone()
        return row["started_at"] if row else None
    finally:
        conn.close()


def get_calculation_traces(
    job_id: int,
    run_id: int = None,
    entity_type: str = None,
    entity_id: str = None,
    entity_key: str = None,
    limit: int = 1000,
) -> list[dict]:
    """Fetch persisted calculation trace rows with optional filters."""
    import json as _json
    conn = _get_conn()
    try:
        clauses = ["job_id=?"]
        params = [job_id]
        if run_id is not None:
            clauses.append("run_id=?")
            params.append(run_id)
        if entity_type:
            clauses.append("entity_type=?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id=?")
            params.append(str(entity_id))
        if entity_key:
            clauses.append("entity_key=?")
            params.append(entity_key)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM calculation_trace
            WHERE {' AND '.join(clauses)}
            ORDER BY id
            LIMIT ?
            """,
            params,
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for src, dest in (
                ("inputs_json", "inputs"),
                ("result_json", "result"),
                ("warnings", "warnings"),
            ):
                raw = d.pop(src, None)
                if raw:
                    try:
                        d[dest] = _json.loads(raw)
                    except (ValueError, TypeError):
                        d[dest] = raw
                else:
                    d[dest] = [] if dest == "warnings" else None
            results.append(d)
        return results
    finally:
        conn.close()


def save_quotes(job_id: int, quotes: list[dict], *, conn: sqlite3.Connection | None = None) -> list[int]:
    """Append parsed quote products for a job. Returns list of new quote ids."""
    with _conn_or_new(conn) as conn:
        ids = []
        for q in quotes:
            if q.get("error"):
                continue  # Skip error entries
            cur = conn.execute("""
                INSERT OR IGNORE INTO job_quotes
                    (job_id, product_name, vendor, unit_price, unit, description, file_name,
                     quoted_at, freight, lead_time, notes, source_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, q.get("product_name"), q.get("vendor"),
                q.get("unit_price", 0), q.get("unit"),
                q.get("description"), q.get("file_name"),
                datetime.now().isoformat(),
                q.get("freight"), q.get("lead_time"), q.get("notes"), q.get("_source_hash")
            ))
            if cur.rowcount:
                ids.append(cur.lastrowid)
        return ids


def update_quote(quote_id: int, data: dict, *, conn: sqlite3.Connection | None = None) -> bool:
    """Update a single quote entry and return success."""
    with _conn_or_new(conn) as conn:
        fields = []
        values = []
        for key in ("product_name", "vendor", "unit_price", "unit", "description"):
            if key in data:
                fields.append(f"{key}=?")
                values.append(data[key])
        if not fields:
            return False
        values.append(quote_id)
        cur = conn.execute(f"UPDATE job_quotes SET {', '.join(fields)} WHERE id=?", values)
        return cur.rowcount > 0


def get_quote_job_id(quote_id: int) -> int | None:
    """Get the job_id for a quote entry."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT job_id FROM job_quotes WHERE id=?", (quote_id,)).fetchone()
        return row["job_id"] if row else None
    finally:
        conn.close()


def delete_quotes(job_id: int, *, conn: sqlite3.Connection | None = None) -> None:
    """Delete all quotes for a job."""
    with _conn_or_new(conn) as conn:
        conn.execute("DELETE FROM job_quotes WHERE job_id=?", (job_id,))


MAX_DELETE_REASON_LENGTH = 500


def clean_delete_reason(reason) -> str:
    """The reason someone gives for deleting a bid: required, 1-500 characters."""
    text = " ".join(str(reason or "").split())
    if not text:
        raise ValueError("Please say why you're deleting this bid.")
    if len(text) > MAX_DELETE_REASON_LENGTH:
        raise ValueError(f"Keep the reason under {MAX_DELETE_REASON_LENGTH} characters.")
    return text


def _job_ref_where(job_ref) -> tuple[str, tuple]:
    if isinstance(job_ref, int) or (isinstance(job_ref, str) and job_ref.strip().isdigit()):
        return "id=?", (int(job_ref),)
    return "slug=?", (str(job_ref).strip(),)


def delete_job(job_ref, *, reason: str, deleted_by: str | None,
               conn: sqlite3.Connection | None = None) -> bool:
    """Hide a bid (soft delete): sets deleted_at, deleted_by and delete_reason.

    No rows are removed, so the bid's materials, proposal, PDFs and history
    all stay and an admin can bring it back with ``restore_job``. Run it in a
    job_write (pass tx.conn) so it is locked and audited. Returns False when
    there's no such bid or it was already deleted.
    """
    reason = clean_delete_reason(reason)
    where, params = _job_ref_where(job_ref)
    with _conn_or_new(conn) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET deleted_at=?, deleted_by=?, delete_reason=? WHERE {where} AND deleted_at IS NULL",
            (_utc_iso_ms(), deleted_by, reason, *params),
        )
        return cur.rowcount > 0


def restore_job(job_ref, *, conn: sqlite3.Connection | None = None) -> bool:
    """Bring back a deleted bid. Returns False when it wasn't deleted."""
    where, params = _job_ref_where(job_ref)
    with _conn_or_new(conn) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET deleted_at=NULL, deleted_by=NULL, delete_reason=NULL "
            f"WHERE {where} AND deleted_at IS NOT NULL",
            params,
        )
        return cur.rowcount > 0


def list_deleted_jobs() -> list[dict]:
    """Deleted bids, most recently deleted first, with who deleted them, why and the saved total."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT j.id, j.slug, j.project_name, j.gc_name, j.deleted_at, j.deleted_by, j.delete_reason,
                      j.proposal_data, j.bid_data, u.display_name AS deleted_by_name
               FROM jobs j LEFT JOIN users u ON u.username = j.deleted_by
               WHERE j.deleted_at IS NOT NULL
               ORDER BY j.deleted_at DESC, j.id DESC"""
        ).fetchall()
    finally:
        conn.close()
    results = []
    for row in rows:
        item = dict(row)
        item["grand_total"] = _saved_bid_total(item.pop("proposal_data", None), item.pop("bid_data", None))
        item["deleted_by_name"] = item.get("deleted_by_name") or item.get("deleted_by") or ""
        results.append(item)
    return results


def load_job(job_ref, include_deleted: bool = False) -> Optional[dict]:
    """Load a job by ID (int) or slug (str) with all related data.

    A deleted bid loads as None unless ``include_deleted`` (it then carries
    deleted_at / deleted_by / delete_reason, like every job row does).
    """
    conn = _get_conn()
    try:
        where, params = _job_ref_where(job_ref)
        row = conn.execute(f"SELECT * FROM jobs WHERE {where}", params).fetchone()
        if not row:
            return None
        if row["deleted_at"] and not include_deleted:
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

        # Parse proposal_data JSON if present
        raw_proposal = job.get("proposal_data")
        if raw_proposal:
            try:
                job["proposal_data"] = _json.loads(raw_proposal)
            except (ValueError, TypeError):
                job["proposal_data"] = None

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
        job["material_price_decisions"] = [
            dict(r) for r in
            conn.execute(
                """SELECT * FROM material_price_decisions
                   WHERE job_id=? AND superseded_at IS NULL
                   ORDER BY created_at DESC, id DESC""",
                (jid,),
            ).fetchall()
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


def save_settings(settings: dict, *, conn: sqlite3.Connection | None = None) -> None:
    """Save app settings (upsert)."""
    with _conn_or_new(conn) as conn:
        for key, value in settings.items():
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value))
            )


def search_all(query: str) -> dict:
    """Search jobs and materials by query string (deleted bids left out)."""
    conn = _get_conn()
    try:
        q = f"%{query}%"
        jobs = [
            dict(r) for r in
            conn.execute(
                """SELECT id, slug, project_name, gc_name, salesperson, city, state
                   FROM jobs
                   WHERE deleted_at IS NULL
                     AND (project_name LIKE ? OR gc_name LIKE ? OR salesperson LIKE ? OR city LIKE ?)
                   ORDER BY created_at DESC LIMIT 10""",
                (q, q, q, q)
            ).fetchall()
        ]
        mat_rows = conn.execute(
            """SELECT m.job_id, m.item_code, m.description, m.material_type,
                      j.project_name, j.slug
               FROM job_materials m
               JOIN jobs j ON m.job_id = j.id
               WHERE j.deleted_at IS NULL AND (m.description LIKE ? OR m.item_code LIKE ?)
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


# -- Estimating Rules Registry -------------------------------------------------

RULE_FIELDS = (
    "rule_id", "name", "category", "stage", "status", "priority",
    "condition_json", "action_json", "source", "description",
    "effective_from", "effective_to", "version", "implementation_ref",
    "test_ref", "notes",
)
RULE_MUTABLE_FIELDS = tuple(f for f in RULE_FIELDS if f != "rule_id")
RULE_JSON_FIELDS = ("condition_json", "action_json")
RULE_LIFECYCLE_STATUSES = {
    "draft", "approved", "implemented", "tested", "active",
    "disabled", "archived", "deprecated",
}
RULE_WIRING_FILE_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".json", ".sh")


def _encode_rule_json(value) -> str:
    if value is None or value == "":
        return "{}"
    if isinstance(value, str):
        json.loads(value)
        return value
    return json.dumps(value, sort_keys=True)


def _prepare_rule_values(data: dict, *, partial: bool = False) -> dict:
    prepared = {}
    fields = RULE_MUTABLE_FIELDS if partial else RULE_FIELDS
    for field in fields:
        if field not in data:
            continue
        value = data.get(field)
        if field in RULE_JSON_FIELDS:
            value = _encode_rule_json(value)
        prepared[field] = value

    if not partial:
        for field in ("condition_json", "action_json"):
            prepared.setdefault(field, "{}")
        prepared.setdefault("status", "active")
        prepared.setdefault("priority", 0)
        prepared.setdefault("version", 1)
        prepared.setdefault("category", "")
        prepared.setdefault("stage", "")
        prepared.setdefault("source", "")
        prepared.setdefault("description", "")
        prepared.setdefault("notes", "")
        prepared.setdefault("effective_from", None)
        prepared.setdefault("effective_to", None)
        prepared.setdefault("implementation_ref", "")
        prepared.setdefault("test_ref", "")

    return prepared


def _rule_from_row(row) -> dict:
    rule = dict(row)
    for field in RULE_JSON_FIELDS:
        raw = rule.get(field)
        try:
            rule[field] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            rule[field] = raw
    return rule


def _decode_prepared_rule(rule: dict) -> dict:
    decoded = dict(rule)
    for field in RULE_JSON_FIELDS:
        raw = decoded.get(field)
        try:
            decoded[field] = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
        except (TypeError, ValueError):
            decoded[field] = raw
    return decoded


def _rule_snapshot(rule: dict) -> str:
    snapshot = {field: rule.get(field) for field in RULE_FIELDS}
    return json.dumps(snapshot, sort_keys=True)


def _ref_mentions_existing_path(ref: str) -> bool:
    """Return true when a rule ref points at a real repo file."""
    ref = str(ref or "").strip()
    if not ref:
        return False

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for token in re.split(r"[\s,;]+", ref):
        clean = token.strip().strip("'\"()[]{}")
        if not clean:
            continue
        for prefix in ("code:", "path:", "test:", "harness:", "file:"):
            if clean.lower().startswith(prefix):
                clean = clean[len(prefix):]
        clean = clean.split("#", 1)[0].split("::", 1)[0]
        if ":" in clean:
            before_colon, after_colon = clean.split(":", 1)
            if before_colon.endswith(RULE_WIRING_FILE_EXTS) or after_colon.isdigit():
                clean = before_colon
        if not clean or ("/" not in clean and not clean.endswith(RULE_WIRING_FILE_EXTS)):
            continue
        candidate = clean if os.path.isabs(clean) else os.path.join(project_root, clean)
        if os.path.exists(candidate):
            return True
    return False


def _ref_mentions_rule_in_existing_path(ref: str, rule_id: str) -> bool:
    """Return true when a real referenced file contains this specific rule id."""
    ref = str(ref or "").strip()
    rule_id = str(rule_id or "").strip()
    if not ref or not rule_id:
        return False

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    candidates = []
    for token in re.split(r"[\s,;]+", ref):
        clean = token.strip().strip("'\"()[]{}")
        if not clean:
            continue
        for prefix in ("code:", "path:", "test:", "harness:", "file:"):
            if clean.lower().startswith(prefix):
                clean = clean[len(prefix):]
        clean = clean.split("#", 1)[0].split("::", 1)[0]
        if ":" in clean:
            before_colon, after_colon = clean.split(":", 1)
            if before_colon.endswith(RULE_WIRING_FILE_EXTS) or after_colon.isdigit():
                clean = before_colon
        if not clean or ("/" not in clean and not clean.endswith(RULE_WIRING_FILE_EXTS)):
            continue
        candidate = clean if os.path.isabs(clean) else os.path.join(project_root, clean)
        if os.path.exists(candidate):
            candidates.append(candidate)

    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        if rule_id in text:
            return True
    return False


def _validate_rule_lifecycle(data: dict, existing: dict | None = None) -> None:
    """Enforce the rule lifecycle gate before a rule can become active."""
    merged = {}
    if existing:
        merged.update(existing)
    merged.update(data or {})

    status = str(merged.get("status") or "draft").strip().lower()
    if status not in RULE_LIFECYCLE_STATUSES:
        allowed = ", ".join(sorted(RULE_LIFECYCLE_STATUSES))
        raise ValueError(f"Invalid rule status '{status}'. Use one of: {allowed}")
    merged["status"] = status
    data["status"] = status

    rule_id = str(merged.get("rule_id") or "").strip()
    custom_rule = rule_id.startswith("custom.")
    if status == "active" and custom_rule:
        implementation_ref = str(merged.get("implementation_ref") or "").strip()
        test_ref = str(merged.get("test_ref") or "").strip()
        if not implementation_ref or not test_ref:
            raise ValueError(
                "Custom rules cannot become active until implementation_ref and test_ref are filled in. "
                "Use tested/implemented until the rule is wired and verified."
            )
        if not _ref_mentions_rule_in_existing_path(implementation_ref, rule_id):
            raise ValueError(
                "Custom rules cannot become active until implementation_ref points to real runtime code "
                "that mentions this rule_id."
            )
        if not _ref_mentions_rule_in_existing_path(test_ref, rule_id):
            raise ValueError(
                "Custom rules cannot become active until test_ref points to a real test or harness artifact "
                "that mentions this rule_id."
            )


def _ruleset_snapshot(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM estimating_rules WHERE LOWER(COALESCE(status, '')) != 'archived' ORDER BY rule_id"
    ).fetchall()
    return [_rule_from_row(row) for row in rows]


def _next_ruleset_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS max_version FROM ruleset_versions").fetchone()
    return int(row["max_version"] or 0) + 1


def _insert_ruleset_version(
    conn: sqlite3.Connection,
    *,
    change_type: str,
    rule_id: str = "",
    changed_by: str = "",
    change_note: str = "",
) -> int:
    rules = _ruleset_snapshot(conn)
    if not rules:
        return 0
    version = _next_ruleset_version(conn)
    active_count = sum(1 for rule in rules if str(rule.get("status") or "").lower() == "active")
    snapshot = {
        "version": version,
        "rules": rules,
        "rule_count": len(rules),
        "active_count": active_count,
    }
    conn.execute(
        """
        INSERT INTO ruleset_versions
            (version, change_type, rule_id, changed_by, change_note,
             rule_count, active_count, snapshot_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version,
            change_type,
            rule_id or "",
            changed_by or "",
            change_note or "",
            len(rules),
            active_count,
            json.dumps(snapshot, sort_keys=True),
            datetime.now().isoformat(),
        ),
    )
    return version


def _ensure_ruleset_history_baseline(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT id FROM ruleset_versions LIMIT 1").fetchone()
    if existing:
        return
    if not conn.execute("SELECT rule_id FROM estimating_rules LIMIT 1").fetchone():
        return
    _insert_ruleset_version(
        conn,
        change_type="baseline",
        changed_by="System",
        change_note="Backfilled current rule registry as ruleset baseline.",
    )
    conn.commit()


def _insert_rule_version(
    conn: sqlite3.Connection,
    rule: dict,
    change_type: str,
    changed_by: str = "",
    change_note: str = "",
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO estimating_rule_versions
            (rule_id, version, change_type, changed_by, change_note, snapshot_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rule["rule_id"],
            int(rule.get("version") or 1),
            change_type,
            changed_by or "",
            change_note or "",
            _rule_snapshot(rule),
            datetime.now().isoformat(),
        ),
    )


def _ensure_rule_history_baseline(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT r.*
        FROM estimating_rules r
        LEFT JOIN estimating_rule_versions v
          ON v.rule_id = r.rule_id AND v.version = r.version
        WHERE v.id IS NULL
        """
    ).fetchall()
    for row in rows:
        _insert_rule_version(
            conn,
            _rule_from_row(row),
            "baseline",
            "System",
            "Backfilled current rule as version history baseline.",
        )
    if rows:
        conn.commit()


def create_rule(rule: dict, *, conn: sqlite3.Connection | None = None) -> str:
    """Create an estimating rule. Returns the rule_id."""
    data = _prepare_rule_values(rule)
    _validate_rule_lifecycle(data)
    rule_id = (data.get("rule_id") or "").strip()
    name = (data.get("name") or "").strip()
    if not rule_id:
        raise ValueError("rule_id is required")
    if not name:
        raise ValueError("name is required")

    now = datetime.now().isoformat()
    changed_by = rule.get("changed_by") or "Rules Registry"
    change_note = rule.get("change_note") or "Rule created."
    with _conn_or_new(conn) as conn:
        conn.execute("""
            INSERT INTO estimating_rules (
                rule_id, name, category, stage, status, priority,
                condition_json, action_json, source, description,
                effective_from, effective_to, version, implementation_ref,
                test_ref, notes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rule_id, name, data.get("category"), data.get("stage"), data.get("status"),
            data.get("priority"), data.get("condition_json"), data.get("action_json"),
            data.get("source"), data.get("description"), data.get("effective_from"),
            data.get("effective_to"), data.get("version"), data.get("implementation_ref"),
            data.get("test_ref"), data.get("notes"), now, now,
        ))
        row = conn.execute("SELECT * FROM estimating_rules WHERE rule_id=?", (rule_id,)).fetchone()
        _insert_rule_version(conn, _rule_from_row(row), "created", changed_by, change_note)
        _insert_ruleset_version(
            conn,
            change_type="rule_created",
            rule_id=rule_id,
            changed_by=changed_by,
            change_note=change_note,
        )
        return rule_id


def list_rules(category: str = None, stage: str = None, status: str = None) -> list[dict]:
    """List estimating rules, optionally filtered by category, stage, and status."""
    where = []
    params = []
    if category:
        where.append("category=?")
        params.append(category)
    if stage:
        where.append("stage=?")
        params.append(stage)
    if status:
        where.append("status=?")
        params.append(status)
    sql = "SELECT * FROM estimating_rules"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY priority DESC, category, stage, rule_id"

    conn = _get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_rule_from_row(r) for r in rows]
    finally:
        conn.close()


def get_rule(rule_id: str) -> dict | None:
    """Fetch a single estimating rule by rule_id."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM estimating_rules WHERE rule_id=?", (rule_id,)).fetchone()
        return _rule_from_row(row) if row else None
    finally:
        conn.close()


def list_rule_versions(rule_id: str) -> list[dict]:
    """List saved versions for an estimating rule."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, rule_id, version, change_type, changed_by, change_note, snapshot_json, created_at
            FROM estimating_rule_versions
            WHERE rule_id=?
            ORDER BY version DESC, id DESC
            """,
            (rule_id,),
        ).fetchall()
        versions = []
        for row in rows:
            item = dict(row)
            raw = item.pop("snapshot_json", "{}")
            try:
                item["snapshot"] = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                item["snapshot"] = {}
            versions.append(item)
        return versions
    finally:
        conn.close()


def update_rule(
    rule_id: str,
    fields: dict,
    *,
    changed_by: str = "",
    change_note: str = "",
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Patch mutable fields on an estimating rule and save a new version."""
    data = _prepare_rule_values(fields, partial=True)
    if not data:
        return False

    with _conn_or_new(conn) as conn:
        existing = conn.execute("SELECT * FROM estimating_rules WHERE rule_id=?", (rule_id,)).fetchone()
        if not existing:
            return False
        _validate_rule_lifecycle(data, _rule_from_row(existing))
        current_version = int(existing["version"] or 1)
        requested_version = int(data["version"]) if "version" in data and data["version"] is not None else 0
        data["version"] = max(current_version + 1, requested_version)
        assignments = [f"{field}=?" for field in data]
        values = list(data.values())
        assignments.append("updated_at=?")
        values.append(datetime.now().isoformat())
        values.append(rule_id)
        cur = conn.execute(
            f"UPDATE estimating_rules SET {', '.join(assignments)} WHERE rule_id=?",
            values,
        )
        if cur.rowcount > 0:
            row = conn.execute("SELECT * FROM estimating_rules WHERE rule_id=?", (rule_id,)).fetchone()
            _insert_rule_version(
                conn,
                _rule_from_row(row),
                "updated",
                changed_by or "Rules Registry",
                change_note or "Rule updated.",
            )
            _insert_ruleset_version(
                conn,
                change_type="rule_updated",
                rule_id=rule_id,
                changed_by=changed_by or "Rules Registry",
                change_note=change_note or "Rule updated.",
            )
        return cur.rowcount > 0


def archive_rule(
    rule_id: str,
    *,
    changed_by: str = "",
    change_note: str = "",
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Archive an estimating rule while preserving history for old bids."""
    with _conn_or_new(conn) as conn:
        existing = conn.execute("SELECT * FROM estimating_rules WHERE rule_id=?", (rule_id,)).fetchone()
        if not existing:
            return False
        now = datetime.now().isoformat()
        next_version = int(existing["version"] or 1) + 1
        cur = conn.execute(
            """
            UPDATE estimating_rules
            SET status='archived', effective_to=?, version=?, updated_at=?
            WHERE rule_id=?
            """,
            (now, next_version, now, rule_id),
        )
        if cur.rowcount > 0:
            row = conn.execute("SELECT * FROM estimating_rules WHERE rule_id=?", (rule_id,)).fetchone()
            _insert_rule_version(
                conn,
                _rule_from_row(row),
                "archived",
                changed_by or "Rules Registry",
                change_note or "Rule archived.",
            )
            _insert_ruleset_version(
                conn,
                change_type="rule_archived",
                rule_id=rule_id,
                changed_by=changed_by or "Rules Registry",
                change_note=change_note or "Rule archived.",
            )
        return cur.rowcount > 0


def delete_rule(rule_id: str, *, changed_by: str = "", conn: sqlite3.Connection | None = None) -> bool:
    """Archive an estimating rule instead of hard deleting it."""
    return archive_rule(rule_id, changed_by=changed_by, conn=conn)


def get_active_rules(stage: str = None, category: str = None, as_of: str = None) -> list[dict]:
    """Return active rules effective for a stage/category at the given ISO timestamp."""
    as_of = as_of or datetime.now().isoformat()
    where = [
        "status='active'",
        "(effective_from IS NULL OR effective_from='' OR effective_from<=?)",
        "(effective_to IS NULL OR effective_to='' OR effective_to>=?)",
    ]
    params = [as_of, as_of]
    if stage:
        where.append("stage=?")
        params.append(stage)
    if category:
        where.append("category=?")
        params.append(category)

    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM estimating_rules WHERE "
            + " AND ".join(where)
            + " ORDER BY priority DESC, category, stage, rule_id",
            params,
        ).fetchall()
        return [_rule_from_row(r) for r in rows]
    finally:
        conn.close()


def seed_rules_registry_defaults(
    overwrite: bool = False,
    *,
    changed_by: str = "System",
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Seed built-in hard rules without overwriting user edits by default.

    ``changed_by`` is saved on the rule and rule set versions it writes."""
    from rules_registry import BUILTIN_RULE_CORRECTIONS, DEFAULT_HARD_RULES

    inserted = 0
    updated = 0
    contract_backfilled = 0
    corrected = 0
    with _conn_or_new(conn) as conn:
        for rule in DEFAULT_HARD_RULES:
            seeded_rule = dict(rule)
            seeded_rule.setdefault("implementation_ref", seeded_rule.get("source") or "")
            seeded_rule.setdefault("test_ref", "scripts/rules_audit_harness.py")
            data = _prepare_rule_values(seeded_rule)
            _validate_rule_lifecycle(data)
            now = datetime.now().isoformat()
            existing = conn.execute(
                "SELECT rule_id, version FROM estimating_rules WHERE rule_id=?",
                (data["rule_id"],),
            ).fetchone()
            if existing and not overwrite:
                current = conn.execute(
                    "SELECT * FROM estimating_rules WHERE rule_id=?",
                    (data["rule_id"],),
                ).fetchone()
                correction = BUILTIN_RULE_CORRECTIONS.get(data["rule_id"])
                correction_applied = False
                if current and correction:
                    current_rule = _rule_from_row(current)
                    expected = correction.get("expected") or {}
                    matches_legacy_seed = (
                        int(current_rule.get("version") or 1) == int(correction.get("from_version") or 1)
                        and all(current_rule.get(field) == value for field, value in expected.items())
                    )
                    if matches_legacy_seed:
                        fields = tuple(correction.get("fields") or ())
                        assignments = [f"{field}=?" for field in fields]
                        values = [data[field] for field in fields]
                        next_version = max(
                            int(current_rule.get("version") or 1) + 1,
                            int(data.get("version") or 1),
                        )
                        conn.execute(
                            f"UPDATE estimating_rules SET {', '.join(assignments)}, version=?, updated_at=? WHERE rule_id=?",
                            (*values, next_version, now, data["rule_id"]),
                        )
                        correction_applied = True
                        corrected += 1
                        current = conn.execute(
                            "SELECT * FROM estimating_rules WHERE rule_id=?",
                            (data["rule_id"],),
                        ).fetchone()
                if current and (not str(current["implementation_ref"] or "").strip() or not str(current["test_ref"] or "").strip()):
                    conn.execute(
                        "UPDATE estimating_rules SET implementation_ref=?, test_ref=?, updated_at=? WHERE rule_id=?",
                        (data["implementation_ref"], data["test_ref"], now, data["rule_id"]),
                    )
                    contract_backfilled += 1
                if correction_applied or (
                    current and (not str(current["implementation_ref"] or "").strip() or not str(current["test_ref"] or "").strip())
                ):
                    row = conn.execute(
                        "SELECT * FROM estimating_rules WHERE rule_id=?",
                        (data["rule_id"],),
                    ).fetchone()
                    _insert_rule_version(
                        conn,
                        _rule_from_row(row),
                        "builtin_correction" if correction_applied else "contract_backfill",
                        changed_by,
                        correction.get("change_note") if correction_applied else "Added implementation and test references required by the rules contract.",
                    )
                continue
            if existing and overwrite:
                next_version = max(int(existing["version"] or 1) + 1, int(data.get("version") or 1))
                conn.execute("""
                    UPDATE estimating_rules SET
                        name=?, category=?, stage=?, status=?, priority=?,
                        condition_json=?, action_json=?, source=?, description=?,
                        effective_from=?, effective_to=?, version=?, implementation_ref=?,
                        test_ref=?, notes=?, updated_at=?
                    WHERE rule_id=?
                """, (
                    data["name"], data["category"], data["stage"], data["status"],
                    data["priority"], data["condition_json"], data["action_json"],
                    data["source"], data["description"], data["effective_from"],
                    data["effective_to"], next_version, data["implementation_ref"],
                    data["test_ref"], data["notes"], now,
                    data["rule_id"],
                ))
                row = conn.execute(
                    "SELECT * FROM estimating_rules WHERE rule_id=?",
                    (data["rule_id"],),
                ).fetchone()
                _insert_rule_version(
                    conn,
                    _rule_from_row(row),
                    "seed_overwrite",
                    changed_by,
                    "Built-in seed overwrote this rule.",
                )
                updated += 1
            else:
                conn.execute("""
                    INSERT INTO estimating_rules (
                        rule_id, name, category, stage, status, priority,
                        condition_json, action_json, source, description,
                        effective_from, effective_to, version, implementation_ref,
                        test_ref, notes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data["rule_id"], data["name"], data["category"], data["stage"],
                    data["status"], data["priority"], data["condition_json"],
                    data["action_json"], data["source"], data["description"],
                    data["effective_from"], data["effective_to"], data["version"],
                    data["implementation_ref"], data["test_ref"], data["notes"], now, now,
                ))
                row = conn.execute(
                    "SELECT * FROM estimating_rules WHERE rule_id=?",
                    (data["rule_id"],),
                ).fetchone()
                _insert_rule_version(
                    conn,
                    _rule_from_row(row),
                    "seeded",
                    changed_by,
                    "Built-in hard rule seeded.",
                )
                inserted += 1
        if inserted or updated or contract_backfilled or corrected:
            if corrected:
                change_type = "builtin_correction"
                change_note = "Corrected built-in rule metadata that did not match runtime behavior."
            elif updated:
                change_type = "seed_overwrite"
                change_note = "Built-in hard rules overwritten."
            elif contract_backfilled:
                change_type = "contract_backfill"
                change_note = "Backfilled implementation and test references for built-in rules."
            else:
                change_type = "seeded"
                change_note = "Built-in hard rules seeded."
            _insert_ruleset_version(
                conn,
                change_type=change_type,
                changed_by=changed_by,
                change_note=change_note,
            )
        return {
            "inserted": inserted,
            "updated": updated,
            "contract_backfilled": contract_backfilled,
            "corrected": corrected,
            "total": len(DEFAULT_HARD_RULES),
        }


def list_ruleset_versions(limit: int = 25) -> list[dict]:
    """List whole-registry snapshots, newest first."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, version, change_type, rule_id, changed_by, change_note,
                   rule_count, active_count, created_at
            FROM ruleset_versions
            ORDER BY version DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_ruleset_version(version: int = None) -> dict | None:
    """Fetch a whole-registry snapshot by version, or latest when omitted."""
    conn = _get_conn()
    try:
        if version is None:
            row = conn.execute(
                "SELECT * FROM ruleset_versions ORDER BY version DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM ruleset_versions WHERE version=?",
                (version,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        raw = item.pop("snapshot_json", "{}")
        try:
            item["snapshot"] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            item["snapshot"] = {}
        return item
    finally:
        conn.close()


def rollback_ruleset_version(
    version: int,
    *,
    changed_by: str = "",
    change_note: str = "",
    conn: sqlite3.Connection | None = None,
) -> int:
    """Restore the registry to a prior ruleset snapshot as a new ruleset version."""
    with _conn_or_new(conn) as conn:
        row = conn.execute(
            "SELECT snapshot_json FROM ruleset_versions WHERE version=?",
            (version,),
        ).fetchone()
        if not row:
            raise ValueError("Ruleset version not found")
        snapshot = json.loads(row["snapshot_json"] or "{}")
        target_rules = snapshot.get("rules") or []
        if not isinstance(target_rules, list):
            raise ValueError("Ruleset snapshot is invalid")

        now = datetime.now().isoformat()
        current_rows = {
            r["rule_id"]: r
            for r in conn.execute("SELECT * FROM estimating_rules").fetchall()
        }
        target_by_id = {}
        actor = changed_by or "Rules Registry"
        note = change_note or f"Rolled registry back to ruleset v{version}."

        for raw_rule in target_rules:
            if not isinstance(raw_rule, dict) or not raw_rule.get("rule_id"):
                continue
            data = _prepare_rule_values(raw_rule)
            _validate_rule_lifecycle(data)
            rule_id = data["rule_id"]
            target_by_id[rule_id] = data
            existing = current_rows.get(rule_id)
            target_version = int(data.get("version") or 1)
            existing_rule = _rule_from_row(existing) if existing else None
            decoded_data = _decode_prepared_rule(data)
            comparable = {field: decoded_data.get(field) for field in RULE_FIELDS if field != "version"}
            current_comparable = {
                field: existing_rule.get(field)
                for field in RULE_FIELDS
                if existing_rule and field != "version"
            }
            if existing and comparable == current_comparable:
                continue

            if existing:
                data["version"] = max(int(existing["version"] or 1) + 1, target_version + 1)
                assignments = [
                    "name=?", "category=?", "stage=?", "status=?", "priority=?",
                    "condition_json=?", "action_json=?", "source=?", "description=?",
                    "effective_from=?", "effective_to=?", "version=?",
                    "implementation_ref=?", "test_ref=?", "notes=?", "updated_at=?",
                ]
                conn.execute(
                    f"UPDATE estimating_rules SET {', '.join(assignments)} WHERE rule_id=?",
                    (
                        data["name"], data["category"], data["stage"], data["status"],
                        data["priority"], data["condition_json"], data["action_json"],
                        data["source"], data["description"], data["effective_from"],
                        data["effective_to"], data["version"], data["implementation_ref"],
                        data["test_ref"], data["notes"], now, rule_id,
                    ),
                )
            else:
                data["version"] = max(target_version, 1)
                conn.execute(
                    """
                    INSERT INTO estimating_rules (
                        rule_id, name, category, stage, status, priority,
                        condition_json, action_json, source, description,
                        effective_from, effective_to, version, implementation_ref,
                        test_ref, notes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rule_id, data["name"], data["category"], data["stage"],
                        data["status"], data["priority"], data["condition_json"],
                        data["action_json"], data["source"], data["description"],
                        data["effective_from"], data["effective_to"], data["version"],
                        data["implementation_ref"], data["test_ref"], data["notes"], now, now,
                    ),
                )

            updated = conn.execute(
                "SELECT * FROM estimating_rules WHERE rule_id=?",
                (rule_id,),
            ).fetchone()
            _insert_rule_version(
                conn,
                _rule_from_row(updated),
                "ruleset_rollback",
                actor,
                note,
            )

        for rule_id, existing in current_rows.items():
            if rule_id in target_by_id:
                continue
            if str(existing["status"] or "").lower() == "archived":
                continue
            next_version = int(existing["version"] or 1) + 1
            conn.execute(
                """
                UPDATE estimating_rules
                SET status='archived', effective_to=?, version=?, updated_at=?
                WHERE rule_id=?
                """,
                (now, next_version, now, rule_id),
            )
            archived = conn.execute(
                "SELECT * FROM estimating_rules WHERE rule_id=?",
                (rule_id,),
            ).fetchone()
            _insert_rule_version(
                conn,
                _rule_from_row(archived),
                "ruleset_rollback_archived",
                actor,
                note,
            )

        new_version = _insert_ruleset_version(
            conn,
            change_type="rollback",
            changed_by=actor,
            change_note=note,
        )
        return new_version


# ── Labor Catalog ────────────────────────────────────────────────────────────

def _catalog_key(row: dict, key_fields: tuple[str, ...]) -> tuple[str, ...]:
    # Case and extra spaces don't make a different entry ("SY" = "sy").
    return tuple(" ".join(str(row.get(field) or "").split()).casefold() for field in key_fields)


def upsert_keyed_rows(conn, table: str, columns: tuple[str, ...], key_fields: tuple[str, ...],
                      entries: list[dict], *, scope: dict | None = None,
                      delete_missing: bool = True) -> dict:
    """Make ``table`` (or the rows matching ``scope``, e.g. {"vendor": "Schluter"})
    hold ``entries``, matching saved rows by ``key_fields`` instead of
    clearing and re-inserting everything.

    A saved row with the same key is updated in place (only when a value
    changed) and keeps its id; when a key repeats, the first entry takes the
    first saved row, the second the second, and so on. Other entries are
    added. With ``delete_missing`` the saved rows no entry matched are deleted
    one by one, so the history lists exactly which rows went.
    Returns {"added": n, "updated": n, "removed": n, "unchanged": n}.
    """
    scope = dict(scope or {})
    where = (" WHERE " + " AND ".join(f"{column} = ?" for column in scope)) if scope else ""
    saved: dict[tuple, list[dict]] = {}
    for row in conn.execute(f"SELECT * FROM {table}{where} ORDER BY id", tuple(scope.values())).fetchall():
        row = dict(row)
        saved.setdefault(_catalog_key(row, key_fields), []).append(row)
    counts = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}
    for entry in entries:
        values = {column: entry.get(column) for column in columns}
        matches = saved.get(_catalog_key(values, key_fields))
        if matches:
            row = matches.pop(0)
            changed = [column for column in columns if not _same_stored_value(row.get(column), values[column])]
            if changed:
                conn.execute(
                    f"UPDATE {table} SET {', '.join(f'{column}=?' for column in changed)} WHERE id=?",
                    (*[values[column] for column in changed], row["id"]),
                )
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
        else:
            conn.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )
            counts["added"] += 1
    if delete_missing:
        leftover = [row["id"] for rows in saved.values() for row in rows]
        for start in range(0, len(leftover), 500):
            chunk = leftover[start:start + 500]
            conn.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?' for _ in chunk)})", chunk)
        counts["removed"] = len(leftover)
    return counts


LABOR_CATALOG_COLUMNS = ("labor_type", "description", "cost", "retail_display", "unit", "gpm_markup")
LABOR_CATALOG_KEY = ("labor_type", "description", "unit")


def save_labor_catalog_entries(entries: list[dict], *, conn: sqlite3.Connection | None = None) -> dict:
    """Make the labor catalog exactly these entries: an entry with the same
    labor type, description and unit as a saved one updates it in place, new
    ones are added and saved ones not in the list are deleted."""
    rows = [
        {
            "labor_type": e.get("labor_type", ""), "description": e.get("description", ""),
            "cost": e.get("cost", 0), "retail_display": e.get("retail_display", ""),
            "unit": e.get("unit", ""), "gpm_markup": e.get("gpm_markup", 0),
        }
        for e in entries
    ]
    with _conn_or_new(conn) as conn:
        return upsert_keyed_rows(conn, "labor_catalog", LABOR_CATALOG_COLUMNS, LABOR_CATALOG_KEY, rows)


def get_labor_catalog_entries() -> list[dict]:
    """Get all labor catalog entries from DB."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM labor_catalog ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_labor_catalog_entry(entry_id: int, data: dict, *, conn: sqlite3.Connection | None = None) -> bool:
    """Update a single labor catalog entry."""
    with _conn_or_new(conn) as conn:
        cur = conn.execute("""
            UPDATE labor_catalog SET labor_type=?, description=?, cost=?, retail_display=?, unit=?, gpm_markup=?
            WHERE id=?
        """, (
            data.get("labor_type", ""), data.get("description", ""),
            data.get("cost", 0), data.get("retail_display", ""),
            data.get("unit", ""), data.get("gpm_markup", 0),
            entry_id
        ))
        return cur.rowcount > 0


def insert_labor_catalog_entry(data: dict, *, conn: sqlite3.Connection | None = None) -> int:
    """Insert a single labor catalog entry; returns new id."""
    with _conn_or_new(conn) as conn:
        cur = conn.execute("""
            INSERT INTO labor_catalog
                (labor_type, description, cost, retail_display, unit, gpm_markup)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data.get("labor_type", ""), data.get("description", ""),
            data.get("cost", 0), data.get("retail_display", ""),
            data.get("unit", ""), data.get("gpm_markup", 0),
        ))
        return cur.lastrowid


def delete_labor_catalog_entry(entry_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
    """Delete a single labor catalog entry."""
    with _conn_or_new(conn) as conn:
        cur = conn.execute("DELETE FROM labor_catalog WHERE id=?", (entry_id,))
        return cur.rowcount > 0


def clear_labor_catalog(*, conn: sqlite3.Connection | None = None) -> None:
    """Delete all labor catalog entries."""
    with _conn_or_new(conn) as conn:
        conn.execute("DELETE FROM labor_catalog")


def clear_price_list(*, conn: sqlite3.Connection | None = None) -> None:
    """Delete all price list entries."""
    with _conn_or_new(conn) as conn:
        conn.execute("DELETE FROM price_list")


# ── Price List ───────────────────────────────────────────────────────────────

PRICE_LIST_COLUMNS = ("product_name", "material_type", "unit", "unit_price", "vendor", "notes")
PRICE_LIST_KEY = ("product_name", "vendor", "unit")


def save_price_list_entries(entries: list[dict], *, conn: sqlite3.Connection | None = None) -> dict:
    """Make the price list exactly these entries: an entry with the same
    product, vendor and unit as a saved one updates it in place, new ones are
    added and saved ones not in the list are deleted."""
    rows = [
        {
            "product_name": e.get("product_name", ""), "material_type": e.get("material_type", ""),
            "unit": e.get("unit", ""), "unit_price": e.get("unit_price", 0),
            "vendor": e.get("vendor", ""), "notes": e.get("notes", ""),
        }
        for e in entries
    ]
    with _conn_or_new(conn) as conn:
        return upsert_keyed_rows(conn, "price_list", PRICE_LIST_COLUMNS, PRICE_LIST_KEY, rows)


def add_price_list_entry(entry: dict, *, conn: sqlite3.Connection | None = None) -> int:
    """Add a single price list entry. Returns the id."""
    with _conn_or_new(conn) as conn:
        cur = conn.execute("""
            INSERT INTO price_list
                (product_name, material_type, unit, unit_price, vendor, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            entry.get("product_name", ""), entry.get("material_type", ""),
            entry.get("unit", ""), entry.get("unit_price", 0),
            entry.get("vendor", ""), entry.get("notes", "")
        ))
        return cur.lastrowid


def update_price_list_entry(entry_id: int, entry: dict, *, conn: sqlite3.Connection | None = None) -> bool:
    """Update a price list entry. Returns True if found."""
    with _conn_or_new(conn) as conn:
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
        return cur.rowcount > 0


def delete_price_list_entry(entry_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
    """Delete a price list entry. Returns True if found."""
    with _conn_or_new(conn) as conn:
        cur = conn.execute("DELETE FROM price_list WHERE id=?", (entry_id,))
        return cur.rowcount > 0


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


def save_company_rate(rate_type: str, data: str, *, conn: sqlite3.Connection | None = None) -> None:
    """Save a company rate JSON blob (upsert)."""
    with _conn_or_new(conn) as conn:
        conn.execute(
            "INSERT INTO company_rates (rate_type, data) VALUES (?, ?) "
            "ON CONFLICT(rate_type) DO UPDATE SET data=excluded.data",
            (rate_type, data)
        )


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


def _json_loads_safe(raw, default=None):
    import json as _json
    if raw in (None, ""):
        return {} if default is None else default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return _json.loads(raw)
    except (TypeError, ValueError):
        return {} if default is None else default


def _decode_golden_job_row(row) -> dict:
    d = dict(row)
    d["target_totals"] = _json_loads_safe(d.pop("target_totals_json", None), {})
    d["tolerance"] = _json_loads_safe(d.pop("tolerance_json", None), {})
    d["snapshot"] = _json_loads_safe(d.pop("snapshot_json", None), {})
    return d


def _decode_golden_replay_row(row) -> dict:
    d = dict(row)
    d["summary"] = _json_loads_safe(d.pop("summary_json", None), {})
    d["diff"] = _json_loads_safe(d.pop("diff_json", None), {})
    d["generated_proposal"] = _json_loads_safe(d.pop("generated_proposal_json", None), {})
    return d


def _decode_golden_version_row(row) -> dict:
    d = dict(row)
    for key, default in (
        ("target_totals_json", {}),
        ("tolerance_json", {}),
        ("snapshot_json", {}),
        ("artifact_manifest_json", []),
        ("rules_registry_snapshot_json", {}),
        ("config_snapshot_json", {}),
    ):
        d[key.removesuffix("_json")] = _json_loads_safe(d.pop(key, None), default)
    return d


def _attach_current_golden_version(conn, golden: dict) -> dict:
    version_id = golden.get("current_version_id")
    if not version_id:
        golden["version_id"] = None
        golden["version_number"] = 1 if golden.get("snapshot") else None
        golden["immutable"] = False
        return golden
    row = conn.execute("SELECT * FROM golden_job_versions WHERE id=?", (version_id,)).fetchone()
    if not row:
        golden["version_id"] = None
        golden["immutable"] = False
        return golden
    version = _decode_golden_version_row(row)
    golden["version_id"] = version.get("id")
    for key in (
        "version_id", "version_number", "jr_quote_id", "target_totals", "tolerance",
        "snapshot", "ruleset_version", "source_fingerprint", "engine_fingerprint",
        "artifact_manifest", "rules_registry_snapshot", "config_snapshot", "notes",
        "reviewer_name", "status", "created_at", "superseded_at",
    ):
        if key in version:
            golden[key] = version[key]
    golden["immutable"] = True
    return golden


def upsert_golden_job(
    *,
    source_job_id: int,
    name: str,
    jr_quote_id: str = "",
    target_totals: dict = None,
    tolerance: dict = None,
    snapshot: dict,
    ruleset_version: int | None = None,
    source_fingerprint: str = "",
    notes: str = "",
    reviewer_name: str = "",
    engine_fingerprint: str = "",
    artifact_manifest: list[dict] | None = None,
    rules_registry_snapshot: dict | None = None,
    config_snapshot: dict | None = None,
    status: str = "active",
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Create a new immutable golden version and update the compatibility pointer."""
    now = datetime.now().isoformat()
    with _conn_or_new(conn) as conn:
        existing = conn.execute(
            "SELECT * FROM golden_jobs WHERE source_job_id=?",
            (source_job_id,),
        ).fetchone()
        if existing:
            golden_id = existing["id"]
            previous_version = existing["current_version_id"]
            if not previous_version:
                legacy_version = conn.execute(
                    "SELECT COALESCE(MAX(version_number), 0) AS max_version FROM golden_job_versions WHERE golden_job_id=?",
                    (golden_id,),
                ).fetchone()["max_version"]
                legacy_number = int(legacy_version or 0) + 1
                conn.execute(
                    """
                    INSERT INTO golden_job_versions
                        (golden_job_id, source_job_id, version_number, jr_quote_id,
                         target_totals_json, tolerance_json, snapshot_json, ruleset_version,
                         source_fingerprint, engine_fingerprint, artifact_manifest_json,
                         rules_registry_snapshot_json, config_snapshot_json, notes,
                         reviewer_name, status, created_at, superseded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'superseded', ?, ?)
                    """,
                    (
                        golden_id, source_job_id, legacy_number,
                        existing["jr_quote_id"] or "", existing["target_totals_json"] or "{}",
                        existing["tolerance_json"] or "{}", existing["snapshot_json"] or "{}",
                        existing["ruleset_version"], existing["source_fingerprint"] or "",
                        "legacy", "[]", "{}", "{}", existing["notes"] or "", "",
                        existing["created_at"] or now, now,
                    ),
                )
                previous_version = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            else:
                conn.execute(
                    "UPDATE golden_job_versions SET status='superseded', superseded_at=? WHERE id=?",
                    (now, previous_version),
                )
        else:
            cur = conn.execute(
                """
                INSERT INTO golden_jobs
                    (source_job_id, name, jr_quote_id, target_totals_json, tolerance_json,
                     snapshot_json, ruleset_version, source_fingerprint, notes, status,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_job_id, name, jr_quote_id or "", _json_dumps_safe(target_totals or {}),
                    _json_dumps_safe(tolerance or {}), _json_dumps_safe(snapshot), ruleset_version,
                    source_fingerprint or "", notes or "", status or "active", now, now,
                ),
            )
            golden_id = cur.lastrowid
            previous_version = None

        next_number = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version FROM golden_job_versions WHERE golden_job_id=?",
            (golden_id,),
        ).fetchone()["next_version"]
        version_cur = conn.execute(
            """
            INSERT INTO golden_job_versions
                (golden_job_id, source_job_id, version_number, jr_quote_id,
                 target_totals_json, tolerance_json, snapshot_json, ruleset_version,
                 source_fingerprint, engine_fingerprint, artifact_manifest_json,
                 rules_registry_snapshot_json, config_snapshot_json, notes,
                 reviewer_name, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                golden_id, source_job_id, next_number, jr_quote_id or "",
                _json_dumps_safe(target_totals or {}), _json_dumps_safe(tolerance or {}),
                _json_dumps_safe(snapshot), ruleset_version, source_fingerprint or "",
                engine_fingerprint or "", _json_dumps_safe(artifact_manifest or []),
                _json_dumps_safe(rules_registry_snapshot or {}), _json_dumps_safe(config_snapshot or {}),
                notes or "", reviewer_name or "", status or "active", now,
            ),
        )
        version_id = version_cur.lastrowid
        conn.execute(
            """
            UPDATE golden_jobs
            SET name=?, jr_quote_id=?, target_totals_json=?, tolerance_json=?,
                snapshot_json=?, ruleset_version=?, source_fingerprint=?, notes=?,
                status=?, current_version_id=?, updated_at=?
            WHERE id=?
            """,
            (
                name, jr_quote_id or "", _json_dumps_safe(target_totals or {}),
                _json_dumps_safe(tolerance or {}), _json_dumps_safe(snapshot), ruleset_version,
                source_fingerprint or "", notes or "", status or "active", version_id, now, golden_id,
            ),
        )
        row = conn.execute("SELECT * FROM golden_jobs WHERE id=?", (golden_id,)).fetchone()
        return _attach_current_golden_version(conn, _decode_golden_job_row(row))


def get_golden_job_for_source(source_job_id: int) -> dict | None:
    """Return the golden baseline attached to a source job, if present."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM golden_jobs WHERE source_job_id=?",
            (source_job_id,),
        ).fetchone()
        return _attach_current_golden_version(conn, _decode_golden_job_row(row)) if row else None
    finally:
        conn.close()


def get_golden_job(golden_job_id: int) -> dict | None:
    """Return a golden baseline by id."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM golden_jobs WHERE id=?", (golden_job_id,)).fetchone()
        return _attach_current_golden_version(conn, _decode_golden_job_row(row)) if row else None
    finally:
        conn.close()


def save_golden_replay(
    *,
    golden_job_id: int,
    source_job_id: int,
    mode: str,
    status: str,
    summary: dict = None,
    diff: dict = None,
    generated_proposal: dict = None,
    audit_run_id: int | None = None,
    golden_version_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Persist one golden job replay report."""
    now = datetime.now().isoformat()
    with _conn_or_new(conn) as conn:
        cur = conn.execute(
            """
            INSERT INTO golden_job_replays
                (golden_job_id, source_job_id, mode, status, summary_json, diff_json,
                 generated_proposal_json, audit_run_id, golden_version_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                golden_job_id,
                source_job_id,
                mode,
                status,
                _json_dumps_safe(summary or {}),
                _json_dumps_safe(diff or {}),
                _json_dumps_safe(generated_proposal or {}),
                audit_run_id,
                golden_version_id,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM golden_job_replays WHERE id=?", (cur.lastrowid,)).fetchone()
        return _decode_golden_replay_row(row)


def list_golden_replays_for_job(source_job_id: int, limit: int = 20) -> list[dict]:
    """List recent replay reports for a source job."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM golden_job_replays
            WHERE source_job_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (source_job_id, limit),
        ).fetchall()
        return [_decode_golden_replay_row(row) for row in rows]
    finally:
        conn.close()


def list_golden_replays_for_version(
    source_job_id: int,
    golden_version_id: int,
    limit: int = 20,
) -> list[dict]:
    """List recent replay reports for one immutable baseline version."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM golden_job_replays
            WHERE source_job_id=? AND golden_version_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (source_job_id, golden_version_id, limit),
        ).fetchall()
        return [_decode_golden_replay_row(row) for row in rows]
    finally:
        conn.close()


def get_latest_golden_replay_for_version(
    source_job_id: int,
    golden_version_id: int,
    mode: str,
) -> dict | None:
    """Return the newest replay in a mode for one immutable baseline version."""
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT * FROM golden_job_replays
            WHERE source_job_id=? AND golden_version_id=? AND mode=?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (source_job_id, golden_version_id, mode),
        ).fetchone()
        return _decode_golden_replay_row(row) if row else None
    finally:
        conn.close()


def get_golden_replay(replay_id: int) -> dict | None:
    """Return one replay report."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM golden_job_replays WHERE id=?", (replay_id,)).fetchone()
        return _decode_golden_replay_row(row) if row else None
    finally:
        conn.close()


def list_jobs() -> list[dict]:
    """List all jobs that aren't deleted (summary with bundle count and bid status)."""
    from bid_tracker import effective_bid_status

    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT j.id, j.slug, j.project_name, j.gc_name, j.salesperson, j.city, j.state, j.created_at,
                      j.bid_status,
                      (SELECT COUNT(*) FROM job_bundles b WHERE b.job_id = j.id) AS bundle_count,
                      (SELECT COUNT(*) FROM job_materials m WHERE m.job_id = j.id) AS material_count,
                      (SELECT COUNT(*) FROM job_materials m WHERE m.job_id = j.id AND m.unit_price > 0) AS priced_count
               FROM jobs j WHERE j.deleted_at IS NULL ORDER BY j.created_at DESC"""
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
            # Same status the Bid Tracker shows: untracked jobs read "Estimating"
            # once they have materials, otherwise "Not started".
            d["bid_status"], d["bid_status_is_default"] = effective_bid_status(d.get("bid_status"), mc)
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


def save_vendor_prices_from_quotes(
    job_id: int,
    products: list[dict],
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Save parsed quote products to vendor_prices. Returns count saved."""
    with _conn_or_new(conn) as conn:
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
            # freight can be a string ("FOB La Grange, GA") or a number
            freight_num = freight if isinstance(freight, (int, float)) else 0
            total = unit_price + freight_num

            conn.execute("""
                INSERT OR IGNORE INTO vendor_prices
                    (product_name, unit_price, vendor_name, job_id,
                     product_normalized, unit, freight_per_unit, total_per_unit,
                     quantity, lead_time, quote_date, file_name, notes, source_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_name, unit_price, vendor_name, job_id,
                product_normalized, p.get("unit", ""), freight, total,
                p.get("quantity"), p.get("lead_time"),
                now, p.get("file_name"), p.get("notes"), p.get("_source_hash"), now
            ))
            count += int(conn.execute("SELECT changes()").fetchone()[0] or 0)

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

        return count


def create_vendor(data: dict, *, conn: sqlite3.Connection | None = None) -> dict:
    """Create a new vendor. Returns the created vendor dict."""
    with _conn_or_new(conn) as conn:
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
        vendor_id = cur.lastrowid
        row = conn.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
        return dict(row)


def delete_vendor(vendor_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
    """Delete a vendor and its associated vendor_prices."""
    with _conn_or_new(conn) as conn:
        conn.execute("DELETE FROM vendor_prices WHERE vendor_id=?", (vendor_id,))
        cur = conn.execute("DELETE FROM vendors WHERE id=?", (vendor_id,))
        return cur.rowcount > 0


def merge_vendors(keep_id: int, merge_ids: list[int], *, conn: sqlite3.Connection | None = None) -> bool:
    """Merge multiple vendor records into one. Reassigns vendor_prices and quote_requests, then deletes the duplicates."""
    with _conn_or_new(conn) as conn:
        for mid in merge_ids:
            if mid == keep_id:
                continue
            conn.execute("UPDATE vendor_prices SET vendor_id=? WHERE vendor_id=?", (keep_id, mid))
            conn.execute("UPDATE quote_requests SET vendor_id=? WHERE vendor_id=?", (keep_id, mid))
            conn.execute("UPDATE job_materials SET vendor=(SELECT name FROM vendors WHERE id=?) WHERE vendor=(SELECT name FROM vendors WHERE id=?)", (keep_id, mid))
            conn.execute("DELETE FROM vendors WHERE id=?", (mid,))
        return True


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


def update_vendor(vendor_id: int, data: dict, *, conn: sqlite3.Connection | None = None) -> bool:
    """Update vendor contact info."""
    with _conn_or_new(conn) as conn:
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
        return cur.rowcount > 0


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


def import_vendor_prices_csv(text: str, *, conn: sqlite3.Connection | None = None) -> dict:
    """Bulk import vendor prices from CSV text. Accepts partial data."""
    import csv as _csv
    reader = _csv.DictReader(io.StringIO(text))
    with _conn_or_new(conn) as conn:
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
        return {"imported": imported, "errors": errors}


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
                         file_size: int = 0, source: str = "manual",
                         artifact_path: str | None = None,
                         artifact_kind: str = "source",
                         *, conn: sqlite3.Connection | None = None):
    """Record an import and repair legacy rows when durable evidence is re-uploaded."""
    with _conn_or_new(conn) as conn:
        conn.execute(
            "INSERT INTO imported_files "
            "(job_id, file_name, file_hash, file_size, source, artifact_path, artifact_kind, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id, file_hash) DO UPDATE SET "
            "file_name=excluded.file_name, file_size=excluded.file_size, source=excluded.source, "
            "artifact_path=COALESCE(excluded.artifact_path, imported_files.artifact_path), "
            "artifact_kind=CASE WHEN excluded.artifact_path IS NOT NULL "
            "THEN excluded.artifact_kind ELSE imported_files.artifact_kind END, "
            "imported_at=excluded.imported_at",
            (job_id, file_name, file_hash, file_size, source, artifact_path, artifact_kind, datetime.now().isoformat())
        )


def list_imported_files(job_id: int) -> list[dict]:
    """List all imported files for a job."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT file_name, file_hash, file_size, source, artifact_path, artifact_kind, imported_at "
            "FROM imported_files WHERE job_id=? ORDER BY imported_at DESC",
            (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def record_job_artifact(
    job_id: int,
    artifact_kind: str,
    artifact_path: str,
    file_hash: str,
    file_size: int = 0,
    *,
    grand_total: float | None = None,
    proposal_version_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Save a receipt for a file written for a job; returns the receipt id.

    Insert-only: a receipt is never changed once saved. Printed PDFs get a new
    file name every time, so each print keeps its own receipt. Recording the
    same file again (same kind and path, e.g. one RFMS workbook uploaded
    twice) keeps and returns the first receipt. Records who made it and in
    which request. Inside a job_write, pass tx.conn (or let it find the open
    write) so the receipt and the history entry are saved together.
    """
    import audit
    context = get_audit_context()
    with _conn_or_new(conn) as conn:
        cur = conn.execute(
            """
            INSERT INTO job_artifacts (job_id, artifact_kind, artifact_path, file_hash, file_size, created_at,
                                       created_by, request_id, proposal_version_id, grand_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, artifact_kind, artifact_path) DO NOTHING
            """,
            (job_id, artifact_kind, artifact_path, file_hash, int(file_size or 0), _utc_iso_ms(),
             audit.actor_label(), context.get("request_id"), proposal_version_id,
             None if grand_total is None else round(float(grand_total), 2)),
        )
        if cur.rowcount:
            return int(cur.lastrowid)
        existing = conn.execute(
            "SELECT id, file_hash FROM job_artifacts WHERE job_id=? AND artifact_kind=? AND artifact_path=?",
            (job_id, artifact_kind, artifact_path),
        ).fetchone()
        if existing["file_hash"] != file_hash:
            print(f"[artifacts] WARNING: {artifact_path} for job {job_id} changed after its receipt was saved; "
                  "keeping the first receipt")
        return int(existing["id"])


_ARTIFACT_COLUMNS = (
    "a.id, a.job_id, a.artifact_kind, a.artifact_path, a.file_hash, a.file_size, a.created_at, "
    "a.created_by, a.request_id, a.proposal_version_id, a.grand_total, u.display_name AS created_by_name"
)


def list_job_artifacts(job_id: int, artifact_kind: str | None = None) -> list[dict]:
    """A job's file receipts (optionally one kind), newest first."""
    conn = _get_conn()
    try:
        sql = f"SELECT {_ARTIFACT_COLUMNS} FROM job_artifacts a LEFT JOIN users u ON u.username = a.created_by WHERE a.job_id=?"
        params: list = [job_id]
        if artifact_kind:
            sql += " AND a.artifact_kind=?"
            params.append(artifact_kind)
        rows = conn.execute(sql + " ORDER BY a.created_at DESC, a.id DESC", params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_job_artifact(job_id: int, artifact_id: int) -> dict | None:
    """One receipt of a job, or None."""
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT {_ARTIFACT_COLUMNS} FROM job_artifacts a LEFT JOIN users u ON u.username = a.created_by "
            "WHERE a.job_id=? AND a.id=?",
            (job_id, artifact_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def record_material_price_decision(
    job_id: int,
    material_id: int,
    *,
    item_code: str,
    decision: str,
    accepted_price_before: float,
    resolved_price: float,
    material_unit: str,
    quote_price: float,
    quote_unit: str,
    source_hash: str,
    source_file: str,
    reason: str,
    reviewer_name: str,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Append an immutable material-price decision and supersede its prior version."""
    owns_connection = conn is None
    conn = conn or _get_conn()
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE material_price_decisions
               SET superseded_at=?
               WHERE job_id=? AND material_id=? AND superseded_at IS NULL""",
            (now, job_id, material_id),
        )
        cur = conn.execute(
            """INSERT INTO material_price_decisions
               (job_id, material_id, item_code, decision, accepted_price_before,
                resolved_price, material_unit, quote_price, quote_unit, source_hash,
                source_file, reason, reviewer_name, created_at, superseded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                job_id, material_id, item_code or "", decision,
                accepted_price_before, resolved_price, material_unit or "",
                quote_price, quote_unit or "", source_hash, source_file or "",
                reason, reviewer_name, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM material_price_decisions WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
        if owns_connection:
            conn.commit()
        return dict(row)
    finally:
        if owns_connection:
            conn.close()


def list_material_price_decisions(job_id: int, *, active_only: bool = False) -> list[dict]:
    """List current or historical estimator decisions for vendor-price conflicts."""
    conn = _get_conn()
    try:
        where = "job_id=? AND superseded_at IS NULL" if active_only else "job_id=?"
        rows = conn.execute(
            f"""SELECT * FROM material_price_decisions
                WHERE {where}
                ORDER BY created_at DESC, id DESC""",
            (job_id,),
        ).fetchall()
        return [dict(row) for row in rows]
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
    """Get notifications, optionally only unread (none for deleted bids)."""
    conn = _get_conn()
    try:
        not_deleted = "NOT EXISTS (SELECT 1 FROM jobs j WHERE j.id = n.job_id AND j.deleted_at IS NOT NULL)"
        if unread_only:
            rows = conn.execute(
                f"SELECT n.* FROM notifications n WHERE n.read=0 AND {not_deleted} ORDER BY n.created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT n.* FROM notifications n WHERE {not_deleted} ORDER BY n.created_at DESC LIMIT 50"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_notification_read(notification_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
    """Mark a notification as read."""
    with _conn_or_new(conn) as conn:
        cur = conn.execute("UPDATE notifications SET read=1 WHERE id=?", (notification_id,))
        return cur.rowcount > 0


# ── Activity Log ─────────────────────────────────────────────────────────────

def log_activity(job_id: int, action: str, summary: str, detail: dict = None, user: str | None = None) -> int:
    """Record an activity event for a job.

    The logged-in person (set per request by the sign-in middleware) is saved
    in ``username``; ``user`` is the name shown in the activity list and falls
    back to their display name, or "System" for background work.

    Also writes the audit trail in the same transaction (for one release,
    while routes move to job_write): inside a job_write for the same bid the
    text becomes that entry's summary, otherwise it is an entry of its own.
    """
    import json as _json
    import audit
    current = get_current_user()
    username = current.get("username") if current else None
    if not user:
        user = _current_user_label(current)
    detail_str = _json.dumps(detail) if detail else None
    insert_sql = (
        "INSERT INTO job_activity (job_id, action, summary, detail, created_at, user, username) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    values = (job_id, action, summary, detail_str, datetime.now().isoformat(), user, username)

    active = audit.active_write()
    if active is not None:
        # Inside job_write/entity_write: use its transaction. A second
        # connection would wait for the write lock that transaction holds.
        cur = active.conn.execute(insert_sql, values)
        _audit_legacy_activity(active.conn, job_id, action, summary, detail)
        return cur.lastrowid

    conn = _get_conn()
    committed = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(insert_sql, values)
        _audit_legacy_activity(conn, job_id, action, summary, detail)
        conn.commit()
        committed = True
        audit.after_commit(conn)
        return cur.lastrowid
    except BaseException:
        if not committed:
            conn.rollback()
            audit.discard_pending(conn)
        raise
    finally:
        conn.close()


def _audit_legacy_activity(conn, job_id, action, summary, detail) -> None:
    """The audit half of log_activity. If it fails, the activity row is
    still saved and the error is logged."""
    import audit
    conn.execute("SAVEPOINT legacy_activity_audit")
    try:
        audit.record_legacy_activity(conn, job_id, action, summary, detail)
    except Exception as err:
        conn.execute("ROLLBACK TO SAVEPOINT legacy_activity_audit")
        print(f"[audit] ERROR: couldn't add '{action}' on job {job_id} to the audit log: {err}")
    finally:
        conn.execute("RELEASE SAVEPOINT legacy_activity_audit")


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

def add_comment(job_id: int, text: str, user: str | None = None, *, conn: sqlite3.Connection | None = None) -> dict:
    """Add a comment to a job. Returns the created comment."""
    if not user:
        user = _current_user_label(get_current_user())
    with _conn_or_new(conn) as conn:
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO job_comments (job_id, text, created_at, user) VALUES (?, ?, ?, ?)",
            (job_id, text, now, user)
        )
        return {"id": cur.lastrowid, "job_id": job_id, "text": text, "created_at": now, "user": user}


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
                         status: str = "draft", sent_at: str = None,
                         *, conn: sqlite3.Connection | None = None) -> dict:
    """Create a quote request record."""
    with _conn_or_new(conn) as conn:
        now = datetime.now().isoformat()
        import json
        cur = conn.execute(
            """INSERT INTO quote_requests (job_id, vendor_id, vendor_name, status, material_ids, request_text, sent_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, vendor_id, vendor_name, status, json.dumps(material_ids), request_text, sent_at, now)
        )
        row = conn.execute("SELECT * FROM quote_requests WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


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


def update_quote_request(request_id: int, *, conn: sqlite3.Connection | None = None, **fields) -> bool:
    """Update a quote request (status, sent_at, received_at, request_text)."""
    with _conn_or_new(conn) as conn:
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
        return cur.rowcount > 0


def delete_quote_request(request_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
    """Delete a quote request."""
    with _conn_or_new(conn) as conn:
        cur = conn.execute("DELETE FROM quote_requests WHERE id=?", (request_id,))
        return cur.rowcount > 0


# ── Price Book ──────────────────────────────────────────────────────────────


PRICE_BOOK_COLUMNS = (
    "vendor", "product_line", "item_no", "material_finish", "size_mm", "size_inches",
    "list_price", "discount_pct", "net_price", "length", "unit", "category",
)
# Within one vendor's book (the vendor is the scope of an import).
PRICE_BOOK_KEY = ("item_no", "material_finish", "size_mm")


def import_price_book(vendor: str, items: list[dict], discount_pct: float, category: str = "", *, conn: sqlite3.Connection | None = None) -> int:
    """Import a vendor price book: afterwards the vendor's book is exactly
    these items. An item with the same item number, finish and size as a
    saved one updates it in place, new ones are added and the vendor's saved
    items not in the book are deleted.
    items: list of {product_line, item_no, material_finish, size_mm, size_inches, list_price, net_price, length, unit}
    Returns number of items imported."""
    rows = [
        {
            "vendor": vendor, "product_line": item.get("product_line", ""), "item_no": item.get("item_no", ""),
            "material_finish": item.get("material_finish", ""), "size_mm": item.get("size_mm", ""),
            "size_inches": item.get("size_inches", ""), "list_price": item.get("list_price", 0),
            "discount_pct": discount_pct, "net_price": item.get("net_price", 0),
            "length": item.get("length", ""), "unit": item.get("unit", "length"),
            "category": item.get("category", category),
        }
        for item in items
    ]
    with _conn_or_new(conn) as conn:
        upsert_keyed_rows(conn, "price_book_items", PRICE_BOOK_COLUMNS, PRICE_BOOK_KEY, rows,
                          scope={"vendor": vendor})
        return len(items)


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


# ── Users & Sessions ─────────────────────────────────────────────────────────
# Simple username + PIN sign-in so several people can use the tool and the
# activity log shows who did what. PINs are stored as salted PBKDF2 hashes and
# session cookies are stored only as SHA-256 hashes of the random token.

PIN_HASH_ITERATIONS = 200_000
SESSION_LIFETIME_DAYS = 30          # log in again after this many days
SESSION_TOUCH_SECONDS = 60          # write "last seen" at most once a minute per session
ONLINE_WINDOW_MINUTES = 15
MIN_USERNAME_LENGTH = 2
MAX_USERNAME_LENGTH = 40
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 12
MAX_DISPLAY_NAME_LENGTH = 80
_USERNAME_RE = re.compile(r"[A-Za-z0-9._-]+")
_PIN_RE = re.compile(r"[0-9]+")

# TEMPORARY shared test account so everyone can get in while real accounts
# are set up. The login page is pre-filled with the same username and PIN.
STARTER_USERNAME = "test"
STARTER_PIN = "1234"
STARTER_DISPLAY_NAME = "Test User"

# The person making the current request. Set by the sign-in middleware in
# main.py; background threads (inbox monitor, simulator) leave it empty.
_current_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar("si_current_user", default=None)


def set_current_user(user: dict | None) -> contextvars.Token:
    return _current_user.set(user)


def reset_current_user(token: contextvars.Token) -> None:
    _current_user.reset(token)


def get_current_user() -> dict | None:
    return _current_user.get()


# Where the current request came from, for audit entries and log lines:
# request_id, source ("http" or "websocket"), session_id, client_ip and route.
# Set by the sign-in middleware in main.py next to the current user. "route"
# may be stored as a function, because the middleware runs before FastAPI has
# matched the route; get_audit_context() calls it when the context is read.
_audit_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar("si_audit_context", default=None)


def set_audit_context(context: dict | None) -> contextvars.Token:
    return _audit_context.set(context)


def reset_audit_context(token: contextvars.Token) -> None:
    _audit_context.reset(token)


def get_audit_context() -> dict:
    """The current request's context as a plain dict.

    Work outside a request (startup, background threads) gets source
    "system" and None for everything else.
    """
    context = _audit_context.get()
    if context is None:
        return {"request_id": None, "source": "system", "session_id": None, "client_ip": None, "route": None}
    result = dict(context)
    if callable(result.get("route")):
        result["route"] = result["route"]()
    return result


def set_audit_session(session_id: int | None) -> None:
    """The current request now belongs to this session (it just logged in),
    so its audit entries carry the new session id."""
    context = _audit_context.get()
    if context is not None:
        context["session_id"] = session_id


def _current_user_label(user: dict | None) -> str:
    if not user:
        return "System"
    return user.get("display_name") or user.get("username") or "System"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(value: datetime) -> str:
    # One fixed format so timestamps compare correctly as text in SQL.
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _utc_iso_ms() -> str:
    """Now, in the audit trail's format (UTC, milliseconds, Z)."""
    import audit
    return audit.iso_ms(audit.utc_now())


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_pin(pin: str, *, salt: bytes | None = None, iterations: int = PIN_HASH_ITERATIONS) -> str:
    """Return a salted PBKDF2-SHA256 hash string for a PIN."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = (pin_hash or "").split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


_unknown_user_pin_hash: str | None = None


def _spend_pin_check_time(pin: str) -> None:
    """Hash anyway when the username does not exist, so both failures take as long."""
    global _unknown_user_pin_hash
    if _unknown_user_pin_hash is None:
        _unknown_user_pin_hash = hash_pin(secrets.token_hex(8))
    verify_pin(pin, _unknown_user_pin_hash)


def _public_user(row) -> dict:
    user = dict(row)
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "is_admin": bool(user.get("is_admin")),
    }


class UserAdminError(ValueError):
    """A change to someone's login that can't be made, with a plain-English reason."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def clean_username(username) -> str:
    username = str(username or "").strip()
    if not (MIN_USERNAME_LENGTH <= len(username) <= MAX_USERNAME_LENGTH):
        raise UserAdminError(f"Username must be {MIN_USERNAME_LENGTH}-{MAX_USERNAME_LENGTH} characters.")
    if not _USERNAME_RE.fullmatch(username):
        raise UserAdminError("Username can only use letters, numbers, dots, dashes and underscores (no spaces).")
    if not any(ch.isalnum() for ch in username):
        raise UserAdminError("Username needs at least one letter or number.")
    return username


def clean_pin(pin) -> str:
    """The PIN as text. Never put the PIN itself in an error message or log."""
    pin = str(pin if pin is not None else "").strip()
    if not _PIN_RE.fullmatch(pin) or not (MIN_PIN_LENGTH <= len(pin) <= MAX_PIN_LENGTH):
        raise UserAdminError(f"PIN must be {MIN_PIN_LENGTH}-{MAX_PIN_LENGTH} digits, numbers only.")
    return pin


def clean_display_name(name) -> str:
    name = " ".join(str(name or "").split())
    if len(name) > MAX_DISPLAY_NAME_LENGTH:
        raise UserAdminError(f"Name must be {MAX_DISPLAY_NAME_LENGTH} characters or fewer.")
    return name


def _user_write_transaction():
    """One connection holding the write lock, so the "keep at least one admin"
    checks and the change they guard can't interleave with another change.
    Commits (and publishes its audit entries) on success."""
    import audit
    return audit.write_transaction()


def _log_admin_action(conn, actor: dict | None, action: str, target_username: str, details: dict | None = None) -> None:
    """Write the change to admin_log (the Users page list) and to the audit
    trail, in the caller's transaction. ``details`` never holds a PIN."""
    import audit
    conn.execute(
        "INSERT INTO admin_log (created_at, username, action, target_username, details) VALUES (?, ?, ?, ?, ?)",
        (
            _utc_iso(_utc_now()),
            (actor or {}).get("username"),
            action,
            target_username,
            json.dumps(details or {}, default=str),
        ),
    )
    row = conn.execute("SELECT display_name FROM users WHERE username = ?", (target_username,)).fetchone()
    name = (row["display_name"] if row else "") or target_username
    audit_action, summary, changes = audit.admin_log_entry(action, target_username, details, name)
    audit.record(
        conn,
        action=audit_action,
        entity_type="user",
        entity_id=target_username,
        summary=summary,
        changes=changes,
        extra=dict(details) if details else None,
    )


def create_user(
    username: str,
    pin: str,
    display_name: str = "",
    active: bool = True,
    is_admin: bool = False,
    actor: dict | None = None,
) -> dict:
    """Add a person who can log in. Returns the admin view of the new person."""
    username = clean_username(username)
    pin_hash = hash_pin(clean_pin(pin))  # slow on purpose, so do it before taking the write lock
    display_name = clean_display_name(display_name) or username
    try:
        with _user_write_transaction() as conn:
            existing = conn.execute("SELECT username, active FROM users WHERE username = ?", (username,)).fetchone()
            if existing is not None:
                if existing["active"]:
                    raise UserAdminError(f"The username \"{existing['username']}\" is already taken.", 409)
                raise UserAdminError(
                    f"The username \"{existing['username']}\" belongs to someone who was removed. "
                    "Restore them instead, or pick a different username.",
                    409,
                )
            conn.execute(
                "INSERT INTO users (username, display_name, pin_hash, active, is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username, display_name, pin_hash, 1 if active else 0, 1 if is_admin else 0, _utc_iso(_utc_now())),
            )
            _log_admin_action(conn, actor, "added", username, {"display_name": display_name, "is_admin": bool(is_admin)})
    except sqlite3.IntegrityError:
        raise UserAdminError(f"The username \"{username}\" is already taken.", 409) from None
    return get_user_for_admin(username)


def seed_default_users() -> bool:
    """Create the TEMPORARY shared test account if it does not exist yet.
    Adds an audit entry (not an admin_log row) when it does."""
    import audit
    conn = _get_conn()
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (STARTER_USERNAME,)).fetchone():
            return False
    finally:
        conn.close()
    pin_hash = hash_pin(STARTER_PIN)  # slow on purpose, so do it before taking the write lock
    with audit.write_transaction() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO users (username, display_name, pin_hash, active, created_at) VALUES (?, ?, ?, 1, ?)",
            (STARTER_USERNAME, STARTER_DISPLAY_NAME, pin_hash, _utc_iso(_utc_now())),
        )
        if not cur.rowcount:
            return False
        _, summary, changes = audit.admin_log_entry(
            "added", STARTER_USERNAME, {"display_name": STARTER_DISPLAY_NAME}, STARTER_DISPLAY_NAME,
        )
        audit.record(conn, action="user.create", entity_type="user", entity_id=STARTER_USERNAME,
                     summary=summary, changes=changes, extra={"shared_test_login": True})
    return True


def authenticate_user(username: str, pin: str) -> dict | None:
    """Return the user when the username and PIN match an active account."""
    username = (username or "").strip()
    pin = str(pin or "")
    if not username or not pin or len(username) > MAX_USERNAME_LENGTH or len(pin) > MAX_PIN_LENGTH:
        return None
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1", (username,)
        ).fetchone()
        if row is None:
            _spend_pin_check_time(pin)
            return None
        if not verify_pin(pin, row["pin_hash"]):
            return None
        now = _utc_iso(_utc_now())
        conn.execute("UPDATE users SET last_login_at=?, last_seen_at=? WHERE id=?", (now, now, row["id"]))
        conn.commit()
        return _public_user(row)
    finally:
        conn.close()


def create_session(user_id: int, *, conn: sqlite3.Connection | None = None) -> str:
    """Start a session for a user and return the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    now = _utc_now()
    with _conn_or_new(conn) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_utc_iso(now),))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (
                _hash_session_token(token),
                user_id,
                _utc_iso(now),
                _utc_iso(now),
                _utc_iso(now + timedelta(days=SESSION_LIFETIME_DAYS)),
            ),
        )
        return token


def session_id_for_token(token: str | None, *, conn: sqlite3.Connection | None = None) -> int | None:
    """The id of the session row for a cookie token (expired or not), or None."""
    if not token or len(token) > 200:
        return None
    with _conn_or_new(conn) as conn:
        row = conn.execute("SELECT id FROM sessions WHERE token_hash=?", (_hash_session_token(token),)).fetchone()
        return int(row["id"]) if row else None


def get_session(token: str | None) -> tuple[dict | None, int | None]:
    """Look up a session token: (active user, session id), or (None, None).

    The session id is kept out of the user dict, which is sent to the
    browser. Refreshes "last seen" about once a minute.
    """
    if not token or len(token) > 200:
        return None, None
    now = _utc_now()
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT u.id, u.username, u.display_name, u.is_admin, s.id AS session_id, s.last_seen_at AS session_seen_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
            (_hash_session_token(token), _utc_iso(now)),
        ).fetchone()
        if row is None:
            return None, None
        user = _public_user(row)
        try:
            seen = datetime.fromisoformat(row["session_seen_at"])
        except (TypeError, ValueError):
            seen = None
        if seen is None or seen.tzinfo is None or (now - seen).total_seconds() >= SESSION_TOUCH_SECONDS:
            try:
                # Don't hold up every request behind a long save just for this.
                conn.execute("PRAGMA busy_timeout = 1000")
                conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (_utc_iso(now), row["session_id"]))
                conn.execute("UPDATE users SET last_seen_at=? WHERE id=?", (_utc_iso(now), row["id"]))
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Database busy; "last seen" can wait for the next request.
        return user, row["session_id"]
    finally:
        conn.close()


def get_session_user(token: str | None) -> dict | None:
    """Look up the active user for a session token, refreshing "last seen" about once a minute."""
    return get_session(token)[0]


def delete_session(token: str | None, *, conn: sqlite3.Connection | None = None) -> None:
    if not token:
        return
    with _conn_or_new(conn) as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_session_token(token),))


def list_online_users(window_minutes: int = ONLINE_WINDOW_MINUTES) -> list[dict]:
    """People with a live session used in the last few minutes, most recent first."""
    now = _utc_now()
    cutoff = _utc_iso(now - timedelta(minutes=window_minutes))
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT u.username, u.display_name, MAX(s.last_seen_at) AS last_seen_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.last_seen_at >= ? AND s.expires_at > ? AND u.active = 1
               GROUP BY u.id
               ORDER BY last_seen_at DESC""",
            (cutoff, _utc_iso(now)),
        ).fetchall()
        return [
            {
                "username": r["username"],
                "display_name": r["display_name"] or r["username"],
                "last_seen_at": r["last_seen_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ── People admin ─────────────────────────────────────────────────────────────
# Admins add and remove people, reset PINs and choose who else is an admin.
# Removing someone keeps their row (so history still shows their name) but
# marks it inactive and ends their sessions. There is always at least one
# active admin, and nobody can remove themselves.

def _online_user_ids(conn, window_minutes: int = ONLINE_WINDOW_MINUTES) -> set[int]:
    now = _utc_now()
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM sessions WHERE last_seen_at >= ? AND expires_at > ?",
        (_utc_iso(now - timedelta(minutes=window_minutes)), _utc_iso(now)),
    ).fetchall()
    return {row["user_id"] for row in rows}


def _admin_user_view(row, online_ids: set[int]) -> dict:
    user = dict(row)
    active = bool(user.get("active"))
    return {
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "is_admin": bool(user.get("is_admin")),
        "active": active,
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
        "last_seen_at": user.get("last_seen_at"),
        "online": active and user["id"] in online_ids,
    }


def list_users_for_admin() -> list[dict]:
    """Everyone who has a login, active people first, then by name."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM users
               ORDER BY active DESC, COALESCE(NULLIF(display_name, ''), username) COLLATE NOCASE, username"""
        ).fetchall()
        online_ids = _online_user_ids(conn)
        return [_admin_user_view(row, online_ids) for row in rows]
    finally:
        conn.close()


def get_user_for_admin(username: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (str(username or "").strip(),)).fetchone()
        return _admin_user_view(row, _online_user_ids(conn)) if row else None
    finally:
        conn.close()


def _find_user_row(conn, username: str):
    username = str(username or "").strip()
    row = None
    if username and len(username) <= MAX_USERNAME_LENGTH:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        raise UserAdminError("No one has that username.", 404)
    return row


def _is_same_user(row, actor: dict | None) -> bool:
    return bool(actor) and actor.get("id") == row["id"]


def _other_active_admin_count(conn, user_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND active = 1 AND id != ?", (user_id,)
    ).fetchone()[0]


def _name(row) -> str:
    return row["display_name"] or row["username"]


def remove_user(username: str, actor: dict | None) -> tuple[dict, int]:
    """Stop someone logging in and log them out everywhere. Returns (person, sessions ended)."""
    with _user_write_transaction() as conn:
        row = _find_user_row(conn, username)
        if _is_same_user(row, actor):
            raise UserAdminError("You can't remove yourself. Ask another admin to do it.")
        if row["is_admin"] and row["active"] and _other_active_admin_count(conn, row["id"]) == 0:
            raise UserAdminError(f"{_name(row)} is the only admin. Make someone else an admin first.")
        ended = conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],)).rowcount
        if row["active"]:
            conn.execute("UPDATE users SET active = 0 WHERE id = ?", (row["id"],))
            _log_admin_action(conn, actor, "removed", row["username"], {"sessions_ended": ended})
        username = row["username"]
    return get_user_for_admin(username), ended


def restore_user(username: str, actor: dict | None) -> dict:
    """Let a removed person log in again (with their old PIN)."""
    with _user_write_transaction() as conn:
        row = _find_user_row(conn, username)
        if not row["active"]:
            conn.execute("UPDATE users SET active = 1 WHERE id = ?", (row["id"],))
            _log_admin_action(conn, actor, "restored", row["username"])
        username = row["username"]
    return get_user_for_admin(username)


def reset_user_pin(username: str, pin, actor: dict | None, keep_session_token: str | None = None) -> tuple[dict, int]:
    """Give someone a new PIN and log them out everywhere.

    ``keep_session_token`` is the admin's own session, so resetting your own
    PIN logs out your other devices but not the one you're using.
    """
    pin_hash = hash_pin(clean_pin(pin))
    keep_hash = _hash_session_token(keep_session_token) if keep_session_token else ""
    with _user_write_transaction() as conn:
        row = _find_user_row(conn, username)
        conn.execute("UPDATE users SET pin_hash = ? WHERE id = ?", (pin_hash, row["id"]))
        ended = conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (row["id"], keep_hash)
        ).rowcount
        _log_admin_action(conn, actor, "reset_pin", row["username"], {"sessions_ended": ended})
        username = row["username"]
    return get_user_for_admin(username), ended


def update_user(
    username: str,
    actor: dict | None,
    display_name: str | None = None,
    is_admin: bool | None = None,
) -> dict:
    """Change someone's name and/or whether they are an admin."""
    new_name = None if display_name is None else clean_display_name(display_name)
    with _user_write_transaction() as conn:
        row = _find_user_row(conn, username)
        if new_name is not None:
            new_name = new_name or row["username"]
            if new_name != row["display_name"]:
                conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (new_name, row["id"]))
                _log_admin_action(conn, actor, "renamed", row["username"], {"from": row["display_name"], "to": new_name})
        if is_admin is not None and bool(is_admin) != bool(row["is_admin"]):
            if not is_admin and row["active"] and _other_active_admin_count(conn, row["id"]) == 0:
                raise UserAdminError(f"{_name(row)} is the only admin. Make someone else an admin first.")
            conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, row["id"]))
            _log_admin_action(conn, actor, "made_admin" if is_admin else "removed_admin", row["username"])
        username = row["username"]
    return get_user_for_admin(username)


def ensure_admin_user(username: str, pin, display_name: str = "") -> list[str]:
    """First-time setup and lock-out recovery for the startup admin login.

    Creates the login as an admin with this PIN when the username is new.
    An existing login is only changed when there are no active admins at all:
    then it is made an active admin again, so someone can get back in.
    Otherwise it is left alone, so removing it or taking away its admin on the
    Users page sticks across restarts. An existing PIN is never overwritten
    (a PIN is only set when the login has none). Returns what changed, empty
    when nothing did. Never logs or returns the PIN.
    """
    username = clean_username(username)
    pin = clean_pin(pin)
    display_name = clean_display_name(display_name) or username
    changes: list[str] = []
    with _user_write_transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (username, display_name, pin_hash, active, is_admin, created_at) VALUES (?, ?, ?, 1, 1, ?)",
                (username, display_name, hash_pin(pin), _utc_iso(_utc_now())),
            )
            changes.append("created")
        elif conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND active = 1").fetchone()[0] == 0:
            # No one can manage logins, so bring this one back as the way in.
            if not row["is_admin"]:
                conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (row["id"],))
                changes.append("made admin")
            if not row["active"]:
                conn.execute("UPDATE users SET active = 1 WHERE id = ?", (row["id"],))
                changes.append("restored")
            if not row["pin_hash"]:
                conn.execute("UPDATE users SET pin_hash = ? WHERE id = ?", (hash_pin(pin), row["id"]))
                changes.append("PIN set")
            username = row["username"]
        if changes:
            _log_admin_action(conn, None, "startup_admin", username, {"changes": changes})
    return changes


def list_admin_log(limit: int = 50) -> list[dict]:
    """Recent people changes, newest first, with display names where known."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT l.id, l.created_at, l.username, l.action, l.target_username, l.details,
                      a.display_name AS actor_name, t.display_name AS target_name
               FROM admin_log l
               LEFT JOIN users a ON a.username = l.username
               LEFT JOIN users t ON t.username = l.target_username
               ORDER BY l.id DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    finally:
        conn.close()
    entries = []
    for row in rows:
        entry = dict(row)
        details = _json_loads_safe(entry.get("details"), {})
        entry["details"] = details if isinstance(details, dict) else {}
        entry["actor_name"] = entry.get("actor_name") or entry.get("username") or None
        entry["target_name"] = entry.get("target_name") or entry.get("target_username") or ""
        entries.append(entry)
    return entries


# ── Bid Tracker ──────────────────────────────────────────────────────────────
# Where each bid stands (status, due date, estimator, follow-ups) plus a
# history of what happened to it. Status rules and flags live in bid_tracker.py.

BID_TRACKING_COLUMNS: tuple[str, ...] = (
    "bid_status",
    "bid_due_date",
    "bid_due_time",
    "estimator",
    "next_follow_up_date",
    "won_lost_at",
    "won_lost_reason",
    "awarded_amount",
)


def _saved_bid_total(proposal_raw, bid_raw) -> float | None:
    """Grand total of the saved proposal, else of an older generated bid."""
    proposal = _json_loads_safe(proposal_raw, {})
    if isinstance(proposal, dict) and proposal.get("bundles"):
        try:
            return round(float(proposal.get("grand_total") or 0), 2)
        except (TypeError, ValueError):
            return None
    bid = _json_loads_safe(bid_raw, {})
    if isinstance(bid, dict) and bid.get("grand_total") is not None:
        try:
            return round(float(bid["grand_total"]), 2)
        except (TypeError, ValueError):
            return None
    return None


def _bid_event_from_row(row) -> dict:
    event = dict(row)
    details = _json_loads_safe(event.get("details"), {})
    event["details"] = details if isinstance(details, dict) else {}
    event["display_name"] = event.get("display_name") or event.get("username") or "System"
    return event


def _latest_bid_events(conn, event_type: str | None, job_id: int | None) -> dict[int, dict]:
    """The newest bid event per job (optionally of one type), keyed by job id."""
    inner_where = []
    params: list = []
    if event_type:
        inner_where.append("event_type = ?")
        params.append(event_type)
    if job_id is not None:
        inner_where.append("job_id = ?")
        params.append(job_id)
    where_sql = f"WHERE {' AND '.join(inner_where)}" if inner_where else ""
    rows = conn.execute(
        f"""SELECT e.*, u.display_name
            FROM bid_events e LEFT JOIN users u ON u.username = e.username
            WHERE e.id IN (SELECT MAX(id) FROM bid_events {where_sql} GROUP BY job_id)""",
        params,
    ).fetchall()
    return {row["job_id"]: _bid_event_from_row(row) for row in rows}


def list_bid_tracker_jobs(job_id: int | None = None) -> list[dict]:
    """Every job's stored bid tracking fields, saved bid total, last send and last change.

    ``bid_status`` is returned as stored (NULL on jobs nobody has tracked yet);
    ``material_count`` lets the caller pick the default status.
    """
    conn = _get_conn()
    try:
        # Deleted bids aren't tracked (an admin can restore them first).
        where_sql = "WHERE j.deleted_at IS NULL" + (" AND j.id = ?" if job_id is not None else "")
        rows = conn.execute(
            f"""SELECT j.id AS job_id, j.slug, j.project_name, j.gc_name, j.salesperson,
                       j.city, j.state, j.created_at,
                       j.bid_status, j.bid_due_date, j.bid_due_time, j.estimator,
                       j.next_follow_up_date, j.won_lost_at, j.won_lost_reason, j.awarded_amount,
                       j.proposal_data, j.bid_data,
                       (SELECT COUNT(*) FROM job_materials m WHERE m.job_id = j.id) AS material_count
                FROM jobs j {where_sql}
                ORDER BY j.created_at DESC""",
            (job_id,) if job_id is not None else (),
        ).fetchall()
        latest_sent = _latest_bid_events(conn, "sent", job_id)
        latest_any = _latest_bid_events(conn, None, job_id)
    finally:
        conn.close()

    results = []
    for row in rows:
        item = dict(row)
        item["bid_total"] = _saved_bid_total(item.pop("proposal_data", None), item.pop("bid_data", None))
        sent = latest_sent.get(item["job_id"])
        if sent:
            details = sent["details"]
            item["last_sent_date"] = str(details.get("sent_on") or sent["created_at"] or "")[:10] or None
            item["last_sent_to"] = details.get("sent_to") or ""
            item["last_sent_gc"] = details.get("gc_name") or ""
            item["last_sent_total"] = details.get("bid_total")
        else:
            item["last_sent_date"] = None
            item["last_sent_to"] = ""
            item["last_sent_gc"] = ""
            item["last_sent_total"] = None
        last = latest_any.get(item["job_id"])
        item["last_updated_at"] = last["created_at"] if last else None
        item["last_updated_by"] = last["username"] if last else None
        item["last_updated_by_name"] = last["display_name"] if last else None
        results.append(item)
    return results


def get_bid_tracker_job(job_id: int) -> dict | None:
    rows = list_bid_tracker_jobs(job_id)
    return rows[0] if rows else None


def list_bid_events(job_id: int, limit: int | None = None) -> list[dict]:
    """Bid history for one job, newest first, with each person's display name."""
    conn = _get_conn()
    try:
        sql = """SELECT e.*, u.display_name
                 FROM bid_events e LEFT JOIN users u ON u.username = e.username
                 WHERE e.job_id = ?
                 ORDER BY e.id DESC"""
        params: list = [job_id]
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [_bid_event_from_row(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def save_bid_tracking(
    job_id: int,
    updates: dict,
    events: list[tuple[str, dict]],
    username: str | None,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[int]:
    """Update a job's bid tracking columns and record history events in one transaction.

    The audit entry is written in the same transaction: inside a job_write
    for this job (pass tx.conn) the events are added to that write's entry,
    which is always recorded when there are events; called on its own, this
    runs its own job_write.
    """
    import audit
    unknown = set(updates) - set(BID_TRACKING_COLUMNS)
    if unknown:
        raise ValueError(f"Not a bid tracking field: {', '.join(sorted(unknown))}")
    active = audit.active_write()
    if conn is None and active is None:
        from job_writes import job_write
        action = f"bid.{events[0][0]}" if events else "bid.tracking.update"
        with job_write(job_id, action=action, scopes=("tracking",)) as tx:
            return save_bid_tracking(job_id, updates, events, username, conn=tx.conn)
    conn = conn or active.conn
    if updates:
        columns = list(updates)
        conn.execute(
            f"UPDATE jobs SET {', '.join(f'{column}=?' for column in columns)} WHERE id=?",
            [updates[column] for column in columns] + [job_id],
        )
    created_at = _utc_iso(_utc_now())
    event_ids = []
    for event_type, details in events:
        cur = conn.execute(
            "INSERT INTO bid_events (job_id, event_type, created_at, username, details) VALUES (?, ?, ?, ?, ?)",
            (job_id, event_type, created_at, username, json.dumps(details or {}, default=str)),
        )
        event_ids.append(cur.lastrowid)
    if (
        events
        and active is not None
        and active.conn is conn
        and getattr(active, "job_id", None) is not None
        and int(active.job_id) == int(job_id)
    ):
        # A bid event is history even when no tracking field changed.
        active.force_record()
        recorded = active.extra.setdefault("bid_events", [])
        for event_id, (event_type, details) in zip(event_ids, events):
            recorded.append({"id": event_id, "type": event_type, "details": details or {}})
    return event_ids


def get_latest_job_artifact(job_id: int, artifact_kind: str) -> dict | None:
    """The newest receipt of one kind (e.g. the latest printed proposal PDF), or None."""
    conn = _get_conn()
    try:
        row = conn.execute(
            f"""SELECT {_ARTIFACT_COLUMNS}
                FROM job_artifacts a LEFT JOIN users u ON u.username = a.created_by
                WHERE a.job_id=? AND a.artifact_kind=?
                ORDER BY a.created_at DESC, a.id DESC LIMIT 1""",
            (job_id, artifact_kind),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
