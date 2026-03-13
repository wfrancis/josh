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
