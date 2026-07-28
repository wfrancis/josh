import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  ArrowDownUp,
  ArrowRight,
  Briefcase,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  Clock3,
  FolderOpen,
  Layers3,
  Mail,
  MailCheck,
  PackageSearch,
  RefreshCw,
  Search,
} from 'lucide-react'
import { api } from '../api'
import QuoteEmailCenter from './quote/QuoteEmailCenter'
import { EmptyState, StatusPill } from './quote/QuoteUi'

const BID_FILTERS = [
  ['all', 'All'],
  ['attention', 'Needs Me'],
  ['replies', 'Replies In'],
  ['waiting', 'Waiting'],
  ['setup', 'Set Up'],
]

const DATE_FILTERS = [
  ['all', 'Any bid date'],
  ['week', 'Last 7 days'],
  ['month', 'Last 30 days'],
  ['year', 'This year'],
]

const SORT_OPTIONS = [
  ['work', 'Needs attention first'],
  ['newest', 'Newest bids first'],
  ['activity', 'Latest activity first'],
  ['replies', 'Most vendor replies'],
  ['unpriced', 'Most materials to price'],
  ['shared', 'Most shared materials'],
]

const ATTENTION_STAGES = new Set(['needs_review', 'overdue', 'ready_to_send'])

const STAGE_PRIORITY = {
  needs_review: 0,
  overdue: 1,
  ready_to_send: 2,
  needs_setup: 3,
  waiting: 4,
  complete: 5,
}

const quoteActionUrl = (bid, emailCenterPath, bidUrl) => {
  if (bid.draft_stale) return bidUrl
  const url = String(bid.next_action?.url || '')
  if (!url) return bidUrl
  if (emailCenterPath !== '/quote-emails' && url.startsWith('/quote-emails')) {
    return `${emailCenterPath}${url.slice('/quote-emails'.length)}`
  }
  return url
}

const plural = (count, singular, pluralLabel = `${singular}s`) => (
  `${count} ${count === 1 ? singular : pluralLabel}`
)

const bidLocation = (bid) => (
  [bid.city, bid.state].filter(Boolean).join(', ')
)

const asDate = (value) => {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

const dateNumber = (value) => asDate(value)?.getTime() || 0

const shortDate = (value) => {
  const date = asDate(value)
  if (!date) return 'No date'
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
  }).format(date)
}

const relativeDate = (value) => {
  const date = asDate(value)
  if (!date) return 'No recent activity'
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  return shortDate(value)
}

const dateMatches = (value, filter) => {
  if (filter === 'all') return true
  const date = asDate(value)
  if (!date) return false
  const now = new Date()
  if (filter === 'year') return date.getFullYear() === now.getFullYear()
  const days = filter === 'week' ? 7 : 30
  const cutoff = new Date(now)
  cutoff.setDate(cutoff.getDate() - days)
  return date >= cutoff
}

const quoteRequestCounts = (bid) => {
  const statuses = bid.request_statuses || {}
  const total = Number(bid.request_count || 0)
  const completed = Number(
    bid.completed_request_count
    ?? (Number(statuses.complete || 0) + Number(statuses.received || 0)),
  )
  const cancelled = Number(
    bid.cancelled_request_count
    ?? Number(statuses.cancelled || 0),
  )
  const active = Number(
    bid.active_request_count
    ?? Math.max(0, total - completed - cancelled),
  )

  return { active, cancelled, completed }
}

const bidEmailDetail = (bid) => {
  if (Number(bid.needs_matching_count || 0) || Number(bid.price_review_count || 0)) {
    return plural(
      Number(bid.needs_matching_count || 0) + Number(bid.price_review_count || 0),
      'reply needs review',
      'replies need review',
    )
  }
  if (Number(bid.draft_group_count || 0)) {
    return plural(Number(bid.draft_group_count), 'saved email draft', 'saved email drafts')
  }
  const { active, completed, cancelled } = quoteRequestCounts(bid)
  if (active) {
    return plural(active, 'vendor email sent', 'vendor emails sent')
  }
  if (completed) {
    return plural(completed, 'completed vendor quote', 'completed vendor quotes')
  }
  if (cancelled) {
    return plural(cancelled, 'cancelled quote request', 'cancelled quote requests')
  }
  return 'No vendor email prepared yet'
}

const bidNeedsAttention = (bid) => ATTENTION_STAGES.has(bid.quote_stage)

const bidHasReply = (bid) => (
  Number(bid.response_count || 0) > 0
  || Number(bid.needs_matching_count || 0) > 0
  || Number(bid.price_review_count || 0) > 0
)

const bidMatchesFilter = (bid, filter) => {
  if (filter === 'all') return true
  if (filter === 'attention') return bidNeedsAttention(bid)
  if (filter === 'replies') return bidHasReply(bid)
  if (filter === 'waiting') return bid.quote_stage === 'waiting'
  if (filter === 'setup') return bid.quote_stage === 'needs_setup'
  return true
}

const sortBids = (bids, sort) => bids.slice().sort((left, right) => {
  if (sort === 'newest') return dateNumber(right.created_at) - dateNumber(left.created_at)
  if (sort === 'activity') return dateNumber(right.last_activity_at) - dateNumber(left.last_activity_at)
  if (sort === 'replies') {
    const replyDifference = (
      Number(right.response_count || 0)
      + Number(right.needs_matching_count || 0)
      + Number(right.price_review_count || 0)
    ) - (
      Number(left.response_count || 0)
      + Number(left.needs_matching_count || 0)
      + Number(left.price_review_count || 0)
    )
    return replyDifference || dateNumber(right.latest_reply_at) - dateNumber(left.latest_reply_at)
  }
  if (sort === 'unpriced') {
    return Number(right.unpriced_count || 0) - Number(left.unpriced_count || 0)
  }
  if (sort === 'shared') {
    return Number(right.shared_material_count || 0) - Number(left.shared_material_count || 0)
  }
  return (
    Number(STAGE_PRIORITY[left.quote_stage] ?? 99) - Number(STAGE_PRIORITY[right.quote_stage] ?? 99)
    || dateNumber(right.last_activity_at) - dateNumber(left.last_activity_at)
    || String(left.project_name || '').localeCompare(String(right.project_name || ''))
  )
})

function BidQuoteCard({ bid, emailCenterPath, featured = false }) {
  const [sharedOpen, setSharedOpen] = useState(false)
  const bidUrl = `/jobs/${bid.slug || bid.job_id}?step=quotes`
  const actionUrl = quoteActionUrl(bid, emailCenterPath, bidUrl)
  const emailActionLabel = bid.draft_stale
    ? 'Update Quote Email'
    : {
    needs_review: 'Review Quote Email',
    overdue: 'Follow up today',
    ready_to_send: 'Review & Send',
    waiting: 'View Quote Status',
    }[bid.quote_stage]
  const location = bidLocation(bid)
  const unpricedCount = Number(bid.unpriced_count || 0)
  const reviewCount = Number(bid.needs_matching_count || 0) + Number(bid.price_review_count || 0)
  const replyCount = Number(bid.response_count || 0)
  const sharedMaterialCount = Number(bid.shared_material_count || 0)
  const sharedUnpricedCount = Number(bid.shared_unpriced_material_count || 0)
  const sharedBidCount = Number(bid.shared_bid_count || 0)
  const sharedId = `shared-inventory-${bid.job_id}`
  const replyLabel = reviewCount
    ? plural(reviewCount, 'reply needs review', 'replies need review')
    : replyCount
      ? plural(replyCount, 'vendor reply', 'vendor replies')
      : ''

  return (
    <article
      className={`rounded-lg border bg-white/[0.02] transition-colors hover:bg-white/[0.035] ${
        featured
          ? 'border-orange-500/25 shadow-[inset_3px_0_0_0_rgba(249,115,22,0.85)]'
          : 'border-white/[0.08]'
      }`}
    >
      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.9fr)_auto] lg:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={bidUrl}
              className="truncate text-base font-bold text-white hover:text-blue-300"
            >
              {bid.project_name}
            </Link>
            <span className="rounded border border-white/[0.08] bg-black/15 px-1.5 py-0.5 text-[10px] font-semibold text-gray-500">
              Bid #{bid.job_id}
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-400">
            {[bid.gc_name, location].filter(Boolean).join(' | ') || 'No GC or location listed'}
          </p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-gray-500">
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays className="h-3.5 w-3.5" />
              Bid {shortDate(bid.created_at)}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock3 className="h-3.5 w-3.5" />
              Updated {relativeDate(bid.last_activity_at || bid.created_at)}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <div className="min-w-0">
            <span className="flex items-center gap-1.5 text-gray-500">
              <PackageSearch className="h-3.5 w-3.5" />
              Pricing
            </span>
            <p className={`mt-0.5 truncate font-semibold ${unpricedCount ? 'text-orange-300' : 'text-emerald-300'}`}>
              {unpricedCount
                ? plural(unpricedCount, 'material to price', 'materials to price')
                : 'All materials priced'}
            </p>
          </div>
          <div className="min-w-0">
            <span className="flex items-center gap-1.5 text-gray-500">
              <Mail className="h-3.5 w-3.5" />
              Vendor email
            </span>
            <p className="mt-0.5 truncate font-semibold text-gray-300">
              {bidEmailDetail(bid)}
            </p>
          </div>
          {bid.replies_available && replyLabel && (
            <div className="min-w-0">
              <span className="flex items-center gap-1.5 text-gray-500">
                <MailCheck className="h-3.5 w-3.5" />
                Latest reply
              </span>
              <p className={`mt-0.5 truncate font-semibold ${reviewCount ? 'text-orange-300' : 'text-sky-300'}`}>
                {replyLabel}{bid.latest_reply_at ? ` · ${relativeDate(bid.latest_reply_at)}` : ''}
              </p>
            </div>
          )}
          {sharedMaterialCount > 0 && (
            <div className="min-w-0">
              <span className="flex items-center gap-1.5 text-gray-500">
                <Layers3 className="h-3.5 w-3.5" />
                Shared inventory
              </span>
              <button
                type="button"
                onClick={() => setSharedOpen((current) => !current)}
                aria-expanded={sharedOpen}
                aria-controls={sharedId}
                className="mt-0.5 inline-flex min-h-7 items-center gap-1 text-left font-semibold text-blue-300 hover:text-white"
              >
                {sharedUnpricedCount
                  ? `${sharedUnpricedCount} need price elsewhere`
                  : `${sharedMaterialCount} shared material${sharedMaterialCount === 1 ? '' : 's'}`}
                <ChevronDown className={`h-3.5 w-3.5 transition-transform ${sharedOpen ? 'rotate-180' : ''}`} />
              </button>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <StatusPill status={bid.quote_stage} label={bid.quote_stage_label} />
          <Link
            to={actionUrl}
            aria-label={`${emailActionLabel || bid.next_action?.label || 'Open Bid'} for ${bid.project_name}`}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-si-orange px-3.5 text-sm font-bold text-[#0A0F1E] hover:bg-orange-400"
          >
            {emailActionLabel || bid.next_action?.label || 'Open Bid'}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
      {sharedOpen && sharedMaterialCount > 0 && (
        <div id={sharedId} className="border-t border-white/[0.07] bg-black/10 px-4 py-3">
          <p className="text-xs text-gray-500">
            Exact material matches in {sharedBidCount} other bid{sharedBidCount === 1 ? '' : 's'}.
          </p>
          <div className="mt-2 grid gap-2 lg:grid-cols-3">
            {(bid.shared_materials || []).map((material) => (
              <div key={`${material.label}-${material.unit}`} className="min-w-0 text-xs">
                <p className="truncate font-semibold text-gray-300">
                  {material.label}{material.unit ? ` · ${material.unit}` : ''}
                </p>
                <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-1 text-gray-500">
                  {(material.other_bids || []).map((otherBid) => (
                    <Link
                      key={otherBid.job_id}
                      to={`/jobs/${otherBid.slug || otherBid.job_id}?step=quotes`}
                      className="truncate hover:text-blue-300"
                    >
                      {otherBid.project_name} · #{otherBid.job_id}
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </article>
  )
}

function MaterialQuoteBids({ emailCenterPath }) {
  const [data, setData] = useState({ bids: [], summary: {} })
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [dateFilter, setDateFilter] = useState('all')
  const [sort, setSort] = useState('work')
  const [sharedOnly, setSharedOnly] = useState(false)

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      setData(await api.getMaterialQuoteBids())
    } catch (err) {
      setError(err.message || 'The bid quote list could not load.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const bids = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    const matching = (data.bids || []).filter((bid) => {
      const matchesSearch = !normalized || [
        bid.project_name,
        bid.gc_name,
        bid.salesperson,
        bid.city,
        bid.state,
        bid.job_id,
        ...(bid.shared_materials || []).map((material) => material.label),
      ].some((value) => String(value || '').toLowerCase().includes(normalized))
      return (
        matchesSearch
        && bidMatchesFilter(bid, filter)
        && dateMatches(bid.created_at, dateFilter)
        && (!sharedOnly || Number(bid.shared_material_count || 0) > 0)
      )
    })
    return sortBids(matching, sort)
  }, [data.bids, dateFilter, filter, query, sharedOnly, sort])

  const counts = useMemo(() => {
    const all = data.bids || []
    const byStage = (stages) => all.filter((bid) => stages.includes(bid.quote_stage)).length
    return {
      all: all.length,
      attention: byStage(['needs_review', 'overdue', 'ready_to_send']),
      replies: all.filter((bid) => bidHasReply(bid)).length,
      waiting: byStage(['waiting']),
      setup: byStage(['needs_setup']),
    }
  }, [data.bids])

  const attentionBids = useMemo(
    () => bids.filter((bid) => bidNeedsAttention(bid)),
    [bids],
  )
  const queueBids = useMemo(
    () => filter === 'all' && sort === 'work'
      ? bids.filter((bid) => !bidNeedsAttention(bid))
      : bids,
    [bids, filter, sort],
  )

  if (loading) {
    return (
      <div className="flex min-h-[360px] items-center justify-center">
        <RefreshCw className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 border-b border-white/[0.07] pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-base font-bold text-white">Browse Bids</h2>
          <p className="mt-1 text-xs text-gray-500">
            New bids, vendor replies, and shared materials in one place.
          </p>
        </div>
        <div className="flex w-full items-center gap-2 lg:max-w-xl">
          <label className="relative min-w-0 flex-1">
          <span className="sr-only">Search bids</span>
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-600" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search bid, GC, location, or bid number"
            className="w-full rounded-md border border-white/[0.1] bg-white/[0.025] py-2.5 pl-9 pr-3 text-sm text-gray-200 outline-none placeholder:text-gray-600 focus:border-blue-400/50"
          />
          </label>
          <button
            type="button"
            onClick={() => load({ quiet: true })}
            disabled={refreshing}
            title="Refresh bids"
            aria-label="Refresh bids"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-white/[0.08] text-gray-400 hover:bg-white/[0.05] hover:text-white disabled:opacity-40"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="space-y-3 border-b border-white/[0.07] pb-4">
        <div className="flex flex-wrap gap-1" aria-label="Bid quick filters">
          {BID_FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              aria-label={`${label}: ${counts[key] || 0} bids`}
              className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-semibold ${
                filter === key
                  ? 'bg-si-orange text-[#0A0F1E]'
                  : 'text-gray-400 hover:bg-white/[0.05] hover:text-gray-200'
              }`}
            >
              {label}
              <span className={`rounded-md px-1.5 py-0.5 text-[11px] tabular-nums ${
                filter === key ? 'bg-black/15 text-[#0A0F1E]' : 'bg-white/[0.06] text-gray-400'
              }`}>
                {counts[key] || 0}
              </span>
            </button>
          ))}
        </div>
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <label className="min-w-0">
            <span className="mb-1 block text-xs font-semibold text-gray-500">Bid date</span>
            <select
              value={dateFilter}
              onChange={(event) => setDateFilter(event.target.value)}
              className="min-h-11 w-full rounded-md border border-white/[0.1] bg-[#0D1322] px-3 text-sm font-semibold text-gray-200 outline-none focus:border-blue-400/50"
            >
              {DATE_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="min-w-0">
            <span className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-gray-500">
              <ArrowDownUp className="h-3.5 w-3.5" />
              Sort bids
            </span>
            <select
              value={sort}
              onChange={(event) => setSort(event.target.value)}
              className="min-h-11 w-full rounded-md border border-white/[0.1] bg-[#0D1322] px-3 text-sm font-semibold text-gray-200 outline-none focus:border-blue-400/50"
            >
              {SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="flex min-h-11 cursor-pointer items-center gap-2 self-end rounded-md border border-white/[0.1] px-3 text-sm font-semibold text-gray-300 hover:bg-white/[0.04]">
            <input
              type="checkbox"
              checked={sharedOnly}
              onChange={(event) => setSharedOnly(event.target.checked)}
              className="h-4 w-4 rounded border-white/[0.2] accent-si-orange"
            />
            <Layers3 className="h-4 w-4 text-blue-300" />
            Shared materials
          </label>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-red-500/20 bg-red-500/[0.06] px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {data.mailbox_locked && (
        <p className="text-xs text-gray-400">
          Outlook is disconnected. Saved requests are visible; connect Outlook to see vendor replies in this list.
        </p>
      )}

      {filter === 'all' && sort === 'work' && attentionBids.length > 0 && (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-si-orange" />
            <h3 className="text-sm font-bold text-white">Work Now</h3>
            <span className="rounded-md bg-orange-500/10 px-2 py-0.5 text-xs font-semibold text-orange-300">
              {attentionBids.length} bid{attentionBids.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="space-y-3">
            {attentionBids.map((bid) => (
              <BidQuoteCard key={bid.job_id} bid={bid} emailCenterPath={emailCenterPath} featured />
            ))}
          </div>
        </section>
      )}

      <section>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-sm font-bold text-white">
            {filter === 'all' && sort === 'work'
              ? 'Browse all other bids'
              : BID_FILTERS.find(([key]) => key === filter)?.[1] || 'Bids'}
          </h3>
          <span className="text-xs font-semibold tabular-nums text-gray-500">
            {queueBids.length} bid{queueBids.length === 1 ? '' : 's'}
          </span>
        </div>
        {queueBids.length ? (
          <div className="space-y-3">
            {queueBids.map((bid) => (
              <BidQuoteCard key={bid.job_id} bid={bid} emailCenterPath={emailCenterPath} />
            ))}
          </div>
        ) : (
          <EmptyState>
            {filter === 'replies' && data.mailbox_locked
              ? 'Connect Outlook to see bids with vendor replies.'
              : query
                ? 'No bids match this search.'
                : 'No bids match these filters.'}
          </EmptyState>
        )}
      </section>
    </div>
  )
}

export default function MaterialQuotesHub() {
  const location = useLocation()
  const fullBidPath = location.pathname.startsWith('/jobs/bids')
  const bidsOpen = location.pathname === '/jobs/bids'
  const emailCenterPath = fullBidPath ? '/jobs/bids/quote-emails' : '/quote-emails'
  const title = fullBidPath ? (bidsOpen ? 'Bids' : 'Quote Emails') : 'Quote Email Center'
  const description = fullBidPath
    ? (bidsOpen
      ? 'Choose a bid, prepare vendor pricing, then finish the proposal in the same bid.'
      : 'Review and send vendor requests for the selected bid. Return to the bid when prices are complete.')
    : 'Fast daily inbox for vendor quote emails across every bid.'

  return (
    <div className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8">
      <div className={`mb-5 border-b border-white/[0.07] pb-4 ${
        fullBidPath
          ? 'flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between'
          : 'flex items-center justify-between gap-3'
      }`}>
        <div>
          <nav className="hidden items-center gap-1 text-xs font-semibold text-gray-500 sm:flex" aria-label="Breadcrumb">
            {fullBidPath ? (
              <>
                <Link to="/jobs" className="inline-flex items-center gap-1 hover:text-gray-300">
                  <FolderOpen className="h-3.5 w-3.5" />
                  Jobs
                </Link>
                <ChevronRight className="h-3.5 w-3.5" />
                <Link to="/jobs/bids" className="hover:text-gray-300">Bids</Link>
              </>
            ) : (
              <Link to="/quote-emails" className="inline-flex items-center gap-1 hover:text-gray-300">
                <Mail className="h-3.5 w-3.5" />
                Quote Email Center
              </Link>
            )}
            {fullBidPath && !bidsOpen && (
              <>
                <ChevronRight className="h-3.5 w-3.5" />
                <span className="text-gray-300">Quote Emails</span>
              </>
            )}
          </nav>
          <div className="flex items-center gap-2 sm:mt-2">
            <Mail className="h-5 w-5 text-si-orange" />
            <h1 className="text-xl font-bold text-white">{title}</h1>
          </div>
          <p className="mt-1 hidden text-sm text-gray-500 sm:block">
            {description}
          </p>
        </div>
        {fullBidPath ? (
          <nav className="flex min-h-11 items-center rounded-lg border border-white/[0.08] bg-white/[0.025] p-1">
            <Link
              to="/jobs/bids"
              className={`inline-flex min-h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold ${
                bidsOpen
                  ? 'bg-white/[0.09] text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <Briefcase className="h-4 w-4" />
              Bids
            </Link>
            <Link
              to="/jobs/bids/quote-emails"
              className={`inline-flex min-h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold ${
                !bidsOpen
                  ? 'bg-white/[0.09] text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <Mail className="h-4 w-4" />
              Quote Emails
            </Link>
          </nav>
        ) : (
          <Link
            to="/jobs/bids"
            className="inline-flex min-h-11 flex-shrink-0 items-center gap-2 rounded-md border border-white/[0.1] px-3 text-sm font-semibold text-gray-300 hover:bg-white/[0.05]"
          >
            <Briefcase className="h-4 w-4" />
            <span className="sm:hidden">Bids</span>
            <span className="hidden sm:inline">Browse Bids</span>
            <ArrowRight className="hidden h-4 w-4 sm:block" />
          </Link>
        )}
      </div>

      {bidsOpen
        ? <MaterialQuoteBids emailCenterPath={emailCenterPath} />
        : <QuoteEmailCenter basePath={emailCenterPath} />}
    </div>
  )
}
