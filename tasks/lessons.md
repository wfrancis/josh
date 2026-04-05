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

## Vendor Quote Matching: No Fuzzy Matching
- The RFMS description contains the vendor name: "T-200 - Arizona Tile - Flash - Ivory"
- The auto-matcher MUST extract the vendor name from the RFMS description
- Vendor name is a HARD FILTER — only match quotes from the vendor named in the RFMS
- If RFMS says "Arizona Tile", NEVER match to Metropolitan Floors or anyone else
- Vendor extraction: split on " - ", skip option prefixes and item codes, take the first real name
- Materials without a clear vendor in the description (transitions, generic items) skip the filter
- Vendor aliases for parent/subsidiary: Daltile=Marazzi (Daltile owns Marazzi), Interface=Flor, Mohawk=Daltile/Marazzi

## Sound Mat (Pliteq Genie Mat) Rules
- RFMS may have BOTH Standard and Premium sound mat lines (one per LVT scheme)
- e.g. "Pliteq Genie Mat RST05 @Standard Unit LVT" and "@Premium Unit LVT"
- Parser dedupes by item_code so the Premium one gets dropped — needs manual add or parser fix
- RFMS may have typo "Preminum" instead of "Premium" — handle both spellings


- Material type: `sound_mat` (NOT rubber_sheet)
- Price: $93.02 per ROLL (120 SF/roll), round up to full rolls
- Adhesive: Taylor Dynamics stocked $73/pail at 700 SF/pail (NO freight — stocked)
- Primer: Taylor $17/bucket at 350 SF/bucket
- NO weld rod (sound mat doesn't get welded)
- Labor: Rubber sheet over 3mm at $0.50/SF
- NOT the same as rubber_sheet which uses $95/pail vendor adhesive + $65 primer + weld rod

## Pliteq Genie Mat RST-05
- $93.02 per ROLL, NOT per SF
- Each roll covers 120 SF
- Round up to full rolls: ceil(SF / 120) × $93.02
- NEVER price this per SF — the $93.02 is the roll price

## Waterproofing (RedGard) Pricing
- Custom RedGard 5 Gal Pail: $156.00, coverage 275 SF/pail (2 coats)
- Mesh fabric: $42.00/roll, 300 SF/roll (corners and seams only)
- Labor: **$0.54/SF Waterproofing Roll On** (NOT Kerdi at $1.07 — Kerdi is sheet membrane, RedGard is roll-on)
- RedGard pails ARE the membrane material — do NOT add a separate "membrane" sundry line
- The only sundry is mesh fabric for corners/seams
- RFMS may include waterproofing as a material line ("Liquid-Latex Rubber...Redgard")
- When RFMS has it: bundler uses that material directly
- When RFMS doesn't have it: bundler derives from tub_shower_surround SF
- NEVER double-count: skip derived bundle if RFMS waterproofing material exists

## RFMS By Item Sheet Can Over-Count
- The By Item sheet totals can be WRONG — they may over-count materials that appear in multiple schemes
- Always cross-check against the Main sheet row sums for suspicious quantities
- T-202 tub surround: By Item said 58,651 SF but Main sheet rows sum to 34,331 SF (1.71x inflated)
- The parser uses By Item install qty which can be wrong — need validation against Main sheet

## Bundle Ordering
- ALL unit bundles MUST come before ALL common area bundles — no exceptions
- Unit order: CPT → LVT → Backsplash → Tile Surrounds → Waterproofing → Sound Mat → Transitions → Stairs
- Common area order follows same pattern but after ALL unit bundles
- Custom/renamed bundles preserve their position relative to neighbors on regenerate

## Schluter Product Pricing Rules
- Schluter products are priced from `price_book_items` table (imported via Schluter catalog)
- ALL Schluter products come in 8' sticks (8' 2-1/2" = 8.208 LF) — ALWAYS round up to full sticks
- Default finish is AE (satin anodized aluminum) unless spec says otherwise
- Default SIZE is always 100 for all Schluter profiles
- Auto-pricer matches by product_line (SCHIENE, RENO-TK, JOLLY, etc.) + item_no from description
- Schluter Jolly for tub/shower surrounds: qty = tub_shower_count × 2 sticks
- Price per stick from price_book_items, NOT per LF — extended_cost = sticks × stick_price

## Silver Pin Metal Transitions
- Silver pin metal is $7.94 per 12' stick (not per LF)
- Only used at unit stretch-in CPT to LVT transitions
- NEVER used for common area/amenity CPT transitions
- Common area CPT transitions use different trim (vendor quoted, e.g. Schluter)
- Stored in config.py SUNDRY_RULES under "transitions"

## RFMS Parser: (Standard)/(Premium) Option Prefix Bug
- RFMS descriptions can start with `(Standard)`, `(Premium)`, `(Alternate)` etc. — these are option designations like `(Scheme A/B)`
- The parser must strip these prefixes to reach the real item code (CPT-200, T-202, etc.)
- If not stripped: ALL `(Standard)` materials share one item_code → install qtys summed across ALL materials → 42x inflated quantities → dedup drops most materials
- Fix: treat option prefixes identically to scheme prefixes in both `_extract_item_label()` and `_extract_install_code()`
- Prefixes can stack: `(Alternate) (Standard) - T-200.1` → must loop to strip all
- The option prefix stays in the item_code for uniqueness: `"(Standard) CPT-200"` vs `"(Premium) CPT-201"`

## Vendor Quote Simulation Bugs Found & Fixed
- **PowerShell UTF-8 BOM**: `Set-Content -Encoding UTF8` adds a BOM (EF BB BF) that corrupts Python's email parser. Always use `[System.IO.File]::WriteAllText($path, $data, (New-Object System.Text.UTF8Encoding $false))` for BOM-free UTF-8.
- **JS string vs number ID mismatch**: Inline `onclick="fn('${id}')"` passes a string, but `array.find(r => r.id === id)` compares to a number from JSON. Always `Number(id)` at the top of every function that receives an ID from HTML onclick.
- **Vendor Simulator status API**: UI expected `data.pending` but API returns `data.counts.pending`. Always check the actual API response shape before writing UI code.
- **Test mode "Send to Simulator" button**: Must show in test mode even when vendor has no email. Use `(contact?.contact_email || testMode)` as the condition, with a fallback email like `vendorname@simulator.local`.
- **Adhesive freight**: Vendor-supplied adhesives need `freight_per_unit: 5.00` in sundry rules. Taylor Dynamics stocked adhesive has no freight.
- **Textura on PDF**: `textura_fee` and `textura_amount` must be passed through the `proposal_data` dict to the PDF generator — they were being sent from frontend but dropped at the API layer.

## Stair Sundry Ratios (Commercial)
- Pad: 0.74 SY/stair (6lb 3/8", $1.38/SY, 30 SY rolls — round up to full rolls)
- Tack strip: 6.0 LF/stair (amenity situation)
- Seam sealer: 5.307 LF/stair

## Tax Calculation
- Tax must be computed as derived state from current cost components, NOT stored from generation time
- Formula: taxable = material_cost + sundry_cost + freight + gpm_material_adder
- Tax = taxable × taxRate
- Recalculate in updateBundle() on every edit, and sum per-bundle in recalcTotals()

## TDZ (Temporal Dead Zone) in React Minified Builds
- `const` + `useCallback` declarations are NOT hoisted in minified builds
- If function A references variable B, B must be declared BEFORE A in source order
- Symptom: `ReferenceError: Cannot access 'X' before initialization` only in production builds

## Server / Frontend
- Python changes require server restart (no auto-reload)
- Frontend JSX changes require `npx vite build` in frontend/ dir (serves from dist/)
- Kill old server process before restarting if port is in use
