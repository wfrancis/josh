import { useState, useMemo } from 'react'
import { Clock, ChevronDown, ChevronUp, Send, MessageSquare, Search, ArrowUpDown } from 'lucide-react'
import { api } from '../api'

const ACTION_COLORS = {
  job_created: 'bg-emerald-400',
  bid_generated: 'bg-emerald-400',
  rfms_uploaded: 'bg-blue-400',
  quotes_uploaded: 'bg-blue-400',
  materials_updated: 'bg-amber-400',
  quote_updated: 'bg-amber-400',
  notes_updated: 'bg-amber-400',
  exclusions_updated: 'bg-amber-400',
  job_updated: 'bg-amber-400',
  bid_calculated: 'bg-amber-400',
  ai_estimate: 'bg-violet-400',
  comment_added: 'bg-gray-400',
  quotes_cleared: 'bg-red-400',
  bid_cleared: 'bg-red-400',
}

const FILTER_ACTIONS = {
  uploads: ['rfms_uploaded', 'quotes_uploaded'],
  updates: ['materials_updated', 'quote_updated', 'notes_updated', 'exclusions_updated', 'job_updated', 'bid_calculated', 'job_created'],
  quotes: ['quotes_uploaded', 'quote_updated'],
  ai: ['ai_estimate'],
  cleared: ['quotes_cleared', 'bid_cleared'],
}

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'uploads', label: 'Uploads' },
  { key: 'updates', label: 'Updates' },
  { key: 'quotes', label: 'Quotes' },
  { key: 'ai', label: 'AI' },
  { key: 'cleared', label: 'Cleared' },
]

function relativeTime(isoString) {
  const now = new Date()
  const then = new Date(isoString)
  const seconds = Math.floor((now - then) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return then.toLocaleDateString()
}

function formatDate(isoString) {
  const d = new Date(isoString)
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function dayLabel(isoString) {
  const d = new Date(isoString)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = Math.floor((today - target) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function ChangesDetail({ changes }) {
  return (
    <div className="mt-1.5 space-y-1">
      {Object.entries(changes).map(([field, vals]) => (
        <div key={field} className="text-xs">
          <span className="text-gray-500">{field}:</span>{' '}
          <span className="text-red-400/70 line-through">{String(vals.old ?? '(empty)')}</span>
          {' → '}
          <span className="text-emerald-400/70">{String(vals.new ?? '(empty)')}</span>
        </div>
      ))}
    </div>
  )
}

export default function ActivityLog({ jobId }) {
  const [open, setOpen] = useState(false)
  const [activities, setActivities] = useState([])
  const [comments, setComments] = useState([])
  const [commentText, setCommentText] = useState('')
  const [sending, setSending] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [tab, setTab] = useState('activity')

  // New state for search, filter, sort
  const [searchQuery, setSearchQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState('all')
  const [sortOrder, setSortOrder] = useState('newest')

  const loadData = async () => {
    try {
      const [acts, cmts] = await Promise.all([
        api.getActivity(jobId),
        api.getComments(jobId),
      ])
      setActivities(acts)
      setComments(cmts)
      setLoaded(true)
    } catch (err) {
      console.error('Failed to load activity:', err)
    }
  }

  const handleToggle = () => {
    const next = !open
    setOpen(next)
    if (next && !loaded) loadData()
  }

  const handleSubmitComment = async (e) => {
    e.preventDefault()
    if (!commentText.trim() || sending) return
    setSending(true)
    try {
      await api.addComment(jobId, commentText.trim())
      setCommentText('')
      loadData()
    } catch (err) {
      console.error('Failed to add comment:', err)
    } finally {
      setSending(false)
    }
  }

  // Filtered, sorted, grouped activities
  const groupedActivities = useMemo(() => {
    let filtered = [...activities]

    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      filtered = filtered.filter(a =>
        a.summary.toLowerCase().includes(q) ||
        (a.detail?.files || []).some(f => f.toLowerCase().includes(q)) ||
        (a.detail?.changes && Object.keys(a.detail.changes).some(k => k.toLowerCase().includes(q)))
      )
    }

    // Category filter
    if (activeFilter !== 'all') {
      const allowed = FILTER_ACTIONS[activeFilter] || []
      filtered = filtered.filter(a => allowed.includes(a.action))
    }

    // Sort
    filtered.sort((a, b) => {
      const cmp = new Date(b.created_at) - new Date(a.created_at)
      return sortOrder === 'newest' ? cmp : -cmp
    })

    // Group by day
    const groups = []
    let currentLabel = null
    for (const a of filtered) {
      const label = dayLabel(a.created_at)
      if (label !== currentLabel) {
        currentLabel = label
        groups.push({ label, items: [] })
      }
      groups[groups.length - 1].items.push(a)
    }
    return groups
  }, [activities, searchQuery, activeFilter, sortOrder])

  const totalCount = activities.length + comments.length
  const filteredCount = groupedActivities.reduce((sum, g) => sum + g.items.length, 0)

  return (
    <div className="glass-card p-4 mt-6">
      <button
        onClick={handleToggle}
        className="flex items-center justify-between w-full text-left"
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-400">
          <Clock className="w-4 h-4" />
          Activity Log
          {loaded && totalCount > 0 && (
            <span className="text-xs bg-white/[0.06] px-2 py-0.5 rounded-full text-gray-500">
              {totalCount}
            </span>
          )}
        </div>
        {open ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
      </button>

      {open && (
        <div className="mt-4">
          {/* Tabs */}
          <div className="flex gap-1 mb-4 border-b border-white/[0.06] pb-2">
            <button
              onClick={() => setTab('activity')}
              className={`text-xs font-medium px-3 py-1.5 rounded-lg transition-colors ${
                tab === 'activity'
                  ? 'bg-white/[0.08] text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <Clock className="w-3 h-3 inline mr-1" />
              Timeline ({activities.length})
            </button>
            <button
              onClick={() => setTab('comments')}
              className={`text-xs font-medium px-3 py-1.5 rounded-lg transition-colors ${
                tab === 'comments'
                  ? 'bg-white/[0.08] text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <MessageSquare className="w-3 h-3 inline mr-1" />
              Comments ({comments.length})
            </button>
          </div>

          {/* Activity Timeline */}
          {tab === 'activity' && (
            <div>
              {/* Search + Filter bar */}
              <div className="space-y-3 mb-4">
                {/* Search */}
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    placeholder="Search activities..."
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg pl-9 pr-3 py-2 text-xs text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                  />
                </div>

                {/* Filters + Sort */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex gap-1 flex-wrap">
                    {FILTERS.map(f => (
                      <button
                        key={f.key}
                        onClick={() => setActiveFilter(f.key)}
                        className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${
                          activeFilter === f.key
                            ? 'bg-si-bright/20 text-si-bright'
                            : 'bg-white/[0.04] text-gray-500 hover:text-gray-300 hover:bg-white/[0.08]'
                        }`}
                      >
                        {f.label}
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={() => setSortOrder(s => s === 'newest' ? 'oldest' : 'newest')}
                    className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-300 transition-colors flex-shrink-0"
                  >
                    <ArrowUpDown className="w-3 h-3" />
                    {sortOrder === 'newest' ? 'Newest' : 'Oldest'}
                  </button>
                </div>
              </div>

              {/* Grouped timeline */}
              <div className="max-h-96 overflow-y-auto pr-1">
                {filteredCount === 0 ? (
                  <p className="text-xs text-gray-600 text-center py-4">
                    {activities.length === 0 ? 'No activity yet' : 'No matching activities'}
                  </p>
                ) : (
                  groupedActivities.map(group => (
                    <div key={group.label} className="mb-4 last:mb-0">
                      {/* Day header */}
                      <div className="flex items-center gap-3 mb-2">
                        <span className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">{group.label}</span>
                        <div className="flex-1 h-px bg-white/[0.06]" />
                        <span className="text-[10px] text-gray-600">{group.items.length}</span>
                      </div>

                      {/* Items */}
                      <div className="space-y-2.5 pl-1">
                        {group.items.map(a => (
                          <div key={a.id} className="flex items-start gap-3 text-sm">
                            <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${ACTION_COLORS[a.action] || 'bg-gray-500'}`} />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-baseline gap-2 flex-wrap">
                                <span className="text-gray-300 text-sm">{a.summary}</span>
                                <span className="text-gray-600 text-xs flex-shrink-0" title={formatDate(a.created_at)}>
                                  {relativeTime(a.created_at)}
                                </span>
                                {a.user && a.user !== 'System' && (
                                  <span className="text-gray-600 text-xs">by {a.user}</span>
                                )}
                              </div>
                              {a.detail?.changes && <ChangesDetail changes={a.detail.changes} />}
                              {a.detail?.files && (
                                <div className="mt-1 text-xs text-gray-600">
                                  Files: {a.detail.files.join(', ')}
                                </div>
                              )}
                              {a.detail?.vendors && a.detail.vendors.length > 0 && (
                                <div className="mt-1 text-xs text-gray-600">
                                  Vendors: {a.detail.vendors.join(', ')}
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* Comments */}
          {tab === 'comments' && (
            <div>
              {/* Input */}
              <form onSubmit={handleSubmitComment} className="flex gap-2 mb-4">
                <input
                  type="text"
                  value={commentText}
                  onChange={e => setCommentText(e.target.value)}
                  placeholder="Add a comment..."
                  className="flex-1 bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={!commentText.trim() || sending}
                  className="btn-primary px-3 py-2 text-sm flex items-center gap-1.5"
                >
                  <Send className="w-3.5 h-3.5" />
                </button>
              </form>

              {/* Comment list */}
              <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
                {comments.length === 0 ? (
                  <p className="text-xs text-gray-600 text-center py-4">No comments yet</p>
                ) : (
                  comments.map(c => (
                    <div key={c.id} className="bg-white/[0.03] rounded-lg px-3 py-2">
                      <p className="text-sm text-gray-300">{c.text}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-gray-600" title={formatDate(c.created_at)}>
                          {relativeTime(c.created_at)}
                        </span>
                        {c.user && c.user !== 'System' && (
                          <span className="text-xs text-gray-600">by {c.user}</span>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
