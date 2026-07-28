import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  History,
  Loader2,
  Mail,
  Plus,
  Save,
  Trash2,
  Users,
} from 'lucide-react'
import { api } from '../../api'
import {
  EmptyState,
  SectionTitle,
  StatusPill,
  asArray,
  formatMoney,
  materialLabel,
  normalizeStatus,
} from './QuoteUi'

const makeLocalId = () =>
  `group-${Date.now()}-${Math.random().toString(16).slice(2)}`

const groupMaterials = (group) => {
  const ready = asArray(group?.materials_to_send)
  return ready.length
    ? ready
    : asArray(group?.materials).filter((material) => !material.already_requested)
}

const groupMatchKey = (group) => {
  const vendorId = String(group?.vendor_id || '').trim()
  if (vendorId) return `id:${vendorId}`
  return `name:${String(group?.vendor_name || '').trim().toLowerCase()}`
}

const prepareGroups = (plan, draft) => {
  const savedGroups = asArray(draft?.groups)
  const useSavedGroups = Boolean(draft && !draft.stale)
  const covered = new Set(
    useSavedGroups
      ? savedGroups.flatMap((group) => asArray(group.material_ids).map(String))
      : [],
  )
  const groups = (useSavedGroups ? savedGroups : []).map((group) => ({
    ...group,
    local_id: group.group_id || makeLocalId(),
    materials: asArray(group.materials),
  }))
  const staleGroupsByVendor = new Map(
    savedGroups
      .filter((group) => groupMatchKey(group) !== 'name:')
      .map((group) => [groupMatchKey(group), group]),
  )
  asArray(plan?.groups).forEach((group, index) => {
    const materials = groupMaterials(group).filter(
      (material) => !covered.has(String(material.id)),
    )
    if (!materials.length) return
    const previous = draft?.stale ? staleGroupsByVendor.get(groupMatchKey(group)) : null
    groups.push({
      ...group,
      local_id: `plan-${index}-${String(group.vendor_name || 'vendor')}`,
      vendor_name: group.vendor_name || previous?.vendor_name || '',
      vendor_email: group.vendor_email || previous?.vendor_email || '',
      materials,
    })
  })
  return groups
}

export default function BidQuotePlan({
  job,
  onGoBack,
  onContinue,
  onCompletionChange,
}) {
  const jobId = job?.id
  const [plan, setPlan] = useState({})
  const [draft, setDraft] = useState(null)
  const [workflow, setWorkflow] = useState({})
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [historyOpen, setHistoryOpen] = useState({})

  const load = useCallback(async () => {
    if (!jobId) return
    setLoading(true)
    setError('')
    try {
      const [planData, draftData, workflowData] = await Promise.all([
        api.getQuotePlan(jobId),
        api.getQuoteEmailDraft(jobId),
        api.getQuoteWorkflow(jobId),
      ])
      const savedDraft = draftData?.draft || null
      setPlan(planData || {})
      setDraft(savedDraft)
      setWorkflow(workflowData || {})
      setGroups(prepareGroups(planData, savedDraft))
    } catch (err) {
      setError(err.message || 'Material quote setup could not load.')
    } finally {
      setLoading(false)
    }
  }, [jobId])

  useEffect(() => {
    load()
  }, [load])

  const requestedMaterials = useMemo(
    () => asArray(plan?.groups).flatMap((group) =>
      asArray(group.materials).filter((material) => material.already_requested),
    ),
    [plan],
  )

  const unpricedCount = (job?.materials || []).filter(
    (material) => Number(material.unit_price || 0) <= 0,
  ).length
  const requestStatuses = workflow?.summary?.statuses || {}
  const openRequestCount = Object.entries(requestStatuses).reduce(
    (total, [status, count]) =>
      ['complete', 'received', 'cancelled'].includes(normalizeStatus(status))
        ? total
        : total + Number(count || 0),
    0,
  )
  const outlookConnected = Boolean(
    workflow?.outlook?.session_authenticated
    ?? workflow?.outlook?.connected,
  )
  const mailboxChecked = outlookConnected || !workflow?.has_quote_activity
  const workflowComplete = (
    unpricedCount === 0
    && openRequestCount === 0
    && Number(workflow?.summary?.needs_matching_count || 0) === 0
    && Number(workflow?.summary?.price_review_count || 0) === 0
    && mailboxChecked
  )

  useEffect(() => {
    onCompletionChange?.(workflowComplete)
  }, [onCompletionChange, workflowComplete])

  const updateGroup = (localId, field, value) => {
    setGroups((current) => current.map((group) =>
      group.local_id === localId ? { ...group, [field]: value } : group,
    ))
  }

  const addGroup = () => {
    setGroups((current) => [
      ...current,
      {
        local_id: makeLocalId(),
        vendor_name: '',
        vendor_email: '',
        materials: [],
      },
    ])
  }

  const removeGroup = (localId) => {
    const target = groups.find((group) => group.local_id === localId)
    if (asArray(target?.materials).length) {
      setError('Move the materials to another vendor before removing this group.')
      return
    }
    setGroups((current) => current.filter((group) => group.local_id !== localId))
  }

  const moveMaterial = (materialId, fromId, toId) => {
    if (!toId || fromId === toId) return
    let moved = null
    setGroups((current) => {
      const without = current.map((group) => {
        if (group.local_id !== fromId) return group
        const materials = asArray(group.materials)
        moved = materials.find((material) => String(material.id) === String(materialId))
        return {
          ...group,
          body: '',
          materials: materials.filter(
            (material) => String(material.id) !== String(materialId),
          ),
        }
      })
      if (!moved) return current
      return without.map((group) =>
        group.local_id === toId
          ? {
            ...group,
            body: '',
            materials: [...asArray(group.materials), moved],
          }
          : group,
      )
    })
  }

  const saveDraft = async () => {
    const populated = groups.filter((group) => asArray(group.materials).length)
    if (!populated.length) {
      setError('Put at least one material into a vendor group.')
      return
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const result = await api.saveQuoteEmailDraft(jobId, {
        source_fingerprint: plan.source_fingerprint,
        prepared_by: job?.salesperson || 'Estimator',
        groups: populated.map((group) => ({
          group_id: group.group_id,
          vendor_id: group.vendor_id,
          vendor_name: group.vendor_name,
          vendor_email: group.vendor_email,
          material_ids: asArray(group.materials).map((material) => material.id),
          subject: group.subject || '',
          body: group.body || '',
        })),
      })
      const savedDraft = result?.draft || null
      setDraft(savedDraft)
      setGroups(prepareGroups(plan, savedDraft))
      setNotice('Email draft saved. Next, review it before anything is sent.')
    } catch (err) {
      setError(err.message || 'The email draft could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[280px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    )
  }

  const materialCount = groups.reduce(
    (total, group) => total + asArray(group.materials).length,
    0,
  )
  const incompleteGroupCount = groups.filter((group) => (
    asArray(group.materials).length
    && (
      !String(group.vendor_name || '').trim()
      || normalizeStatus(group.vendor_name) === 'unassigned'
      || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(group.vendor_email || '')
    )
  )).length
  const allMaterialsRequested = materialCount === 0 && requestedMaterials.length > 0
  const quoteEmailView = allMaterialsRequested
    ? 'waiting'
    : (draft?.stale || incompleteGroupCount ? 'needs_you' : 'ready_to_send')
  const quoteEmailUrl = `/jobs/bids/quote-emails?job=${jobId}&view=${quoteEmailView}`
  const canReviewEmail = Boolean(draft && !draft.stale && !incompleteGroupCount)
  const canOpenQuoteEmails = canReviewEmail || allMaterialsRequested

  return (
    <div className="space-y-6">
      <div className="border-b border-white/[0.07] pb-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase text-si-orange">Step 2 of 3</p>
            <h2 className="mt-1 text-xl font-bold text-white">Quote Emails</h2>
            <p className="mt-1 text-sm text-gray-500">
              Check the vendor and materials here. Review and send the email on the next screen.
            </p>
          </div>
          <StatusPill
            status={allMaterialsRequested ? 'waiting' : (incompleteGroupCount ? 'needs_setup' : 'ready_to_send')}
            label={allMaterialsRequested ? 'Waiting on vendor' : (incompleteGroupCount ? 'Vendor setup needed' : (canReviewEmail ? 'Ready to review' : 'Ready to save'))}
          />
        </div>
      </div>

      <div className="rounded-lg border border-white/[0.08] bg-white/[0.025]">
        <div className="grid grid-cols-3 divide-x divide-white/[0.06]">
          {[
            ['Materials to price', unpricedCount],
            ['Vendor groups', groups.filter((group) => asArray(group.materials).length).length],
            ['Waiting on vendors', requestedMaterials.length],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0 px-4 py-3">
              <p className="text-xs text-gray-500">{label}</p>
              <p className="mt-1 text-lg font-bold tabular-nums text-white">{value}</p>
            </div>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/[0.06] px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {notice && (
        <div className="flex flex-col gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3 text-sm text-emerald-300 sm:flex-row sm:items-center sm:justify-between">
          <span className="inline-flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
            {notice}
          </span>
          <Link
            to={quoteEmailUrl}
            className="inline-flex items-center gap-2 font-semibold text-white hover:text-emerald-200"
          >
            Review Email
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}
      {draft?.stale && (
        <div className="flex items-start gap-2 rounded-lg border border-orange-500/20 bg-orange-500/[0.06] px-4 py-3 text-sm text-orange-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          The material list changed. Your vendor contact is kept, but save a fresh email draft before sending.
        </div>
      )}

      <section>
        <SectionTitle
          icon={Users}
          title="Check vendors and materials"
          count={groups.filter((group) => asArray(group.materials).length).length}
          action={(
            <button
              type="button"
              onClick={addGroup}
              className="inline-flex items-center gap-2 rounded-md border border-white/[0.1] px-3 py-2 text-xs font-semibold text-gray-300 hover:bg-white/[0.05]"
            >
              <Plus className="h-4 w-4" />
              Add Vendor Group
            </button>
          )}
        />
        {groups.length ? (
          <div className="space-y-3">
            {groups.map((group) => {
              const materials = asArray(group.materials)
              const groupReady = (
                materials.length > 0
                && Boolean(String(group.vendor_name || '').trim())
                && normalizeStatus(group.vendor_name) !== 'unassigned'
                && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(group.vendor_email || '')
              )
              return (
                <article
                  key={group.local_id}
                  className="overflow-hidden rounded-lg border border-white/[0.08] bg-white/[0.025]"
                >
                  <div className="grid gap-3 border-b border-white/[0.06] p-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
                    <label className="min-w-0">
                      <span className="mb-1.5 block text-xs font-semibold text-gray-500">
                        Vendor
                      </span>
                      <input
                        value={group.vendor_name || ''}
                        onChange={(event) => updateGroup(group.local_id, 'vendor_name', event.target.value)}
                        placeholder="Vendor name"
                        className="w-full rounded-md border border-white/[0.1] bg-black/20 px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-400/50"
                      />
                    </label>
                    <label className="min-w-0">
                      <span className="mb-1.5 block text-xs font-semibold text-gray-500">
                        Vendor email
                      </span>
                      <input
                        type="email"
                        value={group.vendor_email || ''}
                        onChange={(event) => updateGroup(group.local_id, 'vendor_email', event.target.value)}
                        placeholder="pricing@vendor.com"
                        className="w-full rounded-md border border-white/[0.1] bg-black/20 px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-400/50"
                      />
                    </label>
                    <div className="flex items-center justify-between gap-2 sm:justify-end">
                      <StatusPill
                        status={groupReady ? 'ready_to_send' : 'needs_setup'}
                        label={groupReady ? 'Ready' : 'Needs Setup'}
                      />
                      <button
                        type="button"
                        onClick={() => removeGroup(group.local_id)}
                        title="Remove empty vendor group"
                        className="rounded-md p-2 text-gray-500 hover:bg-red-500/10 hover:text-red-300"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>

                  {materials.length ? (
                    <div className="divide-y divide-white/[0.05]">
                      {materials.map((material) => {
                        const history = plan?.price_history?.[String(material.id)] || {}
                        const historyRecords = asArray(history.records)
                        const open = Boolean(historyOpen[material.id])
                        return (
                          <div key={material.id} className="px-4 py-3">
                            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(150px,220px)] sm:items-center">
                              <div className="min-w-0">
                                <p className="break-words text-sm text-gray-200">
                                  {materialLabel(material)}
                                </p>
                                <button
                                  type="button"
                                  onClick={() => setHistoryOpen((current) => ({
                                    ...current,
                                    [material.id]: !current[material.id],
                                  }))}
                                  className="mt-1 inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300"
                                >
                                  <History className="h-3.5 w-3.5" />
                                  {history.latest
                                    ? `Last verified: ${formatMoney(history.latest.unit_price)}`
                                    : 'No verified price history'}
                                </button>
                              </div>
                              <span className="whitespace-nowrap text-xs tabular-nums text-gray-400">
                                {Number(material.quantity || 0).toLocaleString()} {material.unit || ''}
                              </span>
                              <label className="min-w-0">
                                <span className="sr-only">Move material to vendor group</span>
                                <select
                                  value={group.local_id}
                                  onChange={(event) => moveMaterial(
                                    material.id,
                                    group.local_id,
                                    event.target.value,
                                  )}
                                  className="w-full rounded-md border border-white/[0.08] bg-[#0D1322] px-3 py-2 text-xs text-gray-300 outline-none focus:border-blue-400/50"
                                >
                                  {groups.map((option) => (
                                    <option key={option.local_id} value={option.local_id}>
                                      {option.vendor_name || 'New vendor group'}
                                    </option>
                                  ))}
                                </select>
                              </label>
                            </div>
                            {open && (
                              <div className="mt-3 grid grid-cols-2 gap-2 border-t border-white/[0.05] pt-3 text-xs sm:grid-cols-4">
                                <span className="text-gray-500">
                                  Latest <strong className="block text-gray-200">{formatMoney(history.latest?.unit_price)}</strong>
                                </span>
                                <span className="text-gray-500">
                                  Low <strong className="block text-gray-200">{formatMoney(history.min)}</strong>
                                </span>
                                <span className="text-gray-500">
                                  Average <strong className="block text-gray-200">{formatMoney(history.avg)}</strong>
                                </span>
                                <span className="text-gray-500">
                                  Past quotes <strong className="block text-gray-200">{historyRecords.length}</strong>
                                </span>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="px-4 py-5 text-sm text-gray-500">
                      Move a material here, or remove this empty group.
                    </p>
                  )}
                </article>
              )
            })}
          </div>
        ) : (
          <EmptyState>No unpriced materials are waiting to be grouped.</EmptyState>
        )}
      </section>

      {requestedMaterials.length > 0 && (
        <section>
          <SectionTitle
            icon={Clock3}
            title="Already Requested"
            count={requestedMaterials.length}
          />
          <div className="divide-y divide-white/[0.05] rounded-lg border border-white/[0.08] bg-white/[0.02]">
            {requestedMaterials.map((material) => (
              <div
                key={material.id}
                className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
              >
                <span className="text-gray-300">{materialLabel(material)}</span>
                <StatusPill status="waiting" label="In Quote Emails" />
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="flex flex-col gap-3 rounded-lg border border-white/[0.08] bg-black/20 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-white">
            {allMaterialsRequested
              ? 'All unpriced materials are already waiting on vendors.'
              : incompleteGroupCount
              ? `${incompleteGroupCount} group${incompleteGroupCount === 1 ? '' : 's'} still need a vendor email.`
              : canReviewEmail
                ? 'The email draft is ready to review.'
                : 'The vendor groups are ready to save.'}
          </p>
          <p className="mt-1 text-xs text-gray-500">
            {allMaterialsRequested
              ? 'Check vendor replies and follow-ups in Quote Emails.'
              : incompleteGroupCount
                ? 'Add the vendor email above, then save the draft.'
                : 'Saving creates an email draft. It does not send email.'}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          {canOpenQuoteEmails && (
            <Link
              to={quoteEmailUrl}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-si-orange px-4 py-2.5 text-sm font-bold text-white hover:bg-orange-500"
            >
              <Mail className="h-4 w-4" />
              {allMaterialsRequested ? 'Check Quote Emails' : 'Review Email'}
            </Link>
          )}
          <button
            type="button"
            onClick={saveDraft}
            disabled={saving || materialCount === 0 || incompleteGroupCount > 0}
            className={`inline-flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-40 ${
              canOpenQuoteEmails
                ? 'border border-white/[0.1] text-gray-200 hover:bg-white/[0.05]'
                : 'bg-si-orange text-white hover:bg-orange-500'
            }`}
          >
            {saving
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <Save className="h-4 w-4" />}
            {canReviewEmail ? 'Save Updated Draft' : 'Save Email Draft'}
          </button>
        </div>
      </div>

      <div className="flex flex-col-reverse gap-3 border-t border-white/[0.06] pt-5 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="button"
          onClick={onGoBack}
          className="inline-flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-medium text-gray-400 hover:bg-white/[0.05] hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Takeoff
        </button>
        <div className="text-center sm:text-right">
          {!workflowComplete && (
            <p className="mb-2 text-xs text-amber-300">
              Finish vendor quotes in Quote Emails before Review & Generate.
            </p>
          )}
          <button
            type="button"
            onClick={onContinue}
            disabled={!workflowComplete}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-si-orange px-4 py-2.5 text-sm font-bold text-white hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-35"
          >
            Review & Generate
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
