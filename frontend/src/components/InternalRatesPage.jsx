import { useState, useEffect } from 'react'
import {
  DollarSign, HardHat, FileSpreadsheet, Droplets,
  Wrench, Truck, Loader2, Check, AlertTriangle, Plus, Trash2,
  ChevronDown, ChevronRight, X
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
  const [editedLabor, setEditedLabor] = useState([])
  const [laborDirty, setLaborDirty] = useState(false)
  const [laborSaving, setLaborSaving] = useState(false)
  const [laborSaveSuccess, setLaborSaveSuccess] = useState(false)

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
  const [editedSundry, setEditedSundry] = useState({})
  const [sundrySaving, setSundrySaving] = useState(false)
  const [sundrySaveSuccess, setSundrySaveSuccess] = useState(false)
  const [sundryError, setSundryError] = useState(null)

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

    api.getCompanyRate('waste_factors')
      .then(res => { setWasteFactors(res.data); setEditedWaste(res.data || {}) })
      .catch(() => { setWasteFactors({}); setEditedWaste({}) })
      .finally(() => setWasteLoading(false))

    api.getCompanyRate('sundry_rules')
      .then(res => { setSundryRules(res.data || {}); setEditedSundry(res.data || {}) })
      .catch(() => { setSundryRules({}); setEditedSundry({}) })
      .finally(() => setSundryLoading(false))

    api.getCompanyRate('freight_rates')
      .then(res => { setFreightRates(res.data); setEditedFreight(res.data || {}) })
      .catch(() => { setFreightRates({}); setEditedFreight({}) })
      .finally(() => setFreightLoading(false))
  }, [])

  // Sync edited state when data loads
  useEffect(() => {
    if (laborCatalog?.entries) setEditedLabor(laborCatalog.entries.map(e => ({ ...e })))
  }, [laborCatalog])

  // Labor edit handlers
  const updateLaborEntry = (index, field, value) => {
    setEditedLabor(prev => {
      const updated = [...prev]
      updated[index] = { ...updated[index], [field]: value }
      return updated
    })
    setLaborDirty(true)
  }

  const handleLaborSaveAll = async () => {
    setLaborSaving(true)
    setLaborError(null)
    try {
      for (const entry of editedLabor) {
        if (entry.id) await api.updateLaborCatalogEntry(entry.id, entry)
      }
      const data = await api.getLaborCatalog()
      setLaborCatalog(data)
      setLaborDirty(false)
      setLaborSaveSuccess(true)
      setTimeout(() => setLaborSaveSuccess(false), 3000)
    } catch (err) {
      setLaborError(err.message)
    } finally {
      setLaborSaving(false)
    }
  }

  const handleDeleteLaborEntry = async (id) => {
    try {
      await api.deleteLaborCatalogEntry(id)
      const data = await api.getLaborCatalog()
      setLaborCatalog(data)
    } catch (err) {
      setLaborError(err.message)
    }
  }

  const handleClearLabor = async () => {
    if (!confirm('Clear all labor catalog entries? This cannot be undone.')) return
    try {
      await api.clearLaborCatalog()
      setLaborCatalog({ entries: [], count: 0 })
      setEditedLabor([])
      setLaborDirty(false)
    } catch (err) {
      setLaborError(err.message)
    }
  }

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

  // Handlers — Sundry Rules
  const handleSundrySave = async () => {
    setSundrySaving(true)
    setSundryError(null)
    setSundrySaveSuccess(false)
    try {
      await api.updateCompanyRate('sundry_rules', editedSundry)
      setSundryRules(editedSundry)
      setSundrySaveSuccess(true)
      setTimeout(() => setSundrySaveSuccess(false), 3000)
    } catch (err) {
      setSundryError(err.message)
    } finally {
      setSundrySaving(false)
    }
  }

  const updateSundryItem = (typeKey, index, field, value) => {
    setEditedSundry(prev => {
      const items = [...(prev[typeKey] || [])]
      items[index] = { ...items[index], [field]: value }
      return { ...prev, [typeKey]: items }
    })
  }

  const addSundryItem = (typeKey) => {
    setEditedSundry(prev => {
      const items = [...(prev[typeKey] || []), { sundry_name: '', coverage: 0, unit: '', unit_price: 0 }]
      return { ...prev, [typeKey]: items }
    })
  }

  const removeSundryItem = (typeKey, index) => {
    setEditedSundry(prev => {
      const items = [...(prev[typeKey] || [])]
      items.splice(index, 1)
      return { ...prev, [typeKey]: items }
    })
  }

  const toggleSundrySection = (key) => {
    setExpandedSundry(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const sundryHasChanges = JSON.stringify(sundryRules) !== JSON.stringify(editedSundry)
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
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-gray-500 uppercase tracking-[0.12em]">
                    Loaded Rates
                  </span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400">
                    {laborCatalog.count} entries
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleClearLabor}
                    className="btn-ghost text-xs px-3 py-1.5 text-red-400 hover:text-red-300 hover:bg-red-500/10 flex items-center gap-1.5"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Clear All
                  </button>
                </div>
              </div>
              <div className="overflow-x-auto max-h-64 overflow-y-auto rounded-xl border border-white/[0.06]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900/95 backdrop-blur-sm">
                    <tr className="border-b border-white/[0.06]">
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Type</th>
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Description</th>
                      <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider">Cost</th>
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Unit</th>
                      <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider">Markup %</th>
                      <th className="py-2 px-3 w-10"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.03]">
                    {editedLabor.map((entry, i) => (
                      <tr key={entry.id || i} className="hover:bg-white/[0.02] transition-colors group">
                        <td className="py-2 px-3 text-gray-300 font-medium">
                          <input type="text" className="bg-transparent border-0 outline-none w-full text-xs text-gray-300 font-medium cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.labor_type || ''}
                            onChange={e => updateLaborEntry(i, 'labor_type', e.target.value)} />
                        </td>
                        <td className="py-2 px-3 text-gray-400">
                          <input type="text" className="bg-transparent border-0 outline-none w-full text-xs text-gray-400 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.description || ''}
                            onChange={e => updateLaborEntry(i, 'description', e.target.value)} />
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-gray-300">
                          <input type="number" step="0.01" min="0" className="bg-transparent border-0 outline-none w-full text-xs text-right tabular-nums text-gray-300 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.cost ?? ''}
                            onChange={e => updateLaborEntry(i, 'cost', e.target.value === '' ? 0 : parseFloat(e.target.value))} />
                        </td>
                        <td className="py-2 px-3 text-gray-500">
                          <input type="text" className="bg-transparent border-0 outline-none w-full text-xs text-gray-500 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.unit || ''}
                            onChange={e => updateLaborEntry(i, 'unit', e.target.value)} />
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-gray-500">
                          <input type="number" step="1" min="0" max="100" className="bg-transparent border-0 outline-none w-full text-xs text-right tabular-nums text-gray-500 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.gpm_markup != null ? Math.round(entry.gpm_markup * 100) : ''}
                            onChange={e => updateLaborEntry(i, 'gpm_markup', e.target.value === '' ? 0 : parseFloat(e.target.value) / 100)} />
                        </td>
                        <td className="py-2 px-1">
                          <button
                            onClick={() => handleDeleteLaborEntry(entry.id)}
                            className="p-1 rounded hover:bg-red-500/10 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center gap-3 mt-3">
                <button
                  onClick={handleLaborSaveAll}
                  disabled={laborSaving || !laborDirty}
                  className="btn-primary text-xs"
                >
                  {laborSaving ? (
                    <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving...</>
                  ) : laborSaveSuccess ? (
                    <><Check className="w-3.5 h-3.5" /> Saved</>
                  ) : (
                    'Save Changes'
                  )}
                </button>
              </div>
            </div>
          ) : !catalogLoading && (
            <div className="mt-4 text-center py-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
              <HardHat className="w-8 h-8 text-gray-600 mx-auto mb-2 opacity-40" />
              <p className="text-xs text-gray-500">No labor catalog loaded yet</p>
            </div>
          )}
        </div>

        {/* ── 2. Waste Factors ────────────────────────────── */}
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
                Sundry items (pad, adhesive, seam tape, transitions) auto-added per material type during bid calculation.
              </p>
            </div>
          </div>

          {sundryLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 text-gray-500 animate-spin" />
            </div>
          ) : editedSundry && Object.keys(editedSundry).length > 0 ? (
            <>
              <div className="space-y-2">
                {Object.entries(editedSundry).map(([typeKey, items]) => {
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
                      {isExpanded && (
                        <div className="border-t border-white/[0.06]">
                          {itemList.length > 0 && (
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="border-b border-white/[0.04]">
                                  <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Name</th>
                                  <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider w-24">Coverage</th>
                                  <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider w-28">Unit</th>
                                  <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider w-28">Unit Price</th>
                                  <th className="py-2 px-3 w-10"></th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-white/[0.03]">
                                {itemList.map((item, i) => (
                                  <tr key={i} className="hover:bg-white/[0.02] transition-colors group">
                                    <td className="py-1.5 px-3">
                                      <input
                                        type="text"
                                        className="input w-full text-xs"
                                        value={item.sundry_name || ''}
                                        onChange={e => updateSundryItem(typeKey, i, 'sundry_name', e.target.value)}
                                      />
                                    </td>
                                    <td className="py-1.5 px-3">
                                      <input
                                        type="number"
                                        step="1"
                                        min="0"
                                        className="input w-full text-xs text-right tabular-nums"
                                        value={item.coverage ?? ''}
                                        onChange={e => updateSundryItem(typeKey, i, 'coverage', e.target.value === '' ? 0 : parseFloat(e.target.value))}
                                      />
                                    </td>
                                    <td className="py-1.5 px-3">
                                      <input
                                        type="text"
                                        className="input w-full text-xs"
                                        value={item.unit || ''}
                                        onChange={e => updateSundryItem(typeKey, i, 'unit', e.target.value)}
                                      />
                                    </td>
                                    <td className="py-1.5 px-3">
                                      <div className="flex items-center gap-1">
                                        <span className="text-gray-500 text-xs">$</span>
                                        <input
                                          type="number"
                                          step="0.01"
                                          min="0"
                                          className="input w-full text-xs text-right tabular-nums"
                                          value={item.unit_price ?? ''}
                                          onChange={e => updateSundryItem(typeKey, i, 'unit_price', e.target.value === '' ? 0 : parseFloat(e.target.value))}
                                        />
                                      </div>
                                    </td>
                                    <td className="py-1.5 px-1">
                                      <button
                                        onClick={() => removeSundryItem(typeKey, i)}
                                        className="p-1 rounded hover:bg-red-500/10 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </button>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                          <div className="px-3 py-2 border-t border-white/[0.04]">
                            <button
                              onClick={() => addSundryItem(typeKey)}
                              className="btn-ghost text-[10px] px-2.5 py-1 flex items-center gap-1"
                            >
                              <Plus className="w-3 h-3" /> Add Sundry
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              <div className="flex items-center gap-3 mt-4">
                <button
                  onClick={handleSundrySave}
                  disabled={sundrySaving || !sundryHasChanges}
                  className="btn-primary"
                >
                  {sundrySaving ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>
                  ) : sundrySaveSuccess ? (
                    <><Check className="w-4 h-4" /> Saved</>
                  ) : (
                    'Save Sundry Rules'
                  )}
                </button>
                {sundryError && (
                  <span className="text-sm text-red-400 flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {sundryError}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="text-center py-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
              <Wrench className="w-8 h-8 text-gray-600 mx-auto mb-2 opacity-40" />
              <p className="text-xs text-gray-500">No sundry rules configured</p>
            </div>
          )}
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
