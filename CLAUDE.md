## Build & Deploy
- Build: `cd frontend && npx vite build`
- Deploy: `cd si-bid-tool && flyctl deploy` (set `FLY_API_TOKEN` env var first)
- All testing is done on Fly.io, never locally
- App URL: https://si-bid-tool.fly.dev/

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
- The Fly volume mounts at `/data`, and `DATABASE_PATH` env var points to `/data/si_bid.db`.
- Local dev uses `server/si_bid_tool.db` (fallback in `models.py`).

### Fly Deploy Commands (Windows)
- Build frontend first: `cd frontend && npx vite build`
- Deploy: `cd si-bid-tool && flyctl deploy` (with `FLY_API_TOKEN` set)
- The old CLAUDE.md paths (`/Users/william/...`) are stale Mac paths — ignore them.
- SSH commands on Windows always show `Error: The handle is invalid` — this is cosmetic, the command still runs.
- Always wrap multi-command SSH in `sh -c '...'` — Fly's SSH doesn't support `&&` directly.

