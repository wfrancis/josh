import { useState, useRef, useEffect, useMemo } from 'react'
import { Package, Trash2, Search, ChevronUp, ChevronDown, AlertTriangle, Store, Mail, DollarSign, Sparkles, XCircle, Info } from 'lucide-react'

function round2(val) { return Math.round((val || 0) * 100) / 100 }
function formatCurrency(val) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0)
}
function formatNumber(val, decimals = 2) {
  return (val || 0).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}
function formatCompact(val) {
  if (!val) return '$0'
  if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`
  if (val >= 1000) return `$${(val / 1000).toFixed(0)}K`
  return `$${val.toFixed(0)}`
}

const TYPE_LABELS = {
  unit_carpet_no_pattern: 'Carpet', unit_carpet_pattern: 'Carpet (Pattern)',
  unit_lvt: 'LVT', cpt_tile: 'Carpet Tile', corridor_broadloom: 'Broadloom',
  floor_tile: 'Floor Tile', wall_tile: 'Wall Tile', backsplash: 'Backsplash',
  tub_shower_surround: 'Tub/Shower', rubber_base: 'Rubber Base',
  vct: 'VCT', rubber_tile: 'Rubber Tile', rubber_sheet: 'Rubber Sheet',
  wood: 'Wood', tread_riser: 'Tread/Riser', transitions: 'Transitions',
  waterproofing: 'Waterproofing', pad: 'Pad',
}

const TYPE_COLORS = {
  unit_carpet_no_pattern: 'bg-violet-500/10 text-violet-400 border-violet-500/10',
  unit_carpet_pattern: 'bg-violet-500/10 text-violet-400 border-violet-500/10',
  unit_lvt: 'bg-sky-500/10 text-sky-400 border-sky-500/10',
  cpt_tile: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/10',
  floor_tile: 'bg-amber-500/10 text-amber-400 border-amber-500/10',
  wall_tile: 'bg-amber-500/10 text-amber-400 border-amber-500/10',
  backsplash: 'bg-orange-500/10 text-orange-400 border-orange-500/10',
  tub_shower_surround: 'bg-teal-500/10 text-teal-400 border-teal-500/10',
  rubber_base: 'bg-gray-500/10 text-gray-400 border-gray-500/10',
  transitions: 'bg-lime-500/10 text-lime-400 border-lime-500/10',
  waterproofing: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/10',
}

const VALID_TYPES = [
  'unit_carpet_no_pattern', 'unit_carpet_pattern', 'unit_lvt', 'cpt_tile',
  'corridor_broadloom', 'floor_tile', 'wall_tile', 'backsplash',
  'tub_shower_surround', 'rubber_base', 'vct', 'rubber_tile',
  'rubber_sheet', 'wood', 'tread_riser', 'transitions', 'waterproofing'
]

function ConfidenceDot({ confidence }) {
  if (confidence == null) return null
  let colorClass = 'bg-red-400'
  let sizeClass = 'w-2.5 h-2.5'
  if (confidence >= 0.9) { colorClass = 'bg-emerald-400'; sizeClass = 'w-2 h-2' }
  else if (confidence >= 0.7) { colorClass = 'bg-amber-400'; sizeClass = 'w-2 h-2' }
  else if (confidence >= 0.5) { colorClass = 'bg-amber-400'; sizeClass = 'w-2.5 h-2.5' }
  // Low confidence gets larger dot
  return (
    <span
      className={`inline-block ${sizeClass} rounded-full ${colorClass} flex-shrink-0`}
      title={`AI confidence: ${(confidence * 100).toFixed(0)}%`}
    />
  )
}

function EditableCell({ value, onSave, type = 'text', className = '' }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef(null)

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  const commit = () => {
    setEditing(false)
    const parsed = type === 'number' ? (parseFloat(draft) || 0) : draft
    if (parsed !== value) onSave(parsed)
  }

  if (!editing) {
    return (
      <span
        className={`cursor-pointer hover:bg-white/[0.04] rounded px-1 -mx-1 ${className}`}
        onClick={() => { setDraft(value); setEditing(true) }}
      >
        {type === 'number' ? formatNumber(value) : (value || '—')}
      </span>
    )
  }

  return (
    <input
      ref={inputRef}
      type={type}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
      className={`editable-cell w-full ${className}`}
      step={type === 'number' ? 'any' : undefined}
    />
  )
}

function TypeDropdown({ currentType, confidence, onSelect, editable }) {
  const [open, setOpen] = useState(false)
  const dropdownRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const typeColor = TYPE_COLORS[currentType] || 'bg-gray-500/10 text-gray-400 border-gray-500/10'

  return (
    <div className="relative" ref={dropdownRef}>
      <div
        className={`flex items-center gap-1.5 ${editable ? 'cursor-pointer' : ''}`}
        onClick={() => editable && setOpen(!open)}
      >
        <ConfidenceDot confidence={confidence} />
        <span className={`badge border ${typeColor} ${editable ? 'hover:brightness-125' : ''}`}>
          {TYPE_LABELS[currentType] || currentType}
        </span>
      </div>
      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 w-52 max-h-64 overflow-y-auto
                        bg-gray-900 border border-white/[0.1] rounded-xl shadow-2xl py-1">
          {VALID_TYPES.map((t) => {
            const color = TYPE_COLORS[t] || 'bg-gray-500/10 text-gray-400 border-gray-500/10'
            return (
              <button
                key={t}
                onClick={() => { onSelect(t); setOpen(false) }}
                className={`w-full text-left px-3 py-1.5 text-sm hover:bg-white/[0.06] flex items-center gap-2
                  ${t === currentType ? 'bg-white/[0.04]' : ''}`}
              >
                <span className={`badge border text-xs ${color}`}>
                  {TYPE_LABELS[t] || t}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

function PriceActionMenu({ material, onRequestQuote, onSetTotal, onAiEstimate, onClearPrice, estimating, hasPrice, extendedCost, priceSource }) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const menuRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  const handleSubmitTotal = () => {
    const val = parseFloat(editValue)
    if (val > 0) {
      onSetTotal(val)
    }
    setEditing(false)
    setEditValue('')
  }

  if (editing) {
    return (
      <div className="inline-flex items-center gap-1">
        <span className="text-gray-500 text-sm">$</span>
        <input
          ref={inputRef}
          type="number" step="0.01" min="0"
          value={editValue}
          onChange={e => setEditValue(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') handleSubmitTotal()
            if (e.key === 'Escape') { setEditing(false); setEditValue('') }
          }}
          onBlur={handleSubmitTotal}
          placeholder={extendedCost ? String(Math.round(extendedCost)) : '0'}
          className="editable-cell w-28 text-right text-gray-100"
        />
      </div>
    )
  }

  return (
    <div className="relative inline-block" ref={menuRef}>
      {estimating ? (
        <span className="text-xs font-medium px-2 py-0.5 rounded-md bg-si-bright/10 text-si-bright animate-pulse">
          Estimating...
        </span>
      ) : hasPrice ? (
        <button
          onClick={() => setOpen(!open)}
          className={`cursor-pointer hover:opacity-80 transition-opacity ${
            priceSource === 'ai_estimate' ? 'text-violet-300' :
            priceSource === 'vendor_quote' ? 'text-sky-300' :
            priceSource === 'manual' ? 'text-emerald-300' :
            'text-white'
          }`}
        >
          {formatCurrency(extendedCost)}
          {priceSource && priceSource !== 'none' && (
            <span className={`block text-[10px] font-normal ${
              priceSource === 'ai_estimate' ? 'text-violet-400/60' :
              priceSource === 'vendor_quote' ? 'text-sky-400/60' :
              priceSource === 'manual' ? 'text-emerald-400/60' :
              'text-gray-500'
            }`}>
              {priceSource === 'ai_estimate' ? 'AI est.' :
               priceSource === 'vendor_quote' ? 'Vendor' :
               priceSource === 'manual' ? 'Manual' : ''}
            </span>
          )}
        </button>
      ) : (
        <button
          onClick={() => setOpen(!open)}
          className="text-xs font-medium px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-colors"
        >
          Need Price
        </button>
      )}
      {open && !estimating && (
        <div className="absolute right-0 top-full mt-1 z-50 w-52 bg-gray-900 border border-white/[0.1] rounded-xl shadow-2xl py-1">
          <button
            onClick={() => { setOpen(false); setEditValue(extendedCost ? String(Math.round(extendedCost * 100) / 100) : ''); setEditing(true) }}
            className="w-full text-left px-3 py-2 text-sm hover:bg-white/[0.06] flex items-center gap-2 text-gray-300"
          >
            <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
            Enter Price
          </button>
          <button
            onClick={() => { onRequestQuote(material); setOpen(false) }}
            className="w-full text-left px-3 py-2 text-sm hover:bg-white/[0.06] flex items-center gap-2 text-gray-300"
          >
            <Mail className="w-3.5 h-3.5 text-si-bright" />
            Request Vendor Quote
          </button>
          <button
            onClick={() => { onAiEstimate(); setOpen(false) }}
            className="w-full text-left px-3 py-2 text-sm hover:bg-white/[0.06] flex items-center gap-2 text-gray-300"
          >
            <Sparkles className="w-3.5 h-3.5 text-violet-400" />
            AI Estimate Price
          </button>
          {hasPrice && (
            <>
              <div className="border-t border-white/[0.06] my-1" />
              <button
                onClick={() => { onClearPrice(); setOpen(false) }}
                className="w-full text-left px-3 py-2 text-sm hover:bg-white/[0.06] flex items-center gap-2 text-red-400/70"
              >
                <XCircle className="w-3.5 h-3.5" />
                Clear Price
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <span className="inline-block w-3 ml-0.5" />
  return sortDir === 'asc'
    ? <ChevronUp className="inline-block w-3 h-3 ml-0.5 text-si-bright" />
    : <ChevronDown className="inline-block w-3 h-3 ml-0.5 text-si-bright" />
}

export default function MaterialsTable({ materials, onUpdate, readOnly = false, editable = false, onRequestQuote, onRequestAllQuotes, onAiEstimate }) {
  const [estimatingIdx, setEstimatingIdx] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [unpricedOnly, setUnpricedOnly] = useState(false)
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('desc')

  const updateMaterial = (idx, changes) => {
    const updated = materials.map((m, i) => {
      if (i !== idx) return m
      const next = { ...m, ...changes }
      // If order_qty was directly edited, use it; otherwise auto-calculate
      const installedQty = next.installed_qty || 0
      const wastePct = next.waste_pct || 0
      const orderQty = ('order_qty' in changes)
        ? (changes.order_qty || 0)
        : installedQty * (1 + wastePct)
      const unitPrice = next.unit_price || 0
      return {
        ...next,
        order_qty: Math.round(orderQty * 100) / 100,
        extended_cost: Math.round(orderQty * unitPrice * 100) / 100,
      }
    })
    onUpdate?.(updated)
  }

  const deleteMaterial = (idx) => {
    onUpdate?.(materials.filter((_, i) => i !== idx))
  }


  const handleTypeChange = (idx, newType) => {
    updateMaterial(idx, { material_type: newType, ai_confidence: 1.0 })
  }


  if (!materials?.length) {
    return (
      <div className="text-center py-12 text-gray-600">
        <Package className="w-10 h-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">No materials yet. Upload an RFMS file to get started.</p>
      </div>
    )
  }

  const showDeleteCol = editable
  const colCount = 6 + (showDeleteCol ? 1 : 0)



  // Toggle sort: click same col cycles desc→asc→off, new col starts desc
  const toggleSort = (col) => {
    if (sortCol === col) {
      if (sortDir === 'desc') setSortDir('asc')
      else { setSortCol(null); setSortDir('desc') }
    } else {
      setSortCol(col); setSortDir('desc')
    }
  }

  // Completion stats
  const pricedCount = materials.filter(m => (m.unit_price || 0) > 0).length
  const totalCount = materials.length
  const pricePct = totalCount > 0 ? pricedCount / totalCount : 0

  // Low confidence count
  const lowConfidenceCount = materials.filter(m => m.ai_confidence != null && m.ai_confidence < 0.7).length

  // Type subtotals (from all materials, not filtered)
  const typeSummary = useMemo(() => {
    const map = {}
    materials.forEach(m => {
      const t = m.material_type || 'unknown'
      if (!map[t]) map[t] = { type: t, total: 0, count: 0 }
      map[t].total += (m.extended_cost || 0)
      map[t].count += 1
    })
    return Object.values(map).filter(s => s.total > 0).sort((a, b) => b.total - a.total)
  }, [materials])

  const filteredMaterials = materials.map((m, i) => ({ ...m, _origIdx: i })).filter(m => {
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      const matches = (m.description || '').toLowerCase().includes(q) ||
                      (m.item_code || '').toLowerCase().includes(q) ||
                      (TYPE_LABELS[m.material_type] || m.material_type || '').toLowerCase().includes(q)
      if (!matches) return false
    }
    if (typeFilter && m.material_type !== typeFilter) return false
    if (unpricedOnly && (m.unit_price || 0) > 0) return false
    return true
  })

  // Apply sorting
  const displayMaterials = useMemo(() => {
    if (!sortCol) return filteredMaterials
    const sorted = [...filteredMaterials]
    const getVal = (m) => {
      switch (sortCol) {
        case 'type': return TYPE_LABELS[m.material_type] || m.material_type || ''
        case 'install_qty': return m.installed_qty || 0
        case 'waste': return m.waste_pct || 0
        case 'order_qty': return m.order_qty || 0
        case 'unit_price': return m.unit_price || 0
        case 'extended': return m.extended_cost || 0
        default: return 0
      }
    }
    sorted.sort((a, b) => {
      const va = getVal(a), vb = getVal(b)
      if (typeof va === 'string') return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va)
      return sortDir === 'asc' ? va - vb : vb - va
    })
    return sorted
  }, [filteredMaterials, sortCol, sortDir])

  const isFiltered = searchQuery || typeFilter || unpricedOnly

  return (
    <div className="overflow-x-auto">
      {materials.length > 5 && (
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 sm:gap-3 mb-4">
          <div className="relative flex-1 min-w-0">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-600" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter materials..."
              className="w-full pl-9 pr-3 py-2 sm:py-1.5 text-sm sm:text-xs bg-white/[0.04] border border-white/[0.06] rounded-lg
                         text-gray-300 placeholder-gray-600 focus:outline-none focus:border-white/[0.12] transition-colors"
            />
          </div>
          <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="text-sm sm:text-xs bg-white/[0.04] border border-white/[0.06] rounded-lg px-2.5 py-2 sm:py-1.5
                         text-gray-300 focus:outline-none focus:border-white/[0.12] transition-colors flex-1 sm:flex-none"
            >
              <option value="">All Types</option>
              {VALID_TYPES.map(t => (
                <option key={t} value={t}>{TYPE_LABELS[t] || t}</option>
              ))}
            </select>
            {onRequestQuote && (
              <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={unpricedOnly}
                  onChange={(e) => setUnpricedOnly(e.target.checked)}
                  className="accent-si-bright w-3.5 h-3.5 rounded"
                />
                Unpriced only
              </label>
            )}
            {(searchQuery || typeFilter || unpricedOnly) && (
              <button
                onClick={() => { setSearchQuery(''); setTypeFilter(''); setUnpricedOnly(false) }}
                className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}
      {/* Status bar: completion + confidence warnings */}
      {materials.length > 0 && (onRequestQuote || lowConfidenceCount > 0 || (pricedCount < totalCount && onRequestAllQuotes)) && (
        <div className="flex items-center gap-4 mb-3 flex-wrap text-xs">
          {(onRequestQuote || pricedCount < totalCount) && (
            <span className={`font-medium ${pricePct >= 1 ? 'text-emerald-400' : pricePct >= 0.5 ? 'text-amber-400' : 'text-red-400'}`}>
              {pricedCount}/{totalCount} priced
            </span>
          )}
          {lowConfidenceCount > 0 && (
            <span className="flex items-center gap-1 text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5" />
              {lowConfidenceCount} material{lowConfidenceCount !== 1 ? 's' : ''} with low AI confidence
            </span>
          )}
          {pricedCount < totalCount && onRequestAllQuotes && (
            <button
              onClick={onRequestAllQuotes}
              className="flex items-center gap-1 text-si-bright hover:text-si-bright/80 font-medium transition-colors ml-auto"
            >
              <Mail className="w-3.5 h-3.5" />
              Request quotes for all {totalCount - pricedCount} unpriced
            </button>
          )}
        </div>
      )}

      {/* Type subtotals summary bar */}
      {typeSummary.length > 1 && (
        <div className="flex items-center gap-1.5 mb-3 flex-wrap">
          {typeSummary.map(s => {
            const color = TYPE_COLORS[s.type] || 'bg-gray-500/10 text-gray-400 border-gray-500/10'
            const isActive = typeFilter === s.type
            return (
              <button key={s.type}
                onClick={() => setTypeFilter(isActive ? '' : s.type)}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] border transition-colors
                  ${isActive ? 'ring-1 ring-white/20 brightness-125' : 'hover:brightness-110'} ${color}`}
              >
                <span className="font-medium">{TYPE_LABELS[s.type] || s.type}</span>
                <span className="opacity-60">{formatCompact(s.total)}</span>
              </button>
            )
          })}
        </div>
      )}

      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-[#0c0c14]">
          <tr className="border-b border-white/[0.06]">
            {[
              { label: 'Material', key: null, align: 'left', hide: '', tooltip: 'Material description or item code' },
              { label: 'Type', key: 'type', align: 'left', hide: '', tooltip: 'Material type or category' },
              { label: 'Install Qty', key: 'install_qty', align: 'right', hide: 'hidden md:table-cell', tooltip: 'Quantity needed for installation' },
              { label: 'Waste', key: 'waste', align: 'right', hide: 'hidden lg:table-cell', tooltip: 'Waste factor percentage added to install quantity' },
              { label: 'Order Qty', key: 'order_qty', align: 'right', hide: 'hidden md:table-cell', tooltip: 'Quantity to order (install qty + waste)' },
              ...(onRequestQuote ? [{ label: 'Internal Price', key: 'known_price', align: 'right', hide: 'hidden lg:table-cell', tooltip: 'Price from your warehouse inventory or past vendor quotes' }] : []),
              { label: 'Total', key: 'extended', align: 'right', hide: '', tooltip: 'Your bid price for this line item' },
              ...(showDeleteCol ? [{ label: '', key: null, align: 'center', hide: '' }] : []),
            ].map((col, i) => (
              <th key={col.label || `col-${i}`}
                onClick={col.key ? () => toggleSort(col.key) : undefined}
                className={`py-3 px-2 sm:px-3 font-bold text-gray-500 text-[10px] uppercase tracking-[0.12em]
                  text-${col.align} ${col.label === '' ? 'w-10' : ''} ${col.hide}
                  ${col.key ? 'cursor-pointer hover:text-gray-300 select-none transition-colors' : ''}`}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {col.key && <SortIcon col={col.key} sortCol={sortCol} sortDir={sortDir} />}
                  {col.tooltip && (
                    <span className="relative group/tip">
                      <Info className="w-3 h-3 text-gray-600 hover:text-gray-400 transition-colors" />
                      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2.5 py-1.5 rounded-lg bg-gray-900 border border-white/10 text-[11px] text-gray-300 font-normal normal-case tracking-normal whitespace-nowrap opacity-0 pointer-events-none group-hover/tip:opacity-100 transition-opacity z-50 shadow-lg">
                        {col.tooltip}
                      </span>
                    </span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.03]">
          {displayMaterials.map((m) => {
            const hasPrice = m.unit_price > 0
            const lowConf = m.ai_confidence != null && m.ai_confidence < 0.7
            const veryLowConf = m.ai_confidence != null && m.ai_confidence < 0.5
            const rowBg = !hasPrice ? 'bg-amber-500/[0.04] border-l-2 border-l-amber-500/40' : veryLowConf ? 'bg-red-500/[0.06]' : lowConf ? 'bg-amber-500/[0.06]' : ''
            return (
              <tr key={m.id || m._origIdx} className={`group hover:bg-white/[0.02] transition-colors ${rowBg}`}>
                <td className="py-3 px-2 sm:px-3 max-w-0 sm:max-w-none">
                  {editable ? (
                    <EditableCell
                      value={m.description || m.item_code || ''}
                      onSave={(val) => updateMaterial(m._origIdx, { description: val })}
                      className="font-medium text-gray-200"
                    />
                  ) : (
                    <div className="font-medium text-gray-200 truncate sm:whitespace-normal">{m.description || m.item_code || '—'}</div>
                  )}
                  {m.item_code && m.description && (
                    <div className="text-[11px] text-gray-600 mt-0.5">{m.item_code}</div>
                  )}
                  {m.vendor && (
                    <div className="flex items-center gap-1 mt-0.5">
                      <Store className="w-3 h-3 text-emerald-500/70" />
                      <span className="text-[10px] text-emerald-500/70">{m.vendor}</span>
                    </div>
                  )}
                  {/* Show qty on mobile since column is hidden */}
                  <div className="md:hidden text-[11px] text-gray-500 mt-0.5">
                    {formatNumber(m.installed_qty)} {m.unit} · {((m.waste_pct || 0) * 100).toFixed(0)}% waste
                  </div>
                </td>
                <td className="py-3 px-2 sm:px-3">
                  <TypeDropdown
                    currentType={m.material_type}
                    confidence={m.ai_confidence}
                    onSelect={(t) => handleTypeChange(m._origIdx, t)}
                    editable={editable}
                  />
                </td>
                <td className="hidden md:table-cell py-3 px-2 sm:px-3 text-right tabular-nums text-gray-300">
                  {editable ? (
                    <EditableCell
                      value={m.installed_qty}
                      type="number"
                      onSave={(val) => updateMaterial(m._origIdx, { installed_qty: val })}
                    />
                  ) : (
                    formatNumber(m.installed_qty)
                  )}
                  {' '}<span className="text-gray-600 text-xs">{m.unit}</span>
                </td>
                <td className="hidden lg:table-cell py-3 px-2 sm:px-3 text-right tabular-nums text-gray-500">
                  {editable ? (
                    <EditableCell
                      value={((m.waste_pct || 0) * 100)}
                      type="number"
                      onSave={(val) => updateMaterial(m._origIdx, { waste_pct: val / 100 })}
                    />
                  ) : (
                    ((m.waste_pct || 0) * 100).toFixed(0)
                  )}%
                </td>
                <td className="hidden md:table-cell py-3 px-2 sm:px-3 text-right tabular-nums text-gray-300">
                  {editable ? (
                    <EditableCell
                      value={m.order_qty}
                      type="number"
                      onSave={(val) => updateMaterial(m._origIdx, { order_qty: val })}
                    />
                  ) : (
                    formatNumber(m.order_qty)
                  )}
                </td>
                {onRequestQuote && (
                  <td className="hidden lg:table-cell py-3 px-2 sm:px-3 text-right tabular-nums text-xs">
                    {m.known_price ? (
                      <div>
                        <span className="text-emerald-300 font-medium">{formatCurrency(m.known_price)}</span>
                        <span className={`block text-[10px] ${m.known_price_source === 'vendor_history' ? 'text-sky-500/60' : 'text-emerald-500/60'}`}>
                          {m.known_price_source === 'vendor_history' ? m.known_price_vendor || 'Past Quote' : 'In Stock'}
                        </span>
                      </div>
                    ) : (
                      <span className="text-gray-700">—</span>
                    )}
                  </td>
                )}
                <td className="py-3 px-2 sm:px-3 text-right tabular-nums font-medium">
                  {onRequestQuote ? (
                    <PriceActionMenu
                      material={m}
                      hasPrice={hasPrice}
                      extendedCost={m.extended_cost}
                      priceSource={m.price_source}
                      estimating={estimatingIdx === m._origIdx}
                      onSetTotal={(total) => {
                        const orderQty = m.order_qty || m.installed_qty || 1
                        const unitPrice = orderQty > 0 ? round2(total / orderQty) : total
                        updateMaterial(m._origIdx, { unit_price: unitPrice, extended_cost: round2(total), price_source: 'manual' })
                      }}
                      onRequestQuote={() => onRequestQuote(m)}
                      onAiEstimate={async () => {
                        if (!onAiEstimate) return
                        setEstimatingIdx(m._origIdx)
                        try {
                          await onAiEstimate(m._origIdx)
                        } finally {
                          setEstimatingIdx(null)
                        }
                      }}
                      onClearPrice={() => {
                        updateMaterial(m._origIdx, { unit_price: 0, extended_cost: 0, price_source: null })
                      }}
                    />
                  ) : hasPrice ? (
                    <span className="text-white">{formatCurrency(m.extended_cost)}</span>
                  ) : (
                    <span className="text-gray-600">—</span>
                  )}
                </td>
                {showDeleteCol && (
                  <td className="py-3 px-1 text-center">
                    <button
                      onClick={() => deleteMaterial(m._origIdx)}
                      className="p-1.5 rounded-lg text-gray-700 opacity-100 sm:opacity-0 sm:group-hover:opacity-100
                                 hover:text-red-400 hover:bg-red-500/10 transition-all"
                      title="Remove material"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-white/[0.08]">
            <td colSpan={colCount - 1} className="py-3 px-2 sm:px-3 text-right font-semibold text-gray-500 text-xs uppercase tracking-wider">
              Material Total
            </td>
            <td className="py-3 px-2 sm:px-3 text-right tabular-nums font-bold text-white">
              {formatCurrency(displayMaterials.reduce((sum, m) => sum + (m.extended_cost || 0), 0))}
              {isFiltered && (
                <div className="text-[10px] text-gray-600 font-normal mt-0.5">
                  of {formatCurrency(materials.reduce((sum, m) => sum + (m.extended_cost || 0), 0))} total
                </div>
              )}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
