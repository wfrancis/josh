# Lessons Learned

## Labor Quantity Rules
- Labor is paid on **NET installed area** for ALL materials EXCEPT unit stretch-in broadloom (unit_carpet_no_pattern, unit_carpet_pattern)
- Stretch-in broadloom installers are paid by the roll/total material (with_waste)
- This applies to LVT, carpet tile, floor tile, wall tile, backsplash, tub surrounds, rubber base, VCT — all net area
- Config: `LABOR_QTY_RULES` in config.py, default is `no_waste`

## RFMS Parser: Install Qty vs Material Qty
- RFMS material line includes RFMS's own waste — do NOT use it as the base
- Use the INSTALL line qty (net installed area) and apply our own waste factors
- Example: CPT-2 material=36 SY, install=34.6 SY — use 34.6

## Area Type (Unit vs Common Area)
- Materials from amenity/common area RFMS sheets must be tagged `area_type='common'`
- Detection is from filename: "common area" or "amenity" substring match
- `area_type` must be preserved through AI merge — include it in all merge data structures
- The bundler already handles `common:` prefix and renames "Unit X" to "Common Area X"

## DB-Cached Rules Override Config
- `company_rates` table stores sundry_rules, waste_factors, freight_rates as JSON
- These override config.py defaults — always update BOTH when changing rules
- Check DB first when config changes don't seem to take effect

## Sundry Qty Sources
- RFMS measured quantities (tack_strip_lf, seam_tape_lf, pad_sy) are stored on material records
- Sundry rules with `qty_source` field use these measured values instead of estimating
- Seam tape: 60 LF/roll at $9.09/roll (not 117 LF or $18)

## Freight Calculation
- Materials store `freight_per_unit`, NOT pre-calculated `freight_cost`
- Bundler must calculate: freight_cost = freight_per_unit * order_qty
- Only cpt_tile materials have freight_per_unit set from quotes; broadloom/LVT need config rates applied

## GPM Calculation
- GPM is calculated on material base only (material + sundry + freight) — labor is pass-through
- Profit is redistributed: 99% on labor line, 1% on material/sundry line
- Revenue = material_base / (1 - gpm_pct)

## Server / Frontend
- Python changes require server restart (no auto-reload)
- Frontend JSX changes require `npx vite build` in frontend/ dir (serves from dist/)
- Kill old server process before restarting if port is in use
