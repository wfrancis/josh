import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Check, CheckCircle2, RefreshCw, ShieldAlert, ShieldCheck, Upload, X, XCircle } from 'lucide-react'
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
      <p className="mt-1 break-words text-sm font-semibold leading-5 text-gray-200">{value}</p>
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
              ? 'The material unit price will change to the verified quote. The saved proposal will require recalculation.'
              : 'The accepted price will stay, and this difference will remain visible as a reviewed override.'}
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

export default function ReadinessSummary({ readiness, onRefresh, onRecoverEvidence, onResolveVendorConflict }) {
  const [selectedConflict, setSelectedConflict] = useState(null)
  if (!readiness) return null
  const failed = (readiness.checks || []).filter(check => check.status === 'fail')
  const warnings = (readiness.checks || []).filter(check => check.status === 'warn')
  const important = [...failed, ...warnings]
  const build = readiness.build || {}
  const trust = readiness.trust_summary || {}
  const evidenceRecoveryNeeded = Boolean(trust.evidence_recovery_needed)
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
  const HeaderIcon = readiness.status === 'blocked' ? ShieldAlert : readiness.status === 'warning' ? AlertTriangle : ShieldCheck
  const headerTone = readiness.status === 'blocked'
    ? 'border-red-500/20 bg-red-500/10 text-red-300'
    : readiness.status === 'warning'
      ? 'border-amber-500/20 bg-amber-500/10 text-amber-300'
      : 'border-emerald-500/15 bg-emerald-500/10 text-emerald-300'

  return (
    <>
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
        <Metric
          label="Source evidence"
          value={`${trust.verified_source_count || 0} verified / ${trust.unverified_source_count || 0} unverified`}
        />
        <Metric
          label="Dropbox mode"
          value={trust.vendor_source_mode === 'browser_local_sync_folder' ? 'Local folder only' : 'Not recorded'}
          title={trust.vendor_source_automatic_sync === false ? 'User-started local folder scan; automatic Dropbox cloud sync is not configured.' : undefined}
        />
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

      {evidenceRecoveryNeeded && (
        <div className="mt-4 border-t border-amber-500/20 pt-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-400" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-amber-200">Vendor pricing evidence needs review</p>
              <p className="mt-1 text-xs leading-5 text-gray-400">
                {trust.missing_vendor_receipt_count || 0} accepted vendor price{trust.missing_vendor_receipt_count === 1 ? '' : 's'} lack an exact receipt. {trust.vendor_price_conflict_count || 0} verified quote price{trust.vendor_price_conflict_count === 1 ? '' : 's'} differ from the accepted number. Exact matches link automatically; differences stay blocked until a reviewer records the decision.
              </p>
              <p className="mt-1 text-xs leading-5 text-gray-500">
                Dropbox is scanned from a locally synced folder after the estimator chooses it in Chrome. There is no automatic Dropbox cloud connection.
              </p>
              {trust.quote_source_files_needed?.length > 0 && (
                <p className="mt-2 break-words text-xs leading-5 text-gray-500">
                  Missing originals: {trust.quote_source_files_needed.join(', ')}
                </p>
              )}
              {vendorPriceConflicts.length > 0 && (
                <div className="mt-3 border-t border-amber-500/15 pt-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs font-bold uppercase text-amber-300">Verified quote price differs</p>
                    <span className="text-[10px] font-semibold uppercase text-gray-500">
                      {trust.vendor_price_conflict_count || vendorPriceConflicts.length} conflict{(trust.vendor_price_conflict_count || vendorPriceConflicts.length) === 1 ? '' : 's'}
                    </span>
                  </div>
                  <div className="mt-2 max-h-72 overflow-y-auto border-y border-white/[0.06] sm:hidden">
                    <div className="divide-y divide-white/[0.04]">
                      {vendorPriceConflicts.map((row, index) => (
                        <div key={`mobile-${row.material_id}-${row.source_hash}-${index}`} className="py-3">
                          <div className="flex items-start justify-between gap-3">
                            <p className="min-w-0 break-words text-sm font-semibold text-gray-200">{row.item_code}</p>
                            <p className="flex-shrink-0 text-sm font-semibold tabular-nums text-amber-300">{formatMoney(row.delta)}</p>
                          </div>
                          <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
                            <div>
                              <p className="text-[10px] font-semibold uppercase text-gray-600">Accepted</p>
                              <p className="mt-0.5 tabular-nums text-gray-300">{formatMoney(row.accepted_price)} / {row.accepted_unit}</p>
                            </div>
                            <div>
                              <p className="text-[10px] font-semibold uppercase text-gray-600">Verified quote</p>
                              <p className="mt-0.5 tabular-nums text-gray-300">{formatMoney(row.quote_price)} / {row.quote_unit}</p>
                            </div>
                          </div>
                          <p className="mt-2 break-words text-[11px] leading-4 text-gray-500">{row.source_file || 'Verified quote'}</p>
                          {onResolveVendorConflict && (
                            <button
                              type="button"
                              onClick={() => setSelectedConflict(row)}
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
                          <th className="px-2 py-2 text-right font-semibold">Accepted</th>
                          <th className="px-2 py-2 text-right font-semibold">Quote</th>
                          <th className="px-2 py-2 text-right font-semibold">Difference</th>
                          <th className="px-2 py-2 text-left font-semibold">Source</th>
                          {onResolveVendorConflict && <th className="px-2 py-2 text-right font-semibold">Action</th>}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.04]">
                        {vendorPriceConflicts.map((row, index) => (
                          <tr key={`${row.material_id}-${row.source_hash}-${index}`} className="text-gray-300">
                            <td className="px-2 py-2 font-semibold text-gray-200">{row.item_code}</td>
                            <td className="px-2 py-2 text-right tabular-nums">{formatMoney(row.accepted_price)} / {row.accepted_unit}</td>
                            <td className="px-2 py-2 text-right tabular-nums">{formatMoney(row.quote_price)} / {row.quote_unit}</td>
                            <td className="px-2 py-2 text-right font-semibold tabular-nums text-amber-300">{formatMoney(row.delta)}</td>
                            <td className="max-w-52 truncate px-2 py-2 text-gray-500" title={row.source_file}>{row.source_file || 'Verified quote'}</td>
                            {onResolveVendorConflict && (
                              <td className="px-2 py-2 text-right">
                                <button
                                  type="button"
                                  onClick={() => setSelectedConflict(row)}
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
              )}
            </div>
            {onRecoverEvidence && (
              <button onClick={onRecoverEvidence} className="btn-secondary flex items-center justify-center gap-2 text-sm sm:flex-shrink-0">
                <Upload className="h-4 w-4" />
                Repair quote receipts
              </button>
            )}
          </div>
        </div>
      )}

      {vendorPriceOverrides.length > 0 && (
        <div className="mt-4 border-t border-amber-500/20 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-bold uppercase text-amber-300">Reviewed vendor price overrides</p>
            <span className="text-[10px] font-semibold uppercase text-gray-500">
              {trust.vendor_price_override_count || vendorPriceOverrides.length} documented
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
