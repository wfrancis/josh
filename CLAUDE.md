## Project Goal: Replace JobRunner
- Standard Interiors (the client; Josh is the estimator) uses **JobRunner** (Pacific Solutions/Cyncly flooring software) to build bids and run bids and jobs.
- **Goal: replace JobRunner with tools we build around Microsoft Business Central (BC).** The SI Bid Tool is the first piece: takeoff → priced proposal PDF.
- For every feature, check whether BC already does it before building. Build only what's missing, and connect to BC instead of duplicating it. Never hand data back to JobRunner.
- JobRunner does the things listed below; each needs a replacement:
  - bid intake and bid due dates
  - proposals
  - sending and tracking bids, won/lost
  - turning a won bid into a job
  - purchase orders
  - installer work orders
  - change orders
  - progress billing, retainage and AIA pay applications
  - job cost

## Business Central (BC) — HARD CONSTRAINTS
- **Standard's production BC is READ ONLY.** Never create, edit, post, delete or send anything there. Don't run setup wizards or type into fields. Avoid setup pages, because some of them write a record just by being opened.
- Test any integration in a sandbox or a test company, never in production.
- Production URL: https://businesscentral.dynamics.com/79ae44bb-8783-45ad-9c4a-9db3fa881c12/Production?company=SI

## What's in Standard's BC (read-only look, 2026-09-23)
- Company: Standard Interiors of Colorado, LLC (code `SI`). Locations: CO-DEN, AZ-PHX, NV-LV.
- Plan: **Essentials** plus Team Member licenses; nobody is on Premium. About 34 users are enabled.
- BC partner: **Rand Group, LLC.** They built custom extensions ("Standard Interiors - Custom") and have an Entra app connected to BC. Coordinate any custom BC extension or API with them.
- Add-ons:
  - Avalara AvaTax (sales tax)
  - Continia (bill scanning, approvals, document output)
  - Insight Works Warehouse Insight (warehouse, barcodes)
  - Shopify Connector
  - RUX Toolbox
- **No construction add-on.** Change orders, progress billing, retainage and AIA are not in BC.
- **Projects module is unused.** It holds only two test projects.
- **No bidding in BC:** zero opportunities and one empty sales quote.
- **Commercial jobs** are set up as one customer per project (`C000xxx`, e.g. "Thompson Thrift - 23-266 AZ"). Each has several sales orders (`S-ORD…`) carrying material item lines only, with no labor. The order's External Document No. is a 6-digit number that is probably the JobRunner job number (unverified).
- **Multifamily unit work** uses `MF-` customers (apartment communities). Those orders carry custom fields: Unit Number, Work Description, Install Date.
- Test companies named "SI Test <date>" already exist in the environment.
- Open decision for Standard: keep one customer per job, or move jobs into BC Projects. Projects gives real job budgets and job cost, but it would change how their staff work.

## Build & Deploy
- Build: `cd frontend && npx vite build`
- Deploy: `cd si-bid-tool && flyctl deploy` (set `FLY_API_TOKEN` env var first)
- All testing is done on Fly.io, never locally
- App URL: https://si-bid-tool.fly.dev/

### Audit trail checks
- **Every write route needs `@audit_route("action", ...)` or `@no_audit("reason")`** (from `server/audit.py`). The Docker build runs `scripts/audit_route_coverage.py --missing`, so a deploy **fails** while any POST/PUT/PATCH/DELETE route has neither. Run it yourself first: `python3 scripts/audit_route_coverage.py`.
- **Staging (`si-bid-stg-20260714-c0fa`) runs with `AUDIT_STRICT` on**: a write that saved data without a history entry answers 500 instead of only logging it. This is automatic on that app (the code checks Fly's `FLY_APP_NAME`); `fly secrets set AUDIT_STRICT=0 -a si-bid-stg-20260714-c0fa` turns it off, and `AUDIT_STRICT=1` turns it on anywhere else. Prod is not strict.
- After deploying to staging, run `AUDIT_PROBE_PIN=<pin> python3 scripts/audit_completeness_probe.py --base-url https://si-bid-stg-20260714-c0fa.fly.dev --username <login>`. It edits a throwaway bid and vendor (then deletes them) and checks each change shows up in `/api/audit` with the right action, person and values. `--list-unprobed` lists the audited routes it doesn't call yet.

## Tech Stack
- Frontend: React 18 + Vite 5 + Tailwind CSS 3 + Lucide React icons
- Backend: FastAPI + SQLite + plain sqlite3
- AI: OpenAI API (model selected in app Settings page)

## Mistakes / Lessons Learned (DO NOT REPEAT)

### AI Model Selection
- **NEVER hardcode an AI model name.** Always use `settings.get("openai_model", "gpt-5-mini")` to respect the user's selected model from the Settings page.
- The default fallback is `gpt-5-mini` — do not use `gpt-4o-mini` or any other model as fallback.
- Pattern: `settings = get_settings(); model = settings.get("openai_model", "gpt-5-mini")`
- **NEVER set `temperature` parameter** in OpenAI calls — `gpt-5-mini` only supports the default temperature (1). Remove `temperature=0` or `temperature=0.3` from all calls.

### CSS Transform Containing Block
- **NEVER render `position: fixed` modals inside elements with CSS transforms** (including `animation-fill-mode: forwards` with transforms like `translateY`). A `transform` on any ancestor creates a new containing block, breaking `fixed inset-0` overlays.
- Always render modals at the top level of the component return, outside any animated containers.

### Job ID Resolution
- Job endpoints that accept `{job_id}` as a string must handle both numeric IDs and slugs.
- Use `_resolve_job_id(job_id)` helper (defined in main.py) which calls `load_job()` and returns the numeric DB id.
- Pattern: `db_id = _resolve_job_id(job_id)` then use `db_id` for all DB operations.

### Deploying Local DB to Fly.io
- **NEVER fight with `fly sftp` or chunked SSH uploads on Windows.** It doesn't work reliably.
- To push a local SQLite DB to Fly: temporarily modify the Dockerfile `CMD` to `cp /app/seed_db.db /data/si_bid.db` before starting uvicorn, add a `COPY server/si_bid_tool.db /app/seed_db.db` line, deploy, then **revert the Dockerfile** so future deploys don't overwrite.
- **The DB runs in WAL mode**, so recent changes can sit in `si_bid.db-wal` next to the `.db` file.
  - Before copying a local DB, stop the local server (or run `sqlite3 server/si_bid_tool.db "PRAGMA wal_checkpoint(TRUNCATE);"`) so every change is in the `.db` file.
  - When copying a DB in on Fly, **also delete `/data/si_bid.db-wal` and `/data/si_bid.db-shm`** in the same command, e.g. `rm -f /data/si_bid.db-wal /data/si_bid.db-shm && cp /app/seed_db.db /data/si_bid.db`. A leftover `-wal` file from the old DB would be applied on top of the new one and corrupt it.
- The Fly volume mounts at `/data`, and `DATABASE_PATH` env var points to `/data/si_bid.db`.
- The app must run as **one process on one Fly machine** (never scale out or add uvicorn workers). Startup takes a lock on `/data/.collab.lock` and logs a loud `[single-process] ERROR` if another process already holds it.
- Local dev uses `server/si_bid_tool.db` (fallback in `models.py`).

### Fly Deploy Commands (Windows)
- Build frontend first: `cd frontend && npx vite build`
- Deploy: `cd si-bid-tool && flyctl deploy` (with `FLY_API_TOKEN` set)
- The old CLAUDE.md paths (`/Users/william/...`) are stale Mac paths — ignore them.
- SSH commands on Windows always show `Error: The handle is invalid` — this is cosmetic, the command still runs.
- Always wrap multi-command SSH in `sh -c '...'` — Fly's SSH doesn't support `&&` directly.

