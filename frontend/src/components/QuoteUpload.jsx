import { useState, useEffect, useMemo, useRef } from 'react'
import { FileText, Package, AlertTriangle, CheckCircle2, Trash2, Search, Link2, Check, X } from 'lucide-react'
import FileUpload from './FileUpload'
import ConfirmDialog from './ConfirmDialog'

export default function QuoteUpload({ jobId, onQuotesParsed, onQuotesCleared, existingQuotes, api }) {
  const [loading, setLoading] = useState(false)
  const [products, setProducts] = useState([])
  const [autoMatched, setAutoMatched] = useState(0)
  const [error, setError] = useState(null)
  const [confirmDialog, setConfirmDialog] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const saveTimers = useRef({})
  const [vendorFilter, setVendorFilter] = useState('')
  const [linkedRequests, setLinkedRequests] = useState([]) // requests matched to this upload
  const [linkingId, setLinkingId] = useState(null)

  // Populate from existing quotes on load
  useEffect(() => {
    if (existingQuotes?.length > 0 && products.length === 0) {
      setProducts(existingQuotes)
    }
  }, [existingQuotes])

  const handleUpload = async (files) => {
    setLoading(true); setError(null)
    try {
      const fileList = Array.isArray(files) ? files : [files]
      const result = await api.uploadQuotes(jobId, fileList)
      setProducts(result.products || [])
      setAutoMatched(result.auto_matched || 0)
      setLinkedRequests(result.linked_requests || [])
      onQuotesParsed?.(result.products || [], result.auto_matched || 0)
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  const handleConfirmLink = async (req) => {
    setLinkingId(req.request_id)
    try {
      await api.updateQuoteRequest(req.request_id, {
        status: 'received',
        received_at: new Date().toISOString(),
      })
      setLinkedRequests(prev => prev.filter(r => r.request_id !== req.request_id))
      onQuotesParsed?.() // refresh job to update QuoteTracker
    } catch (err) {
      console.error('Failed to link request:', err)
    } finally {
      setLinkingId(null)
    }
  }

  const handleDismissLink = (reqId) => {
    setLinkedRequests(prev => prev.filter(r => r.request_id !== reqId))
  }

  const handleClear = () => {
    setConfirmDialog({
      title: 'Clear Quotes',
      message: `Clear all ${products.length} parsed products? You can re-upload vendor quotes after clearing.`,
      confirmLabel: 'Clear Quotes',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null)
        try {
          await api.clearQuotes(jobId)
          setProducts([])
          setAutoMatched(0)
          onQuotesCleared?.()
        } catch (err) { setError(err.message) }
      }
    })
  }

  const updateProduct = (idx, field, value) => {
    setProducts(prev => {
      const updated = [...prev]
      updated[idx] = { ...updated[idx], [field]: value }
      const product = updated[idx]
      // Debounced save to DB
      if (product.id) {
        clearTimeout(saveTimers.current[product.id])
        saveTimers.current[product.id] = setTimeout(async () => {
          try {
            await api.updateQuote(product.id, { [field]: value })
            // Refresh job to pick up re-matched materials
            onQuotesParsed?.()
          } catch (err) {
            console.error('Failed to save quote:', err)
          }
        }, 600)
      }
      return updated
    })
  }

  const validProducts = useMemo(() =>
    products.map((p, idx) => ({ ...p, _idx: idx })).filter(p => !p.error),
    [products])
  const vendors = useMemo(() => [...new Set(validProducts.map(p => p.vendor).filter(Boolean))].sort(), [validProducts])
  const filteredProducts = useMemo(() => {
    let filtered = validProducts
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      filtered = filtered.filter(p =>
        (p.product_name || p.description || '').toLowerCase().includes(q) ||
        (p.vendor || '').toLowerCase().includes(q)
      )
    }
    if (vendorFilter) {
      filtered = filtered.filter(p => p.vendor === vendorFilter)
    }
    return filtered
  }, [validProducts, searchQuery, vendorFilter])

  const hasQuotes = products.length > 0 && !loading

  return (
    <div className="space-y-4">
      {!hasQuotes && (
        <FileUpload
          accept=".pdf,.eml,.msg,.txt" multiple
          label="Upload Vendor Quotes"
          description="PDF or text files with vendor pricing"
          icon={FileText} onUpload={handleUpload} loading={loading}
        />
      )}

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
          <button onClick={() => setError(null)} className="ml-auto text-red-500/60 hover:text-red-400 text-xs">dismiss</button>
        </div>
      )}

      {/* Link-to-request confirmation banners */}
      {linkedRequests.length > 0 && (
        <div className="space-y-2">
          {linkedRequests.map(req => {
            const sentDate = req.sent_at ? new Date(req.sent_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : null
            return (
              <div key={req.request_id} className="flex items-center gap-3 px-4 py-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl">
                <Link2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                <div className="flex-1 min-w-0 text-sm">
                  <span className="text-gray-300">This looks like a response from </span>
                  <span className="text-white font-semibold">{req.vendor_name}</span>
                  {sentDate && (
                    <span className="text-gray-400">. Link to your request from {sentDate}?</span>
                  )}
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <button
                    onClick={() => handleConfirmLink(req)}
                    disabled={linkingId === req.request_id}
                    className="text-xs bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 px-2.5 py-1.5 rounded-lg flex items-center gap-1 transition-colors"
                  >
                    <Check className="w-3 h-3" /> Link
                  </button>
                  <button
                    onClick={() => handleDismissLink(req.request_id)}
                    className="text-xs text-gray-600 hover:text-gray-400 p-1.5 rounded-lg transition-colors"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {hasQuotes && (
        <div>
          {/* Header row: count + actions */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">
                Parsed Products ({validProducts.length})
              </span>
              {autoMatched > 0 && (
                <span className="text-[10px] text-emerald-400/70">· {autoMatched} auto-matched</span>
              )}
            </div>
            <button onClick={handleClear}
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors">
              Clear & re-upload
            </button>
          </div>

          {/* Filter bar — matches MaterialsTable style */}
          {validProducts.length > 3 && (
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 sm:gap-3 mb-3">
              <div className="relative flex-1 min-w-0">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-600" />
                <input type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                  placeholder="Filter products..."
                  className="w-full pl-9 pr-3 py-2 sm:py-1.5 text-sm sm:text-xs bg-white/[0.04] border border-white/[0.06] rounded-lg
                             text-gray-300 placeholder-gray-600 focus:outline-none focus:border-white/[0.12] transition-colors" />
              </div>
              <div className="flex items-center gap-2 sm:gap-3">
                {vendors.length > 1 && (
                  <select value={vendorFilter} onChange={e => setVendorFilter(e.target.value)}
                    className="text-sm sm:text-xs bg-white/[0.04] border border-white/[0.06] rounded-lg px-2.5 py-2 sm:py-1.5
                               text-gray-300 focus:outline-none focus:border-white/[0.12] transition-colors flex-1 sm:flex-none">
                    <option value="">All Vendors</option>
                    {vendors.map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                )}
                {(searchQuery || vendorFilter) && (
                  <button onClick={() => { setSearchQuery(''); setVendorFilter('') }}
                    className="text-xs text-gray-600 hover:text-gray-400 transition-colors whitespace-nowrap">
                    Clear filters
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Product list — cards on mobile, table on desktop */}
          {/* Mobile: card layout */}
          <div className="sm:hidden space-y-2 max-h-[400px] overflow-y-auto">
            {filteredProducts.map((p) => (
              <div key={p._idx} className="flex items-center justify-between gap-3 p-3 bg-white/[0.03] border border-white/[0.04] rounded-lg">
                <div className="min-w-0 flex-1">
                  <input type="text"
                    className="bg-transparent border-0 outline-none w-full text-sm text-gray-200 cursor-text focus:bg-white/[0.06] focus:rounded-md transition-colors"
                    value={p.product_name || p.description || ''}
                    onChange={e => updateProduct(p._idx, 'product_name', e.target.value)} />
                  <input type="text"
                    className="bg-transparent border-0 outline-none w-full text-[11px] text-gray-500 mt-0.5 cursor-text focus:bg-white/[0.06] focus:rounded-md transition-colors"
                    value={p.vendor || ''}
                    onChange={e => updateProduct(p._idx, 'vendor', e.target.value)} />
                </div>
                <div className="flex items-center gap-0.5 flex-shrink-0">
                  <span className="text-sm font-semibold text-si-bright">$</span>
                  <input type="number" step="0.01" min="0"
                    className="bg-transparent border-0 outline-none w-16 text-sm font-semibold text-si-bright text-right tabular-nums cursor-text focus:bg-white/[0.06] focus:rounded-md transition-colors"
                    value={p.unit_price ?? ''}
                    onChange={e => updateProduct(p._idx, 'unit_price', e.target.value === '' ? 0 : parseFloat(e.target.value))} />
                  <span className="text-gray-500 text-xs">/{p.unit || 'ea'}</span>
                </div>
              </div>
            ))}
            {filteredProducts.length === 0 && (searchQuery || vendorFilter) && (
              <p className="text-xs text-gray-500 text-center py-6">No products match your filters</p>
            )}
          </div>

          {/* Desktop: table layout */}
          <div className="hidden sm:block overflow-hidden rounded-lg border border-white/[0.06]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  <th className="py-2 px-3 text-left font-bold text-gray-500 text-[10px] uppercase tracking-[0.12em]">Product</th>
                  <th className="py-2 px-3 text-left font-bold text-gray-500 text-[10px] uppercase tracking-[0.12em]">Vendor</th>
                  <th className="py-2 px-3 text-right font-bold text-gray-500 text-[10px] uppercase tracking-[0.12em]">Unit Price</th>
                </tr>
              </thead>
              <tbody>
                {filteredProducts.map((p) => (
                  <tr key={p._idx} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="py-2 px-3">
                      <input type="text"
                        className="bg-transparent border-0 outline-none w-full text-sm text-gray-200 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                        value={p.product_name || p.description || ''}
                        onChange={e => updateProduct(p._idx, 'product_name', e.target.value)} />
                    </td>
                    <td className="py-2 px-3">
                      <input type="text"
                        className="bg-transparent border-0 outline-none w-full text-xs text-gray-500 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                        value={p.vendor || ''}
                        onChange={e => updateProduct(p._idx, 'vendor', e.target.value)} />
                    </td>
                    <td className="py-2 px-3 text-right">
                      <div className="flex items-center justify-end gap-0.5">
                        <span className="text-sm font-semibold text-si-bright">$</span>
                        <input type="number" step="0.01" min="0"
                          className="bg-transparent border-0 outline-none w-20 text-sm font-semibold text-si-bright text-right tabular-nums cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                          value={p.unit_price ?? ''}
                          onChange={e => updateProduct(p._idx, 'unit_price', e.target.value === '' ? 0 : parseFloat(e.target.value))} />
                        <span className="text-gray-500 text-xs">/{p.unit || 'ea'}</span>
                      </div>
                    </td>
                  </tr>
                ))}
                {filteredProducts.length === 0 && (searchQuery || vendorFilter) && (
                  <tr><td colSpan={3} className="text-xs text-gray-500 text-center py-6">No products match your filters</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {filteredProducts.length !== validProducts.length && (
            <p className="text-xs text-gray-500 mt-2">
              Showing {filteredProducts.length} of {validProducts.length}
            </p>
          )}
        </div>
      )}

      <ConfirmDialog {...confirmDialog} open={!!confirmDialog} onCancel={() => setConfirmDialog(null)} />
    </div>
  )
}
