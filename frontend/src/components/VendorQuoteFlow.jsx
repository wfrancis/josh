import { useState, useEffect, useMemo } from 'react'
import {
  X, Sparkles, Loader2, Copy, Check, ChevronDown, ChevronRight,
  Mail, Building2, Clock, Send
} from 'lucide-react'
import { api } from '../api'
import VendorPicker from './VendorPicker'

/**
 * VendorQuoteFlow — AI-powered vendor-grouped quote request modal.
 *
 * Props:
 *   job: full job object (with materials)
 *   onClose: () => void
 *   onQuoteRequestCreated: () => void (refresh callback)
 */
export default function VendorQuoteFlow({ job, onClose, onQuoteRequestCreated }) {
  const [detecting, setDetecting] = useState(false)
  const [detected, setDetected] = useState(false)
  const [materials, setMaterials] = useState(job.materials || [])
  const [vendors, setVendors] = useState([])
  const [expandedVendor, setExpandedVendor] = useState(null)
  const [generatingFor, setGeneratingFor] = useState(null) // vendor name being generated
  const [generatedText, setGeneratedText] = useState({}) // vendor -> text
  const [copied, setCopied] = useState(null) // vendor name that was copied
  const [markingSent, setMarkingSent] = useState(null)
  const [sentVendors, setSentVendors] = useState(new Set())
  const [error, setError] = useState(null)
  const [existingRequests, setExistingRequests] = useState([])

  // Load known vendors + existing quote requests on mount
  useEffect(() => {
    api.listVendors().then(setVendors).catch(console.error)
    // Bug 1 fix: Load existing quote requests so "Sent" status persists across modal open/close
    api.listQuoteRequests(job.id).then(requests => {
      setExistingRequests(requests)
      const sent = new Set(requests.filter(r => r.status === 'sent' || r.sent_at).map(r => r.vendor_name))
      if (sent.size > 0) setSentVendors(sent)
    }).catch(console.error)
  }, [job.id])

  // Group unpriced materials by vendor
  const vendorGroups = useMemo(() => {
    const unpriced = materials.filter(m => !m.unit_price || m.unit_price === 0)
    const groups = {}
    unpriced.forEach((m, idx) => {
      // Find original index in materials array
      const origIdx = materials.indexOf(m)
      const vendor = (m.vendor || '').trim() || 'Unassigned'
      if (!groups[vendor]) groups[vendor] = []
      groups[vendor].push({ ...m, _origIdx: origIdx })
    })
    // Sort: assigned vendors first, then unassigned
    const sorted = Object.entries(groups).sort(([a], [b]) => {
      if (a === 'Unassigned') return 1
      if (b === 'Unassigned') return -1
      return a.localeCompare(b)
    })
    return sorted
  }, [materials])

  const totalUnpriced = vendorGroups.reduce((sum, [, mats]) => sum + mats.length, 0)

  // Auto-detect vendors on mount — but skip if materials already have vendor fields (Bug 2 fix)
  useEffect(() => {
    const materialsWithVendor = (job.materials || []).filter(m => m.vendor && m.vendor.trim())
    const unpricedMaterials = (job.materials || []).filter(m => !m.unit_price || m.unit_price === 0)
    // Only run AI detection if less than half of unpriced materials have vendors assigned
    if (unpricedMaterials.length > 0 && materialsWithVendor.length < unpricedMaterials.length * 0.5) {
      handleDetectVendors()
    } else {
      setDetected(true)
    }
  }, [])

  const handleDetectVendors = async () => {
    setDetecting(true)
    setError(null)
    try {
      const result = await api.detectVendors(job.id)
      // Reload job materials with updated vendor fields
      const updated = await api.getJob(job.id)
      setMaterials(updated.materials || [])
      setDetected(true)
    } catch (err) {
      console.error('Vendor detection failed:', err)
      setError(err.message)
      setDetected(true) // still show what we have
    } finally {
      setDetecting(false)
    }
  }

  const handleGenerateText = async (vendorName, vendorMaterials) => {
    setGeneratingFor(vendorName)
    setError(null)
    try {
      const materialIndices = vendorMaterials.map(m => m._origIdx)
      const result = await api.generateQuoteText(job.id, {
        vendor_name: vendorName,
        material_indices: materialIndices,
      })
      setGeneratedText(prev => ({ ...prev, [vendorName]: result.text }))
      setExpandedVendor(vendorName)
    } catch (err) {
      console.error('Quote text generation failed:', err)
      setError(err.message)
    } finally {
      setGeneratingFor(null)
    }
  }

  const handleCopy = async (vendorName) => {
    const text = generatedText[vendorName]
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopied(vendorName)
    setTimeout(() => setCopied(null), 4000)
  }

  const handleMarkSent = async (vendorName, vendorMaterials) => {
    setMarkingSent(vendorName)
    try {
      const vendorObj = vendors.find(v => v.name === vendorName)
      const materialIds = vendorMaterials.map(m => m.id).filter(Boolean)
      await api.createQuoteRequest(job.id, {
        vendor_name: vendorName,
        vendor_id: vendorObj?.id || null,
        material_ids: materialIds,
        request_text: generatedText[vendorName] || '',
      })
      // Mark as sent
      setSentVendors(prev => new Set([...prev, vendorName]))
      if (onQuoteRequestCreated) onQuoteRequestCreated()
    } catch (err) {
      console.error('Failed to create quote request:', err)
      setError(err.message)
    } finally {
      setMarkingSent(null)
    }
  }

  const handleReassignVendor = (materialOrigIdx, newVendorName) => {
    setMaterials(prev => {
      const next = [...prev]
      next[materialOrigIdx] = { ...next[materialOrigIdx], vendor: newVendorName }
      return next
    })
  }

  // Get vendor contact info
  const getVendorContact = (vendorName) => {
    return vendors.find(v => v.name.toLowerCase() === vendorName.toLowerCase())
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-[#12121a] border border-white/10 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            <Mail className="w-5 h-5 text-si-bright" />
            <div>
              <h2 className="text-base font-bold text-white">Request Vendor Quotes</h2>
              <p className="text-xs text-gray-500">{totalUnpriced} unpriced materials across {vendorGroups.length} vendor{vendorGroups.length !== 1 ? 's' : ''}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 transition-colors p-1.5 -mr-1.5 rounded-lg hover:bg-white/[0.06]">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Status bar */}
        {detecting && (
          <div className="px-6 py-3 bg-violet-500/10 border-b border-violet-500/20 flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-violet-400" />
            <span className="text-xs text-violet-300">AI is detecting vendors from your material descriptions...</span>
          </div>
        )}

        {error && (
          <div className="px-6 py-3 bg-red-500/10 border-b border-red-500/20 flex items-center justify-between">
            <span className="text-xs text-red-300">{error}</span>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {detected && !detecting && (
          <div className="px-6 py-2.5 bg-emerald-500/5 border-b border-white/[0.04] flex items-center gap-2">
            <Sparkles className="w-3.5 h-3.5 text-violet-400" />
            <span className="text-xs text-gray-400">
              AI grouped materials into {vendorGroups.filter(([v]) => v !== 'Unassigned').length} vendor groups
              {vendorGroups.some(([v]) => v === 'Unassigned') && ` · ${vendorGroups.find(([v]) => v === 'Unassigned')?.[1]?.length || 0} unassigned`}
            </span>
          </div>
        )}

        {/* Vendor groups - scrollable */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {vendorGroups.map(([vendorName, vendorMats]) => {
            const contact = getVendorContact(vendorName)
            const isExpanded = expandedVendor === vendorName
            const isSent = sentVendors.has(vendorName)
            const hasText = !!generatedText[vendorName]
            const isGenerating = generatingFor === vendorName
            const isCopied = copied === vendorName
            const isMarkingSent = markingSent === vendorName
            const isUnassigned = vendorName === 'Unassigned'

            return (
              <div
                key={vendorName}
                className={`rounded-xl border transition-colors ${
                  isSent
                    ? 'border-emerald-500/20 bg-emerald-500/5'
                    : isUnassigned
                    ? 'border-amber-500/20 bg-amber-500/5'
                    : 'border-white/[0.06] bg-white/[0.02]'
                }`}
              >
                {/* Vendor header */}
                <div
                  className="flex items-center gap-3 px-4 py-3 cursor-pointer"
                  onClick={() => setExpandedVendor(isExpanded ? null : vendorName)}
                >
                  {isExpanded
                    ? <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
                    : <ChevronRight className="w-4 h-4 text-gray-500 flex-shrink-0" />
                  }
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-semibold ${isUnassigned ? 'text-amber-300' : 'text-white'}`}>
                        {vendorName}
                      </span>
                      <span className="text-[10px] text-gray-500 bg-white/[0.04] px-1.5 py-0.5 rounded">
                        {vendorMats.length} item{vendorMats.length !== 1 ? 's' : ''}
                      </span>
                      {isSent && (
                        <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded flex items-center gap-1">
                          <Check className="w-3 h-3" /> Sent
                        </span>
                      )}
                    </div>
                    {contact && (contact.contact_email || contact.contact_name) && (
                      <p className="text-[10px] text-gray-500 mt-0.5">
                        {[contact.contact_name, contact.contact_email].filter(Boolean).join(' · ')}
                      </p>
                    )}
                  </div>

                  {/* Action button */}
                  {!isSent && !isUnassigned && (
                    <button
                      onClick={e => { e.stopPropagation(); handleGenerateText(vendorName, vendorMats) }}
                      disabled={isGenerating}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gradient-to-b from-si-orange to-orange-600 text-white hover:from-orange-500 hover:to-orange-700 disabled:opacity-50 transition-all flex-shrink-0"
                    >
                      {isGenerating ? (
                        <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Generating...</>
                      ) : hasText ? (
                        <><Sparkles className="w-3.5 h-3.5" /> Regenerate</>
                      ) : (
                        <><Sparkles className="w-3.5 h-3.5" /> Generate & Copy</>
                      )}
                    </button>
                  )}
                </div>

                {/* Expanded content */}
                {isExpanded && (
                  <div className="px-4 pb-4 space-y-3">
                    {/* Material list */}
                    <div className="space-y-1">
                      {vendorMats.map((m, i) => {
                        const qty = Math.round((m.order_qty || m.installed_qty || 0) * 100) / 100
                        return (
                          <div key={m.id || i} className="flex items-center gap-3 text-xs py-1">
                            <span className="text-gray-500 w-5 text-right flex-shrink-0">{i + 1}.</span>
                            <span className="text-gray-300 flex-1 min-w-0 truncate">
                              {m.item_code && <span className="text-gray-500 mr-1">{m.item_code}</span>}
                              {m.description || 'Unknown material'}
                            </span>
                            <span className="text-gray-500 flex-shrink-0 tabular-nums">
                              {qty.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {m.unit || ''}
                            </span>
                          </div>
                        )
                      })}
                    </div>

                    {/* Unassigned: show vendor picker */}
                    {isUnassigned && (
                      <div className="bg-amber-500/5 border border-amber-500/10 rounded-lg p-3 space-y-2">
                        <p className="text-xs text-amber-300">
                          These materials need a vendor assignment. Use AI detection above or assign manually.
                        </p>
                        <button
                          onClick={handleDetectVendors}
                          disabled={detecting}
                          className="text-xs text-violet-400 hover:text-violet-300 flex items-center gap-1.5"
                        >
                          {detecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                          Re-run AI Detection
                        </button>
                      </div>
                    )}

                    {/* Generated text preview */}
                    {hasText && !isUnassigned && (
                      <div className="space-y-3">
                        <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-4 max-h-60 overflow-y-auto">
                          <pre className="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
                            {generatedText[vendorName]}
                          </pre>
                        </div>

                        <div className="flex items-center gap-2">
                          {/* Copy button */}
                          <button
                            onClick={() => handleCopy(vendorName)}
                            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
                              isCopied
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                : 'bg-gradient-to-b from-si-orange to-orange-600 text-white shadow-[0_1px_2px_rgba(0,0,0,0.4)] hover:from-orange-500 hover:to-orange-700'
                            }`}
                          >
                            {isCopied ? (
                              <><Check className="w-4 h-4" /> Copied!</>
                            ) : (
                              <><Copy className="w-4 h-4" /> Copy to Clipboard</>
                            )}
                          </button>

                          {/* Mark Sent button */}
                          <button
                            onClick={() => handleMarkSent(vendorName, vendorMats)}
                            disabled={isMarkingSent}
                            className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-medium bg-white/[0.06] text-gray-300 hover:bg-white/[0.1] hover:text-white transition-colors"
                          >
                            {isMarkingSent ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Send className="w-4 h-4" />
                            )}
                            Mark Sent
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {vendorGroups.length === 0 && (
            <div className="text-center py-8">
              <Check className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
              <p className="text-sm text-gray-300">All materials are priced!</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-white/[0.06] flex items-center justify-between">
          <p className="text-xs text-gray-500">
            {sentVendors.size > 0 && (
              <span className="text-emerald-400">
                {sentVendors.size} quote request{sentVendors.size !== 1 ? 's' : ''} tracked
              </span>
            )}
          </p>
          <button
            onClick={onClose}
            className="text-xs text-gray-400 hover:text-white transition-colors px-3 py-1.5"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
