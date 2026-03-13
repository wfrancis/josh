import { useState } from 'react'
import { Package } from 'lucide-react'

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
  wood: 'Wood', tread_riser: 'Tread/Riser', pad: 'Pad',
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
}

export default function MaterialsTable({ materials, onUpdate, readOnly = false }) {
  const [editingId, setEditingId] = useState(null)

  const handlePriceChange = (idx, value) => {
    const updated = materials.map((m, i) => {
      if (i !== idx) return m
      const unitPrice = parseFloat(value) || 0
      const orderQty = m.installed_qty * (1 + (m.waste_pct || 0))
      return { ...m, unit_price: unitPrice, order_qty: orderQty, extended_cost: orderQty * unitPrice }
    })
    onUpdate?.(updated)
  }

  if (!materials?.length) {
    return (
      <div className="text-center py-12 text-gray-600">
        <Package className="w-10 h-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">No materials yet. Upload an RFMS file to get started.</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/[0.06]">
            {['Material','Type','Install Qty','Waste','Order Qty',
              ...(!readOnly ? ['Unit Price'] : []), 'Extended'].map(h => (
              <th key={h} className={`py-3 px-3 font-bold text-gray-500 text-[10px] uppercase tracking-[0.12em]
                ${h === 'Material' || h === 'Type' ? 'text-left' : 'text-right'}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.03]">
          {materials.map((m, idx) => {
            const typeColor = TYPE_COLORS[m.material_type] || 'bg-gray-500/10 text-gray-400 border-gray-500/10'
            const hasPrice = m.unit_price > 0
            return (
              <tr key={m.id || idx} className="hover:bg-white/[0.02] transition-colors">
                <td className="py-3 px-3">
                  <div className="font-medium text-gray-200">{m.description || m.item_code || '—'}</div>
                  {m.item_code && m.description && (
                    <div className="text-[11px] text-gray-600 mt-0.5">{m.item_code}</div>
                  )}
                </td>
                <td className="py-3 px-3">
                  <span className={`badge border ${typeColor}`}>
                    {TYPE_LABELS[m.material_type] || m.material_type}
                  </span>
                </td>
                <td className="py-3 px-3 text-right tabular-nums text-gray-300">
                  {formatNumber(m.installed_qty)} <span className="text-gray-600 text-xs">{m.unit}</span>
                </td>
                <td className="py-3 px-3 text-right tabular-nums text-gray-500">
                  {((m.waste_pct || 0) * 100).toFixed(0)}%
                </td>
                <td className="py-3 px-3 text-right tabular-nums text-gray-300">
                  {formatNumber(m.order_qty)}
                </td>
                {!readOnly && (
                  <td className="py-3 px-3 text-right">
                    <input
                      type="number" step="0.01" min="0"
                      value={m.unit_price || ''}
                      onChange={(e) => handlePriceChange(idx, e.target.value)}
                      onFocus={() => setEditingId(idx)} onBlur={() => setEditingId(null)}
                      placeholder="0.00"
                      className={`editable-cell w-24 ${!hasPrice && editingId !== idx ? 'text-gray-600' : 'text-gray-100'}`}
                    />
                  </td>
                )}
                <td className="py-3 px-3 text-right tabular-nums font-medium">
                  {hasPrice ? (
                    <span className="text-white">{formatCurrency(m.extended_cost)}</span>
                  ) : (
                    <span className="text-gray-600">—</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-white/[0.08]">
            <td colSpan={readOnly ? 5 : 6} className="py-3 px-3 text-right font-semibold text-gray-500 text-xs uppercase tracking-wider">
              Material Total
            </td>
            <td className="py-3 px-3 text-right tabular-nums font-bold text-white">
              {formatCurrency(materials.reduce((sum, m) => sum + (m.extended_cost || 0), 0))}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
