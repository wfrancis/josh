import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertTriangle,
  Ban,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  ExternalLink,
  FastForward,
  FileText,
  History,
  Inbox,
  Link2,
  Loader2,
  Mail,
  Paperclip,
  Play,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldCheck,
  TestTube2,
  Unplug,
  X,
  XCircle,
} from 'lucide-react'
import { api } from '../api'

const SUMMARY_STATUSES = [
  { key: 'sent', label: 'Sent' },
  { key: 'waiting', label: 'Waiting' },
  { key: 'overdue', label: 'Overdue' },
  { key: 'received', label: 'Received' },
  { key: 'needs_josh', label: 'Needs Josh' },
  { key: 'complete', label: 'Complete' },
]

const SIMULATION_SCENARIOS = [
  { value: 'all', label: 'Run every safety test' },
  { value: 'normal_reply', label: 'Normal vendor reply' },
  { value: 'changed_subject', label: 'Reply with changed subject' },
  { value: 'standalone_email', label: 'New email, not a reply' },
  { value: 'ambiguous_bid', label: 'Could match two bids' },
  { value: 'partial_quote', label: 'Only some prices returned' },
  { value: 'changed_price', label: 'Existing price changed' },
  { value: 'wrong_unit', label: 'Wrong pricing unit' },
  { value: 'duplicate_reply', label: 'Same reply received twice' },
  { value: 'broken_attachment', label: 'Unreadable attachment' },
  { value: 'no_response', label: 'No response and follow-ups' },
  { value: 'materials_changed', label: 'Bid changed after sending' },
  { value: 'send_failure', label: 'Email could not send' },
]

const STATUS_STYLES = {
  sent: 'border-blue-500/20 bg-blue-500/10 text-blue-300',
  sending: 'border-blue-500/20 bg-blue-500/10 text-blue-300',
  waiting: 'border-gray-500/20 bg-gray-500/10 text-gray-300',
  overdue: 'border-amber-500/20 bg-amber-500/10 text-amber-300',
  received: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-300',
  received_partial: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-300',
  needs_josh: 'border-orange-500/20 bg-orange-500/10 text-orange-300',
  needs_matching: 'border-orange-500/20 bg-orange-500/10 text-orange-300',
  needs_review: 'border-orange-500/20 bg-orange-500/10 text-orange-300',
  stale: 'border-orange-500/20 bg-orange-500/10 text-orange-300',
  send_failed: 'border-red-500/20 bg-red-500/10 text-red-300',
  send_uncertain: 'border-orange-500/20 bg-orange-500/10 text-orange-300',
  uncertain: 'border-orange-500/20 bg-orange-500/10 text-orange-300',
  approved: 'border-blue-500/20 bg-blue-500/10 text-blue-300',
  complete: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
  passed: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
  pass: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
  connected: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
  running: 'border-blue-500/20 bg-blue-500/10 text-blue-300',
  scheduled: 'border-blue-500/20 bg-blue-500/10 text-blue-300',
  failed: 'border-red-500/20 bg-red-500/10 text-red-300',
  fail: 'border-red-500/20 bg-red-500/10 text-red-300',
  cancelled: 'border-gray-500/20 bg-gray-500/10 text-gray-400',
  ignored: 'border-gray-500/20 bg-gray-500/10 text-gray-400',
}

const asArray = (value) => {
  if (Array.isArray(value)) return value
  if (typeof value === 'string') return asArray(parseJson(value, []))
  if (Array.isArray(value?.items)) return value.items
  if (Array.isArray(value?.messages)) return value.messages
  return []
}

const normalizeStatus = (value) =>
  String(value || 'waiting').trim().toLowerCase().replace(/[\s-]+/g, '_')

const titleize = (value) =>
  String(value || '').replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())

const formatDate = (value) => {
  if (!value) return 'Not yet'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

const formatMoney = (value) => {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  return amount.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

const parseJson = (value, fallback = {}) => {
  if (!value) return fallback
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return fallback
  }
}

const materialLabel = (material) =>
  [
    material?.item_code,
    material?.description || material?.material_description || material?.product_name || material?.name,
  ].filter(Boolean).join(' · ') || 'Unnamed material'

const materialQuantity = (material) =>
  Number(material?.quantity ?? material?.order_qty ?? material?.installed_qty ?? 0)

const issueLabel = (issue) => {
  if (typeof issue === 'string') return issue
  if (issue?.type && issue?.value) return `${titleize(issue.type)}: ${issue.value}`
  return issue?.message || issue?.reason || issue?.code || issue?.value || issue?.type || 'Needs review'
}

const unresolvedGroupIssues = (group) => {
  const emailReady = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(group?.vendor_email || '')
  const vendorReady = Boolean(group?.vendor_name && normalizeStatus(group.vendor_name) !== 'unassigned')
  return asArray(group?.issues).filter((issue) => {
    const label = issueLabel(issue)
    if (/email|contact/i.test(label)) return !emailReady
    if (/assign.*vendor|vendor.*required/i.test(label)) return !vendorReady
    return true
  })
}

function StatusPill({ status, label }) {
  const normalized = normalizeStatus(status)
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold ${STATUS_STYLES[normalized] || STATUS_STYLES.waiting}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label || titleize(normalized)}
    </span>
  )
}

function SectionHeading({ icon: Icon, title, count, action }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <Icon className="h-4 w-4 flex-shrink-0 text-gray-500" />
        <h2 className="text-sm font-bold text-white">{title}</h2>
        {count != null && (
          <span className="rounded-md bg-white/[0.06] px-2 py-0.5 text-xs font-semibold text-gray-400">{count}</span>
        )}
      </div>
      {action}
    </div>
  )
}

function EmptyRow({ children }) {
  return (
    <div className="rounded-lg border border-dashed border-white/[0.08] px-4 py-7 text-center text-sm text-gray-500">
      {children}
    </div>
  )
}

export default function MaterialQuotes({ job, onJobRefresh, onGoBack, onContinue, onCompletionChange }) {
  const jobId = job?.id
  const [activeTab, setActiveTab] = useState('live')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [workflow, setWorkflow] = useState({})
  const [groups, setGroups] = useState([])
  const [review, setReview] = useState({ messages: [], price_matches: [] })
  const [outlook, setOutlook] = useState({})
  const [inboxMessages, setInboxMessages] = useState([])
  const [reviewerName, setReviewerName] = useState(job?.salesperson || '')
  const [actionKey, setActionKey] = useState('')
  const [confirmAction, setConfirmAction] = useState(null)
  const [targetMaterials, setTargetMaterials] = useState({})
  const [targetRequests, setTargetRequests] = useState({})
  const [historyIndex, setHistoryIndex] = useState(job?.materials?.length ? '0' : '')
  const [priceHistory, setPriceHistory] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [simulationScenario, setSimulationScenario] = useState('all')
  const [simulation, setSimulation] = useState(null)

  const loadLiveData = useCallback(async ({ quiet = false } = {}) => {
    if (!jobId) return
    if (quiet) setRefreshing(true)
    else setLoading(true)
    setError('')

    const results = await Promise.allSettled([
      api.getQuoteWorkflow(jobId),
      api.getQuoteInboxReview(),
    ])

    const [workflowResult, inboxResult] = results
    const succeeded = results.filter((result) => result.status === 'fulfilled').length

    if (workflowResult.status === 'fulfilled') {
      setWorkflow(workflowResult.value || {})
    }

    const workflowGroups = workflowResult.status === 'fulfilled'
      ? asArray(workflowResult.value?.groups)
      : []
    if (workflowResult.status === 'fulfilled') {
      setGroups(workflowGroups)
    }

    if (workflowResult.status === 'fulfilled' && workflowResult.value?.review) {
      setReview(workflowResult.value.review)
    }

    const resolvedOutlook = workflowResult.status === 'fulfilled'
      ? workflowResult.value?.outlook || {}
      : {}
    setOutlook(resolvedOutlook)

    if (inboxResult.status === 'fulfilled') {
      setInboxMessages(asArray(inboxResult.value))
    }

    const sessionConnected = resolvedOutlook.session_authenticated !== undefined
      ? Boolean(resolvedOutlook.session_authenticated)
      : Boolean(resolvedOutlook.connected || normalizeStatus(resolvedOutlook.status) === 'connected')
    const unexpectedFailures = results.filter((result, index) => (
      result.status === 'rejected' && !(!sessionConnected && index === 1)
    ))

    if (!succeeded) {
      const firstError = results.find((result) => result.status === 'rejected')?.reason
      setError(firstError?.message || 'Material Quotes could not load.')
    } else if (unexpectedFailures.length) {
      setError('Some quote information could not load. Refresh to try again.')
    }

    setLoading(false)
    setRefreshing(false)
  }, [jobId])

  useEffect(() => {
    loadLiveData()
  }, [loadLiveData])

  useEffect(() => {
    if (!reviewerName && job?.salesperson) setReviewerName(job.salesperson)
  }, [job?.salesperson, reviewerName])

  const selectedHistoryMaterial = historyIndex === ''
    ? null
    : job?.materials?.[Number(historyIndex)]

  useEffect(() => {
    if (!selectedHistoryMaterial) {
      setPriceHistory(null)
      return
    }
    const materialId = selectedHistoryMaterial.id || selectedHistoryMaterial.material_id
    setPriceHistory(workflow?.price_history?.[String(materialId)] || null)
    setHistoryLoading(false)
  }, [
    historyIndex,
    workflow?.price_history,
    selectedHistoryMaterial?.id,
    selectedHistoryMaterial?.material_id,
    selectedHistoryMaterial?.item_code,
  ])

  const requests = asArray(workflow?.requests)
  const priceMatches = asArray(review?.price_matches)
  const workflowMessages = asArray(review?.messages)
  const relevantInboxMessages = inboxMessages.filter((message) => {
    if (String(message.matched_job_id || '') === String(jobId)) return true
    return asArray(message.candidates).some((candidate) => String(candidate.job_id) === String(jobId))
  })
  const needsMatching = [...workflowMessages, ...relevantInboxMessages].filter((message, index, messages) => {
    const messageId = message.id ?? message.message_id
    return messages.findIndex((candidate) => (candidate.id ?? candidate.message_id) === messageId) === index
  })
  const outlookConnected = outlook?.session_authenticated !== undefined
    ? Boolean(outlook.session_authenticated)
    : Boolean(outlook?.connected || normalizeStatus(outlook?.status) === 'connected')
  const unpricedCount = (job?.materials || []).filter((material) => !Number(material.unit_price)).length
  const unresolvedPriceCount = priceMatches.filter((match) => (
    !match.decision
    && !['complete', 'accepted', 'ignored'].includes(normalizeStatus(match.status))
  )).length
  const unresolvedPriceRequestIds = new Set(
    priceMatches
      .filter((match) => !match.decision)
      .map((match) => String(match.quote_request_id || ''))
      .filter(Boolean),
  )
  const unresolvedRequestCount = requests.filter((request) => (
    !['complete', 'cancelled', 'received'].includes(normalizeStatus(request.status))
    && !(
      normalizeStatus(request.status) === 'needs_review'
      && unresolvedPriceRequestIds.has(String(request.id))
    )
  )).length
  const mailboxVerificationSatisfied = (
    outlookConnected || !workflow?.has_quote_activity
  )
  const quoteWorkflowComplete = (
    mailboxVerificationSatisfied
    &&
    unpricedCount === 0
    && needsMatching.length === 0
    && unresolvedPriceCount === 0
    && unresolvedRequestCount === 0
  )

  useEffect(() => {
    onCompletionChange?.(quoteWorkflowComplete)
  }, [onCompletionChange, quoteWorkflowComplete])

  const summaryCounts = useMemo(() => {
    const summary = workflow?.summary || {}
    const nested = summary.statuses || {}

    return SUMMARY_STATUSES.reduce((counts, item) => {
      const aliases = {
        sent: ['sent'],
        waiting: ['waiting', 'approved', 'sending'],
        overdue: ['overdue'],
        received: ['received', 'received_partial'],
        complete: ['complete'],
      }[item.key] || []

      if (item.key === 'needs_josh') {
        counts[item.key] = needsMatching.length
          + priceMatches.filter((match) => !match.decision).length
          + requests.filter((request) =>
            ['stale', 'send_failed', 'send_uncertain', 'needs_review'].includes(normalizeStatus(request.status))
            && !unresolvedPriceRequestIds.has(String(request.id))
          ).length
        return counts
      }

      const directValue = summary[item.key] ?? summary[`${item.key}_count`]
      const nestedValues = aliases
        .map((key) => nested[key])
        .filter((value) => Number.isFinite(Number(value)))
      if (Number.isFinite(Number(directValue))) counts[item.key] = Number(directValue)
      else if (nestedValues.length) counts[item.key] = nestedValues.reduce((total, value) => total + Number(value), 0)
      else counts[item.key] = requests.filter((request) => aliases.includes(normalizeStatus(request.status))).length
      return counts
    }, {})
  }, [workflow?.summary, requests, needsMatching.length, priceMatches])

  const runAction = async (key, action, successMessage, { refreshJob = false } = {}) => {
    setActionKey(key)
    setError('')
    setNotice('')
    try {
      await action()
      await loadLiveData({ quiet: true })
      if (refreshJob && onJobRefresh) await onJobRefresh()
      if (successMessage) setNotice(successMessage)
    } catch (err) {
      setError(err.message || 'That action could not be completed.')
    } finally {
      setActionKey('')
    }
  }

  const updateGroup = (index, field, value) => {
    setGroups((current) => current.map((group, groupIndex) => (
      groupIndex === index
        ? { ...group, [field]: value, ...(field === 'vendor_name' ? { vendor_id: null } : {}) }
        : group
    )))
  }

  const groupCanSend = (group) => {
    const emailReady = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(group?.vendor_email || '')
    const vendorReady = Boolean(group?.vendor_name && normalizeStatus(group.vendor_name) !== 'unassigned')
    const materialsToSend = asArray(group?.materials_to_send).length
      ? asArray(group.materials_to_send)
      : asArray(group?.materials).filter((material) => !material.already_requested)
    return emailReady
      && vendorReady
      && materialsToSend.length > 0
      && Boolean(group?.subject?.trim())
      && Boolean(group?.body?.trim())
      && unresolvedGroupIssues(group).length === 0
  }

  const readyGroups = groups.filter(groupCanSend)
  const invalidGroupCount = groups.filter((group) => !groupCanSend(group)).length
  const sendBlockReason = !outlookConnected
    ? 'Connect Outlook before sending.'
    : !readyGroups.length
      ? 'No unpriced vendor groups are ready.'
      : !reviewerName.trim()
        ? 'Enter the person approving these requests.'
        : ''

  const approveAndSend = () => {
    setConfirmAction({
      title: 'Send all ready quote requests?',
      message: `${readyGroups.length} vendor email${readyGroups.length === 1 ? '' : 's'} will be sent from the connected Outlook account.`,
      label: 'Approve & Send',
      run: async () => {
        setActionKey('approve-send')
        setError('')
        setNotice('')
        try {
          const result = await api.approveAndSendQuotes(jobId, {
            groups: readyGroups,
            reviewer_name: reviewerName.trim(),
            source_fingerprint: workflow?.source_fingerprint,
          })
          await loadLiveData({ quiet: true })
          const failed = asArray(result?.results).filter((item) => normalizeStatus(item.status) !== 'accepted')
          if (failed.length) {
            setError(`${failed.length} vendor email${failed.length === 1 ? '' : 's'} needs attention. Only requests marked Send Failed can be retried.`)
          } else {
            setNotice('Microsoft accepted the quote requests. The timeline will show the saved Outlook proof.')
          }
        } catch (err) {
          setError(err.message || 'Quote requests could not send.')
        } finally {
          setActionKey('')
        }
      },
    })
  }

  const connectOutlook = () => {
    window.location.assign(api.outlookConnectUrl(window.location.href))
  }

  const disconnectOutlook = () => {
    setConfirmAction({
      title: 'Disconnect Outlook?',
      message: 'Quote tracking and automatic follow-ups will stop until Outlook is connected again.',
      label: 'Disconnect',
      run: () => runAction(
        'disconnect-outlook',
        api.disconnectOutlook,
        'Outlook disconnected.',
      ),
    })
  }

  const handleRequestAction = (request, action) => {
    const requestId = request.id
    if (action === 'retry') {
      runAction(
        `request-${requestId}`,
        () => api.retryQuoteRequest(requestId),
        `Quote request to ${request.vendor_name || 'vendor'} retried.`,
      )
      return
    }

    setConfirmAction({
      title: 'Cancel this quote request?',
      message: `No more automatic follow-ups will be sent to ${request.vendor_name || request.vendor_email || 'this vendor'}.`,
      label: 'Cancel Request',
      run: () => runAction(
        `request-${requestId}`,
        () => api.cancelQuoteRequest(requestId),
        'Quote request cancelled.',
      ),
    })
  }

  const assignMessage = (message, requestId) => {
    const messageId = message.id ?? message.message_id
    if (!requestId) {
      setError('Choose the quote request that this email belongs to.')
      return
    }
    runAction(
      `message-${messageId}`,
      () => api.assignInboxMessage(messageId, {
        job_id: jobId,
        request_id: Number(requestId),
        reviewer_name: reviewerName.trim() || job?.salesperson || 'Estimator',
      }),
      'Email assigned to this bid.',
    )
  }

  const ignoreMessage = (message) => {
    const messageId = message.id ?? message.message_id
    setConfirmAction({
      title: 'Remove this email from this bid?',
      message: 'It will stop showing for this bid. Any other possible bid match stays available.',
      label: 'Remove From Bid',
      run: () => runAction(
        `message-${messageId}`,
        () => api.ignoreInboxMessage(messageId, { job_id: jobId }),
        'Email removed from this bid.',
      ),
    })
  }

  const decidePrice = (match, action) => {
    const matchId = match.id ?? match.match_id
    const data = {
      decision: action,
      reviewer_name: reviewerName.trim() || job?.salesperson || 'Estimator',
      reason: `Estimator selected ${titleize(action)} in Material Quotes.`,
      expected_material_id: match.material_id == null ? null : Number(match.material_id),
      expected_current_price: Number(match.current_price ?? match.accepted_price_before ?? 0),
    }
    if (action === 'match_elsewhere') {
      data.material_id = Number(targetMaterials[matchId])
    }

    const execute = () => runAction(
      `price-${matchId}`,
      () => api.decideQuoteMatch(jobId, matchId, data),
      action === 'match_elsewhere'
        ? 'Material matched. Review it, then press Use Quote.'
        : 'Price decision saved.',
      { refreshJob: true },
    )

    if (action === 'use_quote') {
      const currentPrice = Number(match.current_price ?? match.accepted_price_before ?? 0)
      const impact = (Number(match.quote_price) - currentPrice) * Number(match.quantity || 0)
      setConfirmAction({
        title: 'Use this vendor price?',
        message: `This changes the material to ${formatMoney(match.quote_price)} and moves the bid by about ${formatMoney(impact)}.`,
        label: 'Use Quote',
        run: execute,
      })
    } else {
      execute()
    }
  }

  const hydrateSimulation = async (data) => {
    const runId = data?.id ?? data?.run_id
    if (!runId) {
      setSimulation(data)
      return
    }
    try {
      setSimulation(await api.getQuoteSimulation(jobId, runId))
    } catch {
      setSimulation(data)
    }
  }

  const createSimulation = async () => {
    setActionKey('simulation')
    setError('')
    setNotice('')
    try {
      const result = await api.createQuoteSimulation(jobId, {
        scenario: simulationScenario,
        reviewer_name: reviewerName.trim() || job?.salesperson || 'Estimator',
      })
      await hydrateSimulation(result)
      setNotice('Safe test finished.')
    } catch (err) {
      setError(err.message || 'The safe test could not run.')
    } finally {
      setActionKey('')
    }
  }

  const advanceSimulation = async (businessDays) => {
    const runId = simulation?.id ?? simulation?.run_id
    if (!runId) return
    setActionKey('simulation')
    setError('')
    try {
      const result = await api.advanceQuoteSimulation(jobId, runId, { business_days: businessDays })
      await hydrateSimulation(result)
    } catch (err) {
      setError(err.message || 'The test clock could not move.')
    } finally {
      setActionKey('')
    }
  }

  const simulationResult = parseJson(simulation?.result_json || simulation?.result, {})
  const simulationRunId = simulation?.id ?? simulation?.run_id
  const simulationChecks = asArray(simulationResult?.checks || simulation?.checks)
  const simulationTimeline = asArray(
    simulationResult?.timeline || simulationResult?.events || simulation?.timeline || simulation?.events
  )
  const scenarioResults = asArray(simulationResult?.results || simulation?.results)
  const simulationStatus = normalizeStatus(
    simulationResult?.status || simulation?.status || 'waiting',
  )
  const simulationPassed = ['pass', 'passed'].includes(simulationStatus)
  const liveBidUnchanged = simulationResult?.live_job_mutated === false
  const simulationUsedNoAi = Number(simulationResult?.ai_calls) === 0
  const historyRecords = asArray(priceHistory?.records)

  if (loading) {
    return (
      <div className="flex min-h-[260px] items-center justify-center rounded-lg border border-white/[0.06] bg-white/[0.02]">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    )
  }

  return (
    <>
      <div className="space-y-6">
        <div className="flex flex-col gap-3 border-b border-white/[0.06] pb-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="inline-flex w-fit rounded-lg border border-white/[0.08] bg-black/20 p-1">
            <button
              type="button"
              onClick={() => setActiveTab('live')}
              className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors ${
                activeTab === 'live' ? 'bg-white/[0.09] text-white' : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <Mail className="h-4 w-4" />
              Live Quotes
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('test')}
              className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors ${
                activeTab === 'test' ? 'bg-white/[0.09] text-white' : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <TestTube2 className="h-4 w-4" />
              Test This Bid
            </button>
          </div>

          <button
            type="button"
            onClick={() => loadLiveData({ quiet: true })}
            disabled={refreshing}
            className="inline-flex items-center gap-2 self-start rounded-lg px-3 py-2 text-sm font-medium text-gray-400 hover:bg-white/[0.05] hover:text-white disabled:opacity-50 sm:self-auto"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="flex items-start gap-3 rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <span className="flex-1">{error}</span>
            <button type="button" onClick={() => setError('')} title="Dismiss">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {notice && (
          <div className="flex items-center gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
            <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
            <span className="flex-1">{notice}</span>
            <button type="button" onClick={() => setNotice('')} title="Dismiss">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {activeTab === 'live' ? (
          <>
            <section className="overflow-hidden rounded-lg border border-white/[0.07] bg-white/[0.025]">
              <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-bold text-white">Outlook</h2>
                    <StatusPill
                      status={outlookConnected ? 'connected' : 'cancelled'}
                      label={outlookConnected ? 'Connected' : 'Not connected'}
                    />
                    <span
                      className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/20 bg-emerald-500/[0.08] px-2 py-1 text-xs font-semibold text-emerald-300"
                      title="Email matching uses fixed rules, not an AI model."
                    >
                      <ShieldCheck className="h-3.5 w-3.5" />
                      Deterministic · No AI
                    </span>
                  </div>
                  <p className="mt-1 truncate text-xs text-gray-500">
                    {outlookConnected
                      ? outlook.email || outlook.account_email || 'Microsoft account connected'
                      : 'Connect the estimator mailbox to send and track vendor replies.'}
                  </p>
                  {outlook?.last_sync_at && (
                    <p className="mt-1 text-xs text-gray-600">Last checked {formatDate(outlook.last_sync_at)}</p>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {outlookConnected ? (
                    <>
                      <button
                        type="button"
                        onClick={() => runAction('sync-outlook', api.syncOutlook, 'Outlook checked for new replies.')}
                        disabled={actionKey === 'sync-outlook'}
                        className="inline-flex items-center gap-2 rounded-lg border border-white/[0.08] px-3 py-2 text-sm font-medium text-gray-300 hover:bg-white/[0.06] disabled:opacity-50"
                      >
                        {actionKey === 'sync-outlook'
                          ? <Loader2 className="h-4 w-4 animate-spin" />
                          : <RefreshCw className="h-4 w-4" />}
                        Check Mail
                      </button>
                      <button
                        type="button"
                        onClick={disconnectOutlook}
                        className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-gray-500 hover:bg-red-500/10 hover:text-red-300"
                      >
                        <Unplug className="h-4 w-4" />
                        Disconnect
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={connectOutlook}
                      disabled={!outlook?.configured}
                      title={!outlook?.configured ? 'Microsoft setup is not finished on this Fly app.' : ''}
                      className="inline-flex items-center gap-2 rounded-lg bg-si-bright px-4 py-2 text-sm font-bold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <ExternalLink className="h-4 w-4" />
                      {outlook?.configured ? 'Connect Outlook' : 'Outlook Not Configured'}
                    </button>
                  )}
                </div>
              </div>
            </section>

            <section>
              <SectionHeading icon={Clock3} title="Quote Status" />
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                {SUMMARY_STATUSES.map((item) => (
                  <div key={item.key} className="min-w-0 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-3">
                    <p className="text-xl font-bold tabular-nums text-white">{summaryCounts[item.key] || 0}</p>
                    <p className="mt-0.5 truncate text-xs text-gray-500">{item.label}</p>
                  </div>
                ))}
              </div>
            </section>

            <section>
              <SectionHeading
                icon={Send}
                title="Vendor Groups"
                count={groups.length}
                action={(
                  <button
                    type="button"
                    onClick={() => loadLiveData({ quiet: true })}
                    className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-500 hover:bg-white/[0.05] hover:text-gray-300"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Reset Plan
                  </button>
                )}
              />

              {groups.length ? (
                <div className="space-y-3">
                  {groups.map((group, index) => {
                    const materials = asArray(group.materials)
                    const issues = [...unresolvedGroupIssues(group)]
                    if (!group.subject?.trim()) issues.push('Add an email subject.')
                    if (!group.body?.trim()) issues.push('Add the email message.')
                    const ready = groupCanSend(group)
                    return (
                      <article
                        key={`vendor-group-${index}`}
                        className="overflow-hidden rounded-lg border border-white/[0.07] bg-white/[0.025]"
                      >
                        <div className="flex flex-col gap-3 border-b border-white/[0.06] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-end gap-2">
                              <label className="min-w-[180px] flex-1">
                                <span className="mb-1 block text-[11px] font-semibold text-gray-600">Vendor</span>
                                <input
                                  type="text"
                                  value={group.vendor_name || ''}
                                  onChange={(event) => updateGroup(index, 'vendor_name', event.target.value)}
                                  placeholder="Vendor name"
                                  className="w-full rounded-md border border-white/[0.08] bg-black/20 px-3 py-2 text-sm font-semibold text-white outline-none placeholder:text-gray-600 focus:border-si-bright/50"
                                />
                              </label>
                              <StatusPill status={ready ? 'complete' : 'needs_josh'} label={ready ? 'Ready' : 'Needs Josh'} />
                            </div>
                            <p className="mt-1 text-xs text-gray-500">
                              {materials.length} material{materials.length === 1 ? '' : 's'}
                            </p>
                          </div>
                          <label className="w-full sm:max-w-xs">
                            <span className="mb-1 block text-[11px] font-semibold text-gray-600">Contact email</span>
                            <input
                              type="email"
                              value={group.vendor_email || ''}
                              onChange={(event) => updateGroup(index, 'vendor_email', event.target.value)}
                              placeholder="vendor@example.com"
                              className="w-full rounded-md border border-white/[0.08] bg-black/20 px-3 py-2 text-sm text-gray-200 outline-none placeholder:text-gray-600 focus:border-si-bright/50"
                            />
                          </label>
                        </div>

                        {issues.length > 0 && (
                          <div className="flex flex-wrap gap-2 border-b border-amber-500/10 bg-amber-500/[0.04] px-4 py-2.5">
                            {issues.map((issue, issueIndex) => (
                              <span key={issueIndex} className="text-xs text-amber-300">
                                {issueLabel(issue)}
                              </span>
                            ))}
                          </div>
                        )}

                        <div className="divide-y divide-white/[0.05]">
                          {materials.map((material, materialIndex) => (
                            <div
                              key={material.id || material.material_id || materialIndex}
                              className="grid gap-1 px-4 py-2.5 text-sm sm:grid-cols-[minmax(0,1fr)_auto]"
                            >
                              <span className="flex min-w-0 flex-wrap items-center gap-2 break-words text-gray-300">
                                {materialLabel(material)}
                                {material.already_requested && (
                                  <StatusPill status="waiting" label="Already requested" />
                                )}
                              </span>
                              <span className="text-xs tabular-nums text-gray-500">
                                {materialQuantity(material) || '—'} {material.unit || ''}
                              </span>
                            </div>
                          ))}
                        </div>

                        <div className="grid gap-3 border-t border-white/[0.06] p-4">
                          <label>
                            <span className="mb-1.5 block text-xs font-semibold text-gray-500">Subject preview</span>
                            <input
                              type="text"
                              value={group.subject || ''}
                              onChange={(event) => updateGroup(index, 'subject', event.target.value)}
                              className="w-full rounded-md border border-white/[0.08] bg-black/20 px-3 py-2 text-sm text-gray-200 outline-none focus:border-si-bright/50"
                            />
                          </label>
                          <label>
                            <span className="mb-1.5 block text-xs font-semibold text-gray-500">Email preview</span>
                            <textarea
                              value={group.body || ''}
                              onChange={(event) => updateGroup(index, 'body', event.target.value)}
                              rows={6}
                              className="w-full resize-y rounded-md border border-white/[0.08] bg-black/20 px-3 py-2 text-sm leading-relaxed text-gray-300 outline-none focus:border-si-bright/50"
                            />
                          </label>
                        </div>
                      </article>
                    )
                  })}

                  <div className="flex flex-col gap-3 rounded-lg border border-white/[0.07] bg-black/20 p-4 sm:flex-row sm:items-end sm:justify-between">
                    <label className="w-full sm:max-w-xs">
                      <span className="mb-1.5 block text-xs font-semibold text-gray-500">Approved by</span>
                      <input
                        type="text"
                        value={reviewerName}
                        onChange={(event) => setReviewerName(event.target.value)}
                        placeholder="Estimator name"
                        className="w-full rounded-md border border-white/[0.08] bg-white/[0.03] px-3 py-2 text-sm text-gray-200 outline-none placeholder:text-gray-600 focus:border-si-bright/50"
                      />
                    </label>
                    <div className="sm:text-right">
                      {invalidGroupCount > 0 && readyGroups.length > 0 && (
                        <p className="mb-2 text-xs text-gray-500">
                          {invalidGroupCount} other group{invalidGroupCount === 1 ? '' : 's'} will stay in Needs Josh.
                        </p>
                      )}
                      {sendBlockReason && <p className="mb-2 text-xs text-amber-300">{sendBlockReason}</p>}
                      <button
                        type="button"
                        onClick={approveAndSend}
                        disabled={Boolean(sendBlockReason) || actionKey === 'approve-send'}
                        className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-si-orange px-4 py-2.5 text-sm font-bold text-white hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
                      >
                        {actionKey === 'approve-send'
                          ? <Loader2 className="h-4 w-4 animate-spin" />
                          : <Send className="h-4 w-4" />}
                        Approve & Send
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <EmptyRow>No unpriced materials are waiting for a vendor.</EmptyRow>
              )}
            </section>

            <section>
              <SectionHeading icon={Clock3} title="Request Timeline" count={requests.length} />
              {requests.length ? (
                <div className="space-y-3">
                  {requests.map((request) => {
                    const status = normalizeStatus(request.status)
                    const materials = asArray(request.materials)
                    const followups = asArray(request.followups)
                    const messages = asArray(request.messages)
                    const canRetry = ['send_failed', 'approved'].includes(status)
                    const canCancel = !['complete', 'cancelled', 'received'].includes(status)
                    const deliveryProof = Boolean(
                      request.outlook_message_id && request.sent_artifact_hash
                    )
                    return (
                      <article key={request.id} className="rounded-lg border border-white/[0.07] bg-white/[0.025] p-4">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="truncate text-sm font-bold text-white">{request.vendor_name || 'Vendor'}</h3>
                              <StatusPill status={status} />
                              {request.stale && <StatusPill status="needs_josh" label="Bid changed" />}
                            </div>
                            <p className="mt-1 break-all text-xs text-gray-500">{request.vendor_email || 'No email saved'}</p>
                          </div>
                          <div className="flex items-center gap-2">
                            {canRetry && (
                              <button
                                type="button"
                                onClick={() => handleRequestAction(request, 'retry')}
                                disabled={actionKey === `request-${request.id}`}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-2.5 py-1.5 text-xs font-medium text-gray-300 hover:bg-white/[0.06] disabled:opacity-50"
                              >
                                <RotateCcw className="h-3.5 w-3.5" />
                                Retry
                              </button>
                            )}
                            {canCancel && (
                              <button
                                type="button"
                                onClick={() => handleRequestAction(request, 'cancel')}
                                className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-500 hover:bg-red-500/10 hover:text-red-300"
                              >
                                <Ban className="h-3.5 w-3.5" />
                                Cancel
                              </button>
                            )}
                          </div>
                        </div>

                        <div className="mt-3 grid grid-cols-2 gap-3 border-y border-white/[0.05] py-3 text-xs sm:grid-cols-4">
                          <div>
                            <p className="text-gray-600">Microsoft accepted</p>
                            <p className="mt-1 text-gray-300">{formatDate(request.sent_at)}</p>
                          </div>
                          <div>
                            <p className="text-gray-600">Received</p>
                            <p className="mt-1 text-gray-300">{formatDate(request.received_at)}</p>
                          </div>
                          <div>
                            <p className="text-gray-600">Materials</p>
                            <p className="mt-1 text-gray-300">{materials.length}</p>
                          </div>
                          <div>
                            <p className="text-gray-600">Follow-ups</p>
                            <p className="mt-1 text-gray-300">{followups.length}</p>
                          </div>
                        </div>

                        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                          {deliveryProof ? (
                            <a
                              href={api.quoteRequestEvidenceUrl(request.id)}
                              className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] px-2.5 py-1.5 text-gray-300 hover:bg-white/[0.05] hover:text-white"
                            >
                              <FileText className="h-3.5 w-3.5" />
                              Open verified Outlook email
                            </a>
                          ) : (
                            <StatusPill status="waiting" label="Outlook proof pending" />
                          )}
                          {request.outlook_message_id && (
                            <span className="text-gray-500">Microsoft message ID saved</span>
                          )}
                          {request.sent_artifact_hash && (
                            <span
                              className="font-mono text-gray-600"
                              title={request.sent_artifact_hash}
                            >
                              SHA-256 {request.sent_artifact_hash.slice(0, 12)}…
                            </span>
                          )}
                        </div>

                        {messages.length > 0 && (
                          <div className="mt-3 space-y-2 border-t border-white/[0.05] pt-3">
                            {messages.map((message) => {
                              const attachments = asArray(message.attachments)
                              return (
                                <div key={message.id} className="rounded-md bg-black/20 px-3 py-2 text-xs">
                                  <div className="flex flex-wrap items-center gap-2">
                                    {message.raw_hash && message.raw_artifact_path ? (
                                      <a
                                        href={api.quoteMessageEvidenceUrl(message.id)}
                                        className="inline-flex items-center gap-1.5 font-medium text-blue-300 hover:text-blue-200"
                                      >
                                        <Mail className="h-3.5 w-3.5" />
                                        {message.subject || 'Open vendor email'}
                                      </a>
                                    ) : (
                                      <span className="inline-flex items-center gap-1.5 font-medium text-gray-400">
                                        <Mail className="h-3.5 w-3.5" />
                                        {message.subject || 'Vendor email'}
                                      </span>
                                    )}
                                    <span className="text-gray-600">
                                      {formatDate(message.received_at || message.sent_at)}
                                    </span>
                                    {message.raw_hash && (
                                      <span className="font-mono text-gray-600" title={message.raw_hash}>
                                        {message.raw_hash.slice(0, 12)}…
                                      </span>
                                    )}
                                    {!message.raw_hash && (
                                      <StatusPill status="needs_josh" label="Original email proof missing" />
                                    )}
                                  </div>
                                  {attachments.length > 0 && (
                                    <div className="mt-2 flex flex-wrap gap-2">
                                      {attachments.map((attachment, attachmentIndex) => (
                                        attachment.artifact_path && attachment.file_hash ? (
                                          <a
                                            key={`${message.id}-${attachmentIndex}`}
                                            href={api.quoteMessageAttachmentUrl(message.id, attachmentIndex)}
                                            className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.07] px-2 py-1 text-gray-400 hover:bg-white/[0.05] hover:text-white"
                                            title={`SHA-256 ${attachment.file_hash}`}
                                          >
                                            <Paperclip className="h-3.5 w-3.5" />
                                            {attachment.file_name || `Attachment ${attachmentIndex + 1}`}
                                          </a>
                                        ) : null
                                      ))}
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        )}

                        {followups.length > 0 && (
                          <div className="mt-3 space-y-2">
                            {followups.map((followup, index) => (
                              <div key={followup.id || index} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                                <StatusPill status={followup.status || 'scheduled'} />
                                <span className="text-gray-400">
                                  Follow-up {followup.followup_number || index + 1}
                                </span>
                                <span className="text-gray-600">
                                  {formatDate(followup.sent_at || followup.scheduled_for)}
                                </span>
                                {followup.error && <span className="text-red-300">{followup.error}</span>}
                              </div>
                            ))}
                          </div>
                        )}
                      </article>
                    )
                  })}
                </div>
              ) : (
                <EmptyRow>No quote requests have been sent for this bid.</EmptyRow>
              )}
            </section>

            <section>
              <SectionHeading icon={Inbox} title="Needs Matching" count={needsMatching.length} />
              {needsMatching.length ? (
                <div className="space-y-3">
                  {needsMatching.map((message, index) => {
                    const messageId = message.id ?? message.message_id ?? index
                    const evidence = asArray(message.evidence || message.evidence_json)
                    const candidates = asArray(message.candidates)
                    const messageAttachments = asArray(message.attachments)
                    const currentCandidates = candidates.filter((candidate) =>
                      String(candidate.job_id) === String(jobId)
                    )
                    const onlyRequestId = currentCandidates.length === 1
                      ? currentCandidates[0].quote_request_id || currentCandidates[0].request_id
                      : null
                    const selectedRequestId = targetRequests[messageId]
                      || message.matched_request_id
                      || onlyRequestId
                    return (
                      <article key={messageId} className="rounded-lg border border-orange-500/15 bg-orange-500/[0.035] p-4">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <StatusPill status="needs_matching" label="Needs Matching" />
                              <span className="text-xs text-gray-600">{formatDate(message.received_at)}</span>
                            </div>
                            <h3 className="mt-2 break-words text-sm font-semibold text-white">{message.subject || 'No subject'}</h3>
                            <p className="mt-1 break-all text-xs text-gray-500">
                              {message.sender_email || message.from || 'Unknown sender'}
                            </p>
                            {(message.preview || message.body_preview || message.body_text) && (
                              <p className="mt-2 line-clamp-2 text-sm text-gray-400">
                                {message.preview || message.body_preview || message.body_text}
                              </p>
                            )}
                          </div>
                          <div className="flex flex-col items-stretch gap-2 sm:items-end">
                            {currentCandidates.length > 1 && (
                              <select
                                value={targetRequests[messageId] || ''}
                                onChange={(event) => setTargetRequests((current) => ({
                                  ...current,
                                  [messageId]: event.target.value,
                                }))}
                                className="max-w-xs rounded-md border border-white/[0.08] bg-[#0D1322] px-3 py-2 text-xs text-gray-300 outline-none focus:border-si-bright/50"
                              >
                                <option value="">Choose a vendor request</option>
                                {currentCandidates.map((candidate, candidateIndex) => {
                                  const requestId = candidate.quote_request_id || candidate.request_id
                                  return (
                                    <option key={candidate.id || requestId || candidateIndex} value={requestId || ''}>
                                      {candidate.vendor_name || `Request ${requestId}`}
                                    </option>
                                  )
                                })}
                              </select>
                            )}
                            <div className="flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              onClick={() => assignMessage(message, selectedRequestId)}
                              disabled={!selectedRequestId || actionKey === `message-${messageId}`}
                              title={!selectedRequestId ? 'Choose an exact quote request first' : ''}
                              className="inline-flex items-center gap-1.5 rounded-lg bg-si-bright px-3 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-50"
                            >
                              <Link2 className="h-3.5 w-3.5" />
                              Assign to This Bid
                            </button>
                            <button
                              type="button"
                              onClick={() => ignoreMessage(message)}
                              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-gray-500 hover:bg-white/[0.05] hover:text-gray-300"
                            >
                              <Ban className="h-3.5 w-3.5" />
                              Ignore
                            </button>
                            </div>
                          </div>
                        </div>

                        {(evidence.length > 0 || candidates.length > 0) && (
                          <div className="mt-3 flex flex-wrap gap-2 border-t border-white/[0.05] pt-3">
                            {evidence.map((item, evidenceIndex) => (
                              <span key={evidenceIndex} className="rounded-md bg-white/[0.04] px-2 py-1 text-xs text-gray-400">
                                {issueLabel(item)}
                              </span>
                            ))}
                            {candidates.map((candidate, candidateIndex) => (
                              <span key={candidate.id || candidateIndex} className="rounded-md bg-blue-500/[0.07] px-2 py-1 text-xs text-blue-300">
                                {candidate.job_name || candidate.project_name || `Bid ${candidate.job_id}`}
                              </span>
                            ))}
                          </div>
                        )}
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          {message.raw_hash && (
                            <a
                              href={api.quoteMessageEvidenceUrl(messageId)}
                              className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] px-2 py-1 text-xs text-gray-300 hover:bg-white/[0.05] hover:text-white"
                              title={`SHA-256 ${message.raw_hash}`}
                            >
                              <Mail className="h-3.5 w-3.5" />
                              Open saved email
                            </a>
                          )}
                          {messageAttachments.map((attachment, attachmentIndex) => (
                            attachment.artifact_path && attachment.file_hash ? (
                              <a
                                key={`${messageId}-attachment-${attachmentIndex}`}
                                href={api.quoteMessageAttachmentUrl(messageId, attachmentIndex)}
                                className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] px-2 py-1 text-xs text-gray-400 hover:bg-white/[0.05] hover:text-white"
                                title={`SHA-256 ${attachment.file_hash}`}
                              >
                                <Paperclip className="h-3.5 w-3.5" />
                                {attachment.file_name || `Attachment ${attachmentIndex + 1}`}
                              </a>
                            ) : null
                          ))}
                        </div>
                      </article>
                    )
                  })}
                </div>
              ) : (
                <EmptyRow>No emails need Josh to choose a bid.</EmptyRow>
              )}
            </section>

            <section>
              <SectionHeading icon={CircleDollarSign} title="Price Review" count={priceMatches.length} />
              {priceMatches.length ? (
                <div className="space-y-3">
                  {priceMatches.map((match, index) => {
                    const matchId = match.id ?? match.match_id ?? index
                    const oldPrice = Number(match.accepted_price_before || 0)
                    const currentPrice = Number(match.current_price ?? oldPrice)
                    const newPrice = Number(match.quote_price)
                    const quantity = Number(match.quantity || 0)
                    const impact = (newPrice - currentPrice) * quantity
                    const priceChangedSinceReview = Math.abs(currentPrice - oldPrice) > 0.0001
                    const pending = !match.decision && !['complete', 'accepted', 'ignored'].includes(normalizeStatus(match.status))
                    const lockedRequest = requests.find((request) =>
                      String(request.id) === String(match.quote_request_id)
                    )
                    const lockedMaterialIds = new Set(
                      asArray(lockedRequest?.materials)
                        .filter((material) => normalizeStatus(material.status) === 'requested')
                        .map((material) => String(material.material_id || material.id))
                    )
                    return (
                      <article key={matchId} className="rounded-lg border border-white/[0.07] bg-white/[0.025] p-4">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="break-words text-sm font-bold text-white">
                                {materialLabel(match)}
                              </h3>
                              <StatusPill status={match.status || 'needs_review'} />
                            </div>
                            <p className="mt-1 text-xs text-gray-500">
                              {match.reason || match.match_method || 'Vendor price needs a decision.'}
                            </p>
                            {match.source_file && (
                              <p className="mt-1 flex items-center gap-1.5 break-all text-xs text-gray-600">
                                <Paperclip className="h-3.5 w-3.5 flex-shrink-0" />
                                {match.source_file}
                              </p>
                            )}
                          </div>
                          <div className={`text-left sm:text-right ${impact > 0 ? 'text-amber-300' : impact < 0 ? 'text-emerald-300' : 'text-gray-400'}`}>
                            <p className="text-sm font-bold tabular-nums">{formatMoney(impact)}</p>
                            <p className="text-xs text-gray-600">bid impact</p>
                          </div>
                        </div>

                        <div className="mt-3 grid grid-cols-2 gap-3 border-y border-white/[0.05] py-3 text-xs sm:grid-cols-4">
                          <div>
                            <p className="text-gray-600">Current</p>
                            <p className="mt-1 font-semibold text-gray-300">{formatMoney(currentPrice)}</p>
                            {priceChangedSinceReview && (
                              <p className="mt-1 text-[11px] text-amber-300">
                                Was {formatMoney(oldPrice)} when this reply arrived
                              </p>
                            )}
                          </div>
                          <div>
                            <p className="text-gray-600">Vendor quote</p>
                            <p className="mt-1 font-semibold text-white">{formatMoney(newPrice)}</p>
                          </div>
                          <div>
                            <p className="text-gray-600">Quantity</p>
                            <p className="mt-1 text-gray-300">{quantity || '—'}</p>
                          </div>
                          <div>
                            <p className="text-gray-600">Units</p>
                            <p className="mt-1 text-gray-300">
                              {match.material_unit || '—'} / {match.quote_unit || '—'}
                            </p>
                          </div>
                        </div>

                        {pending && (
                          <div className="mt-3 flex flex-col gap-2">
                            <div className="flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => decidePrice(match, 'use_quote')}
                                disabled={actionKey === `price-${matchId}`}
                                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/15 px-3 py-2 text-xs font-bold text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"
                              >
                                <Check className="h-3.5 w-3.5" />
                                Use Quote
                              </button>
                              <button
                                type="button"
                                onClick={() => decidePrice(match, 'keep_current')}
                                disabled={currentPrice <= 0 || actionKey === `price-${matchId}`}
                                title={currentPrice <= 0 ? 'There is no current price to keep.' : ''}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 py-2 text-xs font-medium text-gray-300 hover:bg-white/[0.06] disabled:opacity-50"
                              >
                                <ShieldCheck className="h-3.5 w-3.5" />
                                Keep Current
                              </button>
                              <button
                                type="button"
                                onClick={() => decidePrice(match, 'ignore')}
                                disabled={actionKey === `price-${matchId}`}
                                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-gray-500 hover:bg-white/[0.05] hover:text-gray-300 disabled:opacity-50"
                              >
                                <Ban className="h-3.5 w-3.5" />
                                Ignore
                              </button>
                            </div>
                            <div className="flex flex-col gap-2 sm:flex-row">
                              <select
                                value={targetMaterials[matchId] || ''}
                                onChange={(event) => setTargetMaterials((current) => ({
                                  ...current,
                                  [matchId]: event.target.value,
                                }))}
                                className="min-w-0 flex-1 rounded-md border border-white/[0.08] bg-[#0D1322] px-3 py-2 text-xs text-gray-300 outline-none focus:border-si-bright/50"
                              >
                                <option value="">Choose another material</option>
                                {(job?.materials || []).filter((material) =>
                                  lockedMaterialIds.has(String(material.id || material.material_id))
                                ).map((material, materialIndex) => {
                                  const materialId = material.id || material.material_id
                                  if (!materialId) return null
                                  return (
                                    <option key={materialId || materialIndex} value={materialId}>
                                      {materialLabel(material)}
                                    </option>
                                  )
                                })}
                              </select>
                              <button
                                type="button"
                                onClick={() => decidePrice(match, 'match_elsewhere')}
                                disabled={!targetMaterials[matchId] || actionKey === `price-${matchId}`}
                                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs font-medium text-blue-300 hover:bg-blue-500/20 disabled:opacity-40"
                              >
                                <Link2 className="h-3.5 w-3.5" />
                                Match Elsewhere
                              </button>
                            </div>
                          </div>
                        )}
                      </article>
                    )
                  })}
                </div>
              ) : (
                <EmptyRow>No vendor prices need a decision.</EmptyRow>
              )}
            </section>

            <section>
              <SectionHeading icon={History} title="Price History" />
              <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] p-4">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-semibold text-gray-500">Material</span>
                  <select
                    value={historyIndex}
                    onChange={(event) => setHistoryIndex(event.target.value)}
                    className="w-full rounded-md border border-white/[0.08] bg-[#0D1322] px-3 py-2 text-sm text-gray-300 outline-none focus:border-si-bright/50"
                  >
                    {(job?.materials || []).map((material, index) => (
                      <option key={material.id || material.material_id || index} value={index}>
                        {materialLabel(material)}
                      </option>
                    ))}
                  </select>
                </label>

                {historyLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-4 w-4 animate-spin text-gray-500" />
                  </div>
                ) : historyRecords.length ? (
                  <>
                    <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {[
                        ['Latest', priceHistory?.latest?.unit_price],
                        ['Low', priceHistory?.min],
                        ['Average', priceHistory?.avg],
                        ['High', priceHistory?.max],
                      ].map(([label, value]) => (
                        <div key={label} className="border-l border-white/[0.08] px-3">
                          <p className="text-xs text-gray-600">{label}</p>
                          <p className="mt-1 text-sm font-bold tabular-nums text-white">{formatMoney(value)}</p>
                        </div>
                      ))}
                    </div>
                    <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t border-white/[0.06] pt-3 text-xs text-gray-500">
                      <span>
                        Latest vendor: <strong className="text-gray-300">{priceHistory?.latest?.vendor_name || 'Unknown'}</strong>
                      </span>
                      <span>
                        Age: <strong className="text-gray-300">
                          {priceHistory?.age_days == null ? 'Unknown' : `${priceHistory.age_days} days`}
                        </strong>
                      </span>
                      <span>
                        Change: <strong className="text-gray-300">
                          {priceHistory?.percentage_change == null ? 'Not enough history' : `${priceHistory.percentage_change}%`}
                        </strong>
                      </span>
                      <span>
                        Similar bids: <strong className="text-gray-300">{priceHistory?.similar_bid_count || 0}</strong>
                      </span>
                    </div>
                    {priceHistory?.predicted_price != null && (
                      <div className="mt-3 rounded-md border border-blue-500/15 bg-blue-500/[0.05] px-3 py-2 text-xs text-blue-300">
                        Suggested price: <strong>{formatMoney(priceHistory.predicted_price)}</strong>. History only; it will not fill the bid.
                      </div>
                    )}
                    <div className="mt-4 divide-y divide-white/[0.05] border-t border-white/[0.06]">
                      {historyRecords.slice(0, 6).map((record, index) => (
                        <div key={record.id || index} className="grid gap-2 py-2.5 text-xs sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] sm:items-center">
                          <span className="min-w-0 truncate text-gray-300">{record.vendor_name || record.vendor || 'Unknown vendor'}</span>
                          <span className="min-w-0 truncate text-gray-500">{record.job_name || 'Past bid'}</span>
                          <span className="text-gray-600">{formatDate(record.quote_date || record.created_at)}</span>
                          <span className="font-semibold tabular-nums text-white">{formatMoney(record.unit_price)}</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="mt-4 text-sm text-gray-500">No verified past prices found for this material.</p>
                )}
              </div>
            </section>
          </>
        ) : (
          <>
            <section className={`rounded-lg border p-4 ${
              simulationPassed
                ? 'border-emerald-500/15 bg-emerald-500/[0.035]'
                : simulation
                  ? 'border-red-500/15 bg-red-500/[0.035]'
                : 'border-white/[0.07] bg-white/[0.025]'
            }`}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill
                      status={simulation ? simulationStatus : 'waiting'}
                      label="Fake email only"
                    />
                    <StatusPill
                      status={liveBidUnchanged ? 'passed' : simulation ? 'failed' : 'waiting'}
                      label="Real bid unchanged"
                    />
                    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold ${
                      simulationUsedNoAi
                        ? 'border-emerald-500/20 bg-emerald-500/[0.08] text-emerald-300'
                        : simulation
                          ? 'border-red-500/20 bg-red-500/[0.08] text-red-300'
                        : 'border-white/[0.08] bg-white/[0.03] text-gray-400'
                    }`}>
                      <ShieldCheck className="h-3.5 w-3.5" />
                      No AI
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-gray-400">Run the real quote rules with a fake mailbox and clock.</p>
                </div>
                {simulation && (
                  <StatusPill status={simulation.status || simulationResult.status || 'running'} />
                )}
              </div>
            </section>

            <section>
              <SectionHeading icon={TestTube2} title="Safe Test" />
              <div className="flex flex-col gap-3 rounded-lg border border-white/[0.07] bg-white/[0.025] p-4 sm:flex-row sm:items-end">
                <label className="min-w-0 flex-1">
                  <span className="mb-1.5 block text-xs font-semibold text-gray-500">Scenario</span>
                  <select
                    value={simulationScenario}
                    onChange={(event) => setSimulationScenario(event.target.value)}
                    className="w-full rounded-md border border-white/[0.08] bg-[#0D1322] px-3 py-2.5 text-sm text-gray-300 outline-none focus:border-si-bright/50"
                  >
                    {SIMULATION_SCENARIOS.map((scenario) => (
                      <option key={scenario.value} value={scenario.value}>{scenario.label}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={createSimulation}
                  disabled={actionKey === 'simulation'}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-si-bright px-4 py-2.5 text-sm font-bold text-white hover:bg-blue-500 disabled:opacity-50"
                >
                  {actionKey === 'simulation'
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <Play className="h-4 w-4" />}
                  Run Safe Test
                </button>
              </div>
            </section>

            {simulation ? (
              <>
                <section>
                  <SectionHeading
                    icon={FastForward}
                    title="Fake Clock Preview"
                    action={(
                      <div className="flex flex-wrap items-center gap-2">
                        <a
                          href={api.quoteSimulationReportUrl(jobId, simulationRunId)}
                          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-400 hover:bg-white/[0.05] hover:text-white"
                        >
                          <FileText className="h-3.5 w-3.5" />
                          Download Report
                        </a>
                        <button
                          type="button"
                          onClick={() => hydrateSimulation(simulation)}
                          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-500 hover:bg-white/[0.05] hover:text-gray-300"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          Refresh Run
                        </button>
                      </div>
                    )}
                  />
                  <div className="flex flex-col gap-3 rounded-lg border border-white/[0.07] bg-white/[0.025] p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-xs text-gray-600">Fake date and time</p>
                      <p className="mt-1 text-sm font-semibold text-white">
                        {formatDate(simulation.virtual_now || simulationResult.virtual_now)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => advanceSimulation(3)}
                        disabled={actionKey === 'simulation'}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 py-2 text-xs font-medium text-gray-300 hover:bg-white/[0.06] disabled:opacity-50"
                      >
                        <FastForward className="h-3.5 w-3.5" />
                        Advance 3 Business Days
                      </button>
                      <button
                        type="button"
                        onClick={() => advanceSimulation(6)}
                        disabled={actionKey === 'simulation'}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 py-2 text-xs font-medium text-gray-300 hover:bg-white/[0.06] disabled:opacity-50"
                      >
                        <FastForward className="h-3.5 w-3.5" />
                        Advance 6 Business Days
                      </button>
                    </div>
                  </div>
                </section>

                <section>
                  <SectionHeading
                    icon={ShieldCheck}
                    title="Results"
                    count={simulationChecks.length || scenarioResults.length}
                  />
                  {(simulationChecks.length || scenarioResults.length) ? (
                    <div className="divide-y divide-white/[0.05] rounded-lg border border-white/[0.07] bg-white/[0.025]">
                      {[...simulationChecks, ...scenarioResults].map((result, index) => {
                        const passed = result.passed ?? (
                          result.expected !== undefined && result.actual !== undefined
                            ? result.expected === result.actual
                            : undefined
                        )
                        const status = result.status || (passed === true ? 'pass' : passed === false ? 'fail' : 'waiting')
                        return (
                          <div key={result.id || result.scenario || index} className="flex items-start gap-3 px-4 py-3">
                            {['pass', 'passed', 'complete'].includes(normalizeStatus(status))
                              ? <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-400" />
                              : normalizeStatus(status) === 'fail' || normalizeStatus(status) === 'failed'
                                ? <XCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-400" />
                                : <Clock3 className="mt-0.5 h-4 w-4 flex-shrink-0 text-gray-500" />}
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="text-sm font-medium text-gray-200">
                                  {result.label || result.name || titleize(result.scenario || `Check ${index + 1}`)}
                                </p>
                                <StatusPill status={status} />
                              </div>
                              {(result.message || result.detail) && (
                                <p className="mt-1 text-xs text-gray-500">{result.message || result.detail}</p>
                              )}
                              {result.expected !== undefined && result.actual !== undefined && (
                                <p className="mt-1 text-xs text-gray-600">
                                  Expected {String(result.expected)} · Got {String(result.actual)}
                                </p>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <EmptyRow>The test has not returned check results yet.</EmptyRow>
                  )}
                </section>

                <section>
                  <SectionHeading icon={FileText} title="Test Timeline" count={simulationTimeline.length} />
                  {simulationTimeline.length ? (
                    <div className="divide-y divide-white/[0.05] rounded-lg border border-white/[0.07] bg-white/[0.025]">
                      {simulationTimeline.map((event, index) => (
                        <div key={event.id || index} className="grid gap-1 px-4 py-3 text-sm sm:grid-cols-[140px_minmax(0,1fr)_auto] sm:items-center">
                          <span className="text-xs text-gray-600">{formatDate(event.at || event.created_at || event.time)}</span>
                          <span className="break-words text-gray-300">{event.message || event.label || event.event || 'Test event'}</span>
                          {event.status && <StatusPill status={event.status} />}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <EmptyRow>No test events recorded yet.</EmptyRow>
                  )}
                </section>
              </>
            ) : (
              <EmptyRow>Choose a scenario and run the safe test.</EmptyRow>
            )}
          </>
        )}

        <div className="flex flex-col-reverse gap-3 border-t border-white/[0.06] pt-5 sm:flex-row sm:items-center sm:justify-between">
          <button
            type="button"
            onClick={onGoBack}
            className="inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-gray-400 hover:bg-white/[0.05] hover:text-white"
          >
            <ChevronLeft className="h-4 w-4" />
            Back to Takeoff
          </button>
          <div className="text-center sm:text-right">
            {!quoteWorkflowComplete && (
              <p className="mb-2 text-xs text-amber-300">
                {!mailboxVerificationSatisfied
                  ? 'Connect Outlook so the app can verify no quote work is still open.'
                  : unpricedCount > 0
                  ? `${unpricedCount} material${unpricedCount === 1 ? '' : 's'} still need${unpricedCount === 1 ? 's' : ''} a price.`
                  : `${needsMatching.length + unresolvedPriceCount + unresolvedRequestCount} quote item${needsMatching.length + unresolvedPriceCount + unresolvedRequestCount === 1 ? '' : 's'} still need attention.`}
              </p>
            )}
            <button
              type="button"
              onClick={onContinue}
              disabled={!quoteWorkflowComplete}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-si-orange px-4 py-2.5 text-sm font-bold text-white hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
            >
              Continue to Review
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {confirmAction && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4" role="dialog" aria-modal="true">
          <button
            type="button"
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setConfirmAction(null)}
            aria-label="Close confirmation"
          />
          <div className="relative w-full max-w-md rounded-lg border border-white/10 bg-[#101522] p-5 shadow-2xl">
            <button
              type="button"
              onClick={() => setConfirmAction(null)}
              className="absolute right-3 top-3 rounded-md p-1.5 text-gray-500 hover:bg-white/[0.05] hover:text-gray-300"
              title="Close"
            >
              <X className="h-4 w-4" />
            </button>
            <AlertTriangle className="mb-3 h-5 w-5 text-amber-400" />
            <h2 className="pr-8 text-base font-bold text-white">{confirmAction.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-gray-400">{confirmAction.message}</p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmAction(null)}
                className="rounded-lg px-3 py-2 text-sm font-medium text-gray-400 hover:bg-white/[0.05] hover:text-white"
              >
                Go Back
              </button>
              <button
                type="button"
                onClick={() => {
                  const run = confirmAction.run
                  setConfirmAction(null)
                  run()
                }}
                className="rounded-lg bg-si-orange px-4 py-2 text-sm font-bold text-white hover:bg-orange-500"
              >
                {confirmAction.label}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
