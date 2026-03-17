import { useState, useEffect, useMemo } from 'react'
import {
  Clock, Check, AlertTriangle, Send, RefreshCw, Loader2,
  ChevronDown, ChevronRight, Trash2, Mail, Sparkles, ExternalLink,
  Phone, User, Building2, X, TrendingUp, Package, FileText, Upload
} from 'lucide-react'
import { api } from '../api'

/**
 * QuoteTracker — shows status of all quote requests for a job.
 *
 * Props:
 *   job: full job object
 *   onRefresh: () => void (reload job data)
 */
export default function QuoteTracker({ job, onRefresh, onUploadQuote }) {
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [resendingId, setResendingId] = useState(null)
  const [followUpId, setFollowUpId] = useState(null)
  const [followUpText, setFollowUpText] = useState(null)
  const [vendorDetails, setVendorDetails] = useState({}) // keyed by vendor_name
  const [vendorLoading, setVendorLoading] = useState(null)
  const [detailModal, setDetailModal] = useState(null) // vendor name for detail modal

  const loadVendorDetail = async (vendorName, vendorId) => {
    if (vendorDetails[vendorName]) return // already loaded
    setVendorLoading(vendorName)
    try {
      if (vendorId) {
        const detail = await api.getVendor(vendorId)
        setVendorDetails(prev => ({ ...prev, [vendorName]: detail }))
      } else {
        // Look up vendor by name from vendor list
        const vendors = await api.listVendors()
        const match = vendors.find(v => v.name.toLowerCase() === vendorName.toLowerCase())
        if (match) {
          const detail = await api.getVendor(match.id)
          setVendorDetails(prev => ({ ...prev, [vendorName]: detail }))
        } else {
          setVendorDetails(prev => ({ ...prev, [vendorName]: null }))
        }
      }
    } catch (err) {
      console.error('Failed to load vendor detail:', err)
      setVendorDetails(prev => ({ ...prev, [vendorName]: null }))
    } finally {
      setVendorLoading(null)
    }
  }

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
      const materialIndices = (req.material_ids || []).map(entry => {
        const isObj = entry && typeof entry === 'object'
        const numId = isObj ? entry.id : entry
        const itemCode = isObj ? entry.item_code : null
        let mat = (job.materials || []).find(m => m.id === numId)
        if (!mat && itemCode) {
          mat = (job.materials || []).find(m => m.item_code && m.item_code.toLowerCase() === itemCode.toLowerCase())
        }
        return mat ? (job.materials || []).indexOf(mat) : -1
      }).filter(i => i >= 0)

      const result = await api.generateQuoteText(job.id, {
        vendor_name: req.vendor_name,
        material_indices: materialIndices,
      })
      // Copy to clipboard (with timeout to prevent hanging)
      try {
        await Promise.race([
          navigator.clipboard.writeText(result.text),
          new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 2000))
        ])
      } catch {
        try {
          const ta = document.createElement('textarea')
          ta.value = result.text
          document.body.appendChild(ta)
          ta.select()
          document.execCommand('copy')
          document.body.removeChild(ta)
        } catch {}
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

  // Get material info for a request (with id for scrolling)
  const getMaterials = (req) => {
    const ids = req.material_ids || []
    // material_ids can be:
    //   - plain numbers (old format): [123, 456]
    //   - objects with item_code (new format): [{id: 123, item_code: "F109"}, ...]
    //   - strings: ["123", "456"]
    return ids.map(entry => {
      const isObj = entry && typeof entry === 'object'
      const numId = isObj ? entry.id : (typeof entry === 'string' ? parseInt(entry, 10) : entry)
      const itemCode = isObj ? entry.item_code : null

      // Try to find material: first by ID, then by item_code
      let mat = (job.materials || []).find(m => m.id === numId || m.id === entry)
      if (!mat && itemCode) {
        mat = (job.materials || []).find(m => m.item_code && m.item_code.toLowerCase() === itemCode.toLowerCase())
      }

      return {
        id: mat?.id || numId,
        name: mat ? (mat.description || mat.item_code || `#${numId}`) : (itemCode || `#${numId}`),
        item_code: mat?.item_code || itemCode || '',
        hasPrice: mat ? (mat.unit_price || 0) > 0 : false,
        priceSource: mat?.price_source || null,
        unitPrice: mat?.unit_price || 0,
        vendor: mat?.vendor || '',
      }
    })
  }

  const scrollToMaterial = (matId) => {
    const el = document.querySelector(`[data-material-id="${matId}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('ring-2', 'ring-si-orange/50')
      setTimeout(() => el.classList.remove('ring-2', 'ring-si-orange/50'), 2000)
    }
  }

  const statusConfig = {
    draft: { icon: Mail, color: 'text-gray-400', bg: 'bg-gray-500/10', label: 'Draft', border: 'border-gray-500/20' },
    waiting: { icon: Clock, color: 'text-blue-400', bg: 'bg-blue-500/10', label: 'Waiting', border: 'border-blue-500/20' },
    overdue: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', label: 'Overdue', border: 'border-amber-500/20' },
    received: { icon: Check, color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: 'Received', border: 'border-emerald-500/20' },
    received_partial: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', label: 'Partial', border: 'border-amber-500/20' },
    received_none: { icon: AlertTriangle, color: 'text-red-400', bg: 'bg-red-500/10', label: 'No Prices', border: 'border-red-500/20' },
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
          const mats = getMaterials(req)
          const pricedCount = mats.filter(m => m.hasPrice).length
          const totalCount = mats.length

          // Override config for received based on pricing completeness
          let effectiveConfig = config
          if (status === 'received' && totalCount > 0) {
            if (pricedCount === 0) effectiveConfig = statusConfig.received_none
            else if (pricedCount < totalCount) effectiveConfig = statusConfig.received_partial
          }
          const EffectiveIcon = effectiveConfig.icon

          return (
            <div key={req.id} className={`rounded-xl border ${effectiveConfig.border} ${effectiveConfig.bg} transition-colors`}>
              {/* Row header */}
              <div
                className="flex items-center gap-3 px-4 py-2.5 cursor-pointer"
                onClick={() => {
                  const nextExpanded = isExpanded ? null : req.id
                  setExpandedId(nextExpanded)
                  if (nextExpanded) loadVendorDetail(req.vendor_name, req.vendor_id)
                }}
              >
                {isExpanded
                  ? <ChevronDown className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                  : <ChevronRight className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                }
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white hover:text-si-orange transition-colors">{req.vendor_name}</span>
                    <span className="text-[10px] text-gray-500">{mats.length} item{mats.length !== 1 ? 's' : ''}</span>
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
                <div className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium ${effectiveConfig.color} ${effectiveConfig.bg}`}>
                  <EffectiveIcon className="w-3 h-3" />
                  {status === 'received'
                    ? (pricedCount === totalCount && totalCount > 0
                        ? `All ${totalCount} priced`
                        : pricedCount === 0 && totalCount > 0
                          ? `0/${totalCount} priced`
                          : `${pricedCount}/${totalCount} priced`)
                    : config.label}
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
                    <>
                      <button
                        onClick={() => onUploadQuote ? onUploadQuote() : handleMarkReceived(req)}
                        className="text-[10px] text-emerald-400 hover:text-emerald-300 bg-emerald-500/10 px-2 py-1 rounded-lg flex items-center gap-1"
                        title="Upload vendor response"
                      >
                        <Upload className="w-3 h-3" /> Upload Response
                      </button>
                      <button
                        onClick={() => handleMarkReceived(req)}
                        className="text-[10px] text-gray-500 hover:text-gray-300 bg-white/[0.04] px-2 py-1 rounded-lg flex items-center gap-1"
                        title="Mark received without uploading"
                      >
                        <Check className="w-3 h-3" />
                      </button>
                    </>
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
                <div className="px-4 pb-3 space-y-3 border-t border-white/[0.04]">
                  {/* Vendor contact info */}
                  {(() => {
                    const vd = vendorDetails[req.vendor_name]
                    const vLoading = vendorLoading === req.vendor_name
                    if (vLoading) return (
                      <div className="flex items-center gap-2 text-gray-500 text-[11px] pt-2">
                        <Loader2 className="w-3 h-3 animate-spin" /> Loading contact info...
                      </div>
                    )
                    if (vd) return (
                      <div className="flex items-center gap-4 pt-2 flex-wrap">
                        {vd.contact_name && (
                          <span className="flex items-center gap-1.5 text-xs text-gray-300">
                            <User className="w-3 h-3 text-gray-500" />
                            {vd.contact_name}
                            {vd.contact_title && <span className="text-gray-600">· {vd.contact_title}</span>}
                          </span>
                        )}
                        {vd.contact_email && (
                          <a href={`mailto:${vd.contact_email}`} className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors" onClick={e => e.stopPropagation()}>
                            <Mail className="w-3 h-3" /> {vd.contact_email}
                          </a>
                        )}
                        {vd.contact_phone && (
                          <a href={`tel:${vd.contact_phone}`} className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-300 transition-colors" onClick={e => e.stopPropagation()}>
                            <Phone className="w-3 h-3" /> {vd.contact_phone}
                          </a>
                        )}
                        {!vd.contact_name && !vd.contact_email && !vd.contact_phone && (
                          <span className="text-[11px] text-gray-600 italic">No contact info on file</span>
                        )}
                        <button
                          onClick={(e) => { e.stopPropagation(); setDetailModal(req.vendor_name) }}
                          className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-si-orange transition-colors ml-auto"
                        >
                          <Building2 className="w-3 h-3" /> View Details
                        </button>
                      </div>
                    )
                    return null
                  })()}

                  {/* Materials — clickable, scrolls to row */}
                  <div className="pt-2">
                    {(() => {
                      const pricedCount = mats.filter(m => m.hasPrice).length
                      const totalCount = mats.length
                      const allPriced = pricedCount === totalCount
                      return (
                        <div className="flex items-center gap-2 mb-1">
                          <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider">Requested Materials</p>
                          {status === 'received' && totalCount > 0 && (
                            <span className={`text-[10px] px-1.5 py-0.5 rounded ${allPriced ? 'text-emerald-400 bg-emerald-500/10' : 'text-amber-400 bg-amber-500/10'}`}>
                              {allPriced ? `All ${totalCount} priced` : `${pricedCount}/${totalCount} priced`}
                            </span>
                          )}
                        </div>
                      )
                    })()}
                    <div className="space-y-0.5">
                      {mats.map((mat, i) => (
                        <button
                          key={i}
                          onClick={() => scrollToMaterial(mat.id)}
                          className="w-full text-left text-xs text-gray-400 hover:text-si-orange truncate flex items-center gap-1 group transition-colors"
                        >
                          {mat.hasPrice ? (
                            <Check className="w-3 h-3 text-emerald-400 flex-shrink-0" />
                          ) : (
                            <span className="w-3 h-3 flex items-center justify-center flex-shrink-0 text-amber-400/60">—</span>
                          )}
                          <span className="text-gray-600 mr-1 flex-shrink-0">{i + 1}.</span>
                          {mat.item_code && <span className="text-gray-500 flex-shrink-0">{mat.item_code} —</span>}
                          <span className={`truncate group-hover:underline ${!mat.hasPrice && status === 'received' ? 'text-amber-400/70' : ''}`}>{mat.name}</span>
                          {mat.hasPrice && mat.unitPrice > 0 && (
                            <span className="text-emerald-400/60 text-[10px] font-mono flex-shrink-0 ml-auto">${mat.unitPrice.toFixed(2)}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Vendor Response — uploaded quote file and/or pricing source */}
                  {status === 'received' && (() => {
                    // Find uploaded quotes matching this vendor
                    const vendorQuotes = (job.quotes || []).filter(q =>
                      (q.vendor || '').toLowerCase().includes(req.vendor_name.toLowerCase()) ||
                      req.vendor_name.toLowerCase().includes((q.vendor || '').toLowerCase().split(',')[0].trim())
                    )
                    const responseFile = req.response_file || vendorQuotes[0]?.file_name || null
                    const hasUploadedQuotes = vendorQuotes.length > 0
                    const pricedMats = mats.filter(m => m.hasPrice)
                    const hasPricing = pricedMats.length > 0

                    // Show response section if we have uploaded quotes OR a response file OR any pricing
                    if (!hasUploadedQuotes && !responseFile && !hasPricing) return null

                    return (
                      <details className="group" open>
                        <summary className="text-[10px] font-bold text-gray-600 uppercase tracking-wider cursor-pointer hover:text-gray-400 flex items-center gap-1">
                          <Upload className="w-3 h-3" /> Vendor Response
                          {hasUploadedQuotes && <span className="text-gray-600 font-normal normal-case">({vendorQuotes.length} products)</span>}
                          {responseFile && <span className="text-gray-700 font-normal normal-case ml-1">— {responseFile}</span>}
                          <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform ml-auto" />
                        </summary>
                        <div className="mt-1.5 space-y-2">
                          {/* Uploaded quote products table */}
                          {hasUploadedQuotes && (
                            <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="border-b border-white/[0.06] text-gray-600">
                                    <th className="text-left py-1.5 pl-3 pr-2 font-medium">Product</th>
                                    <th className="text-right py-1.5 px-2 font-medium">Price</th>
                                    <th className="text-left py-1.5 px-2 font-medium">Unit</th>
                                    {vendorQuotes.some(q => q.lead_time) && <th className="text-left py-1.5 px-2 font-medium">Lead Time</th>}
                                  </tr>
                                </thead>
                                <tbody>
                                  {vendorQuotes.map((q, i) => (
                                    <tr key={i} className="border-t border-white/[0.03] hover:bg-white/[0.02]">
                                      <td className="py-1.5 pl-3 pr-2 text-gray-300 max-w-[200px] truncate">{q.product_name || q.description}</td>
                                      <td className="py-1.5 px-2 text-right text-emerald-400 font-mono">${(q.unit_price || 0).toFixed(2)}</td>
                                      <td className="py-1.5 px-2 text-gray-500">{q.unit || '—'}</td>
                                      {vendorQuotes.some(vq => vq.lead_time) && <td className="py-1.5 px-2 text-gray-500">{q.lead_time || '—'}</td>}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              {vendorQuotes[0]?.freight && (
                                <div className="px-3 py-1.5 border-t border-white/[0.06] text-[10px] text-gray-500">
                                  Freight: {vendorQuotes[0].freight}
                                </div>
                              )}
                              {vendorQuotes[0]?.notes && (
                                <div className="px-3 py-1.5 border-t border-white/[0.03] text-[10px] text-gray-500 italic">
                                  {vendorQuotes[0].notes}
                                </div>
                              )}
                            </div>
                          )}

                          {/* If no uploaded quotes but we have pricing, show where prices came from */}
                          {!hasUploadedQuotes && hasPricing && (
                            <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                              <p className="text-[10px] text-gray-500 mb-1.5">
                                Prices applied from vendor history{responseFile ? ` and uploaded file (${responseFile})` : ''}:
                              </p>
                              <div className="space-y-0.5">
                                {pricedMats.map((mat, i) => (
                                  <div key={i} className="flex items-center justify-between text-xs">
                                    <span className="text-gray-400 truncate mr-2">{mat.item_code || mat.name}</span>
                                    <span className="text-emerald-400 font-mono flex-shrink-0">${mat.unitPrice.toFixed(2)}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Response file only (no quotes, no pricing) */}
                          {!hasUploadedQuotes && !hasPricing && responseFile && (
                            <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                              <p className="text-[10px] text-gray-500">
                                Response file: <span className="text-gray-300">{responseFile}</span>
                              </p>
                              <p className="text-[10px] text-amber-400/70 mt-1">No pricing extracted from this response.</p>
                            </div>
                          )}
                        </div>
                      </details>
                    )
                  })()}

                  {/* Request email text — collapsible */}
                  {req.request_text && (
                    <details className="group">
                      <summary className="text-[10px] font-bold text-gray-600 uppercase tracking-wider cursor-pointer hover:text-gray-400 flex items-center gap-1">
                        <Mail className="w-3 h-3" /> Quote Request Email
                        <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                      </summary>
                      <div className="mt-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 max-h-48 overflow-y-auto">
                        <pre className="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">{req.request_text}</pre>
                      </div>
                    </details>
                  )}

                  {/* Follow-up text */}
                  {followUpText && followUpId === null && expandedId === req.id && (
                    <div className="space-y-2">
                      <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider">Follow-Up Message</p>
                      <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 max-h-40 overflow-y-auto">
                        <pre className="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">{followUpText}</pre>
                      </div>
                      <button
                        onClick={async () => {
                          try {
                            await Promise.race([
                              navigator.clipboard.writeText(followUpText),
                              new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 2000))
                            ])
                          } catch {
                            try {
                              const ta = document.createElement('textarea')
                              ta.value = followUpText
                              document.body.appendChild(ta)
                              ta.select()
                              document.execCommand('copy')
                              document.body.removeChild(ta)
                            } catch {}
                          }
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

      {/* Vendor detail modal */}
      {detailModal && vendorDetails[detailModal] && (
        <VendorDetailModal
          vendor={vendorDetails[detailModal]}
          onClose={() => setDetailModal(null)}
        />
      )}
    </div>
  )
}


function VendorDetailModal({ vendor, onClose }) {
  const formatDate = (d) => d ? (d || '').slice(0, 10) : '—'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#12121a] border border-white/10 rounded-2xl shadow-2xl max-w-3xl w-full max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] sticky top-0 bg-[#12121a] z-10">
          <div className="flex items-center gap-3">
            <Building2 className="w-5 h-5 text-si-accent" />
            <h2 className="text-lg font-bold text-white">{vendor.name}</h2>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 p-2 rounded-xl hover:bg-white/[0.06] transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-5">
          {/* Contact + KPIs row */}
          <div className="flex gap-4 flex-wrap">
            <div className="flex-1 min-w-[220px] bg-white/[0.03] rounded-xl p-4 border border-white/[0.06]">
              <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-2">Contact</p>
              <div className="space-y-1.5">
                <p className="text-sm text-white font-semibold">{vendor.contact_name || '—'}</p>
                {vendor.contact_title && <p className="text-[11px] text-gray-500">{vendor.contact_title}</p>}
                {vendor.contact_email && (
                  <a href={`mailto:${vendor.contact_email}`} className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1.5">
                    <Mail className="w-3 h-3" /> {vendor.contact_email}
                  </a>
                )}
                {vendor.contact_phone && (
                  <a href={`tel:${vendor.contact_phone}`} className="text-xs text-gray-400 hover:text-gray-300 flex items-center gap-1.5">
                    <Phone className="w-3 h-3" /> {vendor.contact_phone}
                  </a>
                )}
                {vendor.notes && <p className="text-[11px] text-gray-500 mt-2 italic">{vendor.notes}</p>}
              </div>
            </div>

            {vendor.stats && (
              <div className="flex gap-3 flex-wrap">
                <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06] min-w-[90px] text-center">
                  <p className="text-lg font-bold text-white">{vendor.stats.total_products_quoted}</p>
                  <p className="text-[10px] text-gray-500 uppercase">Products</p>
                </div>
                <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06] min-w-[90px] text-center">
                  <p className="text-lg font-bold text-white">{vendor.stats.total_requests}</p>
                  <p className="text-[10px] text-gray-500 uppercase">Requests</p>
                </div>
                <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06] min-w-[90px] text-center">
                  <p className={`text-lg font-bold ${vendor.stats.response_rate != null ? (vendor.stats.response_rate >= 80 ? 'text-emerald-400' : vendor.stats.response_rate >= 50 ? 'text-amber-400' : 'text-red-400') : 'text-gray-600'}`}>
                    {vendor.stats.response_rate != null ? `${vendor.stats.response_rate}%` : '—'}
                  </p>
                  <p className="text-[10px] text-gray-500 uppercase">Response</p>
                </div>
                <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06] min-w-[90px] text-center">
                  <p className="text-lg font-bold text-white">
                    {vendor.stats.avg_response_days != null ? `${vendor.stats.avg_response_days}d` : '—'}
                  </p>
                  <p className="text-[10px] text-gray-500 uppercase">Avg Time</p>
                </div>
              </div>
            )}
          </div>

          {/* Product categories */}
          {vendor.categories?.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-2 flex items-center gap-1">
                <Package className="w-3 h-3" /> Products They Supply
              </p>
              <div className="flex flex-wrap gap-1.5">
                {vendor.categories.map((cat, i) => (
                  <span key={i} className="text-[11px] bg-white/[0.06] text-gray-300 px-2.5 py-1 rounded-lg border border-white/[0.06] flex items-center gap-1.5">
                    {cat.product_normalized || 'Other'}
                    <span className="text-gray-500">×{cat.count}</span>
                    {cat.avg_price > 0 && <span className="text-emerald-400 font-mono text-[10px]">~${cat.avg_price}</span>}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Price history + Quote requests */}
          <div className="flex gap-4 flex-wrap">
            <div className="flex-1 min-w-[280px]">
              <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-2 flex items-center gap-1">
                <TrendingUp className="w-3 h-3" /> Price History ({vendor.prices?.length || 0})
              </p>
              {vendor.prices?.length > 0 ? (
                <div className="max-h-52 overflow-y-auto rounded-lg border border-white/[0.06] bg-white/[0.02]">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-[#12121a]">
                      <tr className="text-gray-600 border-b border-white/[0.06]">
                        <th className="text-left py-1.5 pl-3 pr-2 font-medium">Product</th>
                        <th className="text-right py-1.5 px-2 font-medium">Price</th>
                        <th className="text-left py-1.5 px-2 font-medium">Unit</th>
                        <th className="text-left py-1.5 px-2 font-medium">Job</th>
                        <th className="text-left py-1.5 pl-2 pr-3 font-medium">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {vendor.prices.map((p, i) => (
                        <tr key={i} className="border-t border-white/[0.03] text-gray-400 hover:bg-white/[0.02]">
                          <td className="py-1.5 pl-3 pr-2 text-gray-300 max-w-[160px] truncate">{p.product_name}</td>
                          <td className="py-1.5 px-2 text-right text-emerald-400 font-mono">${(p.unit_price || 0).toFixed(2)}</td>
                          <td className="py-1.5 px-2">{p.unit || '—'}</td>
                          <td className="py-1.5 px-2 text-gray-500 max-w-[100px] truncate">{p.job_name || '—'}</td>
                          <td className="py-1.5 pl-2 pr-3 text-gray-500">{formatDate(p.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-gray-600 py-3 px-3 bg-white/[0.02] rounded-lg border border-white/[0.06]">No quotes from this vendor yet.</p>
              )}
            </div>

            <div className="w-[280px] flex-shrink-0">
              <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-2 flex items-center gap-1">
                <FileText className="w-3 h-3" /> Quote Requests ({vendor.quote_requests?.length || 0})
              </p>
              {vendor.quote_requests?.length > 0 ? (
                <div className="space-y-1.5 max-h-52 overflow-y-auto">
                  {vendor.quote_requests.map((qr, i) => {
                    const st = qr.received_at ? 'received' : qr.sent_at ? 'sent' : 'draft'
                    const daysSince = qr.sent_at ? Math.floor((Date.now() - new Date(qr.sent_at).getTime()) / 86400000) : null
                    const responseTime = (qr.sent_at && qr.received_at) ?
                      Math.round((new Date(qr.received_at).getTime() - new Date(qr.sent_at).getTime()) / 86400000 * 10) / 10 : null
                    return (
                      <div key={i} className="flex items-center gap-2 text-xs bg-white/[0.02] rounded-lg px-3 py-2 border border-white/[0.06]">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                          st === 'received' ? 'bg-emerald-400' : st === 'sent' ? (daysSince > 3 ? 'bg-amber-400' : 'bg-blue-400') : 'bg-gray-500'
                        }`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-gray-300 truncate">{qr.job_name || 'Unknown Job'}</p>
                          <p className="text-[10px] text-gray-500">
                            {st === 'received' && responseTime != null && `Responded in ${responseTime}d`}
                            {st === 'sent' && daysSince != null && (daysSince > 3 ? `⚠ ${daysSince}d, no response` : `Sent ${daysSince}d ago`)}
                            {st === 'draft' && 'Draft — not sent'}
                          </p>
                        </div>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          st === 'received' ? 'text-emerald-400 bg-emerald-500/10' :
                          st === 'sent' ? (daysSince > 3 ? 'text-amber-400 bg-amber-500/10' : 'text-blue-400 bg-blue-500/10') :
                          'text-gray-500 bg-gray-500/10'
                        }`}>
                          {st === 'received' ? 'Received' : st === 'sent' ? (daysSince > 3 ? 'Overdue' : 'Waiting') : 'Draft'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="text-xs text-gray-600 py-3 px-3 bg-white/[0.02] rounded-lg border border-white/[0.06]">No quote requests yet.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
