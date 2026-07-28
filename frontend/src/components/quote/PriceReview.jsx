import { useMemo, useState } from 'react'
import { Ban, Check, Link2, Loader2, ShieldCheck } from 'lucide-react'
import { api } from '../../api'
import {
  EmptyState,
  StatusPill,
  asArray,
  formatMoney,
  materialLabel,
} from './QuoteUi'

export default function PriceReview({
  matches,
  requests,
  onRefresh,
  onError,
  onNotice,
}) {
  const [targets, setTargets] = useState({})
  const [busyId, setBusyId] = useState(null)
  const [confirmingId, setConfirmingId] = useState(null)

  const requestMap = useMemo(
    () => Object.fromEntries(requests.map((request) => [String(request.id), request])),
    [requests],
  )

  const decide = async (match, decision, confirmed = false) => {
    if (decision === 'use_quote' && !confirmed) {
      setConfirmingId(match.id)
      return
    }
    const materialId = decision === 'match_elsewhere'
      ? Number(targets[match.id])
      : undefined
    if (decision === 'match_elsewhere' && !materialId) {
      onError?.('Choose the correct material first.')
      return
    }
    setBusyId(match.id)
    onError?.('')
    try {
      await api.decideQuoteMatch(match.job_id, match.id, {
        decision,
        reviewer_name: 'Estimator',
        reason: 'Estimator reviewed the vendor quote in Quote Emails.',
        material_id: materialId,
        expected_material_id: match.material_id,
        expected_current_price: Number(match.current_price || 0),
      })
      onNotice?.(
        decision === 'use_quote'
          ? 'The exact vendor price was added to the bid.'
          : decision === 'keep_current'
            ? 'The current bid price was kept.'
            : decision === 'match_elsewhere'
              ? 'The price was moved. Confirm Use Quote after the screen refreshes.'
              : 'The vendor price was ignored.',
      )
      setConfirmingId(null)
      await onRefresh?.()
    } catch (err) {
      onError?.(err.message || 'The price decision could not be saved.')
    } finally {
      setBusyId(null)
    }
  }

  if (!matches.length) {
    return <EmptyState>No vendor prices need a decision.</EmptyState>
  }

  return (
    <div className="space-y-3">
      {matches.map((match) => {
        const request = requestMap[String(match.quote_request_id)] || {}
        const materialOptions = asArray(request.materials)
        const currentPrice = Number(match.current_price || match.accepted_price_before || 0)
        const quotePrice = Number(match.quote_price || 0)
        return (
          <article
            key={match.id}
            className="rounded-lg border border-orange-500/20 bg-orange-500/[0.04] p-4"
          >
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill status="needs_you" label="Price Review" />
                  <span className="text-sm font-semibold text-white">
                    {match.project_name || request.project_name || 'Bid'}
                  </span>
                  <span className="text-xs text-gray-500">
                    {request.vendor_name || 'Vendor'}
                  </span>
                </div>
                <h3 className="mt-2 break-words text-sm text-gray-200">
                  {match.item_code
                    ? `${match.item_code} - ${match.material_description || match.description || ''}`
                    : match.material_description || match.description || 'Unmatched material'}
                </h3>
                <div className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                  <div>
                    <p className="text-gray-600">Current bid price</p>
                    <p className="mt-1 font-bold tabular-nums text-gray-200">
                      {formatMoney(currentPrice)}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-600">Vendor quote</p>
                    <p className="mt-1 font-bold tabular-nums text-white">
                      {formatMoney(quotePrice)} / {match.quote_unit || '-'}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-600">Quantity</p>
                    <p className="mt-1 tabular-nums text-gray-300">
                      {Number(match.quantity || 0).toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-600">Bid impact</p>
                    <p className={`mt-1 font-bold tabular-nums ${
                      Number(match.dollar_impact || 0) > 0
                        ? 'text-amber-300'
                        : 'text-emerald-300'
                    }`}>
                      {formatMoney(match.dollar_impact)}
                    </p>
                  </div>
                </div>
                {match.reason && (
                  <p className="mt-3 text-xs text-gray-500">{match.reason}</p>
                )}
                {request.subject && (
                  <p className="mt-1 truncate text-xs text-gray-500">
                    Source email: {request.subject}
                  </p>
                )}
              </div>

              <div className="flex min-w-[240px] flex-col justify-center gap-2">
                {confirmingId === match.id && (
                  <div role="alert" className="rounded-md border border-orange-500/25 bg-orange-500/[0.08] p-3 text-xs text-orange-100">
                    <p className="font-semibold">Use this vendor price?</p>
                    <p className="mt-1 leading-5 text-orange-100/80">
                      This changes the bid from {formatMoney(currentPrice)} to {formatMoney(quotePrice)} per {match.quote_unit || 'unit'} and changes the bid by {formatMoney(match.dollar_impact)}.
                    </p>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => decide(match, 'use_quote', true)}
                        disabled={busyId === match.id}
                        className="min-h-11 rounded-md bg-si-orange px-3 text-xs font-bold text-[#0A0F1E] hover:bg-orange-400 disabled:opacity-40"
                      >
                        Use This Price
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingId(null)}
                        className="min-h-11 rounded-md border border-white/[0.14] px-3 text-xs font-semibold text-white hover:bg-white/[0.08]"
                      >
                        Keep Reviewing
                      </button>
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => decide(match, 'use_quote')}
                    disabled={busyId === match.id}
                    className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md bg-si-orange px-3 py-2.5 text-xs font-bold text-[#0A0F1E] hover:bg-orange-400 disabled:opacity-40"
                  >
                    {busyId === match.id
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <Check className="h-3.5 w-3.5" />}
                    Use Quote
                  </button>
                  <button
                    type="button"
                    onClick={() => decide(match, 'keep_current')}
                    disabled={busyId === match.id || currentPrice <= 0}
                    className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md border border-white/[0.1] px-3 py-2.5 text-xs font-semibold text-gray-300 hover:bg-white/[0.05] disabled:opacity-40"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Keep Current
                  </button>
                </div>
                <div className="flex gap-2">
                  <label className="min-w-0 flex-1">
                    <span className="sr-only">Match this vendor price to another material</span>
                    <select
                      value={targets[match.id] || ''}
                      onChange={(event) => setTargets((current) => ({
                        ...current,
                        [match.id]: event.target.value,
                      }))}
                      className="min-h-11 w-full rounded-md border border-white/[0.1] bg-[#0D1322] px-2 py-2 text-xs text-gray-300 outline-none focus:border-blue-400/50"
                    >
                      <option value="">Match to another material</option>
                      {materialOptions.map((material) => (
                        <option
                          key={material.material_id || material.id}
                          value={material.material_id || material.id}
                        >
                          {materialLabel(material)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() => decide(match, 'match_elsewhere')}
                    disabled={busyId === match.id || !targets[match.id]}
                    title="Match price to selected material"
                    aria-label="Match price to selected material"
                    className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-blue-500/20 bg-blue-500/10 p-2.5 text-blue-300 hover:bg-blue-500/20 disabled:opacity-40"
                  >
                    <Link2 className="h-4 w-4" />
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => decide(match, 'ignore')}
                  disabled={busyId === match.id}
                  className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-semibold text-gray-400 hover:bg-white/[0.05] hover:text-gray-300 disabled:opacity-40"
                >
                  <Ban className="h-3.5 w-3.5" />
                  Ignore This Price
                </button>
              </div>
            </div>
          </article>
        )
      })}
    </div>
  )
}
