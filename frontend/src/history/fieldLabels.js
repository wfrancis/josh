// Plain-English names for everything the history shows: actions, parts of a
// bid, field names and values. Anything not listed here falls back to its key
// made readable ("labor_rate_lf" -> "Labor rate LF"), so new fields still show.

import { formatDay, formatMoney, formatTime, formatWhen } from '../bidTracker'

// ── Keys made readable ──────────────────────────────────────────────────────
const ACRONYMS = new Set(['gpm', 'rfms', 'pdf', 'sf', 'sy', 'lf', 'id', 'po', 'gc', 'ai', 'csv', 'url', 'zip', 'pin', 'sku', 'lvt', 'vct', 'smtp', 'imap'])

export function humanize(key) {
  const text = String(key ?? '')
    .replace(/^_+/, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_\-.]+/g, ' ')
    .trim()
    .toLowerCase()
  if (!text) return ''
  const words = text.split(/\s+/).map(word => {
    if (word === 'pct') return '%'
    if (ACRONYMS.has(word)) return word.toUpperCase()
    return word
  })
  const joined = words.join(' ')
  return joined.charAt(0).toUpperCase() + joined.slice(1)
}

// ── Field names (the last part of a change's path) ──────────────────────────
const FIELD_LABELS = {
  // Project info
  project_name: 'Project name',
  gc_name: 'General contractor',
  address: 'Address',
  city: 'City',
  state: 'State',
  zip: 'ZIP',
  tax_rate: 'Tax rate',
  gpm_pct: 'GPM',
  markup_pct: 'Markup',
  unit_count: 'Unit count',
  tub_shower_count: 'Tubs/showers',
  salesperson: 'Salesperson',
  salesperson2: 'Sales person 2',
  architect: 'Architect',
  designer: 'Designer',
  textura_fee: 'Textura fee',
  notes: 'Notes',
  exclusions: 'Exclusions',
  slug: 'Web address',
  quote_number: 'Quote #',
  customer_po: 'Customer PO',
  contract_number: 'Contract #',
  customer_account: 'Customer acct #',
  customer_address: 'Customer address',
  customer_city: 'Customer city',
  customer_state: 'Customer state',
  customer_zip: 'Customer ZIP',
  customer_phone: 'Customer phone',
  customer_fax: 'Customer fax',
  site_phone: 'Job site phone',
  site_contact: 'Job site contact',
  // Bid tracking
  bid_status: 'Bid status',
  bid_due_date: 'Due date',
  bid_due_time: 'Due time',
  estimator: 'Estimator',
  next_follow_up_date: 'Next follow-up',
  won_lost_at: 'Won/lost date',
  won_lost_reason: 'Won/lost reason',
  awarded_amount: 'Awarded amount',
  // Deleting and restoring a bid
  deleted_at: 'Deleted on',
  deleted_by: 'Deleted by',
  delete_reason: 'Reason for deleting',
  // Takeoff lines
  item_code: 'Item code',
  description: 'Description',
  material_type: 'Material type',
  installed_qty: 'Installed qty',
  unit: 'Unit',
  waste_pct: 'Waste',
  order_qty: 'Order qty',
  vendor: 'Vendor',
  unit_price: 'Unit price',
  extended_cost: 'Extended cost',
  fixture_count: 'Fixture count',
  labor_rate_lf: 'Labor rate per LF',
  labor_catalog: 'Labor catalog',
  ai_confidence: 'AI confidence',
  quote_status: 'Quote status',
  price_source: 'Price source',
  quote_source_hash: 'Quote file fingerprint',
  quote_file_name: 'Quote file',
  freight_per_unit: 'Freight per unit',
  freight_source: 'Freight source',
  tack_strip_lf: 'Tack strip (LF)',
  seam_tape_lf: 'Seam tape (LF)',
  pad_sy: 'Pad (SY)',
  area_type: 'Area',
  is_mosaic: 'Mosaic',
  is_penny_hex: 'Penny hex',
  crack_isolation_sf: 'Crack isolation (SF)',
  weld_rod_lf: 'Weld rod (LF)',
  // Sundry and labor lines
  sundry_name: 'Sundry',
  labor_description: 'Labor',
  qty: 'Qty',
  rate: 'Rate',
  freight_cost: 'Freight',
  material_id: 'Material',
  line_key: 'Line',
  // Proposal
  bundles: 'Bundles',
  bundle_name: 'Bundle name',
  description_text: 'Description',
  total_price: 'Total price',
  price_override: 'Price override',
  freight_override: 'Freight override',
  stair_count: 'Stair count',
  stair_labor_type: 'Stair labor type',
  labor_items: 'Labor lines',
  sundry_items: 'Sundry lines',
  materials: 'Materials',
  labor_cost: 'Labor cost',
  sundry_cost: 'Sundry cost',
  material_cost: 'Material cost',
  bundle_cost: 'Bundle cost',
  total_cost: 'Total cost',
  gpm_material_adder: 'GPM on materials',
  gpm_labor_adder: 'GPM on labor',
  gpm_adder: 'GPM added',
  tax_amount: 'Tax',
  taxable: 'Taxable amount',
  subtotal: 'Subtotal',
  grand_total: 'Grand total',
  gpm_profit: 'GPM profit',
  gpm_labor: 'GPM on labor',
  gpm_material: 'GPM on materials',
  manual_adjustment: 'Manual adjustment',
  textura_amount: 'Textura amount',
  terms: 'Terms & conditions',
  deleted_bundles: 'Removed bundles',
  deleted_bundle_reasons: 'Why bundles were removed',
  deleted_material_codes: 'Removed materials',
  deleted_material_reasons: 'Why materials were removed',
  deleted_labor_keys: 'Removed labor lines',
  deleted_labor_reasons: 'Why labor lines were removed',
  is_derived: 'Worked out automatically',
  pdf: 'PDF',
  _order: 'Order',
  // People, settings, vendors, comments
  display_name: 'Name',
  username: 'Username',
  is_admin: 'Admin',
  active: 'Active',
  pin: 'PIN',
  openai_model: 'AI model',
  multi_pass_count: 'AI passes',
  vendor_quote_test_mode: 'Test mode',
  name: 'Name',
  email: 'Email',
  phone: 'Phone',
  contact_name: 'Contact',
  text: 'Comment',
  product_name: 'Product',
  file_name: 'File',
  lead_time: 'Lead time',
  freight: 'Freight',
}

// Collections of rows: the path segment after one of these is a row id.
const COLLECTIONS = {
  materials: 'Material',
  sundries: 'Sundry line',
  labor: 'Labor line',
  bundles: 'Bundle',
  labor_items: 'Labor line',
  sundry_items: 'Sundry line',
  quotes: 'Quote',
  users: 'Person',
  vendors: 'Vendor',
  contacts: 'Contact',
  rows: 'Row',
  items: 'Line',
  entries: 'Entry',
  rules: 'Rule',
  notes: 'Note',
  terms: 'Term',
}

// Top-level parts of a bid, for "Proposal · Notes"-style breadcrumbs.
const SECTION_LABELS = {
  materials: 'Materials',
  sundries: 'Sundries',
  labor: 'Labor',
  bundles: 'Bid bundles',
  proposal: 'Proposal',
  bid: 'Generated bid',
  exclusions: 'Exclusions',
  totals: 'Totals',
  computed: 'Worked out automatically',
}

// Keys that name a row, best first.
const ROW_LABEL_KEYS = ['item_code', 'bundle_name', 'sundry_name', 'labor_description', 'product_name', 'display_name', 'name', 'username', 'title', 'label', 'description']

export function fieldLabel(key) {
  if (key === null || key === undefined || key === '') return ''
  const text = String(key)
  if (FIELD_LABELS[text]) return FIELD_LABELS[text]
  // Names used as keys ("Bath LVT") stay as they are; code keys are made readable.
  return /^[A-Za-z0-9_]+$/.test(text) && !/^[A-Z]/.test(text) ? humanize(text) : text
}

export function entityLabel(entityType) {
  return ENTITY_LABELS[entityType] || humanize(entityType) || 'Item'
}

// JSON-pointer path ("/materials/12/unit_price") -> its parts, unescaped.
export function splitPath(path) {
  if (!path) return []
  return String(path).split('/').slice(1).map(part => part.replace(/~1/g, '/').replace(/~0/g, '~'))
}

function looksLikeRowId(part, parent) {
  if (part === '_order') return false
  if (parent && Object.prototype.hasOwnProperty.call(COLLECTIONS, parent)) return true
  // Positions ("3") and made-up ids with a digit in them ("m_123", "b_9f2c").
  return /^\d+$/.test(part) || /^[a-z]{1,4}_(?=[0-9a-z]*\d)[0-9a-z]{3,}$/i.test(part)
}

// The parts of a path, each marked as a field or a row id.
export function describePath(path) {
  const parts = splitPath(path)
  const out = []
  parts.forEach((part, index) => {
    const parent = parts[index - 1]
    if (index > 0 && looksLikeRowId(part, parent)) {
      out.push({ kind: 'row', key: part, collection: parent, rowPath: '/' + parts.slice(0, index + 1).join('/') })
    } else {
      out.push({ kind: 'field', key: part })
    }
  })
  return out
}

// Just the field: "/materials/12/unit_price" -> "Unit price",
// "/proposal/bundles/b_9f2c/description_text" -> "Description", "/notes" -> "Notes".
export function fieldLabelForPath(path) {
  const parts = describePath(path)
  if (parts.length === 0) return ''
  const last = parts[parts.length - 1]
  if (last.kind === 'row') return COLLECTIONS[last.collection] || 'Row'
  if (last.key === '_order') {
    const parent = parts[parts.length - 2]
    return parent ? `Order of ${fieldLabel(parent.key).toLowerCase()}` : 'Order'
  }
  // Proposal notes/terms/exclusions read better with their section.
  if (parts.length === 2 && parts[0].key === 'proposal' && ['notes', 'exclusions'].includes(last.key)) {
    return `Proposal ${fieldLabel(last.key).toLowerCase()}`
  }
  return fieldLabel(last.key)
}

// ── Row names ───────────────────────────────────────────────────────────────
export function rowName(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return ''
  for (const key of ROW_LABEL_KEYS) {
    const value = row[key]
    if (typeof value === 'string' && value.trim()) return clip(value.trim(), 60)
  }
  return ''
}

// A readable name for the row at rowPath ("/materials/12"), from anything in
// the entry that says what that row is. Empty when nothing does.
export function rowNameFor(item, rowPath) {
  if (!item || !rowPath) return ''
  const extra = item.extra || {}
  const fromExtra = extra.row_labels?.[rowPath] || extra.labels?.[rowPath]
  if (typeof fromExtra === 'string' && fromExtra.trim()) return fromExtra.trim()
  const changes = Array.isArray(item.changes) ? item.changes : []
  // A whole row added or removed carries its values.
  for (const change of changes) {
    if (change.path === rowPath) {
      const name = rowName(change.after) || rowName(change.before)
      if (name) return name
    }
  }
  // A change to the row's naming field (e.g. its item code).
  for (const key of ROW_LABEL_KEYS) {
    const change = changes.find(c => c.path === `${rowPath}/${key}`)
    if (change) {
      const value = typeof change.before === 'string' && change.before.trim() ? change.before : change.after
      if (typeof value === 'string' && value.trim()) return clip(value.trim(), 60)
    }
  }
  return ''
}

// Where a change is, for its label: "CPT-200 · Unit price",
// "Bundle · Description", "Proposal · Tax rate", "Notes".
export function pathLabel(path, item) {
  const parts = describePath(path)
  if (parts.length === 0) return item?.field_path ? fieldLabelForPath(item.field_path) : 'Details'
  const last = parts[parts.length - 1]
  const rows = parts.filter(part => part.kind === 'row')
  const rowCrumbs = rows.map(row => rowNameFor(item, row.rowPath) || COLLECTIONS[row.collection] || 'Row')
  // A whole row added or removed.
  if (last.kind === 'row') return rowCrumbs.join(' · ')
  const field = fieldLabelForPath(path)
  if (rows.length === 0) {
    if (parts.length === 1 || last.key === '_order') return field
    const section = SECTION_LABELS[parts[0].key] || fieldLabel(parts[0].key)
    const middle = parts.slice(1, -1).map(part => fieldLabel(part.key))
    const crumbs = field.toLowerCase().startsWith(section.toLowerCase()) ? [...middle, field] : [section, ...middle, field]
    return crumbs.filter(Boolean).join(' · ')
  }
  // Fields between the last row and the changed field ("Bath LVT · Labor lines · Rate").
  const lastRowIndex = parts.lastIndexOf(rows[rows.length - 1])
  const between = parts.slice(lastRowIndex + 1, -1)
    .filter((part, index, list) => !(list[index + 1] && list[index + 1].kind === 'row'))
    .map(part => fieldLabel(part.key))
  return [...rowCrumbs, ...between, field].filter(Boolean).join(' · ')
}

// The row an entry's field path points into, if any: "CPT-200" for
// "/materials/12/unit_price".
export function entryTarget(item) {
  const parts = describePath(item?.field_path)
  const rows = parts.filter(part => part.kind === 'row')
  if (rows.length === 0) return ''
  const row = rows[rows.length - 1]
  const name = rowNameFor(item, row.rowPath)
  if (name) return name
  return 'a ' + (COLLECTIONS[row.collection] || 'row').toLowerCase()
}

// ── Values ──────────────────────────────────────────────────────────────────
const PERCENT_FRACTION_KEYS = new Set(['tax_rate', 'gpm_pct', 'waste_pct', 'markup_pct', 'ai_confidence', 'textura_rate'])
const MONEY_KEYS = new Set([
  'unit_price', 'extended_cost', 'total_price', 'price_override', 'freight_override', 'labor_cost',
  'sundry_cost', 'material_cost', 'freight_cost', 'freight_per_unit', 'gpm_material_adder',
  'gpm_labor_adder', 'gpm_adder', 'tax_amount', 'taxable', 'subtotal', 'grand_total', 'gpm_profit',
  'gpm_labor', 'gpm_material', 'manual_adjustment', 'textura_amount', 'awarded_amount', 'rate',
  'labor_rate_lf', 'bundle_cost', 'total_cost', 'price', 'cost', 'amount', 'freight', 'bid_total',
  'quote_price', 'accepted_price',
])
const QUANTITY_KEYS = new Set([
  'qty', 'installed_qty', 'order_qty', 'unit_count', 'stair_count', 'fixture_count', 'tub_shower_count',
  'tack_strip_lf', 'seam_tape_lf', 'pad_sy', 'crack_isolation_sf', 'weld_rod_lf', 'multi_pass_count',
])
const YES_NO_KEYS = new Set(['textura_fee', 'is_mosaic', 'is_penny_hex', 'is_admin', 'active', 'is_derived', 'vendor_quote_test_mode', 'taxable_flag'])
// Longer free text: shown as a word-by-word before/after.
const TEXT_KEYS = new Set(['description', 'description_text', 'notes', 'won_lost_reason', 'text', 'site_contact', 'labor_description', 'summary', 'reason', 'message', 'body', 'request_text', 'response_notes'])

export function valueKind(path) {
  const parts = describePath(path).filter(part => part.kind === 'field')
  const key = parts.length ? parts[parts.length - 1].key : ''
  if (PERCENT_FRACTION_KEYS.has(key) || /_pct$/.test(key)) return 'percent'
  if (YES_NO_KEYS.has(key) || /^is_/.test(key)) return 'yesno'
  if (MONEY_KEYS.has(key) || /(_price|_cost|_amount|_total|_adder)$/.test(key)) return 'money'
  if (QUANTITY_KEYS.has(key) || /(_qty|_count|_lf|_sy|_sf)$/.test(key)) return 'quantity'
  if (key === 'bid_due_time' || /_time$/.test(key)) return 'time'
  if (/(_date|_at)$/.test(key)) return 'date'
  if (TEXT_KEYS.has(key)) return 'text'
  return 'plain'
}

export function isBlank(value) {
  return value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)
}

export function isRedacted(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value) && value.redacted === true
}

export function isTruncated(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value) && value.truncated === true
}

function clip(text, max) {
  const value = String(text)
  return value.length > max ? value.slice(0, max - 1).trimEnd() + '…' : value
}

function formatNumber(value, maxDecimals = 2) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: maxDecimals }).format(value)
}

function formatPercent(value) {
  // Stored as a fraction (0.0915 = 9.15%). Older values may already be whole percents.
  const pct = Math.abs(value) > 1 ? value : value * 100
  return `${formatNumber(pct, 2)}%`
}

function formatDateValue(value) {
  const text = String(value)
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return formatDay(text)
  const when = formatWhen(text)
  return when || text
}

// One value as text for the history ("$24.50", "9.15%", "Sep 24", "Yes").
export function formatValue(value, path) {
  if (isRedacted(value)) return 'Hidden'
  if (isTruncated(value)) return `${clip(value.head || '', 200)} (too long to show in full)`
  if (isBlank(value)) return '(blank)'
  const kind = valueKind(path)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (kind === 'yesno' && (value === 0 || value === 1 || value === '0' || value === '1')) {
    return Number(value) === 1 ? 'Yes' : 'No'
  }
  const numeric = typeof value === 'number' ? value
    : (typeof value === 'string' && value.trim() !== '' && !Number.isNaN(Number(value)) && kind !== 'plain' && kind !== 'text' ? Number(value) : null)
  if (numeric !== null && Number.isFinite(numeric)) {
    if (kind === 'money') return formatMoney(numeric)
    if (kind === 'percent') return formatPercent(numeric)
    if (kind === 'quantity') return formatNumber(numeric, 2)
    return formatNumber(numeric, 4)
  }
  if (typeof value === 'string') {
    if (kind === 'date') return formatDateValue(value)
    if (kind === 'time') return formatTime(value) || value
    return value
  }
  if (Array.isArray(value)) {
    if (value.every(entry => typeof entry !== 'object' || entry === null)) {
      return clip(value.map(entry => (isBlank(entry) ? '(blank)' : String(entry))).join('; '), 240)
    }
    const names = value.map(rowName).filter(Boolean)
    const count = `${value.length} ${value.length === 1 ? 'row' : 'rows'}`
    return names.length ? `${count}: ${clip(names.slice(0, 4).join(', '), 160)}${names.length > 4 ? ', …' : ''}` : count
  }
  if (typeof value === 'object') return summarizeRow(value)
  return String(value)
}

// A row in a few words: "CPT-200 · 1,200 SY · $24.50". omitName: leave the
// name out when the label next to it already shows it.
export function summarizeRow(row, omitName = '') {
  if (!row || typeof row !== 'object') return formatValue(row)
  const name = rowName(row)
  const bits = []
  if (name && name !== omitName) bits.push(name)
  if (row.description && row.description !== name && typeof row.description === 'string') bits.push(clip(row.description, 60))
  const qty = row.installed_qty ?? row.qty
  if (typeof qty === 'number' && qty) bits.push(`${formatNumber(qty, 2)}${row.unit ? ' ' + row.unit : ''}`)
  const price = row.unit_price ?? row.rate
  if (typeof price === 'number' && price) bits.push(formatMoney(price))
  if (typeof row.total_price === 'number' && row.total_price) bits.push(`total ${formatMoney(row.total_price)}`)
  if (bits.length) return bits.join(' · ')
  if (name) return name
  // Nothing recognisable: the first few simple values.
  const simple = Object.entries(row)
    .filter(([key, value]) => !key.startsWith('_') && value !== null && value !== '' && typeof value !== 'object')
    .slice(0, 3)
    .map(([key, value]) => `${fieldLabel(key)}: ${formatValue(value, '/' + key)}`)
  return simple.length ? simple.join(' · ') : `${Object.keys(row).length} values`
}

// Should this before/after be shown as a word-by-word text diff?
export function isTextChange(change) {
  const { before, after } = change || {}
  const bothText = (typeof before === 'string' || isBlank(before)) && (typeof after === 'string' || isBlank(after))
  if (!bothText || (isBlank(before) && isBlank(after))) return false
  if (valueKind(change.path) === 'text') return true
  const longest = Math.max(String(before || '').length, String(after || '').length)
  return longest > 40 || /\n/.test(String(before || '') + String(after || ''))
}

// ── Actions ─────────────────────────────────────────────────────────────────
const ACTION_LABELS = {
  'job.create': 'Created the bid',
  'job.update': 'Updated project info',
  'job.notes': 'Updated notes',
  'job.notes.update': 'Updated notes',
  'job.exclusions.update': 'Updated exclusions',
  'job.delete': 'Deleted the bid',
  'job.restore': 'Restored the bid',
  'job.duplicate': 'Duplicated the bid',
  'job.bulk_delete': 'Deleted bids',
  'materials.update': 'Updated materials',
  'materials.delete': 'Removed materials',
  'materials.recount_transitions': 'Recounted transition sticks',
  'materials.price_decision': 'Decided on a vendor price',
  'materials.ai_estimate': 'Asked AI to estimate a price',
  'materials.detect_vendors': 'Asked AI to find vendors',
  'rfms.upload': 'Uploaded the RFMS takeoff',
  'rfms.lines_removed': 'Removed takeoff lines',
  'quotes.upload': 'Uploaded vendor quotes',
  'quotes.clear': 'Cleared vendor quotes',
  'quotes.update': 'Updated a vendor quote',
  'quotes.auto_import': 'Imported a vendor quote from email',
  'quote_request.create': 'Made a quote request',
  'quote_request.update': 'Updated a quote request',
  'quote_request.delete': 'Deleted a quote request',
  'quote_request.email': 'Emailed a quote request',
  'bid.calculate': 'Calculated the bid',
  'bid.generate': 'Generated the bid',
  'bid.regenerate': 'Regenerated the bid',
  'bid.clear': 'Cleared the bid',
  'bid.sent': 'Marked the bid sent',
  'bid.won': 'Marked the bid won',
  'bid.lost': 'Marked the bid lost',
  'bid.follow_up': 'Logged a follow-up',
  'bid.note': 'Added a bid note',
  'bid.status': 'Changed the bid status',
  'bid.tracking.update': 'Updated bid tracking',
  'bid.pdf': 'Made the bid PDF',
  'proposal.edit': 'Edited the proposal',
  'proposal.save': 'Saved the proposal',
  'proposal.update': 'Updated the proposal',
  'proposal.generate': 'Generated the proposal',
  'proposal.regenerate': 'Regenerated the proposal',
  'proposal.restore': 'Restored an earlier proposal',
  'proposal.version_label': 'Named a proposal version',
  'proposal.pdf': 'Made the proposal PDF',
  'proposal.audit_refresh': "Rechecked the bid's numbers with the latest version of the tool",
  'comment.add': 'Added a comment',
  'golden.capture': 'Saved a reproducibility baseline',
  'golden.replay': 'Ran a reproducibility check',
  'auth.login': 'Logged in',
  'auth.login_failed': 'Tried to log in with a wrong PIN',
  'auth.failed_login': 'Tried to log in with a wrong PIN',
  'auth.lockout': 'Was locked out after too many wrong PINs',
  'auth.logout': 'Logged out',
  'auth.login_throttled': 'Login turned away after too many wrong tries',
  'user.create': 'Added a person',
  'user.update': 'Updated a person',
  'user.remove': 'Removed a person',
  'user.restore': 'Restored a person',
  'user.reset_pin': 'Gave someone a new PIN',
  'user.rename': 'Renamed a person',
  'user.make_admin': 'Made someone an admin',
  'user.remove_admin': 'Took admin rights away',
  'user.startup_admin': 'Set up the admin login at startup',
  'settings.update': 'Changed settings',
  'company_rates.update': 'Changed company rates',
  'company_rates.seed': 'Added default company rates',
  'notification.read': 'Read a notification',
  'labor_catalog.create': 'Added a labor catalog entry',
  'labor_catalog.update': 'Changed a labor catalog entry',
  'labor_catalog.delete': 'Removed a labor catalog entry',
  'price_list.create': 'Added a price list entry',
  'price_list.update': 'Changed a price list entry',
  'price_list.delete': 'Removed a price list entry',
  'vendor.merge': 'Merged vendors',
  'rules.seed': 'Added the built-in estimating rules',
  'route.unaudited': "Made a change the history didn't capture",
  unaudited_write: "Made a change the history didn't capture",
}

const ACTION_VERBS = {
  create: 'Added', add: 'Added', update: 'Updated', edit: 'Edited', save: 'Saved', delete: 'Deleted',
  remove: 'Removed', restore: 'Restored', upload: 'Uploaded', import: 'Imported', clear: 'Cleared',
  rollback: 'Rolled back', archive: 'Archived', generate: 'Generated', regenerate: 'Regenerated',
  calculate: 'Calculated', send: 'Sent', sent: 'Sent', email: 'Emailed', reset: 'Reset', rename: 'Renamed',
  read: 'Read', login: 'Logged in', logout: 'Logged out', capture: 'Captured', replay: 'Replayed',
  replace: 'Replaced', move: 'Moved', approve: 'Approved', reject: 'Rejected', pdf: 'Made a PDF of',
}

const ACTION_NOUNS = {
  job: 'the bid', materials: 'materials', material: 'a material', proposal: 'the proposal', bid: 'the bid',
  rfms: 'the RFMS takeoff', quotes: 'vendor quotes', quote: 'a vendor quote', quote_request: 'a quote request',
  comment: 'a comment', user: 'a person', settings: 'settings', vendor: 'a vendor', vendors: 'vendors',
  vendor_contact: 'a vendor contact', price_list: 'the price list', labor_catalog: 'the labor catalog',
  price_book: 'the price book', company_rates: 'company rates', sundry_rates: 'sundry rates', rule: 'an estimating rule',
  rules: 'estimating rules', ruleset: 'the rule set', notification: 'a notification', vendor_prices: 'vendor prices',
  golden: 'a reproducibility baseline', bundle: 'a bundle', auth: 'login',
}

// "materials.update" -> "Updated materials"
export function actionLabel(action) {
  if (!action) return 'Made a change'
  if (ACTION_LABELS[action]) return ACTION_LABELS[action]
  const parts = String(action).split('.')
  if (parts[0] === 'activity') return humanize(parts.slice(1).join(' ')) || 'Made a change'
  const verbKey = parts[parts.length - 1]
  const verb = ACTION_VERBS[verbKey]
  const nounKey = parts.length > 1 ? parts.slice(0, -1).join('.') : ''
  const noun = ACTION_NOUNS[nounKey] || ACTION_NOUNS[parts[0]] || (nounKey ? humanize(nounKey).toLowerCase() : '')
  if (verb && noun) return `${verb} ${noun}`
  if (verb) return verb
  return humanize(parts.join(' ')) || 'Made a change'
}

// ── Kinds of change (filters and colours) ───────────────────────────────────
// actions: sent to the server as the "action" filter; "bid" also matches
// "bid.sent", "bid.won" and so on.
export const HISTORY_TYPES = [
  { key: 'project', label: 'Project info', actions: ['job'], dot: 'bg-amber-400' },
  { key: 'takeoff', label: 'Takeoff', actions: ['rfms', 'materials'], dot: 'bg-blue-400' },
  { key: 'pricing', label: 'Pricing', actions: ['quotes', 'quote_request', 'materials.price_decision', 'materials.ai_estimate', 'materials.detect_vendors', 'bid.calculate', 'pricing'], dot: 'bg-violet-400' },
  { key: 'proposal', label: 'Proposal', actions: ['proposal', 'bundle', 'bid.generate', 'bid.regenerate', 'bid.clear'], dot: 'bg-emerald-400' },
  { key: 'tracking', label: 'Bid tracking', actions: ['bid.sent', 'bid.won', 'bid.lost', 'bid.follow_up', 'bid.note', 'bid.status', 'bid.tracking'], dot: 'bg-cyan-400' },
  { key: 'files', label: 'Files', actions: ['rfms.upload', 'quotes.upload', 'quotes.auto_import', 'file', 'upload'], dot: 'bg-sky-400' },
  { key: 'pdfs', label: 'PDFs', actions: ['proposal.pdf', 'bid.pdf', 'pdf'], dot: 'bg-rose-400' },
  { key: 'comments', label: 'Comments', actions: ['comment'], dot: 'bg-gray-300' },
]

// Company-wide areas for the Audit page (on top of the bid types above).
export const AUDIT_AREAS = [
  ...HISTORY_TYPES,
  { key: 'logins', label: 'Logins', actions: ['auth'], dot: 'bg-gray-400' },
  { key: 'people', label: 'People', actions: ['user'], dot: 'bg-orange-400' },
  { key: 'settings', label: 'Settings', actions: ['settings'], dot: 'bg-gray-400' },
  { key: 'vendors', label: 'Vendors', actions: ['vendor', 'vendor_contact', 'vendor_prices'], dot: 'bg-teal-400' },
  { key: 'pricing_setup', label: 'Pricing setup', actions: ['price_list', 'labor_catalog', 'price_book', 'company_rates', 'sundry_rates'], dot: 'bg-violet-300' },
  { key: 'rules', label: 'Estimating rules', actions: ['rule', 'rules', 'ruleset'], dot: 'bg-lime-400' },
]

function prefixMatches(action, prefix) {
  return action === prefix || action.startsWith(prefix + '.')
}

// The best-fitting kind for an entry (longest matching action prefix).
export function entryKind(item) {
  const action = String(item?.action || '')
  let best = null
  let bestLength = -1
  for (const area of AUDIT_AREAS) {
    for (const prefix of area.actions) {
      if (prefixMatches(action, prefix) && prefix.length > bestLength) {
        best = area
        bestLength = prefix.length
      }
    }
  }
  return best
}

export function areaForActionFilter(actionFilter) {
  if (!actionFilter) return null
  return AUDIT_AREAS.find(area => area.actions.join(',') === actionFilter) || null
}

// ── Entity types ────────────────────────────────────────────────────────────
const ENTITY_LABELS = {
  job: 'Bid',
  material: 'Material',
  materials: 'Materials',
  proposal: 'Proposal',
  bundle: 'Bundle',
  sundry: 'Sundry line',
  labor: 'Labor line',
  quote: 'Vendor quote',
  quote_request: 'Quote request',
  comment: 'Comment',
  user: 'Person',
  session: 'Login',
  auth: 'Login',
  settings: 'Settings',
  vendor: 'Vendor',
  vendor_contact: 'Vendor contact',
  vendor_price: 'Vendor price',
  price_list: 'Price list',
  labor_catalog: 'Labor catalog',
  price_book: 'Price book',
  company_rates: 'Company rates',
  sundry_rates: 'Sundry rates',
  rule: 'Estimating rule',
  ruleset: 'Rule set',
  notification: 'Notification',
  golden: 'Reproducibility baseline',
  route: 'Unrecorded change',
}

// Shown in the Audit page's "Kind of thing" list even before any turn up.
export const KNOWN_ENTITY_TYPES = ['job', 'user', 'session', 'settings', 'vendor', 'price_list', 'labor_catalog', 'price_book', 'company_rates', 'rule', 'quote_request', 'notification']

// ── Who and where from ──────────────────────────────────────────────────────
const SOURCE_LABELS = {
  ws: 'live editing',
  startup: 'server startup',
  inbox_monitor: 'the vendor inbox monitor',
  sim_watcher: 'the test-mode simulator',
  migration: 'a database update',
  legacy_import: 'the old activity log',
  system: 'the system',
}

// '' for ordinary web requests; otherwise where the change came from.
export function sourceLabel(source) {
  if (!source || source === 'http') return ''
  return SOURCE_LABELS[source] || humanize(source).toLowerCase()
}

// Everyone on an entry, main editor first, no repeats: [{ username, name, editCount }].
export function entryPeople(item) {
  const keyOf = (username, name) => (username || name || '').toLowerCase()
  const byKey = new Map()
  for (const actor of item?.actors || []) {
    const key = keyOf(actor.username, actor.display_name)
    if (!key || byKey.has(key)) continue
    byKey.set(key, { username: actor.username || null, name: actor.display_name || actor.username || 'Someone', editCount: Number(actor.edit_count) || 0 })
  }
  const mainKey = keyOf(item?.actor_username, item?.actor_display)
  const people = []
  if (mainKey) {
    people.push(byKey.get(mainKey) || { username: item.actor_username || null, name: item.actor_display || item.actor_username, editCount: 0 })
    byKey.delete(mainKey)
  }
  return [...people, ...byKey.values()]
}

// "Josh", "Josh + Bob", "Josh, Bob + 2 others", "System".
export function peopleText(item) {
  if (item?.actor_kind === 'system' && !item?.actor_username) return 'System'
  if (item?.actor_kind === 'anonymous' && !item?.actor_username) return 'Someone not logged in'
  const names = entryPeople(item).map(person => person.name)
  if (names.length === 0) return 'Someone'
  if (names.length === 1) return names[0]
  if (names.length === 2) return `${names[0]} + ${names[1]}`
  const others = names.length - 2
  return `${names[0]}, ${names[1]} + ${others} other${others === 1 ? '' : 's'}`
}

// Past-tense verbs a summary can start with; they read as "Josh changed …".
const SUMMARY_VERBS = new Set([
  'changed', 'added', 'removed', 'updated', 'uploaded', 'edited', 'deleted', 'set', 'cleared', 'generated',
  'regenerated', 'marked', 'logged', 'created', 'renamed', 'restored', 'made', 'took', 'gave', 'sent', 'recounted',
  'reset', 'imported', 'replaced', 'moved', 'ran', 'captured', 'calculated', 'printed', 'saved', 'turned',
  'combined', 'split', 'accepted', 'rejected', 'kept', 'used', 'duplicated', 'approved', 'archived', 'rolled',
  'recalculated', 'emailed', 'requested', 'estimated', 'read', 'tried', 'was', 'asked', 'decided', 'priced',
  'typed', 'unmarked', 'reordered', 'excluded', 'included', 'linked', 'relinked', 'reviewed', 'copied',
])

function sentenceAfterName(text) {
  const value = String(text || '').trim()
  if (!value) return ''
  const firstWord = value.split(/\s+/)[0]
  if (SUMMARY_VERBS.has(firstWord.toLowerCase()) && firstWord !== firstWord.toUpperCase()) {
    return value.charAt(0).toLowerCase() + value.slice(1)
  }
  return ''
}

export function changeCount(item) {
  const count = Number(item?.edit_count) || 0
  if (count > 1) return count
  return Array.isArray(item?.changes) ? item.changes.filter(change => !change.derived).length : 0
}

export function isGroupedEdit(item) {
  return (Number(item?.edit_count) || 0) > 1 || (item?.actors?.length || 0) > 1
}

// Raw field keys in a server summary ("Updated city, tax_rate") -> plain words.
export function plainSummary(summary) {
  return String(summary || '').replace(/\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g, (key) => {
    const label = FIELD_LABELS[key]
    if (!label) return key
    return /^[A-Z][a-z]/.test(label) ? label.charAt(0).toLowerCase() + label.slice(1) : label
  })
}

const FILLER_WORDS = new Set(['a', 'an', 'the', 'was', 'were', 'is'])
function words(text) {
  return String(text || '').toLowerCase().match(/[a-z0-9']+/g)?.filter(word => !FILLER_WORDS.has(word)) || []
}

// "Comment added" says nothing that "Added a comment" doesn't.
function restates(summary, label) {
  const labelWords = new Set(words(label))
  const summaryWords = words(summary)
  return summaryWords.length > 0 && summaryWords.every(word => labelWords.has(word))
}

// The one-line headline for an entry, in pieces the UI can style:
// { who, text, joined, detail }: text reads after the name ("edited CPT-200 ·
// Description"; joined=false means show a separator first), and detail is the
// summary when the headline doesn't already say it.
export function describeEntry(item) {
  const who = peopleText(item)
  const summary = plainSummary(String(item?.summary || '').trim())
  const commentText = String(item?.action || '').startsWith('comment') ? item?.extra?.detail?.text : ''
  const extraDetail = typeof commentText === 'string' && commentText.trim() ? `"${clip(commentText.trim(), 160)}"` : ''
  if (isGroupedEdit(item) && item?.field_path) {
    const target = entryTarget(item)
    const field = fieldLabelForPath(item.field_path)
    const text = `edited ${target ? target + ' · ' : ''}${field || 'details'}`
    const redundant = !summary || restates(summary, `${text} ${actionLabel(item?.action)} changed`)
    return { who, text, joined: true, detail: extraDetail || (redundant ? '' : summary) }
  }
  const fromSummary = sentenceAfterName(summary)
  if (fromSummary) return { who, text: fromSummary, joined: true, detail: extraDetail }
  const label = actionLabel(item?.action)
  const fromAction = sentenceAfterName(label)
  const detail = extraDetail || (summary && !restates(summary, label) ? summary : '')
  return { who, text: fromAction || label, joined: !!fromAction, detail }
}

// ── Times ───────────────────────────────────────────────────────────────────
function timeOnly(date) {
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

function sameMinute(a, b) {
  return Math.floor(a.getTime() / 60000) === Math.floor(b.getTime() / 60000)
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

// "2:14 PM", "2:14–2:16 PM", "11:58 AM–12:03 PM", or dates when it spans days.
export function timeRange(item) {
  const end = new Date(item?.ts || item?.ts_first || '')
  if (Number.isNaN(end.getTime())) return ''
  const start = new Date(item?.ts_first || item?.ts)
  if (Number.isNaN(start.getTime()) || sameMinute(start, end)) return timeOnly(end)
  if (!sameDay(start, end)) return `${formatWhen(start.toISOString())} – ${formatWhen(end.toISOString())}`
  const startText = timeOnly(start)
  const endText = timeOnly(end)
  const startSuffix = startText.slice(-2)
  const endSuffix = endText.slice(-2)
  return startSuffix === endSuffix ? `${startText.slice(0, -3)}–${endText}` : `${startText}–${endText}`
}

// Full local date and time, for tooltips.
export function fullTime(iso) {
  const date = new Date(iso || '')
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' })
}

export function dayLabel(iso) {
  const date = new Date(iso || '')
  if (Number.isNaN(date.getTime())) return 'Unknown date'
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const days = Math.round((today - target) / 86400000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  return date.toLocaleDateString('en-US', date.getFullYear() === now.getFullYear()
    ? { weekday: 'short', month: 'short', day: 'numeric' }
    : { month: 'short', day: 'numeric', year: 'numeric' })
}

// Entries (newest first) split into days: [{ label, items }].
export function groupByDay(items) {
  const groups = []
  for (const item of items) {
    const label = dayLabel(item.ts)
    if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, items: [] })
    groups[groups.length - 1].items.push(item)
  }
  return groups
}

// ── Date filters ────────────────────────────────────────────────────────────
export const DATE_PRESETS = [
  { key: '', label: 'Any time' },
  { key: 'today', label: 'Today' },
  { key: '7d', label: 'Last 7 days' },
  { key: '30d', label: 'Last 30 days' },
  { key: '90d', label: 'Last 90 days' },
  { key: 'custom', label: 'Pick dates' },
]

function localMidnight(dateString) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateString || '')
  if (!match) return null
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
}

// A preset (or custom local dates) -> { since, until } as UTC times the
// server understands, so "Today" means the person's own today.
export function dateRangeFilters(preset, from, to) {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const daysBack = { today: 0, '7d': 6, '30d': 29, '90d': 89 }
  if (preset in daysBack) {
    const start = new Date(startOfToday)
    start.setDate(start.getDate() - daysBack[preset])
    return { since: start.toISOString() }
  }
  if (preset === 'custom') {
    const out = {}
    const start = localMidnight(from)
    const end = localMidnight(to)
    if (start) out.since = start.toISOString()
    if (end) {
      end.setDate(end.getDate() + 1)
      out.until = new Date(end.getTime() - 1).toISOString()
    }
    return out
  }
  return {}
}
