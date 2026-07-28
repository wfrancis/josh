import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  ArrowRight,
  Briefcase,
  ChevronRight,
  FolderOpen,
  Mail,
  RefreshCw,
  Search,
} from 'lucide-react'
import { api } from '../api'
import QuoteEmailCenter from './quote/QuoteEmailCenter'
import { EmptyState, StatusPill } from './quote/QuoteUi'

const QUOTE_FILTERS = [
  ['open', 'To Do'],
  ['attention', 'Needs your decision'],
  ['prepare', 'Set up needed'],
  ['send', 'Ready to review'],
  ['waiting', 'Waiting'],
  ['complete', 'Complete'],
]

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

function BidQuoteCard({ bid, emailCenterPath, featured = false }) {
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

  return (
    <article
      className={`rounded-lg border bg-white/[0.02] transition-colors hover:bg-white/[0.035] ${
        featured
          ? 'border-orange-500/25 shadow-[inset_3px_0_0_0_rgba(249,115,22,0.85)]'
          : 'border-white/[0.08]'
      }`}
    >
      <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
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
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            <span className={unpricedCount ? 'font-semibold text-orange-300' : 'font-semibold text-emerald-300'}>
              {unpricedCount ? plural(unpricedCount, 'material needs a price', 'materials need prices') : 'All materials are priced'}
            </span>
            <span className="text-gray-500">
              {plural(Number(bid.vendor_group_count || 0), 'vendor group')} · {bidEmailDetail(bid)}
            </span>
          </div>
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
    </article>
  )
}

function MaterialQuoteBids({ emailCenterPath }) {
  const [data, setData] = useState({ bids: [], summary: {} })
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('open')

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
    if (!normalized) return data.bids || []
    return (data.bids || []).filter((bid) =>
      [bid.project_name, bid.gc_name, bid.salesperson, bid.city, bid.state, bid.job_id]
        .some((value) => String(value || '').toLowerCase().includes(normalized)),
    )
  }, [data.bids, query])

  const counts = useMemo(() => {
    const all = data.bids || []
    const byStage = (stages) => all.filter((bid) => stages.includes(bid.quote_stage)).length
    return {
      open: byStage(['needs_review', 'overdue', 'ready_to_send', 'needs_setup', 'waiting']),
      attention: byStage(['needs_review', 'overdue']),
      prepare: byStage(['needs_setup']),
      send: byStage(['ready_to_send']),
      waiting: byStage(['waiting']),
      complete: byStage(['complete']),
    }
  }, [data.bids])

  const visibleBids = useMemo(() => {
    const matches = {
      open: ['needs_review', 'overdue', 'ready_to_send', 'needs_setup', 'waiting'],
      attention: ['needs_review', 'overdue'],
      prepare: ['needs_setup'],
      send: ['ready_to_send'],
      waiting: ['waiting'],
      complete: ['complete'],
    }
    return bids.filter((bid) => matches[filter].includes(bid.quote_stage))
  }, [bids, filter])

  const attentionBids = useMemo(
    () => visibleBids.filter((bid) => ['needs_review', 'overdue'].includes(bid.quote_stage)),
    [visibleBids],
  )
  const queueBids = useMemo(
    () => filter === 'open'
      ? visibleBids.filter((bid) => !['needs_review', 'overdue'].includes(bid.quote_stage))
      : visibleBids,
    [filter, visibleBids],
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
          <h2 className="text-sm font-bold text-white">Bids needing vendor prices</h2>
          <p className="mt-1 text-xs text-gray-500">
            Choose a bid, then take the one next step shown on the right.
          </p>
        </div>
        <label className="relative w-full lg:max-w-sm">
          <span className="sr-only">Search bids</span>
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-600" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search bid, GC, location, or bid number"
            className="w-full rounded-md border border-white/[0.1] bg-white/[0.025] py-2.5 pl-9 pr-3 text-sm text-gray-200 outline-none placeholder:text-gray-600 focus:border-blue-400/50"
          />
        </label>
      </div>

      <div className="flex flex-col gap-2 border-b border-white/[0.07] pb-2 md:flex-row md:items-center">
        <div className="grid grid-cols-2 gap-1 md:flex md:flex-1">
          {QUOTE_FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              aria-label={`${label}: ${counts[key] || 0} bids`}
              className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-md border-b-2 px-2 text-sm font-semibold md:flex-shrink-0 md:justify-start md:px-3 ${
                filter === key
                  ? 'border-si-orange bg-white/[0.05] text-white'
                  : 'border-transparent text-gray-500 hover:bg-white/[0.025] hover:text-gray-300'
              }`}
            >
              {label}
              <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[11px] tabular-nums text-gray-400">
                {counts[key] || 0}
              </span>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => load({ quiet: true })}
          disabled={refreshing}
          title="Refresh bid quote queue"
          className="hidden h-10 w-10 items-center justify-center rounded-md text-gray-500 hover:bg-white/[0.04] hover:text-white disabled:opacity-40 md:ml-auto md:inline-flex md:flex-shrink-0"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-red-500/20 bg-red-500/[0.06] px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {data.mailbox_locked && (
        <p className="text-xs text-gray-400">
          Outlook is disconnected. Saved vendor requests are still visible; connect Outlook to check for new replies.
        </p>
      )}

      {filter === 'open' && attentionBids.length > 0 && (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-si-orange" />
            <h3 className="text-sm font-bold text-white">Needs your decision</h3>
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
            {filter === 'open' ? 'Other bid work' : QUOTE_FILTERS.find(([key]) => key === filter)?.[1]}
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
            {query ? 'No bids match this search.' : 'Nothing is waiting in this part of the quote queue.'}
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
      <div className={`mb-5 flex flex-col gap-4 border-b border-white/[0.07] pb-4 sm:flex-row sm:items-end sm:justify-between ${
        fullBidPath ? '' : 'max-sm:flex-row max-sm:items-center max-sm:justify-end max-sm:gap-0'
      }`}>
        <div className={fullBidPath ? '' : 'hidden sm:block'}>
          <nav className="flex items-center gap-1 text-xs font-semibold text-gray-500" aria-label="Breadcrumb">
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
          <div className="mt-2 flex items-center gap-2">
            <Mail className="h-5 w-5 text-si-orange" />
            <h1 className="text-xl font-bold text-white">{title}</h1>
          </div>
          <p className="mt-1 text-sm text-gray-500">
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
            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-white/[0.1] px-3 text-sm font-semibold text-gray-300 hover:bg-white/[0.05]"
          >
            <Briefcase className="h-4 w-4" />
            Browse Bids
            <ArrowRight className="h-4 w-4" />
          </Link>
        )}
      </div>

      {bidsOpen
        ? <MaterialQuoteBids emailCenterPath={emailCenterPath} />
        : <QuoteEmailCenter basePath={emailCenterPath} />}
    </div>
  )
}
