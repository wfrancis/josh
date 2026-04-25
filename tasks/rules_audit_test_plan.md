# Rules/Audit Deployed Harness

`scripts/rules_audit_harness.py` is a deployed-environment QA harness for the rules/audit lane. It accepts a Fly/staging/prod `--base-url`, creates a temporary test job by default, uploads a synthesized RFMS workbook generated from `test_data/rules_audit/josh_lessons_cases.json`, prices the parsed materials, runs calculate/proposal generation, and emits both a human PASS/FAIL report and JSON details.

## Run

```bash
cd /Users/william/josh
python3 scripts/rules_audit_harness.py --base-url https://si-bid-tool.fly.dev
```

Useful options:

```bash
python3 scripts/rules_audit_harness.py \
  --base-url https://si-bid-tool.fly.dev \
  --json-output /tmp/rules_audit_harness.json \
  --keep-job
```

Use `--job-id <id-or-slug>` only with a disposable existing job; the harness uploads RFMS data and rewrites materials on the target job. Use `--header 'Authorization: Bearer ...'` if a deployed environment adds auth. `--allow-missing-audit` downgrades missing audit trace payloads to WARN while production audit endpoints are still being wired.

## Permanent Cases

The fixture permanently covers:

- 5x5 tile is not mosaic.
- 2x12 tile is mosaic.
- `B-` rubber base fallback.
- `WM-` walk-off mat/carpet tile fallback.
- `RF-` rubber sheet fallback.
- `VCT-` fallback.
- Carpet tile labor at `$3.85/SY`.
- Tax excludes labor.
- Deleted proposal bundles stay deleted across regenerate.
- Audit trace is expected to include material, sundry, labor, tax, and GPM total categories.

## API Assumptions

Required existing app APIs:

- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `PUT /api/jobs/{job_id}/materials`
- `POST /api/jobs/{job_id}/upload-rfms`
- `POST /api/jobs/{job_id}/calculate`
- `POST /api/jobs/{job_id}/proposal/generate`
- `PUT /api/jobs/{job_id}/proposal/bundles`
- `DELETE /api/jobs/{job_id}` for cleanup when the harness created the job

Rule registry discovery currently accepts either a formal registry endpoint (`/api/rules/registry`, `/api/rule-registry`, `/api/rules`, `/api/audit/rules`, or `/api/pricing-rules/registry`) or the legacy combination of `/api/company-rates` plus `/api/labor-catalog`.

Optional future rule evaluator endpoints are probed at `/api/rules/evaluate`, `/api/rules/test`, `/api/rules/material`, and `/api/rule-registry/evaluate`. The payload shape is:

```json
{
  "case_id": "T-212",
  "material": {
    "item_code": "T-212",
    "description": "T-212 - Arizona Tile - Linear Mosaic 2\" x 12\"",
    "material_type": "unknown",
    "installed_qty": 1,
    "unit": "SF"
  }
}
```

Optional audit endpoints are probed at `/api/jobs/{job_id}/audit`, `/api/jobs/{job_id}/proposal/audit`, `/api/jobs/{job_id}/rules/audit`, and `/api/jobs/{job_id}/calculation-audit`. If no endpoint exists, the harness also searches proposal output for trace-like keys such as `audit`, `trace`, `calculation_trace`, or `rule_trace`.
