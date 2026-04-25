import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Calculator, Database, Info, ShieldCheck, X } from 'lucide-react'

function isPlainObject(value) {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

function getNested(obj, path) {
  if (!obj || !path) return null
  return String(path).split('.').reduce((acc, key) => (acc == null ? null : acc[key]), obj)
}

function stringifyValue(value) {
  if (value == null || value === '') return null
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function findTraceInRecord(record, field) {
  if (!record || !field) return null

  const directPaths = [
    `audit.${field}`,
    `audit_trace.${field}`,
    `audit_traces.${field}`,
    `traces.${field}`,
    `why.${field}`,
    `explain.${field}`,
  ]
  for (const path of directPaths) {
    const hit = getNested(record, path)
    if (hit) return hit
  }

  const arrays = [record.audit, record.audit_trace, record.audit_traces, record.traces, record.audit_events, record.events]
  for (const maybeArray of arrays) {
    if (!Array.isArray(maybeArray)) continue
    const hit = maybeArray.find((entry) => entry?.field === field || entry?.target === field || entry?.key === field)
    if (hit) return hit
  }

  return null
}

export function resolveAuditTrace({ record, field, external, bundleIndex, bundleName, lineIndex }) {
  const local = findTraceInRecord(record, field)
  if (local) return local

  if (!external || !field) return null

  const matchesField = (entry) => entry?.output_field === field || entry?.field === field ||
    entry?.target === field || entry?.key === field
  const matchesBundle = (entry) => bundleName
    ? entry?.entity_key === bundleName || entry?.bundle_name === bundleName || entry?.bundle === bundleName
    : true

  if (Array.isArray(external.traces)) {
    const descriptiveLineKey = record?.sundry_name || record?.labor_description
    const stableLineKey = record?.entity_key || record?.item_code || record?.material_id
    const lineKey = descriptiveLineKey || stableLineKey

    if (lineIndex != null) {
      const indexedHit = [...external.traces].reverse().find((entry) => {
        if (!matchesField(entry)) return false
        const inputs = entry?.inputs || {}
        if (inputs.line_index !== lineIndex) return false
        if (bundleIndex != null && inputs.bundle_index !== bundleIndex) return false
        const entryKey = String(entry.entity_key || '')
        if (descriptiveLineKey && entryKey.includes(String(descriptiveLineKey))) return true
        if (stableLineKey && entryKey.includes(String(stableLineKey))) return true
        if (record?.id != null && String(entry.entity_id) === String(record.id)) return true
        if (record?.material_id != null && String(entry.entity_id) === String(record.material_id)) return true
        return false
      })
      if (indexedHit) return indexedHit
    }

    if (!bundleName && !lineKey && record?.id == null && record?.material_id == null) {
      const proposalHit = [...external.traces].reverse().find((entry) => {
        const entityType = String(entry?.entity_type || '').toLowerCase()
        const entityKey = String(entry?.entity_key || '').toLowerCase()
        return matchesField(entry) &&
          (entityType === 'proposal' || entityType === 'total' || entityType === 'totals' ||
            entityKey === 'proposal' || entityKey === 'totals' || entityKey === 'summary')
      })
      if (proposalHit) return proposalHit
    }

    const directHit = [...external.traces].reverse().find((entry) => {
      if (!matchesField(entry)) return false
      const entryKey = String(entry.entity_key || '')
      if (descriptiveLineKey && entryKey.includes(String(descriptiveLineKey))) {
        if (record?.material_id == null || entryKey.includes(String(record.material_id)) || String(entry.entity_id) === String(record.material_id)) return true
      }
      if (stableLineKey && entryKey.includes(String(stableLineKey))) return true
      if (record?.id != null && String(entry.entity_id) === String(record.id)) return true
      if (record?.material_id != null && String(entry.entity_id) === String(record.material_id)) return true
      return lineIndex == null && !!bundleName && matchesBundle(entry)
    })
    if (directHit) return directHit
  }

  const bundleBuckets = [
    external.bundles?.[bundleIndex],
    bundleName ? external.by_bundle?.[bundleName] : null,
    bundleName ? external.bundle_traces?.[bundleName] : null,
  ].filter(Boolean)

  for (const bucket of bundleBuckets) {
    const hit = findTraceInRecord(bucket, field)
    if (hit) return hit
    if (lineIndex != null) {
      const lineBuckets = [bucket.materials?.[lineIndex], bucket.sundry_items?.[lineIndex], bucket.labor_items?.[lineIndex]]
      for (const lineBucket of lineBuckets) {
        const lineHit = findTraceInRecord(lineBucket, field)
        if (lineHit) return lineHit
      }
    }
  }

  const globalBuckets = [external.fields, external.totals, external.audit, external.audit_trace, external.audit_traces]
  for (const bucket of globalBuckets) {
    const hit = isPlainObject(bucket) ? bucket[field] : null
    if (hit) return hit
  }

  if (Array.isArray(external.events)) {
    return external.events.find((entry) =>
      matchesField(entry) &&
      (bundleIndex == null || entry?.bundle_index === bundleIndex || entry?.bundleIndex === bundleIndex)
    ) || null
  }

  return null
}

function normalizeTrace(trace) {
  if (!trace) return null
  if (typeof trace === 'string') return { summary: trace }
  if (Array.isArray(trace)) return { events: trace }
  return trace
}

function DetailRow({ icon: Icon, label, value }) {
  const text = stringifyValue(value)
  if (!text) return null
  return (
    <div className="grid grid-cols-[72px_1fr] gap-3">
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-gray-600">
        {Icon && <Icon className="w-3 h-3" />}
        {label}
      </div>
      <div className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap break-words">{text}</div>
    </div>
  )
}

export default function AuditTraceButton({ trace, label = 'Audit trace', className = '' }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState(null)
  const buttonRef = useRef(null)
  const normalized = useMemo(() => normalizeTrace(trace), [trace])
  const hasTrace = !!normalized

  useEffect(() => {
    if (!open) return
    const updatePosition = () => {
      const rect = buttonRef.current?.getBoundingClientRect()
      if (!rect) return
      setPosition({
        top: Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - 260)),
        left: Math.max(12, Math.min(Math.max(12, rect.left - 300), window.innerWidth - 340)),
      })
    }
    const closeOnKey = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    document.addEventListener('keydown', closeOnKey)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
      document.removeEventListener('keydown', closeOnKey)
    }
  }, [open])

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={(event) => {
          event.stopPropagation()
          setOpen((value) => !value)
        }}
        className={`inline-flex items-center justify-center rounded-md p-1 transition-colors ${
          hasTrace
            ? 'text-blue-300 hover:text-white hover:bg-blue-500/15'
            : 'text-gray-600 hover:text-gray-400 hover:bg-white/[0.04]'
        } ${className}`}
        title={hasTrace ? `Show ${label}` : 'No audit trace captured yet'}
      >
        <Info className="w-3.5 h-3.5" />
      </button>
      {open && position && createPortal(
        <div
          className="fixed z-[80] w-[328px] rounded-lg border border-white/[0.1] bg-[#0d1429] shadow-2xl"
          style={{ top: position.top, left: position.left }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
              <ShieldCheck className={`w-4 h-4 flex-shrink-0 ${hasTrace ? 'text-blue-300' : 'text-gray-600'}`} />
              <span className="text-xs font-bold text-white truncate">{label}</span>
            </div>
            <button onClick={() => setOpen(false)} className="p-1 rounded-md text-gray-600 hover:text-gray-300 hover:bg-white/[0.04]">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          {hasTrace ? (
            <div className="max-h-80 overflow-y-auto px-3 py-3 space-y-3">
              <DetailRow icon={Calculator} label="Formula" value={normalized.formula || normalized.calculation || normalized.expression} />
              <DetailRow label="Result" value={normalized.result ?? normalized.result_value} />
              <DetailRow icon={Database} label="Source" value={normalized.source || normalized.source_name || normalized.source_ref} />
              <DetailRow icon={ShieldCheck} label="Rule" value={normalized.rule || normalized.rule_id || normalized.rule_name} />
              <DetailRow label="Why" value={normalized.summary || normalized.reason || normalized.explanation || normalized.note} />
              <DetailRow label="Inputs" value={normalized.inputs || normalized.values} />
              {Array.isArray(normalized.events) && normalized.events.length > 0 && (
                <div className="space-y-1.5">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Events</div>
                  <div className="space-y-1">
                    {normalized.events.slice(0, 8).map((event, index) => (
                      <div key={index} className="rounded-md border border-white/[0.05] bg-white/[0.03] px-2 py-1.5 text-xs text-gray-300 leading-relaxed">
                        {stringifyValue(event.summary || event.message || event.reason || event)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="px-3 py-5 text-center text-xs text-gray-500">
              No audit trace captured yet.
            </div>
          )}
        </div>,
        document.body
      )}
    </>
  )
}
