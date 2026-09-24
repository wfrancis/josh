import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ClipboardList, Send, PhoneCall, MessageSquarePlus, Trophy, ThumbsDown,
  Loader2, Save, AlertTriangle, X,
} from 'lucide-react'
import { api } from '../api'
import BidStatusBadge from './BidStatusBadge'
import {
  BID_STATUSES, localToday, addDays, formatDay, formatMoney, formatWhen,
  daysAgoText, dueText, describeBidEvent, bidEventFacts,
} from '../bidTracker'

// Width and text color are left out of the base so callers can set them without class clashes.
const FIELD_BASE = 'bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm placeholder-gray-600 focus:border-si-bright/50 focus:outline-none [color-scheme:dark]'
const FIELD_CLASS = `w-full text-white ${FIELD_BASE}`
const LABEL_CLASS = 'text-xs text-gray-500 mb-1 block'
const EDITABLE_FIELDS = ['bid_status', 'bid_due_date', 'bid_due_time', 'estimator', 'next_follow_up_date']
const HISTORY_PREVIEW = 4
// Statuses that have their own form (who it went to, reason, amount). Picking
// one in the status list opens that form instead of just changing the status.
const STATUS_FORMS = { Sent: 'sent', Won: 'won', Lost: 'lost' }
// Fields each action can change on the server. After the action, these show
// the saved value even if they had unsaved edits; other unsaved edits stay.
const ACTION_FIELDS = {
  sent: ['bid_status', 'next_follow_up_date'],
  follow_up: ['next_follow_up_date'],
  note: [],
  won: ['bid_status', 'next_follow_up_date'],
  lost: ['bid_status', 'next_follow_up_date'],
}
const OUTCOME_STATUS = { won: 'Won', lost: 'Lost' }

const EVENT_DOTS = {
  status_change: 'bg-blue-400',
  sent: 'bg-cyan-400',
  follow_up: 'bg-amber-400',
  note: 'bg-gray-400',
  won: 'bg-emerald-400',
  lost: 'bg-red-400',
}

const WON_REASONS = ['Best price', 'Relationship with the GC', 'Best value / scope', 'Could meet the schedule']
const LOST_REASONS = ['Price too high', 'GC went with another sub', 'Project on hold or cancelled', 'Scope changed', 'Never heard back']

function fieldsFrom(tracking) {
  return Object.fromEntries(EDITABLE_FIELDS.map(key => [key, tracking?.[key] || '']))
}

// Fill the fields from newly loaded tracking without losing unsaved edits.
// A field keeps what the person typed unless it was just saved (`saved`, the
// values sent) or an action changed it on the server (`overwrite`).
function mergeFields(current, before, after, { overwrite = [], saved = {} } = {}) {
  if (!before) return fieldsFrom(after)
  return Object.fromEntries(EDITABLE_FIELDS.map((key) => {
    const typed = current[key] || ''
    const fresh = after?.[key] || ''
    const edited = typed !== (before[key] || '')
    const justSaved = key in saved && (saved[key] || '') === typed
    const changedByAction = overwrite.includes(key) && fresh !== (before[key] || '')
    return [key, !edited || justSaved || changedByAction ? fresh : typed]
  }))
}

function sameAmount(a, b) {
  return String(a ?? '') === String(b ?? '')
}

function blankForm(kind, tracking) {
  const today = localToday()
  const remark = OUTCOME_STATUS[kind] && tracking?.bid_status === OUTCOME_STATUS[kind]
  switch (kind) {
    case 'sent':
      return { sent_to: '', gc_name: tracking?.gc_name || '', sent_on: today, next_follow_up_date: addDays(today, 7), note: '' }
    case 'follow_up':
      return { note: '', next_follow_up_date: addDays(today, 7) }
    case 'won':
    case 'lost':
      // Already won/lost: start from what is saved so adding a note keeps it.
      if (remark) {
        return { reason: tracking.won_lost_reason || '', awarded_amount: tracking.awarded_amount ?? '', note: '' }
      }
      return { reason: '', awarded_amount: kind === 'won' ? (tracking?.bid_total ?? '') : '', note: '' }
    default:
      return { note: '' }
  }
}

function Field({ label, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      <span className={LABEL_CLASS}>{label}</span>
      {children}
    </label>
  )
}

// refreshKey: JobDetail bumps it whenever the proposal below is saved, so the
// bid total shown here (and recorded with a send) stays current.
export default function BidTrackingCard({ jobId, hasMaterials, refreshKey = 0 }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [fields, setFields] = useState(fieldsFrom(null))
  const [savingFields, setSavingFields] = useState(false)
  const [formKind, setFormKind] = useState(null) // null | 'sent' | 'follow_up' | 'note' | 'won' | 'lost'
  const [form, setForm] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [showAllHistory, setShowAllHistory] = useState(false)

  const tracking = data?.tracking
  const events = data?.events || []

  // Latest tracking and open form, for callbacks that finish later.
  const trackingRef = useRef(null)
  const formKindRef = useRef(null)
  // Bumped by every request and every finished save, so a reload that was
  // already on its way can't overwrite newer data when it lands.
  const requestSeqRef = useRef(0)

  const applyResult = useCallback((result, options) => {
    const before = trackingRef.current
    const after = result.tracking
    trackingRef.current = after
    setData(result)
    setFields(current => mergeFields(current, before, after, options))
    // A Won amount nobody has typed over follows a newly saved bid total.
    if (formKindRef.current === 'won' && before && before.bid_status !== 'Won') {
      setForm(f => (sameAmount(f.awarded_amount, before.bid_total) ? { ...f, awarded_amount: after?.bid_total ?? '' } : f))
    }
  }, [])

  const load = useCallback(async () => {
    const seq = ++requestSeqRef.current
    try {
      const result = await api.getBidTracking(jobId)
      if (seq === requestSeqRef.current) applyResult(result)
    } catch (err) {
      // Background reloads fail quietly; only a failed first load is shown.
      if (seq === requestSeqRef.current && !trackingRef.current) setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [jobId, applyResult])

  // Reload when the job gets its first materials (the default status changes)
  // and whenever the proposal is saved (the bid total changes).
  useEffect(() => { load() }, [load, hasMaterials, refreshKey])

  const dirty = useMemo(
    () => tracking && EDITABLE_FIELDS.some(key => (fields[key] || '') !== (tracking[key] || '')),
    [fields, tracking],
  )

  const saveFields = async () => {
    const changed = Object.fromEntries(
      EDITABLE_FIELDS.filter(key => (fields[key] || '') !== (tracking[key] || '')).map(key => [key, fields[key]]),
    )
    if (Object.keys(changed).length === 0) return
    setSavingFields(true)
    setError(null)
    try {
      const result = await api.updateBidTracking(jobId, changed)
      requestSeqRef.current += 1
      applyResult(result, { saved: changed })
    } catch (err) {
      setError(err.message)
    } finally {
      setSavingFields(false)
    }
  }

  const openForm = (kind) => {
    setError(null)
    formKindRef.current = kind
    setFormKind(kind)
    setForm(blankForm(kind, trackingRef.current))
    // Pick up a bid total saved since the page opened; unsaved edits stay.
    load()
  }

  const closeForm = () => {
    formKindRef.current = null
    setFormKind(null)
    setForm({})
  }

  const submitForm = async (e) => {
    e.preventDefault()
    const kind = formKind
    setSubmitting(true)
    setError(null)
    try {
      const payload = { event_type: kind, ...form }
      if (payload.awarded_amount === '') delete payload.awarded_amount
      const result = await api.addBidEvent(jobId, payload)
      requestSeqRef.current += 1
      applyResult(result, { overwrite: ACTION_FIELDS[kind] || [] })
      closeForm()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const setFormValue = (key) => (e) => setForm(f => ({ ...f, [key]: e.target.value }))
  const setFieldValue = (key) => (e) => setFields(f => ({ ...f, [key]: e.target.value }))

  // Sent / Won / Lost go through their own form so the send date, bid total,
  // reason and amount get recorded; the status list stays on the saved status.
  const changeStatus = (e) => {
    const status = e.target.value
    const formForStatus = STATUS_FORMS[status]
    if (formForStatus && status !== tracking.bid_status) {
      setFields(f => ({ ...f, bid_status: tracking.bid_status }))
      openForm(formForStatus)
      return
    }
    setFields(f => ({ ...f, bid_status: status }))
  }

  if (loading) {
    return (
      <div className="glass-card p-4 mb-4 flex items-center gap-2 text-sm text-gray-500">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading bid tracking...
      </div>
    )
  }
  if (!tracking) {
    return error ? (
      <div className="glass-card p-4 mb-4 flex items-center gap-2 text-sm text-red-400">
        <AlertTriangle className="w-4 h-4" /> Bid tracking could not load: {error}
      </div>
    ) : null
  }

  const formValid = {
    sent: true,
    follow_up: Boolean(form.note?.trim() || form.next_follow_up_date),
    note: Boolean(form.note?.trim()),
    won: true,
    lost: true,
  }[formKind]

  const statusLine = (() => {
    if ((tracking.bid_status === 'Won' || tracking.bid_status === 'Lost') && tracking.won_lost_at) {
      return [
        `${tracking.bid_status} ${formatDay(tracking.won_lost_at)}`,
        tracking.won_lost_reason,
        tracking.awarded_amount !== null && tracking.awarded_amount !== undefined ? `awarded ${formatMoney(tracking.awarded_amount)}` : null,
      ].filter(Boolean).join(' · ')
    }
    if (tracking.last_sent_date) {
      const who = tracking.last_sent_to || tracking.last_sent_gc
      return `Last sent ${formatDay(tracking.last_sent_date)}${who ? ` to ${who}` : ''} (${daysAgoText(tracking.days_since_sent)})`
    }
    return null
  })()

  const visibleEvents = showAllHistory ? events : events.slice(0, HISTORY_PREVIEW)

  return (
    <div className="glass-card p-4 sm:p-5 mb-4">
      {/* Title row */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <ClipboardList className="w-4 h-4 text-gray-400" />
        <h2 className="text-xs font-bold text-gray-400 uppercase tracking-[0.15em]">Bid Tracking</h2>
        <BidStatusBadge status={tracking.bid_status} />
        {tracking.is_open && tracking.bid_due_date && (tracking.due_overdue || tracking.due_soon) && (
          <span className={`text-xs font-medium ${tracking.due_overdue ? 'text-red-400' : 'text-amber-400'}`}>
            {dueText(tracking.days_until_due)}
          </span>
        )}
        {(tracking.follow_up_overdue || tracking.follow_up_due_today) && (
          <span className={`text-xs font-medium ${tracking.follow_up_overdue ? 'text-red-400' : 'text-amber-400'}`}>
            {tracking.follow_up_overdue ? 'Follow-up past due' : 'Follow up today'}
          </span>
        )}
        <div className="ml-auto text-sm text-gray-400">
          {tracking.bid_total !== null && tracking.bid_total !== undefined
            ? <>Bid total <span className="font-semibold text-white tabular-nums">{formatMoney(tracking.bid_total)}</span></>
            : <span className="text-gray-600">No saved bid total yet</span>}
        </div>
      </div>
      {statusLine && <p className="mt-1.5 text-xs text-gray-500">{statusLine}</p>}

      {/* Editable fields */}
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <Field label={tracking.bid_status_is_default && fields.bid_status === tracking.bid_status ? 'Status (automatic until set)' : 'Status'}>
          <select value={fields.bid_status} onChange={changeStatus} className={FIELD_CLASS}>
            {BID_STATUSES.map(status => <option key={status} value={status} className="bg-[#111827]">{status}</option>)}
          </select>
        </Field>
        <Field label="Bid due date">
          <input type="date" value={fields.bid_due_date} onChange={setFieldValue('bid_due_date')}
            className={`w-full ${FIELD_BASE} ${tracking.due_overdue && fields.bid_due_date === tracking.bid_due_date ? 'text-red-400' : 'text-white'}`} />
        </Field>
        <Field label="Due time (optional)">
          <input type="time" value={fields.bid_due_time} onChange={setFieldValue('bid_due_time')} className={FIELD_CLASS} />
        </Field>
        <Field label="Estimator">
          <input type="text" value={fields.estimator} onChange={setFieldValue('estimator')}
            className={FIELD_CLASS} placeholder="Who is estimating" maxLength={200} />
        </Field>
        <Field label="Next follow-up">
          <input type="date" value={fields.next_follow_up_date} onChange={setFieldValue('next_follow_up_date')}
            className={`w-full ${FIELD_BASE} ${tracking.follow_up_overdue && fields.next_follow_up_date === tracking.next_follow_up_date ? 'text-red-400' : 'text-white'}`} />
        </Field>
      </div>
      {dirty && (
        <div className="mt-3 flex items-center gap-2">
          <button type="button" onClick={saveFields} disabled={savingFields} className="btn-primary text-sm px-4 py-2">
            {savingFields ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save changes
          </button>
          <button type="button" onClick={() => setFields(fieldsFrom(tracking))} className="btn-ghost text-sm px-4 py-2">Cancel</button>
        </div>
      )}

      {/* Actions */}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={() => openForm('sent')}
          className={`btn-secondary text-xs px-3 py-2 ${formKind === 'sent' ? 'bg-white/[0.09] text-white' : ''}`}>
          <Send className="w-3.5 h-3.5" /> Mark as sent
        </button>
        <button type="button" onClick={() => openForm('follow_up')}
          className={`btn-secondary text-xs px-3 py-2 ${formKind === 'follow_up' ? 'bg-white/[0.09] text-white' : ''}`}>
          <PhoneCall className="w-3.5 h-3.5" /> Log follow-up
        </button>
        <button type="button" onClick={() => openForm('note')}
          className={`btn-secondary text-xs px-3 py-2 ${formKind === 'note' ? 'bg-white/[0.09] text-white' : ''}`}>
          <MessageSquarePlus className="w-3.5 h-3.5" /> Add note
        </button>
        <button type="button" onClick={() => openForm('won')}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium border transition-colors
                     bg-emerald-500/10 border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/20">
          <Trophy className="w-3.5 h-3.5" /> Won
        </button>
        <button type="button" onClick={() => openForm('lost')}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium border transition-colors
                     bg-red-500/10 border-red-500/20 text-red-400 hover:bg-red-500/20">
          <ThumbsDown className="w-3.5 h-3.5" /> Lost
        </button>
      </div>

      {error && (
        <div className="mt-3 flex items-center gap-2 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
          <button type="button" onClick={() => setError(null)} className="ml-auto p-1 text-red-500/60 hover:text-red-400" title="Dismiss">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Action form (inline, not a pop-up) */}
      {formKind && (
        <form onSubmit={submitForm} className="mt-3 rounded-xl border border-white/[0.08] bg-white/[0.02] p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">
              {{ sent: 'Mark as sent', follow_up: 'Log a follow-up', note: 'Add a note', won: 'Mark as won', lost: 'Mark as lost' }[formKind]}
            </h3>
            <button type="button" onClick={closeForm} className="text-xs text-gray-500 hover:text-gray-300">Close</button>
          </div>

          {formKind === 'sent' && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Sent to (names or emails)">
                  <input type="text" value={form.sent_to} onChange={setFormValue('sent_to')} className={FIELD_CLASS}
                    placeholder="e.g. Jane Smith, bids@acmegc.com" autoFocus maxLength={500} />
                </Field>
                <Field label="GC">
                  <input type="text" value={form.gc_name} onChange={setFormValue('gc_name')} className={FIELD_CLASS}
                    placeholder="General contractor" maxLength={200} />
                </Field>
                <Field label="Sent on">
                  <input type="date" value={form.sent_on} onChange={setFormValue('sent_on')} className={FIELD_CLASS} max={addDays(localToday(), 1)} />
                </Field>
                <Field label="Follow up on (optional)">
                  <input type="date" value={form.next_follow_up_date} onChange={setFormValue('next_follow_up_date')} className={FIELD_CLASS} />
                </Field>
              </div>
              <Field label="Note (optional)">
                <input type="text" value={form.note} onChange={setFormValue('note')} className={FIELD_CLASS}
                  placeholder="e.g. Emailed the PDF, alternates included" maxLength={2000} />
              </Field>
              <p className="text-xs text-gray-500">
                {tracking.bid_total !== null && tracking.bid_total !== undefined
                  ? <>The bid total of <span className="text-gray-300 font-medium">{formatMoney(tracking.bid_total)}</span> is recorded with this send.</>
                  : 'There is no saved bid total yet, so none will be recorded.'}
                {' '}Nothing is emailed from here.
              </p>
            </>
          )}

          {formKind === 'follow_up' && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <Field label="What happened" className="sm:col-span-2">
                <input type="text" value={form.note} onChange={setFormValue('note')} className={FIELD_CLASS}
                  placeholder="e.g. Called Jane, they award next week" autoFocus maxLength={2000} />
              </Field>
              <Field label="Next follow-up">
                <input type="date" value={form.next_follow_up_date} onChange={setFormValue('next_follow_up_date')} className={FIELD_CLASS} />
              </Field>
            </div>
          )}

          {formKind === 'note' && (
            <Field label="Note">
              <textarea value={form.note} onChange={setFormValue('note')} className={`${FIELD_CLASS} min-h-[70px] resize-y`}
                placeholder="e.g. GC asked for LVT alternate pricing" autoFocus maxLength={2000} />
            </Field>
          )}

          {(formKind === 'won' || formKind === 'lost') && (
            <>
              {tracking.bid_status === OUTCOME_STATUS[formKind] && (
                <p className="text-xs text-gray-500">
                  This bid is already marked {formKind}. The saved reason and amount are filled in below; a field left blank keeps what's saved.
                </p>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Reason (optional)">
                  <input type="text" value={form.reason} onChange={setFormValue('reason')} className={FIELD_CLASS}
                    list={`bid-${formKind}-reasons`} placeholder={formKind === 'won' ? 'e.g. Best price' : 'e.g. Price too high'}
                    autoFocus maxLength={500} />
                  <datalist id={`bid-${formKind}-reasons`}>
                    {(formKind === 'won' ? WON_REASONS : LOST_REASONS).map(reason => <option key={reason} value={reason} />)}
                  </datalist>
                </Field>
                <Field label={formKind === 'won' ? 'Awarded amount (optional)' : 'Winning number, if you know it (optional)'}>
                  <input type="text" inputMode="decimal" value={form.awarded_amount} onChange={setFormValue('awarded_amount')}
                    className={FIELD_CLASS} placeholder="e.g. 125,000" />
                </Field>
              </div>
              <Field label="Note (optional)">
                <input type="text" value={form.note} onChange={setFormValue('note')} className={FIELD_CLASS} maxLength={2000} />
              </Field>
            </>
          )}

          <div className="flex items-center gap-2">
            <button type="submit" disabled={submitting || !formValid} className="btn-primary text-sm px-4 py-2">
              {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
              {{ sent: 'Mark as sent', follow_up: 'Save follow-up', note: 'Save note', won: 'Mark as won', lost: 'Mark as lost' }[formKind]}
            </button>
            <button type="button" onClick={closeForm} className="btn-ghost text-sm px-4 py-2">Cancel</button>
          </div>
        </form>
      )}

      {/* History */}
      <div className="mt-4 pt-4 border-t border-white/[0.05]">
        <div className="text-[10px] font-bold text-gray-600 uppercase tracking-[0.15em] mb-2">History</div>
        {events.length === 0 ? (
          <p className="text-xs text-gray-600">Nothing logged yet. Status changes, sends, follow-ups and results show up here with who did them.</p>
        ) : (
          <>
            <ul className="space-y-3">
              {visibleEvents.map(event => {
                const facts = bidEventFacts(event)
                return (
                  <li key={event.id} className="flex gap-3">
                    <span className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${EVENT_DOTS[event.event_type] || 'bg-gray-400'}`} />
                    <div className="min-w-0">
                      <div className="text-sm text-gray-200">{describeBidEvent(event)}</div>
                      {facts.length > 0 && <div className="text-xs text-gray-500 mt-0.5">{facts.join(' · ')}</div>}
                      {event.details?.note && (
                        <div className="text-xs text-gray-400 mt-1 whitespace-pre-wrap break-words">"{event.details.note}"</div>
                      )}
                      <div className="text-[11px] text-gray-600 mt-0.5">{event.display_name} · {formatWhen(event.created_at)}</div>
                    </div>
                  </li>
                )
              })}
            </ul>
            {events.length > HISTORY_PREVIEW && (
              <button type="button" onClick={() => setShowAllHistory(v => !v)}
                className="mt-3 text-xs text-si-bright hover:underline">
                {showAllHistory ? 'Show less' : `Show all ${events.length}`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
