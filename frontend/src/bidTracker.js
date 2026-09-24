// Shared bits for the Bid Tracker page and the job page's Bid Tracking card.
// Keep the status list in step with server/bid_tracker.py.

export const BID_STATUSES = ['Not started', 'Estimating', 'Ready to send', 'Sent', 'Won', 'Lost', 'No bid']
export const OPEN_BID_STATUSES = ['Not started', 'Estimating', 'Ready to send']
export const CLOSED_BID_STATUSES = ['Won', 'Lost', 'No bid']

export const BID_STATUS_STYLES = {
  'Not started': 'bg-gray-500/10 text-gray-400 border-gray-500/15',
  Estimating: 'bg-si-bright/10 text-blue-400 border-si-bright/15',
  'Ready to send': 'bg-violet-500/10 text-violet-300 border-violet-500/15',
  Sent: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/15',
  Won: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/15',
  Lost: 'bg-red-500/10 text-red-400 border-red-500/15',
  'No bid': 'bg-white/[0.03] text-gray-500 border-white/[0.06]',
}

// Calendar dates travel as 'YYYY-MM-DD'. Build them from local parts so a
// date never shifts a day because of the time zone.
export function toDateString(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function localToday() {
  return toDateString(new Date())
}

export function parseLocalDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '')
  if (!match) return null
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
}

export function addDays(value, days) {
  const d = parseLocalDate(value) || new Date()
  d.setDate(d.getDate() + days)
  return toDateString(d)
}

// "Sep 24", or "Sep 24, 2025" when it is not this year.
export function formatDay(value) {
  const d = parseLocalDate(value)
  if (!d) return ''
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString('en-US', sameYear
    ? { month: 'short', day: 'numeric' }
    : { month: 'short', day: 'numeric', year: 'numeric' })
}

// '14:00' -> '2:00 PM'
export function formatTime(value) {
  const match = /^(\d{2}):(\d{2})/.exec(value || '')
  if (!match) return ''
  const hours = Number(match[1])
  const suffix = hours >= 12 ? 'PM' : 'AM'
  return `${hours % 12 || 12}:${match[2]} ${suffix}`
}

// A saved timestamp -> "Sep 24, 3:05 PM" in the viewer's time zone.
export function formatWhen(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleString('en-US', sameYear
    ? { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
    : { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function formatMoney(value, { cents = true } = {}) {
  if (value === null || value === undefined || value === '') return ''
  const amount = Number(value)
  if (!Number.isFinite(amount)) return ''
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  }).format(amount)
}

export function daysAgoText(days) {
  if (days === null || days === undefined) return ''
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  return `${days} days ago`
}

export function dueText(daysUntilDue) {
  if (daysUntilDue === null || daysUntilDue === undefined) return ''
  if (daysUntilDue < -1) return `${-daysUntilDue} days late`
  if (daysUntilDue === -1) return '1 day late'
  if (daysUntilDue === 0) return 'due today'
  if (daysUntilDue === 1) return 'due tomorrow'
  return `in ${daysUntilDue} days`
}

const FIELD_NAMES = {
  bid_due_date: 'due date',
  bid_due_time: 'due time',
  estimator: 'estimator',
  next_follow_up_date: 'next follow-up',
  won_lost_reason: 'reason',
  awarded_amount: 'awarded amount',
}

function describeValue(field, value) {
  if (value === null || value === undefined || value === '') return 'blank'
  if (field === 'bid_due_date' || field === 'next_follow_up_date') return formatDay(value)
  if (field === 'bid_due_time') return formatTime(value)
  if (field === 'awarded_amount') return formatMoney(value)
  return String(value)
}

// One plain-English line per history entry, e.g. "Marked as sent to Jane (Acme GC)".
export function describeBidEvent(event) {
  const d = event?.details || {}
  const changes = Object.entries(d.changes || {}).map(
    ([field, change]) => `${FIELD_NAMES[field] || field} set to ${describeValue(field, change?.new)}`,
  )
  const changeText = changes.length ? changes.join(', ') : ''
  switch (event?.event_type) {
    case 'status_change': {
      const base = `Status changed from ${d.from || '?'} to ${d.to || '?'}`
      return changeText ? `${base}; ${changeText}` : base
    }
    case 'sent': {
      const who = [d.sent_to, d.gc_name && d.sent_to ? `(${d.gc_name})` : d.gc_name].filter(Boolean).join(' ')
      return who ? `Marked as sent to ${who}` : 'Marked as sent'
    }
    case 'follow_up':
      return 'Followed up'
    case 'won':
      return 'Marked as won'
    case 'lost':
      return 'Marked as lost'
    case 'note':
    default:
      if (changeText) return changeText.charAt(0).toUpperCase() + changeText.slice(1)
      return 'Note'
  }
}

// Short extra facts under the main line (totals, dates, reasons).
export function bidEventFacts(event) {
  const d = event?.details || {}
  const facts = []
  if (event?.event_type === 'sent') {
    if (d.sent_on) facts.push(`Sent ${formatDay(d.sent_on)}`)
    facts.push(d.bid_total !== null && d.bid_total !== undefined
      ? `Bid total ${formatMoney(d.bid_total)}`
      : 'No saved bid total')
    if (d.next_follow_up_date) facts.push(`Follow up ${formatDay(d.next_follow_up_date)}`)
  }
  if (event?.event_type === 'follow_up') {
    if ('next_follow_up_date' in d) {
      facts.push(d.next_follow_up_date ? `Next follow-up ${formatDay(d.next_follow_up_date)}` : 'No next follow-up')
    }
  }
  if (event?.event_type === 'won' || event?.event_type === 'lost') {
    if (d.reason) facts.push(`Reason: ${d.reason}`)
    if (d.awarded_amount !== null && d.awarded_amount !== undefined) facts.push(`Awarded ${formatMoney(d.awarded_amount)}`)
    if (d.bid_total !== null && d.bid_total !== undefined) facts.push(`Our bid ${formatMoney(d.bid_total)}`)
  }
  return facts
}
