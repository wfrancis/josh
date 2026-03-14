import { useState, useEffect, useMemo } from 'react'
import {
  Calculator, FileDown, Loader2, ChevronDown, ChevronRight,
  Package, Wrench, HardHat, Truck, Ban, DollarSign, Plus, X, Save, RotateCcw, AlertTriangle
} from 'lucide-react'

const VALID_TYPES = [
  'unit_carpet_no_pattern', 'unit_carpet_pattern', 'unit_lvt', 'cpt_tile',
  'corridor_broadloom', 'floor_tile', 'wall_tile', 'backsplash',
  'tub_shower_surround', 'rubber_base', 'vct', 'rubber_tile',
  'rubber_sheet', 'wood', 'tread_riser', 'transitions', 'waterproofing'
]

const TYPE_LABELS = {
  unit_carpet_no_pattern: 'Carpet (No Pattern)', unit_carpet_pattern: 'Carpet (Pattern)',
  unit_lvt: 'LVT', cpt_tile: 'Carpet Tile', corridor_broadloom: 'Broadloom',
  floor_tile: 'Floor Tile', wall_tile: 'Wall Tile', backsplash: 'Backsplash',
  tub_shower_surround: 'Tub/Shower', rubber_base: 'Rubber Base', vct: 'VCT',
  rubber_tile: 'Rubber Tile', rubber_sheet: 'Rubber Sheet', wood: 'Wood',
  tread_riser: 'Tread & Riser', transitions: 'Transitions', waterproofing: 'Waterproofing',
}

function formatCurrency(val) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0)
}

function formatCompact(val) {
  if (!val) return '$0'
  if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`
  if (val >= 1000) return `$${(val / 1000).toFixed(0)}K`
  return `$${val.toFixed(0)}`
}

function formatQty(val) {
  if (!val) return '0'
  return val >= 100 ? Math.round(val).toLocaleString() : val.toFixed(1)
}

function BundleCard({ bundle, index, hasFlag }) {
  const [expanded, setExpanded] = useState(false)
  const unitRate = bundle.order_qty > 0 ? bundle.total_price / bundle.order_qty : 0

  return (
    <div className={`overflow-hidden rounded-xl border transition-colors ${
      hasFlag ? 'border-amber-500/20 bg-amber-500/[0.03]' : 'border-white/[0.06] bg-white/[0.02]'
    }`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 sm:gap-4 p-3 sm:p-4 hover:bg-white/[0.02] transition-colors text-left"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-white text-sm">{bundle.bundle_name}</span>
            <span className="text-[10px] text-gray-600 uppercase">{TYPE_LABELS[bundle.material_type] || bundle.material_type}</span>
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {formatQty(bundle.installed_qty)} {bundle.unit} installed → {formatQty(bundle.order_qty)} ordered
            {bundle.waste_pct > 0 && <span className="text-gray-600"> ({(bundle.waste_pct * 100).toFixed(0)}% waste)</span>}
          </div>
        </div>
        <div className="text-right flex-shrink-0">
          <div className="font-bold text-white tabular-nums text-sm">{formatCurrency(bundle.total_price)}</div>
          {unitRate > 0 && (
            <div className="text-[10px] text-gray-500 tabular-nums">
              {formatCurrency(unitRate)}/{bundle.unit}
            </div>
          )}
        </div>
        {expanded ? <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-gray-600 flex-shrink-0" />}
      </button>
      {expanded && (
        <div className="px-3 sm:px-4 pb-3 sm:pb-4 border-t border-white/[0.04] pt-3 space-y-2 animate-fade-in">
          <p className="text-xs text-gray-500 whitespace-pre-line leading-relaxed mb-3">{bundle.description_text}</p>
          <div className="grid grid-cols-2 gap-2">
            <CostRow icon={Package} label="Material" value={bundle.material_cost} flag={false} />
            <CostRow icon={Wrench} label="Sundries" value={bundle.sundry_cost} flag={bundle.sundry_cost === 0} />
            <CostRow icon={HardHat} label="Labor" value={bundle.labor_cost} flag={bundle.labor_cost === 0} />
            <CostRow icon={Truck} label="Freight" value={bundle.freight_cost} flag={false} />
          </div>
          {(bundle.sundry_cost === 0 || bundle.labor_cost === 0) && (
            <div className="flex items-center gap-1.5 text-[10px] text-amber-500/70 mt-1">
              <AlertTriangle className="w-3 h-3" />
              {bundle.sundry_cost === 0 && bundle.labor_cost === 0
                ? 'No sundries or labor calculated'
                : bundle.labor_cost === 0 ? 'No labor calculated' : 'No sundries calculated'}
              — verify type classification is correct
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CostRow({ icon: Icon, label, value, flag }) {
  return (
    <div className={`flex items-center gap-2 p-2.5 rounded-xl border ${
      flag ? 'bg-amber-500/[0.04] border-amber-500/[0.1]' : 'bg-white/[0.03] border-white/[0.04]'
    }`}>
      <Icon className={`w-3.5 h-3.5 ${flag ? 'text-amber-500/60' : 'text-gray-500'}`} />
      <span className={`text-xs flex-1 ${flag ? 'text-amber-500/60' : 'text-gray-500'}`}>{label}</span>
      <span className={`text-xs font-semibold tabular-nums ${
        flag ? 'text-amber-500/60' : 'text-gray-300'
      }`}>{formatCurrency(value)}</span>
    </div>
  )
}

function CategoryTotals({ bundles }) {
  const totals = useMemo(() => {
    let material = 0, sundry = 0, labor = 0, freight = 0
    for (const b of bundles) {
      material += b.material_cost || 0
      sundry += b.sundry_cost || 0
      labor += b.labor_cost || 0
      freight += b.freight_cost || 0
    }
    return { material, sundry, labor, freight }
  }, [bundles])

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <CategoryCard icon={Package} label="Materials" value={totals.material} />
      <CategoryCard icon={Wrench} label="Sundries" value={totals.sundry} flag={totals.sundry === 0} />
      <CategoryCard icon={HardHat} label="Labor" value={totals.labor} flag={totals.labor === 0} />
      <CategoryCard icon={Truck} label="Freight" value={totals.freight} />
    </div>
  )
}

function CategoryCard({ icon: Icon, label, value, flag }) {
  return (
    <div className={`p-3 rounded-xl border ${
      flag ? 'border-amber-500/15 bg-amber-500/[0.04]' : 'border-white/[0.06] bg-white/[0.03]'
    }`}>
      <div className="flex items-center gap-2 mb-1">
        <Icon className={`w-3.5 h-3.5 ${flag ? 'text-amber-500/60' : 'text-gray-500'}`} />
        <span className={`text-[10px] uppercase tracking-wider font-bold ${flag ? 'text-amber-500/60' : 'text-gray-500'}`}>
          {label}
        </span>
        {flag && <AlertTriangle className="w-3 h-3 text-amber-500/50" />}
      </div>
      <div className={`text-lg font-bold tabular-nums ${flag ? 'text-amber-400/70' : 'text-white'}`}>
        {formatCompact(value)}
      </div>
    </div>
  )
}

function TypeGroups({ bundles, expandedType, setExpandedType }) {
  const groups = useMemo(() => {
    const map = {}
    for (const b of bundles) {
      const t = b.material_type || 'unknown'
      if (!map[t]) map[t] = { type: t, bundles: [], total: 0, count: 0 }
      map[t].bundles.push(b)
      map[t].total += b.total_price || 0
      map[t].count++
    }
    return Object.values(map).sort((a, b) => b.total - a.total)
  }, [bundles])

  const flaggedBundles = useMemo(() => {
    const flags = new Set()
    for (const b of bundles) {
      if (b.sundry_cost === 0 || b.labor_cost === 0) flags.add(b.bundle_name)
    }
    return flags
  }, [bundles])

  return (
    <div className="space-y-4">
      {groups.map(g => {
        const isExpanded = expandedType === g.type
        const groupFlags = g.bundles.filter(b => b.sundry_cost === 0 || b.labor_cost === 0).length
        return (
          <div key={g.type}>
            <button
              onClick={() => setExpandedType(isExpanded ? null : g.type)}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-white/[0.03] transition-colors text-left"
            >
              {isExpanded
                ? <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
                : <ChevronRight className="w-4 h-4 text-gray-600 flex-shrink-0" />}
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wider flex-1">
                {TYPE_LABELS[g.type] || g.type} ({g.count})
              </span>
              {groupFlags > 0 && (
                <span className="text-[10px] text-amber-500/70 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" /> {groupFlags}
                </span>
              )}
              <span className="text-sm font-bold text-white tabular-nums">{formatCurrency(g.total)}</span>
            </button>
            {isExpanded && (
              <div className="space-y-2 mt-2 ml-2 sm:ml-4">
                {g.bundles.map((b, i) => (
                  <BundleCard key={i} bundle={b} index={i} hasFlag={flaggedBundles.has(b.bundle_name)} />
                ))}
              </div>
            )}
          </div>
        )
      })}
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

export default function BidPreview({ job, api, onGoBack, onBidCleared }) {
  const [calculating, setCalculating] = useState(false)
  const [bidData, setBidData] = useState(null)
  const [error, setError] = useState(null)
  const [markup, setMarkup] = useState(job.markup_pct ? (job.markup_pct * 100) : 0)
  const [expandedType, setExpandedType] = useState(null)
  const [laborCatalogCount, setLaborCatalogCount] = useState(null)

  // Load existing bid data from job on mount
  useEffect(() => {
    if (job.bid_data && job.bid_data.bundles?.length > 0) {
      setBidData(job.bid_data)
    }
  }, [job.id])

  // Pre-flight: check labor catalog
  useEffect(() => {
    api.getLaborCatalog()
      .then(data => setLaborCatalogCount(data.count || 0))
      .catch(() => setLaborCatalogCount(0))
  }, [])

  const unknownMaterials = job.materials?.filter(m =>
    !m.material_type || !VALID_TYPES.includes(m.material_type)
  ) || []

  const hasMaterialPricing = job?.materials?.some(m => m.unit_price > 0)
  const unpricedCount = job?.materials?.filter(m => !m.unit_price || m.unit_price === 0).length || 0

  // Flags summary
  const flagSummary = useMemo(() => {
    if (!bidData?.bundles) return null
    let zeroLabor = 0, zeroSundry = 0
    for (const b of bidData.bundles) {
      if (b.labor_cost === 0) zeroLabor++
      if (b.sundry_cost === 0) zeroSundry++
    }
    return { zeroLabor, zeroSundry }
  }, [bidData])

  const handleCalculate = async () => {
    setCalculating(true); setError(null)
    try {
      // Auto-save materials + markup before generating
      await api.updateMaterials(job.id, job.materials)
      await api.updateJob(job.id, { markup_pct: markup / 100 })
      await api.calculate(job.id)
      const result = await api.generateBid(job.id)
      setBidData(result)
    } catch (err) { setError(err.message) }
    finally { setCalculating(false) }
  }

  const handleClear = async () => {
    try {
      await api.clearBid(job.id)
      setBidData(null)
      onBidCleared?.()
    } catch (err) { setError(err.message) }
  }

  if (!hasMaterialPricing) {
    return (
      <div className="text-center py-16">
        <DollarSign className="w-12 h-12 text-gray-600 mx-auto mb-4" />
        <p className="text-gray-400 font-medium">Set material prices first</p>
        <p className="text-sm text-gray-600 mt-1 mb-4">Enter unit prices in Takeoff & Pricing before generating a bid</p>
        {onGoBack && (
          <button onClick={onGoBack} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-si-bright/10 border border-si-bright/20 text-si-bright text-sm font-medium hover:bg-si-bright/15 transition-colors">
            Go to Takeoff & Pricing
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
          {/* Pre-flight warnings */}
          {laborCatalogCount === 0 && (
            <div className="flex items-start gap-3 px-4 py-3 mb-4 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400 max-w-md mx-auto text-left">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <div>
                <span className="font-medium">No labor catalog loaded</span>
                <span className="text-red-500/80"> — all labor costs will be $0. <a href="/internal-rates" className="underline hover:text-red-300">Upload labor rates</a> before generating.</span>
              </div>
            </div>
          )}
          {unpricedCount > 0 && (
            <div className="flex items-start gap-3 px-4 py-3 mb-4 bg-amber-500/10 border border-amber-500/20 rounded-xl text-sm text-amber-400 max-w-md mx-auto text-left">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <div>
                <span className="font-medium">{unpricedCount} material{unpricedCount !== 1 ? 's have' : ' has'} no price</span>
                <span className="text-amber-500/80"> — material costs will be undercounted.</span>
              </div>
            </div>
          )}
          {unknownMaterials.length > 0 && (
            <div className="flex items-start gap-3 px-4 py-3 mb-4 bg-amber-500/10 border border-amber-500/20 rounded-xl text-sm text-amber-400 max-w-md mx-auto text-left">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <div>
                <span className="font-medium">{unknownMaterials.length} material{unknownMaterials.length !== 1 ? 's have' : ' has'} unknown types</span>
                <span className="text-amber-500/80"> — sundries and labor may not calculate correctly.</span>
              </div>
            </div>
          )}
          <div className="flex items-center gap-4 mb-4 justify-center">
            <label className="text-sm text-gray-400 font-medium">Markup</label>
            <div className="flex items-center gap-1">
              <input
                type="number"
                step="0.5"
                min="0"
                max="100"
                value={markup}
                onChange={(e) => setMarkup(parseFloat(e.target.value) || 0)}
                className="w-20 px-3 py-1.5 text-sm bg-white/[0.04] border border-white/[0.06] rounded-lg
                           text-gray-200 text-right tabular-nums focus:outline-none focus:border-white/[0.12] transition-colors"
              />
              <span className="text-sm text-gray-500">%</span>
            </div>
          </div>
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
          <div className="glass-card p-4 sm:p-5">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-1 sm:gap-y-2 text-sm">
              <div><span className="text-gray-600">Project:</span> <span className="text-gray-200 font-medium">{job.project_name}</span></div>
              {job.gc_name && <div><span className="text-gray-600">GC:</span> <span className="text-gray-200">{job.gc_name}</span></div>}
              {(job.city || job.state) && <div><span className="text-gray-600">Location:</span> <span className="text-gray-200">{[job.city, job.state].filter(Boolean).join(', ')}</span></div>}
              {job.salesperson && <div><span className="text-gray-600">Salesperson:</span> <span className="text-gray-200">{job.salesperson}</span></div>}
            </div>
          </div>

          {/* Cost Category Totals */}
          <CategoryTotals bundles={bidData.bundles || []} />

          {/* Flags bar */}
          {flagSummary && (flagSummary.zeroLabor > 0 || flagSummary.zeroSundry > 0) && (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-500/[0.06] border border-amber-500/15 rounded-xl text-xs text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
              {flagSummary.zeroLabor > 0 && <span>{flagSummary.zeroLabor} items with $0 labor</span>}
              {flagSummary.zeroLabor > 0 && flagSummary.zeroSundry > 0 && <span className="text-amber-500/40">|</span>}
              {flagSummary.zeroSundry > 0 && <span>{flagSummary.zeroSundry} items with $0 sundries</span>}
              <span className="text-amber-500/60">— check type classifications</span>
            </div>
          )}

          {/* Line Items Grouped by Type */}
          <div>
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-[0.15em] mb-3">
              Line Items by Type ({bidData.bundles?.length || 0})
            </h3>
            <TypeGroups
              bundles={bidData.bundles || []}
              expandedType={expandedType}
              setExpandedType={setExpandedType}
            />
          </div>

          {/* Totals */}
          <div className="glass-card p-4 sm:p-6 relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-si-orange/[0.04] to-transparent" />
            <div className="relative space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Subtotal</span>
                <span className="font-semibold text-gray-200 tabular-nums">{formatCurrency(bidData.subtotal)}</span>
              </div>
              {bidData.markup_amount > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Markup ({(bidData.markup_pct * 100).toFixed(1)}%)</span>
                  <span className="text-gray-200 tabular-nums">{formatCurrency(bidData.markup_amount)}</span>
                </div>
              )}
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
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4 pt-2">
            <button onClick={handleClear}
                    className="btn-ghost text-sm px-4 py-2.5 text-gray-500 hover:text-red-400">
              Clear Bid
            </button>
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
