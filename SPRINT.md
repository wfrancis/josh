# RFQ Feature Redesign Sprint

## Overview
AI-powered vendor-grouped quote requests with tracking. Three phases: Vendor Contacts, AI Quote Requests, Quote Tracker.

---

## Phase 0: Vendor Contacts Management Page
**Status: ✅ COMPLETE**

| Task | Status | Notes |
|------|--------|-------|
| 0A. Backend: `POST /api/vendors` | ✅ Done | create_vendor in models.py |
| 0A. Backend: `DELETE /api/vendors/{id}` | ✅ Done | delete_vendor with cascade |
| 0A. Backend: `POST /api/vendors/suggest-contacts` | ✅ Done | AI suggests contact info for flooring manufacturers |
| 0B. Frontend: `VendorContactsPage.jsx` | ✅ Done | Inline-edit table, expandable price history, AI suggest, delete modal |
| 0B. Route: `/vendor-contacts` in App.jsx | ✅ Done | |
| 0B. Nav: Sidebar item in Layout.jsx | ✅ Done | Building2 icon |
| 0C. API methods in api.js | ✅ Done | createVendor, deleteVendor, suggestVendorContacts |

### Phase 0 Verification Checklist
- [x] Navigate to `/vendor-contacts` from sidebar
- [x] Existing vendors from quote uploads appear in table
- [ ] Add a new vendor with contact info → saves correctly
- [ ] Edit inline → mark dirty → Save → persists
- [ ] Delete a vendor → removed from list
- [ ] Click "AI Suggest" → AI fills in suggestions for vendors with missing contacts
- [ ] Apply a suggestion → contact info populated
- [ ] Expand vendor row → shows price history

---

## Phase 1: AI-Powered Vendor-Grouped Quote Requests
**Status: ✅ COMPLETE**

| Task | Status | Notes |
|------|--------|-------|
| 1A. Backend: `POST /api/jobs/{id}/detect-vendors` | ✅ Done | AI detects manufacturer from material descriptions |
| 1B. Backend: `POST /api/jobs/{id}/generate-quote-text` | ✅ Done | AI writes professional quote request emails |
| 1C. Backend: `POST /api/jobs/{id}/suggest-vendors` | ✅ Done | AI suggests vendors for unassigned materials with reasons |
| 1D. Backend: `quote_requests` table + CRUD | ✅ Done | create, list, update, delete |
| 1E. Frontend: `VendorQuoteFlow.jsx` | ✅ Done | Modal with vendor groups, generate, copy, mark sent |
| 1F. Frontend: `VendorPicker.jsx` | ✅ Done | Autocomplete dropdown with create |
| 1G. Wire into `JobDetail.jsx` | ✅ Done | Replaced QuoteRequest with VendorQuoteFlow modal |

### Phase 1 Bug Fixes
| Bug | Status | Notes |
|-----|--------|-------|
| Sent status lost on modal close/reopen | ✅ Fixed | Loads existing quote_requests on mount |
| AI re-detects vendors every open | ✅ Fixed | Skips if ≥50% materials have vendors |
| X button click target too small | ✅ Fixed | Added padding + hover bg |
| Mark Sent creates "draft" not "sent" | ✅ Fixed | Now passes status='sent' + sent_at to create_quote_request |
| QuoteTracker doesn't refresh after modal close | ✅ Fixed | useEffect depends on job object ref, not just job.id |

### Phase 1 Verification Checklist
- [x] Open job → Click "Request Quotes"
- [x] AI auto-detects vendors from material descriptions
- [x] Materials grouped by vendor with contact info shown
- [x] Click "Generate & Copy" → AI writes professional quote text
- [x] Copy to clipboard works with visual feedback
- [x] "Mark Sent" → quote_request record created, card shows "Sent" status
- [x] Close and reopen modal → sent status persists
- [ ] Unassigned materials show vendor suggestions (1C)

---

## Phase 2: Smart Quote Matching + Tracker
**Status: ✅ COMPLETE**

| Task | Status | Notes |
|------|--------|-------|
| 2A. AI-powered quote matching | ✅ Done | Phase 1: exact item_code → Phase 2: AI fuzzy matching (80%+ confidence) |
| 2B. `QuoteTracker.jsx` component | ✅ Done | Status dashboard: draft/waiting/overdue/received per vendor, follow-up generation |
| 2C. Link uploads to quote requests | ✅ Done | Auto-detects vendor from uploaded PDF, auto-links to open requests |
| 2D. `MaterialsTable.jsx` status badges | ✅ Done | "Requested from X" (blue) / "Quoted by X" (green) badges on unpriced materials |

### Phase 2 Verification Checklist
- [x] Upload vendor quote PDF → AI matches products to materials (Daltile: 22 products, 5 auto-matched)
- [x] System auto-links upload to existing quote request (Daltile + Ann Sacks auto-marked "received")
- [x] QuoteTracker shows status per vendor (waiting/overdue/received)
- [x] MaterialsTable shows "Requested from X" badges
- [ ] "Follow Up" generates AI-written follow-up message

### Phase 2 Bug Fixes
| Bug | Status | Notes |
|-----|--------|-------|
| Vendor name fuzzy match fails on hyphens | ✅ Fixed | Normalize names: strip punctuation before comparing ("Dal-Tile" → "daltile") |

---

## Persona Evaluations

### Round 1 — Pre-Implementation (Baseline)
_Evaluations performed before any redesign work._

| Persona | Grade | Key Feedback |
|---------|-------|-------------|
| Wall Street Trader (JP Morgan Markets) | — | No vendor awareness, no tracking, generic text |
| UX Designer | — | Disconnected flow, no status persistence |
| Veteran Flooring Estimator | — | Can't group by vendor, no quote history |

### Round 2 — Post Phase 0+1 (2026-03-16)
_Evaluations after Phase 0 + Phase 1 completion._

| Persona | Grade | Strength | Weakness |
|---------|-------|----------|----------|
| Wall Street Trader | B+ | AI-grouped vendor detection + one-click email generation is killer. 4 emails in 2 min vs 20+ min manual. Vendor price history in emails shows you're a serious buyer. | Zero visibility post-send. No dashboard showing overdue vendors, no aging clock, no "3 of 6 responded" triage. Excellent at sending, doesn't exist for receiving. |
| UX Designer | A- | Copy → "Copied!" → Mark Sent micro-interaction chain is exactly right. Color system (emerald/amber/violet/red) is purposeful. Tracked request count closes feedback loop. | Unassigned materials path is AI-only — no manual "assign to vendor" control. Dead end if AI suggestions are wrong and user knows the vendor themselves. |
| Veteran Flooring Estimator | B+ | Auto-grouping by manufacturer is the right model — reviewing exceptions vs doing all the work. Price history reference in emails is smart, vendor reps respond faster. | Workflow breaks after "Generate & Copy" — still switching to Outlook, finding thread, pasting, sending. A `mailto:` link pre-populating To/Subject/Body would cut to 90 sec/vendor. |

### Round 3 — Post Phase 2 (2026-03-16)
_Evaluations after all 3 phases complete._

| Persona | Grade | Strength | Weakness |
|---------|-------|----------|----------|
| Wall Street Trader | A- (↑ from B+) | QuoteTracker is a closed-loop state machine — summary badges, 3-day overdue auto-escalation, AI follow-up, auto-link on PDF upload. | No cross-job aggregate view. Can't see "all overdue requests across all bids" without opening each job. Need a top-of-book blotter. |
| UX Designer | A (↑ from A-) | Auto-link on PDF upload closes the loop without manual action. Progressive disclosure is consistent across all 3 phases. Complete end-to-end workflow. | Overdue threshold hardcoded at 3 days with no UI to change it. No notification/badge on job cards when requests go overdue — must open each job to discover. |
| Veteran Flooring Estimator | A- (↑ from B+) | Two-phase AI quote matching (fast item code → AI fuzzy at 80%+ confidence) + auto-link eliminates 10 min/vendor of manual Excel work. Materials table "Requested/Quoted by X" badges give instant status. | Email button only appears if vendor has email in contacts DB. No fallback prompt to add email on the spot. Follow-up messages are copy-only (no mailto). AI Suggest skips vendors with phone but no email. |

### Grade Progression
| Persona | Round 2 | Round 3 | Δ |
|---------|---------|---------|---|
| Wall Street Trader | B+ | A- | ↑ |
| UX Designer | A- | A | ↑ |
| Veteran Flooring Estimator | B+ | A- | ↑ |
