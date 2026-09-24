import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Download, Loader2, RefreshCw, Search, X } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import HistoryEntry from '../history/HistoryEntry'
import useAuditFeed, { historyErrorText } from '../history/useAuditFeed'
import {
  AUDIT_AREAS, DATE_PRESETS, KNOWN_ENTITY_TYPES, actionLabel, dateRangeFilters, entityLabel, entryPeople, groupByDay,
} from '../history/fieldLabels'

// Company-wide history: every change anyone made, newest first. Filters live
// in the address bar so a filtered view can be bookmarked or sent to someone.
// Open to everyone who is logged in.

const PAGE_SIZE = 50
const SELECT_CLASS = 'w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-gray-200 focus:border-si-bright/50 focus:outline-none'
const OPTION_CLASS = 'bg-[#0d1429]'

function FilterField({ label, children }) {
  return (
    <label className="block min-w-0">
      <span className="text-[11px] font-medium text-gray-500 mb-1 block">{label}</span>
      {children}
    </label>
  )
}

export default function AuditPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const person = searchParams.get('person') || ''
  const bid = searchParams.get('bid') || ''
  const entityType = searchParams.get('type') || ''
  const action = searchParams.get('action') || ''
  const range = searchParams.get('range') || ''
  const from = searchParams.get('from') || ''
  const to = searchParams.get('to') || ''
  const q = searchParams.get('q') || ''

  const setParams = useCallback((updates) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      for (const [key, value] of Object.entries(updates)) {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      return next
    }, { replace: true })
  }, [setSearchParams])

  // Search box: typed text goes to the address bar after a short pause.
  const [search, setSearch] = useState(q)
  useEffect(() => { setSearch(q) }, [q])
  useEffect(() => {
    if (search === q) return undefined
    const timer = setTimeout(() => setParams({ q: search }), 350)
    return () => clearTimeout(timer)
  }, [search, q, setParams])

  const filters = useMemo(() => ({
    actor: person || undefined,
    job_id: bid || undefined,
    entity_type: entityType || undefined,
    action: action || undefined,
    q: q.trim() || undefined,
    ...dateRangeFilters(range, from, to),
  }), [person, bid, entityType, action, q, range, from, to])

  const fetchPage = useCallback(
    (beforeId) => api.getAudit({ ...filters, before_id: beforeId, limit: PAGE_SIZE }),
    [filters],
  )
  const feed = useAuditFeed(fetchPage)
  const groups = useMemo(() => groupByDay(feed.items), [feed.items])

  const [expanded, setExpanded] = useState(() => new Set())
  const toggle = useCallback((id) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // ── Choices for the filters ──
  const [jobs, setJobs] = useState([])
  useEffect(() => {
    api.listJobs()
      .then(rows => setJobs(Array.isArray(rows) ? rows : []))
      .catch(() => {})
  }, [])

  const [people, setPeople] = useState(() => new Map())
  const addPeople = useCallback((list) => {
    setPeople(prev => {
      let changed = false
      const next = new Map(prev)
      for (const p of list) {
        const key = (p.username || '').toLowerCase()
        if (!key || next.has(key)) continue
        next.set(key, { username: p.username, name: p.name || p.username })
        changed = true
      }
      return changed ? next : prev
    })
  }, [])
  useEffect(() => {
    if (user?.username) addPeople([{ username: user.username, name: user.display_name || user.username }])
    api.getOnlineUsers()
      .then(list => addPeople((Array.isArray(list) ? list : []).map(p => ({ username: p.username, name: p.display_name }))))
      .catch(() => {})
    if (user?.is_admin) {
      api.listPeople()
        .then(list => addPeople((Array.isArray(list) ? list : []).map(p => ({ username: p.username, name: p.display_name }))))
        .catch(() => {})
    }
  }, [user?.username, user?.display_name, user?.is_admin, addPeople])
  useEffect(() => {
    addPeople(feed.items.flatMap(item => entryPeople(item)).filter(p => p.username))
  }, [feed.items, addPeople])

  const [seenTypes, setSeenTypes] = useState(() => new Set(KNOWN_ENTITY_TYPES))
  useEffect(() => {
    setSeenTypes(prev => {
      const missing = feed.items.map(item => item.entity_type).filter(t => t && !prev.has(t))
      return missing.length ? new Set([...prev, ...missing]) : prev
    })
  }, [feed.items])

  const personOptions = [...people.values()].sort((a, b) => a.name.localeCompare(b.name))
  if (person && person !== 'system' && !people.has(person.toLowerCase())) personOptions.unshift({ username: person, name: person })
  const jobOptions = [...jobs].sort((a, b) => String(a.project_name || '').localeCompare(String(b.project_name || '')))
  const bidMissing = bid && !jobs.some(job => String(job.id) === bid)
  const bidMissingName = bidMissing ? feed.items.find(item => String(item.job_id) === bid)?.job_name : ''
  const typeOptions = [...new Set([...seenTypes, ...(entityType ? [entityType] : [])])]
    .map(type => ({ value: type, label: entityLabel(type) }))
    .sort((a, b) => a.label.localeCompare(b.label))
  const actionIsPreset = !action || AUDIT_AREAS.some(area => area.actions.join(',') === action)

  const filtersActive = !!(person || bid || entityType || action || range || q)
  const clearFilters = () => {
    setSearch('')
    setSearchParams({}, { replace: true })
  }

  // ── Infinite scroll: load the next page as the end of the list comes into view ──
  const sentinelRef = useRef(null)
  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !feed.hasMore || feed.error || typeof IntersectionObserver === 'undefined') return undefined
    // The page scrolls inside <main>, so watch against that (and start loading a bit early).
    const observer = new IntersectionObserver(
      (entries) => { if (entries.some(entry => entry.isIntersecting)) feed.loadMore() },
      { root: el.closest('main'), rootMargin: '600px 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [feed.hasMore, feed.error, feed.loadMore, feed.items.length])

  const openInBid = useCallback((item) => {
    navigate(`/jobs/${item.job_id}?history=${item.id}`)
  }, [navigate])

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end gap-4 mb-6">
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-extrabold text-white tracking-tight">Audit</h1>
          <p className="text-sm text-gray-500 mt-1">
            Every change anyone made in the bid tool, newest first. Click a change on a bid to see it on that bid.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => feed.reload({ keepItems: true })}
            disabled={feed.loading}
            className="btn-secondary text-sm px-3"
            title="Check for new changes"
          >
            <RefreshCw className={`w-4 h-4 ${feed.loading && feed.items.length ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
          <a
            href={api.auditExportUrl(filters)}
            download
            className="btn-secondary text-sm px-3"
            title="Download these changes (with the current filters) as a spreadsheet file"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </a>
        </div>
      </div>

      {/* Filters */}
      <div className="glass-card p-4 mb-6 space-y-3">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search summaries, values, bid names, people..."
            className="w-full bg-white/[0.04] border border-white/10 rounded-lg pl-9 pr-9 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
          />
          {search && (
            <button
              type="button"
              onClick={() => { setSearch(''); setParams({ q: '' }) }}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-600 hover:text-gray-300"
              title="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <FilterField label="Person">
            <select value={person} onChange={e => setParams({ person: e.target.value })} className={SELECT_CLASS}>
              <option value="" className={OPTION_CLASS}>Everyone</option>
              {personOptions.map(p => <option key={p.username} value={p.username} className={OPTION_CLASS}>{p.name}</option>)}
              <option value="system" className={OPTION_CLASS}>System (automatic changes)</option>
            </select>
          </FilterField>
          <FilterField label="Bid">
            <select value={bid} onChange={e => setParams({ bid: e.target.value })} className={SELECT_CLASS}>
              <option value="" className={OPTION_CLASS}>All bids</option>
              {bidMissing && <option value={bid} className={OPTION_CLASS}>{bidMissingName || `Bid #${bid}`}</option>}
              {jobOptions.map(job => (
                <option key={job.id} value={String(job.id)} className={OPTION_CLASS}>{job.project_name || `Bid #${job.id}`}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Kind of thing">
            <select value={entityType} onChange={e => setParams({ type: e.target.value })} className={SELECT_CLASS}>
              <option value="" className={OPTION_CLASS}>Everything</option>
              {typeOptions.map(option => <option key={option.value} value={option.value} className={OPTION_CLASS}>{option.label}</option>)}
            </select>
          </FilterField>
          <FilterField label="What happened">
            <select value={action} onChange={e => setParams({ action: e.target.value })} className={SELECT_CLASS}>
              <option value="" className={OPTION_CLASS}>Anything</option>
              {!actionIsPreset && <option value={action} className={OPTION_CLASS}>{actionLabel(action)}</option>}
              {AUDIT_AREAS.map(area => (
                <option key={area.key} value={area.actions.join(',')} className={OPTION_CLASS}>{area.label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="When">
            <select
              value={range}
              onChange={e => setParams(e.target.value === 'custom' ? { range: 'custom' } : { range: e.target.value, from: '', to: '' })}
              className={SELECT_CLASS}
            >
              {DATE_PRESETS.map(preset => <option key={preset.key} value={preset.key} className={OPTION_CLASS}>{preset.label}</option>)}
            </select>
          </FilterField>
        </div>
        {range === 'custom' && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <span>From</span>
            <input type="date" value={from} onChange={e => setParams({ from: e.target.value })} aria-label="From date"
              className="bg-white/[0.04] border border-white/10 rounded-lg px-2 py-1.5 text-sm text-gray-200 [color-scheme:dark]" />
            <span>to</span>
            <input type="date" value={to} onChange={e => setParams({ to: e.target.value })} aria-label="To date"
              className="bg-white/[0.04] border border-white/10 rounded-lg px-2 py-1.5 text-sm text-gray-200 [color-scheme:dark]" />
          </div>
        )}
        {filtersActive && (
          <div className="flex items-center justify-between gap-3 pt-1">
            <span className="text-xs text-gray-500">
              {feed.ready ? `${feed.items.length}${feed.hasMore ? '+' : ''} matching change${feed.items.length === 1 && !feed.hasMore ? '' : 's'}` : ' '}
            </span>
            <button type="button" onClick={clearFilters} className="text-xs font-medium text-si-bright hover:text-blue-300">
              Clear all filters
            </button>
          </div>
        )}
      </div>

      {/* List */}
      {feed.error && feed.items.length === 0 ? (
        <div className="glass-card p-8 text-center">
          <AlertTriangle className="w-6 h-6 text-amber-400 mx-auto mb-3" />
          <p className="text-sm text-gray-300">{historyErrorText(feed.error)}</p>
          <button type="button" onClick={() => feed.reload()} className="btn-secondary text-sm mt-4 inline-flex">
            <RefreshCw className="w-4 h-4" /> Try again
          </button>
        </div>
      ) : feed.loading && feed.items.length === 0 ? (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
        </div>
      ) : feed.items.length === 0 ? (
        <div className="glass-card p-8 text-center">
          <p className="text-sm text-gray-400">{filtersActive ? 'No changes match these filters.' : 'No changes have been recorded yet.'}</p>
          {filtersActive && (
            <button type="button" onClick={clearFilters} className="mt-2 text-xs font-medium text-si-bright hover:text-blue-300">
              Clear all filters
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map(group => (
            <section key={group.label}>
              <div className="flex items-center gap-3 mb-2 px-1">
                <span className="text-[11px] font-bold text-gray-500 uppercase tracking-[0.15em]">{group.label}</span>
                <div className="flex-1 h-px bg-white/[0.06]" />
                <span className="text-[10px] text-gray-600 tabular-nums">{group.items.length}</span>
              </div>
              <ul className="glass-card p-1.5 space-y-0.5">
                {group.items.map(item => (
                  <HistoryEntry
                    key={item.id}
                    item={item}
                    expanded={expanded.has(item.id)}
                    onToggle={toggle}
                    onOpen={openInBid}
                    showJob
                  />
                ))}
              </ul>
            </section>
          ))}

          <div ref={sentinelRef} className="py-4 text-center">
            {feed.error && (
              <p className="text-xs text-red-400 mb-2">{historyErrorText(feed.error)}</p>
            )}
            {feed.hasMore ? (
              <button
                type="button"
                onClick={() => feed.loadMore()}
                disabled={feed.loadingMore}
                className="btn-secondary text-xs px-4 py-1.5 inline-flex"
              >
                {feed.loadingMore && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {feed.loadingMore ? 'Loading...' : 'Load more'}
              </button>
            ) : (
              <p className="text-[11px] text-gray-600">That's everything{filtersActive ? ' that matches' : ''}.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
