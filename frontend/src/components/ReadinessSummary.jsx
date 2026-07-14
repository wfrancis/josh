import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert, ShieldCheck, XCircle } from 'lucide-react'
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

function formatMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return 'Not set'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value))
}

function formatDate(value) {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleString()
}

function Metric({ label, value, title }) {
  return (
    <div className="min-w-0 border-t border-white/[0.06] pt-3" title={title}>
      <p className="text-[10px] font-semibold uppercase text-gray-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-gray-200">{value}</p>
    </div>
  )
}

export default function ReadinessSummary({ readiness, onRefresh }) {
  if (!readiness) return null
  const failed = (readiness.checks || []).filter(check => check.status === 'fail')
  const warnings = (readiness.checks || []).filter(check => check.status === 'warn')
  const important = [...failed, ...warnings]
  const build = readiness.build || {}
  const trust = readiness.trust_summary || {}
  const goldenBadgeStatus = readiness.golden_verification_status === 'golden_verified' ? 'golden' : null
  const metadataBadgeStatus = readiness.golden_status === 'metadata_changed'
    || (readiness.current_replay_status === 'warn' && readiness.current_replay_drift_classification === 'metadata_only')
    ? 'metadata_changed'
    : null
  const driftBadgeStatus = readiness.current_replay_status === 'incomparable' || readiness.golden_verification_status === 'incomparable'
    ? 'incomparable'
    : (!metadataBadgeStatus && (
      ['warn', 'fail'].includes(readiness.current_replay_status)
      || ['fail', 'drift', 'incomparable'].includes(readiness.golden_status)
    ))
      ? 'drift'
      : null
  const HeaderIcon = readiness.status === 'blocked' ? ShieldAlert : readiness.status === 'warning' ? AlertTriangle : ShieldCheck
  const headerTone = readiness.status === 'blocked'
    ? 'border-red-500/20 bg-red-500/10 text-red-300'
    : readiness.status === 'warning'
      ? 'border-amber-500/20 bg-amber-500/10 text-amber-300'
      : 'border-emerald-500/15 bg-emerald-500/10 text-emerald-300'

  return (
    <section className="glass-card p-4 sm:p-5 mb-6" aria-label="Bid readiness">
      <div className="flex flex-wrap items-start gap-3">
        <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border ${headerTone}`}>
          <HeaderIcon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-bold text-white">Bid Readiness</h2>
            <StatusBadge status={readiness.status} />
            {goldenBadgeStatus && <StatusBadge status={goldenBadgeStatus} />}
            {metadataBadgeStatus && <StatusBadge status={metadataBadgeStatus} />}
            {driftBadgeStatus && <StatusBadge status={driftBadgeStatus} />}
            {readiness.warning_count > 0 && (
              <span className="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] font-bold uppercase text-amber-300">
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

      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-6">
        <Metric label="Last audit" value={formatDate(trust.last_audit_at)} />
        <Metric label="Last PDF" value={formatDate(trust.last_pdf_at)} />
        <Metric
          label="Build"
          value={`${trust.build_tag && trust.build_tag !== 'unknown' ? trust.build_tag : 'untagged'} / ${shortCommit(trust.build_commit || build.commit)}`}
          title={trust.engine_fingerprint ? `Engine ${trust.engine_fingerprint}` : undefined}
        />
        <Metric label="Rules" value={trust.ruleset_version != null ? `Ruleset v${trust.ruleset_version}` : 'Not recorded'} />
        <Metric label="Golden baseline" value={trust.golden_baseline_version ? `Version ${trust.golden_baseline_version}` : 'Not captured'} />
        <Metric label="Durable artifacts" value={`${trust.artifact_count || 0} recorded`} />
        <Metric label="JR target" value={formatMoney(trust.jr_target_total)} />
        <Metric label="Accepted proposal" value={formatMoney(trust.accepted_proposal_total)} />
        <Metric
          label={trust.replay_mode === 'current' ? 'Current replay' : 'Latest replay'}
          value={formatMoney(trust.replay_total)}
          title={trust.replay_status ? `Replay status: ${trust.replay_status}` : undefined}
        />
        <Metric label="Manual overrides" value={String(trust.manual_override_count || 0)} />
        <Metric label="Unknown materials" value={String(trust.unknown_material_count || 0)} />
        <Metric label="Low confidence" value={String(trust.low_confidence_material_count || 0)} />
      </div>

      {trust.largest_deltas?.length > 0 && (
        <div className="mt-4 border-t border-white/[0.06] pt-3">
          <p className="text-[10px] font-semibold uppercase text-gray-500">Largest replay deltas</p>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
            {trust.largest_deltas.map((delta, index) => (
              <span key={`${delta.bundle_name}-${index}`} className={delta.status === 'fail' ? 'text-sm text-red-300' : delta.status === 'warn' ? 'text-sm text-amber-300' : 'text-sm text-gray-300'}>
                {delta.bundle_name || `Bundle ${index + 1}`}: {formatMoney(delta.delta)}
              </span>
            ))}
          </div>
        </div>
      )}

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
