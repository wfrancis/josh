import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  ArrowRight,
  Briefcase,
  Loader2,
  Mail,
  RefreshCw,
  Search,
} from 'lucide-react'
import { api } from '../api'
import QuoteEmailCenter from './quote/QuoteEmailCenter'
import { EmptyState, StatusPill } from './quote/QuoteUi'

const STATUS_ORDER = [
  ['needs_review', 'Needs Your Review'],
  ['overdue', 'Overdue'],
  ['ready_to_send', 'Ready to Send'],
  ['needs_setup', 'Needs Setup'],
  ['waiting', 'Waiting on Vendor'],
  ['complete', 'Complete'],
]

function MaterialQuoteBids() {
  const [data, setData] = useState({ bids: [], summary: {} })
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

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
      [bid.project_name, bid.gc_name, bid.salesperson]
        .some((value) => String(value || '').toLowerCase().includes(normalized)),
    )
  }, [data.bids, query])

  if (loading) {
    return (
      <div className="flex min-h-[360px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-white/[0.08] bg-white/[0.06] sm:grid-cols-3 lg:grid-cols-6">
        {STATUS_ORDER.map(([key, label]) => (
          <div key={key} className="min-w-0 bg-[#0B1120] px-3 py-3">
            <p className="truncate text-[11px] text-gray-500">{label}</p>
            <p className="mt-1 text-lg font-bold tabular-nums text-white">
              {Number(data.summary?.[key] || 0)}
            </p>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <label className="relative w-full sm:max-w-sm">
          <span className="sr-only">Search bids</span>
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-600" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search project or GC"
            className="w-full rounded-md border border-white/[0.1] bg-white/[0.025] py-2.5 pl-9 pr-3 text-sm text-gray-200 outline-none placeholder:text-gray-600 focus:border-blue-400/50"
          />
        </label>
        <button
          type="button"
          onClick={() => load({ quiet: true })}
          disabled={refreshing}
          className="inline-flex items-center justify-center gap-2 rounded-md border border-white/[0.1] px-3 py-2.5 text-sm font-semibold text-gray-400 hover:bg-white/[0.05] hover:text-white disabled:opacity-40"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/[0.06] px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {data.mailbox_locked && (
        <p className="text-xs text-gray-600">
          Connect Outlook in Email Center to see mailbox reply status.
        </p>
      )}

      {bids.length ? (
        <div className="overflow-hidden rounded-lg border border-white/[0.08]">
          <div className="hidden grid-cols-[minmax(0,1.5fr)_minmax(120px,0.8fr)_100px_100px_150px_150px] gap-3 border-b border-white/[0.07] bg-white/[0.025] px-4 py-2.5 text-[11px] font-semibold text-gray-600 lg:grid">
            <span>Bid</span>
            <span>GC</span>
            <span>Unpriced</span>
            <span>Vendors</span>
            <span>Status</span>
            <span className="text-right">Next Step</span>
          </div>
          <div className="divide-y divide-white/[0.06]">
            {bids.map((bid) => (
              <div
                key={bid.job_id}
                className="grid gap-3 bg-white/[0.015] px-4 py-4 hover:bg-white/[0.03] lg:grid-cols-[minmax(0,1.5fr)_minmax(120px,0.8fr)_100px_100px_150px_150px] lg:items-center"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">
                    {bid.project_name}
                  </p>
                  <p className="mt-1 text-xs text-gray-600">
                    {bid.request_count
                      ? `${bid.request_count} email request${bid.request_count === 1 ? '' : 's'}`
                      : bid.draft_group_count
                        ? `${bid.draft_group_count} saved draft group${bid.draft_group_count === 1 ? '' : 's'}`
                        : 'No quote email yet'}
                  </p>
                </div>
                <p className="truncate text-sm text-gray-400">
                  {bid.gc_name || '-'}
                </p>
                <div className="flex items-center justify-between lg:block">
                  <span className="text-xs text-gray-600 lg:hidden">Unpriced</span>
                  <span className="text-sm font-semibold tabular-nums text-gray-200">
                    {bid.unpriced_count}
                  </span>
                </div>
                <div className="flex items-center justify-between lg:block">
                  <span className="text-xs text-gray-600 lg:hidden">Vendor groups</span>
                  <span className="text-sm font-semibold tabular-nums text-gray-200">
                    {bid.vendor_group_count}
                  </span>
                </div>
                <div>
                  <StatusPill
                    status={bid.quote_stage}
                    label={bid.quote_stage_label}
                  />
                  {(bid.needs_matching_count > 0 || bid.price_review_count > 0) && (
                    <p className="mt-1 text-[11px] text-orange-300">
                      {bid.needs_matching_count + bid.price_review_count} reply item{bid.needs_matching_count + bid.price_review_count === 1 ? '' : 's'}
                    </p>
                  )}
                </div>
                <Link
                  to={bid.next_action?.url || `/jobs/${bid.slug || bid.job_id}`}
                  className="inline-flex items-center justify-center gap-2 rounded-md border border-white/[0.1] px-3 py-2.5 text-sm font-semibold text-gray-200 hover:border-white/[0.16] hover:bg-white/[0.05]"
                >
                  {bid.next_action?.label || 'Open'}
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <EmptyState>No bids match this search.</EmptyState>
      )}
    </div>
  )
}

export default function MaterialQuotesHub() {
  const location = useLocation()
  const emailOpen = location.pathname === '/material-quotes/email'

  return (
    <div className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8">
      <div className="mb-5 flex flex-col gap-4 border-b border-white/[0.07] pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Mail className="h-5 w-5 text-si-orange" />
            <h1 className="text-xl font-bold text-white">Material Quotes</h1>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Prepare bids first. Send and review email in one place.
          </p>
        </div>
        <nav className="flex min-h-10 items-center rounded-lg border border-white/[0.08] bg-white/[0.025] p-1">
          <Link
            to="/material-quotes"
            className={`inline-flex min-h-8 items-center gap-2 rounded-md px-3 text-sm font-semibold ${
              !emailOpen
                ? 'bg-white/[0.09] text-white'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            <Briefcase className="h-4 w-4" />
            Bids
          </Link>
          <Link
            to="/material-quotes/email"
            className={`inline-flex min-h-8 items-center gap-2 rounded-md px-3 text-sm font-semibold ${
              emailOpen
                ? 'bg-white/[0.09] text-white'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            <Mail className="h-4 w-4" />
            Email Center
          </Link>
        </nav>
      </div>

      {emailOpen ? <QuoteEmailCenter /> : <MaterialQuoteBids />}
    </div>
  )
}
