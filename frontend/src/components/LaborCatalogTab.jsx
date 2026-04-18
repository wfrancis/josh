import { useState, useEffect } from 'react'
import {
  HardHat, FileSpreadsheet, Loader2, Check, Trash2,
  Search, ChevronDown, ChevronRight, Upload
} from 'lucide-react'
import { api } from '../api'
import FileUpload from './FileUpload'

export default function LaborCatalogTab() {
  // Data
  const [laborCatalog, setLaborCatalog] = useState(null)
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [editedLabor, setEditedLabor] = useState([])
  const [laborDirty, setLaborDirty] = useState(false)

  // Upload
  const [laborLoading, setLaborLoading] = useState(false)
  const [laborSuccess, setLaborSuccess] = useState(false)
  const [laborError, setLaborError] = useState(null)

  // Save
  const [laborSaving, setLaborSaving] = useState(false)
  const [laborSaveSuccess, setLaborSaveSuccess] = useState(false)

  // Search
  const [search, setSearch] = useState('')

  // Upload section collapse
  const [uploadExpanded, setUploadExpanded] = useState(false)

  // Load on mount
  useEffect(() => {
    api.getLaborCatalog()
      .then(data => {
        setLaborCatalog(data)
        if (!data?.entries?.length) setUploadExpanded(true)
      })
      .catch(() => {
        setLaborCatalog({ entries: [], count: 0 })
        setUploadExpanded(true)
      })
      .finally(() => setCatalogLoading(false))
  }, [])

  // Sync edited state when data loads
  useEffect(() => {
    if (laborCatalog?.entries) setEditedLabor(laborCatalog.entries.map(e => ({ ...e })))
  }, [laborCatalog])

  // Filter logic
  const filtered = editedLabor.filter(entry => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      (entry.labor_type || '').toLowerCase().includes(q) ||
      (entry.description || '').toLowerCase().includes(q)
    )
  })

  const isFiltered = search && filtered.length !== editedLabor.length

  // Edit handler
  const updateLaborEntry = (globalIndex, field, value) => {
    setEditedLabor(prev => {
      const updated = [...prev]
      updated[globalIndex] = { ...updated[globalIndex], [field]: value }
      return updated
    })
    setLaborDirty(true)
  }

  // Save all
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

  // Delete single
  const handleDeleteLaborEntry = async (id) => {
    try {
      await api.deleteLaborCatalogEntry(id)
      const data = await api.getLaborCatalog()
      setLaborCatalog(data)
    } catch (err) {
      setLaborError(err.message)
    }
  }

  // Clear all
  const handleClearLabor = async () => {
    if (!confirm('Clear all labor catalog entries? This cannot be undone.')) return
    try {
      await api.clearLaborCatalog()
      setLaborCatalog({ entries: [], count: 0 })
      setEditedLabor([])
      setLaborDirty(false)
      setUploadExpanded(true)
    } catch (err) {
      setLaborError(err.message)
    }
  }

  // Upload
  const handleLaborUpload = async (file) => {
    setLaborLoading(true)
    setLaborError(null)
    try {
      await api.uploadLaborCatalog(file)
      setLaborSuccess(true)
      const data = await api.getLaborCatalog()
      setLaborCatalog(data)
      setUploadExpanded(false)
    } catch (err) {
      setLaborError(err.message)
    } finally {
      setLaborLoading(false)
    }
  }

  // Find the global index for a filtered entry
  const getGlobalIndex = (entry) => editedLabor.indexOf(entry)

  return (
    <div className="space-y-6">
      <div className="glass-card p-8">
        {/* Header */}
        <div className="flex items-start gap-4 mb-6">
          <div className="w-11 h-11 rounded-xl bg-violet-500/10 flex items-center justify-center flex-shrink-0">
            <HardHat className="w-5 h-5 text-violet-400" />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-white">Labor Catalog</h2>
            <p className="text-sm text-gray-500 mt-1">
              Searchable catalog of labor rates used when generating bids. Upload a PDF or Excel file, or edit entries inline.
            </p>
          </div>
        </div>

        {/* Upload section — collapsible */}
        <div className="mb-6">
          <button
            onClick={() => setUploadExpanded(!uploadExpanded)}
            className="flex items-center gap-2 text-xs font-medium text-gray-400 hover:text-gray-300 transition-colors mb-3"
          >
            {uploadExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            <Upload className="w-3.5 h-3.5" />
            Upload Labor Catalog
          </button>
          {uploadExpanded && (
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
          )}
        </div>

        {/* Error */}
        {laborError && (
          <div className="mb-4 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
            {laborError}
          </div>
        )}

        {/* Loading */}
        {catalogLoading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
          </div>
        ) : laborCatalog && laborCatalog.count > 0 ? (
          <div>
            {/* Toolbar: search + actions */}
            <div className="flex items-center gap-3 mb-3">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
                <input
                  type="text"
                  placeholder="Search by type or description..."
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-white/[0.04] border border-white/[0.06] rounded-lg text-xs text-gray-300 placeholder-gray-600 outline-none focus:border-violet-500/30 focus:bg-white/[0.06] transition-colors"
                />
              </div>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400 whitespace-nowrap">
                {isFiltered ? `${filtered.length} of ${editedLabor.length}` : `${editedLabor.length}`} entries
              </span>
              <button
                onClick={handleClearLabor}
                className="btn-ghost text-xs px-3 py-1.5 text-red-400 hover:text-red-300 hover:bg-red-500/10 flex items-center gap-1.5"
              >
                <Trash2 className="w-3.5 h-3.5" /> Clear All
              </button>
            </div>

            {/* Table */}
            <div className="overflow-x-auto max-h-[28rem] overflow-y-auto rounded-xl border border-white/[0.06]">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-gray-900/95 backdrop-blur-sm z-10">
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
                  {filtered.map((entry) => {
                    const gi = getGlobalIndex(entry)
                    return (
                      <tr key={entry.id || gi} className="hover:bg-white/[0.02] transition-colors group">
                        <td className="py-2 px-3 text-gray-300 font-medium">
                          <input
                            type="text"
                            className="bg-transparent border-0 outline-none w-full text-xs text-gray-300 font-medium cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.labor_type || ''}
                            onChange={e => updateLaborEntry(gi, 'labor_type', e.target.value)}
                          />
                        </td>
                        <td className="py-2 px-3 text-gray-400">
                          <input
                            type="text"
                            className="bg-transparent border-0 outline-none w-full text-xs text-gray-400 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.description || ''}
                            onChange={e => updateLaborEntry(gi, 'description', e.target.value)}
                          />
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-gray-300">
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            className="bg-transparent border-0 outline-none w-full text-xs text-right tabular-nums text-gray-300 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.cost ?? ''}
                            onChange={e => updateLaborEntry(gi, 'cost', e.target.value === '' ? 0 : parseFloat(e.target.value))}
                          />
                        </td>
                        <td className="py-2 px-3 text-gray-500">
                          <input
                            type="text"
                            className="bg-transparent border-0 outline-none w-full text-xs text-gray-500 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.unit || ''}
                            onChange={e => updateLaborEntry(gi, 'unit', e.target.value)}
                          />
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-gray-500">
                          <input
                            type="number"
                            step="1"
                            min="0"
                            max="100"
                            className="bg-transparent border-0 outline-none w-full text-xs text-right tabular-nums text-gray-500 cursor-text focus:bg-white/[0.06] focus:px-1.5 focus:py-0.5 focus:-mx-1.5 focus:-my-0.5 focus:rounded-md transition-colors"
                            value={entry.gpm_markup != null ? Math.round(entry.gpm_markup * 100) : ''}
                            onChange={e => updateLaborEntry(gi, 'gpm_markup', e.target.value === '' ? 0 : parseFloat(e.target.value) / 100)}
                          />
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
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Save / Clear buttons */}
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
                  'Save All'
                )}
              </button>
            </div>
          </div>
        ) : !catalogLoading && (
          <div className="text-center py-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
            <HardHat className="w-8 h-8 text-gray-600 mx-auto mb-2 opacity-40" />
            <p className="text-xs text-gray-500">No labor catalog loaded yet</p>
          </div>
        )}
      </div>
    </div>
  )
}
