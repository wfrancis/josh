import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertTriangle, History, Link2, Loader2, MessageSquare, RefreshCw, Search, Send, X,
} from 'lucide-react'
import { api } from '../api'
import { formatWhen } from '../bidTracker'
import HistoryEntry from './HistoryEntry'
import useAuditFeed, { historyErrorText } from './useAuditFeed'
import { DATE_PRESETS, HISTORY_TYPES, dateRangeFilters, entryPeople, groupByDay } from './fieldLabels'

// The bid's History drawer: every change to this bid, grouped (several quick
// edits of one field are one entry), with filters, plus the bid's comments.
// focusId: an entry to scroll to and open (from /jobs/:id?history=<id>).

const PAGE_SIZE = 50
// How many pages to look through for a linked entry before showing it on its own.
const FOCUS_MAX_PAGES = 20
// With system changes hidden, fetch a few more pages rather than show a near-empty list.
const FILL_MIN_VISIBLE = 15
const FILL_MAX_PAGES = 5

function useDebounced(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

function Chip({ active, onClick, children, title }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors whitespace-nowrap
        ${active
          ? 'bg-si-bright/20 text-blue-300'
          : 'bg-white/[0.04] text-gray-500 hover:text-gray-300 hover:bg-white/[0.08]'}`}
    >
      {children}
    </button>
  )
}

function TabButton({ active, onClick, icon: Icon, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors
        ${active ? 'bg-white/[0.08] text-white' : 'text-gray-500 hover:text-gray-300'}`}
    >
      <Icon className="w-3.5 h-3.5" />
      {children}
    </button>
  )
}

function CommentsTab({ jobId, comments, error, onAdded }) {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    const value = text.trim()
    if (!value || sending) return
    setSending(true)
    setSendError('')
    try {
      await api.addComment(jobId, value)
      setText('')
      onAdded()
    } catch (err) {
      setSendError(err.message || "The comment couldn't be saved.")
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="px-5 py-4">
      <form onSubmit={submit} className="mb-4">
        <div className="flex gap-2">
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e) }}
            placeholder="Add a comment for everyone on this bid..."
            rows={2}
            className="flex-1 bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none resize-y"
          />
          <button
            type="submit"
            disabled={!text.trim() || sending}
            className="btn-primary px-3 py-2 text-sm self-start"
            title="Post comment"
          >
            {sending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          </button>
        </div>
        {sendError && <p className="mt-2 text-xs text-red-400">{sendError}</p>}
      </form>

      {error && <p className="text-xs text-red-400 mb-3">{error}</p>}
      {comments === null && !error ? (
        <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 text-gray-600 animate-spin" /></div>
      ) : comments && comments.length === 0 ? (
        <p className="text-xs text-gray-600 text-center py-8">No comments yet.</p>
      ) : (
        <ul className="space-y-2.5">
          {(comments || []).map(comment => (
            <li key={comment.id} className="bg-white/[0.03] border border-white/[0.04] rounded-lg px-3 py-2">
              <p className="text-sm text-gray-200 whitespace-pre-wrap break-words">{comment.text}</p>
              <p className="mt-1 text-[11px] text-gray-500">
                {comment.user && comment.user !== 'System' ? `${comment.user} · ` : ''}{formatWhen(comment.created_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function BidHistoryPanel({ jobId, jobName, focusId = null, onClose }) {
  const [tab, setTab] = useState('history')
  const [person, setPerson] = useState('')
  const [type, setType] = useState('')
  const [search, setSearch] = useState('')
  const q = useDebounced(search.trim(), 300)
  const [range, setRange] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [showSystem, setShowSystem] = useState(false)
  const [expanded, setExpanded] = useState(() => new Set(focusId ? [focusId] : []))
  const [people, setPeople] = useState(() => new Map())
  const [comments, setComments] = useState(null)
  const [commentsError, setCommentsError] = useState('')
  // Linked entry: 'searching' the list for it, 'found', or 'missing' (shown on its own).
  const [focusStatus, setFocusStatus] = useState(focusId ? 'searching' : null)
  const [linkedItem, setLinkedItem] = useState(null)
  const focusPagesRef = useRef(0)
  const fillPagesRef = useRef(0)
  const closeRef = useRef(null)

  const filters = useMemo(() => {
    const kind = HISTORY_TYPES.find(t => t.key === type)
    return {
      actor: person || undefined,
      action: kind ? kind.actions.join(',') : undefined,
      q: q || undefined,
      ...dateRangeFilters(range, from, to),
    }
  }, [person, type, q, range, from, to])

  const fetchPage = useCallback(
    (beforeId) => api.getJobHistory(jobId, { ...filters, before_id: beforeId, limit: PAGE_SIZE }),
    [jobId, filters],
  )
  const feed = useAuditFeed(fetchPage)

  // ── Comments ──
  const loadComments = useCallback(() => {
    api.getComments(jobId)
      .then(list => { setComments(Array.isArray(list) ? list : []); setCommentsError('') })
      .catch(err => setCommentsError(err.message || "Comments couldn't be loaded."))
  }, [jobId])
  useEffect(() => { loadComments() }, [loadComments])

  // ── Close on Escape; start with focus on the close button ──
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onCloseRef.current?.() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  // ── Everyone seen so far, for the people chips ──
  useEffect(() => {
    setPeople(prev => {
      let changed = false
      const next = new Map(prev)
      for (const item of feed.items) {
        for (const p of entryPeople(item)) {
          const key = (p.username || '').toLowerCase()
          if (key && !next.has(key)) { next.set(key, { username: p.username, name: p.name }); changed = true }
        }
      }
      return changed ? next : prev
    })
  }, [feed.items])

  const includeSystem = showSystem || person === 'system'
  const visible = useMemo(
    () => (includeSystem ? feed.items : feed.items.filter(item => item.actor_kind !== 'system' || item.id === focusId)),
    [feed.items, includeSystem, focusId],
  )
  const hiddenSystemCount = feed.items.length - visible.length
  const groups = useMemo(() => groupByDay(visible), [visible])

  // ── Linked entry (?history=<id>) ──
  useEffect(() => {
    if (!focusId) return undefined
    let cancelled = false
    api.getAuditItem(focusId)
      .then(item => { if (!cancelled) setLinkedItem(item) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [focusId])

  // Changing a filter means the person has moved on from the linked entry.
  const filtersKey = JSON.stringify(filters)
  const initialFiltersKey = useRef(filtersKey)
  useEffect(() => {
    if (filtersKey !== initialFiltersKey.current) setFocusStatus(status => (status === 'searching' ? null : status))
  }, [filtersKey])

  useEffect(() => {
    if (focusStatus !== 'searching' || !feed.ready || feed.loadingMore) return
    if (feed.items.some(item => item.id === focusId)) {
      setFocusStatus('found')
      return
    }
    if (feed.error) {
      setFocusStatus('missing')
      return
    }
    const oldest = feed.items[feed.items.length - 1]
    if (feed.hasMore && (!oldest || oldest.id > focusId) && focusPagesRef.current < FOCUS_MAX_PAGES) {
      focusPagesRef.current += 1
      feed.loadMore()
      return
    }
    setFocusStatus('missing')
  }, [focusStatus, feed.ready, feed.loadingMore, feed.items, feed.hasMore, feed.error, feed.loadMore, focusId])

  useEffect(() => {
    if (focusStatus !== 'found') return
    const el = document.getElementById(`history-entry-${focusId}`)
    el?.scrollIntoView({ block: 'center' })
  }, [focusStatus, focusId])

  // ── Keep the list filled when system changes are hidden ──
  useEffect(() => { fillPagesRef.current = 0 }, [fetchPage, includeSystem])
  useEffect(() => {
    if (!feed.ready || feed.loadingMore || !feed.hasMore || feed.error) return
    if (visible.length >= FILL_MIN_VISIBLE || fillPagesRef.current >= FILL_MAX_PAGES) return
    fillPagesRef.current += 1
    feed.loadMore()
  }, [feed.ready, feed.loadingMore, feed.hasMore, feed.error, feed.loadMore, visible.length])

  const toggle = useCallback((id) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const filtersActive = !!(person || type || search.trim() || range)
  const clearFilters = () => {
    setPerson('')
    setType('')
    setSearch('')
    setRange('')
    setFrom('')
    setTo('')
  }

  const peopleList = [...people.values()].sort((a, b) => a.name.localeCompare(b.name))
  if (person && person !== 'system' && !people.has(person.toLowerCase())) peopleList.unshift({ username: person, name: person })
  const showLinkedAlone = linkedItem && focusStatus === 'missing'

  return createPortal(
    <div className="fixed inset-0 z-[70] flex justify-end" role="dialog" aria-modal="true" aria-labelledby="bid-history-title">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" onClick={onClose} />
      <aside className="relative flex h-full w-full sm:max-w-[540px] flex-col bg-[#0B1122] border-l border-white/[0.08] shadow-2xl animate-slide-in-right">
        {/* Header */}
        <div className="flex items-start gap-3 px-5 pt-5 pb-3">
          <div className="w-9 h-9 flex-shrink-0 rounded-xl bg-si-bright/10 border border-si-bright/15 flex items-center justify-center">
            <History className="w-4 h-4 text-blue-300" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 id="bid-history-title" className="text-base font-bold text-white">History</h2>
            <p className="text-xs text-gray-500 truncate">{jobName || 'This bid'}: every change, who made it, and when</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="btn-ghost p-2 -mr-2" title="Close history">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 px-5 pb-2 border-b border-white/[0.06]">
          <TabButton active={tab === 'history'} onClick={() => setTab('history')} icon={History}>Changes</TabButton>
          <TabButton active={tab === 'comments'} onClick={() => setTab('comments')} icon={MessageSquare}>
            Comments{comments ? ` (${comments.length})` : ''}
          </TabButton>
          {tab === 'history' && (
            <button
              type="button"
              onClick={() => feed.reload({ keepItems: true })}
              disabled={feed.loading}
              className="ml-auto p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-white/[0.06] disabled:opacity-40"
              title="Check for new changes"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${feed.loading && feed.items.length ? 'animate-spin' : ''}`} />
            </button>
          )}
        </div>

        {tab === 'comments' ? (
          <div className="flex-1 overflow-y-auto">
            <CommentsTab
              jobId={jobId}
              comments={comments}
              error={commentsError}
              onAdded={() => { loadComments(); feed.reload({ keepItems: true }) }}
            />
          </div>
        ) : (
          <>
            {/* Filters */}
            <div className="px-5 py-3 space-y-2.5 border-b border-white/[0.06]">
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                <input
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search changes, values, names..."
                  className="w-full bg-white/[0.04] border border-white/10 rounded-lg pl-9 pr-3 py-2 text-xs text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                />
              </div>
              <div className="flex flex-wrap gap-1">
                <Chip active={!type} onClick={() => setType('')}>All</Chip>
                {HISTORY_TYPES.map(kind => (
                  <Chip key={kind.key} active={type === kind.key} onClick={() => setType(type === kind.key ? '' : kind.key)}>
                    {kind.label}
                  </Chip>
                ))}
              </div>
              {peopleList.length > 1 || person ? (
                <div className="flex flex-wrap gap-1">
                  <Chip active={!person} onClick={() => setPerson('')}>Everyone</Chip>
                  {peopleList.map(p => (
                    <Chip
                      key={p.username}
                      active={person.toLowerCase() === p.username.toLowerCase()}
                      onClick={() => setPerson(person.toLowerCase() === p.username.toLowerCase() ? '' : p.username)}
                      title={`Only changes ${p.name} made or helped make`}
                    >
                      {p.name}
                    </Chip>
                  ))}
                </div>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={range}
                  onChange={e => setRange(e.target.value)}
                  className="bg-white/[0.04] border border-white/10 rounded-md px-2 py-1 text-[11px] text-gray-300 focus:border-si-bright/50 focus:outline-none"
                  aria-label="When"
                >
                  {DATE_PRESETS.map(preset => <option key={preset.key} value={preset.key} className="bg-[#0d1429]">{preset.label}</option>)}
                </select>
                {range === 'custom' && (
                  <span className="inline-flex items-center gap-1 text-[11px] text-gray-500">
                    <input type="date" value={from} onChange={e => setFrom(e.target.value)} aria-label="From"
                      className="bg-white/[0.04] border border-white/10 rounded-md px-1.5 py-0.5 text-[11px] text-gray-300 [color-scheme:dark]" />
                    to
                    <input type="date" value={to} onChange={e => setTo(e.target.value)} aria-label="To"
                      className="bg-white/[0.04] border border-white/10 rounded-md px-1.5 py-0.5 text-[11px] text-gray-300 [color-scheme:dark]" />
                  </span>
                )}
                <label className="ml-auto inline-flex items-center gap-1.5 text-[11px] text-gray-500 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={showSystem}
                    onChange={e => setShowSystem(e.target.checked)}
                    className="w-3.5 h-3.5 rounded border-white/10 bg-white/[0.04]"
                  />
                  Show system changes
                </label>
              </div>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto px-3 py-3">
              {showLinkedAlone && (
                <div className="mb-4">
                  <div className="flex items-center gap-1.5 px-2 pb-1.5 text-[11px] font-medium text-gray-500 uppercase tracking-wider">
                    <Link2 className="w-3 h-3" /> Linked change
                  </div>
                  <ul>
                    <HistoryEntry item={linkedItem} expanded={expanded.has(linkedItem.id)} onToggle={toggle} highlighted />
                  </ul>
                </div>
              )}

              {feed.error && !feed.loadingMore && feed.items.length === 0 ? (
                <div className="text-center py-10 px-4">
                  <AlertTriangle className="w-5 h-5 text-amber-400 mx-auto mb-2" />
                  <p className="text-sm text-gray-300">{historyErrorText(feed.error)}</p>
                  <button type="button" onClick={() => feed.reload()} className="btn-secondary text-xs mt-3 inline-flex px-3 py-1.5">
                    <RefreshCw className="w-3.5 h-3.5" /> Try again
                  </button>
                </div>
              ) : feed.loading && feed.items.length === 0 ? (
                <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 text-gray-600 animate-spin" /></div>
              ) : visible.length === 0 && !feed.hasMore ? (
                <div className="text-center py-10 px-4">
                  <p className="text-sm text-gray-400">
                    {filtersActive ? 'Nothing matches these filters.' : feed.items.length ? 'Only system changes so far.' : 'No changes recorded for this bid yet.'}
                  </p>
                  {filtersActive && (
                    <button type="button" onClick={clearFilters} className="mt-2 text-xs font-medium text-si-bright hover:text-blue-300">Clear filters</button>
                  )}
                  {!filtersActive && hiddenSystemCount > 0 && (
                    <button type="button" onClick={() => setShowSystem(true)} className="mt-2 text-xs font-medium text-si-bright hover:text-blue-300">
                      Show {hiddenSystemCount} system change{hiddenSystemCount === 1 ? '' : 's'}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  {groups.map(group => (
                    <section key={group.label} className="mb-3 last:mb-0">
                      <div className="sticky top-0 z-10 -mx-3 px-5 py-1.5 bg-[#0B1122]/95 backdrop-blur flex items-center gap-3">
                        <span className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">{group.label}</span>
                        <div className="flex-1 h-px bg-white/[0.06]" />
                      </div>
                      <ul className="space-y-0.5">
                        {group.items.map(item => (
                          <HistoryEntry
                            key={item.id}
                            item={item}
                            expanded={expanded.has(item.id)}
                            onToggle={toggle}
                            highlighted={item.id === focusId && focusStatus === 'found'}
                          />
                        ))}
                      </ul>
                    </section>
                  ))}

                  <div className="pt-3 pb-2 text-center">
                    {feed.error && feed.items.length > 0 && (
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
                        Load more
                      </button>
                    ) : visible.length > 0 ? (
                      <p className="text-[11px] text-gray-600">
                        That's everything{hiddenSystemCount > 0 && !includeSystem ? ` (${hiddenSystemCount} system change${hiddenSystemCount === 1 ? '' : 's'} hidden)` : ''}.
                      </p>
                    ) : null}
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </aside>
    </div>,
    document.body,
  )
}
