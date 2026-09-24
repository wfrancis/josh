import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ClipboardList, CalendarClock, Send, Trophy, Search, Loader2, AlertTriangle, FolderOpen,
} from 'lucide-react'
import { api } from '../api'
import BidStatusBadge from './BidStatusBadge'
import {
  BID_STATUSES, OPEN_BID_STATUSES,
  formatDay, formatTime, formatMoney, formatWhen, daysAgoText, dueText,
} from '../bidTracker'

// 'all' is the default tab (no ?tab= in the address), so every bid shows, won and lost included.
const DEFAULT_TAB = 'all'
const TABS = [
  { key: 'all', label: 'All', statuses: null },
  { key: 'open', label: 'Open', statuses: OPEN_BID_STATUSES },
  { key: 'sent', label: 'Sent', statuses: ['Sent'] },
  { key: 'won', label: 'Won', statuses: ['Won'] },
  { key: 'lost', label: 'Lost', statuses: ['Lost'] },
]

// Dates are 'YYYY-MM-DD', so plain string order is date order. Blank dates go last.
function byDate(a, b, dir = 1) {
  if (!a && !b) return 0
  if (!a) return 1
  if (!b) return -1
  return a < b ? -dir : a > b ? dir : 0
}

function sortBids(rows, tab) {
  const list = [...rows]
  const byName = (a, b) => (a.project_name || '').localeCompare(b.project_name || '')
  if (tab === 'open') {
    list.sort((a, b) => byDate(a.bid_due_date, b.bid_due_date) || byName(a, b))
  } else if (tab === 'sent') {
    list.sort((a, b) => byDate(a.next_follow_up_date, b.next_follow_up_date)
      || byDate(a.last_sent_date, b.last_sent_date) || byName(a, b))
  } else if (tab === 'won' || tab === 'lost') {
    list.sort((a, b) => byDate(a.won_lost_at, b.won_lost_at, -1) || byName(a, b))
  } else {
    list.sort((a, b) => (BID_STATUSES.indexOf(a.bid_status) - BID_STATUSES.indexOf(b.bid_status))
      || byDate(a.bid_due_date, b.bid_due_date) || byName(a, b))
  }
  return list
}

function SummaryTile({ icon: Icon, label, value, note, noteTone = 'muted' }) {
  const noteClass = {
    muted: 'text-gray-500',
    red: 'text-red-400',
    amber: 'text-amber-400',
    green: 'text-emerald-400',
  }[noteTone]
  return (
    <div className="glass-card p-4 sm:p-5">
      <div className="flex items-center gap-2 text-xs font-medium text-gray-500">
        <Icon className="w-4 h-4 text-gray-400" />
        {label}
      </div>
      <div className="mt-2 text-2xl sm:text-3xl font-extrabold text-white tabular-nums tracking-tight">{value}</div>
      {note && <div className={`mt-1 text-xs ${noteClass}`}>{note}</div>}
    </div>
  )
}

function winRateNote(summary) {
  if (summary.win_rate_this_month !== null && summary.win_rate_this_month !== undefined) {
    return { text: `${Math.round(summary.win_rate_this_month * 100)}% win rate this month`, tone: 'green' }
  }
  if (summary.win_rate_all_time !== null && summary.win_rate_all_time !== undefined) {
    return {
      text: `${Math.round(summary.win_rate_all_time * 100)}% win rate all time (${summary.won_all_time} of ${summary.won_all_time + summary.lost_all_time})`,
      tone: 'muted',
    }
  }
  return { text: 'No wins or losses recorded yet', tone: 'muted' }
}

function Dash() {
  return <span className="text-gray-600">—</span>
}

export default function BidTracker() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')

  const tab = TABS.some(t => t.key === searchParams.get('tab')) ? searchParams.get('tab') : DEFAULT_TAB
  const setTab = (key) => setSearchParams(key === DEFAULT_TAB ? {} : { tab: key }, { replace: true })

  useEffect(() => {
    api.getBidTracker()
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const bids = data?.bids || []

  const counts = useMemo(() => Object.fromEntries(TABS.map(t => [
    t.key,
    t.statuses ? bids.filter(b => t.statuses.includes(b.bid_status)).length : bids.length,
  ])), [bids])

  const visible = useMemo(() => {
    const current = TABS.find(t => t.key === tab)
    const q = search.trim().toLowerCase()
    const filtered = bids.filter(b => {
      if (current.statuses && !current.statuses.includes(b.bid_status)) return false
      if (!q) return true
      return [b.project_name, b.gc_name, b.estimator, b.salesperson, b.city, b.last_sent_to, b.last_sent_gc]
        .some(value => (value || '').toLowerCase().includes(q))
    })
    return sortBids(filtered, tab)
  }, [bids, tab, search])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-40">
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    )
  }

  const summary = data?.summary
  const rate = summary ? winRateNote(summary) : null

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
      {/* Header */}
      <div className="mb-6 sm:mb-8">
        <h1 className="text-2xl font-extrabold text-white tracking-tight">Bid Tracker</h1>
        <p className="text-sm text-gray-500 mt-1">Every bid, when it's due, and where it stands.</p>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 mb-6 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Summary tiles */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6 sm:mb-8">
          <SummaryTile
            icon={ClipboardList}
            label="Open bids"
            value={summary.open}
            note={summary.overdue > 0 ? `${summary.overdue} past due` : 'Nothing past due'}
            noteTone={summary.overdue > 0 ? 'red' : 'muted'}
          />
          <SummaryTile
            icon={CalendarClock}
            label="Due this week"
            value={summary.due_this_week}
            note="Open bids due in the next 7 days"
          />
          <SummaryTile
            icon={Send}
            label="Sent, waiting to hear"
            value={summary.sent_awaiting}
            note={summary.follow_ups_due > 0
              ? `${summary.follow_ups_due} need${summary.follow_ups_due === 1 ? 's' : ''} a follow-up`
              : 'No follow-ups due'}
            noteTone={summary.follow_ups_due > 0 ? 'amber' : 'muted'}
          />
          <SummaryTile
            icon={Trophy}
            label="Won / lost this month"
            value={`${summary.won_this_month} / ${summary.lost_this_month}`}
            note={rate.text}
            noteTone={rate.tone}
          />
        </div>
      )}

      {/* Tabs + search */}
      <div className="flex flex-col lg:flex-row lg:items-center gap-3 mb-4">
        <div className="flex flex-wrap gap-1.5">
          {TABS.map(t => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`px-3.5 py-2 rounded-xl text-sm font-medium transition-colors border
                ${tab === t.key
                  ? 'bg-white/[0.08] text-white border-white/[0.1]'
                  : 'text-gray-500 border-transparent hover:text-gray-300 hover:bg-white/[0.04]'}`}
            >
              {t.label}
              <span className={`ml-1.5 tabular-nums ${tab === t.key ? 'text-gray-400' : 'text-gray-600'}`}>{counts[t.key]}</span>
            </button>
          ))}
        </div>
        <div className="relative lg:ml-auto lg:w-80">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search project, GC, estimator..."
            className="input pl-11 py-2.5"
          />
        </div>
      </div>

      {/* Table */}
      {visible.length === 0 ? (
        <div className="text-center py-16 glass-card">
          <FolderOpen className="w-12 h-12 text-gray-600 mx-auto mb-4" />
          {bids.length === 0 ? (
            <>
              <p className="text-gray-400 font-medium">No bids yet</p>
              <p className="text-sm text-gray-600 mt-1">Every job shows up here. Create a job from the Dashboard to start.</p>
            </>
          ) : search ? (
            <>
              <p className="text-gray-400 font-medium">Nothing matches "{search}"</p>
              <button onClick={() => setSearch('')} className="text-sm text-si-bright hover:underline mt-2">Clear search</button>
            </>
          ) : (
            <p className="text-gray-400 font-medium">No bids in this list</p>
          )}
        </div>
      ) : (
        <div className="glass-card overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider">
                <th className="px-4 py-3">Project</th>
                <th className="px-3 py-3">GC</th>
                <th className="px-3 py-3">Estimator</th>
                <th className="px-3 py-3">Status</th>
                <th className="px-3 py-3">Due</th>
                <th className="px-3 py-3 text-right">Bid total</th>
                <th className="px-3 py-3">Sent</th>
                <th className="px-3 py-3">Next follow-up</th>
                <th className="px-4 py-3">Last updated</th>
              </tr>
            </thead>
            <tbody>
              {visible.map(bid => {
                const open = () => navigate(`/jobs/${bid.slug || bid.job_id}`)
                const dueTone = bid.due_overdue ? 'text-red-400' : bid.due_soon ? 'text-amber-400' : 'text-gray-300'
                const followTone = bid.follow_up_overdue ? 'text-red-400' : bid.follow_up_due_today ? 'text-amber-400' : 'text-gray-300'
                return (
                  <tr
                    key={bid.job_id}
                    onClick={open}
                    onKeyDown={e => { if (e.key === 'Enter') open() }}
                    tabIndex={0}
                    className="border-t border-white/[0.05] hover:bg-white/[0.04] focus:bg-white/[0.04] focus:outline-none cursor-pointer transition-colors align-top"
                  >
                    <td className="px-4 py-3">
                      <div className="font-semibold text-white">{bid.project_name}</div>
                      {(bid.city || bid.state) && (
                        <div className="text-xs text-gray-500 mt-0.5">{[bid.city, bid.state].filter(Boolean).join(', ')}</div>
                      )}
                    </td>
                    <td className="px-3 py-3 text-gray-300">{bid.gc_name || <Dash />}</td>
                    <td className="px-3 py-3 text-gray-300">{bid.estimator || <Dash />}</td>
                    <td className="px-3 py-3">
                      <span title={bid.bid_status_is_default ? 'Not set yet. Shown from how far along the job is.' : undefined}>
                        <BidStatusBadge status={bid.bid_status} className={bid.bid_status_is_default ? 'opacity-70' : ''} />
                      </span>
                      {(bid.bid_status === 'Won' || bid.bid_status === 'Lost') && bid.won_lost_reason && (
                        <div className="text-xs text-gray-500 mt-1 max-w-[12rem] truncate" title={bid.won_lost_reason}>{bid.won_lost_reason}</div>
                      )}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap">
                      {bid.bid_due_date ? (
                        <>
                          <div className={`font-medium ${dueTone}`}>
                            {formatDay(bid.bid_due_date)}
                            {bid.bid_due_time && <span className="ml-1 font-normal">{formatTime(bid.bid_due_time)}</span>}
                          </div>
                          {bid.is_open && <div className={`text-xs mt-0.5 ${bid.due_overdue || bid.due_soon ? dueTone : 'text-gray-500'}`}>{dueText(bid.days_until_due)}</div>}
                        </>
                      ) : <Dash />}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums whitespace-nowrap">
                      {bid.bid_total !== null && bid.bid_total !== undefined
                        ? <span className="text-gray-200">{formatMoney(bid.bid_total, { cents: false })}</span>
                        : <Dash />}
                      {bid.bid_status === 'Won' && bid.awarded_amount !== null && bid.awarded_amount !== undefined && (
                        <div className="text-xs text-emerald-400/80 mt-0.5">Awarded {formatMoney(bid.awarded_amount, { cents: false })}</div>
                      )}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap">
                      {bid.last_sent_date ? (
                        <>
                          <div className="text-gray-300">{formatDay(bid.last_sent_date)}</div>
                          {bid.bid_status === 'Sent' && <div className="text-xs text-gray-500 mt-0.5">{daysAgoText(bid.days_since_sent)}</div>}
                        </>
                      ) : <Dash />}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap">
                      {bid.next_follow_up_date ? (
                        <>
                          <div className={`font-medium ${followTone}`}>{formatDay(bid.next_follow_up_date)}</div>
                          {bid.follow_up_overdue && <div className="text-xs text-red-400 mt-0.5">past due</div>}
                          {bid.follow_up_due_today && <div className="text-xs text-amber-400 mt-0.5">today</div>}
                        </>
                      ) : <Dash />}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {bid.last_updated_by_name ? (
                        <>
                          <div className="text-gray-300">{bid.last_updated_by_name}</div>
                          <div className="text-xs text-gray-500 mt-0.5">{formatWhen(bid.last_updated_at)}</div>
                        </>
                      ) : <Dash />}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
