import { useState, useEffect } from 'react'
import {
  DollarSign, HardHat, FileSpreadsheet, ShoppingCart, Droplets,
  Wrench, Truck, Loader2, Check, AlertTriangle, Plus, Trash2,
  ChevronDown, ChevronRight, Info, X
} from 'lucide-react'
import { api } from '../api'
import FileUpload from './FileUpload'

const TYPE_LABELS = {
  unit_carpet_no_pattern: 'Carpet (No Pattern)',
  unit_carpet_pattern: 'Carpet (Pattern)',
  unit_lvt: 'LVT',
  cpt_tile: 'Carpet Tile',
  corridor_broadloom: 'Broadloom',
  floor_tile: 'Floor Tile',
  wall_tile: 'Wall Tile',
  backsplash: 'Backsplash',
  tub_shower_surround: 'Tub/Shower',
  rubber_base: 'Rubber Base',
  vct: 'VCT',
  rubber_tile: 'Rubber Tile',
  rubber_sheet: 'Rubber Sheet',
  wood: 'Wood',
  tread_riser: 'Tread/Riser',
  pad: 'Pad',
}

const MATERIAL_TYPES = Object.keys(TYPE_LABELS)

export default function InternalRatesPage() {
  // Labor Catalog
  const [laborLoading, setLaborLoading] = useState(false)
  const [laborSuccess, setLaborSuccess] = useState(false)
  const [laborError, setLaborError] = useState(null)
  const [laborCatalog, setLaborCatalog] = useState(null)
  const [catalogLoading, setCatalogLoading] = useState(true)

  // Price List
  const [priceListLoading, setPriceListLoading] = useState(false)
  const [priceListSuccess, setPriceListSuccess] = useState(false)
  const [priceListError, setPriceListError] = useState(null)
  const [priceList, setPriceList] = useState(null)
  const [priceListFetching, setPriceListFetching] = useState(true)
  const [showAddRow, setShowAddRow] = useState(false)
  const [newEntry, setNewEntry] = useState({ product_name: '', material_type: '', unit: '', unit_price: '', vendor: '' })
  const [addingEntry, setAddingEntry] = useState(false)
  const [deletingId, setDeletingId] = useState(null)

  // Waste Factors
  const [wasteFactors, setWasteFactors] = useState(null)
  const [wasteLoading, setWasteLoading] = useState(true)
  const [wasteSaving, setWasteSaving] = useState(false)
  const [wasteSaveSuccess, setWasteSaveSuccess] = useState(false)
  const [wasteError, setWasteError] = useState(null)
  const [editedWaste, setEditedWaste] = useState({})

  // Sundry Rules
  const [sundryRules, setSundryRules] = useState(null)
  const [sundryLoading, setSundryLoading] = useState(true)
  const [expandedSundry, setExpandedSundry] = useState({})

  // Freight Rates
  const [freightRates, setFreightRates] = useState(null)
  const [freightLoading, setFreightLoading] = useState(true)
  const [freightSaving, setFreightSaving] = useState(false)
  const [freightSaveSuccess, setFreightSaveSuccess] = useState(false)
  const [freightError, setFreightError] = useState(null)
  const [editedFreight, setEditedFreight] = useState({})

  // Load all data on mount
  useEffect(() => {
    api.getLaborCatalog()
      .then(data => setLaborCatalog(data))
      .catch(() => setLaborCatalog({ entries: [], count: 0 }))
      .finally(() => setCatalogLoading(false))

    api.getPriceList()
      .then(data => setPriceList(data))
      .catch(() => setPriceList({ entries: [], count: 0 }))
      .finally(() => setPriceListFetching(false))

    api.getCompanyRate('waste_factors')
      .then(res => { setWasteFactors(res.data); setEditedWaste(res.data || {}) })
      .catch(() => { setWasteFactors({}); setEditedWaste({}) })
      .finally(() => setWasteLoading(false))

    api.getCompanyRate('sundry_rules')
      .then(res => setSundryRules(res.data || {}))
      .catch(() => setSundryRules({}))
      .finally(() => setSundryLoading(false))

    api.getCompanyRate('freight_rates')
      .then(res => { setFreightRates(res.data); setEditedFreight(res.data || {}) })
      .catch(() => { setFreightRates({}); setEditedFreight({}) })
      .finally(() => setFreightLoading(false))
  }, [])

  // Handlers — Labor
  const handleLaborUpload = async (file) => {
    setLaborLoading(true)
    setLaborError(null)
    try {
      await api.uploadLaborCatalog(file)
      setLaborSuccess(true)
      const data = await api.getLaborCatalog()
      setLaborCatalog(data)
    } catch (err) {
      setLaborError(err.message)
    } finally {
      setLaborLoading(false)
    }
  }

  // Handlers — Price List
  const handlePriceListUpload = async (file) => {
    setPriceListLoading(true)
    setPriceListError(null)
    try {
      await api.uploadPriceList(file)
      setPriceListSuccess(true)
      const data = await api.getPriceList()
      setPriceList(data)
    } catch (err) {
      setPriceListError(err.message)
    } finally {
      setPriceListLoading(false)
    }
  }

  const handleAddEntry = async () => {
    if (!newEntry.product_name || !newEntry.unit_price) return
    setAddingEntry(true)
    try {
      await api.addPriceListEntry({
        ...newEntry,
        unit_price: parseFloat(newEntry.unit_price),
      })
      const data = await api.getPriceList()
      setPriceList(data)
      setNewEntry({ product_name: '', material_type: '', unit: '', unit_price: '', vendor: '' })
      setShowAddRow(false)
    } catch (err) {
      setPriceListError(err.message)
    } finally {
      setAddingEntry(false)
    }
  }

  const handleDeleteEntry = async (id) => {
    setDeletingId(id)
    try {
      await api.deletePriceListEntry(id)
      const data = await api.getPriceList()
      setPriceList(data)
    } catch (err) {
      setPriceListError(err.message)
    } finally {
      setDeletingId(null)
    }
  }

  // Handlers — Waste Factors
  const handleWasteSave = async () => {
    setWasteSaving(true)
    setWasteError(null)
    setWasteSaveSuccess(false)
    try {
      await api.updateCompanyRate('waste_factors', editedWaste)
      setWasteFactors(editedWaste)
      setWasteSaveSuccess(true)
      setTimeout(() => setWasteSaveSuccess(false), 3000)
    } catch (err) {
      setWasteError(err.message)
    } finally {
      setWasteSaving(false)
    }
  }

  // Handlers — Freight Rates
  const handleFreightSave = async () => {
    setFreightSaving(true)
    setFreightError(null)
    setFreightSaveSuccess(false)
    try {
      await api.updateCompanyRate('freight_rates', editedFreight)
      setFreightRates(editedFreight)
      setFreightSaveSuccess(true)
      setTimeout(() => setFreightSaveSuccess(false), 3000)
    } catch (err) {
      setFreightError(err.message)
    } finally {
      setFreightSaving(false)
    }
  }

  const toggleSundrySection = (key) => {
    setExpandedSundry(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const wasteHasChanges = JSON.stringify(wasteFactors) !== JSON.stringify(editedWaste)
  const freightHasChanges = JSON.stringify(freightRates) !== JSON.stringify(editedFreight)

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-extrabold text-white tracking-tight flex items-center gap-3">
          <DollarSign className="w-6 h-6 text-gray-400" />
          Internal Rates
        </h1>
        <p className="text-sm text-gray-500 mt-1">Manage labor, materials, waste, sundries, and freight</p>
      </div>

      <div className="space-y-6">

        {/* ── 1. Labor Catalog ─────────────────────────────── */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-violet-500/10 flex items-center justify-center flex-shrink-0">
              <HardHat className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Labor Catalog</h2>
              <p className="text-sm text-gray-500 mt-1">
                Upload your labor rate catalog (PDF or Excel). This sets the per-unit labor rates used when generating bids.
              </p>
            </div>
          </div>
          <FileUpload
            accept=".pdf,.xlsx,.xls"
            label="Upload Labor Catalog"
            description="PDF or Excel file with labor rates per material type"
            icon={FileSpreadsheet}
            onUpload={handleLaborUpload}
            onReset={() => setLaborSuccess(false)}
            loading={laborLoading}
            success={laborSuccess}
            successMessage="Labor catalog uploaded successfully"
          />
          {laborError && (
            <div className="mt-3 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
              {laborError}
            </div>
          )}

          {catalogLoading ? (
            <div className="mt-4 flex items-center justify-center py-6">
              <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
            </div>
          ) : laborCatalog && laborCatalog.count > 0 ? (
            <div className="mt-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-bold text-gray-500 uppercase tracking-[0.12em]">
                  Loaded Rates
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400">
                  {laborCatalog.count} entries
                </span>
              </div>
              <div className="overflow-x-auto max-h-64 overflow-y-auto rounded-xl border border-white/[0.06]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900/95 backdrop-blur-sm">
                    <tr className="border-b border-white/[0.06]">
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Type</th>
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Description</th>
                      <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider">Cost</th>
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Unit</th>
                      <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider">Markup</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.03]">
                    {laborCatalog.entries.map((entry, i) => (
                      <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-2 px-3 text-gray-300 font-medium">{entry.labor_type}</td>
                        <td className="py-2 px-3 text-gray-400">{entry.description}</td>
                        <td className="py-2 px-3 text-right tabular-nums text-gray-300">
                          ${(entry.cost || 0).toFixed(2)}
                        </td>
                        <td className="py-2 px-3 text-gray-500">{entry.unit}</td>
                        <td className="py-2 px-3 text-right tabular-nums text-gray-500">
                          {entry.gpm_markup ? `${(entry.gpm_markup * 100).toFixed(0)}%` : '\u2014'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : !catalogLoading && (
            <div className="mt-4 text-center py-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
              <HardHat className="w-8 h-8 text-gray-600 mx-auto mb-2 opacity-40" />
              <p className="text-xs text-gray-500">No labor catalog loaded yet</p>
            </div>
          )}
        </div>

        {/* ── 2. Material Price List ──────────────────────── */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-emerald-500/10 flex items-center justify-center flex-shrink-0">
              <ShoppingCart className="w-5 h-5 text-emerald-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Material Price List</h2>
              <p className="text-sm text-gray-500 mt-1">
                Upload or manually manage your material pricing. Used to match against vendor quotes.
              </p>
            </div>
          </div>
          <FileUpload
            accept=".csv,.xlsx,.pdf"
            label="Upload Price List"
            description="CSV, Excel, or PDF with material pricing"
            icon={FileSpreadsheet}
            onUpload={handlePriceListUpload}
            onReset={() => setPriceListSuccess(false)}
            loading={priceListLoading}
            success={priceListSuccess}
            successMessage="Price list uploaded successfully"
          />
          {priceListError && (
            <div className="mt-3 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400 flex items-center justify-between">
              <span>{priceListError}</span>
              <button onClick={() => setPriceListError(null)} className="p-0.5 hover:bg-white/[0.06] rounded">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {priceListFetching ? (
            <div className="mt-4 flex items-center justify-center py-6">
              <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
            </div>
          ) : (
            <div className="mt-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-gray-500 uppercase tracking-[0.12em]">
                    Price Entries
                  </span>
                  {priceList && priceList.count > 0 && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400">
                      {priceList.count} entries
                    </span>
                  )}
                </div>
                <button
                  onClick={() => setShowAddRow(!showAddRow)}
                  className="btn-ghost text-xs px-3 py-1.5 flex items-center gap-1.5"
                >
                  {showAddRow ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
                  {showAddRow ? 'Cancel' : 'Add Entry'}
                </button>
              </div>

              {showAddRow && (
                <div className="mb-3 p-4 bg-white/[0.03] border border-white/[0.06] rounded-xl space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block mb-1">Product Name</label>
                      <input
                        type="text"
                        className="input w-full text-sm"
                        value={newEntry.product_name}
                        onChange={e => setNewEntry(prev => ({ ...prev, product_name: e.target.value }))}
                        placeholder="e.g. Shaw Floors LVT"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block mb-1">Material Type</label>
                      <select
                        className="input w-full text-sm"
                        value={newEntry.material_type}
                        onChange={e => setNewEntry(prev => ({ ...prev, material_type: e.target.value }))}
                      >
                        <option value="">Select type...</option>
                        {MATERIAL_TYPES.map(t => (
                          <option key={t} value={t}>{TYPE_LABELS[t]}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block mb-1">Unit</label>
                      <input
                        type="text"
                        className="input w-full text-sm"
                        value={newEntry.unit}
                        onChange={e => setNewEntry(prev => ({ ...prev, unit: e.target.value }))}
                        placeholder="e.g. SY, SF"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block mb-1">Unit Price</label>
                      <input
                        type="number"
                        step="0.01"
                        className="input w-full text-sm"
                        value={newEntry.unit_price}
                        onChange={e => setNewEntry(prev => ({ ...prev, unit_price: e.target.value }))}
                        placeholder="0.00"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block mb-1">Vendor</label>
                      <input
                        type="text"
                        className="input w-full text-sm"
                        value={newEntry.vendor}
                        onChange={e => setNewEntry(prev => ({ ...prev, vendor: e.target.value }))}
                        placeholder="e.g. Shaw"
                      />
                    </div>
                  </div>
                  <div className="flex justify-end">
                    <button
                      onClick={handleAddEntry}
                      disabled={addingEntry || !newEntry.product_name || !newEntry.unit_price}
                      className="btn-primary text-xs px-4 py-2"
                    >
                      {addingEntry ? (
                        <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Adding...</>
                      ) : (
                        <><Plus className="w-3.5 h-3.5" /> Add Entry</>
                      )}
                    </button>
                  </div>
                </div>
              )}

              {priceList && priceList.count > 0 ? (
                <div className="overflow-x-auto max-h-64 overflow-y-auto rounded-xl border border-white/[0.06]">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-gray-900/95 backdrop-blur-sm">
                      <tr className="border-b border-white/[0.06]">
                        <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Product Name</th>
                        <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Type</th>
                        <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Unit</th>
                        <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider">Unit Price</th>
                        <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Vendor</th>
                        <th className="py-2 px-3 w-10"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.03]">
                      {priceList.entries.map((entry) => (
                        <tr key={entry.id} className="hover:bg-white/[0.02] transition-colors group">
                          <td className="py-2 px-3 text-gray-300 font-medium">{entry.product_name}</td>
                          <td className="py-2 px-3 text-gray-400">{TYPE_LABELS[entry.material_type] || entry.material_type || '\u2014'}</td>
                          <td className="py-2 px-3 text-gray-500">{entry.unit || '\u2014'}</td>
                          <td className="py-2 px-3 text-right tabular-nums text-gray-300">
                            ${(entry.unit_price || 0).toFixed(2)}
                          </td>
                          <td className="py-2 px-3 text-gray-500">{entry.vendor || '\u2014'}</td>
                          <td className="py-2 px-1">
                            <button
                              onClick={() => handleDeleteEntry(entry.id)}
                              disabled={deletingId === entry.id}
                              className="p-1 rounded hover:bg-red-500/10 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                            >
                              {deletingId === entry.id ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
                  <ShoppingCart className="w-8 h-8 text-gray-600 mx-auto mb-2 opacity-40" />
                  <p className="text-xs text-gray-500">No price list entries yet</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── 3. Waste Factors ────────────────────────────── */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-amber-500/10 flex items-center justify-center flex-shrink-0">
              <Droplets className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Waste Factors</h2>
              <p className="text-sm text-gray-500 mt-1">
                Percentage of extra material ordered per type to account for cuts, pattern matching, and waste.
              </p>
            </div>
          </div>

          {wasteLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 text-gray-500 animate-spin" />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto rounded-xl border border-white/[0.06]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="py-2.5 px-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Material Type</th>
                      <th className="py-2.5 px-4 text-right text-xs font-bold text-gray-500 uppercase tracking-wider w-32">Waste %</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.03]">
                    {Object.keys(TYPE_LABELS).map(key => (
                      <tr key={key} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-2 px-4 text-gray-300">{TYPE_LABELS[key]}</td>
                        <td className="py-2 px-4 text-right">
                          <div className="flex items-center justify-end gap-1">
                            <input
                              type="number"
                              step="1"
                              min="0"
                              max="100"
                              className="input w-20 text-right text-sm tabular-nums"
                              value={editedWaste[key] != null ? Math.round(editedWaste[key] * 100) : ''}
                              onChange={e => {
                                const val = e.target.value
                                setEditedWaste(prev => ({
                                  ...prev,
                                  [key]: val === '' ? 0 : parseFloat(val) / 100,
                                }))
                              }}
                            />
                            <span className="text-gray-500 text-xs">%</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center gap-3 mt-4">
                <button
                  onClick={handleWasteSave}
                  disabled={wasteSaving || !wasteHasChanges}
                  className="btn-primary"
                >
                  {wasteSaving ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>
                  ) : wasteSaveSuccess ? (
                    <><Check className="w-4 h-4" /> Saved</>
                  ) : (
                    'Save Waste Factors'
                  )}
                </button>
                {wasteError && (
                  <span className="text-sm text-red-400 flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {wasteError}
                  </span>
                )}
              </div>
            </>
          )}
        </div>

        {/* ── 4. Sundry Rules ─────────────────────────────── */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-si-bright/10 flex items-center justify-center flex-shrink-0">
              <Wrench className="w-5 h-5 text-si-bright" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Sundry Rules</h2>
              <p className="text-sm text-gray-500 mt-1">
                Auto-calculated sundry items (adhesive, seam sealer, transitions) per material type.
              </p>
            </div>
          </div>

          {sundryLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 text-gray-500 animate-spin" />
            </div>
          ) : sundryRules && Object.keys(sundryRules).length > 0 ? (
            <div className="space-y-2">
              {Object.entries(sundryRules).map(([typeKey, items]) => {
                const isExpanded = expandedSundry[typeKey]
                const label = TYPE_LABELS[typeKey] || typeKey
                const itemList = Array.isArray(items) ? items : []
                return (
                  <div key={typeKey} className="border border-white/[0.06] rounded-xl overflow-hidden">
                    <button
                      onClick={() => toggleSundrySection(typeKey)}
                      className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4 text-gray-500" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-gray-500" />
                        )}
                        <span className="text-sm font-medium text-gray-200">{label}</span>
                      </div>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-white/[0.06] text-gray-400">
                        {itemList.length} {itemList.length === 1 ? 'item' : 'items'}
                      </span>
                    </button>
                    {isExpanded && itemList.length > 0 && (
                      <div className="border-t border-white/[0.06]">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-white/[0.04]">
                              <th className="py-2 px-4 text-left font-bold text-gray-500 uppercase tracking-wider">Name</th>
                              <th className="py-2 px-4 text-right font-bold text-gray-500 uppercase tracking-wider">Coverage</th>
                              <th className="py-2 px-4 text-left font-bold text-gray-500 uppercase tracking-wider">Unit</th>
                              <th className="py-2 px-4 text-right font-bold text-gray-500 uppercase tracking-wider">Unit Price</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-white/[0.03]">
                            {itemList.map((item, i) => (
                              <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                                <td className="py-2 px-4 text-gray-300 font-medium">{item.sundry_name || item.name || '\u2014'}</td>
                                <td className="py-2 px-4 text-right tabular-nums text-gray-400">{item.coverage ?? '\u2014'}</td>
                                <td className="py-2 px-4 text-gray-500">{item.unit || '\u2014'}</td>
                                <td className="py-2 px-4 text-right tabular-nums text-gray-300">
                                  {item.unit_price != null ? `$${Number(item.unit_price).toFixed(2)}` : '\u2014'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-center py-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
              <Wrench className="w-8 h-8 text-gray-600 mx-auto mb-2 opacity-40" />
              <p className="text-xs text-gray-500">No sundry rules configured</p>
            </div>
          )}

          <div className="mt-4 flex items-start gap-2 px-4 py-3 bg-si-bright/[0.04] border border-si-bright/10 rounded-xl">
            <Info className="w-4 h-4 text-si-bright flex-shrink-0 mt-0.5" />
            <p className="text-xs text-gray-400 leading-relaxed">
              Sundry rules are managed server-side. Contact support to modify sundry configurations.
            </p>
          </div>
        </div>

        {/* ── 5. Freight Rates ────────────────────────────── */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-blue-500/10 flex items-center justify-center flex-shrink-0">
              <Truck className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Freight Rates</h2>
              <p className="text-sm text-gray-500 mt-1">
                Per-unit shipping costs applied to each material category in bid calculations.
              </p>
            </div>
          </div>

          {freightLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 text-gray-500 animate-spin" />
            </div>
          ) : editedFreight && Object.keys(editedFreight).length > 0 ? (
            <>
              <div className="overflow-x-auto rounded-xl border border-white/[0.06]">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="py-2.5 px-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Category</th>
                      <th className="py-2.5 px-4 text-right text-xs font-bold text-gray-500 uppercase tracking-wider w-36">Rate per Unit</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.03]">
                    {Object.entries(editedFreight).map(([key, value]) => (
                      <tr key={key} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-2 px-4 text-gray-300">{TYPE_LABELS[key] || key}</td>
                        <td className="py-2 px-4 text-right">
                          <div className="flex items-center justify-end gap-1">
                            <span className="text-gray-500 text-xs">$</span>
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              className="input w-24 text-right text-sm tabular-nums"
                              value={value ?? ''}
                              onChange={e => {
                                const val = e.target.value
                                setEditedFreight(prev => ({
                                  ...prev,
                                  [key]: val === '' ? 0 : parseFloat(val),
                                }))
                              }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center gap-3 mt-4">
                <button
                  onClick={handleFreightSave}
                  disabled={freightSaving || !freightHasChanges}
                  className="btn-primary"
                >
                  {freightSaving ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>
                  ) : freightSaveSuccess ? (
                    <><Check className="w-4 h-4" /> Saved</>
                  ) : (
                    'Save Freight Rates'
                  )}
                </button>
                {freightError && (
                  <span className="text-sm text-red-400 flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {freightError}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="text-center py-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
              <Truck className="w-8 h-8 text-gray-600 mx-auto mb-2 opacity-40" />
              <p className="text-xs text-gray-500">No freight rates configured</p>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
