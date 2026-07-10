import { AlertTriangle, CheckCircle2, RefreshCw, ShieldCheck, XCircle } from 'lucide-react'
import StatusBadge from './StatusBadge'

function CheckIcon({ status }) {
  if (status === 'pass') return <CheckCircle2 className="w-4 h-4 text-emerald-400" />
  if (status === 'fail') return <XCircle className="w-4 h-4 text-red-400" />
  return <AlertTriangle className="w-4 h-4 text-amber-400" />
}

function shortCommit(value) {
  if (!value || value === 'unknown') return 'build unknown'
  return String(value).slice(0, 10)
}

export default function ReadinessSummary({ readiness, onRefresh }) {
  if (!readiness) return null
  const failed = (readiness.checks || []).filter(check => check.status === 'fail')
  const warnings = (readiness.checks || []).filter(check => check.status === 'warn')
  const important = [...failed, ...warnings]
  const build = readiness.build || {}

  return (
    <section className="glass-card p-4 sm:p-5 mb-6" aria-label="Bid readiness">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-emerald-500/15 bg-emerald-500/10">
          <ShieldCheck className="h-5 w-5 text-emerald-300" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-bold text-white">Bid Readiness</h2>
            <StatusBadge status={readiness.golden_status === 'golden_verified' ? 'golden' : readiness.golden_status === 'fail' ? 'drift' : readiness.status} />
            {readiness.warning_count > 0 && (
              <span className="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-amber-300">
                {readiness.warning_count} warning{readiness.warning_count === 1 ? '' : 's'}
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-gray-500">
            <span>{readiness.blocking_count ? `${readiness.blocking_count} blocker${readiness.blocking_count === 1 ? '' : 's'}` : 'No blockers'}</span>
            <span>verified {new Date(readiness.verified_at).toLocaleString()}</span>
            <span className="font-mono">{shortCommit(build.commit)}</span>
            {build.engine_fingerprint && <span className="font-mono">engine {String(build.engine_fingerprint).slice(0, 10)}</span>}
          </div>
        </div>
        <button onClick={onRefresh} className="btn-ghost p-2" title="Refresh bid readiness">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {important.length > 0 ? (
        <div className="mt-4 space-y-2">
          {important.map(check => (
            <div key={check.id} className="flex items-start gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
              <CheckIcon status={check.status} />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-gray-200">{check.message}</p>
                {check.affected_items?.length > 0 && (
                  <p className="mt-1 truncate text-xs text-gray-500">{check.affected_items.slice(0, 6).join(', ')}{check.affected_items.length > 6 ? '...' : ''}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-500/15 bg-emerald-500/[0.04] px-3 py-2 text-sm text-emerald-200">
          <CheckCircle2 className="w-4 h-4" />
          All required readiness checks passed.
        </div>
      )}
    </section>
  )
}
