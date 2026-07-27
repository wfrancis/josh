import { useEffect, useState } from 'react'
import { Link2, Loader2, MailQuestion, Paperclip, X } from 'lucide-react'
import { api } from '../../api'
import {
  EmptyState,
  StatusPill,
  asArray,
  formatDate,
  normalizeStatus,
} from './QuoteUi'

export default function NeedsMatching({
  messages,
  requests = [],
  onRefresh,
  onError,
  onNotice,
}) {
  const [selected, setSelected] = useState({})
  const [busyId, setBusyId] = useState(null)
  const [clock, setClock] = useState(Date.now())

  useEffect(() => {
    if (!messages.some((message) => message.assignment_in_progress)) return undefined
    const timer = window.setInterval(() => setClock(Date.now()), 5000)
    return () => window.clearInterval(timer)
  }, [messages])

  const assign = async (message) => {
    const candidates = asArray(message.candidates)
    const choice = selected[message.id]
      || (candidates.length === 1
        ? `${candidates[0].job_id}:${candidates[0].quote_request_id}`
        : '')
    const [jobId, requestId] = String(choice).split(':')
    if (!jobId || !requestId) {
      onError?.('Choose the bid and vendor request first.')
      return
    }
    setBusyId(message.id)
    onError?.('')
    try {
      await api.assignInboxMessage(message.id, {
        job_id: Number(jobId),
        request_id: Number(requestId),
        reviewer_name: 'Estimator',
      })
      onNotice?.('The reply is now attached to the selected bid.')
      await onRefresh?.()
    } catch (err) {
      onError?.(err.message || 'The email could not be matched.')
    } finally {
      setBusyId(null)
    }
  }

  const ignore = async (message) => {
    setBusyId(message.id)
    onError?.('')
    try {
      await api.ignoreInboxMessage(message.id)
      onNotice?.('The unrelated email was ignored.')
      await onRefresh?.()
    } catch (err) {
      onError?.(err.message || 'The email could not be ignored.')
    } finally {
      setBusyId(null)
    }
  }

  if (!messages.length) {
    return <EmptyState>No emails need help finding their bid.</EmptyState>
  }

  return (
    <div className="space-y-3">
      {messages.map((message) => {
        const candidates = asArray(message.candidates)
        const options = candidates.length
          ? candidates
          : requests
            .filter((request) => !['complete', 'cancelled'].includes(normalizeStatus(request.status)))
            .map((request) => ({
              id: `request-${request.id}`,
              job_id: request.job_id,
              quote_request_id: request.id,
              project_name: request.project_name,
              vendor_name: request.vendor_name,
            }))
        const retryAt = Date.parse(message.assignment_retry_at || '')
        const canRetryAssignment = message.assignment_retry_available
          || !Number.isFinite(retryAt)
          || clock >= retryAt
        return (
          <article
            key={message.id}
            className="rounded-lg border border-orange-500/20 bg-orange-500/[0.04] p-4"
          >
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(240px,360px)]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill
                    status={message.assignment_in_progress ? 'waiting' : 'needs_you'}
                    label={message.assignment_in_progress ? 'Matching' : 'Needs Matching'}
                  />
                  <span className="text-xs text-gray-600">
                    {formatDate(message.received_at)}
                  </span>
                </div>
                <h3 className="mt-2 break-words text-sm font-semibold text-white">
                  {message.subject || 'No subject'}
                </h3>
                <p className="mt-1 break-all text-xs text-gray-500">
                  {message.sender_email || 'Unknown sender'}
                </p>
                {message.body_text && (
                  <p className="mt-2 line-clamp-3 text-sm text-gray-400">
                    {message.body_text}
                  </p>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {asArray(message.evidence).map((evidence, index) => (
                    <span
                      key={evidence.id || index}
                      className="rounded-md border border-white/[0.08] px-2 py-1 text-[11px] text-gray-400"
                    >
                      {evidence.label || evidence.value || evidence.type || 'Exact clue'}
                    </span>
                  ))}
                  {asArray(message.attachments).map((attachment, index) => (
                    attachment.artifact_path ? (
                      <a
                        key={`${message.id}-attachment-${index}`}
                        href={api.quoteMessageAttachmentUrl(message.id, index)}
                        className="inline-flex items-center gap-1 rounded-md border border-white/[0.08] px-2 py-1 text-[11px] text-gray-400 hover:text-white"
                      >
                        <Paperclip className="h-3 w-3" />
                        {attachment.file_name || `Attachment ${index + 1}`}
                      </a>
                    ) : null
                  ))}
                </div>
              </div>

              <div className="flex flex-col justify-center gap-2">
                <label>
                  <span className="mb-1.5 block text-xs font-semibold text-gray-500">
                    Which bid is this for?
                  </span>
                  <select
                    value={selected[message.id] || (
                      candidates.length === 1
                        ? `${candidates[0].job_id}:${candidates[0].quote_request_id}`
                        : ''
                    )}
                    onChange={(event) => setSelected((current) => ({
                      ...current,
                      [message.id]: event.target.value,
                    }))}
                    disabled={message.assignment_in_progress && !canRetryAssignment}
                    className="w-full rounded-md border border-white/[0.1] bg-[#0D1322] px-3 py-2.5 text-sm text-gray-300 outline-none focus:border-blue-400/50 disabled:opacity-50"
                  >
                    <option value="">Choose a bid and vendor</option>
                    {options.map((candidate) => (
                      <option
                        key={candidate.id || `${candidate.job_id}:${candidate.quote_request_id}`}
                        value={`${candidate.job_id}:${candidate.quote_request_id}`}
                      >
                        {candidate.project_name} - {candidate.vendor_name || 'Vendor'}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={() => assign(message)}
                    disabled={
                      busyId === message.id
                      || (message.assignment_in_progress && !canRetryAssignment)
                    }
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-md bg-si-orange px-3 py-2.5 text-sm font-bold text-white hover:bg-orange-500 disabled:opacity-40"
                  >
                    {busyId === message.id
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <Link2 className="h-4 w-4" />}
                    Use This Bid
                  </button>
                  <button
                    type="button"
                    onClick={() => ignore(message)}
                    disabled={busyId === message.id}
                    className="inline-flex items-center justify-center gap-2 rounded-md border border-white/[0.1] px-3 py-2.5 text-sm font-semibold text-gray-400 hover:bg-white/[0.05] hover:text-white disabled:opacity-40"
                  >
                    <X className="h-4 w-4" />
                    Ignore
                  </button>
                </div>
                {!candidates.length && (
                  <p className="inline-flex items-start gap-1.5 text-xs text-orange-300">
                    <MailQuestion className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                    No exact bid clues were found. Your choice is required.
                  </p>
                )}
              </div>
            </div>
          </article>
        )
      })}
    </div>
  )
}
