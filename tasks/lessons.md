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
- Within each type: Standard before Premium before Alternate
- Related sub-items follow their parent immediately:
  1. CPT (Standard → Premium) → Stairs (broadloom stair carpet follows CPT)
  2. LVT (Standard) → Sound Mat (Standard) → LVT (Premium) → Sound Mat (Premium)
  3. Backsplash (Standard → Premium → Alternate)
  4. Tile Surrounds (Standard → Premium)
  5. Waterproofing
  6. Transitions
- Sound mat follows LVT because it's underlayment FOR the LVT
- Common area ordering: CPT tiles (numerical) → LVT → RF (rubber) → Tile (T-xxx numerical)
- Within each type, sort by numeric code (CPT-100, CPT-101, CPT-102...)
- F-codes (F-101, F-102) are floor finish callouts from the finish schedule, NOT material types — sort separately
- Common area follows same type ordering but after ALL unit bundles
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
- Tack strip: 6.0 LF/stair — priced per CARTON (400 LF/carton @ $36.99), round up to full boxes
  - Same carton pricing as regular CPT tack strip
  - qty = Math.ceil(totalLF / 400) cartons, NOT raw LF
- Seam sealer: 5.307 LF/stair

## Stair Sundries: Remove Regular Duplicates
- When stair sundries (Stair Pad, Stair Tack Strip, Stair Seam Sealer) are added, REMOVE the regular pad, tack_strip, and seam_tape sundries
- The stair-specific versions REPLACE the regular ones — they are NOT additive
- pad_cement should STAY (still needed to glue pad on stairs)
- Code fix is in ProposalEditor.jsx `addStairLabor()` — filters out ['pad', 'tack_strip', 'seam_tape'] before combining

## Sound Mat: Net Area + 5% Waste
- Sound mat quantity = net installed area of the LVT it goes under + 5% waste
- Do NOT use the LVT's order_qty (which includes LVT's own waste factor)
- The bid_assembler.py has a special case: for sound_mat with unit EA, apply waste to order_qty even though it's pre-calculated
- Formula: `order_qty = ceil(original_order_qty * 1.05)`

## RFMS Unit Conversion: SY vs SF
- RFMS quantities can be in SY even when the material is sold by SF
- Rubber sheet (RF-xxx) is a common case: RFMS measures in SY, vendor sells by SF
- ALWAYS check RFMS unit vs vendor quote unit — if mismatched, convert: SF = SY × 9
- The installed_qty, order_qty, and extended_cost all need updating after conversion
- Labor may use different units (SY for sheet set, LF for welding) — check before changing

## Vendor Quote Sundry Pricing
- When a vendor quote includes sundries (adhesive, primer, etc.), use THOSE prices, not config defaults
- Eco Surfaces/Spartan: ES-90 Adhesive 4 Gal = $308.71/pail (180-480 SF coverage), E-Cleaner = $73.64/gal (6000 SF)
- Config defaults ($95 adhesive, $65 primer) are generic fallbacks — vendor quotes override
- Always note the quote number in sundry notes for traceability

## Common Area Bundle Ordering (Josh's spec)
- Each common area material gets its OWN bundle — never combine multiple materials into one mega-bundle
- **Order of common area sections:**
  1. CPT Tile (CPT-xxx, then WM-xxx walk-off) — sort numerically within each
  2. Resilient floors (RF-xxx rubber sheet)
  3. Ceramic/Porcelain Tile (T-xxx) — includes T-116 tub_shower_surround in sequence
  4. BOH LVT (LVT-xxx)
  5. Common Transitions (all amenity/common transitions)
  6. Waterproofing (Dog Wash, etc)
  7. Crack Isolation
  8. Rubber Base (B-xxx), Sound Mat (amenity), other
- T-116 is tub_shower_surround type but MUST sort with T-100..T-115 (drive by T-code number)
- WM-100 (walk-off mat) material_type=cpt_tile, sorts AFTER last CPT-xxx (not mixed in)
- proposal_bundler.py `_sort_key` uses priority ranges 1100/1200/1300/... for common-area categories

## Schluter Jolly for Tub/Shower Surrounds
- Every tub/shower gets 2 sticks of Schluter Jolly AE
- Sticks are 8' (8' 2-1/2") each
- qty = tub_shower_count × 2
- Price from price_book_items: JOLLY J 100 AE = $9.78/stick (net after 55% discount)
- Goes in the Unit Transitions bundle alongside Schiene and silver pin metal
- If missing from transitions bundle, it needs to be added manually

## Tax Calculation
- Tax must be computed as derived state from current cost components, NOT stored from generation time
- Formula: taxable = material_cost + sundry_cost + freight + gpm_material_adder
- Tax = taxable × taxRate
- Recalculate in updateBundle() on every edit, and sum per-bundle in recalcTotals()

## TDZ (Temporal Dead Zone) in React Minified Builds
- `const` + `useCallback` declarations are NOT hoisted in minified builds
- If function A references variable B, B must be declared BEFORE A in source order
- Symptom: `ReferenceError: Cannot access 'X' before initialization` only in production builds

## EA Materials: Never Recalculate order_qty from installed_qty
- When unit is "EA" and installed_qty is in SF but order_qty is in BUCKETS/ROLLS/UNITS, they are DIFFERENT units
- order_qty = number of physical products to order (buckets, rolls, boxes)
- installed_qty = area in SF that those products cover
- When scaling qty: use the RATIO, e.g. `new_order_qty = ceil(old_order_qty * (new_sf / old_sf))`
- NEVER do `order_qty = installed_qty * (1 + waste)` for EA materials — this confuses SF with product count
- Example: Redgard 214 buckets for 58,651 SF → scaled to 39,052 SF = ceil(214 * 0.666) = 143 buckets
- Same applies to: sound mat rolls, adhesive pails, primer buckets, etc.

## Server / Frontend
- Python changes require server restart (no auto-reload)
- Frontend JSX changes require `npx vite build` in frontend/ dir (serves from dist/)
- Kill old server process before restarting if port is in use

## Waterproofing: No Separate Membrane Sundry
- RedGard pails ARE the membrane — NEVER add a separate `membrane` sundry line
- If a `membrane` sundry appears in the bundle, it is wrong and must be removed
- Only valid sundry for RedGard waterproofing is `mesh_fabric` (corners/seams only)
- Material line: RedGard 5 Gal pail @ $156.00, coverage 275 SF/pail (2 coats)
- Mesh fabric: $42.00/roll, 300 SF/roll

## Schluter @Tub/Shower Surrounds: Use RFMS LF for Labor and Stick Count
- RFMS Main sheet contains "Schluter - Schiene #AE-100 - Metal Edge Strip @Tub/Shower Surrounds" rows
- Sum all those rows across all unit types to get total installed LF (e.g., 8,384.93 LF for Sun Valley Blk 2)
- Sticks to order: ceil(total_lf / 8.208) — round up to full sticks
- Labor: total_lf × $0.50/LF (Schluter Schiene rate)
- The By Item sheet shows this as a bare number row with no description (e.g., `'8385'`) — parser skips it
- NEVER calculate from tub_count × 2 sticks × 8.208 LF — use RFMS measured LF instead
- This is separate from the Schiene @Kitchen Backsplash line (also in RFMS, also parsed)

## RFMS By Item Parser Gap: Bare Number Rows
- The By Item sheet sometimes has rows where description = a bare number (e.g., `'8385'`)
- These represent RFMS totals for items that weren't labeled correctly in the export
- For Schiene @Tub/Shower, the bare number matches the sum of Main sheet rows exactly
- Workaround: sum the Main sheet rows directly for these items
- Long-term fix: parser should cross-reference Main sheet when By Item description is non-descriptive

## Schluter Jolly Labor: Must Be Added Manually for Manually-Added Materials
- Materials added manually to proposal_data with id=None bypass labor_calc.py entirely
- labor_calc only runs on job_materials table entries (from RFMS import)
- For Schluter Jolly (tub surrounds), labor must be explicitly added to the bundle's labor_items
- Rate: $0.50/LF (Schluter Schiene from labor catalog) — no separate "Jolly" catalog entry
- Qty: use RFMS measured LF, not sticks × 8.208

## Freight Stale After Manual proposal_data Edits
- proposal_bundler.py correctly calculates freight (freight_per_unit OR config FREIGHT_RATES × order_qty)
- BUT when we hand-edit proposal_data (remove sundries, add labor, re-sort bundles), freight_cost is NOT recomputed
- After any manual edit to materials/sundries/qtys, recompute freight_cost per bundle THEN redistribute GPM THEN recalculate tax
- Formula per bundle: freight_cost = sum(config_freight(mt) × order_qty for each material) + sum(sundry.freight_cost)
- FREIGHT_RATES: cpt_tile=$1.25, broadloom=$0.65, lvt_2mm=$0.11, lvt_5mm=$0.25
- FREIGHT_MAP covers only: cpt_tile, corridor_broadloom, unit_carpet_*, unit_lvt
- Floor/wall tile, backsplash, rubber sheet, sound mat, transitions, waterproofing → NO freight per config (vendor FOB or included)

## Material Classification: unknown → No Freight
- Materials with material_type="unknown" get ZERO freight even if they should (CPT tile, walk-off mat)
- Parser misclassifies when description doesn't match classifier heuristics (e.g., CPT-110 with only dimensions, WM-100 walk-off mat)
- Fix: reclassify by item_code prefix — CPT-* → cpt_tile, WM-* → cpt_tile (carpet construction), T-* → floor_tile/wall_tile, B-* → rubber_base
- Root-cause fix belongs in classifier.py: add regex rules for CPT-\d+, WM-\d+, T-\d+, B-\d+ item codes
