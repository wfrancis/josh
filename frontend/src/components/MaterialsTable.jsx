import { useState, useRef, useEffect } from 'react'
import { Package, Trash2, Search } from 'lucide-react'

function formatCurrency(val) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0)
}
function formatNumber(val, decimals = 2) {
  return (val || 0).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
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
  if (confidence >= 0.9) colorClass = 'bg-emerald-400'
  else if (confidence >= 0.7) colorClass = 'bg-amber-400'
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${colorClass} flex-shrink-0`}
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

export default function MaterialsTable({ materials, onUpdate, readOnly = false, editable = false }) {
  const [editingPriceId, setEditingPriceId] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [unpricedOnly, setUnpricedOnly] = useState(false)

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

  const handlePriceChange = (idx, value) => {
    updateMaterial(idx, { unit_price: parseFloat(value) || 0 })
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

  const showPriceCol = !readOnly && !editable
  const showDeleteCol = editable
  const colCount = 6 + (showPriceCol ? 1 : 0) + (showDeleteCol ? 1 : 0)



  const displayMaterials = materials.map((m, i) => ({ ...m, _origIdx: i })).filter(m => {
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

  const isFiltered = searchQuery || typeFilter || unpricedOnly

  return (
    <div className="overflow-x-auto">
      {materials.length > 5 && (
        <div className="flex items-center gap-3 mb-4 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-600" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter materials..."
              className="w-full pl-9 pr-3 py-1.5 text-xs bg-white/[0.04] border border-white/[0.06] rounded-lg
                         text-gray-300 placeholder-gray-600 focus:outline-none focus:border-white/[0.12] transition-colors"
            />
          </div>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="text-xs bg-white/[0.04] border border-white/[0.06] rounded-lg px-2.5 py-1.5
                       text-gray-300 focus:outline-none focus:border-white/[0.12] transition-colors"
          >
            <option value="">All Types</option>
            {VALID_TYPES.map(t => (
              <option key={t} value={t}>{TYPE_LABELS[t] || t}</option>
            ))}
          </select>
          {showPriceCol && (
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
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/[0.06]">
            {['Material', 'Type', 'Install Qty', 'Waste', 'Order Qty',
              ...(showPriceCol ? ['Unit Price'] : []), 'Extended',
              ...(showDeleteCol ? [''] : [])].map((h, i) => (
              <th key={h || `col-${i}`} className={`py-3 px-2 sm:px-3 font-bold text-gray-500 text-[10px] uppercase tracking-[0.12em]
                ${h === 'Material' || h === 'Type' ? 'text-left' : 'text-right'}
                ${h === '' ? 'w-10' : ''}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.03]">
          {displayMaterials.map((m) => {
            const hasPrice = m.unit_price > 0
            return (
              <tr key={m.id || m._origIdx} className="group hover:bg-white/[0.02] transition-colors">
                <td className="py-3 px-2 sm:px-3">
                  {editable ? (
                    <EditableCell
                      value={m.description || m.item_code || ''}
                      onSave={(val) => updateMaterial(m._origIdx, { description: val })}
                      className="font-medium text-gray-200"
                    />
                  ) : (
                    <div className="font-medium text-gray-200">{m.description || m.item_code || '—'}</div>
                  )}
                  {m.item_code && m.description && (
                    <div className="text-[11px] text-gray-600 mt-0.5">{m.item_code}</div>
                  )}
                </td>
                <td className="py-3 px-2 sm:px-3">
                  <TypeDropdown
                    currentType={m.material_type}
                    confidence={m.ai_confidence}
                    onSelect={(t) => handleTypeChange(m._origIdx, t)}
                    editable={editable}
                  />
                </td>
                <td className="py-3 px-2 sm:px-3 text-right tabular-nums text-gray-300">
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
                <td className="py-3 px-2 sm:px-3 text-right tabular-nums text-gray-500">
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
                <td className="py-3 px-2 sm:px-3 text-right tabular-nums text-gray-300">
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
                {showPriceCol && (
                  <td className="py-3 px-2 sm:px-3 text-right">
                    <input
                      type="number" step="0.01" min="0"
                      value={m.unit_price || ''}
                      onChange={(e) => handlePriceChange(m._origIdx, e.target.value)}
                      onFocus={() => setEditingPriceId(m._origIdx)} onBlur={() => setEditingPriceId(null)}
                      placeholder="0.00"
                      className={`editable-cell w-24 ${!hasPrice && editingPriceId !== m._origIdx ? 'text-gray-600' : 'text-gray-100'}`}
                    />
                  </td>
                )}
                <td className="py-3 px-2 sm:px-3 text-right tabular-nums font-medium">
                  {hasPrice ? (
                    <span className="text-white">{formatCurrency(m.extended_cost)}</span>
                  ) : (
                    <span className="text-gray-600">—</span>
                  )}
                </td>
                {showDeleteCol && (
                  <td className="py-3 px-1 text-center">
                    <button
                      onClick={() => deleteMaterial(m._origIdx)}
                      className="p-1.5 rounded-lg text-gray-700 opacity-0 group-hover:opacity-100
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
