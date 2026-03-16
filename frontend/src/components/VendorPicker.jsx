import { useState, useEffect, useRef } from 'react'
import { ChevronDown, Plus, Building2 } from 'lucide-react'

/**
 * VendorPicker — autocomplete dropdown for selecting/creating vendors.
 *
 * Props:
 *   value: current vendor name string
 *   vendors: array of vendor objects from api.listVendors()
 *   onChange: (vendorName, vendorObj|null) => void
 *   onCreateVendor: (name) => Promise<vendor> (optional)
 *   placeholder: string
 *   className: extra classes
 */
export default function VendorPicker({ value = '', vendors = [], onChange, onCreateVendor, placeholder = 'Select vendor...', className = '' }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef(null)
  const inputRef = useRef(null)

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filtered = vendors.filter(v =>
    v.name.toLowerCase().includes((query || '').toLowerCase())
  )

  const handleSelect = (vendor) => {
    onChange(vendor.name, vendor)
    setQuery('')
    setOpen(false)
  }

  const handleCreate = async () => {
    const name = query.trim()
    if (!name) return
    if (onCreateVendor) {
      try {
        const vendor = await onCreateVendor(name)
        onChange(vendor.name, vendor)
      } catch (err) {
        console.error('Create vendor failed:', err)
      }
    } else {
      onChange(name, null)
    }
    setQuery('')
    setOpen(false)
  }

  const displayValue = value || ''
  const exactMatch = filtered.some(v => v.name.toLowerCase() === (query || '').toLowerCase())

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => { setOpen(!open); setTimeout(() => inputRef.current?.focus(), 50) }}
        className="w-full flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-left hover:bg-white/[0.06] transition-colors"
      >
        <Building2 className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        <span className={displayValue ? 'text-white flex-1 truncate' : 'text-gray-500 flex-1'}>
          {displayValue || placeholder}
        </span>
        <ChevronDown className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-[200px] bg-[#1a1a2e] border border-white/10 rounded-xl shadow-2xl overflow-hidden">
          {/* Search */}
          <div className="p-2 border-b border-white/[0.06]">
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search vendors..."
              className="w-full bg-white/[0.06] border-0 rounded-lg px-3 py-1.5 text-sm text-white placeholder-gray-500 outline-none focus:ring-1 focus:ring-si-accent/40"
              onKeyDown={e => {
                if (e.key === 'Enter' && !exactMatch && query.trim()) {
                  handleCreate()
                } else if (e.key === 'Enter' && filtered.length === 1) {
                  handleSelect(filtered[0])
                } else if (e.key === 'Escape') {
                  setOpen(false)
                }
              }}
            />
          </div>

          {/* Results */}
          <div className="max-h-48 overflow-y-auto">
            {filtered.map(v => (
              <button
                key={v.id}
                onClick={() => handleSelect(v)}
                className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-white/[0.04] transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white truncate">{v.name}</p>
                  {(v.contact_email || v.contact_name) && (
                    <p className="text-[10px] text-gray-500 truncate">
                      {[v.contact_name, v.contact_email].filter(Boolean).join(' · ')}
                    </p>
                  )}
                </div>
                {v.price_count > 0 && (
                  <span className="text-[10px] text-gray-600">{v.price_count} quotes</span>
                )}
              </button>
            ))}

            {filtered.length === 0 && !query && (
              <p className="px-3 py-3 text-xs text-gray-500 text-center">No vendors yet</p>
            )}

            {/* Create new */}
            {query.trim() && !exactMatch && (
              <button
                onClick={handleCreate}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.04] transition-colors border-t border-white/[0.06]"
              >
                <Plus className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-sm text-emerald-400">Add "{query.trim()}"</span>
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
