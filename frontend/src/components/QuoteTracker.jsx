import { useState, useEffect, useMemo } from 'react'
import {
  Clock, Check, AlertTriangle, Send, RefreshCw, Loader2,
  ChevronDown, ChevronRight, Trash2, Mail, Sparkles, ExternalLink
} from 'lucide-react'
import { api } from '../api'

/**
 * QuoteTracker — shows status of all quote requests for a job.
 *
 * Props:
 *   job: full job object
 *   onRefresh: () => void (reload job data)
 */
export default function QuoteTracker({ job, onRefresh }) {
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [resendingId, setResendingId] = useState(null)
  const [followUpId, setFollowUpId] = useState(null)
  const [followUpText, setFollowUpText] = useState(null)

  const loadRequests = async () => {
    try {
      const data = await api.listQuoteRequests(job.id)
      setRequests(data)
    } catch (err) {
      console.error('Failed to load quote requests:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadRequests() }, [job.id, job])

  const getStatus = (req) => {
    if (req.received_at) return 'received'
    if (req.sent_at) {
      const sentDate = new Date(req.sent_at)
      const daysSince = Math.floor((Date.now() - sentDate.getTime()) / (1000 * 60 * 60 * 24))
      if (daysSince >= 3) return 'overdue'
      return 'waiting'
    }
    return 'draft'
  }

  const getDaysSinceSent = (req) => {
    if (!req.sent_at) return 0
    return Math.floor((Date.now() - new Date(req.sent_at).getTime()) / (1000 * 60 * 60 * 24))
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return '—'
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  const handleDelete = async (id) => {
    setDeletingId(id)
    try {
      await api.deleteQuoteRequest(id)
      await loadRequests()
    } catch (err) {
      console.error('Delete failed:', err)
    } finally {
      setDeletingId(null)
    }
  }

  const handleResend = async (req) => {
    setResendingId(req.id)
    try {
      const materialIndices = (req.material_ids || []).map(id => {
        const mat = (job.materials || []).find(m => m.id === id)
        return mat ? (job.materials || []).indexOf(mat) : -1
      }).filter(i => i >= 0)

      const result = await api.generateQuoteText(job.id, {
        vendor_name: req.vendor_name,
        material_indices: materialIndices,
      })
      // Copy to clipboard
      try {
        await navigator.clipboard.writeText(result.text)
      } catch {
        const ta = document.createElement('textarea')
        ta.value = result.text
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      // Update request text
      await api.updateQuoteRequest(req.id, { request_text: result.text })
      await loadRequests()
    } catch (err) {
      console.error('Resend failed:', err)
    } finally {
      setResendingId(null)
    }
  }

  const handleFollowUp = async (req) => {
    setFollowUpId(req.id)
    setFollowUpText(null)
    try {
      const settings = await api.getSettings()
      const days = getDaysSinceSent(req)
      // Generate follow-up text via AI
      const result = await api.generateQuoteText(job.id, {
        vendor_name: req.vendor_name,
        material_indices: [],
        follow_up: true,
        days_since_sent: days,
      })
      setFollowUpText(result.text)
    } catch (err) {
      console.error('Follow-up generation failed:', err)
      setFollowUpText('Failed to generate follow-up text.')
    } finally {
      setFollowUpId(null)
    }
  }

  const handleMarkReceived = async (req) => {
    try {
      await api.updateQuoteRequest(req.id, {
        status: 'received',
        received_at: new Date().toISOString(),
      })
      await loadRequests()
      if (onRefresh) onRefresh()
    } catch (err) {
      console.error('Mark received failed:', err)
    }
  }

  // Get material names for a request
  const getMaterialNames = (req) => {
    const ids = req.material_ids || []
    return ids.map(id => {
      const mat = (job.materials || []).find(m => m.id === id)
      return mat ? (mat.description || mat.item_code || `#${id}`) : `#${id}`
    })
  }

  const statusConfig = {
    draft: { icon: Mail, color: 'text-gray-400', bg: 'bg-gray-500/10', label: 'Draft', border: 'border-gray-500/20' },
    waiting: { icon: Clock, color: 'text-blue-400', bg: 'bg-blue-500/10', label: 'Waiting', border: 'border-blue-500/20' },
    overdue: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', label: 'Overdue', border: 'border-amber-500/20' },
    received: { icon: Check, color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: 'Received', border: 'border-emerald-500/20' },
  }

  // Summary stats
  const stats = useMemo(() => {
    const s = { total: requests.length, draft: 0, waiting: 0, overdue: 0, received: 0 }
    requests.forEach(r => { s[getStatus(r)]++ })
    return s
  }, [requests])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-xs py-3">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading quote requests...
      </div>
    )
  }

  if (requests.length === 0) return null

  return (
    <div className="space-y-3">
      {/* Header with stats */}
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-bold text-gray-500 uppercase tracking-[0.15em]">Quote Tracker</h4>
        <div className="flex items-center gap-2">
          {stats.waiting > 0 && (
            <span className="text-[10px] text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded flex items-center gap-1">
              <Clock className="w-3 h-3" /> {stats.waiting} waiting
            </span>
          )}
          {stats.overdue > 0 && (
            <span className="text-[10px] text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" /> {stats.overdue} overdue
            </span>
          )}
          {stats.received > 0 && (
            <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded flex items-center gap-1">
              <Check className="w-3 h-3" /> {stats.received} received
            </span>
          )}
        </div>
      </div>

      {/* Request rows */}
      <div className="space-y-2">
        {requests.map(req => {
          const status = getStatus(req)
          const config = statusConfig[status]
          const StatusIcon = config.icon
          const isExpanded = expandedId === req.id
          const days = getDaysSinceSent(req)
          const matNames = getMaterialNames(req)

          return (
            <div key={req.id} className={`rounded-xl border ${config.border} ${config.bg} transition-colors`}>
              {/* Row header */}
              <div
                className="flex items-center gap-3 px-4 py-2.5 cursor-pointer"
                onClick={() => setExpandedId(isExpanded ? null : req.id)}
              >
                {isExpanded
                  ? <ChevronDown className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                  : <ChevronRight className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                }
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white">{req.vendor_name}</span>
                    <span className="text-[10px] text-gray-500">{matNames.length} item{matNames.length !== 1 ? 's' : ''}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    {req.sent_at && (
                      <span className="text-[10px] text-gray-500">Sent {formatDate(req.sent_at)}</span>
                    )}
                    {req.received_at && (
                      <span className="text-[10px] text-emerald-400">Received {formatDate(req.received_at)}</span>
                    )}
                  </div>
                </div>

                {/* Status pill */}
                <div className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium ${config.color} ${config.bg}`}>
                  <StatusIcon className="w-3 h-3" />
                  {config.label}
                  {status === 'waiting' && days > 0 && ` (${days}d)`}
                  {status === 'overdue' && ` (${days}d)`}
                </div>

                {/* Quick actions */}
                <div className="flex items-center gap-1 flex-shrink-0" onClick={e => e.stopPropagation()}>
                  {status === 'overdue' && (
                    <button
                      onClick={() => handleFollowUp(req)}
                      disabled={followUpId === req.id}
                      className="text-[10px] text-amber-400 hover:text-amber-300 bg-amber-500/10 px-2 py-1 rounded-lg flex items-center gap-1"
                      title="Generate follow-up message"
                    >
                      {followUpId === req.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                      Follow Up
                    </button>
                  )}
                  {(status === 'waiting' || status === 'overdue') && (
                    <button
                      onClick={() => handleMarkReceived(req)}
                      className="text-[10px] text-emerald-400 hover:text-emerald-300 bg-emerald-500/10 px-2 py-1 rounded-lg flex items-center gap-1"
                      title="Mark as received"
                    >
                      <Check className="w-3 h-3" /> Received
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(req.id)}
                    disabled={deletingId === req.id}
                    className="text-gray-600 hover:text-red-400 p-1 transition-colors"
                    title="Delete request"
                  >
                    {deletingId === req.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                  </button>
                </div>
              </div>

              {/* Expanded content */}
              {isExpanded && (
                <div className="px-4 pb-3 space-y-2 border-t border-white/[0.04]">
                  {/* Materials */}
                  <div className="pt-2">
                    <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-1">Requested Materials</p>
                    <div className="space-y-0.5">
                      {matNames.map((name, i) => (
                        <p key={i} className="text-xs text-gray-400 truncate">
                          <span className="text-gray-600 mr-1">{i + 1}.</span> {name}
                        </p>
                      ))}
                    </div>
                  </div>

                  {/* Follow-up text */}
                  {followUpText && followUpId === null && expandedId === req.id && (
                    <div className="mt-2 space-y-2">
                      <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider">Follow-Up Message</p>
                      <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 max-h-40 overflow-y-auto">
                        <pre className="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">{followUpText}</pre>
                      </div>
                      <button
                        onClick={async () => {
                          try { await navigator.clipboard.writeText(followUpText) } catch {}
                        }}
                        className="text-xs text-gray-400 hover:text-white flex items-center gap-1.5"
                      >
                        <ExternalLink className="w-3 h-3" /> Copy follow-up
                      </button>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="flex items-center gap-2 pt-1">
                    {status !== 'received' && (
                      <button
                        onClick={() => handleResend(req)}
                        disabled={resendingId === req.id}
                        className="text-xs text-gray-400 hover:text-white flex items-center gap-1.5 bg-white/[0.04] px-2.5 py-1.5 rounded-lg"
                      >
                        {resendingId === req.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                        Regenerate & Copy
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
