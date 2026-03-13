import { useState, useEffect } from 'react'
import {
  Calculator, FileDown, Loader2, ChevronDown, ChevronRight,
  Package, Wrench, HardHat, Truck, Ban, DollarSign, Plus, X, Save, RotateCcw
} from 'lucide-react'

function formatCurrency(val) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0)
}

function BundleCard({ bundle, index }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="glass-card overflow-hidden animate-slide-up" style={{ animationDelay: `${index * 60}ms` }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-4 p-4 hover:bg-white/[0.02] transition-colors text-left"
      >
        <div className="w-10 h-10 rounded-xl bg-si-bright/[0.08] border border-si-bright/[0.1]
                       flex items-center justify-center flex-shrink-0">
          <Package className="w-5 h-5 text-si-bright" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-white">{bundle.bundle_name}</div>
          <div className="text-xs text-gray-500 mt-0.5">{bundle.installed_qty} {bundle.unit} installed</div>
        </div>
        <div className="text-right">
          <div className="font-bold text-white tabular-nums">{formatCurrency(bundle.total_price)}</div>
        </div>
        {expanded ? <ChevronDown className="w-4 h-4 text-gray-500" /> : <ChevronRight className="w-4 h-4 text-gray-600" />}
      </button>
      {expanded && (
        <div className="px-4 pb-4 border-t border-white/[0.04] pt-3 space-y-2 animate-fade-in">
          <p className="text-xs text-gray-500 whitespace-pre-line leading-relaxed mb-3">{bundle.description_text}</p>
          <div className="grid grid-cols-2 gap-2">
            <CostRow icon={Package} label="Material" value={bundle.material_cost} />
            <CostRow icon={Wrench} label="Sundries" value={bundle.sundry_cost} />
            <CostRow icon={HardHat} label="Labor" value={bundle.labor_cost} />
            <CostRow icon={Truck} label="Freight" value={bundle.freight_cost} />
          </div>
        </div>
      )}
    </div>
  )
}

function CostRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-2 p-2.5 bg-white/[0.03] rounded-xl border border-white/[0.04]">
      <Icon className="w-3.5 h-3.5 text-gray-500" />
      <span className="text-xs text-gray-500 flex-1">{label}</span>
      <span className="text-xs font-semibold text-gray-300 tabular-nums">{formatCurrency(value)}</span>
    </div>
  )
}

function ExclusionsList({ jobId, api, exclusions: initialExclusions }) {
  const [exclusions, setExclusions] = useState(initialExclusions || [])
  const [newLine, setNewLine] = useState('')
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (!initialExclusions) {
      api.getExclusions(jobId).then(data => {
        setExclusions(data.exclusions || [])
      }).catch(() => {})
    }
  }, [jobId])

  const addLine = () => {
    const text = newLine.trim()
    if (!text) return
    setExclusions(prev => [...prev, text])
    setNewLine('')
    setDirty(true)
  }

  const removeLine = (idx) => {
    setExclusions(prev => prev.filter((_, i) => i !== idx))
    setDirty(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.updateExclusions(jobId, exclusions)
      setDirty(false)
    } catch (err) {
      console.error('Failed to save exclusions:', err)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    try {
      const data = await api.getExclusions(jobId)
      // Load defaults by passing empty to get template
      await api.updateExclusions(jobId, [])
      const fresh = await api.getExclusions(jobId)
      setExclusions(fresh.exclusions || [])
      setDirty(false)
    } catch (err) {
      console.error('Failed to reset exclusions:', err)
    }
  }

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-bold text-gray-500 uppercase tracking-[0.15em] flex items-center gap-2">
          <Ban className="w-4 h-4" /> Exclusions ({exclusions.length})
        </h4>
        <div className="flex items-center gap-2">
          {dirty && (
            <span className="text-xs text-amber-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              Unsaved
            </span>
          )}
          <button onClick={handleReset} className="btn-ghost text-xs px-2 py-1 text-gray-500 hover:text-gray-300"
                  title="Reset to defaults">
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button onClick={handleSave} disabled={saving || !dirty}
                  className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-40">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save
          </button>
        </div>
      </div>
      <ul className="space-y-1.5 mb-3">
        {exclusions.map((ex, i) => (
          <li key={i} className="group flex items-start gap-2 text-sm text-gray-400 hover:text-gray-300 transition-colors">
            <span className="text-gray-600 mt-0.5 flex-shrink-0">•</span>
            <span className="flex-1">{ex}</span>
            <button
              onClick={() => removeLine(i)}
              className="opacity-0 group-hover:opacity-100 p-0.5 hover:bg-red-500/10 rounded text-gray-600 hover:text-red-400 transition-all flex-shrink-0"
              title="Remove"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={newLine}
          onChange={(e) => setNewLine(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addLine() }}
          placeholder="Add exclusion..."
          className="input flex-1 text-sm py-1.5"
        />
        <button onClick={addLine} disabled={!newLine.trim()}
                className="btn-ghost p-1.5 text-gray-500 hover:text-si-bright disabled:opacity-30">
          <Plus className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

export default function BidPreview({ job, api, onGoBack }) {
  const [calculating, setCalculating] = useState(false)
  const [bidData, setBidData] = useState(null)
  const [error, setError] = useState(null)

  const hasMaterialPricing = job?.materials?.some(m => m.unit_price > 0)

  const handleCalculate = async () => {
    setCalculating(true); setError(null)
    try {
      await api.calculate(job.id)
      const result = await api.generateBid(job.id)
      setBidData(result)
    } catch (err) { setError(err.message) }
    finally { setCalculating(false) }
  }

  if (!hasMaterialPricing) {
    return (
      <div className="text-center py-16">
        <DollarSign className="w-12 h-12 text-gray-600 mx-auto mb-4" />
        <p className="text-gray-400 font-medium">Set material prices first</p>
        <p className="text-sm text-gray-600 mt-1 mb-4">Enter unit prices in Quotes & Pricing before generating a bid</p>
        {onGoBack && (
          <button onClick={onGoBack} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-si-bright/10 border border-si-bright/20 text-si-bright text-sm font-medium hover:bg-si-bright/15 transition-colors">
            Go to Quotes & Pricing
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {!bidData && (
        <div className="text-center py-10">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-si-orange/20 to-si-orange/5
                        border border-si-orange/15 flex items-center justify-center mx-auto mb-5">
            <Calculator className="w-8 h-8 text-si-orange" />
          </div>
          <h3 className="text-lg font-bold text-white mb-2">Ready to Generate Bid</h3>
          <p className="text-sm text-gray-500 mb-8 max-w-md mx-auto">
            This will calculate sundries, labor, and freight, then assemble your complete bid.
          </p>
          <button onClick={handleCalculate} disabled={calculating}
                  className="btn-primary text-base px-8 py-3.5 glow-orange">
            {calculating ? (
              <><Loader2 className="w-5 h-5 animate-spin" /> Calculating...</>
            ) : (
              <><Calculator className="w-5 h-5" /> Calculate & Generate Bid</>
            )}
          </button>
        </div>
      )}

      {error && (
        <div className="px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">{error}</div>
      )}

      {bidData && (
        <div className="space-y-6 animate-fade-in">
          {/* Job Info Header */}
          <div className="glass-card p-5">
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
              <div><span className="text-gray-600">Project:</span> <span className="text-gray-200 font-medium">{job.project_name}</span></div>
              {job.gc_name && <div><span className="text-gray-600">GC:</span> <span className="text-gray-200">{job.gc_name}</span></div>}
              {(job.city || job.state) && <div><span className="text-gray-600">Location:</span> <span className="text-gray-200">{[job.city, job.state].filter(Boolean).join(', ')}</span></div>}
              {job.salesperson && <div><span className="text-gray-600">Salesperson:</span> <span className="text-gray-200">{job.salesperson}</span></div>}
            </div>
          </div>

          {/* Line Items */}
          <div>
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-[0.15em] mb-3">
              Line Items ({bidData.bundles?.length || 0})
            </h3>
            <div className="space-y-3">
              {bidData.bundles?.map((b, i) => <BundleCard key={i} bundle={b} index={i} />)}
            </div>
          </div>

          {/* Totals */}
          <div className="glass-card p-6 relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-si-orange/[0.04] to-transparent" />
            <div className="relative space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Subtotal</span>
                <span className="font-semibold text-gray-200 tabular-nums">{formatCurrency(bidData.subtotal)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Tax ({((bidData.tax_rate || 0) * 100).toFixed(1)}%)</span>
                <span className="font-semibold text-gray-200 tabular-nums">{formatCurrency(bidData.tax_amount)}</span>
              </div>
              <div className="h-px bg-white/[0.08]" />
              <div className="flex justify-between items-center">
                <span className="text-lg font-bold text-white">Grand Total</span>
                <span className="text-3xl font-extrabold text-white tabular-nums tracking-tight">
                  {formatCurrency(bidData.grand_total)}
                </span>
              </div>
            </div>
          </div>

          {/* Editable Exclusions */}
          <ExclusionsList jobId={job.id} api={api} exclusions={bidData.exclusions} />

          {/* Actions */}
          <div className="flex items-center justify-center gap-4 pt-2">
            <button onClick={handleCalculate} disabled={calculating}
                    className="btn-secondary text-sm px-5 py-2.5">
              {calculating ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
              Recalculate
            </button>
            <button onClick={() => window.open(api.getBidPdfUrl(job.id), '_blank')}
                    className="btn-primary text-base px-8 py-3.5 glow-orange">
              <FileDown className="w-5 h-5" /> Download Bid PDF
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
