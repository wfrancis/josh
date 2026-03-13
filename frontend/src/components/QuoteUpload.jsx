import { useState } from 'react'
import { FileText, Package, AlertTriangle, CheckCircle2 } from 'lucide-react'
import FileUpload from './FileUpload'

export default function QuoteUpload({ jobId, onQuotesParsed, api }) {
  const [loading, setLoading] = useState(false)
  const [products, setProducts] = useState([])
  const [error, setError] = useState(null)

  const handleUpload = async (files) => {
    setLoading(true); setError(null)
    try {
      const fileList = Array.isArray(files) ? files : [files]
      const result = await api.uploadQuotes(jobId, fileList)
      setProducts(result.products || [])
      onQuotesParsed?.(result.products || [])
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <FileUpload
        accept=".pdf,.eml,.msg,.txt" multiple
        label="Upload Vendor Quotes"
        description="PDF or text files with vendor pricing"
        icon={FileText} onUpload={handleUpload} loading={loading}
        success={products.length > 0 && !loading}
        successMessage={`Parsed ${products.length} product${products.length !== 1 ? 's' : ''} from quotes`}
      />

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
        </div>
      )}

      {products.length > 0 && (
        <div className="glass-card p-4 animate-fade-in">
          <h4 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" /> Parsed Products
          </h4>
          <div className="space-y-2">
            {products.map((p, i) => (
              <div key={i} className="flex items-center gap-3 p-3 bg-white/[0.03] border border-white/[0.04] rounded-xl">
                <Package className="w-4 h-4 text-gray-500 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-200 truncate">
                    {p.product_name || p.description || 'Unknown product'}
                  </div>
                  {p.vendor && <div className="text-xs text-gray-500">{p.vendor}</div>}
                </div>
                {p.unit_price > 0 && (
                  <div className="text-sm font-semibold text-si-bright tabular-nums">
                    ${(p.unit_price || 0).toFixed(2)}/{p.unit || 'ea'}
                  </div>
                )}
                {p.error && (
                  <div className="text-xs text-red-400 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> Parse error
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
