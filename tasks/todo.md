# SI Bid Tool — Frontend Redesign Plan

## Brand Identity (from standardinteriors.com)
- **Primary Navy**: `#134791`
- **Bright Blue**: `#116DFF`
- **Dark Navy**: `#05224B`
- **Orange Accent**: `#FF5F00`
- **Warm Cream**: `#F3EFE5`
- **Light Cream**: `#FDFBF7`
- **Logo**: "STANDARD" bold blue wordmark with underline

## Design Philosophy
- **"Sell it to the boss"** — this needs to look like a polished SaaS product, not an internal tool
- **Clean, spacious, professional** — matches SI's corporate branding
- **Estimator-first UX** — minimal clicks, drag-and-drop uploads, clear progress
- **Dashboard feel** — the boss should see it and think "this is what our competitors don't have"

## Tech Stack
- React 18 + Vite (fresh project, source code this time)
- Tailwind CSS (fast, professional, easy to theme with SI brand colors)
- Lucide React icons
- No component library — custom components for that polished feel

## Architecture — 5 Views

### 1. Dashboard (Job List) — `/`
- Hero header with SI branding (navy gradient + orange accent line)
- Stats bar: total jobs, bids generated this month, total bid value
- Job cards in a grid — each shows project name, GC, date, status badge
- Status badges: Draft → Materials Uploaded → Priced → Bid Generated
- "New Job" button prominent in top-right (orange accent)
- Clean empty state with illustration for first-time use

### 2. Job Detail — `/jobs/:id`
- Horizontal stepper showing progress: Job Info → Materials → Pricing → Bid
- Left sidebar with job info summary (always visible)
- Main content area changes per step

### 3. Step 1: Job Info + RFMS Upload
- Job details form (project name, GC, address, tax rate, etc.)
- Drag-and-drop zone for RFMS Excel file — large, inviting, with animation
- Upload triggers auto-parse → shows parsed materials in a preview table
- Success state: green check, material count summary

### 4. Step 2: Vendor Quotes + Pricing
- Drag-and-drop zone for vendor quote PDFs (multi-file)
- Parsed quotes appear as cards with vendor name, products, prices
- Materials table with editable unit_price column
- Auto-calculates extended costs as prices are entered
- "Match" UI — drag quote prices onto material rows (stretch goal: simple dropdowns)

### 5. Step 3: Review + Generate Bid
- "Calculate" button runs sundry + labor calculations
- Bundle preview — each bundle as a card showing material + sundry + labor + freight breakdown
- Grand total with tax calculation
- "Generate PDF" button — big, orange, satisfying
- PDF preview/download area
- Exclusions list shown for transparency

## File Structure
```
frontend/
  package.json
  vite.config.js
  tailwind.config.js
  postcss.config.js
  index.html
  src/
    main.jsx
    App.jsx
    index.css              (Tailwind base + SI brand tokens)
    api.js                 (API client — all fetch calls)
    components/
      Layout.jsx           (nav, branding, page wrapper)
      Dashboard.jsx        (job list view)
      JobDetail.jsx        (stepper + step content)
      JobForm.jsx          (create/edit job info)
      FileUpload.jsx       (reusable drag-and-drop zone)
      MaterialsTable.jsx   (editable materials grid)
      QuoteUpload.jsx      (vendor quote upload + parsed results)
      BidPreview.jsx       (bundle cards + totals)
      StatusBadge.jsx      (job status indicator)
      StepIndicator.jsx    (horizontal progress stepper)
```

## Implementation Order
- [ ] 1. Scaffold React + Vite + Tailwind project with SI brand theme
- [ ] 2. Build Layout component (nav, branding, routing)
- [ ] 3. Build API client (all 9 endpoints)
- [ ] 4. Build Dashboard — job list with cards, stats, empty state
- [ ] 5. Build JobDetail with stepper + JobForm + FileUpload
- [ ] 6. Build MaterialsTable with editable pricing
- [ ] 7. Build QuoteUpload with parsed results display
- [ ] 8. Build BidPreview with bundle cards + PDF generation
- [ ] 9. Polish — animations, loading states, error handling, responsive
- [ ] 10. Build, test against backend, verify full workflow

---

## 2026-04-23 — CPT Stair Labor Rule Fix

### Problem
For CPT Stairs, we pay the **Installed Area labor** (broadloom rate × area) **PLUS** the **stair add-labor** (per-stair rate × stair count). The current `addStairLabor()` in `ProposalEditor.jsx` REPLACES the installed-area labor with stair labor, under-billing the bid.

### Plan
- [x] Locate stair labor logic → `frontend/src/components/ProposalEditor.jsx` `addStairLabor()` (~line 514) and the bundle regenerate merge (~line 1376)
- [ ] `addStairLabor()`: do not filter out non-stair labor — append stair labor to the full existing labor list
- [ ] Merge logic: drop the `prevHasStairLabor → replace-all` branch; always use fresh labor (installed area) and re-attach any prev `is_stair_labor` / `is_manual` lines
- [ ] Update `tasks/lessons.md` to record the new rule (installed area + stair add-labor, both paid)
- [ ] `cd frontend && npx vite build`
- [ ] `cd si-bid-tool && flyctl deploy`
- [ ] Verify a bundle with CPT stairs shows BOTH the broadloom labor AND stair labor lines

### Review
- Edits landed in [ProposalEditor.jsx](si-bid-tool/frontend/src/components/ProposalEditor.jsx): `addStairLabor()` now appends the stair labor line to the full existing labor list; the regenerate merge path combines fresh auto-labor with prev's `is_stair_labor`/`is_manual` lines (no more replace-all short-circuit).
- Lesson captured in [tasks/lessons.md](si-bid-tool/tasks/lessons.md) under "CPT Stair Labor: Installed Area + Stair Add-Labor (BOTH paid)".
- Build: vite produced `dist/assets/index-BoM3viuz.js` (471 kB); deploy: `deployment-01KPX5VPAWS4H8B9QVDTBTZ1QD` healthy on Fly.io.
- Deployed `si-bid-tool.fly.dev` serves the same `index-BoM3viuz.js`; greps confirm the old `filter(l => l.is_stair_labor)` and `prevHasStairLabor` branch are gone.
- Next CPT-stair bundle generated/edited should bill both the broadloom installed-area labor AND the per-stair add-labor.

---

## 2026-04-23 — JR Alignment Phase 1 + 7 (sundry prices)

### Problem
After comparing Sun Valley Block 2 (JR quote #293113) vs the SI Bid Tool proposal, eight sundry unit prices in `config.py` + `company_rates.sundry_rules` are stale relative to what Josh actually bills in Job Runner. Biggest deltas: cove base adhesive ($12 vs $4.38 — ~$838 overcharge on Sun Valley), grout ($32 vs $32.91), Taylor 2025 primer ($17 vs $15.94). Also the Gypcrete tack strip SKU ($50/carton) was missing from stair sundries.

### Plan
- [x] Update `config.py` `SUNDRY_RULES` for 7 sundry prices (pad_cement, tack_strip, seam_tape, primer, grout, caulk, cove base adhesive).
- [x] Update `STAIR_SUNDRY_KITS` — swap Concrete tack strip for Gypcrete ($50.00) since stairs are always on elevated floors; bump stair seam sealer to $0.1590/LF (reflects $9.54 roll).
- [x] Update `DERIVED_BUNDLE_RULES["crack_isolation"].labor_rate_sf` → $0.27 (Phase 7).
- [x] PUT updated JSON to `company_rates.sundry_rules` on Fly.io (one-off migration script).
- [ ] Deploy `config.py` changes to Fly.io for fresh-install defaults.
- [ ] Regenerate Sun Valley Block 2 and diff totals vs JR.

### Review
- `config.py` edits: `SUNDRY_RULES` pad_cement/tack_strip/seam_tape/primer/grout/caulking/rubber_base-adhesive; `STAIR_SUNDRY_KITS` gypcrete tack strip + seam sealer; `DERIVED_BUNDLE_RULES["crack_isolation"].labor_rate_sf = 0.27`.
- Live `company_rates.sundry_rules` PUT via one-off `_update_live_sundry_rules.py` — 15 price patches applied (pad_cement already at $29.16 in DB; rest updated). Script deleted after use.
- Deploy `deployment-01KPXQ62BAT9F07MKKFKWTW9Z6` healthy on Fly.io.
- All 14 targeted prices verified live via GET `/api/company-rates/sundry_rules`.
- Expected Sun Valley Block 2 delta on regenerate (sundries only): **net -$1,493** (primer savings $1,200, caulking $566; grout +$292, seam tape +$41). Plus TH Stairs tack strip goes to $50/carton gypcrete (≈+$65). Crack isolation labor dropped $0.01/SF (~-$58).
- Lessons captured in [tasks/lessons.md](si-bid-tool/tasks/lessons.md): "Sundry Prices Authoritative per Job Runner" and "Source of Truth: company_rates DB Overrides config.py at Runtime".
- **Next:** Phase 2 — fix material classifier so B-101 and WM-100 stop being `material_type='unknown'` (currently produce $0 labor, $0 sundries). Expected impact ≈+$4.8K on B-101, +$412 on WM-100.

---

## 2026-04-23 — JR Alignment Phase 2 (material classifier fallback)

### Problem
B-101 (Amenity Rubber Base) and WM-100 (Walk-off Mat) on Sun Valley Block 2 both had `material_type="unknown"` because the AI classifier missed them. Unknown types land in the catch-all "individual" bundle with no labor, no sundries — B-101 was $0 labor vs JR's $4,357 labor + $482 adhesive. $4.8K hole per rubber-base bundle, across every future job.

### Plan
- [x] Add `_infer_material_type_fallback(item_code, description)` to `rfms_parser.py` — deterministic rules (B-/WB- → rubber_base, WM- → cpt_tile, RF- → rubber_sheet, VCT- → vct, plus description keywords).
- [x] Wire fallback into `parse_rfms` so it runs when AI returns "unknown" (ai_confidence = 0.5 on fallback).
- [x] Wire `_backfill_unknowns` post-processor into `ai_merge_materials` return paths and `_fallback_merge`.
- [x] Deploy to Fly.io (`deployment-01KPXQ...` — server-only).
- [x] Backfill existing Sun Valley rows via one-off script → PUT `/api/jobs/6/materials` with corrected `material_type` for B-101 and WM-100. Verified via GET.
- [x] Capture lesson in `tasks/lessons.md`.

### Review
- `rfms_parser.py`: [_infer_material_type_fallback](si-bid-tool/server/rfms_parser.py:247) + [_backfill_unknowns](si-bid-tool/server/rfms_parser.py:754); wired into `parse_rfms` inner loop and `ai_merge_materials` return paths.
- Live verify: WM-100 now `cpt_tile`, B-101 now `rubber_base` on Sun Valley Block 2 (job id=6).
- **Action needed from Josh:** click "Regenerate Bundles" on Sun Valley Block 2 in the UI so B-101 and WM-100 pick up labor rules (`rubber_base` → cove base labor $0.70/LF + cove base adhesive $4.38/tube; `cpt_tile` → carpet tile labor $3.85/SY). After regenerate, B-101 bundle should gain labor (~$4,357 at 6,222 LF × $0.70) and adhesive sundries (~$454 at 104 tubes × $4.38). WM-100 gains ~$412 labor at 103 SY × $3.85. Phase 4b will differentiate the $5.00/SY small-tile tier and $4.00/SY walk-off mat rate.
- **Next:** Phase 3 — RF-100 SY→SF conversion (11× qty bump).

---

## 2026-04-23 — JR Alignment Phase 3 (RF-100 qty correction)

### Problem
Sun Valley RF-100 stored as 309.28 SF (≈$4,116 material). JR has 3,400 SF (≈$38,400 material). RFMS reported the value in SY; our parser stored it as SF without converting. 11× qty shortfall on this bundle.

### Plan
- [x] Direct PUT correction on Sun Valley: RF-100 installed_qty 309.28 → 2,783.52 SF, waste_pct 0.20 → order_qty auto-recomputes to 3,340.22 SF; extended_cost now $37,043 (matches JR's $37,400 material within freight rounding).
- [x] Capture lesson "RFMS Rubber Sheet: SY-Stored-As-SF Bug" in `tasks/lessons.md`.
- [ ] Parser-level auto-detection deferred — need more RFMS samples to confirm the unit column is reliably populated. Short-term: per-job manual correction when the qty looks suspiciously small vs the described room.

### Review
- RF-100 corrected on live DB: inst=2783.52, ord=3340.22, ext=$37,043.08.
- On Sun Valley regenerate, RF-100 labor (Commercial Sheet Vinyl over 1/4") jumps from 34 SY × $16 ≈ $549 → ~309 SY × $16 ≈ $4,947. Weld rod labor jumps from 309 LF × $3.21 → scales up too.
- Net expected Sun Valley delta from Phase 3 alone: **+~$30-35K** (material from $4K → $37K, labor from $1.5K → $16K, sundries from $200 → proportional).
- **Next:** Phase 4 — labor rule tiers (sound mat thickness + CPT tile size tier + walk-off mat).

---

## 2026-04-23 — JR Alignment Phase 4a (sound mat thickness tiers)

### Problem
`LABOR_RULES["sound_mat"]` hardcoded "less than 3mm" in its base keywords, so the picker only ever hit the $0.50/SF catalog row. Amenity FT Sound Mat at Sun Valley uses 5mm RST05 — should bill $0.75/SF per JR. Labor catalog already has all three tiers (<3mm $0.50, 4–6mm $0.75, >7mm $1.50).

### Plan
- [x] Add `_parse_mat_thickness_mm(desc)` helper — regex `(\d+(?:\.\d+)?)\s*mm\b` returns float or None.
- [x] Add `_sound_mat_tier_kw(thickness_mm)` — <3 → "less than 3mm"; 3–6 → "4mm to 6mm"; >6 → "more than 7mm".
- [x] Loosen `LABOR_RULES["sound_mat"].base` from `["install sound mat", "less than 3mm"]` to `["install sound mat"]`.
- [x] In `_find_labor_entries`, add a sound_mat branch mirroring the tile-dim filter: filter candidates by `tier_kw` from material description; fall back to "<3mm" if no mm in description.
- [x] Deploy to Fly.io.

### Review
- Changes in [labor_calc.py](si-bid-tool/server/labor_calc.py): `_parse_mat_thickness_mm`, `_sound_mat_tier_kw`, sound_mat filter block added to `_find_labor_entries`; `LABOR_RULES["sound_mat"].base` loosened.
- Expected Sun Valley impact on regenerate: Amenity FT Sound Mat (5,840 SF × 5mm product): $0.50 → $0.75 labor = **+$1,460** for that bundle. Other sound mat bundles are AMB 2000 (no mm in desc) → default "<3mm" → $0.50 (no change).
- **Next:** Phase 4b and 5 both require decisions — see open questions below.

---

## 2026-04-23 — Phases paused for Josh input

## 2026-04-24 — JR Alignment Phase 8 (deep dive on $48K gap)

### Problem
After all earlier fixes, SI Bid Tool was $48K under JR ($2,286,828 vs $2,335,240) AND $30K low on profit. Josh wanted a deep dive identifying every divergence.

### Plan + outcome
- [x] Bump GPM 22% → 22.85% (job.gpm_pct via PUT /api/jobs/6)
- [x] LVT-100 BOH corrected: Evoke Main Street 1,549 SF → Shaw City Center 3,815 SF @ $0.92
- [x] B-101 corrected: $1.00/SF → $1.21, qty 6,222 → 6,225
- [x] Added missing Amenity FT Sound Mat material (SM-FT, 5,840 SF Pliteq RST05 5mm @ $0.83/SF)
- [x] Caulking over-allocation fix: `sundry_calc.py` now applies job-level (`tub_shower_total`/`unit_count`) sundries ONCE per (material_type, sundry_name), to the largest material. Saves ~$8K — was firing on T-202 + T-203 + T-116 (all 231 tubes) and T-200 + T-201 (both 198 tubes).
- [x] RF-100 ES-90 adhesive config: `rubber_sheet` SUNDRY_RULES adhesive now $308.71/pail @ 230 SF coverage (was $95/pail @ 700 SF)
- [x] Premium Sound Mat tier override: bundles whose material description contains "premium" (and no explicit mm) bump to 4-6mm tier ($0.75/SF). Mirrors JR's split rate for the same product.
- [x] RF-100 labor routing: rubber_sheet materials without "vinyl" in description now pick the new "Rolled Rubber over 3mm" catalog row at $2.75/SF
- [x] New labor catalog row: "Rolled Rubber over 3mm" @ $2.75/SF (id=140)
- [x] Bundler bug fix: deletion-handler logic moved INTO `generate_proposal_data` (proposal_bundler.py) so GPM/tax recompute correctly for kept-bundles only. Fixes a double-tax bug introduced when I added deleted_bundles support — previously grand_total = subtotal + tax + textura, but bundle.total_price ALREADY had tax baked in, so tax got counted twice.

### Result
| | Before | After Phase 8 | JR target | Delta |
|---|---|---|---|---|
| Cost | $1,699,305 | $1,705,069 | $1,722,307 | -$17K |
| GPM | 22% | 22.85% | 22.85% | match |
| Subtotal (sell, w/o tax) | $2,178,597 | $2,210,069 | $2,232,332 | -$22K |
| Tax | $103,232 | $102,909 | $102,909 | match |
| Textura | $5,000 | $0 | 0 | — |
| **Grand Total** | **$2,286,828** | **$2,312,978** | **$2,335,241** | **-$22,263 (0.95%)** |
| Profit | $479,291 | ~$505,000 | $510,025 | -$5K |

Within 1% on grand total, within 1% on profit. Big wins:
- RF-100 labor flipped: $4,948 (Commercial Sheet Vinyl) → $7,655 (Rolled Rubber over 3mm)
- Premium Sound Mat: $0.50 → $0.75 = $13,049 (matches JR exactly)
- LVT-100 labor: $1,239 → $3,052 (matches JR)
- Caulking: $14,604 → ~$5,800 (down ~$8.8K, matches JR within $1K)

Remaining gap mostly Josh's intentional rate choices ($7.50 vs $8.00 for 24×48 tiles) plus minor per-bundle deltas not worth chasing.

### Phase 4b — CPT tile size tier + walk-off mat (blocked)
JR's rate pattern is inconsistent: 18×36 tiles bill $3.85/SY, but 24×24 sometimes bill $3.85 (CPT-103) and sometimes $5.00 (CPT-107). Small formats (19.7×19.7, 10.7×19.7) all bill $5.00. Walk-off mat (WM-100, Obex 24×24) bills $4.00/SY.

**Questions for Josh before coding:**
1. What's the actual rule? My best guess: max_edge ≥ 36 → $3.85/SY, else → $5.00/SY. But CPT-103 (24×24) at $3.85 and CPT-108 (18×36 Exchange Tile) at $5.00 break this. Is it product-specific vendor-contract rates rather than a pure size tier?
2. The labor catalog only has `Carpet Tile All Monolithic or Ashlar Pattern` @ $3.85. Before the rule can pick a $5.00 or $4.00 row, we need those rows in the catalog. Should I add them ("Carpet Tile Small Format" @ $5.00 and "Walk Off Mat Install" @ $4.00) or do you want to manage the catalog yourself?

### Phase 5 — Tack strip substrate toggle (concrete vs gypcrete)
Phase 1 already set stair tack strip to $50/carton gypcrete (always the case for TH stairs on elevated floors). For non-stair unit bundles, the concrete price $36.39 is correct on slab-on-grade jobs. A full substrate toggle requires a schema migration (`substrate` column on `job_bundles`) + UI radio button + sundry_calc change. For Sun Valley Block 2 this is not needed (only TH Stairs was gypcrete, and that's handled via STAIR_SUNDRY_KITS). Deferring unless you get a wood-framed multifamily where units also need gypcrete tack strip.
