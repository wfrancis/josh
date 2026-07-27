export const STATUS_STYLES = {
  needs_review: 'border-orange-500/25 bg-orange-500/10 text-orange-300',
  needs_you: 'border-orange-500/25 bg-orange-500/10 text-orange-300',
  needs_setup: 'border-orange-500/25 bg-orange-500/10 text-orange-300',
  stale: 'border-orange-500/25 bg-orange-500/10 text-orange-300',
  send_uncertain: 'border-orange-500/25 bg-orange-500/10 text-orange-300',
  overdue: 'border-amber-500/25 bg-amber-500/10 text-amber-300',
  ready_to_send: 'border-blue-500/25 bg-blue-500/10 text-blue-300',
  approved: 'border-blue-500/25 bg-blue-500/10 text-blue-300',
  sending: 'border-blue-500/25 bg-blue-500/10 text-blue-300',
  sent: 'border-blue-500/25 bg-blue-500/10 text-blue-300',
  waiting: 'border-gray-500/25 bg-gray-500/10 text-gray-300',
  received_partial: 'border-cyan-500/25 bg-cyan-500/10 text-cyan-300',
  received: 'border-cyan-500/25 bg-cyan-500/10 text-cyan-300',
  complete: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
  connected: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
  pass: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
  passed: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
  send_failed: 'border-red-500/25 bg-red-500/10 text-red-300',
  fail: 'border-red-500/25 bg-red-500/10 text-red-300',
  failed: 'border-red-500/25 bg-red-500/10 text-red-300',
  cancelled: 'border-gray-500/20 bg-gray-500/10 text-gray-500',
  ignored: 'border-gray-500/20 bg-gray-500/10 text-gray-500',
}

export const asArray = (value) => {
  if (Array.isArray(value)) return value
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }
  return []
}

export const normalizeStatus = (value) =>
  String(value || 'waiting').trim().toLowerCase().replace(/[\s-]+/g, '_')

export const titleize = (value) =>
  String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())

export const formatDate = (value) => {
  if (!value) return 'Not yet'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export const formatMoney = (value) => {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '-'
  return amount.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
  })
}

export const materialLabel = (material) =>
  [
    material?.item_code,
    material?.description
      || material?.material_description
      || material?.product_name,
  ].filter(Boolean).join(' - ') || 'Unnamed material'

export function StatusPill({ status, label }) {
  const normalized = normalizeStatus(status)
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold ${STATUS_STYLES[normalized] || STATUS_STYLES.waiting}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label || titleize(normalized)}
    </span>
  )
}

export function EmptyState({ children }) {
  return (
    <div className="rounded-lg border border-dashed border-white/[0.1] px-4 py-8 text-center text-sm text-gray-500">
      {children}
    </div>
  )
}

export function SectionTitle({ icon: Icon, title, count, action }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        {Icon && <Icon className="h-4 w-4 flex-shrink-0 text-gray-500" />}
        <h2 className="text-sm font-bold text-white">{title}</h2>
        {count != null && (
          <span className="rounded-md bg-white/[0.06] px-2 py-0.5 text-xs font-semibold text-gray-400">
            {count}
          </span>
        )}
      </div>
      {action}
    </div>
  )
}
