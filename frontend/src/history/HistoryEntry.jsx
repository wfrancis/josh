import { useMemo, useState } from 'react'
import { ArrowRight, ArrowUpRight, ChevronDown, Lock } from 'lucide-react'
import TextDiff, { diffTokens } from './TextDiff'
import {
  changeCount, describeEntry, entityLabel, entryKind, entryPeople, fieldLabel, formatValue, fullTime,
  isBlank, isRedacted, isTextChange, pathLabel, sourceLabel, summarizeRow, timeRange,
} from './fieldLabels'

// One history entry (grouped edits included): who, what, when, and on click
// the field-by-field before/after. Shared by the bid's History drawer and the
// Audit page.

const FIRST_CHANGES_SHOWN = 25
const DERIVED_SHOWN = 100

function Dot() {
  return <span className="text-gray-700" aria-hidden="true">·</span>
}

// A before or after value. tone: old | new | add | remove. label: the change's
// label, so a row's name isn't repeated right next to it.
function Value({ value, path, tone, label = '' }) {
  const blank = isBlank(value)
  const text = value && typeof value === 'object' && !Array.isArray(value) && !value.truncated && !value.redacted
    ? summarizeRow(value, label)
    : formatValue(value, path)
  const style = blank
    ? 'text-gray-600 italic'
    : tone === 'old' ? 'text-red-300/80 line-through decoration-red-400/50'
      : tone === 'remove' ? 'text-red-300/90 line-through decoration-red-400/50'
        : 'text-emerald-300'
  return <span className={`text-[13px] break-words ${style}`}>{text}</span>
}

// A list of lines (terms, exclusions, notes lines): changed lines only, with a
// word-by-word diff when one line was edited.
function LinesDiff({ change }) {
  const ops = useMemo(() => {
    const toLines = (value) => (Array.isArray(value) ? value.map(line => String(line ?? '')) : isBlank(value) ? [] : null)
    const before = toLines(change.before)
    const after = toLines(change.after)
    return before && after ? diffTokens(before, after) : null
  }, [change.before, change.after])
  if (!ops) {
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        <Value value={change.before} path={change.path} tone="old" />
        <ArrowRight className="w-3 h-3 text-gray-600" />
        <Value value={change.after} path={change.path} tone="new" />
      </div>
    )
  }
  const rows = []
  const pairedWithPrevious = new Set()
  ops.forEach((op, index) => {
    if (op.type === 'same') {
      if (index === 0 || index === ops.length - 1 || op.tokens.length > 2) {
        rows.push(
          <div key={`s${index}`} className="text-[11px] text-gray-600 italic">
            {op.tokens.length} unchanged line{op.tokens.length === 1 ? '' : 's'}
          </div>,
        )
      } else {
        op.tokens.forEach((line, i) => rows.push(<div key={`s${index}-${i}`} className="text-[13px] text-gray-500">{line}</div>))
      }
      return
    }
    const next = ops[index + 1]
    // One line swapped for one line: show which words changed.
    if (op.type === 'del' && next && next.type === 'ins' && op.tokens.length === next.tokens.length) {
      op.tokens.forEach((line, i) => rows.push(
        <div key={`p${index}-${i}`} className="flex gap-2">
          <span className="text-gray-600 select-none text-[13px]">~</span>
          <TextDiff before={line} after={next.tokens[i]} className="flex-1 min-w-0" />
        </div>,
      ))
      pairedWithPrevious.add(index + 1)
      return
    }
    if (pairedWithPrevious.has(index)) return
    const removed = op.type === 'del'
    op.tokens.forEach((line, i) => rows.push(
      <div key={`${op.type}${index}-${i}`} className="flex gap-2 text-[13px]">
        <span className={`select-none ${removed ? 'text-red-400/70' : 'text-emerald-400/70'}`}>{removed ? '−' : '+'}</span>
        <span className={`flex-1 min-w-0 break-words ${removed ? 'text-red-300/90 line-through decoration-red-400/40' : 'text-emerald-300'}`}>
          {line || <span className="italic text-gray-600">(blank line)</span>}
        </span>
      </div>,
    ))
  })
  return <div className="space-y-0.5">{rows}</div>
}

function ChangeRow({ change, item }) {
  const label = pathLabel(change.path, item)
  let body
  if (change.redacted || isRedacted(change.before) || isRedacted(change.after)) {
    body = (
      <span className="inline-flex items-center gap-1.5 text-xs text-gray-500">
        <Lock className="w-3 h-3" /> Changed (hidden for security)
      </span>
    )
  } else if (change.op === 'lines') {
    body = <LinesDiff change={change} />
  } else if (change.op === 'add' || (change.op !== 'remove' && isBlank(change.before) && !isBlank(change.after))) {
    body = typeof change.after === 'string' && change.after.length > 40
      ? <TextDiff before="" after={change.after} />
      : <span className="inline-flex flex-wrap items-baseline gap-1.5"><span className="text-[11px] text-gray-500">Added</span><Value value={change.after} path={change.path} tone="add" label={label} /></span>
  } else if (change.op === 'remove' || (isBlank(change.after) && !isBlank(change.before))) {
    body = typeof change.before === 'string' && change.before.length > 40
      ? <TextDiff before={change.before} after="" />
      : <span className="inline-flex flex-wrap items-baseline gap-1.5"><span className="text-[11px] text-gray-500">Removed</span><Value value={change.before} path={change.path} tone="remove" label={label} /></span>
  } else if (isTextChange(change)) {
    body = <TextDiff before={change.before} after={change.after} />
  } else {
    body = (
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
        <Value value={change.before} path={change.path} tone="old" />
        <ArrowRight className="w-3 h-3 text-gray-600 flex-shrink-0" />
        <Value value={change.after} path={change.path} tone="new" />
      </div>
    )
  }
  return (
    <div>
      <div className="text-xs font-medium text-gray-400 mb-0.5 break-words">{label}</div>
      {body}
    </div>
  )
}

// Older entries kept extra facts (files, vendors, comment text) outside the changes.
function ExtraDetail({ item }) {
  const detail = item.extra?.detail
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null
  const lines = []
  for (const [key, value] of Object.entries(detail)) {
    if (value === null || value === undefined || value === '' || key.startsWith('_')) continue
    if (Array.isArray(value)) {
      if (value.length === 0 || value.some(entry => entry && typeof entry === 'object')) continue
      lines.push([fieldLabel(key), value.join(', ')])
    } else if (typeof value !== 'object') {
      lines.push([fieldLabel(key), formatValue(value, '/' + key)])
    }
    if (lines.length >= 6) break
  }
  if (lines.length === 0) return null
  return (
    <dl className="space-y-0.5 text-xs">
      {lines.map(([label, value]) => (
        <div key={label} className="flex gap-2">
          <dt className="text-gray-500 flex-shrink-0">{label}:</dt>
          <dd className="text-gray-300 break-words min-w-0">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function EntryFooter({ item }) {
  const people = entryPeople(item)
  const grouped = people.length > 1 || (Number(item.edit_count) || 0) > 1
  const started = fullTime(item.ts_first)
  const ended = fullTime(item.ts)
  return (
    <div className="pt-2 mt-1 border-t border-white/[0.05] space-y-0.5 text-[11px] text-gray-600">
      {grouped && people.some(person => person.editCount) && (
        <div>
          {people.map(person => `${person.name}${person.editCount ? ` (${person.editCount} edit${person.editCount === 1 ? '' : 's'})` : ''}`).join(', ')}
        </div>
      )}
      <div>{started && started !== ended ? `${started} to ${ended}` : ended}</div>
      {item.request_id && (
        <div className="font-mono truncate" title="Reference for this change, for tracing it in the server logs">
          Ref {item.request_id}
        </div>
      )}
    </div>
  )
}

export function ChangeList({ item }) {
  const changes = Array.isArray(item.changes) ? item.changes : []
  const edits = changes.filter(change => !change.derived)
  const derived = changes.filter(change => change.derived)
  const [showAll, setShowAll] = useState(false)
  // Nothing but worked-out values (e.g. a recalculation): show them straight away.
  const [showDerived, setShowDerived] = useState(edits.length === 0)
  const shown = showAll ? edits : edits.slice(0, FIRST_CHANGES_SHOWN)
  const truncated = item.extra?.changes_truncated

  return (
    <div className="space-y-2.5">
      {changes.length === 0 && (
        <p className="text-xs text-gray-500">No field-by-field details were recorded for this change.</p>
      )}
      {shown.map((change, index) => <ChangeRow key={`${change.path}-${index}`} change={change} item={item} />)}
      {edits.length > shown.length && (
        <button type="button" onClick={() => setShowAll(true)} className="text-xs font-medium text-si-bright hover:text-blue-300">
          Show all {edits.length} changes
        </button>
      )}
      {derived.length > 0 && edits.length > 0 && (
        <button
          type="button"
          onClick={() => setShowDerived(value => !value)}
          className="block text-[11px] text-gray-500 hover:text-gray-300"
        >
          {showDerived ? 'Hide' : 'Show'} {derived.length} worked-out value{derived.length === 1 ? '' : 's'} (totals and costs recalculated from these edits)
        </button>
      )}
      {showDerived && derived.length > 0 && (
        <div className="space-y-2.5 pl-3 border-l border-white/[0.06]">
          {derived.slice(0, DERIVED_SHOWN).map((change, index) => <ChangeRow key={`d-${change.path}-${index}`} change={change} item={item} />)}
          {derived.length > DERIVED_SHOWN && (
            <p className="text-[11px] text-gray-600">and {derived.length - DERIVED_SHOWN} more worked-out values</p>
          )}
        </div>
      )}
      {truncated && (
        <p className="text-[11px] text-amber-400/80">
          This was a very large change. Showing {truncated.kept} of its {truncated.total} parts.
        </p>
      )}
      <ExtraDetail item={item} />
      <EntryFooter item={item} />
    </div>
  )
}

// onOpen: when given, clicking the entry calls it (e.g. open the bid) and the
// arrow button on the right shows the details instead.
export default function HistoryEntry({ item, expanded, onToggle, onOpen, highlighted = false, showJob = false }) {
  const kind = entryKind(item)
  const { who, text, joined, detail } = describeEntry(item)
  const count = changeCount(item)
  const source = sourceLabel(item.source)
  const system = item.actor_kind === 'system'
  const canOpen = !!onOpen && item.job_id != null

  const handleMain = () => {
    if (canOpen) onOpen(item)
    else onToggle?.(item.id)
  }

  return (
    <li
      id={`history-entry-${item.id}`}
      className={`rounded-xl border transition-colors scroll-mt-4
        ${highlighted
          ? 'border-si-bright/40 bg-si-bright/[0.06] ring-1 ring-si-bright/25'
          : expanded ? 'border-white/[0.08] bg-white/[0.03]' : 'border-transparent hover:bg-white/[0.03]'}
        ${item.net_noop ? 'opacity-70' : ''}`}
    >
      <div className="flex items-start gap-3 px-3 py-2.5">
        <span
          className={`mt-[7px] w-2 h-2 rounded-full flex-shrink-0 ${kind?.dot || 'bg-gray-500'} ${item.group_open ? 'animate-pulse' : ''}`}
          title={kind?.label}
        />
        <button
          type="button"
          onClick={handleMain}
          className="flex-1 min-w-0 text-left"
          title={canOpen ? 'Open this change in its bid' : undefined}
        >
          <div className="text-sm text-gray-300 leading-snug break-words">
            <span className={`font-semibold ${system ? 'text-gray-400' : 'text-white'}`}>{who}</span>
            {joined ? ' ' : <span className="text-gray-600"> · </span>}
            {text}
          </div>
          {detail && <div className="mt-0.5 text-xs text-gray-500 line-clamp-2 break-words">{detail}</div>}
          <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-gray-500">
            <span title={fullTime(item.ts)}>{timeRange(item)}</span>
            {count > 1 && <><Dot /><span>{count} changes</span></>}
            {showJob && item.job_id != null && (
              <>
                <Dot />
                <span className="inline-flex items-center gap-0.5 text-gray-400 min-w-0">
                  <span className="truncate max-w-[18rem]">{item.job_name || `Bid #${item.job_id}`}</span>
                  {canOpen && <ArrowUpRight className="w-3 h-3 flex-shrink-0" />}
                </span>
              </>
            )}
            {showJob && item.job_id == null && item.entity_type && <><Dot /><span>{entityLabel(item.entity_type)}</span></>}
            {source && <><Dot /><span>via {source}</span></>}
            {item.group_open && <><Dot /><span className="text-emerald-400/90">still being edited</span></>}
            {item.net_noop && <><Dot /><span className="italic">ended where it started</span></>}
          </div>
        </button>
        <button
          type="button"
          onClick={() => onToggle?.(item.id)}
          aria-expanded={!!expanded}
          title={expanded ? 'Hide the changes' : 'Show the changes'}
          className="p-1 -mr-1 mt-0.5 rounded-md text-gray-600 hover:text-gray-300 hover:bg-white/[0.06] flex-shrink-0"
        >
          <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </button>
      </div>
      {expanded && (
        <div className="px-3 pb-3 pl-8">
          <ChangeList item={item} />
        </div>
      )}
    </li>
  )
}
