import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Check, CheckCircle2, ChevronRight, RefreshCw, ShieldAlert, ShieldCheck, Upload, X, XCircle } from 'lucide-react'
import StatusBadge from './StatusBadge'

// Checks only an admin or developer can act on. They never show in the
// estimator's to-do list, only under "Technical details" (the server marks
// them with technical: true; this list covers an older server).
const TECHNICAL_CHECK_IDS = new Set(['deployed_build_identity', 'durable_artifacts', 'golden_replay', 'current_replay_drift'])

function isTechnical(check) {
  return Boolean(check.technical) || TECHNICAL_CHECK_IDS.has(check.id)
}

function CheckIcon({ status }) {
  if (status === 'pass') return <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-emerald-400" />
  if (status === 'fail') return <XCircle className="w-4 h-4 flex-shrink-0 text-red-400" />
  return <AlertTriangle className="w-4 h-4 flex-shrink-0 text-amber-400" />
}

function shortCommit(value) {
  if (!value || value === 'unknown') return 'unknown'
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

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : (many || `${one}s`)}`
}

// Same message twice (e.g. two checks pointing at one fix) shows once.
function uniqueByMessage(checks) {
  const seen = new Set()
  return checks.filter(check => {
    if (seen.has(check.message)) return false
    seen.add(check.message)
    return true
  })
}

function Metric({ label, value, title }) {
  return (
    <div className="min-w-0 border-t border-white/[0.06] pt-3" title={title}>
      <p className="text-[10px] font-semibold uppercase text-gray-500">{label}</p>
      <p className="mt-1 break-words text-sm font-semibold leading-5 text-gray-200">{value}</p>
    </div>
  )
}

function ActionButton({ action, onAction }) {
  if (!action?.id || !onAction) return null
  return (
    <button
      type="button"
      onClick={() => onAction(action.id)}
      className="btn-secondary min-h-9 flex-shrink-0 px-3 py-1.5 text-xs"
      data-testid={`readiness-action-${action.id}`}
    >
      {action.label}
      <ChevronRight className="h-3.5 w-3.5" />
    </button>
  )
}

function CheckRow({ check, onAction, children }) {
  const items = check.affected_items || []
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5" data-testid={`readiness-check-${check.id}`}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <span className="mt-0.5"><CheckIcon status={check.status} /></span>
          <div className="min-w-0 flex-1">
            <p className="text-sm leading-5 text-gray-200">{check.message}</p>
            {items.length > 0 && (
              <p className="mt-1 break-words text-xs leading-5 text-gray-500">
                {items.slice(0, 8).join(', ')}{items.length > 8 ? ` and ${items.length - 8} more` : ''}
              </p>
            )}
          </div>
        </div>
        <ActionButton action={check.action} onAction={onAction} />
      </div>
      {children}
    </div>
  )
}

function VendorConflictList({ conflicts, total, onReview }) {
  return (
    <div className="mt-3 border-t border-amber-500/15 pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-bold uppercase text-amber-300">Price differs from the vendor's quote</p>
        <span className="text-[10px] font-semibold uppercase text-gray-500">
          {plural(total || conflicts.length, 'price')}
        </span>
      </div>
      <div className="mt-2 max-h-72 overflow-y-auto border-y border-white/[0.06] sm:hidden">
        <div className="divide-y divide-white/[0.04]">
          {conflicts.map((row, index) => (
            <div key={`mobile-${row.material_id}-${row.source_hash}-${index}`} className="py-3">
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 break-words text-sm font-semibold text-gray-200">{row.item_code}</p>
                <p className="flex-shrink-0 text-sm font-semibold tabular-nums text-amber-300">{formatMoney(row.delta)}</p>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="text-[10px] font-semibold uppercase text-gray-600">On the bid</p>
                  <p className="mt-0.5 tabular-nums text-gray-300">{formatMoney(row.accepted_price)} / {row.accepted_unit}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase text-gray-600">Vendor quote</p>
                  <p className="mt-0.5 tabular-nums text-gray-300">{formatMoney(row.quote_price)} / {row.quote_unit}</p>
                </div>
              </div>
              <p className="mt-2 break-words text-[11px] leading-4 text-gray-500">{row.source_file || 'Vendor quote'}</p>
              {onReview && (
                <button
                  type="button"
                  onClick={() => onReview(row)}
                  className="btn-secondary mt-3 flex min-h-9 w-full items-center justify-center gap-2 text-xs"
                >
                  <Check className="h-3.5 w-3.5" />
                  Review price
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-2 hidden max-h-56 overflow-auto border-y border-white/[0.06] sm:block">
        <table className="w-full min-w-[580px] text-xs">
          <thead className="sticky top-0 bg-[#111827] text-[10px] uppercase text-gray-500">
            <tr>
              <th className="px-2 py-2 text-left font-semibold">Material</th>
              <th className="px-2 py-2 text-right font-semibold">On the bid</th>
              <th className="px-2 py-2 text-right font-semibold">Vendor quote</th>
              <th className="px-2 py-2 text-right font-semibold">Difference</th>
              <th className="px-2 py-2 text-left font-semibold">Quote file</th>
              {onReview && <th className="px-2 py-2 text-right font-semibold">Action</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {conflicts.map((row, index) => (
              <tr key={`${row.material_id}-${row.source_hash}-${index}`} className="text-gray-300">
                <td className="px-2 py-2 font-semibold text-gray-200">{row.item_code}</td>
                <td className="px-2 py-2 text-right tabular-nums">{formatMoney(row.accepted_price)} / {row.accepted_unit}</td>
                <td className="px-2 py-2 text-right tabular-nums">{formatMoney(row.quote_price)} / {row.quote_unit}</td>
                <td className="px-2 py-2 text-right font-semibold tabular-nums text-amber-300">{formatMoney(row.delta)}</td>
                <td className="max-w-52 truncate px-2 py-2 text-gray-500" title={row.source_file}>{row.source_file || 'Vendor quote'}</td>
                {onReview && (
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => onReview(row)}
                      className="btn-secondary inline-flex min-h-8 items-center gap-1.5 px-2.5 text-xs"
                    >
                      <Check className="h-3.5 w-3.5" />
                      Review
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PriceDecisionDialog({ conflict, onClose, onSubmit }) {
  const [decision, setDecision] = useState('use_quote')
  const [reviewerName, setReviewerName] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = event => {
      if (event.key === 'Escape' && !saving) onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose, saving])

  const handleSubmit = async event => {
    event.preventDefault()
    if (reviewerName.trim().length < 2 || reason.trim().length < 5) {
      setError('Enter the reviewer name and a short reason.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await onSubmit(conflict, {
        decision,
        source_hash: conflict.source_hash,
        quote_price: conflict.quote_price,
        quote_unit: conflict.quote_unit,
        accepted_price: conflict.accepted_price,
        reviewer_name: reviewerName.trim(),
        reason: reason.trim(),
      })
      onClose()
    } catch (err) {
      setError(err.message || 'The price decision could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-3 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="price-decision-title">
      <form onSubmit={handleSubmit} className="flex max-h-[calc(100dvh-1.5rem)] w-full max-w-xl flex-col overflow-hidden rounded-lg border border-white/[0.12] bg-[#111827] shadow-2xl sm:max-h-[calc(100dvh-3rem)]">
        <div className="flex items-start gap-3 border-b border-white/[0.08] px-4 py-4 sm:px-5">
          <div className="min-w-0 flex-1">
            <h3 id="price-decision-title" className="text-base font-bold text-white">Review {conflict.item_code}</h3>
            <p className="mt-1 break-words text-xs leading-5 text-gray-400">{conflict.source_file || 'Verified vendor quote'}</p>
          </div>
          <button type="button" onClick={onClose} disabled={saving} className="btn-ghost p-2" title="Close price review">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="overflow-y-auto px-4 py-4 sm:px-5">
          <div className="grid grid-cols-3 gap-3 border-y border-white/[0.07] py-3 text-center">
            <Metric label="Accepted" value={`${formatMoney(conflict.accepted_price)} / ${conflict.accepted_unit}`} />
            <Metric label="Verified quote" value={`${formatMoney(conflict.quote_price)} / ${conflict.quote_unit}`} />
            <Metric label="Difference" value={formatMoney(conflict.delta)} />
          </div>

          <div className="mt-4 grid grid-cols-2 rounded-lg border border-white/[0.08] bg-black/20 p-1" aria-label="Price decision">
            <button
              type="button"
              onClick={() => setDecision('use_quote')}
              className={`min-h-10 rounded-md px-3 py-2 text-sm font-semibold ${decision === 'use_quote' ? 'bg-emerald-600 text-white' : 'text-gray-400 hover:text-white'}`}
            >
              Use verified quote
            </button>
            <button
              type="button"
              onClick={() => setDecision('keep_accepted')}
              className={`min-h-10 rounded-md px-3 py-2 text-sm font-semibold ${decision === 'keep_accepted' ? 'bg-amber-500 text-gray-950' : 'text-gray-400 hover:text-white'}`}
            >
              Keep accepted price
            </button>
          </div>
          <p className="mt-2 text-xs leading-5 text-gray-500">
            {decision === 'use_quote'
              ? 'The material price will change to the vendor quote. Afterwards, click Regenerate on the Review & Generate step to update the bid.'
              : 'The price on the bid stays. The difference and your reason stay on record.'}
          </p>

          <label className="mt-4 block text-xs font-semibold text-gray-300">
            Reviewer
            <input
              value={reviewerName}
              onChange={event => setReviewerName(event.target.value)}
              className="mt-1 w-full rounded-md border border-white/[0.1] bg-black/25 px-3 py-2 text-sm text-white outline-none focus:border-si-bright/60"
              placeholder="Estimator name"
              autoFocus
            />
          </label>
          <label className="mt-3 block text-xs font-semibold text-gray-300">
            Reason
            <textarea
              value={reason}
              onChange={event => setReason(event.target.value)}
              rows={3}
              className="mt-1 w-full resize-none rounded-md border border-white/[0.1] bg-black/25 px-3 py-2 text-sm text-white outline-none focus:border-si-bright/60"
              placeholder={decision === 'use_quote' ? 'Why this quote is the correct source' : 'Why the accepted price should stay'}
            />
          </label>
          {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-white/[0.08] px-4 py-3 sm:px-5">
          <button type="button" onClick={onClose} disabled={saving} className="btn-ghost px-3 py-2 text-sm">Cancel</button>
          <button type="submit" disabled={saving} className="btn-primary flex items-center gap-2 px-4 py-2 text-sm">
            <Check className="h-4 w-4" />
            {saving ? 'Saving...' : 'Save decision'}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  )
}


export default function ReadinessSummary({ readiness, onRefresh, onRecoverEvidence, onResolveVendorConflict, onAction }) {
  const [selectedConflict, setSelectedConflict] = useState(null)
  const [technicalOpen, setTechnicalOpen] = useState(false)
  const technicalRef = useRef(null)
  if (!readiness) return null
  const checks = readiness.checks || []
  const handleAction = onAction || (actionId => { if (actionId === 'quotes') onRecoverEvidence?.() })
  // A check another failing check already covers (covered_by) isn't listed twice.
  const isCovered = check => Boolean(check.covered_by)
    && checks.some(other => other.id === check.covered_by && other.status === 'fail')
  const mustDo = uniqueByMessage(checks.filter(check => check.status === 'fail' && !isTechnical(check) && !isCovered(check)))
  const secondLook = uniqueByMessage(checks.filter(check => check.status === 'warn' && !isTechnical(check)))
  const technicalChecks = checks.filter(isTechnical)
  const technicalBlockers = technicalChecks.filter(check => check.status === 'fail' && !isCovered(check))
  const build = readiness.build || {}
  const trust = readiness.trust_summary || {}
  const vendorPriceConflicts = trust.vendor_price_conflicts || []
  const vendorPriceOverrides = trust.vendor_price_overrides || []
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

  const fixCount = mustDo.length + (technicalBlockers.length > 0 ? 1 : 0)
  const blocked = fixCount > 0
  const HeaderIcon = blocked ? ShieldAlert : secondLook.length ? AlertTriangle : ShieldCheck
  const headerTone = blocked
    ? 'border-red-500/20 bg-red-500/10 text-red-300'
    : secondLook.length
      ? 'border-amber-500/20 bg-amber-500/10 text-amber-300'
      : 'border-emerald-500/15 bg-emerald-500/10 text-emerald-300'
  const headline = blocked
    ? `Fix ${plural(fixCount, 'thing')} before sending`
    : secondLook.length
      ? `Ready to send. ${plural(secondLook.length, 'thing')} worth a second look.`
      : 'Ready to send'

  const openTechnical = () => {
    setTechnicalOpen(true)
    window.setTimeout(() => technicalRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  return (
    <>
    <section className="glass-card p-4 sm:p-5 mb-6" aria-label="Before you send this bid" data-testid="readiness-card">
      <div className="flex items-start gap-3">
        <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border ${headerTone}`}>
          <HeaderIcon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-bold text-white">Before you send this bid</h2>
          <p
            className={`mt-0.5 text-sm font-semibold ${blocked ? 'text-red-300' : secondLook.length ? 'text-amber-300' : 'text-emerald-300'}`}
            data-testid="readiness-status"
            data-status={blocked ? 'blocked' : secondLook.length ? 'warning' : 'ready'}
          >
            {headline}
          </p>
        </div>
        <button onClick={onRefresh} className="btn-ghost p-2" title="Check again">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {!blocked && !secondLook.length && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] px-3 py-3 text-sm font-semibold text-emerald-200" data-testid="readiness-ready">
          <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-emerald-400" />
          Ready to send. Everything on this bid checks out.
        </div>
      )}

      {blocked && (
        <div className="mt-4 space-y-2" data-testid="readiness-todo">
          {mustDo.map(check => (
            <CheckRow key={check.id} check={check} onAction={handleAction}>
              {check.id === 'vendor_quote_evidence' && vendorPriceConflicts.length > 0 && (
                <VendorConflictList
                  conflicts={vendorPriceConflicts}
                  total={trust.vendor_price_conflict_count}
                  onReview={onResolveVendorConflict ? setSelectedConflict : null}
                />
              )}
            </CheckRow>
          ))}
          {technicalBlockers.length > 0 && (
            <div className="flex flex-col gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5 sm:flex-row sm:items-center">
              <div className="flex min-w-0 flex-1 items-start gap-2">
                <span className="mt-0.5"><CheckIcon status="fail" /></span>
                <p className="text-sm leading-5 text-gray-200">
                  Something behind the scenes needs attention. Open Technical details below, or ask your admin.
                </p>
              </div>
              <button type="button" onClick={openTechnical} className="btn-secondary min-h-9 flex-shrink-0 px-3 py-1.5 text-xs">
                Show details
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      )}

      {secondLook.length > 0 && (
        <div className="mt-4" data-testid="readiness-warnings">
          {blocked && <p className="mb-2 text-[11px] font-semibold uppercase text-gray-500">Also worth a second look</p>}
          <div className="space-y-2">
            {secondLook.map(check => (
              <CheckRow key={check.id} check={check} onAction={handleAction} />
            ))}
          </div>
        </div>
      )}

      <details
        ref={technicalRef}
        open={technicalOpen}
        onToggle={event => setTechnicalOpen(event.currentTarget.open)}
        className="mt-4 scroll-mt-20 border-t border-white/[0.06] pt-3"
        data-testid="readiness-technical"
      >
        <summary className="flex cursor-pointer select-none items-center gap-2 text-xs font-semibold text-gray-500 hover:text-gray-300">
          <ChevronRight className={`h-3.5 w-3.5 transition-transform ${technicalOpen ? 'rotate-90' : ''}`} />
          Technical details
        </summary>

        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <StatusBadge status={readiness.status} />
            {goldenBadgeStatus && <StatusBadge status={goldenBadgeStatus} />}
            {metadataBadgeStatus && <StatusBadge status={metadataBadgeStatus} />}
            {driftBadgeStatus && <StatusBadge status={driftBadgeStatus} />}
            <span>checked {formatDate(readiness.verified_at)}</span>
            <span className="font-mono">{shortCommit(build.commit)}</span>
            {build.engine_fingerprint && <span className="font-mono">engine {String(build.engine_fingerprint).slice(0, 10)}</span>}
          </div>

          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-6">
            <Metric label="Last numbers check" value={formatDate(trust.last_audit_at)} />
            <Metric label="Last PDF" value={formatDate(trust.last_pdf_at)} />
            <Metric
              label="Build"
              value={`${trust.build_tag && trust.build_tag !== 'unknown' ? trust.build_tag : 'untagged'} / ${shortCommit(trust.build_commit || build.commit)}`}
              title={trust.engine_fingerprint ? `Engine ${trust.engine_fingerprint}` : undefined}
            />
            <Metric label="Rules" value={trust.ruleset_version != null ? `Ruleset v${trust.ruleset_version}` : 'Not recorded'} />
            <Metric label="Golden baseline" value={trust.golden_baseline_version ? `Version ${trust.golden_baseline_version}` : 'Not captured'} />
            <Metric
              label="Source evidence"
              value={`${trust.verified_source_count || 0} verified / ${trust.unverified_source_count || 0} unverified`}
            />
            <Metric
              label="Dropbox mode"
              value={trust.vendor_source_mode === 'browser_local_sync_folder' ? 'Local folder only' : 'Not recorded'}
              title={trust.vendor_source_automatic_sync === false ? 'Dropbox is scanned from a locally synced folder after the estimator picks it in Chrome. There is no automatic Dropbox cloud connection.' : undefined}
            />
            <Metric label="JR target" value={formatMoney(trust.jr_target_total)} />
            <Metric label="Accepted proposal" value={formatMoney(trust.accepted_proposal_total)} />
            <Metric
              label={trust.replay_mode === 'current' ? 'Current replay' : 'Latest replay'}
              value={formatMoney(trust.replay_total)}
              title={trust.replay_status ? `Replay status: ${trust.replay_status}` : undefined}
            />
            <Metric label="Manual overrides" value={String(trust.manual_override_count || 0)} />
            <Metric label="Typed prices" value={String(trust.manual_price_count || 0)} />
            <Metric label="Unknown materials" value={String(trust.unknown_material_count || 0)} />
            <Metric label="Low confidence" value={String(trust.low_confidence_material_count || 0)} />
          </div>

          {technicalChecks.length > 0 && (
            <div className="mt-4 space-y-2">
              {technicalChecks.map(check => (
                <CheckRow key={check.id} check={check} />
              ))}
            </div>
          )}

          {vendorPriceOverrides.length > 0 && (
            <div className="mt-4 border-t border-white/[0.06] pt-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[10px] font-semibold uppercase text-gray-500">Prices kept on purpose</p>
                <span className="text-[10px] font-semibold uppercase text-gray-500">
                  {trust.vendor_price_override_count || vendorPriceOverrides.length} with a reason
                </span>
              </div>
              <div className="mt-2 divide-y divide-white/[0.05] border-y border-white/[0.06]">
                {vendorPriceOverrides.map((row, index) => (
                  <div key={`${row.decision_id}-${index}`} className="grid gap-1 py-2 text-xs sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-5">
                    <div className="min-w-0">
                      <p className="font-semibold text-gray-200">{row.item_code}</p>
                      <p className="mt-0.5 break-words leading-5 text-gray-500">{row.reason}</p>
                    </div>
                    <div className="text-left tabular-nums text-gray-400 sm:text-right">
                      <p>{formatMoney(row.accepted_price)} kept vs {formatMoney(row.quote_price)}</p>
                      <p className="mt-0.5 text-[11px] text-gray-600">{row.reviewer_name} / {formatDate(row.created_at)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {trust.largest_deltas?.length > 0 && (
            <div className="mt-4 border-t border-white/[0.06] pt-3">
              <p className="text-[10px] font-semibold uppercase text-gray-500">
                {trust.largest_deltas.some(delta => delta.target_source === 'jr') ? 'Largest JR bundle deltas' : 'Largest replay deltas'}
              </p>
              <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
                {trust.largest_deltas.map((delta, index) => (
                  <span key={`${delta.bundle_name}-${index}`} className={delta.status === 'fail' ? 'text-sm text-red-300' : delta.status === 'warn' ? 'text-sm text-amber-300' : 'text-sm text-gray-300'}>
                    {delta.bundle_name || `Bundle ${index + 1}`}: {formatMoney(delta.delta)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {onRecoverEvidence && trust.evidence_recovery_needed && (
            <button type="button" onClick={onRecoverEvidence} className="btn-secondary mt-4 flex items-center justify-center gap-2 text-xs">
              <Upload className="h-3.5 w-3.5" />
              Repair quote receipts
            </button>
          )}
        </div>
      </details>
    </section>
    {selectedConflict && onResolveVendorConflict && (
      <PriceDecisionDialog
        conflict={selectedConflict}
        onClose={() => setSelectedConflict(null)}
        onSubmit={onResolveVendorConflict}
      />
    )}
    </>
  )
}
