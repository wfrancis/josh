import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertTriangle, CheckCircle2, Database, Loader2, PlayCircle,
  RefreshCw, Save, ShieldCheck, X, XCircle
} from 'lucide-react'
import { api } from '../api'

const TOTAL_FIELDS = [
  ['grand_total', 'Grand Total'],
  ['subtotal', 'Subtotal'],
  ['tax_amount', 'Tax'],
  ['gpm_profit', 'Profit'],
  ['gpm_labor', 'Labor GPM'],
  ['gpm_material', 'Material GPM'],
]

function money(value) {
  const n = Number(value || 0)
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function moneyOrDash(value) {
  if (value == null || value === '') return '-'
  return money(value)
}

function shortMoney(value) {
  const n = Number(value || 0)
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

function parseMoney(value) {
  if (value == null || value === '') return null
  const n = Number(String(value).replace(/[$,]/g, ''))
  return Number.isFinite(n) ? n : null
}

function statusClass(status) {
  const key = String(status || '').toLowerCase()
  if (key === 'pass' || key === 'golden_verified') return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
  if (key === 'metadata_changed' || key === 'metadata_only') return 'bg-blue-500/10 text-blue-300 border-blue-500/20'
  if (key === 'warn' || key === 'stale' || key === 'drift') return 'bg-amber-500/10 text-amber-300 border-amber-500/20'
  if (key === 'fail') return 'bg-red-500/10 text-red-300 border-red-500/20'
  if (key === 'incomparable') return 'bg-purple-500/10 text-purple-300 border-purple-500/20'
  return 'bg-white/[0.04] text-gray-400 border-white/[0.08]'
}

function StatusIcon({ status }) {
  const key = String(status || '').toLowerCase()
  if (key === 'pass' || key === 'golden_verified') return <CheckCircle2 className="w-4 h-4" />
  if (key === 'fail') return <XCircle className="w-4 h-4" />
  return <AlertTriangle className="w-4 h-4" />
}

function StatusBadge({ status }) {
  const label = status === 'not_replayed'
    ? 'not replayed'
    : status === 'metadata_only'
      ? 'metadata only'
      : String(status || 'not replayed').replaceAll('_', ' ')
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] font-bold uppercase ${statusClass(status)}`}>
      <StatusIcon status={status} />
      {label}
    </span>
  )
}

function TotalsTable({ replay, rowsKey = 'totals', title = 'Accepted Proposal Comparison' }) {
  const rows = replay?.diff?.[rowsKey] || []
  if (!rows.length) return null
  return (
    <div>
      <h3 className="mb-2 text-xs font-bold uppercase text-gray-500">{title}</h3>
      <div className="overflow-x-auto rounded-lg border border-white/[0.06]">
        <table className="w-full text-sm">
        <thead className="bg-white/[0.03] text-[10px] uppercase text-gray-500">
          <tr>
            <th className="px-3 py-2 text-left font-bold">Total</th>
            <th className="px-3 py-2 text-right font-bold">Target</th>
            <th className="px-3 py-2 text-right font-bold">Replay</th>
            <th className="px-3 py-2 text-right font-bold">Delta</th>
            <th className="px-3 py-2 text-left font-bold">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.04]">
          {rows.map(row => (
            <tr key={row.field} className="text-gray-300">
              <td className="px-3 py-2">{row.field.replace(/_/g, ' ')}</td>
              <td className="px-3 py-2 text-right tabular-nums">{shortMoney(row.target)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{shortMoney(row.actual)}</td>
              <td className={`px-3 py-2 text-right tabular-nums ${Number(row.delta) === 0 ? 'text-gray-500' : Number(row.delta) > 0 ? 'text-amber-300' : 'text-blue-300'}`}>
                {shortMoney(row.delta)}
              </td>
              <td className="px-3 py-2">
                <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${statusClass(row.status)}`}>
                  {row.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
        </table>
      </div>
    </div>
  )
}

function BundleDeltas({ replay }) {
  const rows = (replay?.diff?.bundles || []).filter(row => row.status !== 'pass' || Number(row.delta || 0) !== 0).slice(0, 6)
  if (!rows.length) return null
  return (
    <div className="rounded-lg border border-white/[0.06] p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase text-gray-500">Bundle Deltas</h3>
        <span className="text-[10px] text-gray-600">largest first</span>
      </div>
      <div className="space-y-2">
        {rows.map(row => (
          <div key={row.bundle_name} className="flex items-center gap-3 text-sm">
            <span className="min-w-0 flex-1 truncate text-gray-300">{row.bundle_name}</span>
            <span className="tabular-nums text-gray-500">{shortMoney(row.target_total)}</span>
            <span className={Number(row.delta || 0) > 0 ? 'tabular-nums text-amber-300' : 'tabular-nums text-blue-300'}>
              {shortMoney(row.delta || 0)}
            </span>
            <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${statusClass(row.status)}`}>
              {row.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function JRBundleDeltas({ replay }) {
  const rows = replay?.diff?.jr_bundles || []
  if (!rows.length) return null
  const visible = rows.filter(row => row.status !== 'pass' || Number(row.delta || 0) !== 0).slice(0, 15)
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-bold uppercase text-gray-500">Job Runner Bundle Delta</h3>
        <span className="text-[10px] font-semibold uppercase text-gray-600">{rows.length} targets / largest first</span>
      </div>
      {visible.length > 0 ? (
        <div className="max-h-80 overflow-auto border-y border-white/[0.06]">
          <table className="w-full min-w-[620px] text-sm">
            <thead className="sticky top-0 bg-[#111827] text-[10px] uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2 text-left font-bold">Bundle</th>
                <th className="px-3 py-2 text-right font-bold">JR</th>
                <th className="px-3 py-2 text-right font-bold">Accepted replay</th>
                <th className="px-3 py-2 text-right font-bold">Delta</th>
                <th className="px-3 py-2 text-left font-bold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {visible.map(row => (
                <tr key={row.bundle_name} className="text-gray-300">
                  <td className="px-3 py-2">
                    <p className="font-medium text-gray-200">{row.jr_label || row.bundle_name}</p>
                    {row.jr_label && row.jr_label !== row.bundle_name && <p className="mt-0.5 text-[11px] text-gray-600">{row.bundle_name}</p>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{shortMoney(row.target_total)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.actual_total == null ? '-' : shortMoney(row.actual_total)}</td>
                  <td className={`px-3 py-2 text-right font-semibold tabular-nums ${Number(row.delta || 0) > 0 ? 'text-amber-300' : 'text-blue-300'}`}>
                    {row.delta == null ? '-' : shortMoney(row.delta)}
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={row.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex items-center gap-2 border-y border-emerald-500/15 py-3 text-sm text-emerald-200">
          <CheckCircle2 className="h-4 w-4" />
          Every stored JR bundle target matches this replay.
        </div>
      )}
    </div>
  )
}

function StructuralIssues({ replay }) {
  const rows = replay?.diff?.structural || []
  if (!rows.length) return null
  return (
    <div className="rounded-lg border border-red-500/20 bg-red-500/[0.04] p-3">
      <h3 className="mb-2 text-xs font-bold uppercase text-red-300">Structural Issues</h3>
      <div className="space-y-1.5">
        {rows.slice(0, 5).map((row, idx) => (
          <p key={`${row.check}-${idx}`} className="text-sm text-red-200">{row.message || row.check}</p>
        ))}
      </div>
    </div>
  )
}

function DriftRows({ replay }) {
  const rows = replay?.diff?.drift || []
  if (!rows.length) return null
  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] p-3">
      <h3 className="mb-2 text-xs font-bold uppercase text-amber-300">Rule / Rate Drift</h3>
      <div className="space-y-1.5">
        {rows.map(row => (
          <p key={row.check} className="text-sm text-amber-100">
            <span className="font-semibold">
              {row.classification === 'metadata_only' ? 'Metadata only: ' : 'Calculation behavior: '}
            </span>
            {row.message || row.check}
          </p>
        ))}
      </div>
    </div>
  )
}

function EngineReplayNotice({ replay }) {
  const engine = replay?.diff?.engine
  if (!engine || engine.status === 'pass') return null
  const totalDeltas = (engine.totals || []).filter(row => row.status !== 'pass')
  const bundleDeltas = (engine.bundles || []).filter(row => row.status !== 'pass' || Number(row.delta || 0) !== 0).slice(0, 3)
  const structural = engine.structural || []
  return (
    <div className="rounded-lg border border-blue-500/20 bg-blue-500/[0.04] p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-xs font-bold uppercase text-blue-300">Engine Replay Before Accepted Edits</h3>
        <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${statusClass(engine.status)}`}>
          {engine.status}
        </span>
      </div>
      <div className="space-y-1.5 text-sm text-blue-100">
        {totalDeltas.slice(0, 3).map(row => (
          <p key={row.field}>{row.field.replace(/_/g, ' ')} moved {shortMoney(row.delta)}</p>
        ))}
        {bundleDeltas.map(row => (
          <p key={row.bundle_name}>{row.bundle_name}: {shortMoney(row.delta || 0)}</p>
        ))}
        {structural.slice(0, 3).map((row, idx) => (
          <p key={`${row.check}-${idx}`}>{row.message || row.check}</p>
        ))}
      </div>
    </div>
  )
}

export default function ReproducibilityPanel({ jobId, onConfidenceChange }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [runningMode, setRunningMode] = useState(null)
  const [selectedMode, setSelectedMode] = useState('baseline')
  const [showCapture, setShowCapture] = useState(false)
  const [bundleTargets, setBundleTargets] = useState({})
  const [form, setForm] = useState({
    jr_quote_id: '',
    reviewer_name: '',
    grand_total: '',
    subtotal: '',
    tax_amount: '',
    gpm_profit: '',
    gpm_labor: '',
    gpm_material: '',
    notes: '',
  })

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setData(await api.getReproducibility(jobId))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setBundleTargets({})
    load()
  }, [jobId])

  useEffect(() => {
    if (!showCapture) return undefined
    const previousOverflow = document.body.style.overflow
    const handleKeyDown = event => {
      if (event.key === 'Escape' && !saving) setShowCapture(false)
    }
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [showCapture, saving])

  const golden = data?.golden_job
  const activeReplays = data?.active_version_replays || []
  const baselineReplay = data?.baseline_replay || activeReplays.find(replay => replay.mode === 'baseline')
  const currentReplay = data?.current_replay || activeReplays.find(replay => replay.mode === 'current')
  const latest = (selectedMode === 'baseline' ? baselineReplay : currentReplay) || data?.latest_replay
  const acceptedBundles = data?.accepted_bundles || []
  const enteredBundleTargetCount = acceptedBundles.filter(bundle => parseMoney(bundleTargets[bundle.bundle_name]) != null).length
  const canCapture = useMemo(() => (
    (parseMoney(form.grand_total) || 0) > 0
    && form.jr_quote_id.trim().length > 0
    && form.reviewer_name.trim().length > 0
  ), [form.grand_total, form.jr_quote_id, form.reviewer_name])

  function startNewVersion() {
    const targets = golden?.target_totals || {}
    setBundleTargets(Object.fromEntries(
      (golden?.target_bundles || []).map(bundle => [bundle.bundle_name, bundle.target_total ?? ''])
    ))
    setForm({
      jr_quote_id: golden?.jr_quote_id || '',
      reviewer_name: golden?.reviewer_name || '',
      grand_total: targets.grand_total ?? '',
      subtotal: targets.subtotal ?? '',
      tax_amount: targets.tax_amount ?? '',
      gpm_profit: targets.gpm_profit ?? '',
      gpm_labor: targets.gpm_labor ?? '',
      gpm_material: targets.gpm_material ?? '',
      notes: '',
    })
    setShowCapture(true)
  }

  async function captureBaseline() {
    const target_totals = {}
    TOTAL_FIELDS.forEach(([key]) => {
      const value = parseMoney(form[key])
      if (value != null) target_totals[key] = value
    })
    const target_bundles = acceptedBundles.flatMap(bundle => {
      const value = parseMoney(bundleTargets[bundle.bundle_name])
      return value == null ? [] : [{ bundle_name: bundle.bundle_name, target_total: value }]
    })
    setSaving(true)
    setError(null)
    try {
      await api.captureGoldenBaseline(jobId, {
        jr_quote_id: form.jr_quote_id,
        reviewer_name: form.reviewer_name,
        target_totals,
        target_bundles,
        notes: form.notes,
      })
      setShowCapture(false)
      await load()
      onConfidenceChange?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function runReplay(mode) {
    setRunningMode(mode)
    setSelectedMode(mode)
    setError(null)
    try {
      await api.runGoldenReplay(jobId, mode)
      await load()
      onConfidenceChange?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setRunningMode(null)
    }
  }

  return (
    <div className="glass-card p-4 sm:p-5 mb-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-cyan-500/15 bg-cyan-500/10">
          <ShieldCheck className="h-5 w-5 text-cyan-300" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-bold text-white">Reproducibility</h2>
            {golden ? <StatusBadge status={data?.comparison_status || latest?.status || 'not_replayed'} /> : (
              <span className="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] font-bold uppercase text-amber-300">
                No baseline
              </span>
            )}
          </div>
          {golden && (
            <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-gray-500">
              <span>JR {golden.jr_quote_id || '-'}</span>
              <span>Baseline v{golden.version_number || '-'}</span>
              <span>Ruleset v{golden.ruleset_version || '-'}</span>
              <span>{golden.target_bundles?.length || 0} JR bundle targets</span>
              {golden.reviewer_name && <span>Reviewed by {golden.reviewer_name}</span>}
              <span className="font-mono">{String(golden.source_fingerprint || '').slice(0, 10)}</span>
            </div>
          )}
          {golden && data?.live_source_matches_baseline === false && (
            <p className="mt-2 text-xs font-medium text-amber-300">
              The live job changed after this baseline was captured. Capture a new version after the estimator accepts the changes.
            </p>
          )}
        </div>
        <button onClick={load} disabled={loading} className="btn-ghost p-2" title="Refresh reproducibility">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        </button>
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="p-1 text-red-300/60 hover:text-red-200" title="Dismiss error">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {!loading && !golden && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <Database className="h-4 w-4 text-amber-300" />
            <span>JR baseline not captured</span>
          </div>
          <button
            type="button"
            onClick={startNewVersion}
            className="btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm"
          >
            <Save className="h-4 w-4" />
            Capture Golden Baseline
          </button>
        </div>
      )}

      {showCapture && createPortal(
        <div
          className="fixed inset-0 z-50 overflow-y-auto bg-black/70 px-3 py-4 backdrop-blur-sm sm:px-6 sm:py-8"
          onClick={() => {
            if (!saving) setShowCapture(false)
          }}
        >
          <div className="flex min-h-full items-start justify-center">
            <form
              role="dialog"
              aria-modal="true"
              aria-labelledby="golden-baseline-dialog-title"
              className="flex max-h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-white/[0.08] bg-[#111827] shadow-2xl sm:max-h-[calc(100vh-4rem)]"
              onClick={event => event.stopPropagation()}
              onSubmit={event => {
                event.preventDefault()
                if (canCapture && !saving) captureBaseline()
              }}
            >
              <div className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-white/[0.06] px-4 py-4 sm:px-5">
                <div>
                  <h2 id="golden-baseline-dialog-title" className="text-base font-bold text-white">
                    {golden ? `Capture Baseline Version ${(golden.version_number || 0) + 1}` : 'Capture Golden Baseline'}
                  </h2>
                  <p className="mt-1 text-xs text-gray-500">Job Runner totals and accepted bundle targets</p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowCapture(false)}
                  disabled={saving}
                  className="btn-ghost p-2 disabled:cursor-not-allowed disabled:opacity-40"
                  title="Close baseline dialog"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-5">
                {error && (
                  <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    <span className="flex-1">{error}</span>
                    <button type="button" onClick={() => setError(null)} className="p-1 text-red-300/60 hover:text-red-200" title="Dismiss error">
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                )}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <label className="block">
                    <span className="mb-1 block text-xs text-gray-500">JR Quote ID</span>
                    <input
                      value={form.jr_quote_id}
                      onChange={event => setForm(current => ({ ...current, jr_quote_id: event.target.value }))}
                      className="input w-full text-sm"
                      placeholder="293113"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs text-gray-500">Reviewed By</span>
                    <input
                      value={form.reviewer_name}
                      onChange={event => setForm(current => ({ ...current, reviewer_name: event.target.value }))}
                      className="input w-full text-sm"
                      placeholder="Estimator name"
                    />
                  </label>
                  {TOTAL_FIELDS.slice(0, 2).map(([key, label]) => (
                    <label key={key} className="block">
                      <span className="mb-1 block text-xs text-gray-500">{label}</span>
                      <input
                        value={form[key]}
                        onChange={event => setForm(current => ({ ...current, [key]: event.target.value }))}
                        className="input w-full text-sm"
                        placeholder="$0"
                      />
                    </label>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {TOTAL_FIELDS.slice(2).map(([key, label]) => (
                    <label key={key} className="block">
                      <span className="mb-1 block text-xs text-gray-500">{label}</span>
                      <input
                        value={form[key]}
                        onChange={event => setForm(current => ({ ...current, [key]: event.target.value }))}
                        className="input w-full text-sm"
                        placeholder="$0"
                      />
                    </label>
                  ))}
                </div>
                <label className="block">
                  <span className="mb-1 block text-xs text-gray-500">Notes</span>
                  <input
                    value={form.notes}
                    onChange={event => setForm(current => ({ ...current, notes: event.target.value }))}
                    className="input w-full text-sm"
                    placeholder="Sun Valley accepted baseline"
                  />
                </label>
                {acceptedBundles.length > 0 && (
                  <div className="border-t border-white/[0.06] pt-4">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-bold uppercase text-gray-400">JR Bundle Breakouts</p>
                      <span className="text-[10px] font-semibold uppercase text-gray-600">
                        {enteredBundleTargetCount} / {acceptedBundles.length} entered
                      </span>
                    </div>
                    <div className="max-h-96 overflow-y-auto border-y border-white/[0.06] sm:hidden">
                      <div className="divide-y divide-white/[0.04]">
                        {acceptedBundles.map(bundle => (
                          <div key={`mobile-${bundle.bundle_name}`} className="py-3">
                            <p className="break-words text-sm font-medium leading-5 text-gray-300">{bundle.bundle_name}</p>
                            <div className="mt-2 grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] items-end gap-3">
                              <div>
                                <p className="text-[10px] font-semibold uppercase text-gray-600">Accepted</p>
                                <p className="mt-1 text-sm tabular-nums text-gray-400">{shortMoney(bundle.accepted_total)}</p>
                              </div>
                              <label className="block">
                                <span className="mb-1 block text-[10px] font-semibold uppercase text-gray-600">JR target</span>
                                <input
                                  value={bundleTargets[bundle.bundle_name] ?? ''}
                                  onChange={event => setBundleTargets(current => ({ ...current, [bundle.bundle_name]: event.target.value }))}
                                  className="input w-full text-right text-sm tabular-nums"
                                  placeholder="$0"
                                  aria-label={`JR target for ${bundle.bundle_name}`}
                                />
                              </label>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="hidden max-h-96 overflow-auto border-y border-white/[0.06] sm:block">
                      <table className="w-full min-w-[560px] text-sm">
                        <thead className="sticky top-0 bg-[#111827] text-[10px] uppercase text-gray-500">
                          <tr>
                            <th className="px-3 py-2 text-left font-bold">Accepted bundle</th>
                            <th className="px-3 py-2 text-right font-bold">Accepted</th>
                            <th className="w-40 px-3 py-2 text-right font-bold">JR target</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/[0.04]">
                          {acceptedBundles.map(bundle => (
                            <tr key={bundle.bundle_name}>
                              <td className="px-3 py-2 text-gray-300">{bundle.bundle_name}</td>
                              <td className="px-3 py-2 text-right tabular-nums text-gray-500">{shortMoney(bundle.accepted_total)}</td>
                              <td className="px-3 py-1.5">
                                <input
                                  value={bundleTargets[bundle.bundle_name] ?? ''}
                                  onChange={event => setBundleTargets(current => ({ ...current, [bundle.bundle_name]: event.target.value }))}
                                  className="input w-full text-right text-sm tabular-nums"
                                  placeholder="$0"
                                  aria-label={`JR target for ${bundle.bundle_name}`}
                                />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-shrink-0 items-center justify-end gap-2 border-t border-white/[0.06] px-4 py-3 sm:px-5">
                <button
                  type="button"
                  onClick={() => setShowCapture(false)}
                  disabled={saving}
                  className="btn-ghost px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || !canCapture}
                  className="btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {golden ? 'Capture New Baseline Version' : 'Capture Golden Baseline'}
                </button>
              </div>
            </form>
          </div>
        </div>,
        document.body,
      )}

      {golden && (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
              <div className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                <Database className="h-3.5 w-3.5" />
                JR Target
              </div>
              <p className="text-lg font-bold text-white">{moneyOrDash(golden.target_totals?.grand_total)}</p>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
              <p className="mb-1 text-xs text-gray-500">Accepted Proposal</p>
              <p className="text-lg font-bold text-white">{moneyOrDash(golden.accepted_totals?.grand_total)}</p>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
              <p className="mb-1 text-xs text-gray-500">Latest Replay</p>
              <p className="text-lg font-bold text-white">{moneyOrDash(latest?.summary?.generated_totals?.grand_total)}</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => runReplay('baseline')}
              disabled={!!runningMode}
              className="btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-40"
            >
              {runningMode === 'baseline' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
              Replay Baseline
            </button>
            <button
              onClick={() => runReplay('current')}
              disabled={!!runningMode}
              className="btn-ghost inline-flex items-center gap-2 px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-40"
            >
              {runningMode === 'current' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
              Replay Current
            </button>
            <button
              onClick={startNewVersion}
              disabled={!!runningMode || showCapture}
              className="btn-ghost inline-flex items-center gap-2 px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Save className="h-4 w-4" />
              Capture New Version
            </button>
          </div>

          {(baselineReplay || currentReplay) && (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setSelectedMode('baseline')}
                className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${selectedMode === 'baseline' ? 'border-cyan-500/30 bg-cyan-500/[0.08]' : 'border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04]'}`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-bold uppercase text-gray-300">Baseline proof</span>
                  <span className="mt-0.5 block text-[11px] text-gray-500">
                    Raw {baselineReplay?.summary?.raw_engine_status || 'not replayed'} / accepted {baselineReplay?.summary?.accepted_proposal_status || 'not replayed'}
                  </span>
                </span>
                <StatusBadge status={baselineReplay?.status || 'not_replayed'} />
              </button>
              <button
                type="button"
                onClick={() => setSelectedMode('current')}
                className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${selectedMode === 'current' ? 'border-cyan-500/30 bg-cyan-500/[0.08]' : 'border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04]'}`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-bold uppercase text-gray-300">Current drift</span>
                  <span className="mt-0.5 block text-[11px] text-gray-500">
                    Raw {currentReplay?.summary?.raw_engine_status || 'not replayed'} / accepted {currentReplay?.summary?.accepted_proposal_status || 'not replayed'}
                  </span>
                </span>
                <StatusBadge status={currentReplay?.summary?.drift_classification === 'metadata_only' ? 'metadata_only' : currentReplay?.status || 'not_replayed'} />
              </button>
            </div>
          )}

          {latest && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                <StatusBadge status={latest.status} />
                <span>{latest.mode} replay</span>
                <span>run #{latest.id}</span>
                <span>audit #{latest.audit_run_id || '-'}</span>
                <span>engine {latest.summary?.raw_engine_status || latest.summary?.engine_status || '-'}</span>
                <span>accepted {latest.summary?.accepted_proposal_status || '-'}</span>
                <span>JR target {latest.summary?.jr_target_status || '-'}</span>
              </div>
              <TotalsTable replay={latest} />
              <TotalsTable replay={latest} rowsKey="jr_totals" title="Job Runner Target Delta" />
              <JRBundleDeltas replay={latest} />
              <StructuralIssues replay={latest} />
              <BundleDeltas replay={latest} />
              <DriftRows replay={latest} />
              <EngineReplayNotice replay={latest} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
