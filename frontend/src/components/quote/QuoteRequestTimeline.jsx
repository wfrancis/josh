import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Ban,
  FileText,
  Loader2,
  Mail,
  Paperclip,
  RotateCcw,
} from 'lucide-react'
import { api } from '../../api'
import {
  EmptyState,
  StatusPill,
  asArray,
  formatDate,
  materialLabel,
  normalizeStatus,
} from './QuoteUi'

export default function QuoteRequestTimeline({
  requests,
  onRefresh,
  onError,
  onNotice,
}) {
  const [busyId, setBusyId] = useState(null)
  const [expandedMaterials, setExpandedMaterials] = useState({})

  const runRequestAction = async (request, action) => {
    setBusyId(request.id)
    onError?.('')
    try {
      if (action === 'retry') await api.retryQuoteRequest(request.id)
      else await api.cancelQuoteRequest(request.id)
      onNotice?.(
        action === 'retry'
          ? `Retry started for ${request.vendor_name}.`
          : `Request to ${request.vendor_name} was cancelled.`,
      )
      await onRefresh?.()
    } catch (err) {
      onError?.(err.message || 'The request could not be updated.')
    } finally {
      setBusyId(null)
    }
  }

  if (!requests.length) {
    return <EmptyState>No vendor requests are in this view.</EmptyState>
  }

  return (
    <div className="space-y-3">
      {requests.map((request) => {
        const status = normalizeStatus(request.status)
        const materials = asArray(request.materials)
        const followups = asArray(request.followups)
        const messages = asArray(request.messages)
        const materialsExpanded = Boolean(expandedMaterials[request.id])
        const visibleMaterials = materialsExpanded ? materials : materials.slice(0, 3)
        const hiddenMaterialCount = Math.max(0, materials.length - visibleMaterials.length)
        const canRetry = ['send_failed', 'approved'].includes(status)
        const canCancel = !['complete', 'received', 'cancelled'].includes(status)
        const slug = request.slug || request.job_id
        return (
          <article
            key={request.id}
            className="overflow-hidden rounded-lg border border-white/[0.08] bg-white/[0.025]"
          >
            <div className="flex flex-col gap-3 border-b border-white/[0.06] p-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    to={`/jobs/${slug}?step=quotes`}
                    className="truncate text-sm font-bold text-white hover:text-blue-300"
                  >
                    {request.project_name || 'Bid'}
                  </Link>
                  <span className="text-gray-600">/</span>
                  <span className="truncate text-sm font-semibold text-gray-300">
                    {request.vendor_name || 'Vendor'}
                  </span>
                  <StatusPill status={status} />
                </div>
                <p className="mt-1 break-all text-xs text-gray-500">
                  {request.vendor_email || 'No recipient saved'}
                </p>
                <p className="mt-1 break-words text-xs text-gray-600">
                  {request.subject || 'No subject'}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {canRetry && (
                  <button
                    type="button"
                    onClick={() => runRequestAction(request, 'retry')}
                    disabled={busyId === request.id}
                    className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.1] px-2.5 py-1.5 text-xs font-semibold text-gray-300 hover:bg-white/[0.05] disabled:opacity-50"
                  >
                    {busyId === request.id
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <RotateCcw className="h-3.5 w-3.5" />}
                    Retry
                  </button>
                )}
                {canCancel && (
                  <button
                    type="button"
                    onClick={() => runRequestAction(request, 'cancel')}
                    disabled={busyId === request.id}
                    className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold text-gray-500 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-50"
                  >
                    <Ban className="h-3.5 w-3.5" />
                    Cancel
                  </button>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 divide-x divide-y divide-white/[0.05] border-b border-white/[0.06] sm:grid-cols-4 sm:divide-y-0">
              {[
                ['Sent', formatDate(request.sent_at)],
                ['Reply', formatDate(request.received_at)],
                ['Materials', materials.length],
                ['Follow-ups', followups.length],
              ].map(([label, value]) => (
                <div key={label} className="min-w-0 px-4 py-3 text-xs">
                  <p className="text-gray-600">{label}</p>
                  <p className="mt-1 truncate text-gray-300">{value}</p>
                </div>
              ))}
            </div>

            <div className="divide-y divide-white/[0.05]">
              {visibleMaterials.map((material) => (
                <div
                  key={material.id || material.material_id}
                  className="grid gap-1 px-4 py-2.5 text-xs sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                >
                  <span className="break-words text-gray-300">
                    {materialLabel(material)}
                  </span>
                  <span className="tabular-nums text-gray-500">
                    {Number(material.quantity || 0).toLocaleString()} {material.unit || ''}
                  </span>
                </div>
              ))}
              {hiddenMaterialCount > 0 && (
                <div className="px-4 py-2.5 text-xs">
                  <button
                    type="button"
                    onClick={() => setExpandedMaterials((current) => ({
                      ...current,
                      [request.id]: true,
                    }))}
                    className="font-semibold text-blue-300 hover:text-blue-200"
                  >
                    Show {hiddenMaterialCount} more material{hiddenMaterialCount === 1 ? '' : 's'}
                  </button>
                </div>
              )}
              {materialsExpanded && materials.length > 3 && (
                <div className="px-4 py-2.5 text-xs">
                  <button
                    type="button"
                    onClick={() => setExpandedMaterials((current) => ({
                      ...current,
                      [request.id]: false,
                    }))}
                    className="font-semibold text-blue-300 hover:text-blue-200"
                  >
                    Show fewer materials
                  </button>
                </div>
              )}
            </div>

            <div className="border-t border-white/[0.06] p-4">
              <div className="flex flex-wrap items-center gap-2">
                {request.sent_artifact_hash ? (
                  <a
                    href={api.quoteRequestEvidenceUrl(request.id)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] px-2.5 py-1.5 text-xs text-gray-300 hover:bg-white/[0.05]"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    Sent email proof
                  </a>
                ) : (
                  <StatusPill status="waiting" label="Email proof pending" />
                )}
              </div>
              {request.sent_artifact_hash && (
                <details className="mt-3 text-xs text-gray-600">
                  <summary className="cursor-pointer select-none hover:text-gray-400">
                    Technical details
                  </summary>
                  <p className="mt-1 font-mono text-[10px]">
                    Evidence fingerprint: {request.sent_artifact_hash.slice(0, 12)}
                  </p>
                </details>
              )}

              {messages.length > 0 && (
                <div className="mt-3 space-y-2 border-t border-white/[0.05] pt-3">
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className="grid gap-2 text-xs sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"
                    >
                      <div className="min-w-0">
                        <a
                          href={api.quoteMessageEvidenceUrl(message.id)}
                          className="inline-flex max-w-full items-center gap-1.5 text-blue-300 hover:text-blue-200"
                        >
                          <Mail className="h-3.5 w-3.5 flex-shrink-0" />
                          <span className="truncate">{message.subject || 'Vendor reply'}</span>
                        </a>
                        <div className="mt-1 flex flex-wrap gap-2">
                          {asArray(message.attachments).map((attachment, index) => (
                            attachment.artifact_path ? (
                              <a
                                key={`${message.id}-${index}`}
                                href={api.quoteMessageAttachmentUrl(message.id, index)}
                                className="inline-flex items-center gap-1 text-gray-500 hover:text-gray-300"
                              >
                                <Paperclip className="h-3 w-3" />
                                {attachment.file_name || `Attachment ${index + 1}`}
                              </a>
                            ) : null
                          ))}
                        </div>
                      </div>
                      <span className="text-gray-600">
                        {formatDate(message.received_at || message.sent_at)}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {followups.length > 0 && (
                <div className="mt-3 space-y-2 border-t border-white/[0.05] pt-3">
                  {followups.map((followup) => (
                    <div
                      key={followup.id}
                      className="flex flex-wrap items-center gap-2 text-xs"
                    >
                      <StatusPill status={followup.status || 'scheduled'} />
                      <span className="text-gray-400">
                        Follow-up {followup.followup_number}
                      </span>
                      <span className="text-gray-600">
                        {formatDate(followup.sent_at || followup.scheduled_for)}
                      </span>
                      {followup.error && (
                        <span className="text-red-300">{followup.error}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </article>
        )
      })}
    </div>
  )
}
