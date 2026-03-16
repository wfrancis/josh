import { useState, useMemo } from 'react'
import { Copy, Check, Mail, Package, ChevronDown, ChevronUp } from 'lucide-react'

/**
 * QuoteRequest — generates copyable vendor quote request text from unpriced materials.
 *
 * Props:
 *   job: { project_name, gc_name, architect, designer, address, city, state, zip }
 *   materials: all job materials (component filters to unpriced)
 *   onClose: callback to close the panel
 */
export default function QuoteRequest({ job, materials, onClose, preSelectedIds = null }) {
  const [copied, setCopied] = useState(false)
  const [selectedIds, setSelectedIds] = useState(preSelectedIds ? new Set(preSelectedIds) : null) // null = all selected

  // Filter to unpriced materials
  const unpricedMaterials = useMemo(() =>
    (materials || []).filter(m => !m.unit_price || m.unit_price === 0),
    [materials]
  )

  // Initialize selection on first render
  const selected = selectedIds ?? new Set(unpricedMaterials.map(m => m.id))

  const toggleItem = (id) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedIds(next)
  }

  const toggleAll = () => {
    if (selected.size === unpricedMaterials.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(unpricedMaterials.map(m => m.id)))
    }
  }

  const selectedMaterials = unpricedMaterials.filter(m => selected.has(m.id))

  // Generate the quote request text
  const generateText = () => {
    const lines = []

    lines.push(`Project: ${job.project_name || ''}`)
    if (job.architect) lines.push(`Architect: ${job.architect}`)
    if (job.designer) lines.push(`Designer: ${job.designer}`)

    const locationParts = [job.address, job.city, job.state, job.zip].filter(Boolean)
    if (locationParts.length) lines.push(`Location: ${locationParts.join(', ')}`)

    if (job.gc_name) lines.push(`GC: ${job.gc_name}`)

    lines.push('')
    lines.push('We are bidding the above project and need pricing on the following materials:')
    lines.push('')

    for (const m of selectedMaterials) {
      const parts = [m.item_code, m.description].filter(Boolean)
      let line = parts.join(' - ')
      const qty = m.installed_qty || m.order_qty || 0
      if (qty) line += ` — ${Math.round(qty * 100) / 100} ${m.unit || ''}`
      lines.push(`• ${line}`)
    }

    lines.push('')
    lines.push('Please include unit pricing, freight, and lead times.')
    lines.push('Thank you!')

    return lines.join('\n')
  }

  const requestText = generateText()

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(requestText)
      setCopied(true)
      setTimeout(() => setCopied(false), 3000)
    } catch {
      // Fallback for older browsers
      const ta = document.createElement('textarea')
      ta.value = requestText
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 3000)
    }
  }

  if (unpricedMaterials.length === 0) {
    return (
      <div className="glass-card p-6 text-center">
        <Check className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
        <p className="text-sm text-gray-300">All materials are priced!</p>
        {onClose && (
          <button onClick={onClose} className="mt-3 text-xs text-gray-500 hover:text-gray-300 transition-colors">
            Close
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Mail className="w-4 h-4 text-si-bright" />
          <h3 className="text-sm font-bold text-white">Generate Quote Request</h3>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-300 transition-colors">
            Close
          </button>
        )}
      </div>

      <p className="text-xs text-gray-500">
        Select materials to include, then copy the text below and paste into your email.
      </p>

      {/* Material Selection */}
      <div className="rounded-lg border border-white/[0.06] overflow-hidden">
        {/* Select all header */}
        <div className="flex items-center gap-3 px-3 py-2 bg-white/[0.03] border-b border-white/[0.06]">
          <input
            type="checkbox"
            checked={selected.size === unpricedMaterials.length}
            onChange={toggleAll}
            className="rounded border-gray-600 bg-transparent text-si-bright focus:ring-si-bright/40 focus:ring-offset-0"
          />
          <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">
            {selected.size} of {unpricedMaterials.length} selected
          </span>
        </div>

        {/* Material list */}
        <div className="max-h-48 overflow-y-auto">
          {unpricedMaterials.map(m => (
            <label
              key={m.id}
              className="flex items-center gap-3 px-3 py-2 hover:bg-white/[0.02] transition-colors cursor-pointer border-b border-white/[0.03] last:border-b-0"
            >
              <input
                type="checkbox"
                checked={selected.has(m.id)}
                onChange={() => toggleItem(m.id)}
                className="rounded border-gray-600 bg-transparent text-si-bright focus:ring-si-bright/40 focus:ring-offset-0"
              />
              <div className="flex-1 min-w-0">
                <span className="text-xs text-gray-300 truncate block">
                  {[m.item_code, m.description].filter(Boolean).join(' - ')}
                </span>
              </div>
              <span className="text-[10px] text-gray-500 flex-shrink-0">
                {Math.round((m.installed_qty || m.order_qty || 0) * 100) / 100 || '?'} {m.unit || ''}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Generated Text Preview */}
      {selectedMaterials.length > 0 && (
        <>
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-4">
            <pre className="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
              {requestText}
            </pre>
          </div>

          <button
            onClick={handleCopy}
            className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
              copied
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                : 'bg-gradient-to-b from-si-orange to-orange-600 text-white shadow-[0_1px_2px_rgba(0,0,0,0.4)] hover:from-orange-500 hover:to-orange-700'
            }`}
          >
            {copied ? (
              <><Check className="w-4 h-4" /> Copied to Clipboard</>
            ) : (
              <><Copy className="w-4 h-4" /> Copy Quote Request</>
            )}
          </button>
        </>
      )}
    </div>
  )
}
