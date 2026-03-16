fly tokens create deploy -a pokemon-card-trader

## Build & Deploy
- Build: `cd frontend && nvm use 18 && node node_modules/.bin/vite build`
- Deploy: `cd /Users/william/josh && /Users/william/.fly/bin/fly deploy`
- All testing is done on Fly.io, never locally

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

