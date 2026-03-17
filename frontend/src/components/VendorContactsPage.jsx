import { useState, useEffect } from 'react'
import {
  Building2, Plus, Trash2, Loader2, Check, Save, Sparkles,
  ChevronDown, ChevronRight, ExternalLink, X, Search,
  Clock, Mail, Phone, TrendingUp, Package, FileText, Send
} from 'lucide-react'
import { api } from '../api'

export default function VendorContactsPage() {
  const [vendors, setVendors] = useState([])
  const [loading, setLoading] = useState(true)
  const [edited, setEdited] = useState([])
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [newVendor, setNewVendor] = useState({ name: '', contact_name: '', contact_email: '', contact_phone: '', notes: '' })
  const [adding, setAdding] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [vendorDetail, setVendorDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [suggestions, setSuggestions] = useState({}) // keyed by vendor name
  const [searchQuery, setSearchQuery] = useState('')

  const loadVendors = async () => {
    try {
      const data = await api.listVendors()
      setVendors(data)
      setEdited(data.map(v => ({ ...v })))
      setDirty(false)
    } catch (err) {
      console.error('Failed to load vendors:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadVendors() }, [])

  const updateField = (idx, field, value) => {
    setEdited(prev => {
      const next = [...prev]
      next[idx] = { ...next[idx], [field]: value }
      return next
    })
    setDirty(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      for (const v of edited) {
        const orig = vendors.find(o => o.id === v.id)
        if (!orig) continue
        const changed = ['name', 'contact_name', 'contact_title', 'contact_email', 'contact_phone', 'notes']
          .some(k => (v[k] || '') !== (orig[k] || ''))
        if (changed) {
          await api.updateVendor(v.id, v)
        }
      }
      await loadVendors()
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err) {
      console.error('Save failed:', err)
    } finally {
      setSaving(false)
    }
  }

  const handleAdd = async () => {
    if (!newVendor.name.trim()) return
    setAdding(true)
    try {
      await api.createVendor(newVendor)
      setNewVendor({ name: '', contact_name: '', contact_email: '', contact_phone: '', notes: '' })
      setShowAdd(false)
      await loadVendors()
    } catch (err) {
      console.error('Add failed:', err)
      alert(err.message)
    } finally {
      setAdding(false)
    }
  }

  const [confirmDelete, setConfirmDelete] = useState(null)

  const handleDelete = async (id) => {
    setConfirmDelete(id)
  }

  const confirmDeleteVendor = async () => {
    const id = confirmDelete
    setConfirmDelete(null)
    setDeletingId(id)
    try {
      await api.deleteVendor(id)
      await loadVendors()
    } catch (err) {
      console.error('Delete failed:', err)
    } finally {
      setDeletingId(null)
    }
  }

  const handleExpand = async (vendor) => {
    if (expandedId === vendor.id) {
      setExpandedId(null)
      setVendorDetail(null)
      return
    }
    setExpandedId(vendor.id)
    setDetailLoading(true)
    try {
      const detail = await api.getVendor(vendor.id)
      setVendorDetail(detail)
    } catch (err) {
      console.error('Failed to load vendor detail:', err)
    } finally {
      setDetailLoading(false)
    }
  }

  const handleAiSuggest = async () => {
    // Find vendors with missing contact info
    const needsSuggestion = edited.filter(v =>
      !v.contact_email && !v.contact_phone
    ).map(v => v.name)

    if (needsSuggestion.length === 0) {
      alert('All vendors already have contact info!')
      return
    }

    setSuggesting(true)
    try {
      const result = await api.suggestVendorContacts(needsSuggestion)
      const sugMap = {}
      for (const s of (result.suggestions || [])) {
        sugMap[s.vendor] = s
      }
      setSuggestions(sugMap)
    } catch (err) {
      console.error('AI suggestion failed:', err)
      alert('AI suggestion failed: ' + err.message)
    } finally {
      setSuggesting(false)
    }
  }

  const applySuggestion = (vendorName, suggestion) => {
    const idx = edited.findIndex(v => v.name === vendorName)
    if (idx < 0) return
    setEdited(prev => {
      const next = [...prev]
      next[idx] = {
        ...next[idx],
        contact_email: suggestion.general_email || next[idx].contact_email || '',
        notes: [next[idx].notes, suggestion.products, suggestion.notes, suggestion.find_rep_url]
          .filter(Boolean).join(' | '),
      }
      return next
    })
    setDirty(true)
    setSuggestions(prev => {
      const next = { ...prev }
      delete next[vendorName]
      return next
    })
  }

  const filteredEdited = searchQuery
    ? edited.filter(v =>
        v.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (v.contact_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        (v.contact_email || '').toLowerCase().includes(searchQuery.toLowerCase())
      )
    : edited

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-si-accent" />
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <Building2 className="w-7 h-7 text-si-accent" />
          Vendor Contacts
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Manage your vendor reps — contact info is used when generating quote requests.
        </p>
      </div>

      {/* Actions bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search vendors..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full bg-white/[0.04] border border-white/[0.06] rounded-lg pl-9 pr-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-si-accent/40"
          />
        </div>
        <button
          onClick={handleAiSuggest}
          disabled={suggesting}
          className="btn-ghost text-xs px-3 py-2 text-violet-400 hover:text-violet-300 flex items-center gap-1.5"
        >
          {suggesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
          AI Suggest Contacts
        </button>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="btn-ghost text-xs px-3 py-2 text-emerald-400 hover:text-emerald-300 flex items-center gap-1.5"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Vendor
        </button>
        <button
          onClick={handleSave}
          disabled={saving || !dirty}
          className="btn-secondary text-sm flex items-center gap-1.5"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : saveSuccess ? <Check className="w-4 h-4 text-emerald-400" /> : <Save className="w-4 h-4" />}
          {saveSuccess ? 'Saved' : 'Save Changes'}
        </button>
      </div>

      {/* Add vendor form */}
      {showAdd && (
        <div className="glass-card p-4 animate-slide-up">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-white">New Vendor</h3>
            <button onClick={() => setShowAdd(false)} className="text-gray-500 hover:text-gray-300">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <input
              placeholder="Vendor Name *"
              value={newVendor.name}
              onChange={e => setNewVendor(p => ({ ...p, name: e.target.value }))}
              className="bg-white/[0.06] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-si-accent/40"
            />
            <input
              placeholder="Contact Name"
              value={newVendor.contact_name}
              onChange={e => setNewVendor(p => ({ ...p, contact_name: e.target.value }))}
              className="bg-white/[0.06] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-si-accent/40"
            />
            <input
              placeholder="Email"
              value={newVendor.contact_email}
              onChange={e => setNewVendor(p => ({ ...p, contact_email: e.target.value }))}
              className="bg-white/[0.06] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-si-accent/40"
            />
            <input
              placeholder="Phone"
              value={newVendor.contact_phone}
              onChange={e => setNewVendor(p => ({ ...p, contact_phone: e.target.value }))}
              className="bg-white/[0.06] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-si-accent/40"
            />
            <button
              onClick={handleAdd}
              disabled={adding || !newVendor.name.trim()}
              className="bg-gradient-to-b from-si-orange to-orange-600 text-white text-sm font-semibold rounded-lg px-4 py-2 hover:from-orange-500 hover:to-orange-700 disabled:opacity-50 flex items-center justify-center gap-1.5"
            >
              {adding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Add
            </button>
          </div>
        </div>
      )}

      {/* Vendor table */}
      <div className="glass-card overflow-hidden">
        {filteredEdited.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            <Building2 className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p className="text-sm">{searchQuery ? 'No vendors match your search.' : 'No vendors yet. Add one or upload vendor quotes to auto-create.'}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-900/95 backdrop-blur-sm z-10">
                <tr className="border-b border-white/[0.06]">
                  <th className="text-left text-[10px] font-bold text-gray-500 uppercase tracking-wider px-4 py-3">Vendor</th>
                  <th className="text-left text-[10px] font-bold text-gray-500 uppercase tracking-wider px-3 py-3 hidden sm:table-cell">Contact</th>
                  <th className="text-left text-[10px] font-bold text-gray-500 uppercase tracking-wider px-3 py-3">Email</th>
                  <th className="text-left text-[10px] font-bold text-gray-500 uppercase tracking-wider px-3 py-3 hidden md:table-cell">Phone</th>
                  <th className="text-left text-[10px] font-bold text-gray-500 uppercase tracking-wider px-3 py-3 hidden lg:table-cell">Notes</th>
                  <th className="text-right text-[10px] font-bold text-gray-500 uppercase tracking-wider px-3 py-3 w-16">Quotes</th>
                  <th className="w-10 px-2"></th>
                </tr>
              </thead>
              <tbody>
                {filteredEdited.map((v, idx) => {
                  const realIdx = edited.findIndex(e => e.id === v.id)
                  const sug = suggestions[v.name]
                  return (
                    <VendorRow
                      key={v.id}
                      vendor={v}
                      idx={realIdx}
                      updateField={updateField}
                      onDelete={() => handleDelete(v.id)}
                      deleting={deletingId === v.id}
                      expanded={expandedId === v.id}
                      onToggleExpand={() => handleExpand(v)}
                      detail={expandedId === v.id ? vendorDetail : null}
                      detailLoading={expandedId === v.id && detailLoading}
                      suggestion={sug}
                      onApplySuggestion={() => applySuggestion(v.name, sug)}
                    />
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Summary */}
      <div className="text-xs text-gray-600 text-center">
        {searchQuery && filteredEdited.length !== vendors.length
          ? `${filteredEdited.length} of ${vendors.length} vendors`
          : `${vendors.length} vendor${vendors.length !== 1 ? 's' : ''}`}
        {dirty && <span className="ml-2 text-amber-400">• Unsaved changes</span>}
      </div>

      {/* Delete confirmation modal */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setConfirmDelete(null)}>
          <div className="bg-[#12121a] border border-white/10 rounded-2xl shadow-2xl max-w-sm w-full p-6 space-y-4" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold text-white">Delete Vendor</h3>
            <p className="text-sm text-gray-400">
              Delete <span className="text-white font-medium">{edited.find(v => v.id === confirmDelete)?.name}</span> and all their price history? This cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setConfirmDelete(null)}
                className="px-3 py-1.5 text-sm text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteVendor}
                className="px-3 py-1.5 text-sm bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


function VendorRow({ vendor, idx, updateField, onDelete, deleting, expanded, onToggleExpand, detail, detailLoading, suggestion, onApplySuggestion }) {
  return (
    <>
      <tr className="border-b border-white/[0.03] hover:bg-white/[0.02] group transition-colors">
        {/* Name */}
        <td className="px-4 py-2">
          <div className="flex items-center gap-2">
            <button onClick={onToggleExpand} className="text-gray-500 hover:text-gray-300 flex-shrink-0 p-1.5 -m-1.5 rounded-lg hover:bg-white/[0.06] transition-colors" title={expanded ? 'Collapse' : 'Expand vendor details'}>
              {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
            <input
              value={vendor.name || ''}
              onChange={e => updateField(idx, 'name', e.target.value)}
              className="bg-transparent border-0 outline-none text-white font-medium w-full min-w-[120px] focus:bg-white/[0.06] focus:rounded px-1 -mx-1"
            />
          </div>
        </td>
        {/* Contact */}
        <td className="px-3 py-2 hidden sm:table-cell">
          <input
            value={vendor.contact_name || ''}
            onChange={e => updateField(idx, 'contact_name', e.target.value)}
            placeholder="—"
            className="bg-transparent border-0 outline-none text-gray-300 w-full min-w-[100px] placeholder-gray-700 focus:bg-white/[0.06] focus:rounded px-1 -mx-1"
          />
        </td>
        {/* Email */}
        <td className="px-3 py-2">
          <input
            value={vendor.contact_email || ''}
            onChange={e => updateField(idx, 'contact_email', e.target.value)}
            placeholder="—"
            type="email"
            className="bg-transparent border-0 outline-none text-gray-300 w-full min-w-[140px] placeholder-gray-700 focus:bg-white/[0.06] focus:rounded px-1 -mx-1"
          />
        </td>
        {/* Phone */}
        <td className="px-3 py-2 hidden md:table-cell">
          <input
            value={vendor.contact_phone || ''}
            onChange={e => updateField(idx, 'contact_phone', e.target.value)}
            placeholder="—"
            className="bg-transparent border-0 outline-none text-gray-300 w-full min-w-[100px] placeholder-gray-700 focus:bg-white/[0.06] focus:rounded px-1 -mx-1"
          />
        </td>
        {/* Notes */}
        <td className="px-3 py-2 hidden lg:table-cell">
          <input
            value={vendor.notes || ''}
            onChange={e => updateField(idx, 'notes', e.target.value)}
            placeholder="—"
            className="bg-transparent border-0 outline-none text-gray-400 w-full min-w-[120px] placeholder-gray-700 focus:bg-white/[0.06] focus:rounded px-1 -mx-1 text-xs"
          />
        </td>
        {/* Quote count — also clickable to expand */}
        <td className="px-3 py-2 text-right cursor-pointer" onClick={onToggleExpand}>
          <span className="text-xs text-gray-500 hover:text-gray-300 transition-colors">{vendor.price_count || 0}</span>
        </td>
        {/* Delete */}
        <td className="px-2 py-2">
          <button
            onClick={onDelete}
            disabled={deleting}
            className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-all"
          >
            {deleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
          </button>
        </td>
      </tr>

      {/* AI Suggestion banner */}
      {suggestion && (
        <tr className="border-b border-white/[0.03]">
          <td colSpan={7} className="px-4 py-2">
            <div className="flex items-start gap-3 bg-violet-500/10 border border-violet-500/20 rounded-lg px-3 py-2">
              <Sparkles className="w-4 h-4 text-violet-400 mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-violet-300 font-medium">AI Suggestion for {vendor.name}</p>
                <p className="text-xs text-gray-400 mt-1">
                  {suggestion.products && <span className="block">Products: {suggestion.products}</span>}
                  {suggestion.general_email && <span className="block">Email: {suggestion.general_email}</span>}
                  {suggestion.find_rep_url && <span className="block">Find a rep: {suggestion.find_rep_url}</span>}
                  {suggestion.website && <span className="block">Website: {suggestion.website}</span>}
                  {suggestion.notes && <span className="block mt-1">{suggestion.notes}</span>}
                </p>
              </div>
              <button
                onClick={onApplySuggestion}
                className="text-xs bg-violet-500/20 text-violet-300 px-2.5 py-1 rounded-md hover:bg-violet-500/30 transition-colors flex-shrink-0"
              >
                Apply
              </button>
            </div>
          </td>
        </tr>
      )}

      {/* Expanded detail: vendor drill-down */}
      {expanded && (
        <tr className="border-b border-white/[0.03]">
          <td colSpan={7} className="p-0 bg-white/[0.01]">
            {detailLoading ? (
              <div className="flex items-center gap-2 text-gray-500 text-xs py-6 px-6">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading vendor details...
              </div>
            ) : detail ? (
              <div className="px-6 py-4 space-y-4">
                {/* Contact card + KPI stats row */}
                <div className="flex gap-4 flex-wrap">
                  {/* Contact card */}
                  <div className="flex-1 min-w-[240px] bg-white/[0.03] rounded-xl p-4 border border-white/[0.06]">
                    <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-2">Contact</p>
                    <div className="space-y-1.5">
                      <p className="text-sm text-white font-semibold">{vendor.contact_name || '—'}</p>
                      {vendor.contact_title && <p className="text-[11px] text-gray-500">{vendor.contact_title}</p>}
                      {vendor.contact_email && (
                        <a href={`mailto:${vendor.contact_email}`} className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1.5">
                          <Mail className="w-3 h-3" /> {vendor.contact_email}
                        </a>
                      )}
                      {vendor.contact_phone && (
                        <a href={`tel:${vendor.contact_phone}`} className="text-xs text-gray-400 hover:text-gray-300 flex items-center gap-1.5">
                          <Phone className="w-3 h-3" /> {vendor.contact_phone}
                        </a>
                      )}
                      {vendor.notes && <p className="text-[11px] text-gray-500 mt-2 italic">{vendor.notes}</p>}
                    </div>
                  </div>

                  {/* KPI stats */}
                  {detail.stats && (
                    <div className="flex gap-3 flex-wrap">
                      <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06] min-w-[100px] text-center">
                        <p className="text-lg font-bold text-white">{detail.stats.total_products_quoted}</p>
                        <p className="text-[10px] text-gray-500 uppercase">Products Quoted</p>
                      </div>
                      <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06] min-w-[100px] text-center">
                        <p className="text-lg font-bold text-white">{detail.stats.total_requests}</p>
                        <p className="text-[10px] text-gray-500 uppercase">Quotes Requested</p>
                      </div>
                      <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06] min-w-[100px] text-center">
                        <p className={`text-lg font-bold ${detail.stats.response_rate != null ? (detail.stats.response_rate >= 80 ? 'text-emerald-400' : detail.stats.response_rate >= 50 ? 'text-amber-400' : 'text-red-400') : 'text-gray-600'}`}>
                          {detail.stats.response_rate != null ? `${detail.stats.response_rate}%` : '—'}
                        </p>
                        <p className="text-[10px] text-gray-500 uppercase">Response Rate</p>
                      </div>
                      <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06] min-w-[100px] text-center">
                        <p className="text-lg font-bold text-white">
                          {detail.stats.avg_response_days != null ? `${detail.stats.avg_response_days}d` : '—'}
                        </p>
                        <p className="text-[10px] text-gray-500 uppercase">Avg Response</p>
                      </div>
                    </div>
                  )}
                </div>

                {/* Product categories */}
                {detail.categories?.length > 0 && (
                  <div>
                    <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-2 flex items-center gap-1">
                      <Package className="w-3 h-3" /> Products They Supply
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {detail.categories.map((cat, i) => (
                        <span key={i} className="text-[11px] bg-white/[0.06] text-gray-300 px-2.5 py-1 rounded-lg border border-white/[0.06] flex items-center gap-1.5">
                          {cat.product_normalized || 'Other'}
                          <span className="text-gray-500">×{cat.count}</span>
                          {cat.avg_price > 0 && <span className="text-emerald-400 font-mono text-[10px]">~${cat.avg_price}</span>}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Two-column: Price History + Quote Requests */}
                <div className="flex gap-4 flex-wrap">
                  {/* Price history by job */}
                  <div className="flex-1 min-w-[300px]">
                    <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-2 flex items-center gap-1">
                      <TrendingUp className="w-3 h-3" /> Price History ({detail.prices?.length || 0} products)
                    </p>
                    {detail.prices?.length > 0 ? (
                      <div className="max-h-52 overflow-y-auto rounded-lg border border-white/[0.06] bg-white/[0.02]">
                        <table className="w-full text-xs">
                          <thead className="sticky top-0 bg-[#12121a]">
                            <tr className="text-gray-600 border-b border-white/[0.06]">
                              <th className="text-left py-1.5 pl-3 pr-2 font-medium">Product</th>
                              <th className="text-right py-1.5 px-2 font-medium">Price</th>
                              <th className="text-left py-1.5 px-2 font-medium">Unit</th>
                              <th className="text-left py-1.5 px-2 font-medium">Job</th>
                              <th className="text-left py-1.5 pl-2 pr-3 font-medium">Date</th>
                            </tr>
                          </thead>
                          <tbody>
                            {detail.prices.map((p, i) => (
                              <tr key={i} className="border-t border-white/[0.03] text-gray-400 hover:bg-white/[0.02]">
                                <td className="py-1.5 pl-3 pr-2 text-gray-300 max-w-[180px] truncate">{p.product_name}</td>
                                <td className="py-1.5 px-2 text-right text-emerald-400 font-mono">
                                  ${(p.unit_price || 0).toFixed(2)}
                                </td>
                                <td className="py-1.5 px-2">{p.unit || '—'}</td>
                                <td className="py-1.5 px-2 text-gray-500 max-w-[120px] truncate">{p.job_name || '—'}</td>
                                <td className="py-1.5 pl-2 pr-3 text-gray-500">{(p.created_at || '').slice(0, 10)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-xs text-gray-600 py-3 px-3 bg-white/[0.02] rounded-lg border border-white/[0.06]">No quotes uploaded from this vendor yet.</p>
                    )}
                  </div>

                  {/* Quote request history */}
                  <div className="w-[320px] flex-shrink-0">
                    <p className="text-[10px] font-bold text-gray-600 uppercase tracking-wider mb-2 flex items-center gap-1">
                      <FileText className="w-3 h-3" /> Quote Requests ({detail.quote_requests?.length || 0})
                    </p>
                    {detail.quote_requests?.length > 0 ? (
                      <div className="space-y-1.5 max-h-52 overflow-y-auto">
                        {detail.quote_requests.map((qr, i) => {
                          const status = qr.received_at ? 'received' : qr.sent_at ? 'sent' : 'draft'
                          const daysSince = qr.sent_at ? Math.floor((Date.now() - new Date(qr.sent_at).getTime()) / 86400000) : null
                          const responseTime = (qr.sent_at && qr.received_at) ?
                            Math.round((new Date(qr.received_at).getTime() - new Date(qr.sent_at).getTime()) / 86400000 * 10) / 10 : null
                          return (
                            <div key={i} className="flex items-center gap-2 text-xs bg-white/[0.02] rounded-lg px-3 py-2 border border-white/[0.06]">
                              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                                status === 'received' ? 'bg-emerald-400' : status === 'sent' ? (daysSince > 3 ? 'bg-amber-400' : 'bg-blue-400') : 'bg-gray-500'
                              }`} />
                              <div className="flex-1 min-w-0">
                                <p className="text-gray-300 truncate">{qr.job_name || 'Unknown Job'}</p>
                                <p className="text-[10px] text-gray-500">
                                  {status === 'received' && responseTime != null && `Responded in ${responseTime}d`}
                                  {status === 'sent' && daysSince != null && (daysSince > 3 ? `⚠ ${daysSince}d, no response` : `Sent ${daysSince}d ago`)}
                                  {status === 'draft' && 'Draft — not sent'}
                                </p>
                              </div>
                              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                                status === 'received' ? 'text-emerald-400 bg-emerald-500/10' :
                                status === 'sent' ? (daysSince > 3 ? 'text-amber-400 bg-amber-500/10' : 'text-blue-400 bg-blue-500/10') :
                                'text-gray-500 bg-gray-500/10'
                              }`}>
                                {status === 'received' ? 'Received' : status === 'sent' ? (daysSince > 3 ? 'Overdue' : 'Waiting') : 'Draft'}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <p className="text-xs text-gray-600 py-3 px-3 bg-white/[0.02] rounded-lg border border-white/[0.06]">No quote requests for this vendor yet.</p>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-xs text-gray-600 py-4 px-6">No data available for this vendor.</p>
            )}
          </td>
        </tr>
      )}
    </>
  )
}
