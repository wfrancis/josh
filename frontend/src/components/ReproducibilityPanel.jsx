import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle, CheckCircle2, Database, Loader2, PlayCircle,
  RefreshCw, Save, ShieldCheck, XCircle
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
  if (key === 'pass') return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
  if (key === 'warn') return 'bg-amber-500/10 text-amber-300 border-amber-500/20'
  if (key === 'fail') return 'bg-red-500/10 text-red-300 border-red-500/20'
  return 'bg-white/[0.04] text-gray-400 border-white/[0.08]'
}

function StatusIcon({ status }) {
  const key = String(status || '').toLowerCase()
  if (key === 'pass') return <CheckCircle2 className="w-4 h-4" />
  if (key === 'fail') return <XCircle className="w-4 h-4" />
  return <AlertTriangle className="w-4 h-4" />
}

function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] font-bold uppercase tracking-wider ${statusClass(status)}`}>
      <StatusIcon status={status} />
      {status || 'ready'}
    </span>
  )
}

function TotalsTable({ replay }) {
  const rows = replay?.diff?.totals || []
  if (!rows.length) return null
  return (
    <div className="overflow-x-auto rounded-lg border border-white/[0.06]">
      <table className="w-full text-sm">
        <thead className="bg-white/[0.03] text-[10px] uppercase tracking-wider text-gray-500">
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
  )
}

function BundleDeltas({ replay }) {
  const rows = (replay?.diff?.bundles || []).filter(row => row.status !== 'pass' || Number(row.delta || 0) !== 0).slice(0, 6)
  if (!rows.length) return null
  return (
    <div className="rounded-lg border border-white/[0.06] p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500">Bundle Deltas</h3>
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

function StructuralIssues({ replay }) {
  const rows = replay?.diff?.structural || []
  if (!rows.length) return null
  return (
    <div className="rounded-lg border border-red-500/20 bg-red-500/[0.04] p-3">
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-red-300">Structural Issues</h3>
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
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-amber-300">Rule / Rate Drift</h3>
      <div className="space-y-1.5">
        {rows.map(row => (
          <p key={row.check} className="text-sm text-amber-100">{row.message || row.check}</p>
        ))}
      </div>
    </div>
  )
}

export default function ReproducibilityPanel({ jobId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [runningMode, setRunningMode] = useState(null)
  const [form, setForm] = useState({
    jr_quote_id: '',
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

  useEffect(() => { load() }, [jobId])

  const golden = data?.golden_job
  const latest = data?.latest_replay
  const hasTarget = useMemo(() => TOTAL_FIELDS.some(([key]) => parseMoney(form[key]) != null), [form])

  async function captureBaseline() {
    const target_totals = {}
    TOTAL_FIELDS.forEach(([key]) => {
      const value = parseMoney(form[key])
      if (value != null) target_totals[key] = value
    })
    setSaving(true)
    setError(null)
    try {
      setData(await api.captureGoldenBaseline(jobId, {
        jr_quote_id: form.jr_quote_id,
        target_totals,
        notes: form.notes,
      }))
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function runReplay(mode) {
    setRunningMode(mode)
    setError(null)
    try {
      await api.runGoldenReplay(jobId, mode)
      await load()
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
            {golden ? <StatusBadge status={latest?.status || 'ready'} /> : (
              <span className="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-amber-300">
                No baseline
              </span>
            )}
          </div>
          {golden && (
            <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-gray-500">
              <span>JR {golden.jr_quote_id || '-'}</span>
              <span>Ruleset v{golden.ruleset_version || '-'}</span>
              <span className="font-mono">{String(golden.source_fingerprint || '').slice(0, 10)}</span>
            </div>
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
          <button onClick={() => setError(null)} className="text-red-300/60 hover:text-red-200">dismiss</button>
        </div>
      )}

      {!loading && !golden && (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">JR Quote ID</span>
              <input
                value={form.jr_quote_id}
                onChange={e => setForm(f => ({ ...f, jr_quote_id: e.target.value }))}
                className="input w-full text-sm"
                placeholder="293113"
              />
            </label>
            {TOTAL_FIELDS.slice(0, 2).map(([key, label]) => (
              <label key={key} className="block">
                <span className="mb-1 block text-xs text-gray-500">{label}</span>
                <input
                  value={form[key]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
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
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
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
              onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              className="input w-full text-sm"
              placeholder="Sun Valley accepted baseline"
            />
          </label>
          <button
            onClick={captureBaseline}
            disabled={saving || !hasTarget}
            className="btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Capture Golden Baseline
          </button>
        </div>
      )}

      {golden && (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
              <div className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                <Database className="h-3.5 w-3.5" />
                JR Target
              </div>
              <p className="text-lg font-bold text-white">{money(golden.target_totals?.grand_total)}</p>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
              <p className="mb-1 text-xs text-gray-500">Accepted Proposal</p>
              <p className="text-lg font-bold text-white">{money(golden.accepted_totals?.grand_total)}</p>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
              <p className="mb-1 text-xs text-gray-500">Latest Replay</p>
              <p className="text-lg font-bold text-white">{money(latest?.summary?.generated_totals?.grand_total)}</p>
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
          </div>

          {latest && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                <StatusBadge status={latest.status} />
                <span>{latest.mode} replay</span>
                <span>run #{latest.id}</span>
                <span>audit #{latest.audit_run_id || '-'}</span>
              </div>
              <TotalsTable replay={latest} />
              <StructuralIssues replay={latest} />
              <BundleDeltas replay={latest} />
              <DriftRows replay={latest} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
