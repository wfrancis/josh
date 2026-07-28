import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  Check,
  ChevronDown,
  ChevronUp,
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
  ['needs_you', 'Needs'],
  ['overdue', 'Follow'],
  ['ready_to_send', 'Ready'],
  ['waiting', 'Waiting'],
  ['complete', 'Closed'],
]

const VIEW_DETAILS = {
  needs_you: {
    title: 'Needs your decision',
    description: 'Fix a draft, match an unclear reply, or review a vendor price.',
  },
  overdue: {
    title: 'Follow up today',
    description: 'These vendors are past the expected reply date.',
  },
  ready_to_send: {
    title: 'Ready for approval',
    description: 'These drafts are ready for one final review before sending.',
  },
  waiting: {
    title: 'Waiting on vendors',
    description: 'These requests are sent. The tool is watching for replies and follow-ups.',
  },
  complete: {
    title: 'Closed',
    description: 'These quote requests no longer need work.',
  },
}

const defaultView = (summary) => (
  ['needs_you', 'overdue', 'ready_to_send', 'waiting', 'complete']
    .find((key) => Number(summary?.[key] || 0) > 0)
  || 'ready_to_send'
)

const requestBucket = (request) => {
  const status = normalizeStatus(request.status)
  if (status === 'overdue') return 'overdue'
  if (['send_failed', 'send_uncertain', 'stale', 'needs_review'].includes(status)) {
    return 'needs_you'
  }
  if (['complete', 'received', 'cancelled'].includes(status)) return 'complete'
  return 'waiting'
}

export default function QuoteEmailCenter({ basePath = '/quote-emails' }) {
  const location = useLocation()
  const navigate = useNavigate()
  const params = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  )
  const jobFilter = params.get('job') || ''
  const requestedView = params.get('view')
  const normalizedRequestedView = requestedView ? normalizeStatus(requestedView) : ''
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
  const [expandedGroups, setExpandedGroups] = useState({})
  const [confirmation, setConfirmation] = useState(null)
  const dialogRef = useRef(null)
  const cancelButtonRef = useRef(null)
  const previouslyFocusedRef = useRef(null)
  const hasUnsavedChanges = Object.keys(dirtyGroups).length > 0

  useEffect(() => {
    if (!confirmation) return undefined
    previouslyFocusedRef.current = document.activeElement
    const focusDialog = window.requestAnimationFrame(() => {
      cancelButtonRef.current?.focus()
    })
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setConfirmation(null)
        return
      }
      if (event.key !== 'Tab') return
      const focusable = dialogRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusDialog)
      document.removeEventListener('keydown', handleKeyDown)
      previouslyFocusedRef.current?.focus?.()
    }
  }, [confirmation])

  useEffect(() => {
    if (!hasUnsavedChanges) return undefined
    const warnBeforeLeaving = (event) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeLeaving)
    return () => window.removeEventListener('beforeunload', warnBeforeLeaving)
  }, [hasUnsavedChanges])

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const data = await api.getMaterialQuoteEmailCenter()
      setCenter(data || {})
      setDirtyGroups({})
    } catch (err) {
      setError(err.message || 'Quote Email Center could not load.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const discardUnsavedChanges = (continueAction) => {
    if (!hasUnsavedChanges) {
      continueAction()
      return
    }
    setConfirmation({
      action: 'discard_changes',
      title: 'Discard unsaved email changes?',
      message: 'Your edited vendor email has not been saved yet. Leave this screen and lose those changes?',
      confirmLabel: 'Discard Changes',
      destructive: true,
      onConfirm: continueAction,
    })
  }

  const setFilter = (view) => {
    discardUnsavedChanges(() => {
      const next = new URLSearchParams(location.search)
      next.set('view', view)
      navigate(`${basePath}?${next.toString()}`)
    })
  }

  const clearJobFilter = () => {
    discardUnsavedChanges(() => {
      const next = new URLSearchParams(location.search)
      next.delete('job')
      next.delete('view')
      navigate(`${basePath}${next.toString() ? `?${next}` : ''}`)
    })
  }

  const selectJob = (event) => {
    const nextJobId = event.target.value
    if (String(nextJobId) === String(jobFilter)) return
    discardUnsavedChanges(() => {
      const next = new URLSearchParams(location.search)
      if (nextJobId) next.set('job', nextJobId)
      else next.delete('job')
      // Each bid has its own highest-priority task. Carrying the prior bid's
      // filter forward can show an empty screen and hide the real work.
      next.delete('view')
      navigate(`${basePath}${next.toString() ? `?${next}` : ''}`)
    })
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
      const result = await api.updateQuoteEmailDraftGroup(draft.job_id, group.group_id, {
        vendor_email: group.vendor_email,
        subject: group.subject,
        body: group.body,
      })
      if (result?.draft) {
        setCenter((current) => ({
          ...current,
          drafts: asArray(current.drafts).map((currentDraft) => {
            if (String(currentDraft.job_id) !== String(draft.job_id)) {
              return currentDraft
            }
            const savedGroups = new Map(
              asArray(result.draft.groups).map((savedGroup) => [
                String(savedGroup.group_id),
                savedGroup,
              ]),
            )
            return {
              ...currentDraft,
              ...result.draft,
              // Keep edits in other open vendor emails. The API returns the
              // complete saved draft, but only this one group was submitted.
              groups: asArray(currentDraft.groups).map((currentGroup) => {
                const currentKey = `${draft.job_id}:${currentGroup.group_id}`
                if (
                  String(currentGroup.group_id) !== String(group.group_id)
                  && dirtyGroups[currentKey]
                ) {
                  return currentGroup
                }
                return savedGroups.get(String(currentGroup.group_id)) || currentGroup
              }),
            }
          }),
        }))
      }
      setDirtyGroups((current) => {
        const next = { ...current }
        delete next[key]
        return next
      })
      setExpandedGroups((current) => ({ ...current, [key]: true }))
      setNotice(`Saved the email for ${draft.project_name}. Nothing was sent.`)
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
      readyGroups: ready,
      incompleteGroups: asArray(draft.groups).filter((group) => !group.can_send),
      title: 'Review quote requests',
      message: `Nothing has been sent yet. Confirm the vendor requests for ${draft.project_name}.`,
      confirmLabel: `Send ${ready.length} quote request${ready.length === 1 ? '' : 's'}`,
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
        `${sent} quote request${sent === 1 ? '' : 's'} sent for ${draft.project_name}.`,
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

  const requestSyncOutlook = () => discardUnsavedChanges(syncOutlook)

  const requestDisconnectOutlook = () => {
    discardUnsavedChanges(() => setConfirmation({
      action: 'disconnect',
      title: 'Disconnect Outlook?',
      message: 'Email drafts and saved quote evidence will stay in the bid tool.',
      confirmLabel: 'Disconnect',
      destructive: true,
    }))
  }

  const requestCancelQuoteRequest = (request) => {
    setConfirmation({
      action: 'cancel_request',
      request,
      title: 'Stop vendor follow-ups?',
      message: `This stops automatic follow-ups to ${request.vendor_name || 'this vendor'} for ${request.project_name || 'this bid'}. The email already sent stays saved as proof.`,
      confirmLabel: 'Stop Follow-ups',
      destructive: true,
    })
  }

  const cancelQuoteRequest = async (request) => {
    setBusyKey(`cancel:${request.id}`)
    setError('')
    try {
      await api.cancelQuoteRequest(request.id)
      setNotice(`Follow-ups to ${request.vendor_name || 'the vendor'} were stopped. The sent email is still saved as proof.`)
      await load({ quiet: true })
    } catch (err) {
      setError(err.message || 'The vendor follow-ups could not be stopped.')
    } finally {
      setBusyKey('')
    }
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
    if (pending?.action === 'cancel_request') cancelQuoteRequest(pending.request)
    if (pending?.action === 'discard_changes') pending.onConfirm?.()
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
  // The selected-bid view must describe that bid only. Global totals made it
  // look like a task existed here when it belonged to another bid.
  const scopedSummary = {
    ready_to_send: drafts.reduce(
      (total, draft) => total + (draft.stale ? 0 : Number(draft.ready_group_count || 0)),
      0,
    ),
    needs_you: drafts.filter((draft) => (
      draft.stale || Number(draft.needs_setup_count || 0) > 0
    )).length
      + requests.filter((request) => requestBucket(request) === 'needs_you').length
      + messages.length
      + priceMatches.length,
    overdue: requests.filter((request) => requestBucket(request) === 'overdue').length,
    waiting: requests.filter((request) => requestBucket(request) === 'waiting').length,
    complete: requests.filter((request) => requestBucket(request) === 'complete').length,
  }
  const activeFilter = FILTERS.some(([key]) => key === normalizedRequestedView)
    ? normalizedRequestedView
    : defaultView(scopedSummary)
  const activeViewDetails = VIEW_DETAILS[activeFilter] || VIEW_DETAILS.ready_to_send
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
  const showRequestTimeline = filteredRequests.length > 0
    || ['waiting', 'overdue', 'complete'].includes(activeFilter)
  const showReviewSections = activeFilter === 'needs_you'
    && !center.mailbox_locked
    && (messages.length > 0 || priceMatches.length > 0)
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
      <section className="rounded-lg border border-white/[0.08] bg-white/[0.025] p-3 sm:p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase text-gray-500">
              {selectedJob ? 'Vendor email work for this bid' : 'Vendor email work'}
            </p>
            <h2 className="mt-1 truncate text-lg font-bold text-white">
              {selectedJob?.project_name || 'All Bids'}
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              {selectedJob
                ? [selectedJob.gc_name, [selectedJob.city, selectedJob.state].filter(Boolean).join(', ')].filter(Boolean).join(' | ') || 'Selected bid'
                : activeViewDetails.description}
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
                className="min-h-11 w-full rounded-md border border-white/[0.1] bg-[#0D1322] px-3 py-2.5 text-sm font-semibold text-gray-200 outline-none focus:border-blue-400/50"
              >
                <option value="">All bids</option>
                {bidOptions.map((job) => {
                  const location = [job.city, job.state].filter(Boolean).join(', ')
                  const detail = [job.gc_name, location].filter(Boolean).join(' | ')
                  return (
                    <option key={job.id} value={job.id}>
                      {job.project_name} (Bid #{job.id}){detail ? ` - ${detail}` : ''}
                    </option>
                  )
                })}
              </select>
            </label>

            {selectedJob && (
              <div className="flex gap-2">
                <Link
                  to={`/jobs/${selectedJob.slug || selectedJob.id}?step=quotes`}
                  onClick={(event) => {
                    if (!hasUnsavedChanges) return
                    event.preventDefault()
                    discardUnsavedChanges(() => navigate(`/jobs/${selectedJob.slug || selectedJob.id}?step=quotes`))
                  }}
                  className="inline-flex min-h-11 items-center gap-2 rounded-md border border-white/[0.1] px-3 text-xs font-semibold text-gray-300 hover:bg-white/[0.05]"
                >
                  Back to Bid
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
                <button
                  type="button"
                  onClick={clearJobFilter}
                  className="min-h-11 rounded-md px-3 text-xs font-semibold text-blue-300 hover:bg-blue-500/[0.08] hover:text-white"
                >
                  All Bids
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="mt-3 flex flex-col gap-3 border-t border-white/[0.07] pt-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Mail className="h-4 w-4 text-gray-500" />
              <h2 className="text-sm font-bold text-white">Email</h2>
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
                  onClick={requestSyncOutlook}
                  disabled={busyKey === 'sync'}
                  className="inline-flex min-h-11 items-center gap-2 rounded-md border border-white/[0.1] px-3 py-2 text-xs font-semibold text-gray-300 hover:bg-white/[0.05] disabled:opacity-40"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${busyKey === 'sync' ? 'animate-spin' : ''}`} />
                  Sync
                </button>
                <button
                  type="button"
                  onClick={requestDisconnectOutlook}
                  disabled={busyKey === 'disconnect'}
                  className="inline-flex min-h-11 items-center gap-2 rounded-md px-3 py-2 text-xs font-semibold text-gray-400 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40"
                >
                  <Unplug className="h-3.5 w-3.5" />
                  Disconnect
                </button>
              </>
            ) : (
              <a
                href={api.outlookConnectUrl(returnTo)}
                className="inline-flex min-h-11 items-center gap-2 rounded-md bg-si-orange px-4 py-2.5 text-sm font-bold text-[#0A0F1E] hover:bg-orange-400"
              >
                <Mail className="h-4 w-4" />
                Connect Outlook
              </a>
            )}
          </div>
        </div>
      </section>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-lg border border-red-500/20 bg-red-500/[0.06] px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" aria-live="polite" className="rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3 text-sm text-emerald-300">
          {notice}
        </div>
      )}

      <section className="rounded-lg border border-white/[0.08] bg-white/[0.02] p-2">
        <div className="flex flex-wrap items-center justify-between gap-3 px-2 pb-2 pt-1">
          <div>
            <p className="text-xs font-semibold uppercase text-gray-500">Next up</p>
            <p className="mt-0.5 text-sm font-semibold text-white">{activeViewDetails.title}</p>
          </div>
          <button
            type="button"
            onClick={() => discardUnsavedChanges(() => load({ quiet: true }))}
            disabled={refreshing}
            title="Refresh Quote Email Center"
            aria-label="Refresh Quote Email Center"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-gray-400 hover:bg-white/[0.05] hover:text-white disabled:opacity-40"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="grid grid-cols-5 gap-1 sm:flex">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              aria-pressed={activeFilter === key}
              aria-label={`${VIEW_DETAILS[key].title}: ${Number(scopedSummary[key] || 0)} items`}
              className={`flex min-h-11 min-w-0 items-center justify-between gap-1 rounded-md px-2 text-xs font-semibold sm:flex-1 sm:justify-start sm:gap-2 sm:px-3 sm:text-sm ${
                activeFilter === key
                  ? 'bg-si-orange text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]'
                  : 'text-gray-400 hover:bg-white/[0.05] hover:text-gray-200'
              }`}
            >
              <span className="truncate">{label}</span>
              <span className={`rounded-md px-1.5 py-0.5 text-[11px] tabular-nums ${
                activeFilter === key ? 'bg-black/15 text-white' : 'bg-white/[0.06] text-gray-400'
              }`}>
                {Number(scopedSummary[key] || 0)}
              </span>
            </button>
          ))}
        </div>
      </section>

      {(activeFilter === 'ready_to_send' || activeFilter === 'needs_you') && (
        <section>
          <SectionTitle
            icon={Send}
            title={activeFilter === 'ready_to_send' ? 'Emails ready for approval' : 'Needs your decision'}
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
                            label={draft.stale ? 'Update needed' : (
                              `${draft.ready_group_count || 0} ready`
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
                        className="inline-flex min-h-11 items-center gap-1.5 self-start rounded-md px-3 py-2 text-xs text-gray-400 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40 sm:self-center"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete Draft
                      </button>
                    </div>

                    {draft.stale && (
                      <div className="flex items-start gap-2 border-b border-orange-500/15 bg-orange-500/[0.05] px-4 py-3 text-xs text-orange-300">
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                        <div>
                          <p>This bid changed. Save a fresh draft before sending.</p>
                          <Link
                            to={`/jobs/${draft.slug || draft.job_id}?step=quotes`}
                            className="mt-2 inline-flex min-h-9 items-center gap-1.5 font-semibold text-orange-200 underline decoration-orange-300/40 underline-offset-4 hover:text-white"
                          >
                            Update draft in bid
                            <ArrowRight className="h-3.5 w-3.5" />
                          </Link>
                        </div>
                      </div>
                    )}

                    <div className="divide-y divide-white/[0.06]">
                      {asArray(draft.groups).map((group) => {
                        const key = `${draft.job_id}:${group.group_id}`
                        const isDirty = Boolean(dirtyGroups[key])
                        const contentId = `quote-email-${draft.job_id}-${group.group_id}`
                        const isExpanded = !draft.stale && (
                          !group.can_send || isDirty || Boolean(expandedGroups[key])
                        )
                        return (
                          <div key={group.group_id} className="p-4">
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <h3 className="text-sm font-semibold text-gray-200">
                                    {group.vendor_name || 'Vendor'}
                                  </h3>
                                  <StatusPill
                                    status={draft.stale ? 'stale' : (group.can_send ? 'ready_to_send' : 'needs_setup')}
                                    label={draft.stale ? 'Update in bid' : (group.can_send ? 'Ready' : 'Fix needed')}
                                  />
                                  <span className="text-xs text-gray-500">
                                    {asArray(group.materials).length} material{asArray(group.materials).length === 1 ? '' : 's'}
                                  </span>
                                </div>
                                <p className="mt-1 truncate text-xs text-gray-400">
                                  {draft.stale
                                    ? 'Refresh this email from the bid before sending.'
                                    : group.vendor_email || 'No recipient saved'}
                                </p>
                              </div>
                              {!draft.stale && (
                                <button
                                  type="button"
                                  onClick={() => setExpandedGroups((current) => ({
                                    ...current,
                                    [key]: !isExpanded,
                                  }))}
                                  aria-expanded={isExpanded}
                                  aria-controls={contentId}
                                  className="inline-flex min-h-11 flex-shrink-0 items-center justify-center gap-1.5 rounded-md border border-white/[0.1] px-3 text-xs font-semibold text-gray-300 hover:bg-white/[0.05]"
                                >
                                  {isExpanded
                                    ? <ChevronUp className="h-3.5 w-3.5" />
                                    : <ChevronDown className="h-3.5 w-3.5" />}
                                  {isExpanded ? 'Hide Email' : 'Edit Email'}
                                </button>
                              )}
                            </div>
                            {asArray(group.issues).length > 0 && (
                              <ul className="mt-3 space-y-1 text-xs text-orange-300">
                                {asArray(group.issues).map((issue) => (
                                  <li key={issue}>- {issue}</li>
                                ))}
                              </ul>
                            )}
                            {isExpanded && (
                              <div id={contentId} className="mt-3">
                                <div className="grid gap-3">
                                  <label>
                                    <span className="mb-1.5 block text-xs font-semibold text-gray-400">
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
                                      className="min-h-11 w-full rounded-md border border-white/[0.1] bg-black/20 px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-400/50"
                                    />
                                  </label>
                                  <label>
                                    <span className="mb-1.5 block text-xs font-semibold text-gray-400">
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
                                      className="min-h-11 w-full rounded-md border border-white/[0.1] bg-black/20 px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-400/50"
                                    />
                                  </label>
                                  <label>
                                    <span className="mb-1.5 block text-xs font-semibold text-gray-400">
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
                                  <div className="min-w-0 text-xs text-gray-400">
                                    {asArray(group.materials).map((material) => materialLabel(material)).join(', ')}
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => saveGroup(draft, group)}
                                    disabled={!isDirty || busyKey === `save:${key}`}
                                    className="inline-flex min-h-11 flex-shrink-0 items-center justify-center gap-2 rounded-md border border-white/[0.1] px-3 py-2 text-xs font-semibold text-gray-300 hover:bg-white/[0.05] disabled:opacity-35"
                                  >
                                    {busyKey === `save:${key}`
                                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                      : <Save className="h-3.5 w-3.5" />}
                                    Save Changes
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>

                    <div className="flex flex-col gap-3 border-t border-white/[0.06] bg-black/20 p-4 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-xs text-gray-500">
                        {hasDirtyGroup
                          ? 'Save your changes before sending.'
                          : `${draft.ready_group_count || 0} complete group${draft.ready_group_count === 1 ? '' : 's'} will be reviewed. Incomplete groups will not be sent.`}
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
                        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-si-orange px-4 py-2.5 text-sm font-bold text-[#0A0F1E] hover:bg-orange-400 disabled:cursor-not-allowed disabled:opacity-35"
                      >
                        {busyKey === `send:${draft.job_id}`
                          ? <Loader2 className="h-4 w-4 animate-spin" />
                          : <Send className="h-4 w-4" />}
                        {!outlookConnected
                          ? 'Connect Outlook to send'
                          : `Review ${draft.ready_group_count || 0} email${draft.ready_group_count === 1 ? '' : 's'}`}
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
                : 'Nothing needs to be fixed before sending.'}
            </EmptyState>
          )}
        </section>
      )}

      {showRequestTimeline && (
        <section>
          <SectionTitle
            icon={Inbox}
            title={
              activeFilter === 'waiting'
                ? 'Waiting on Vendors'
                : activeFilter === 'overdue'
                  ? 'Overdue Requests'
                  : activeFilter === 'complete'
                    ? 'Closed Requests'
                    : 'Requests that need attention'
            }
            count={filteredRequests.length}
          />
          {center.mailbox_locked && filteredRequests.length > 0 && (
            <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-500/20 bg-amber-500/[0.06] px-3 py-2.5 text-xs leading-5 text-amber-200">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
              <span><strong>Sync paused.</strong> Saved request details and sent-email proof are still here. Connect Outlook to look for new replies.</span>
            </div>
          )}
          <QuoteRequestTimeline
            requests={filteredRequests}
            onRefresh={() => load({ quiet: true })}
            onError={setError}
            onNotice={setNotice}
            onCancelRequest={requestCancelQuoteRequest}
          />
        </section>
      )}

      {showReviewSections && (
        <>
          {messages.length > 0 && (
            <section>
              <SectionTitle
                icon={Inbox}
                title="Match an Unclear Reply"
                count={messages.length}
              />
              <NeedsMatching
                messages={messages}
                requests={requests}
                onRefresh={() => load({ quiet: true })}
                onError={setError}
                onNotice={setNotice}
              />
            </section>
          )}
          {priceMatches.length > 0 && (
            <section>
              <SectionTitle
                icon={Check}
                title="Review Vendor Prices"
                count={priceMatches.length}
              />
              <PriceReview
                matches={priceMatches}
                requests={requests}
                onRefresh={() => load({ quiet: true })}
                onError={setError}
                onNotice={setNotice}
              />
            </section>
          )}
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
          aria-describedby="quote-confirmation-description"
        >
          <div
            ref={dialogRef}
            className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg border border-white/[0.12] bg-[#111827] shadow-2xl"
          >
            <div className="flex items-start gap-3 border-b border-white/[0.08] px-4 py-4 sm:px-5">
              <div className="min-w-0 flex-1">
                <h2 id="quote-confirmation-title" className="text-base font-bold text-white">
                  {confirmation.title}
                </h2>
                <p id="quote-confirmation-description" className="mt-1 text-sm leading-6 text-gray-400">
                  {confirmation.message}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setConfirmation(null)}
                aria-label="Close confirmation"
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-gray-400 hover:bg-white/[0.06] hover:text-white"
                title="Close confirmation"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {confirmation.action === 'send' && (
              <div className="space-y-3 border-b border-white/[0.08] px-4 py-4 sm:px-5">
                <div className="rounded-md border border-blue-500/20 bg-blue-500/[0.06] px-3 py-2 text-xs text-blue-200">
                  Sending from {outlook.email || outlook.mailbox_email || 'your connected Outlook account'}.
                </div>
                {asArray(confirmation.readyGroups).map((group) => (
                  <div key={group.group_id} className="rounded-md border border-white/[0.08] bg-black/15 p-3">
                    <p className="text-sm font-semibold text-white">{group.vendor_name || 'Vendor'}</p>
                    <p className="mt-0.5 break-all text-xs text-gray-400">{group.vendor_email || 'No recipient'}</p>
                    <p className="mt-2 break-words text-xs text-gray-400">{group.subject || 'No subject'}</p>
                    <p className="mt-2 text-xs font-semibold text-gray-300">
                      {asArray(group.materials).length} material{asArray(group.materials).length === 1 ? '' : 's'}
                    </p>
                    <ul className="mt-1.5 space-y-1 text-xs text-gray-500">
                      {asArray(group.materials).map((material) => (
                        <li key={material.id || material.item_code}>
                          {materialLabel(material)} - {Number(material.quantity || 0).toLocaleString()} {material.unit || ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                {asArray(confirmation.incompleteGroups).length > 0 && (
                  <div className="rounded-md border border-amber-500/20 bg-amber-500/[0.06] px-3 py-2 text-xs leading-5 text-amber-200">
                    {confirmation.incompleteGroups.length} incomplete vendor group{confirmation.incompleteGroups.length === 1 ? '' : 's'} will stay unsent until fixed.
                  </div>
                )}
              </div>
            )}
            <div className="flex justify-end gap-2 px-4 py-3 sm:px-5">
              <button
                type="button"
                onClick={() => setConfirmation(null)}
                ref={cancelButtonRef}
                className="min-h-11 rounded-md border border-white/[0.1] px-4 py-2.5 text-sm font-semibold text-gray-300 hover:bg-white/[0.05]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={runConfirmedAction}
                className={`min-h-11 rounded-md px-4 py-2.5 text-sm font-bold ${
                  confirmation.destructive
                    ? 'bg-red-600 text-white hover:bg-red-500'
                    : 'bg-si-orange text-[#0A0F1E] hover:bg-orange-400'
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
