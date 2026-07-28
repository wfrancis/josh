import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  Check,
  Inbox,
  Loader2,
  Mail,
  RefreshCw,
  Save,
  Send,
  Trash2,
  Unplug,
  X,
} from 'lucide-react'
import { api } from '../../api'
import NeedsMatching from './NeedsMatching'
import PriceReview from './PriceReview'
import QuoteRequestTimeline from './QuoteRequestTimeline'
import SafeQuoteTest from './SafeQuoteTest'
import {
  EmptyState,
  SectionTitle,
  StatusPill,
  asArray,
  materialLabel,
  normalizeStatus,
} from './QuoteUi'

const FILTERS = [
  ['ready_to_send', 'Ready to Send'],
  ['waiting', 'Waiting'],
  ['overdue', 'Overdue'],
  ['needs_you', 'Needs You'],
  ['complete', 'Complete'],
]

const QUOTE_EMAILS_PATH = '/jobs/bids/quote-emails'

const requestBucket = (request) => {
  const status = normalizeStatus(request.status)
  if (status === 'overdue') return 'overdue'
  if (['send_failed', 'send_uncertain', 'stale', 'needs_review'].includes(status)) {
    return 'needs_you'
  }
  if (['complete', 'received', 'cancelled'].includes(status)) return 'complete'
  return 'waiting'
}

export default function QuoteEmailCenter() {
  const location = useLocation()
  const navigate = useNavigate()
  const params = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  )
  const jobFilter = params.get('job') || ''
  const requestedView = normalizeStatus(params.get('view') || 'ready_to_send')
  const activeFilter = FILTERS.some(([key]) => key === requestedView)
    ? requestedView
    : 'ready_to_send'
  const [center, setCenter] = useState({
    drafts: [],
    requests: [],
    review: { messages: [], price_matches: [] },
    jobs: [],
    summary: {},
    outlook: {},
  })
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busyKey, setBusyKey] = useState('')
  const [dirtyGroups, setDirtyGroups] = useState({})
  const [confirmation, setConfirmation] = useState(null)

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const data = await api.getMaterialQuoteEmailCenter()
      setCenter(data || {})
      setDirtyGroups({})
    } catch (err) {
      setError(err.message || 'Quote Emails could not load.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const setFilter = (view) => {
    const next = new URLSearchParams(location.search)
    next.set('view', view)
    navigate(`${QUOTE_EMAILS_PATH}?${next.toString()}`)
  }

  const clearJobFilter = () => {
    const next = new URLSearchParams(location.search)
    next.delete('job')
    navigate(`${QUOTE_EMAILS_PATH}${next.toString() ? `?${next}` : ''}`)
  }

  const selectJob = (event) => {
    const next = new URLSearchParams(location.search)
    const nextJobId = event.target.value
    if (nextJobId) next.set('job', nextJobId)
    else next.delete('job')
    navigate(`${QUOTE_EMAILS_PATH}${next.toString() ? `?${next}` : ''}`)
  }

  const updateDraftGroup = (jobId, groupId, field, value) => {
    const key = `${jobId}:${groupId}`
    setCenter((current) => ({
      ...current,
      drafts: asArray(current.drafts).map((draft) =>
        String(draft.job_id) === String(jobId)
          ? {
            ...draft,
            groups: asArray(draft.groups).map((group) =>
              String(group.group_id) === String(groupId)
                ? { ...group, [field]: value }
                : group,
            ),
          }
          : draft,
      ),
    }))
    setDirtyGroups((current) => ({ ...current, [key]: true }))
  }

  const saveGroup = async (draft, group) => {
    const key = `${draft.job_id}:${group.group_id}`
    setBusyKey(`save:${key}`)
    setError('')
    setNotice('')
    try {
      await api.updateQuoteEmailDraftGroup(draft.job_id, group.group_id, {
        vendor_email: group.vendor_email,
        subject: group.subject,
        body: group.body,
      })
      setNotice(`Saved the email for ${draft.project_name}. Nothing was sent.`)
      await load({ quiet: true })
    } catch (err) {
      setError(err.message || 'The email changes could not be saved.')
    } finally {
      setBusyKey('')
    }
  }

  const requestSendDraft = (draft) => {
    const dirty = asArray(draft.groups).some(
      (group) => dirtyGroups[`${draft.job_id}:${group.group_id}`],
    )
    if (dirty) {
      setError('Save the email changes before sending.')
      return
    }
    const ready = asArray(draft.groups).filter((group) => group.can_send)
    if (!ready.length) {
      setError('Fix at least one vendor email before sending.')
      return
    }
    setConfirmation({
      action: 'send',
      draft,
      title: 'Send vendor emails?',
      message: `Send ${ready.length} vendor email${ready.length === 1 ? '' : 's'} for ${draft.project_name}?`,
      confirmLabel: ready.length === 1 ? 'Send Email' : 'Send Emails',
    })
  }

  const sendDraft = async (draft) => {
    setBusyKey(`send:${draft.job_id}`)
    setError('')
    setNotice('')
    try {
      const result = await api.sendQuoteEmailDraft(draft.job_id, {
        reviewer_name: draft.prepared_by || 'Estimator',
      })
      const sent = Number(result.sent_group_count || 0)
      setNotice(
        `${sent} vendor email${sent === 1 ? '' : 's'} sent for ${draft.project_name}.`,
      )
      await load({ quiet: true })
      setFilter(sent ? 'waiting' : 'needs_you')
    } catch (err) {
      setError(err.message || 'The vendor emails could not be sent.')
    } finally {
      setBusyKey('')
    }
  }

  const requestDeleteDraft = (draft) => {
    setConfirmation({
      action: 'delete',
      draft,
      title: 'Delete saved draft?',
      message: `Delete the saved email draft for ${draft.project_name}? No email will be sent.`,
      confirmLabel: 'Delete Draft',
      destructive: true,
    })
  }

  const deleteDraft = async (draft) => {
    setBusyKey(`delete:${draft.job_id}`)
    setError('')
    try {
      await api.deleteQuoteEmailDraft(draft.job_id)
      setNotice('The saved draft was deleted. No email was sent.')
      await load({ quiet: true })
    } catch (err) {
      setError(err.message || 'The draft could not be deleted.')
    } finally {
      setBusyKey('')
    }
  }

  const syncOutlook = async () => {
    setBusyKey('sync')
    setError('')
    try {
      await api.syncOutlook()
      setNotice('Outlook is up to date.')
      await load({ quiet: true })
    } catch (err) {
      setError(err.message || 'Outlook could not sync.')
    } finally {
      setBusyKey('')
    }
  }

  const requestDisconnectOutlook = () => {
    setConfirmation({
      action: 'disconnect',
      title: 'Disconnect Outlook?',
      message: 'Email drafts and saved quote evidence will stay in the bid tool.',
      confirmLabel: 'Disconnect',
      destructive: true,
    })
  }

  const disconnectOutlook = async () => {
    setBusyKey('disconnect')
    setError('')
    try {
      await api.disconnectOutlook()
      setNotice('Outlook was disconnected. Saved bid drafts remain.')
      await load({ quiet: true })
    } catch (err) {
      setError(err.message || 'Outlook could not disconnect.')
    } finally {
      setBusyKey('')
    }
  }

  const runConfirmedAction = () => {
    const pending = confirmation
    setConfirmation(null)
    if (pending?.action === 'send') sendDraft(pending.draft)
    if (pending?.action === 'delete') deleteDraft(pending.draft)
    if (pending?.action === 'disconnect') disconnectOutlook()
  }

  const drafts = asArray(center.drafts).filter(
    (draft) => !jobFilter || String(draft.job_id) === String(jobFilter),
  )
  const requests = asArray(center.requests).filter(
    (request) => !jobFilter || String(request.job_id) === String(jobFilter),
  )
  const messages = asArray(center.review?.messages).filter((message) => {
    if (!jobFilter) return true
    if (String(message.matched_job_id || '') === String(jobFilter)) return true
    return asArray(message.candidates).some(
      (candidate) => String(candidate.job_id) === String(jobFilter),
    )
  })
  const priceMatches = asArray(center.review?.price_matches).filter(
    (match) => !jobFilter || String(match.job_id) === String(jobFilter),
  )
  const filteredDrafts = drafts.filter((draft) => (
    activeFilter === 'ready_to_send'
      ? Number(draft.ready_group_count || 0) > 0 && !draft.stale
      : activeFilter === 'needs_you'
        ? draft.stale || Number(draft.needs_setup_count || 0) > 0
        : false
  ))
  const filteredRequests = requests.filter(
    (request) => requestBucket(request) === activeFilter,
  )
  const selectedJob = asArray(center.jobs).find(
    (job) => String(job.id) === String(jobFilter),
  )
  const bidOptions = useMemo(
    () => asArray(center.jobs).slice().sort((left, right) => (
      String(left.project_name || '').localeCompare(String(right.project_name || ''))
    )),
    [center.jobs],
  )
  const outlook = center.outlook || {}
  const outlookConnected = Boolean(
    outlook.session_authenticated ?? outlook.connected,
  )
  const returnTo = `${location.pathname}${location.search}`

  if (loading) {
    return (
      <div className="flex min-h-[360px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-white/[0.08] bg-white/[0.025] p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase text-gray-500">
              {selectedJob ? 'Quote emails for this bid' : 'Quote email inbox'}
            </p>
            <h2 className="mt-1 truncate text-lg font-bold text-white">
              {selectedJob?.project_name || 'All Bids'}
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              {selectedJob
                ? [selectedJob.gc_name, [selectedJob.city, selectedJob.state].filter(Boolean).join(', ')].filter(Boolean).join(' | ') || 'Selected bid'
                : 'Choose a bid to work on one email thread at a time.'}
            </p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="block min-w-0 sm:w-[320px]">
              <span className="mb-1.5 flex items-center gap-2 text-xs font-semibold text-gray-500">
                <Briefcase className="h-3.5 w-3.5" />
                {selectedJob ? 'Switch bid' : 'Choose a bid'}
              </span>
              <select
                value={jobFilter}
                onChange={selectJob}
                className="w-full rounded-md border border-white/[0.1] bg-[#0D1322] px-3 py-2.5 text-sm font-semibold text-gray-200 outline-none focus:border-blue-400/50"
              >
                <option value="">All bids</option>
                {bidOptions.map((job) => {
                  const location = [job.city, job.state].filter(Boolean).join(', ')
                  const detail = [job.gc_name, location].filter(Boolean).join(' | ')
                  return (
                    <option key={job.id} value={job.id}>
                      {job.project_name}{detail ? ` - ${detail}` : ''}
                    </option>
                  )
                })}
              </select>
            </label>

            {selectedJob && (
              <div className="flex gap-2">
                <Link
                  to={`/jobs/${selectedJob.slug || selectedJob.id}?step=quotes`}
                  className="inline-flex min-h-10 items-center gap-2 rounded-md border border-white/[0.1] px-3 text-xs font-semibold text-gray-300 hover:bg-white/[0.05]"
                >
                  Back to Bid
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
                <button
                  type="button"
                  onClick={clearJobFilter}
                  className="min-h-10 rounded-md px-3 text-xs font-semibold text-blue-300 hover:bg-blue-500/[0.08] hover:text-white"
                >
                  All Bids
                </button>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="border-b border-white/[0.07] pb-4">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Mail className="h-4 w-4 text-gray-500" />
              <h2 className="text-sm font-bold text-white">Outlook</h2>
              <StatusPill
                status={outlookConnected ? 'connected' : 'needs_setup'}
                label={outlookConnected ? 'Connected' : 'Not Connected'}
              />
            </div>
            <p className="mt-1 break-words text-xs text-gray-500">
              {outlookConnected
                ? outlook.email || outlook.mailbox_email || 'Microsoft mailbox connected'
                : 'Connect Outlook to send requests and read vendor replies.'}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {outlookConnected ? (
              <>
                <button
                  type="button"
                  onClick={syncOutlook}
                  disabled={busyKey === 'sync'}
                  className="inline-flex items-center gap-2 rounded-md border border-white/[0.1] px-3 py-2 text-xs font-semibold text-gray-300 hover:bg-white/[0.05] disabled:opacity-40"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${busyKey === 'sync' ? 'animate-spin' : ''}`} />
                  Sync
                </button>
                <button
                  type="button"
                  onClick={requestDisconnectOutlook}
                  disabled={busyKey === 'disconnect'}
                  className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-semibold text-gray-500 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40"
                >
                  <Unplug className="h-3.5 w-3.5" />
                  Disconnect
                </button>
              </>
            ) : (
              <a
                href={api.outlookConnectUrl(returnTo)}
                className="inline-flex items-center gap-2 rounded-md bg-si-orange px-4 py-2.5 text-sm font-bold text-white hover:bg-orange-500"
              >
                <Mail className="h-4 w-4" />
                Connect Outlook
              </a>
            )}
          </div>
        </div>
      </section>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/[0.06] px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3 text-sm text-emerald-300">
          {notice}
        </div>
      )}

      <div className="grid grid-cols-2 gap-1 border-b border-white/[0.07] pb-1 sm:flex sm:pb-0">
        {FILTERS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={`flex min-h-10 items-center justify-between gap-2 rounded-md border-b-2 px-3 text-sm font-semibold sm:flex-shrink-0 sm:justify-start sm:rounded-none ${
              activeFilter === key
                ? 'border-si-orange bg-white/[0.05] text-white sm:bg-transparent'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            {label}
            <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[11px] tabular-nums text-gray-400">
              {Number(center.summary?.[key] || 0)}
            </span>
          </button>
        ))}
        <button
          type="button"
          onClick={() => load({ quiet: true })}
          disabled={refreshing}
          title="Refresh Quote Emails"
          className="hidden h-10 w-10 items-center justify-center rounded-md text-gray-500 hover:bg-white/[0.04] hover:text-white disabled:opacity-40 sm:ml-auto sm:flex sm:flex-shrink-0 sm:rounded-none"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {(activeFilter === 'ready_to_send' || activeFilter === 'needs_you') && (
        <section>
          <SectionTitle
            icon={Send}
            title={activeFilter === 'ready_to_send' ? 'Email Drafts' : 'Drafts Needing Setup'}
            count={filteredDrafts.length}
          />
          {filteredDrafts.length ? (
            <div className="space-y-4">
              {filteredDrafts.map((draft) => {
                const hasDirtyGroup = asArray(draft.groups).some(
                  (group) => dirtyGroups[`${draft.job_id}:${group.group_id}`],
                )
                return (
                  <article
                    key={draft.job_id}
                    className="overflow-hidden rounded-lg border border-white/[0.08] bg-white/[0.025]"
                  >
                    <div className="flex flex-col gap-3 border-b border-white/[0.06] p-4 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Link
                            to={`/jobs/${draft.slug || draft.job_id}?step=quotes`}
                            className="text-sm font-bold text-white hover:text-blue-300"
                          >
                            {draft.project_name}
                          </Link>
                          <StatusPill
                            status={draft.stale ? 'stale' : (
                              draft.ready_group_count ? 'ready_to_send' : 'needs_setup'
                            )}
                            label={draft.stale ? 'Bid Changed' : (
                              `${draft.ready_group_count || 0} Ready`
                            )}
                          />
                        </div>
                        <p className="mt-1 text-xs text-gray-500">
                          {draft.gc_name || 'No GC listed'} - {draft.group_count} vendor group{draft.group_count === 1 ? '' : 's'}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => requestDeleteDraft(draft)}
                        disabled={busyKey === `delete:${draft.job_id}`}
                        title="Delete saved draft"
                        className="inline-flex items-center gap-1.5 self-start rounded-md px-2.5 py-1.5 text-xs text-gray-500 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40 sm:self-center"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete Draft
                      </button>
                    </div>

                    {draft.stale && (
                      <div className="flex items-start gap-2 border-b border-orange-500/15 bg-orange-500/[0.05] px-4 py-3 text-xs text-orange-300">
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                        This bid changed. Open the bid and save a fresh email draft before sending.
                      </div>
                    )}

                    <div className="divide-y divide-white/[0.06]">
                      {asArray(draft.groups).map((group) => {
                        const key = `${draft.job_id}:${group.group_id}`
                        const isDirty = Boolean(dirtyGroups[key])
                        return (
                          <div key={group.group_id} className="p-4">
                            <div className="mb-3 flex flex-wrap items-center gap-2">
                              <h3 className="text-sm font-semibold text-gray-200">
                                {group.vendor_name || 'Vendor'}
                              </h3>
                              <StatusPill
                                status={group.can_send ? 'ready_to_send' : 'needs_setup'}
                                label={group.can_send ? 'Ready' : 'Needs Setup'}
                              />
                              <span className="text-xs text-gray-600">
                                {asArray(group.materials).length} material{asArray(group.materials).length === 1 ? '' : 's'}
                              </span>
                            </div>
                            {asArray(group.issues).length > 0 && (
                              <ul className="mb-3 space-y-1 text-xs text-orange-300">
                                {asArray(group.issues).map((issue) => (
                                  <li key={issue}>- {issue}</li>
                                ))}
                              </ul>
                            )}
                            <div className="grid gap-3">
                              <label>
                                <span className="mb-1.5 block text-xs font-semibold text-gray-500">
                                  Recipient
                                </span>
                                <input
                                  type="email"
                                  value={group.vendor_email || ''}
                                  onChange={(event) => updateDraftGroup(
                                    draft.job_id,
                                    group.group_id,
                                    'vendor_email',
                                    event.target.value,
                                  )}
                                  className="w-full rounded-md border border-white/[0.1] bg-black/20 px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-400/50"
                                />
                              </label>
                              <label>
                                <span className="mb-1.5 block text-xs font-semibold text-gray-500">
                                  Subject
                                </span>
                                <input
                                  value={group.subject || ''}
                                  onChange={(event) => updateDraftGroup(
                                    draft.job_id,
                                    group.group_id,
                                    'subject',
                                    event.target.value,
                                  )}
                                  className="w-full rounded-md border border-white/[0.1] bg-black/20 px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-400/50"
                                />
                              </label>
                              <label>
                                <span className="mb-1.5 block text-xs font-semibold text-gray-500">
                                  Email
                                </span>
                                <textarea
                                  rows={6}
                                  value={group.body || ''}
                                  onChange={(event) => updateDraftGroup(
                                    draft.job_id,
                                    group.group_id,
                                    'body',
                                    event.target.value,
                                  )}
                                  className="w-full resize-y rounded-md border border-white/[0.1] bg-black/20 px-3 py-2 text-sm leading-relaxed text-gray-300 outline-none focus:border-blue-400/50"
                                />
                              </label>
                            </div>
                            <div className="mt-3 flex flex-col gap-2 border-t border-white/[0.05] pt-3 sm:flex-row sm:items-center sm:justify-between">
                              <div className="min-w-0 text-xs text-gray-500">
                                {asArray(group.materials).map((material) => materialLabel(material)).join(', ')}
                              </div>
                              <button
                                type="button"
                                onClick={() => saveGroup(draft, group)}
                                disabled={!isDirty || busyKey === `save:${key}`}
                                className="inline-flex flex-shrink-0 items-center justify-center gap-2 rounded-md border border-white/[0.1] px-3 py-2 text-xs font-semibold text-gray-300 hover:bg-white/[0.05] disabled:opacity-35"
                              >
                                {busyKey === `save:${key}`
                                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  : <Save className="h-3.5 w-3.5" />}
                                Save Changes
                              </button>
                            </div>
                          </div>
                        )
                      })}
                    </div>

                    <div className="flex flex-col gap-3 border-t border-white/[0.06] bg-black/20 p-4 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-xs text-gray-500">
                        {hasDirtyGroup
                          ? 'Save your changes before sending.'
                          : `${draft.ready_group_count || 0} complete group${draft.ready_group_count === 1 ? '' : 's'} will send. Incomplete groups stay here.`}
                      </p>
                      <button
                        type="button"
                        onClick={() => requestSendDraft(draft)}
                        disabled={
                          !outlookConnected
                          || draft.stale
                          || !draft.ready_group_count
                          || hasDirtyGroup
                          || busyKey === `send:${draft.job_id}`
                        }
                        className="inline-flex items-center justify-center gap-2 rounded-md bg-si-orange px-4 py-2.5 text-sm font-bold text-white hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-35"
                      >
                        {busyKey === `send:${draft.job_id}`
                          ? <Loader2 className="h-4 w-4 animate-spin" />
                          : <Send className="h-4 w-4" />}
                        Approve & Send
                      </button>
                    </div>
                  </article>
                )
              })}
            </div>
          ) : (
            <EmptyState>
              {activeFilter === 'ready_to_send'
                ? 'No saved bid emails are ready to send.'
                : 'No saved drafts need setup.'}
            </EmptyState>
          )}
        </section>
      )}

      {(activeFilter === 'waiting'
        || activeFilter === 'overdue'
        || activeFilter === 'complete'
        || activeFilter === 'needs_you') && (
        <section>
          <SectionTitle
            icon={Inbox}
            title={
              activeFilter === 'waiting'
                ? 'Waiting on Vendors'
                : activeFilter === 'overdue'
                  ? 'Overdue Requests'
                  : activeFilter === 'complete'
                    ? 'Completed Requests'
                    : 'Requests Needing Help'
            }
            count={filteredRequests.length}
          />
          {center.mailbox_locked ? (
            <EmptyState>Connect Outlook to read request and reply history.</EmptyState>
          ) : (
            <QuoteRequestTimeline
              requests={filteredRequests}
              onRefresh={() => load({ quiet: true })}
              onError={setError}
              onNotice={setNotice}
            />
          )}
        </section>
      )}

      {activeFilter === 'needs_you' && (
        <>
          <section>
            <SectionTitle
              icon={Inbox}
              title="Needs Matching"
              count={center.mailbox_locked ? 'Hidden' : messages.length}
            />
            {center.mailbox_locked ? (
              <EmptyState>Connect Outlook to review unmatched replies.</EmptyState>
            ) : (
              <NeedsMatching
                messages={messages}
                requests={requests}
                onRefresh={() => load({ quiet: true })}
                onError={setError}
                onNotice={setNotice}
              />
            )}
          </section>
          <section>
            <SectionTitle
              icon={Check}
              title="Price Review"
              count={center.mailbox_locked ? 'Hidden' : priceMatches.length}
            />
            {center.mailbox_locked ? (
              <EmptyState>Connect Outlook to review vendor prices.</EmptyState>
            ) : (
              <PriceReview
                matches={priceMatches}
                requests={requests}
                onRefresh={() => load({ quiet: true })}
                onError={setError}
                onNotice={setNotice}
              />
            )}
          </section>
        </>
      )}

      <SafeQuoteTest
        jobs={asArray(center.jobs)}
        defaultJobId={jobFilter}
      />

      {confirmation && createPortal(
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-3 sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="quote-confirmation-title"
          onClick={() => setConfirmation(null)}
        >
          <div
            className="w-full max-w-md overflow-hidden rounded-lg border border-white/[0.12] bg-[#111827] shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start gap-3 border-b border-white/[0.08] px-4 py-4 sm:px-5">
              <div className="min-w-0 flex-1">
                <h2 id="quote-confirmation-title" className="text-base font-bold text-white">
                  {confirmation.title}
                </h2>
                <p className="mt-1 text-sm leading-6 text-gray-400">
                  {confirmation.message}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setConfirmation(null)}
                className="rounded-md p-2 text-gray-500 hover:bg-white/[0.06] hover:text-white"
                title="Close confirmation"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex justify-end gap-2 px-4 py-3 sm:px-5">
              <button
                type="button"
                onClick={() => setConfirmation(null)}
                className="rounded-md border border-white/[0.1] px-4 py-2.5 text-sm font-semibold text-gray-300 hover:bg-white/[0.05]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={runConfirmedAction}
                className={`rounded-md px-4 py-2.5 text-sm font-bold text-white ${
                  confirmation.destructive
                    ? 'bg-red-600 hover:bg-red-500'
                    : 'bg-si-orange hover:bg-orange-500'
                }`}
              >
                {confirmation.confirmLabel}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}
