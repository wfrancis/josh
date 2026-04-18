import { useState, useEffect, useRef } from 'react'
import { Loader2, Check, Plus, Trash2, Save, AlertTriangle } from 'lucide-react'
import { api } from '../api'

const DEFAULT_SUNDRY_PRICES = {
  'Pad (6lb 3/8")': { unit: 'SY/roll', price: 1.38, coverage: 30, notes: '30 SY/roll' },
  'Pad Cement': { unit: 'SY/each', price: 28.00, coverage: 100, notes: '' },
  'Tack Strip': { unit: 'LF/carton', price: 36.99, coverage: 400, notes: '400 LF/carton' },
  'Seam Tape': { unit: 'LF/roll', price: 9.09, coverage: 60, notes: '60 LF/roll' },
  'Adhesive (Taylor Dynamics 4-gal)': { unit: 'SF/pail', price: 73.00, coverage: 700, notes: '' },
  'Primer (Taylor 2025)': { unit: 'SF/bucket', price: 17.00, coverage: 350, notes: '' },
  'Thinset (Grey)': { unit: 'SF/bag', price: 15.95, coverage: 40, notes: 'Standard thinset' },
  'Thinset (White)': { unit: 'SF/bag', price: 17.95, coverage: 40, notes: 'For backsplash/mosaic' },
  'LFT Thinset': { unit: 'SF/bag', price: 16.95, coverage: 30, notes: 'Large format tile 16x30+' },
  'Grout (Prism)': { unit: 'SF/bag', price: 32.00, coverage: 100, notes: '' },
  'Caulking': { unit: 'EA/tube', price: 13.85, coverage: 2, notes: '2 units per tube' },
  'Schluter Jolly AE': { unit: 'EA/stick', price: 9.78, coverage: 0.5, notes: '8\' 2-1/2" stick' },
}

export default function SundryRatesTab() {
  const [prices, setPrices] = useState(null)
  const [editedPrices, setEditedPrices] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [error, setError] = useState(null)
  const [showNewRow, setShowNewRow] = useState(false)
  const [newProduct, setNewProduct] = useState({ name: '', unit: '', price: '', coverage: '', notes: '' })
  const newNameRef = useRef(null)

  const dirty = prices !== null && JSON.stringify(prices) !== JSON.stringify(editedPrices)

  useEffect(() => {
    loadPrices()
  }, [])

  useEffect(() => {
    if (saveSuccess) {
      const t = setTimeout(() => setSaveSuccess(false), 3000)
      return () => clearTimeout(t)
    }
  }, [saveSuccess])

  async function loadPrices() {
    setLoading(true)
    setError(null)
    try {
      const res = await api.getCompanyRate('sundry_prices')
      const data = res.data && Object.keys(res.data).length > 0 ? res.data : null
      if (data) {
        setPrices(data)
        setEditedPrices(JSON.parse(JSON.stringify(data)))
      } else {
        // Seed defaults
        await api.updateCompanyRate('sundry_prices', DEFAULT_SUNDRY_PRICES)
        setPrices(JSON.parse(JSON.stringify(DEFAULT_SUNDRY_PRICES)))
        setEditedPrices(JSON.parse(JSON.stringify(DEFAULT_SUNDRY_PRICES)))
      }
    } catch (e) {
      // If 404 or no data, seed defaults
      try {
        await api.updateCompanyRate('sundry_prices', DEFAULT_SUNDRY_PRICES)
        setPrices(JSON.parse(JSON.stringify(DEFAULT_SUNDRY_PRICES)))
        setEditedPrices(JSON.parse(JSON.stringify(DEFAULT_SUNDRY_PRICES)))
      } catch (e2) {
        setError('Failed to load sundry prices: ' + e2.message)
      }
    } finally {
      setLoading(false)
    }
  }

  function updateField(productName, field, value) {
    setEditedPrices(prev => ({
      ...prev,
      [productName]: {
        ...prev[productName],
        [field]: field === 'price' || field === 'coverage' ? (value === '' ? '' : Number(value)) : value,
      },
    }))
  }

  function deleteProduct(productName) {
    setEditedPrices(prev => {
      const next = { ...prev }
      delete next[productName]
      return next
    })
  }

  function addNewRow() {
    if (!newProduct.name.trim()) return
    setEditedPrices(prev => ({
      ...prev,
      [newProduct.name.trim()]: {
        unit: newProduct.unit,
        price: newProduct.price === '' ? 0 : Number(newProduct.price),
        coverage: newProduct.coverage === '' ? 0 : Number(newProduct.coverage),
        notes: newProduct.notes,
      },
    }))
    setNewProduct({ name: '', unit: '', price: '', coverage: '', notes: '' })
    setShowNewRow(false)
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await api.updateCompanyRate('sundry_prices', editedPrices)
      setPrices(JSON.parse(JSON.stringify(editedPrices)))
      setSaveSuccess(true)
    } catch (e) {
      setError('Failed to save: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  const sortedEntries = Object.entries(editedPrices).sort(([a], [b]) => a.localeCompare(b))

  if (loading) {
    return (
      <div className="glass-card p-6 flex items-center justify-center py-20">
        <Loader2 className="w-5 h-5 animate-spin text-blue-400 mr-2" />
        <span className="text-sm text-gray-400">Loading sundry prices...</span>
      </div>
    )
  }

  return (
    <div className="glass-card p-6">
      {/* Header */}
      <div className="mb-5">
        <h3 className="text-sm font-semibold text-white">Sundry Product Prices</h3>
        <p className="text-[11px] text-gray-500 mt-0.5">
          Master price list for all sundry items. Changes here update prices across all material types.
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-xl border border-white/[0.06] overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-900/95 backdrop-blur-sm sticky top-0 z-10">
            <tr>
              <th className="text-left px-4 py-2.5 text-[10px] font-bold text-gray-500 uppercase tracking-[0.12em]">Product</th>
              <th className="text-left px-4 py-2.5 text-[10px] font-bold text-gray-500 uppercase tracking-[0.12em]">Unit</th>
              <th className="text-left px-4 py-2.5 text-[10px] font-bold text-gray-500 uppercase tracking-[0.12em]">Coverage</th>
              <th className="text-right px-4 py-2.5 text-[10px] font-bold text-gray-500 uppercase tracking-[0.12em]">Price</th>
              <th className="text-left px-4 py-2.5 text-[10px] font-bold text-gray-500 uppercase tracking-[0.12em]">Notes</th>
              <th className="w-10 px-2 py-2.5"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.03]">
            {sortedEntries.map(([name, item]) => (
              <tr key={name} className="group hover:bg-white/[0.02] transition-colors">
                <td className="px-4 py-2">
                  <span className="text-xs text-gray-200">{name}</span>
                </td>
                <td className="px-4 py-2">
                  <input
                    type="text"
                    value={item.unit}
                    onChange={e => updateField(name, 'unit', e.target.value)}
                    className="bg-transparent border-0 outline-none text-xs text-gray-300 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-full"
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    type="number"
                    value={item.coverage}
                    onChange={e => updateField(name, 'coverage', e.target.value)}
                    className="bg-transparent border-0 outline-none text-xs text-gray-300 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-24"
                  />
                </td>
                <td className="px-4 py-2">
                  <div className="flex items-center justify-end">
                    <span className="text-xs text-gray-600 mr-0.5">$</span>
                    <input
                      type="number"
                      step="0.01"
                      value={item.price}
                      onChange={e => updateField(name, 'price', e.target.value)}
                      className="bg-transparent border-0 outline-none text-xs text-gray-300 text-right tabular-nums cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-20"
                    />
                  </div>
                </td>
                <td className="px-4 py-2">
                  <input
                    type="text"
                    value={item.notes}
                    onChange={e => updateField(name, 'notes', e.target.value)}
                    className="bg-transparent border-0 outline-none text-xs text-gray-400 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-full"
                    placeholder="—"
                  />
                </td>
                <td className="px-2 py-2">
                  <button
                    onClick={() => deleteProduct(name)}
                    className="opacity-0 group-hover:opacity-100 p-1 text-gray-600 hover:text-red-400 transition-all rounded"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}

            {/* New row */}
            {showNewRow && (
              <tr className="bg-white/[0.02]">
                <td className="px-4 py-2">
                  <input
                    ref={newNameRef}
                    type="text"
                    value={newProduct.name}
                    onChange={e => setNewProduct(p => ({ ...p, name: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && addNewRow()}
                    onBlur={() => { if (newProduct.name.trim()) addNewRow() }}
                    placeholder="Product name"
                    className="bg-transparent border-0 outline-none text-xs text-gray-200 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-full placeholder:text-gray-600"
                    autoFocus
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    type="text"
                    value={newProduct.unit}
                    onChange={e => setNewProduct(p => ({ ...p, unit: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && addNewRow()}
                    placeholder="Unit"
                    className="bg-transparent border-0 outline-none text-xs text-gray-300 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-full placeholder:text-gray-600"
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    type="number"
                    value={newProduct.coverage}
                    onChange={e => setNewProduct(p => ({ ...p, coverage: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && addNewRow()}
                    placeholder="0"
                    className="bg-transparent border-0 outline-none text-xs text-gray-300 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-24 placeholder:text-gray-600"
                  />
                </td>
                <td className="px-4 py-2">
                  <div className="flex items-center justify-end">
                    <span className="text-xs text-gray-600 mr-0.5">$</span>
                    <input
                      type="number"
                      step="0.01"
                      value={newProduct.price}
                      onChange={e => setNewProduct(p => ({ ...p, price: e.target.value }))}
                      onKeyDown={e => e.key === 'Enter' && addNewRow()}
                      placeholder="0.00"
                      className="bg-transparent border-0 outline-none text-xs text-gray-300 text-right tabular-nums cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-20 placeholder:text-gray-600"
                    />
                  </div>
                </td>
                <td className="px-4 py-2">
                  <input
                    type="text"
                    value={newProduct.notes}
                    onChange={e => setNewProduct(p => ({ ...p, notes: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && addNewRow()}
                    placeholder="Notes"
                    className="bg-transparent border-0 outline-none text-xs text-gray-400 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors w-full placeholder:text-gray-600"
                  />
                </td>
                <td className="px-2 py-2">
                  <button
                    onClick={() => { setShowNewRow(false); setNewProduct({ name: '', unit: '', price: '', coverage: '', notes: '' }) }}
                    className="p-1 text-gray-600 hover:text-gray-400 transition-colors rounded"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Bottom bar */}
      <div className="flex items-center justify-between mt-4">
        <button
          onClick={() => { setShowNewRow(true); setTimeout(() => newNameRef.current?.focus(), 50) }}
          disabled={showNewRow}
          className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Product
        </button>

        <div className="flex items-center gap-3">
          {saveSuccess && (
            <span className="flex items-center gap-1 text-xs text-emerald-400">
              <Check className="w-3.5 h-3.5" />
              Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save Changes
          </button>
        </div>
      </div>
    </div>
  )
}
