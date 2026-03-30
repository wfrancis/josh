import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import {
  FileDown, Loader2, ChevronDown, ChevronRight, ChevronUp,
  GripVertical, Pencil, Trash2, Plus, Save, RotateCcw, Eye, Check, X,
  Package, FileText, AlertTriangle, ArrowLeft, Combine, Square, CheckSquare, Sparkles
} from 'lucide-react'

function formatCurrency(val) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0)
}

function parseCurrencyInput(str) {
  const cleaned = String(str).replace(/[^0-9.-]/g, '')
  const num = parseFloat(cleaned)
  return isNaN(num) ? 0 : num
}

/* ─── Editable List (Notes, Terms, Exclusions) ───────────────────────── */
function EditableList({ title, items, onChange }) {
  const [editIdx, setEditIdx] = useState(null)
  const [editVal, setEditVal] = useState('')
  const [adding, setAdding] = useState(false)
  const [addVal, setAddVal] = useState('')

  const startEdit = (i) => {
    setEditIdx(i)
    setEditVal(items[i])
  }

  const saveEdit = () => {
    if (editIdx == null) return
    const next = [...items]
    next[editIdx] = editVal.trim()
    onChange(next.filter(Boolean))
    setEditIdx(null)
    setEditVal('')
  }

  const cancelEdit = () => {
    setEditIdx(null)
    setEditVal('')
  }

  const remove = (i) => {
    onChange(items.filter((_, idx) => idx !== i))
    if (editIdx === i) cancelEdit()
  }

  const addItem = () => {
    if (!addVal.trim()) return
    onChange([...items, addVal.trim()])
    setAddVal('')
    setAdding(false)
  }

  return (
    <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-bold text-white">{title}</h4>
        <button
          onClick={() => { setAdding(true); setAddVal('') }}
          className="flex items-center gap-1 text-xs text-si-accent hover:text-si-accent/80 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> Add
        </button>
      </div>

      {items.length === 0 && !adding && (
        <p className="text-xs text-gray-600 italic">No items yet.</p>
      )}

      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className="group flex items-start gap-2">
            {editIdx === i ? (
              <div className="flex-1 flex gap-2">
                <textarea
                  value={editVal}
                  onChange={(e) => setEditVal(e.target.value)}
                  rows={2}
                  className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm resize-none focus:outline-none focus:border-si-accent/50"
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit() } }}
                  autoFocus
                />
                <div className="flex flex-col gap-1">
                  <button onClick={saveEdit} className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors">
                    <Check className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={cancelEdit} className="p-1.5 rounded-lg bg-white/[0.04] text-gray-500 hover:bg-white/[0.08] transition-colors">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ) : (
              <>
                <span className="flex-1 text-sm text-gray-400 leading-relaxed">{item}</span>
                <button onClick={() => startEdit(i)} className="p-1 rounded text-gray-600 hover:text-gray-300 transition-colors opacity-0 group-hover:opacity-100">
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button onClick={() => remove(i)} className="p-1 rounded text-gray-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </>
            )}
          </div>
        ))}

        {adding && (
          <div className="flex gap-2">
            <textarea
              value={addVal}
              onChange={(e) => setAddVal(e.target.value)}
              rows={2}
              placeholder="Enter new item..."
              className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm resize-none placeholder:text-gray-600 focus:outline-none focus:border-si-accent/50"
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); addItem() } }}
              autoFocus
            />
            <div className="flex flex-col gap-1">
              <button onClick={addItem} className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors">
                <Check className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => { setAdding(false); setAddVal('') }} className="p-1.5 rounded-lg bg-white/[0.04] text-gray-500 hover:bg-white/[0.08] transition-colors">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/* ─── Helpers ─────────────────────────────────────────────────────────── */
function sumField(arr, key) { return arr.reduce((s, b) => s + (b[key] || 0), 0) }
function round2(n) { return Math.round(n * 100) / 100 }

/* ─── Combine Bundles Dialog ─────────────────────────────────────────── */
function CombineBundlesDialog({ bundles, selectedIndices, onCombine, onCancel }) {
  const selected = [...selectedIndices].sort((a, b) => a - b).map(i => bundles[i])
  const totalQty = round2(sumField(selected, 'installed_qty'))

  // Check if all selected bundles are exclusively cpt_tile
  const allCptTile = selected.every(b =>
    b.materials?.length > 0 && b.materials.every(m => m.material_type === 'cpt_tile')
  )

  // Check if any selected bundles contain common area materials
  const hasCommonArea = selected.some(b =>
    b.materials?.some(m => (m.area_type || '').toLowerCase() === 'common') ||
    b.bundle_name?.toLowerCase().includes('common')
  )
  const areaPrefix = hasCommonArea ? 'Common Area' : 'Unit'

  const [name, setName] = useState(() => {
    if (allCptTile) return `${areaPrefix} Carpet Tile`
    return selected[0]?.bundle_name || 'Combined Bundle'
  })
  const [addPattern, setAddPattern] = useState(false)

  const patternCost = round2(totalQty * 0.27)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#1a1d23] border border-white/[0.08] rounded-2xl w-full max-w-lg mx-4 shadow-2xl">
        <div className="p-5 border-b border-white/[0.06]">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Combine className="w-5 h-5 text-si-accent" />
            Combine {selected.length} Bundles
          </h3>
        </div>

        <div className="p-5 space-y-4">
          {/* Bundle name */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5 block">
              Combined Bundle Name
            </label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-si-accent/50"
              autoFocus
            />
          </div>

          {/* Summary of bundles being combined */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5 block">
              Bundles to Combine
            </label>
            <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] divide-y divide-white/[0.04] max-h-48 overflow-y-auto">
              {selected.map((b, i) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 text-sm">
                  <span className="text-gray-300">{b.bundle_name}</span>
                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    <span>{b.installed_qty} {b.unit}</span>
                    <span className="tabular-nums">{formatCurrency(b.total_price)}</span>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex justify-between mt-2 text-sm font-semibold">
              <span className="text-gray-400">Total</span>
              <span className="text-white">{totalQty} {selected[0]?.unit || 'SY'} — {formatCurrency(sumField(selected, 'total_price'))}</span>
            </div>
          </div>

          {/* Pattern addon - only for cpt_tile */}
          {allCptTile && (
            <div
              onClick={() => setAddPattern(!addPattern)}
              className="flex items-center gap-3 p-3 rounded-lg border border-white/[0.06] bg-white/[0.02] cursor-pointer hover:bg-white/[0.04] transition-colors"
            >
              {addPattern
                ? <CheckSquare className="w-5 h-5 text-si-accent flex-shrink-0" />
                : <Square className="w-5 h-5 text-gray-500 flex-shrink-0" />
              }
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white font-medium">Add Pattern Layout Labor</p>
                <p className="text-xs text-gray-500">
                  X ADD for Carpet Tile Pattern — +$0.27/SY × {totalQty} SY = {formatCurrency(patternCost)}
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 p-4 border-t border-white/[0.06]">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-400 hover:text-white rounded-lg hover:bg-white/[0.06] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onCombine(selectedIndices, name.trim() || 'Combined Bundle', addPattern)}
            disabled={!name.trim()}
            className="flex items-center gap-2 bg-si-accent hover:bg-si-accent/90 text-white font-medium rounded-xl px-5 py-2 text-sm transition-colors disabled:opacity-50"
          >
            <Combine className="w-4 h-4" />
            Combine
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─── Bundle Card ─────────────────────────────────────────────────────── */
function BundleCard({ bundle, index, total, onUpdate, onDelete, onMove, selectMode, selected, onToggleSelect }) {
  const [expanded, setExpanded] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [nameVal, setNameVal] = useState(bundle.bundle_name)
  const [descVal, setDescVal] = useState(bundle.description_text || '')
  const [priceVal, setPriceVal] = useState(String(bundle.price_override ?? bundle.total_price ?? 0))
  const [editingFreight, setEditingFreight] = useState(false)
  const [freightVal, setFreightVal] = useState(String(bundle.freight_override ?? bundle.freight_cost ?? 0))
  const [addingLabor, setAddingLabor] = useState(false)
  const [newLabor, setNewLabor] = useState({ labor_description: '', qty: '', unit: 'SY', rate: '' })
  const [editingLaborRate, setEditingLaborRate] = useState(null)
  const [laborRateVal, setLaborRateVal] = useState('')
  const [editingSundryPrice, setEditingSundryPrice] = useState(null)
  const [sundryPriceVal, setSundryPriceVal] = useState('')
  const [editingGpmLabor, setEditingGpmLabor] = useState(false)
  const [gpmLaborVal, setGpmLaborVal] = useState(String(bundle.gpm_labor_adder || 0))
  const [editingGpmMaterial, setEditingGpmMaterial] = useState(false)
  const [gpmMaterialVal, setGpmMaterialVal] = useState(String(bundle.gpm_material_adder || 0))
  const [showStairLabor, setShowStairLabor] = useState(false)
  const [stairLaborOptions, setStairLaborOptions] = useState([])
  const [stairCountVal, setStairCountVal] = useState(String(bundle.stair_count || ''))
  const [editingStairCount, setEditingStairCount] = useState(false)
  const [editingLaborQty, setEditingLaborQty] = useState(null)
  const [laborQtyVal, setLaborQtyVal] = useState('')

  // Sync local state when bundle prop changes
  useEffect(() => {
    setNameVal(bundle.bundle_name)
    setDescVal(bundle.description_text || '')
    setPriceVal(String(bundle.price_override ?? bundle.total_price ?? 0))
    setFreightVal(String(bundle.freight_override ?? bundle.freight_cost ?? 0))
    setStairCountVal(String(bundle.stair_count || ''))
  }, [bundle])

  const saveName = () => {
    const trimmed = nameVal.trim()
    if (trimmed) onUpdate(index, { ...bundle, bundle_name: trimmed })
    else setNameVal(bundle.bundle_name)
    setEditingName(false)
  }

  const saveDescription = (val) => {
    setDescVal(val)
    onUpdate(index, { ...bundle, description_text: val })
  }

  const savePrice = () => {
    const num = parseCurrencyInput(priceVal)
    setPriceVal(String(num))
    onUpdate(index, { ...bundle, price_override: num })
  }

  const saveFreight = () => {
    const num = parseCurrencyInput(freightVal)
    setFreightVal(String(num))
    setEditingFreight(false)
    onUpdate(index, { ...bundle, freight_override: num })
  }

  const saveGpmLabor = () => {
    const num = parseCurrencyInput(gpmLaborVal)
    setGpmLaborVal(String(num))
    setEditingGpmLabor(false)
    const oldAdder = (bundle.gpm_labor_adder || 0) + (bundle.gpm_material_adder || 0)
    const newAdder = num + (bundle.gpm_material_adder || 0)
    const diff = newAdder - oldAdder
    onUpdate(index, {
      ...bundle,
      gpm_labor_adder: num,
      gpm_adder: round2(newAdder),
      total_price: round2((bundle.total_price || 0) + diff),
      price_override: undefined,
    })
  }

  const saveGpmMaterial = () => {
    const num = parseCurrencyInput(gpmMaterialVal)
    setGpmMaterialVal(String(num))
    setEditingGpmMaterial(false)
    const oldAdder = (bundle.gpm_labor_adder || 0) + (bundle.gpm_material_adder || 0)
    const newAdder = (bundle.gpm_labor_adder || 0) + num
    const diff = newAdder - oldAdder
    // Recalculate tax since GPM material adder affects taxable base
    const taxRate = bundle.tax_amount && bundle.taxable ? bundle.tax_amount / bundle.taxable : 0
    const oldTaxable = bundle.taxable || 0
    const newTaxable = round2(oldTaxable - (bundle.gpm_material_adder || 0) + num)
    const newTax = round2(newTaxable * taxRate)
    const taxDiff = newTax - (bundle.tax_amount || 0)
    onUpdate(index, {
      ...bundle,
      gpm_material_adder: num,
      gpm_adder: round2(newAdder),
      taxable: newTaxable,
      tax_amount: newTax,
      total_price: round2((bundle.total_price || 0) + diff + taxDiff),
      price_override: undefined,
    })
  }

  const deleteLabor = (laborIdx) => {
    const updatedLabor = (bundle.labor_items || []).filter((_, i) => i !== laborIdx)
    const newLaborCost = round2(updatedLabor.reduce((s, l) => s + (l.extended_cost || 0), 0))
    const diff = newLaborCost - (bundle.labor_cost || 0)
    onUpdate(index, {
      ...bundle,
      labor_items: updatedLabor,
      labor_cost: newLaborCost,
      total_price: round2((bundle.total_price || 0) + diff),
      price_override: null,
    })
  }

  const addLabor = () => {
    const qty = parseFloat(newLabor.qty) || 0
    const rate = parseFloat(newLabor.rate) || 0
    if (!newLabor.labor_description.trim() || qty <= 0 || rate <= 0) return
    const extCost = round2(qty * rate)
    const newItem = {
      labor_description: newLabor.labor_description.trim(),
      qty, unit: newLabor.unit, rate, extended_cost: extCost,
    }
    const updatedLabor = [...(bundle.labor_items || []), newItem]
    const newLaborCost = round2(updatedLabor.reduce((s, l) => s + (l.extended_cost || 0), 0))
    const diff = newLaborCost - (bundle.labor_cost || 0)
    onUpdate(index, {
      ...bundle,
      labor_items: updatedLabor,
      labor_cost: newLaborCost,
      total_price: round2((bundle.total_price || 0) + diff),
      price_override: null,
    })
    setNewLabor({ labor_description: '', qty: '', unit: 'SY', rate: '' })
    setAddingLabor(false)
  }

  const saveLaborRate = (laborIdx) => {
    const newRate = parseFloat(laborRateVal) || 0
    if (newRate <= 0) { setEditingLaborRate(null); return }
    const updatedLabor = (bundle.labor_items || []).map((l, i) => {
      if (i !== laborIdx) return l
      const extCost = round2(l.qty * newRate)
      return { ...l, rate: newRate, extended_cost: extCost }
    })
    const newLaborCost = round2(updatedLabor.reduce((s, l) => s + (l.extended_cost || 0), 0))
    const diff = newLaborCost - (bundle.labor_cost || 0)
    onUpdate(index, {
      ...bundle,
      labor_items: updatedLabor,
      labor_cost: newLaborCost,
      total_price: round2((bundle.total_price || 0) + diff),
      price_override: null,
    })
    setEditingLaborRate(null)
  }

  const saveLaborQty = (laborIdx) => {
    const newQty = parseFloat(laborQtyVal) || 0
    if (newQty <= 0) { setEditingLaborQty(null); return }
    const updatedLabor = (bundle.labor_items || []).map((l, i) => {
      if (i !== laborIdx) return l
      const extCost = round2(newQty * l.rate)
      return { ...l, qty: newQty, extended_cost: extCost }
    })
    const newLaborCost = round2(updatedLabor.reduce((s, l) => s + (l.extended_cost || 0), 0))
    const diff = newLaborCost - (bundle.labor_cost || 0)
    onUpdate(index, {
      ...bundle,
      labor_items: updatedLabor,
      labor_cost: newLaborCost,
      total_price: round2((bundle.total_price || 0) + diff),
      price_override: null,
    })
    setEditingLaborQty(null)
  }

  const saveSundryPrice = (sundryIdx) => {
    const newPrice = parseFloat(sundryPriceVal) || 0
    if (newPrice <= 0) { setEditingSundryPrice(null); return }
    const updatedSundries = (bundle.sundry_items || []).map((s, i) => {
      if (i !== sundryIdx) return s
      const extCost = round2(s.qty * newPrice)
      return { ...s, unit_price: newPrice, extended_cost: extCost }
    })
    const newSundryCost = round2(updatedSundries.reduce((s, item) => s + (item.extended_cost || 0), 0))
    const diff = newSundryCost - (bundle.sundry_cost || 0)
    onUpdate(index, {
      ...bundle,
      sundry_items: updatedSundries,
      sundry_cost: newSundryCost,
      total_price: round2((bundle.total_price || 0) + diff),
      price_override: null,
    })
    setEditingSundryPrice(null)
  }

  // ── Stair Labor ──────────────────────────────────────────────────────────
  const STAIR_KITS = {
    stretched: [
      { sundry_name: 'Stair Pad (6lb 3/8″)', ratio_per_stair: 0.74, unit: 'SY', unit_price: 1.38, roll_size: 30 },
      { sundry_name: 'Stair Tack Strip', ratio_per_stair: 6.0, unit: 'LF', unit_price: 0 },
      { sundry_name: 'Stair Seam Sealer', ratio_per_stair: 5.307, unit: 'LF', unit_price: 0 },
    ],
  }

  const calcSundryQty = (rule, count) => {
    const raw = rule.ratio_per_stair * count
    if (rule.roll_size) return Math.ceil(raw / rule.roll_size) * rule.roll_size
    return round2(raw)
  }

  const fetchStairLaborOptions = async () => {
    if (stairLaborOptions.length > 0) { setShowStairLabor(true); return }
    try {
      const res = await fetch('/api/labor-catalog/stairs').then(r => r.ok ? r.json() : null)
      if (res?.entries) { setStairLaborOptions(res.entries); setShowStairLabor(true) }
    } catch (e) { console.error('Failed to fetch stair labor:', e) }
  }

  const addStairLabor = (catalogEntry) => {
    const count = parseInt(stairCountVal) || bundle.stair_count || 0
    if (count <= 0) { setEditingStairCount(true); setShowStairLabor(false); return }

    const laborItem = {
      labor_description: `${catalogEntry.description}`,
      qty: count, unit: 'EA', rate: catalogEntry.cost,
      extended_cost: round2(count * catalogEntry.cost),
      is_stair_labor: true,
    }

    const kitType = (catalogEntry.description || '').toLowerCase().includes('stretch') ? 'stretched' : null
    const kitSundries = (STAIR_KITS[kitType] || []).map(s => {
      const qty = calcSundryQty(s, count)
      return {
        sundry_name: s.sundry_name, qty, unit: s.unit,
        unit_price: s.unit_price, extended_cost: round2(qty * s.unit_price),
        is_stair_sundry: true,
      }
    })

    const updatedLabor = [...(bundle.labor_items || []), laborItem]
    const updatedSundries = [...(bundle.sundry_items || []), ...kitSundries]
    const newLaborCost = round2(updatedLabor.reduce((s, l) => s + (l.extended_cost || 0), 0))
    const newSundryCost = round2(updatedSundries.reduce((s, item) => s + (item.extended_cost || 0), 0))
    const laborDiff = newLaborCost - (bundle.labor_cost || 0)
    const sundryDiff = newSundryCost - (bundle.sundry_cost || 0)

    onUpdate(index, {
      ...bundle,
      labor_items: updatedLabor,
      sundry_items: updatedSundries,
      labor_cost: newLaborCost,
      sundry_cost: newSundryCost,
      total_price: round2((bundle.total_price || 0) + laborDiff + sundryDiff),
      stair_count: count,
      stair_labor_type: kitType,
      price_override: null,
    })
    setShowStairLabor(false)
  }

  const saveStairCount = () => {
    const newCount = parseInt(stairCountVal) || 0
    setEditingStairCount(false)
    if (newCount === (bundle.stair_count || 0)) return

    // Update stair labor quantities
    const updatedLabor = (bundle.labor_items || []).map(l => {
      if (!l.is_stair_labor) return l
      return { ...l, qty: newCount, extended_cost: round2(newCount * l.rate) }
    })

    // Update stair sundry quantities
    const kitType = bundle.stair_labor_type || 'stretched'
    const kit = STAIR_KITS[kitType] || []
    const updatedSundries = (bundle.sundry_items || []).map(s => {
      if (!s.is_stair_sundry) return s
      const rule = kit.find(k => k.sundry_name === s.sundry_name)
      if (!rule) return s
      const qty = calcSundryQty(rule, newCount)
      return { ...s, qty, extended_cost: round2(qty * s.unit_price) }
    })

    const newLaborCost = round2(updatedLabor.reduce((s, l) => s + (l.extended_cost || 0), 0))
    const newSundryCost = round2(updatedSundries.reduce((s, item) => s + (item.extended_cost || 0), 0))
    const laborDiff = newLaborCost - (bundle.labor_cost || 0)
    const sundryDiff = newSundryCost - (bundle.sundry_cost || 0)

    onUpdate(index, {
      ...bundle,
      labor_items: updatedLabor,
      sundry_items: updatedSundries,
      labor_cost: newLaborCost,
      sundry_cost: newSundryCost,
      total_price: round2((bundle.total_price || 0) + laborDiff + sundryDiff),
      stair_count: newCount,
      price_override: null,
    })
  }

  const materialCount = bundle.materials?.length || 0
  const freightAdj = bundle.freight_override != null ? (bundle.freight_override - (bundle.freight_cost || 0)) : 0
  const displayPrice = bundle.price_override ?? ((bundle.total_price ?? 0) + freightAdj)
  const descPreview = (bundle.description_text || '').split('\n').slice(0, 2).join('\n')
  const hasMoreDesc = (bundle.description_text || '').split('\n').length > 2

  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.06] bg-white/[0.02] transition-colors">
      {/* Header row */}
      <div className="flex items-center gap-2 p-3 sm:p-4">
        {/* Select checkbox (combine mode) */}
        {selectMode && (
          <button
            onClick={() => onToggleSelect(index)}
            className="flex-shrink-0 p-0.5 rounded transition-colors"
          >
            {selected
              ? <CheckSquare className="w-5 h-5 text-si-accent" />
              : <Square className="w-5 h-5 text-gray-500 hover:text-gray-300" />
            }
          </button>
        )}

        {/* Drag handle / index */}
        <div className="flex-shrink-0 flex items-center gap-1 text-gray-600">
          <GripVertical className="w-4 h-4" />
          <span className="text-[10px] font-mono w-4 text-center">{index + 1}</span>
        </div>

        {/* Name */}
        <div className="flex-1 min-w-0">
          {editingName ? (
            <div className="flex items-center gap-2">
              <input
                value={nameVal}
                onChange={(e) => setNameVal(e.target.value)}
                className="bg-white/[0.04] border border-white/[0.08] rounded-lg px-2 py-1 text-white text-sm font-semibold focus:outline-none focus:border-si-accent/50 w-full"
                onKeyDown={(e) => { if (e.key === 'Enter') saveName(); if (e.key === 'Escape') { setNameVal(bundle.bundle_name); setEditingName(false) } }}
                autoFocus
                onBlur={saveName}
              />
            </div>
          ) : (
            <button
              onClick={() => setEditingName(true)}
              className="flex items-center gap-1.5 group text-left"
              title="Click to edit name"
            >
              <span className="font-semibold text-white text-sm truncate">{bundle.bundle_name}</span>
              <Pencil className="w-3 h-3 text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
            </button>
          )}
          {!expanded && descPreview && (
            <p className="text-xs text-gray-500 mt-0.5 line-clamp-2 leading-relaxed">{descPreview}</p>
          )}
        </div>

        {/* Material count badge */}
        {materialCount > 0 && (
          <span className="flex-shrink-0 text-[10px] bg-white/[0.04] border border-white/[0.06] rounded-full px-2 py-0.5 text-gray-400 tabular-nums">
            {materialCount} item{materialCount !== 1 ? 's' : ''}
          </span>
        )}

        {/* Price */}
        <div className="flex-shrink-0 text-right">
          <span className="font-bold text-white text-sm tabular-nums">{formatCurrency(displayPrice)}</span>
        </div>

        {/* Actions */}
        <div className="flex-shrink-0 flex items-center gap-0.5">
          <button
            onClick={() => onMove(index, -1)}
            disabled={index === 0}
            className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/[0.06] disabled:opacity-20 disabled:cursor-not-allowed transition-colors"
            title="Move up"
          >
            <ChevronUp className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => onMove(index, 1)}
            disabled={index === total - 1}
            className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/[0.06] disabled:opacity-20 disabled:cursor-not-allowed transition-colors"
            title="Move down"
          >
            <ChevronDown className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 rounded-lg text-gray-500 hover:text-si-accent hover:bg-white/[0.06] transition-colors"
            title={expanded ? 'Collapse' : 'Edit bundle'}
          >
            {expanded ? <X className="w-3.5 h-3.5" /> : <Pencil className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={() => onDelete(index)}
            className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
            title="Delete bundle"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Expanded editing panel */}
      {expanded && (
        <div className="px-3 sm:px-4 pb-4 border-t border-white/[0.04] pt-3 space-y-4 animate-fade-in">
          {/* Description textarea */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5 block">Description</label>
            <textarea
              value={descVal}
              onChange={(e) => saveDescription(e.target.value)}
              rows={4}
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm resize-none focus:outline-none focus:border-si-accent/50 leading-relaxed"
              placeholder="Bundle description for the proposal..."
            />
          </div>

          {/* Stair Count */}
          <div className="flex items-center gap-3">
            <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Stair Count</label>
            {editingStairCount ? (
              <input
                type="number"
                value={stairCountVal}
                onChange={(e) => setStairCountVal(e.target.value)}
                onBlur={saveStairCount}
                onKeyDown={(e) => { if (e.key === 'Enter') saveStairCount(); if (e.key === 'Escape') { setStairCountVal(String(bundle.stair_count || '')); setEditingStairCount(false) } }}
                className="w-24 bg-white/[0.04] border border-si-accent/50 rounded px-2 py-1 text-white text-xs text-right focus:outline-none tabular-nums"
                autoFocus
                placeholder="0"
              />
            ) : (
              <span
                onClick={() => setEditingStairCount(true)}
                className="cursor-pointer text-gray-300 tabular-nums text-xs hover:text-si-accent transition-colors px-2 py-1 rounded hover:bg-white/[0.04]"
                title="Click to edit stair count"
              >
                {bundle.stair_count || '—'}
              </span>
            )}
          </div>

          {/* Materials table */}
          {materialCount > 0 && (
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5 block">
                Materials ({materialCount})
              </label>
              <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-gray-500">
                      <th className="text-left px-3 py-2 font-medium">Item</th>
                      <th className="text-left px-3 py-2 font-medium">Description</th>
                      <th className="text-right px-3 py-2 font-medium">Order Qty</th>
                      <th className="text-right px-3 py-2 font-medium">Unit</th>
                      <th className="text-right px-3 py-2 font-medium">Unit Price</th>
                      <th className="text-right px-3 py-2 font-medium">Ext Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {bundle.materials.map((mat, mi) => (
                      <tr key={mi} className="hover:bg-white/[0.02]">
                        <td className="px-3 py-2 text-si-accent font-mono whitespace-nowrap">{mat.item_code || '—'}</td>
                        <td className="px-3 py-2 text-gray-400 max-w-[300px] truncate">{mat.description || '—'}</td>
                        <td className="px-3 py-2 text-gray-300 tabular-nums text-right whitespace-nowrap">
                          {(mat.order_qty || mat.installed_qty) != null ? Number(mat.order_qty || mat.installed_qty).toLocaleString(undefined, {maximumFractionDigits: 1}) : '—'}
                        </td>
                        <td className="px-3 py-2 text-gray-500 text-right">{mat.unit || ''}</td>
                        <td className="px-3 py-2 text-gray-300 tabular-nums text-right whitespace-nowrap">
                          {mat.unit_price != null ? formatCurrency(mat.unit_price) : '—'}
                        </td>
                        <td className="px-3 py-2 text-white tabular-nums text-right font-medium whitespace-nowrap">
                          {mat.extended_cost != null ? formatCurrency(mat.extended_cost) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-white/[0.08]">
                      <td colSpan={5} className="px-3 py-2 text-gray-500 text-right font-medium">Material Total</td>
                      <td className="px-3 py-2 text-white tabular-nums text-right font-bold">{formatCurrency(bundle.material_cost)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}

          {/* Sundries table */}
          {(bundle.sundry_items?.length > 0 || bundle.sundry_cost > 0) && (
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5 block">
                Sundries ({bundle.sundry_items?.length || 0})
              </label>
              <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-gray-500">
                      <th className="text-left px-3 py-2 font-medium">Sundry</th>
                      <th className="text-right px-3 py-2 font-medium">Qty</th>
                      <th className="text-right px-3 py-2 font-medium">Unit</th>
                      <th className="text-right px-3 py-2 font-medium">Unit Price</th>
                      <th className="text-right px-3 py-2 font-medium">Ext Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {(bundle.sundry_items || []).map((s, si) => (
                      <tr key={si} className="hover:bg-white/[0.02]">
                        <td className="px-3 py-2 text-gray-400">{s.sundry_name || '—'}</td>
                        <td className="px-3 py-2 text-gray-300 tabular-nums text-right">{s.qty != null ? Number(s.qty).toLocaleString(undefined, {maximumFractionDigits: 1}) : '—'}</td>
                        <td className="px-3 py-2 text-gray-500 text-right">{s.unit || ''}</td>
                        <td className="px-3 py-2 text-right">
                          {editingSundryPrice === si ? (
                            <input
                              type="number"
                              step="0.01"
                              value={sundryPriceVal}
                              onChange={(e) => setSundryPriceVal(e.target.value)}
                              onBlur={() => saveSundryPrice(si)}
                              onKeyDown={(e) => { if (e.key === 'Enter') saveSundryPrice(si); if (e.key === 'Escape') setEditingSundryPrice(null) }}
                              className="w-20 bg-white/[0.04] border border-si-accent/50 rounded px-2 py-0.5 text-white text-xs text-right focus:outline-none tabular-nums"
                              autoFocus
                            />
                          ) : (
                            <span
                              onClick={() => { setEditingSundryPrice(si); setSundryPriceVal(String(s.unit_price ?? '')) }}
                              className="cursor-pointer text-gray-300 tabular-nums hover:text-si-accent transition-colors"
                              title="Click to edit price"
                            >
                              {s.unit_price != null ? formatCurrency(s.unit_price) : '—'}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-white tabular-nums text-right font-medium">{s.extended_cost != null ? formatCurrency(s.extended_cost) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-white/[0.08]">
                      <td colSpan={4} className="px-3 py-2 text-gray-500 text-right font-medium">Sundry Total</td>
                      <td className="px-3 py-2 text-white tabular-nums text-right font-bold">{formatCurrency(bundle.sundry_cost)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}

          {/* Labor table */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
                Labor ({bundle.labor_items?.length || 0})
              </label>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => { setAddingLabor(true); setNewLabor({ labor_description: '', qty: '', unit: 'SY', rate: '' }) }}
                  className="flex items-center gap-1 text-[10px] text-si-accent hover:text-si-accent/80 transition-colors"
                >
                  <Plus className="w-3 h-3" /> Add Labor
                </button>
                <div className="relative">
                  <button
                    onClick={fetchStairLaborOptions}
                    className="flex items-center gap-1 text-[10px] text-amber-400 hover:text-amber-300 transition-colors"
                  >
                    <Plus className="w-3 h-3" /> Add Stair Labor
                  </button>
                  {showStairLabor && stairLaborOptions.length > 0 && (
                    <div className="absolute right-0 top-full mt-1 z-50 bg-gray-900 border border-white/[0.1] rounded-lg shadow-xl py-1 min-w-[280px] max-h-60 overflow-y-auto">
                      {stairLaborOptions.map((opt, oi) => (
                        <button
                          key={oi}
                          onClick={() => addStairLabor(opt)}
                          className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-white/[0.06] hover:text-white transition-colors flex justify-between items-center gap-2"
                        >
                          <span className="truncate">{opt.description}</span>
                          <span className="text-gray-500 tabular-nums flex-shrink-0">{formatCurrency(opt.cost)}/{opt.unit}</span>
                        </button>
                      ))}
                      <button
                        onClick={() => setShowStairLabor(false)}
                        className="w-full text-left px-3 py-1.5 text-[10px] text-gray-600 hover:text-gray-400 border-t border-white/[0.06]"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-white/[0.06] text-gray-500">
                    <th className="text-left px-3 py-2 font-medium">Description</th>
                    <th className="text-right px-3 py-2 font-medium">Qty</th>
                    <th className="text-right px-3 py-2 font-medium">Unit</th>
                    <th className="text-right px-3 py-2 font-medium">Rate</th>
                    <th className="text-right px-3 py-2 font-medium">Ext Cost</th>
                    <th className="w-8"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {(bundle.labor_items || []).map((l, li) => (
                    <tr key={li} className="group hover:bg-white/[0.02]">
                      <td className="px-3 py-2 text-gray-400">{l.labor_description || '—'}</td>
                      <td className="px-3 py-2 text-right">
                        {editingLaborQty === li ? (
                          <input
                            type="number"
                            step="0.01"
                            value={laborQtyVal}
                            onChange={(e) => setLaborQtyVal(e.target.value)}
                            onBlur={() => saveLaborQty(li)}
                            onKeyDown={(e) => { if (e.key === 'Enter') saveLaborQty(li); if (e.key === 'Escape') setEditingLaborQty(null) }}
                            className="w-20 bg-white/[0.04] border border-si-accent/50 rounded px-2 py-0.5 text-white text-xs text-right focus:outline-none tabular-nums"
                            autoFocus
                          />
                        ) : (
                          <span
                            onClick={() => { setEditingLaborQty(li); setLaborQtyVal(String(l.qty ?? '')) }}
                            className="cursor-pointer text-gray-300 tabular-nums hover:text-si-accent transition-colors"
                            title="Click to edit qty"
                          >
                            {l.qty != null ? Number(l.qty).toLocaleString(undefined, {maximumFractionDigits: 1}) : '—'}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-gray-500 text-right">{l.unit || ''}</td>
                      <td className="px-3 py-2 text-right">
                        {editingLaborRate === li ? (
                          <input
                            type="number"
                            step="0.01"
                            value={laborRateVal}
                            onChange={(e) => setLaborRateVal(e.target.value)}
                            onBlur={() => saveLaborRate(li)}
                            onKeyDown={(e) => { if (e.key === 'Enter') saveLaborRate(li); if (e.key === 'Escape') setEditingLaborRate(null) }}
                            className="w-20 bg-white/[0.04] border border-si-accent/50 rounded px-2 py-0.5 text-white text-xs text-right focus:outline-none tabular-nums"
                            autoFocus
                          />
                        ) : (
                          <span
                            onClick={() => { setEditingLaborRate(li); setLaborRateVal(String(l.rate ?? '')) }}
                            className="cursor-pointer text-gray-300 tabular-nums hover:text-si-accent transition-colors"
                            title="Click to edit rate"
                          >
                            {l.rate != null ? formatCurrency(l.rate) : '—'}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-white tabular-nums text-right font-medium">{l.extended_cost != null ? formatCurrency(l.extended_cost) : '—'}</td>
                      <td className="px-1 py-2">
                        <button
                          onClick={() => deleteLabor(li)}
                          className="p-1 rounded text-gray-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                          title="Delete labor line"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {addingLabor && (
                    <tr className="bg-white/[0.03]">
                      <td className="px-2 py-1.5">
                        <input
                          type="text"
                          value={newLabor.labor_description}
                          onChange={(e) => setNewLabor({ ...newLabor, labor_description: e.target.value })}
                          placeholder="Labor description"
                          className="w-full bg-white/[0.04] border border-white/[0.08] rounded px-2 py-1 text-white text-xs focus:outline-none focus:border-si-accent/50"
                          autoFocus
                          onKeyDown={(e) => { if (e.key === 'Enter') addLabor(); if (e.key === 'Escape') setAddingLabor(false) }}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <input
                          type="number"
                          value={newLabor.qty}
                          onChange={(e) => setNewLabor({ ...newLabor, qty: e.target.value })}
                          placeholder="Qty"
                          className="w-20 bg-white/[0.04] border border-white/[0.08] rounded px-2 py-1 text-white text-xs text-right focus:outline-none focus:border-si-accent/50"
                          onKeyDown={(e) => { if (e.key === 'Enter') addLabor(); if (e.key === 'Escape') setAddingLabor(false) }}
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <select
                          value={newLabor.unit}
                          onChange={(e) => setNewLabor({ ...newLabor, unit: e.target.value })}
                          className="bg-white/[0.04] border border-white/[0.08] rounded px-2 py-1 text-white text-xs focus:outline-none focus:border-si-accent/50"
                        >
                          <option value="SY">SY</option>
                          <option value="SF">SF</option>
                          <option value="LF">LF</option>
                          <option value="EA">EA</option>
                        </select>
                      </td>
                      <td className="px-2 py-1.5">
                        <input
                          type="number"
                          step="0.01"
                          value={newLabor.rate}
                          onChange={(e) => setNewLabor({ ...newLabor, rate: e.target.value })}
                          placeholder="Rate"
                          className="w-20 bg-white/[0.04] border border-white/[0.08] rounded px-2 py-1 text-white text-xs text-right focus:outline-none focus:border-si-accent/50"
                          onKeyDown={(e) => { if (e.key === 'Enter') addLabor(); if (e.key === 'Escape') setAddingLabor(false) }}
                        />
                      </td>
                      <td className="px-2 py-1.5 text-gray-500 text-xs text-right tabular-nums">
                        {(parseFloat(newLabor.qty) || 0) > 0 && (parseFloat(newLabor.rate) || 0) > 0
                          ? formatCurrency((parseFloat(newLabor.qty) || 0) * (parseFloat(newLabor.rate) || 0))
                          : '—'}
                      </td>
                      <td className="px-1 py-1.5">
                        <div className="flex flex-col gap-0.5">
                          <button onClick={addLabor} className="p-0.5 rounded text-emerald-400 hover:bg-emerald-500/20 transition-colors" title="Save">
                            <Check className="w-3.5 h-3.5" />
                          </button>
                          <button onClick={() => setAddingLabor(false)} className="p-0.5 rounded text-gray-500 hover:text-gray-300 transition-colors" title="Cancel">
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
                {(bundle.labor_items?.length > 0 || bundle.labor_cost > 0) && (
                  <tfoot>
                    <tr className="border-t border-white/[0.08]">
                      <td colSpan={5} className="px-3 py-2 text-gray-500 text-right font-medium">Labor Total</td>
                      <td className="px-3 py-2 text-white tabular-nums text-right font-bold">{formatCurrency(bundle.labor_cost)}</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </div>

          {/* Cost Summary */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5 block">Cost Summary</label>
            <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] p-3 space-y-1.5 text-xs">
              <div className="flex justify-between text-gray-400">
                <span>Material</span><span className="tabular-nums text-gray-300">{formatCurrency(bundle.material_cost)}</span>
              </div>
              {bundle.sundry_cost > 0 && (
                <div className="flex justify-between text-gray-400">
                  <span>Sundries</span><span className="tabular-nums text-gray-300">{formatCurrency(bundle.sundry_cost)}</span>
                </div>
              )}
              {bundle.labor_cost > 0 && (
                <div className="flex justify-between text-gray-400">
                  <span>Labor</span><span className="tabular-nums text-gray-300">{formatCurrency(bundle.labor_cost)}</span>
                </div>
              )}
              {(bundle.freight_override ?? bundle.freight_cost) > 0 || editingFreight ? (
                <div className="flex justify-between items-center text-gray-400">
                  <span>Freight</span>
                  {editingFreight ? (
                    <div className="flex items-center gap-1">
                      <span className="text-gray-500 text-xs">$</span>
                      <input
                        autoFocus
                        type="text"
                        value={freightVal}
                        onChange={(e) => setFreightVal(e.target.value)}
                        onBlur={saveFreight}
                        onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') { setFreightVal(String(bundle.freight_override ?? bundle.freight_cost ?? 0)); setEditingFreight(false) } }}
                        className="bg-white/[0.06] border border-white/[0.12] rounded px-2 py-0.5 text-white text-xs tabular-nums focus:outline-none focus:border-si-accent/50 w-24 text-right"
                      />
                    </div>
                  ) : (
                    <span
                      className="tabular-nums text-gray-300 cursor-pointer hover:text-si-accent transition-colors"
                      onClick={() => setEditingFreight(true)}
                      title="Click to edit freight"
                    >
                      {formatCurrency(bundle.freight_override ?? bundle.freight_cost)}
                    </span>
                  )}
                </div>
              ) : null}
              <div className="flex justify-between text-gray-400">
                <span>GPM Labor</span>
                {editingGpmLabor ? (
                  <input
                    autoFocus
                    type="text"
                    value={gpmLaborVal}
                    onChange={(e) => setGpmLaborVal(e.target.value)}
                    onBlur={saveGpmLabor}
                    onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') { setGpmLaborVal(String(bundle.gpm_labor_adder || 0)); setEditingGpmLabor(false) } }}
                    className="bg-white/[0.06] border border-white/[0.12] rounded px-2 py-0.5 text-emerald-400 text-xs tabular-nums focus:outline-none focus:border-emerald-400/50 w-28 text-right"
                  />
                ) : (
                  <span
                    className="tabular-nums text-emerald-400 cursor-pointer hover:text-emerald-300 transition-colors"
                    onClick={() => { setGpmLaborVal(String(bundle.gpm_labor_adder || 0)); setEditingGpmLabor(true) }}
                    title="Click to edit GPM labor"
                  >
                    {formatCurrency(bundle.gpm_labor_adder || 0)}
                  </span>
                )}
              </div>
              <div className="flex justify-between text-gray-400">
                <span>GPM Material</span>
                {editingGpmMaterial ? (
                  <input
                    autoFocus
                    type="text"
                    value={gpmMaterialVal}
                    onChange={(e) => setGpmMaterialVal(e.target.value)}
                    onBlur={saveGpmMaterial}
                    onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') { setGpmMaterialVal(String(bundle.gpm_material_adder || 0)); setEditingGpmMaterial(false) } }}
                    className="bg-white/[0.06] border border-white/[0.12] rounded px-2 py-0.5 text-emerald-400 text-xs tabular-nums focus:outline-none focus:border-emerald-400/50 w-28 text-right"
                  />
                ) : (
                  <span
                    className="tabular-nums text-emerald-400 cursor-pointer hover:text-emerald-300 transition-colors"
                    onClick={() => { setGpmMaterialVal(String(bundle.gpm_material_adder || 0)); setEditingGpmMaterial(true) }}
                    title="Click to edit GPM material"
                  >
                    {formatCurrency(bundle.gpm_material_adder || 0)}
                  </span>
                )}
              </div>
              {bundle.tax_amount > 0 && (
                <div className="flex justify-between text-gray-400">
                  <span>Tax</span><span className="tabular-nums text-gray-300">{formatCurrency(bundle.tax_amount)}</span>
                </div>
              )}
              <div className="flex justify-between text-white font-bold pt-1.5 border-t border-white/[0.06]">
                <span>Bundle Total</span><span className="tabular-nums">{formatCurrency(
                  bundle.freight_override != null
                    ? bundle.total_price + (bundle.freight_override - (bundle.freight_cost || 0))
                    : bundle.total_price
                )}</span>
              </div>
            </div>
          </div>

          {/* Price override */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5 block">Price Override</label>
            <div className="flex items-center gap-2">
              <span className="text-gray-500 text-sm">$</span>
              <input
                type="text"
                value={priceVal}
                onChange={(e) => setPriceVal(e.target.value)}
                onBlur={savePrice}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.target.blur() } }}
                className="bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm tabular-nums focus:outline-none focus:border-si-accent/50 w-48"
              />
              {bundle.price_override != null && bundle.price_override !== bundle.total_price && (
                <button
                  onClick={() => {
                    setPriceVal(String(bundle.total_price || 0))
                    onUpdate(index, { ...bundle, price_override: null })
                  }}
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
                  title="Reset to calculated price"
                >
                  <RotateCcw className="w-3 h-3" /> Reset
                </button>
              )}
            </div>
            {bundle.total_price != null && bundle.price_override != null && bundle.price_override !== bundle.total_price && (
              <p className="text-[10px] text-amber-500/70 mt-1">
                Calculated: {formatCurrency(bundle.total_price)} — overridden to {formatCurrency(bundle.price_override)}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/* ─── Main Component ──────────────────────────────────────────────────── */
export default function ProposalEditor({ job, api: apiProp, onGoBack }) {
  const [bundles, setBundles] = useState([])
  const [notes, setNotes] = useState([])
  const [terms, setTerms] = useState([])
  const [exclusions, setExclusions] = useState([])
  const [subtotal, setSubtotal] = useState(0)
  const [taxRate, setTaxRate] = useState(0)
  const [taxAmount, setTaxAmount] = useState(0)
  const [grandTotal, setGrandTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [pdfReady, setPdfReady] = useState(false)
  const [editingBundle, setEditingBundle] = useState(null)
  const [error, setError] = useState(null)
  const [hasGenerated, setHasGenerated] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIndices, setSelectedIndices] = useState(new Set())
  const [showCombineDialog, setShowCombineDialog] = useState(false)
  const [rewriting, setRewriting] = useState(false)
  const [texturaEnabled, setTexturaEnabled] = useState(!!job?.textura_fee)
  const [texturaAmount, setTexturaAmount] = useState(0)
  const [gpmPct, setGpmPct] = useState(job?.gpm_pct ? (job.gpm_pct * 100) : 0)
  const [gpmLabor, setGpmLabor] = useState(0)
  const [gpmMaterial, setGpmMaterial] = useState(0)
  const [gpmTotal, setGpmTotal] = useState(0)

  // Auto-save state
  const [isDirty, setIsDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [lastSaved, setLastSaved] = useState(null)
  const autoSaveRef = useRef(null)

  // Recalculate totals when bundles, GPM, tax, or textura change
  const recalcTotals = useCallback((currentBundles, rate, textura, gpm) => {
    const gpmDecimal = (gpm || 0) / 100

    // Sum raw base costs across all bundles
    const totalBaseCost = currentBundles.reduce((sum, b) => {
      return sum + (b.material_cost || 0) + (b.sundry_cost || 0) + (b.labor_cost || 0)
        + (b.freight_override ?? b.freight_cost ?? 0)
    }, 0)

    // Calculate GPM profit on total cost
    let profit = 0, profitLabor = 0, profitMaterial = 0
    if (gpmDecimal > 0 && gpmDecimal < 1 && totalBaseCost > 0) {
      const revenue = totalBaseCost / (1 - gpmDecimal)
      profit = Math.round((revenue - totalBaseCost) * 100) / 100
      profitLabor = Math.round(profit * 0.9793 * 100) / 100
      profitMaterial = Math.round((profit - profitLabor) * 100) / 100
    }
    setGpmTotal(profit)
    setGpmLabor(profitLabor)
    setGpmMaterial(profitMaterial)

    // Sell price = base cost + GPM profit
    const sellPrice = totalBaseCost + profit

    // Tax on materials only: material + sundry + freight + GPM material adder
    const taxableBase = currentBundles.reduce((sum, b) => {
      return sum + (b.material_cost || 0) + (b.sundry_cost || 0)
        + (b.freight_override ?? b.freight_cost ?? 0)
    }, 0) + profitMaterial
    const tax = Math.round(taxableBase * rate * 100) / 100

    const preTotalCalc = sellPrice + tax
    setSubtotal(sellPrice)
    setTaxAmount(tax)

    // Textura fee: 0.22% of total, capped at $5,000
    const txtAmt = textura ? Math.min(Math.round(preTotalCalc * 0.0022 * 100) / 100, 5000) : 0
    setTexturaAmount(txtAmt)
    setGrandTotal(preTotalCalc + txtAmt)
  }, [])

  useEffect(() => {
    recalcTotals(bundles, taxRate, texturaEnabled, gpmPct)
  }, [bundles, taxRate, texturaEnabled, gpmPct, recalcTotals])

  // Generate proposal bundles from API
  const generateBundles = useCallback(async () => {
    if (!job?.id) return
    setLoading(true)
    setError(null)
    setPdfReady(false)
    try {
      const res = await fetch(`/api/jobs/${job.id}/proposal/generate`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || 'Failed to generate proposal')
      }
      const data = await res.json()
      setBundles(data.bundles || [])
      setNotes(data.notes || [])
      setTerms(data.terms || [])
      setExclusions(data.exclusions || [])
      setTaxRate(data.tax_rate || job.tax_rate || 0)
      setHasGenerated(true)
      setIsDirty(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [job])

  // Load saved bundles on mount, or auto-generate if none saved
  useEffect(() => {
    if (!job?.id || hasGenerated) return
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const saved = await fetch(`/api/jobs/${job.id}/proposal/bundles`).then(r => r.ok ? r.json() : null)
        if (cancelled) return
        if (saved && saved.bundles && saved.bundles.length > 0) {
          setBundles(saved.bundles)
          setNotes(saved.notes || [])
          setTerms(saved.terms || [])
          setExclusions(saved.exclusions || [])
          setTaxRate(saved.tax_rate ?? job.tax_rate ?? 0)
          if (saved.gpm_pct != null) setGpmPct(saved.gpm_pct * 100)
          if (saved.textura_fee != null) setTexturaEnabled(!!saved.textura_fee)
          setHasGenerated(true)
          setLoading(false)
          return
        }
      } catch (e) {
        console.warn('Could not load saved proposal, generating fresh:', e)
      }
      if (!cancelled) {
        generateBundles()
      }
    })()
    return () => { cancelled = true }
  }, [job?.id])

  // Auto-save debounce (1.5s after any edit)
  useEffect(() => {
    if (!isDirty || !job?.id || bundles.length === 0) return
    if (autoSaveRef.current) clearTimeout(autoSaveRef.current)
    autoSaveRef.current = setTimeout(async () => {
      setSaving(true)
      try {
        await fetch(`/api/jobs/${job.id}/proposal/bundles`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            bundles,
            notes,
            terms,
            exclusions,
            tax_rate: taxRate,
            gpm_pct: gpmPct / 100,
            textura_fee: texturaEnabled ? 1 : 0,
            subtotal,
            tax_amount: taxAmount,
            grand_total: grandTotal,
            gpm_profit: gpmTotal,
            gpm_labor: gpmLabor,
            gpm_material: gpmMaterial,
            textura_amount: texturaAmount,
          }),
        })
        setIsDirty(false)
        setLastSaved(new Date())
      } catch (e) {
        console.error('Auto-save failed:', e)
      } finally {
        setSaving(false)
      }
    }, 1500)
    return () => { if (autoSaveRef.current) clearTimeout(autoSaveRef.current) }
  }, [isDirty, bundles, notes, terms, exclusions, taxRate, gpmPct, texturaEnabled, subtotal, taxAmount, grandTotal, gpmTotal, gpmLabor, gpmMaterial, texturaAmount, job?.id])

  // Ref to hold latest state for flush-on-unmount (avoids stale closures)
  const stateRef = useRef({ bundles: [], notes: [], terms: [], exclusions: [], taxRate: 0, gpmPct: 0, texturaEnabled: false, subtotal: 0, taxAmount: 0, grandTotal: 0, gpmTotal: 0, gpmLabor: 0, gpmMaterial: 0, texturaAmount: 0, isDirty: false })
  useEffect(() => {
    stateRef.current = { bundles, notes, terms, exclusions, taxRate, gpmPct, texturaEnabled, subtotal, taxAmount, grandTotal, gpmTotal, gpmLabor, gpmMaterial, texturaAmount, isDirty }
  })

  // Flush pending save immediately on unmount or beforeunload
  useEffect(() => {
    const flushSave = () => {
      const s = stateRef.current
      if (!s.isDirty || !job?.id || s.bundles.length === 0) return
      // Use sendBeacon for reliability during unload
      const payload = JSON.stringify({
        bundles: s.bundles, notes: s.notes, terms: s.terms, exclusions: s.exclusions,
        tax_rate: s.taxRate, gpm_pct: s.gpmPct / 100, textura_fee: s.texturaEnabled ? 1 : 0,
        subtotal: s.subtotal, tax_amount: s.taxAmount, grand_total: s.grandTotal,
        gpm_profit: s.gpmTotal, gpm_labor: s.gpmLabor, gpm_material: s.gpmMaterial,
        textura_amount: s.texturaAmount,
      })
      navigator.sendBeacon(`/api/jobs/${job.id}/proposal/bundles/save`, new Blob([payload], { type: 'application/json' }))
    }
    window.addEventListener('beforeunload', flushSave)
    return () => {
      window.removeEventListener('beforeunload', flushSave)
      flushSave() // Also flush on component unmount (tab switch)
    }
  }, [job?.id])

  // Helper: set bundles + mark dirty
  const setBundlesAndDirty = useCallback((updater) => {
    setBundles(updater)
    setIsDirty(true)
  }, [])

  // Update a bundle at index
  const updateBundle = useCallback((idx, updated) => {
    setBundlesAndDirty(prev => {
      const next = [...prev]
      next[idx] = updated
      return next
    })
  }, [setBundlesAndDirty])

  // Delete a bundle
  const deleteBundle = useCallback((idx) => {
    setBundlesAndDirty(prev => prev.filter((_, i) => i !== idx))
  }, [setBundlesAndDirty])

  // Move a bundle up/down
  const moveBundle = useCallback((idx, direction) => {
    setBundlesAndDirty(prev => {
      const next = [...prev]
      const targetIdx = idx + direction
      if (targetIdx < 0 || targetIdx >= next.length) return prev
      const temp = next[idx]
      next[idx] = next[targetIdx]
      next[targetIdx] = temp
      return next
    })
  }, [setBundlesAndDirty])

  // Add a new blank bundle
  const addBundle = useCallback(() => {
    const newBundle = {
      bundle_name: `Custom Bundle ${bundles.length + 1}`,
      description_text: '',
      total_price: 0,
      price_override: 0,
      materials: [],
    }
    setBundlesAndDirty(prev => [...prev, newBundle])
  }, [bundles.length, setBundlesAndDirty])

  // Rewrite descriptions using AI agent
  const rewriteDescriptions = useCallback(async () => {
    if (!job?.id || bundles.length === 0) return
    setRewriting(true)
    setError(null)
    try {
      const res = await fetch(`/api/jobs/${job.id}/proposal/rewrite-descriptions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bundles }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || 'Failed to rewrite descriptions')
      }
      const data = await res.json()
      const descriptions = data.descriptions || []
      if (descriptions.length > 0) {
        setBundlesAndDirty(prev => {
          const next = [...prev]
          for (const d of descriptions) {
            const idx = d.index
            if (idx >= 0 && idx < next.length && d.description) {
              next[idx] = { ...next[idx], description_text: d.description }
            }
          }
          return next
        })
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setRewriting(false)
    }
  }, [job, bundles])

  // Toggle selection for combine mode
  const toggleSelect = useCallback((idx) => {
    setSelectedIndices(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }, [])

  // Combine selected bundles
  const combineBundles = useCallback((indices, newName, addPatternAddon) => {
    const sorted = [...indices].sort((a, b) => a - b)
    const selected = sorted.map(i => bundles[i])

    const combined = {
      bundle_name: newName,
      description_text: selected.map(b => b.description_text).filter(Boolean).join('\n\n'),
      materials: selected.flatMap(b => b.materials || []),
      sundry_items: selected.flatMap(b => b.sundry_items || []),
      labor_items: [...selected.flatMap(b => b.labor_items || [])],
      material_cost: round2(sumField(selected, 'material_cost')),
      sundry_cost: round2(sumField(selected, 'sundry_cost')),
      labor_cost: round2(sumField(selected, 'labor_cost')),
      freight_cost: round2(sumField(selected, 'freight_cost')),
      gpm_labor_adder: round2(sumField(selected, 'gpm_labor_adder')),
      gpm_material_adder: round2(sumField(selected, 'gpm_material_adder')),
      gpm_adder: round2(sumField(selected, 'gpm_adder')),
      tax_amount: round2(sumField(selected, 'tax_amount')),
      taxable: round2(sumField(selected, 'taxable')),
      installed_qty: round2(sumField(selected, 'installed_qty')),
      unit: selected[0]?.unit || 'SY',
      editable: true,
    }

    // Add pattern addon labor line if requested
    if (addPatternAddon && combined.installed_qty > 0) {
      const patternCost = round2(combined.installed_qty * 0.27)
      combined.labor_items.push({
        labor_description: 'Project Carpet - X ADD for Carpet Tile Pattern',
        qty: round2(combined.installed_qty),
        unit: 'SY',
        rate: 0.27,
        extended_cost: patternCost,
      })
      combined.labor_cost = round2(combined.labor_cost + patternCost)
    }

    // Recalculate total_price
    combined.total_price = round2(
      combined.material_cost + combined.sundry_cost +
      combined.labor_cost + combined.freight_cost +
      combined.gpm_adder + combined.tax_amount
    )

    // Remove selected bundles and insert combined at first selected position
    const remaining = bundles.filter((_, i) => !indices.has(i))
    remaining.splice(sorted[0], 0, combined)
    setBundlesAndDirty(() => remaining)

    // Reset combine state
    setSelectMode(false)
    setSelectedIndices(new Set())
    setShowCombineDialog(false)
  }, [bundles])

  // Generate PDF
  const generatePdf = useCallback(async () => {
    if (!job?.id) return
    setGenerating(true)
    setError(null)
    try {
      const proposalData = {
        bundles: bundles.map((b, i) => ({
          ...b,
          sort_order: i,
          final_price: b.price_override ?? b.total_price ?? 0,
        })),
        notes,
        terms,
        exclusions,
        subtotal,
        tax_rate: taxRate,
        tax_amount: taxAmount,
        gpm_pct: gpmPct / 100,
        gpm_profit: gpmTotal,
        gpm_labor: gpmLabor,
        gpm_material: gpmMaterial,
        textura_fee: texturaEnabled ? 1 : 0,
        textura_amount: texturaAmount,
        grand_total: grandTotal,
      }
      const res = await fetch(`/api/jobs/${job.id}/proposal/pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(proposalData),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || 'Failed to generate PDF')
      }
      setPdfReady(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }, [job, bundles, notes, terms, exclusions, subtotal, taxRate, taxAmount, gpmPct, gpmTotal, gpmLabor, gpmMaterial, texturaEnabled, texturaAmount, grandTotal])

  // Download PDF
  const downloadPdf = useCallback(() => {
    if (!job?.id) return
    window.open(`/api/jobs/${job.id}/proposal.pdf`, '_blank')
  }, [job])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-si-accent" />
            Proposal Editor
          </h2>
          <p className="text-sm text-gray-500 mt-0.5 flex items-center gap-2">
            Edit bundles, pricing, and generate the proposal PDF
            {saving && <span className="text-xs text-si-accent/70 flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> Saving...</span>}
            {!saving && lastSaved && <span className="text-xs text-emerald-500/60">✓ Saved</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!selectMode ? (
            <>
              <button
                onClick={generateBundles}
                disabled={loading}
                className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] text-gray-300 font-medium rounded-xl px-4 py-2 text-sm transition-colors disabled:opacity-50"
              >
                <RotateCcw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                Regenerate
              </button>
              <button
                onClick={rewriteDescriptions}
                disabled={rewriting || bundles.length === 0}
                className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] text-gray-300 font-medium rounded-xl px-4 py-2 text-sm transition-colors disabled:opacity-50"
              >
                <Sparkles className={`w-4 h-4 ${rewriting ? 'animate-pulse text-si-accent' : ''}`} />
                {rewriting ? 'Rewriting...' : 'Rewrite'}
              </button>
              <button
                onClick={() => { setSelectMode(true); setSelectedIndices(new Set()) }}
                disabled={bundles.length < 2}
                className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] text-gray-300 font-medium rounded-xl px-4 py-2 text-sm transition-colors disabled:opacity-50"
              >
                <Combine className="w-4 h-4" />
                Combine
              </button>
              <button
                onClick={addBundle}
                className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] text-gray-300 font-medium rounded-xl px-4 py-2 text-sm transition-colors"
              >
                <Plus className="w-4 h-4" />
                Add Bundle
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => { setSelectMode(false); setSelectedIndices(new Set()) }}
                className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] text-gray-400 font-medium rounded-xl px-4 py-2 text-sm transition-colors"
              >
                <X className="w-4 h-4" />
                Cancel
              </button>
              <button
                onClick={() => setShowCombineDialog(true)}
                disabled={selectedIndices.size < 2}
                className="flex items-center gap-2 bg-si-accent hover:bg-si-accent/90 text-white font-medium rounded-xl px-4 py-2 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Combine className="w-4 h-4" />
                Combine ({selectedIndices.size} selected)
              </button>
            </>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3 text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-red-400/60 hover:text-red-300">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="glass-card p-12 flex flex-col items-center justify-center gap-3">
          <Loader2 className="w-8 h-8 text-si-accent animate-spin" />
          <p className="text-sm text-gray-400">Generating proposal bundles...</p>
        </div>
      )}

      {/* Bundle list */}
      {!loading && bundles.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider">
              Bundles ({bundles.length})
            </h3>
          </div>
          {bundles.map((bundle, i) => (
            <BundleCard
              key={`${bundle.bundle_name}-${i}`}
              bundle={bundle}
              index={i}
              total={bundles.length}
              onUpdate={updateBundle}
              onDelete={deleteBundle}
              onMove={moveBundle}
              selectMode={selectMode}
              selected={selectedIndices.has(i)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && bundles.length === 0 && hasGenerated && (
        <div className="glass-card p-12 flex flex-col items-center justify-center gap-3 text-center">
          <Package className="w-10 h-10 text-gray-600" />
          <p className="text-sm text-gray-400">No bundles generated.</p>
          <p className="text-xs text-gray-600">Try regenerating or add a custom bundle.</p>
        </div>
      )}

      {/* Notes, Terms, Exclusions */}
      {!loading && hasGenerated && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <EditableList title="Notes" items={notes} onChange={v => { setNotes(v); setIsDirty(true) }} />
          <EditableList title="Terms & Conditions" items={terms} onChange={v => { setTerms(v); setIsDirty(true) }} />
          <EditableList title="Exclusions" items={exclusions} onChange={v => { setExclusions(v); setIsDirty(true) }} />
        </div>
      )}

      {/* Totals & Actions */}
      {!loading && bundles.length > 0 && (() => {
        const totalMaterial = bundles.reduce((s, b) => s + (b.material_cost || 0), 0)
        const totalSundry = bundles.reduce((s, b) => s + (b.sundry_cost || 0), 0)
        const totalLabor = bundles.reduce((s, b) => s + (b.labor_cost || 0), 0)
        const totalFreight = bundles.reduce((s, b) => s + (b.freight_override ?? b.freight_cost ?? 0), 0)
        const totalCost = totalMaterial + totalSundry + totalLabor + totalFreight
        const totalGpmLabor = bundles.reduce((s, b) => s + (b.gpm_labor_adder || 0), 0)
        const totalGpmMaterial = bundles.reduce((s, b) => s + (b.gpm_material_adder || 0), 0)
        const totalGpm = totalGpmLabor + totalGpmMaterial
        return (
        <div className="glass-card p-4 sm:p-6">
          {/* Cost Breakdown */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-6">
            {/* Left: Cost breakdown */}
            <div>
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-3">Cost Breakdown</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Materials</span>
                  <span className="text-gray-300 tabular-nums">{formatCurrency(totalMaterial)}</span>
                </div>
                {totalSundry > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-400">Sundries</span>
                    <span className="text-gray-300 tabular-nums">{formatCurrency(totalSundry)}</span>
                  </div>
                )}
                {totalLabor > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-400">Labor</span>
                    <span className="text-gray-300 tabular-nums">{formatCurrency(totalLabor)}</span>
                  </div>
                )}
                {totalFreight > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-400">Freight</span>
                    <span className="text-gray-300 tabular-nums">{formatCurrency(totalFreight)}</span>
                  </div>
                )}
                <div className="flex justify-between border-t border-white/[0.06] pt-2">
                  <span className="text-white font-semibold">Total Cost</span>
                  <span className="text-white font-semibold tabular-nums">{formatCurrency(totalCost)}</span>
                </div>
                <div className="border-t border-white/[0.06] pt-2 mt-1">
                  <div className="flex justify-between">
                    <div className="flex items-center gap-2 text-emerald-400 font-semibold">
                      <span>GPM Profit</span>
                      <input
                        type="text"
                        value={gpmPct ? Number(gpmPct).toFixed(2) : '0.00'}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value)
                          setGpmPct(isNaN(val) ? 0 : val)
                          setIsDirty(true)
                        }}
                        className="bg-white/[0.04] border border-white/[0.08] rounded-lg px-2 py-1 text-emerald-400 text-xs tabular-nums w-20 text-center focus:outline-none focus:border-emerald-400/50"
                      />
                      <span className="text-emerald-600 text-xs">%</span>
                    </div>
                    <span className="text-emerald-400 font-semibold tabular-nums">{formatCurrency(gpmTotal)}</span>
                  </div>
                  {gpmTotal > 0 && (
                    <>
                      <div className="flex justify-between text-xs pl-3 mt-2">
                        <span className="text-gray-500">Labor (97.93%)</span>
                        <span className="text-gray-400 tabular-nums">{formatCurrency(gpmLabor)}</span>
                      </div>
                      <div className="flex justify-between text-xs pl-3">
                        <span className="text-gray-500">Material (2.07%)</span>
                        <span className="text-gray-400 tabular-nums">{formatCurrency(gpmMaterial)}</span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Right: Sell price totals */}
            <div>
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-3">Proposal Totals</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Subtotal (Sell Price)</span>
                  <span className="text-white font-semibold tabular-nums">{formatCurrency(subtotal)}</span>
                </div>
                <div className="flex justify-between">
                  <div className="flex items-center gap-2 text-gray-400">
                    <span>Tax (materials only)</span>
                    <input
                      type="text"
                      value={taxRate ? (taxRate * 100).toFixed(2) : '0.00'}
                      onChange={(e) => {
                        const val = parseFloat(e.target.value)
                        setTaxRate(isNaN(val) ? 0 : val / 100)
                      }}
                      className="bg-white/[0.04] border border-white/[0.08] rounded-lg px-2 py-1 text-white text-xs tabular-nums w-20 text-center focus:outline-none focus:border-si-accent/50"
                    />
                    <span className="text-gray-600 text-xs">%</span>
                  </div>
                  <span className="text-white font-semibold tabular-nums">{formatCurrency(taxAmount)}</span>
                </div>
                {/* Textura fee toggle + display */}
                <div className="flex justify-between">
                  <div className="flex items-center gap-2 text-gray-400">
                    <input
                      type="checkbox"
                      checked={texturaEnabled}
                      onChange={(e) => { setTexturaEnabled(e.target.checked); setIsDirty(true) }}
                      className="w-3.5 h-3.5 rounded border-white/10 bg-white/[0.04] text-si-accent focus:ring-si-accent/50"
                    />
                    <span>Textura (0.22%)</span>
                  </div>
                  <span className="text-white font-semibold tabular-nums">{texturaEnabled ? formatCurrency(texturaAmount) : '—'}</span>
                </div>
                <div className="border-t border-white/[0.06] pt-2 flex justify-between">
                  <span className="text-white font-bold text-base">Grand Total</span>
                  <span className="text-white font-bold text-lg tabular-nums">{formatCurrency(grandTotal)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={onGoBack}
              className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] text-gray-300 font-medium rounded-xl px-4 py-2.5 text-sm transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Materials
            </button>

            <div className="flex-1" />

            <button
              onClick={generatePdf}
              disabled={generating || bundles.length === 0}
              className="flex items-center gap-2 bg-si-accent hover:bg-si-accent/90 text-white font-medium rounded-xl px-5 py-2.5 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {generating ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Generating PDF...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  Generate PDF
                </>
              )}
            </button>

            {pdfReady && (
              <button
                onClick={downloadPdf}
                className="flex items-center gap-2 bg-emerald-500/15 border border-emerald-500/25 hover:bg-emerald-500/25 text-emerald-400 font-bold rounded-xl px-5 py-2.5 text-sm transition-colors"
              >
                <FileDown className="w-4 h-4" />
                Download PDF
              </button>
            )}
          </div>
        </div>
        )})()}

      {/* Combine Bundles Dialog — portaled to document.body to escape CSS transform containing block */}
      {showCombineDialog && createPortal(
        <CombineBundlesDialog
          bundles={bundles}
          selectedIndices={selectedIndices}
          onCombine={combineBundles}
          onCancel={() => setShowCombineDialog(false)}
        />,
        document.body
      )}
    </div>
  )
}
