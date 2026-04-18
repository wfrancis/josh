import { useState, useEffect, useRef } from 'react'
import { Loader2, Check, Save, ChevronDown, ChevronRight, Search, Plus, Trash2, AlertTriangle, Link2 } from 'lucide-react'
import { api } from '../api'

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
  transitions: 'Transitions',
  waterproofing: 'Waterproofing',
  sound_mat: 'Sound Mat',
}

const TYPE_GROUPS = {
  'Carpet': ['unit_carpet_no_pattern', 'unit_carpet_pattern', 'corridor_broadloom'],
  'Hard Tile': ['floor_tile', 'wall_tile', 'backsplash', 'tub_shower_surround'],
  'Resilient': ['unit_lvt', 'cpt_tile', 'vct', 'rubber_tile', 'rubber_sheet'],
  'Other': ['rubber_base', 'wood', 'tread_riser', 'transitions', 'waterproofing', 'sound_mat'],
}

const SUNDRY_NAME_LABELS = {
  pad: 'Pad (6lb 3/8")', pad_cement: 'Pad Cement', tack_strip: 'Tack Strip', seam_tape: 'Seam Tape',
  adhesive: 'Adhesive', primer: 'Primer', thinset: 'Thinset (Grey)', white_thinset: 'Thinset (White)',
  lft_thinset: 'LFT Thinset', grout: 'Grout (Prism)', caulking: 'Caulking',
  schluter_jolly: 'Schluter Jolly AE', weld_rod: 'Weld Rod',
}

const FREIGHT_MAP = {
  cpt_tile: 'cpt_tile',
  corridor_broadloom: 'broadloom',
  unit_carpet_no_pattern: 'broadloom',
  unit_carpet_pattern: 'broadloom',
  unit_lvt: 'lvt_2mm',
  // Other types don't typically have freight
}

function titleCase(slug) {
  return slug.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function getSundryLabel(name) {
  return SUNDRY_NAME_LABELS[name] || titleCase(name)
}

const inputClass = 'bg-white/[0.04] border border-white/[0.06] rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-white/[0.15] w-full'

export default function ByMaterialTab() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  const [selectedType, setSelectedType] = useState('unit_carpet_no_pattern')
  const [searchQuery, setSearchQuery] = useState('')

  const [editedSundry, setEditedSundry] = useState({})
  const [editedWaste, setEditedWaste] = useState({})
  const [editedFreight, setEditedFreight] = useState({})

  // Originals for dirty tracking
  const [origSundry, setOrigSundry] = useState({})
  const [origWaste, setOrigWaste] = useState({})
  const [origFreight, setOrigFreight] = useState({})

  const [collapsedGroups, setCollapsedGroups] = useState({})

  useEffect(() => {
    loadAll()
  }, [])

  async function loadAll() {
    setLoading(true)
    setError(null)
    try {
      const [sundry, waste, freight] = await Promise.all([
        api.getCompanyRate('sundry_rules'),
        api.getCompanyRate('waste_factors'),
        api.getCompanyRate('freight_rates'),
      ])
      const s = sundry?.data || sundry || {}
      const w = waste?.data || waste || {}
      const f = freight?.data || freight || {}
      setEditedSundry(JSON.parse(JSON.stringify(s)))
      setEditedWaste({ ...w })
      setEditedFreight({ ...f })
      setOrigSundry(JSON.parse(JSON.stringify(s)))
      setOrigWaste({ ...w })
      setOrigFreight({ ...f })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const isDirty =
    JSON.stringify(editedSundry) !== JSON.stringify(origSundry) ||
    JSON.stringify(editedWaste) !== JSON.stringify(origWaste) ||
    JSON.stringify(editedFreight) !== JSON.stringify(origFreight)

  async function handleSaveAll() {
    setSaving(true)
    setSaveSuccess(false)
    setError(null)
    try {
      await Promise.all([
        api.updateCompanyRate('sundry_rules', editedSundry),
        api.updateCompanyRate('waste_factors', editedWaste),
        api.updateCompanyRate('freight_rates', editedFreight),
      ])
      setOrigSundry(JSON.parse(JSON.stringify(editedSundry)))
      setOrigWaste({ ...editedWaste })
      setOrigFreight({ ...editedFreight })
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  function updateSundryField(typeKey, idx, field, value) {
    setEditedSundry(prev => {
      const copy = JSON.parse(JSON.stringify(prev))
      if (!copy[typeKey]) copy[typeKey] = []
      copy[typeKey][idx] = { ...copy[typeKey][idx], [field]: value }
      return copy
    })
  }

  function addSundryRow(typeKey) {
    setEditedSundry(prev => {
      const copy = JSON.parse(JSON.stringify(prev))
      if (!copy[typeKey]) copy[typeKey] = []
      copy[typeKey].push({ sundry_name: '', coverage: '', unit: '', unit_price: 0 })
      return copy
    })
  }

  function removeSundryRow(typeKey, idx) {
    setEditedSundry(prev => {
      const copy = JSON.parse(JSON.stringify(prev))
      if (copy[typeKey]) copy[typeKey].splice(idx, 1)
      return copy
    })
  }

  // Filter material types by search
  const lowerQuery = searchQuery.toLowerCase()
  function matchesSearch(typeKey) {
    if (!searchQuery) return true
    const label = TYPE_LABELS[typeKey] || typeKey
    return label.toLowerCase().includes(lowerQuery) || typeKey.toLowerCase().includes(lowerQuery)
  }

  const sundryItems = editedSundry[selectedType] || []
  const freightKey = FREIGHT_MAP[selectedType]

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 gap-3 text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin" />
        Loading material data...
      </div>
    )
  }

  return (
    <div className="flex gap-0" style={{ minHeight: '70vh' }}>
      {/* Left sidebar */}
      <div className="w-52 flex-shrink-0 border-r border-white/[0.06] pr-3 overflow-y-auto" style={{ maxHeight: '75vh' }}>
        {/* Search */}
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
          <input
            type="text"
            placeholder="Search materials..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="bg-white/[0.04] border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-white/[0.15] w-full pl-9"
          />
        </div>

        {/* Material type list */}
        {searchQuery ? (
          // Flat filtered list when searching
          <div className="space-y-0.5">
            {Object.keys(TYPE_LABELS).filter(matchesSearch).map(typeKey => (
              <SidebarItem
                key={typeKey}
                typeKey={typeKey}
                selected={selectedType === typeKey}
                onClick={() => setSelectedType(typeKey)}
                count={editedSundry[typeKey]?.length || 0}
              />
            ))}
          </div>
        ) : (
          // Grouped list
          Object.entries(TYPE_GROUPS).map(([groupName, types]) => {
            const isCollapsed = collapsedGroups[groupName]
            return (
              <div key={groupName} className="mb-1">
                <button
                  onClick={() => setCollapsedGroups(prev => ({ ...prev, [groupName]: !prev[groupName] }))}
                  className="w-full flex items-center gap-1 text-[10px] font-bold text-gray-600 uppercase tracking-[0.12em] px-2 py-2 hover:text-gray-400 transition-colors"
                >
                  {isCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  {groupName}
                </button>
                {!isCollapsed && (
                  <div className="space-y-0.5">
                    {types.filter(matchesSearch).map(typeKey => (
                      <SidebarItem
                        key={typeKey}
                        typeKey={typeKey}
                        selected={selectedType === typeKey}
                        onClick={() => setSelectedType(typeKey)}
                        count={editedSundry[typeKey]?.length || 0}
                      />
                    ))}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>

      {/* Right detail panel */}
      <div className="flex-1 pl-6 overflow-y-auto" style={{ maxHeight: '75vh' }}>
        <h2 className="text-lg font-bold text-white mb-5">
          {TYPE_LABELS[selectedType] || selectedType}
        </h2>

        {error && (
          <div className="flex items-center gap-2 text-red-400 text-sm mb-4 bg-red-500/[0.08] border border-red-500/20 rounded-lg px-4 py-2.5">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* Section 1: Sundry Rules */}
        <div className="glass-card p-5 mb-4">
          <div className="flex items-center gap-2 mb-4">
            <h3 className="text-sm font-semibold text-white">Sundry Rules</h3>
            <span className="text-[10px] bg-white/[0.08] text-gray-400 px-2 py-0.5 rounded-full">
              {sundryItems.length}
            </span>
          </div>

          {sundryItems.length > 0 ? (
            <table className="w-full text-sm table-fixed">
              <thead>
                <tr className="text-[11px] text-gray-500 uppercase tracking-wider">
                  <th className="text-left pb-2 font-medium" style={{width:'180px'}}>Name</th>
                  <th className="text-left pb-2 font-medium" style={{width:'80px'}}>Coverage</th>
                  <th className="text-left pb-2 font-medium" style={{width:'90px'}}>Unit</th>
                  <th className="text-left pb-2 font-medium" style={{width:'110px'}}>Unit Price</th>
                  <th className="pb-2" style={{width:'32px'}}></th>
                </tr>
              </thead>
              <tbody>
                {sundryItems.map((item, idx) => (
                  <tr key={idx} className="group border-t border-white/[0.04]">
                    <td className="py-2 pr-2">
                      <select
                        value={item.sundry_name || ''}
                        onChange={e => updateSundryField(selectedType, idx, 'sundry_name', e.target.value)}
                        className={inputClass}
                      >
                        <option value="">Select...</option>
                        {Object.entries(SUNDRY_NAME_LABELS).map(([key, label]) => (
                          <option key={key} value={key}>{label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2 pr-2">
                      <input
                        type="text"
                        value={item.coverage ?? ''}
                        onChange={e => updateSundryField(selectedType, idx, 'coverage', e.target.value)}
                        className={inputClass}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <input
                        type="text"
                        value={item.unit ?? ''}
                        onChange={e => updateSundryField(selectedType, idx, 'unit', e.target.value)}
                        className={inputClass}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <div className="relative">
                        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
                        <input
                          type="number"
                          step="0.01"
                          value={item.unit_price ?? 0}
                          onChange={e => updateSundryField(selectedType, idx, 'unit_price', parseFloat(e.target.value) || 0)}
                          className={`${inputClass} pl-6`}
                        />
                      </div>
                    </td>
                    <td className="py-2">
                      <button
                        onClick={() => removeSundryRow(selectedType, idx)}
                        className="opacity-0 group-hover:opacity-100 p-1 text-gray-500 hover:text-red-400 transition-all"
                        title="Remove"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-gray-500 italic">No sundry rules for this material type.</p>
          )}

          <button
            onClick={() => addSundryRow(selectedType)}
            className="mt-3 flex items-center gap-1.5 text-xs text-gray-400 hover:text-white transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            Add Sundry
          </button>
        </div>

        {/* Section 2: Waste Factor */}
        <div className="glass-card p-5 mb-4">
          <h3 className="text-sm font-semibold text-white mb-3">Waste Factor</h3>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-400">Waste Factor</span>
            <div className="relative w-28">
              <input
                type="number"
                step="1"
                value={editedWaste[selectedType] != null ? Math.round(editedWaste[selectedType] * 100) : ''}
                onChange={e => setEditedWaste(prev => ({ ...prev, [selectedType]: (parseFloat(e.target.value) || 0) / 100 }))}
                className={inputClass}
              />
            </div>
            <span className="text-sm text-gray-500">%</span>
          </div>
        </div>

        {/* Section 3: Freight Rate */}
        <div className="glass-card p-5 mb-4">
          <div className="flex items-center gap-2 mb-3">
            <h3 className="text-sm font-semibold text-white">Freight Rate</h3>
            {freightKey && freightKey !== selectedType && (
              <span className="flex items-center gap-1 text-[10px] text-gray-500">
                <Link2 className="w-3 h-3" />
                {freightKey}
              </span>
            )}
          </div>
          {freightKey ? (
            <div className="flex items-center gap-3">
              <span className="text-sm text-gray-400">Freight Rate</span>
              <div className="relative w-28">
                <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
                <input
                  type="number"
                  step="0.01"
                  value={editedFreight[freightKey] ?? ''}
                  onChange={e => setEditedFreight(prev => ({ ...prev, [freightKey]: parseFloat(e.target.value) || 0 }))}
                  className={`${inputClass} pl-6 w-28`}
                />
              </div>
              <span className="text-sm text-gray-500">$/unit</span>
            </div>
          ) : (
            <p className="text-sm text-gray-500">Not applicable — freight is typically only charged for carpet, carpet tile, and LVT.</p>
          )}
        </div>

        {/* Save button */}
        <div className="pt-2">
          <button
            onClick={handleSaveAll}
            disabled={saving || !isDirty}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all ${
              saveSuccess
                ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                : isDirty
                  ? 'bg-orange-500 hover:bg-orange-600 text-white shadow-lg shadow-orange-500/20'
                  : 'bg-white/[0.06] text-gray-500 cursor-not-allowed'
            }`}
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : saveSuccess ? (
              <Check className="w-4 h-4" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saving ? 'Saving...' : saveSuccess ? 'Saved' : 'Save All Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

function SidebarItem({ typeKey, selected, onClick, count }) {
  const ref = useRef(null)
  useEffect(() => {
    if (selected && ref.current) ref.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selected])
  return (
    <button
      ref={ref}
      onClick={onClick}
      className={`w-full text-left px-3 py-2 rounded-lg text-sm flex items-center justify-between transition-colors ${
        selected
          ? 'bg-white/[0.08] text-white'
          : 'text-gray-400 hover:text-gray-200 hover:bg-white/[0.04]'
      }`}
    >
      <span className="truncate">{TYPE_LABELS[typeKey] || typeKey}</span>
      {count > 0 && (
        <span className="text-[10px] bg-white/[0.08] text-gray-500 px-1.5 py-0.5 rounded-full ml-2 flex-shrink-0">
          {count}
        </span>
      )}
    </button>
  )
}
