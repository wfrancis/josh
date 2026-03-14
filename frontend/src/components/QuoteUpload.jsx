import { useState, useEffect, useMemo } from 'react'
import { FileText, Package, AlertTriangle, CheckCircle2, Trash2, Search } from 'lucide-react'
import FileUpload from './FileUpload'
import ConfirmDialog from './ConfirmDialog'

export default function QuoteUpload({ jobId, onQuotesParsed, onQuotesCleared, existingQuotes, api }) {
  const [loading, setLoading] = useState(false)
  const [products, setProducts] = useState([])
  const [autoMatched, setAutoMatched] = useState(0)
  const [error, setError] = useState(null)
  const [confirmDialog, setConfirmDialog] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [vendorFilter, setVendorFilter] = useState('')

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
      onQuotesParsed?.(result.products || [], result.auto_matched || 0)
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
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

  const validProducts = products.filter(p => !p.error)
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
            {filteredProducts.map((p, i) => (
              <div key={i} className="flex items-center justify-between gap-3 p-3 bg-white/[0.03] border border-white/[0.04] rounded-lg">
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-gray-200 truncate">{p.product_name || p.description || 'Unknown product'}</div>
                  {p.vendor && <div className="text-[11px] text-gray-500 mt-0.5">{p.vendor}</div>}
                </div>
                {p.unit_price > 0 && (
                  <div className="text-sm font-semibold text-si-bright tabular-nums whitespace-nowrap">
                    ${(p.unit_price).toFixed(2)}<span className="text-gray-500 font-normal text-xs">/{p.unit || 'ea'}</span>
                  </div>
                )}
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
                {filteredProducts.map((p, i) => (
                  <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="py-2 px-3">
                      <div className="text-sm text-gray-200 truncate max-w-[400px]">
                        {p.product_name || p.description || 'Unknown product'}
                      </div>
                    </td>
                    <td className="py-2 px-3 text-xs text-gray-500 whitespace-nowrap">{p.vendor || '—'}</td>
                    <td className="py-2 px-3 text-right tabular-nums whitespace-nowrap">
                      {p.unit_price > 0 ? (
                        <span className="text-sm font-semibold text-si-bright">${(p.unit_price).toFixed(2)}<span className="text-gray-500 font-normal">/{p.unit || 'ea'}</span></span>
                      ) : (
                        <span className="text-xs text-gray-600">—</span>
                      )}
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
