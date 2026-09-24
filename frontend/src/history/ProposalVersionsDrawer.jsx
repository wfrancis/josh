import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertTriangle, ArchiveRestore, Check, CheckCircle2, Eye, FileDown, GitCompare,
  Info, Layers, Loader2, Pencil, RefreshCw, Send, X,
} from 'lucide-react'
import { api } from '../api'
import { formatDay, formatMoney, formatWhen } from '../bidTracker'
import ConfirmDialog from '../components/ConfirmDialog'
import { ChangeRow } from './HistoryEntry'
import { fieldLabel, humanize, rowName, splitPath } from './fieldLabels'

// Saved copies of a bid's proposal: when each was taken and why, who worked
// on it, its total, and the PDF made from it. Each one can be previewed,
// compared with the current proposal, named, and restored. A restore first
// saves the current proposal as a version, so nothing is ever lost.
//
// onRestore(version) does the restore (the editor saves pending edits first
// and reloads afterwards) and resolves with the server's reply: { job,
// version, unchanged, before_restore_version_id, job_fields_differ,
// materials_changed_since }.

const REASON_TEXT = {
  edit_burst: 'Saved after editing',
  generate: 'Generated from materials',
  before_regenerate: 'Before regenerate',
  pdf: 'PDF made',
  sent: 'Sent to GC',
  before_restore: 'Before restore',
  restore: 'Restored',
  rfms_upload: 'After new takeoff upload',
  baseline: 'Original',
}

const LABEL_MAX = 120
// Roots of the paths a comparison sends: the proposal itself, and the bid's
// own fields (header, tax, GPM, Textura, exclusions), which a restore leaves alone.
const PROPOSAL_ROOTS = new Set(['proposal_data', 'proposal'])
const BID_FIELD_ROOTS = new Set(['job_fields', 'job'])
// Bid fields named so they can't be mistaken for the proposal's own rows.
const BID_FIELD_LABELS = {
  tax_rate: 'Bid tax rate',
  gpm_pct: 'Bid GPM',
  textura_fee: 'Bid Textura fee',
  exclusions: 'Bid exclusions',
}

function bidFieldLabel(key) {
  return BID_FIELD_LABELS[key] || fieldLabel(key) || humanize(key)
}

// "tax rate, GPM and general contractor" for a list of bid field keys.
function bidFieldList(keys) {
  const names = [...new Set((keys || []).map(key => {
    const label = BID_FIELD_LABELS[key] ? BID_FIELD_LABELS[key].replace(/^Bid /, '') : (fieldLabel(key) || humanize(key))
    return /^[A-Z]{2,}/.test(label) || /^Textura/.test(label) ? label : label.charAt(0).toLowerCase() + label.slice(1)
  }))]
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

function reasonText(version, byId) {
  if (version.reason === 'restore') {
    const from = byId.get(version.restored_from_version_id)
    if (from) return `Restored from v${from.version_no}`
    return version.restored_from_version_id ? 'Restored an earlier version' : REASON_TEXT.restore
  }
  return REASON_TEXT[version.reason] || humanize(version.reason) || 'Saved'
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

function bundleName(bundle, index) {
  const name = bundle?.bundle_name || bundle?.name
  return typeof name === 'string' && name.trim() ? name.trim() : `Bundle ${index + 1}`
}

function bundlePrice(bundle) {
  const value = bundle?.price_override ?? bundle?.total_price
  return value === null || value === undefined || value === '' ? null : Number(value)
}

function sameMoney(a, b) {
  if (a === null || a === undefined || b === null || b === undefined) return false
  return Math.abs(Number(a) - Number(b)) < 0.005
}

function moneyDelta(before, after) {
  if (before === null || before === undefined || after === null || after === undefined) return ''
  const delta = Number(after) - Number(before)
  if (!Number.isFinite(delta) || Math.abs(delta) < 0.005) return 'no change'
  return `${delta > 0 ? '+' : '−'}${formatMoney(Math.abs(delta))}`
}

// ── Grouping a diff by bundle ───────────────────────────────────────────────

// Path without the proposal root ("/proposal/notes" -> "/notes").
function withoutProposalRoot(path) {
  const raw = String(path || '').split('/')
  if (raw.length > 2 && PROPOSAL_ROOTS.has(raw[1])) return '/' + raw.slice(2).join('/')
  return String(path || '')
}

// The bid field a change is about ("/job_fields/tax_rate" -> "tax_rate"), or null.
function bidFieldKey(path) {
  const raw = String(path || '').split('/')
  return raw.length > 2 && BID_FIELD_ROOTS.has(raw[1]) ? splitPath(path)[1] : null
}

function groupChanges(changes) {
  const bundles = new Map()
  const other = []
  const bidFields = []
  for (const change of changes) {
    const fieldKey = bidFieldKey(change.path)
    if (fieldKey) {
      // Kept apart (with its full path, so values format by field): a restore doesn't change these.
      bidFields.push({ ...change, fieldKey })
      continue
    }
    const path = withoutProposalRoot(change.path)
    const raw = path.split('/')
    const parts = splitPath(path)
    const index = parts.indexOf('bundles')
    if (index < 0 || parts.length <= index + 1 || parts[index + 1] === '_order') {
      other.push({ ...change, path })
      continue
    }
    const key = parts[index + 1]
    // raw[0] is '' (paths start with '/'), so part i is raw[i + 1].
    const rest = raw.slice(index + 3)
    let group = bundles.get(key)
    if (!group) {
      group = { key, whole: null, changes: [] }
      bundles.set(key, group)
    }
    if (rest.length === 0) group.whole = change
    else group.changes.push({ ...change, path: '/' + rest.join('/') })
  }
  return { bundles: [...bundles.values()], other, bidFields }
}

function groupName(group, names, fallbackIndex) {
  const whole = group.whole
  const fromWhole = whole ? rowName(whole.after) || rowName(whole.before) : ''
  if (fromWhole) return fromWhole
  const rename = group.changes.find(change => change.path === '/bundle_name')
  if (rename) {
    const value = typeof rename.after === 'string' && rename.after.trim() ? rename.after : rename.before
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  if (names.has(group.key)) return names.get(group.key)
  if (/^\d+$/.test(group.key)) return `Bundle ${Number(group.key) + 1}`
  return `Bundle ${fallbackIndex + 1}`
}

// Bundle names by uid / id, from any list of bundles we have.
function bundleNames(...lists) {
  const names = new Map()
  for (const list of lists) {
    if (!Array.isArray(list)) continue
    list.forEach((bundle, index) => {
      const name = bundleName(bundle, index)
      for (const key of ['uid', 'id', 'bundle_uid']) {
        const value = bundle?.[key]
        if (value !== null && value !== undefined && value !== '' && !names.has(String(value))) names.set(String(value), name)
      }
    })
  }
  return names
}

function CompareChange({ change, item, label }) {
  if (/(^|\/)_order$/.test(change.path)) {
    const parent = splitPath(change.path).slice(-2, -1)[0]
    return (
      <div>
        <div className="text-xs font-medium text-gray-400 mb-0.5">{label || (parent ? `Order of ${humanize(parent).toLowerCase()}` : 'Order')}</div>
        <span className="text-[13px] text-gray-300">The order changed.</span>
      </div>
    )
  }
  return <ChangeRow change={change} item={item} label={label} />
}

function BundleGroup({ group, name }) {
  const [showDerived, setShowDerived] = useState(false)
  const whole = group.whole
  const item = useMemo(() => ({ changes: group.changes }), [group.changes])
  const edits = group.changes.filter(change => !change.derived)
  const derived = group.changes.filter(change => change.derived)
  // The bundle's price before and after: a typed price wins over the worked-out one.
  const override = group.changes.find(change => change.path === '/price_override')
  const worked = group.changes.find(change => change.path === '/total_price')
  const priceBefore = override && override.before != null ? override.before : worked?.before
  const priceAfter = override && override.after != null ? override.after : worked?.after
  const showPrice = !whole && (override || worked) && (priceBefore != null || priceAfter != null)

  let badge = { text: 'Changed', style: 'bg-si-bright/10 text-blue-300 border-si-bright/20' }
  if (whole?.op === 'add' || (whole && whole.before == null)) badge = { text: 'Added', style: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' }
  else if (whole?.op === 'remove' || (whole && whole.after == null)) badge = { text: 'Removed', style: 'bg-red-500/10 text-red-300 border-red-500/20' }

  const row = whole ? (whole.after || whole.before) : null
  const rowDescription = row && typeof row === 'object' ? (row.description_text || row.description || '') : ''
  const rowPrice = row && typeof row === 'object' ? bundlePrice(row) : null

  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${badge.style}`}>{badge.text}</span>
        <span className="text-sm font-semibold text-white break-words min-w-0">{name}</span>
        {showPrice && (
          <span className="ml-auto text-xs tabular-nums text-gray-400 whitespace-nowrap">
            {formatMoney(priceBefore) || '—'} → <span className="text-gray-200">{formatMoney(priceAfter) || '—'}</span>
          </span>
        )}
        {whole && rowPrice !== null && (
          <span className="ml-auto text-xs tabular-nums text-gray-300 whitespace-nowrap">{formatMoney(rowPrice)}</span>
        )}
      </div>
      {whole ? (
        rowDescription ? <p className="mt-1.5 text-xs text-gray-400 whitespace-pre-wrap break-words line-clamp-4">{rowDescription}</p> : null
      ) : (
        <div className="mt-2 space-y-2.5">
          {edits.map((change, index) => (
            <CompareChange key={`${change.path}-${index}`} change={change} item={item} />
          ))}
          {edits.length === 0 && derived.length > 0 && !showDerived && (
            <p className="text-xs text-gray-500">Only worked-out values changed (totals recalculated).</p>
          )}
          {derived.length > 0 && (
            <button
              type="button"
              onClick={() => setShowDerived(value => !value)}
              className="block text-[11px] text-gray-500 hover:text-gray-300"
            >
              {showDerived ? 'Hide' : 'Show'} {plural(derived.length, 'worked-out value')}
            </button>
          )}
          {showDerived && (
            <div className="space-y-2.5 pl-3 border-l border-white/[0.06]">
              {derived.map((change, index) => (
                <CompareChange key={`d-${change.path}-${index}`} change={change} item={item} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Preview and compare panels ──────────────────────────────────────────────

function VersionPreview({ detail }) {
  const data = detail?.proposal_data || {}
  const fields = detail?.job_fields || {}
  const bundles = Array.isArray(data.bundles) ? data.bundles : []
  const total = data.grand_total ?? detail?.grand_total
  const taxRate = fields.tax_rate ?? data.tax_rate
  const gpm = fields.gpm_pct ?? data.gpm_pct
  const lists = [
    ['note', data.notes],
    ['term', data.terms],
    ['exclusion', data.exclusions],
  ].filter(([, list]) => Array.isArray(list) && list.length > 0)

  if (bundles.length === 0) {
    return <p className="text-xs text-gray-500">This version has no bundles.</p>
  }
  return (
    <div className="space-y-2">
      <ul className="space-y-1.5">
        {bundles.map((bundle, index) => {
          const price = bundlePrice(bundle)
          const description = bundle.description_text || bundle.description || ''
          return (
            <li key={bundle.uid || `${bundleName(bundle, index)}-${index}`} className="rounded-lg bg-white/[0.02] border border-white/[0.05] px-3 py-2">
              <div className="flex items-start gap-3">
                <span className="flex-1 min-w-0 text-sm font-medium text-gray-200 break-words">{bundleName(bundle, index)}</span>
                <span className="text-xs tabular-nums text-gray-300 whitespace-nowrap">{price !== null ? formatMoney(price) : '—'}</span>
              </div>
              {description && (
                <p className="mt-1 text-xs text-gray-500 whitespace-pre-wrap break-words line-clamp-3">{description}</p>
              )}
            </li>
          )
        })}
      </ul>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs text-gray-500">
        {total !== null && total !== undefined && (
          <span>Grand total <span className="text-gray-200 font-semibold tabular-nums">{formatMoney(total)}</span></span>
        )}
        {taxRate !== null && taxRate !== undefined && taxRate !== '' && (
          <span>Tax {(Number(taxRate) * 100).toFixed(2)}%</span>
        )}
        {gpm !== null && gpm !== undefined && gpm !== '' && Number(gpm) > 0 && (
          <span>GPM {(Number(gpm) * 100).toFixed(2).replace(/\.00$/, '')}%</span>
        )}
        {lists.map(([word, list]) => <span key={word}>{plural(list.length, word)}</span>)}
      </div>
    </div>
  )
}

function VersionCompare({ version, diff, detail, currentBundles }) {
  const changes = Array.isArray(diff?.changes) ? diff.changes : []
  const summary = diff?.summary || {}
  const grouped = useMemo(() => groupChanges(changes), [changes])
  const names = useMemo(
    () => bundleNames(detail?.proposal_data?.bundles, currentBundles),
    [detail, currentBundles],
  )
  const otherItem = useMemo(() => ({ changes: grouped.other }), [grouped.other])
  const bidItem = useMemo(() => ({ changes: grouped.bidFields }), [grouped.bidFields])
  const proposalSame = grouped.bundles.length === 0 && grouped.other.length === 0

  // Which side is which: the side whose total matches this version is "this
  // version"; when that can't be told, the version is the starting point.
  const versionFirst = !(sameMoney(summary.grand_total_after, version.grand_total) && !sameMoney(summary.grand_total_before, version.grand_total))
  const fromLabel = versionFirst ? `v${version.version_no}` : 'the current proposal'
  const toLabel = versionFirst ? 'the current proposal' : `v${version.version_no}`

  const added = summary.bundles_added ?? grouped.bundles.filter(g => g.whole && g.whole.op === 'add').length
  const removed = summary.bundles_removed ?? grouped.bundles.filter(g => g.whole && g.whole.op === 'remove').length
  const changed = summary.bundles_changed ?? grouped.bundles.filter(g => !g.whole).length
  const hasTotals = summary.grand_total_before != null || summary.grand_total_after != null

  if (changes.length === 0) {
    return (
      <p className="flex items-center gap-2 text-xs text-emerald-300/90">
        <CheckCircle2 className="w-3.5 h-3.5" /> No differences: v{version.version_no} matches the current proposal.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-2.5 space-y-1.5">
        <p className="text-xs text-gray-400">
          Changes from <span className="text-gray-200 font-medium">{fromLabel}</span> to <span className="text-gray-200 font-medium">{toLabel}</span>
        </p>
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          {changed > 0 && <span className="px-2 py-0.5 rounded-md bg-si-bright/10 text-blue-300">{plural(changed, 'bundle')} changed</span>}
          {added > 0 && <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300">{added} added</span>}
          {removed > 0 && <span className="px-2 py-0.5 rounded-md bg-red-500/10 text-red-300">{removed} removed</span>}
          {changed + added + removed === 0 && (
            <span className="px-2 py-0.5 rounded-md bg-white/[0.04] text-gray-400">{proposalSame ? 'The proposal is the same' : 'Bundles are the same'}</span>
          )}
        </div>
        {hasTotals && (
          <p className="text-xs text-gray-400 tabular-nums">
            Grand total {formatMoney(summary.grand_total_before) || '—'} → <span className="text-white font-semibold">{formatMoney(summary.grand_total_after) || '—'}</span>
            <span className="text-gray-500"> ({moneyDelta(summary.grand_total_before, summary.grand_total_after)})</span>
          </p>
        )}
      </div>

      {grouped.bundles.length > 0 && (
        <div className="space-y-2">
          {grouped.bundles.map((group, index) => (
            <BundleGroup key={group.key} group={group} name={groupName(group, names, index)} />
          ))}
        </div>
      )}

      {grouped.other.length > 0 && (
        <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5 space-y-2.5">
          <div className="text-[11px] font-bold uppercase tracking-wider text-gray-500">Rest of the proposal</div>
          {grouped.other.filter(change => !change.derived).map((change, index) => (
            <CompareChange key={`${change.path}-${index}`} change={change} item={otherItem} />
          ))}
          {grouped.other.some(change => change.derived) && (
            <p className="text-[11px] text-gray-500">
              and {plural(grouped.other.filter(change => change.derived).length, 'worked-out total')} recalculated
            </p>
          )}
        </div>
      )}

      {grouped.bidFields.length > 0 && (
        <div className="rounded-lg border border-dashed border-white/[0.08] px-3 py-2.5 space-y-2.5">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-gray-500">Bid details</div>
            <p className="text-[11px] text-gray-500 mt-0.5">
              These are the bid's own fields, not part of the proposal. Restore doesn't change them: they stay as they are on the bid now.
            </p>
          </div>
          {grouped.bidFields.map((change, index) => (
            <CompareChange key={`bid-${change.path}-${index}`} change={change} item={bidItem} label={bidFieldLabel(change.fieldKey)} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── One version in the list ─────────────────────────────────────────────────

function VersionRow({
  jobId, version, reason, openMode, onToggle, detailState, diffState, currentBundles,
  renaming, onStartRename, onRenameChange, onRenameSave, onRenameCancel,
  onRestore, restoring, busy,
}) {
  const contributors = Array.isArray(version.contributors) ? version.contributors.filter(Boolean) : []
  const createdBy = version.created_by_name || version.created_by
  const showContributors = contributors.length > 1
    || (contributors.length === 1 && String(contributors[0]).toLowerCase() !== String(version.created_by || '').toLowerCase())
  const count = Number(version.bundle_count)
  // "Sent" bid events that point at this version: this is what went to the GC.
  const sentList = Array.isArray(version.sent) ? version.sent.filter(Boolean) : []
  const lastSent = sentList[sentList.length - 1]
  const inputRef = useRef(null)

  useEffect(() => {
    if (renaming) inputRef.current?.focus()
  }, [renaming])

  return (
    <li className={`rounded-xl border transition-colors ${openMode ? 'border-white/[0.08] bg-white/[0.03]' : 'border-white/[0.04] hover:bg-white/[0.02]'}`}>
      <div className="px-3 py-2.5">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 flex-shrink-0 text-[11px] font-bold tabular-nums px-1.5 py-0.5 rounded-md bg-white/[0.06] text-gray-300">
            v{version.version_no}
          </span>
          <div className="flex-1 min-w-0">
            {renaming ? (
              <form
                onSubmit={(e) => { e.preventDefault(); onRenameSave() }}
                className="flex items-center gap-1.5"
              >
                <input
                  ref={inputRef}
                  type="text"
                  value={renaming.value}
                  maxLength={LABEL_MAX}
                  onChange={e => onRenameChange(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onRenameCancel() } }}
                  placeholder={reason}
                  disabled={renaming.saving}
                  aria-label="Version name"
                  className="flex-1 min-w-0 bg-white/[0.04] border border-white/10 rounded-md px-2 py-1 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                />
                <button type="submit" disabled={renaming.saving} className="p-1.5 rounded-md text-emerald-400 hover:bg-emerald-500/10" title="Save name">
                  {renaming.saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                </button>
                <button type="button" onClick={onRenameCancel} disabled={renaming.saving} className="p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-white/[0.06]" title="Cancel">
                  <X className="w-3.5 h-3.5" />
                </button>
              </form>
            ) : (
              <div className="flex items-start gap-1.5">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-white break-words">{version.label || reason}</div>
                  {version.label && <div className="text-[11px] text-gray-500">{reason}</div>}
                </div>
                <button
                  type="button"
                  onClick={onStartRename}
                  disabled={busy}
                  className="flex-shrink-0 p-1 -mt-0.5 rounded-md text-gray-600 hover:text-gray-300 hover:bg-white/[0.06]"
                  title={version.label ? 'Rename this version' : 'Name this version'}
                >
                  <Pencil className="w-3 h-3" />
                </button>
              </div>
            )}
            {renaming?.error && <p className="mt-1 text-xs text-red-400">{renaming.error}</p>}

            <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-gray-500">
              {createdBy && <span className="text-gray-400">{createdBy}</span>}
              {createdBy && <span className="text-gray-700">·</span>}
              <span title={version.created_at || ''}>{formatWhen(version.created_at)}</span>
            </div>
            {showContributors && (
              <div className="mt-0.5 text-[11px] text-gray-500 break-words">Worked on by {contributors.join(', ')}</div>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
              {version.grand_total !== null && version.grand_total !== undefined && (
                <span className="text-gray-200 font-semibold tabular-nums">{formatMoney(version.grand_total)}</span>
              )}
              {Number.isFinite(count) && (
                <span className="inline-flex items-center gap-1 text-gray-500"><Layers className="w-3 h-3" />{plural(count, 'bundle')}</span>
              )}
              {version.artifact_id != null && version.artifact_id !== '' && (
                <a
                  href={api.jobArtifactDownloadUrl(jobId, version.artifact_id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-emerald-400 hover:text-emerald-300"
                  title="Open the PDF made from this version"
                >
                  <FileDown className="w-3 h-3" /> PDF
                </a>
              )}
              {sentList.length > 0 && (
                <span
                  className="inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-md bg-cyan-500/10 text-cyan-300 border border-cyan-500/20"
                  title={sentList.map(sent => `Sent${sent.sent_on ? ` ${formatDay(sent.sent_on)}` : ''}${sent.sent_to ? ` to ${sent.sent_to}` : ''}`).join('\n')}
                >
                  <Send className="w-3 h-3" />
                  Sent{lastSent.sent_on ? ` ${formatDay(lastSent.sent_on)}` : ''}{lastSent.sent_to ? ` to ${lastSent.sent_to}` : ''}
                  {sentList.length > 1 ? ` (${sentList.length} times)` : ''}
                </span>
              )}
            </div>
            {lastSent?.proposal_changed_since_pdf && (
              <div className="mt-0.5 text-[11px] text-amber-400/80">The proposal was changed after this PDF was made and before it was sent.</div>
            )}
          </div>
        </div>

        <div className="mt-2 pl-9 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => onToggle('preview')}
            aria-expanded={openMode === 'preview'}
            className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-md transition-colors
              ${openMode === 'preview' ? 'bg-si-bright/20 text-blue-300' : 'bg-white/[0.04] text-gray-400 hover:text-gray-200 hover:bg-white/[0.08]'}`}
          >
            <Eye className="w-3 h-3" /> Preview
          </button>
          <button
            type="button"
            onClick={() => onToggle('compare')}
            aria-expanded={openMode === 'compare'}
            className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-md transition-colors
              ${openMode === 'compare' ? 'bg-si-bright/20 text-blue-300' : 'bg-white/[0.04] text-gray-400 hover:text-gray-200 hover:bg-white/[0.08]'}`}
          >
            <GitCompare className="w-3 h-3" /> Compare with current
          </button>
          <button
            type="button"
            onClick={onRestore}
            disabled={busy}
            className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-md bg-white/[0.04] text-gray-400 hover:text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
          >
            {restoring ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArchiveRestore className="w-3 h-3" />}
            Restore
          </button>
        </div>
      </div>

      {openMode && (
        <div className="px-3 pb-3 pt-1 border-t border-white/[0.05]">
          {openMode === 'preview' ? (
            detailState?.error ? (
              <p className="text-xs text-red-400">{detailState.error}</p>
            ) : !detailState?.data ? (
              <div className="flex justify-center py-4"><Loader2 className="w-4 h-4 text-gray-600 animate-spin" /></div>
            ) : (
              <VersionPreview detail={detailState.data} />
            )
          ) : diffState?.error ? (
            <p className="text-xs text-red-400">{diffState.error}</p>
          ) : !diffState?.data ? (
            <div className="flex justify-center py-4"><Loader2 className="w-4 h-4 text-gray-600 animate-spin" /></div>
          ) : (
            <VersionCompare version={version} diff={diffState.data} detail={detailState?.data} currentBundles={currentBundles} />
          )}
        </div>
      )}
    </li>
  )
}

// What a restore did, from the server's reply (see onRestore above).
function restoreNotice(version, result, list) {
  const name = `v${version.version_no}`
  const extra = []
  let tone = 'success'
  const fields = Array.isArray(result?.job_fields_differ) ? result.job_fields_differ : []
  if (fields.length > 0) {
    extra.push(`The bid's ${bidFieldList(fields)} ${fields.length === 1 ? 'was' : 'were'} left as ${fields.length === 1 ? 'it is' : 'they are'} now: a restore only changes the proposal.`)
  }
  if (result?.materials_changed_since) {
    tone = 'warning'
    extra.push(`The takeoff has changed since ${name} was saved, so its prices come from the old material lines. Regenerate the proposal if you want prices from the takeoff as it is now.`)
  }
  if (result?.unchanged) {
    return { tone: tone === 'warning' ? 'warning' : 'info', text: [`${name} already matches the current proposal, so nothing changed.`, ...extra].join(' ') }
  }
  const text = [`Restored ${name}.`]
  const beforeId = result?.before_restore_version_id
  if (beforeId !== null && beforeId !== undefined) {
    const before = (list || []).find(item => item.id === beforeId)
    text.push(before ? `What you had before is saved as v${before.version_no}.` : 'What you had before is saved as a version too.')
  }
  return { tone, text: [...text, ...extra].join(' ') }
}

const NOTICE_STYLES = {
  success: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300',
  info: 'bg-white/[0.04] border-white/[0.08] text-gray-300',
  warning: 'bg-amber-500/10 border-amber-500/20 text-amber-300',
  error: 'bg-red-500/10 border-red-500/20 text-red-400',
}

// ── The drawer ──────────────────────────────────────────────────────────────

export default function ProposalVersionsDrawer({ jobId, jobName, currentBundles = [], onRestore, onClose }) {
  const [versions, setVersions] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(null) // { id, mode: 'preview' | 'compare' }
  const [details, setDetails] = useState({}) // id -> { data, error }
  const [diffs, setDiffs] = useState({}) // id -> { data, error }
  const [renaming, setRenaming] = useState(null) // { id, value, saving, error }
  const [confirmRestore, setConfirmRestore] = useState(null)
  const [restoringId, setRestoringId] = useState(null)
  const [notice, setNotice] = useState(null) // { tone, text }
  const closeRef = useRef(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const list = await api.listProposalVersions(jobId)
      const items = Array.isArray(list) ? list : Array.isArray(list?.items) ? list.items : []
      setVersions(items)
      return items
    } catch (err) {
      setLoadError(err.message || "Versions couldn't be loaded.")
      return null
    } finally {
      setLoading(false)
    }
  }, [jobId])
  useEffect(() => { load() }, [load])

  const byId = useMemo(() => new Map((versions || []).map(version => [version.id, version])), [versions])

  // Escape closes the innermost thing: the restore question, then a rename, then the drawer.
  const stateRef = useRef({})
  stateRef.current = { confirmRestore, renaming, restoringId, onClose }
  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      const state = stateRef.current
      if (state.restoringId !== null) return
      if (state.confirmRestore) setConfirmRestore(null)
      else if (state.renaming) setRenaming(null)
      else state.onClose?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const loadDetail = useCallback((id) => {
    setDetails(prev => (prev[id]?.data ? prev : { ...prev, [id]: {} }))
    api.getProposalVersion(jobId, id)
      .then(data => setDetails(prev => ({ ...prev, [id]: { data } })))
      .catch(err => setDetails(prev => ({ ...prev, [id]: { error: err.message || "This version couldn't be loaded." } })))
  }, [jobId])

  const loadDiff = useCallback((id) => {
    setDiffs(prev => ({ ...prev, [id]: {} }))
    api.diffProposalVersion(jobId, id, 'current')
      .then(data => setDiffs(prev => ({ ...prev, [id]: { data } })))
      .catch(err => setDiffs(prev => ({ ...prev, [id]: { error: err.message || "The comparison couldn't be made." } })))
  }, [jobId])

  const toggle = (version, mode) => {
    if (open?.id === version.id && open.mode === mode) {
      setOpen(null)
      return
    }
    setOpen({ id: version.id, mode })
    // Preview and compare both use the version itself (compare names bundles from it).
    if (!details[version.id]?.data) loadDetail(version.id)
    // The current proposal keeps changing, so compare fresh each time it's opened.
    if (mode === 'compare') loadDiff(version.id)
  }

  const saveRename = async () => {
    if (!renaming || renaming.saving) return
    const value = renaming.value.trim()
    if (value.length > LABEL_MAX) {
      setRenaming(prev => ({ ...prev, error: `Keep it to ${LABEL_MAX} characters or fewer.` }))
      return
    }
    const current = byId.get(renaming.id)
    if (current && (current.label || '') === value) {
      setRenaming(null)
      return
    }
    setRenaming(prev => ({ ...prev, saving: true, error: '' }))
    try {
      const updated = await api.renameProposalVersion(jobId, renaming.id, value)
      const label = updated && typeof updated === 'object' && 'label' in updated ? updated.label : value
      setVersions(prev => (prev || []).map(version => (version.id === renaming.id ? { ...version, ...(updated && typeof updated === 'object' ? updated : {}), label } : version)))
      setRenaming(null)
    } catch (err) {
      setRenaming(prev => (prev ? { ...prev, saving: false, error: err.message || "The name couldn't be saved." } : prev))
    }
  }

  const restore = async (version) => {
    setConfirmRestore(null)
    setRestoringId(version.id)
    setNotice(null)
    try {
      const result = await onRestore?.(version)
      setOpen(null)
      setDiffs({})
      const list = await load()
      setNotice(restoreNotice(version, result, list))
    } catch (err) {
      setNotice({ tone: 'error', text: `v${version.version_no} couldn't be restored: ${err?.message || 'try again.'}` })
    } finally {
      setRestoringId(null)
    }
  }

  const busy = restoringId !== null

  return createPortal(
    <div className="fixed inset-0 z-[70] flex justify-end" role="dialog" aria-modal="true" aria-labelledby="proposal-versions-title">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" onClick={() => { if (!busy) onClose?.() }} />
      <aside className="relative flex h-full w-full sm:max-w-[560px] flex-col bg-[#0B1122] border-l border-white/[0.08] shadow-2xl animate-slide-in-right">
        <div className="flex items-start gap-3 px-5 pt-5 pb-3 border-b border-white/[0.06]">
          <div className="w-9 h-9 flex-shrink-0 rounded-xl bg-si-bright/10 border border-si-bright/15 flex items-center justify-center">
            <Layers className="w-4 h-4 text-blue-300" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 id="proposal-versions-title" className="text-base font-bold text-white">Proposal versions</h2>
            <p className="text-xs text-gray-500">
              {jobName ? `${jobName}: ` : ''}saved copies of the proposal. Preview, compare or restore any of them.
            </p>
          </div>
          <button
            type="button"
            onClick={() => load()}
            disabled={loading}
            className="p-2 rounded-md text-gray-500 hover:text-gray-300 hover:bg-white/[0.06] disabled:opacity-40"
            title="Check for new versions"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading && versions ? 'animate-spin' : ''}`} />
          </button>
          <button ref={closeRef} type="button" onClick={onClose} disabled={busy} className="btn-ghost p-2 -mr-2" title="Close versions">
            <X className="w-4 h-4" />
          </button>
        </div>

        {notice && (
          <div
            role={notice.tone === 'error' ? 'alert' : 'status'}
            className={`mx-5 mt-3 flex items-start gap-2 px-3 py-2 rounded-lg text-xs border ${NOTICE_STYLES[notice.tone] || NOTICE_STYLES.info}`}
          >
            {notice.tone === 'success' ? <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
              : notice.tone === 'info' ? <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                : <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />}
            <span className="flex-1">{notice.text}</span>
            <button type="button" onClick={() => setNotice(null)} className="opacity-70 hover:opacity-100" title="Dismiss">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-3 py-3">
          {loadError && !versions ? (
            <div className="text-center py-10 px-4">
              <AlertTriangle className="w-5 h-5 text-amber-400 mx-auto mb-2" />
              <p className="text-sm text-gray-300">{loadError}</p>
              <button type="button" onClick={() => load()} className="btn-secondary text-xs mt-3 inline-flex px-3 py-1.5">
                <RefreshCw className="w-3.5 h-3.5" /> Try again
              </button>
            </div>
          ) : versions === null ? (
            <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 text-gray-600 animate-spin" /></div>
          ) : versions.length === 0 ? (
            <div className="text-center py-10 px-6">
              <p className="text-sm text-gray-400">No versions saved yet.</p>
              <p className="text-xs text-gray-600 mt-1">
                A version is saved after a stretch of editing, before a regenerate, when a PDF is made and when the bid is sent.
              </p>
            </div>
          ) : (
            <>
              {loadError && <p className="px-2 pb-2 text-xs text-red-400">{loadError}</p>}
              <ul className="space-y-2">
                {versions.map(version => {
                  return (
                    <VersionRow
                      key={version.id}
                      jobId={jobId}
                      version={version}
                      reason={reasonText(version, byId)}
                      openMode={open?.id === version.id ? open.mode : null}
                      onToggle={(mode) => toggle(version, mode)}
                      detailState={details[version.id]}
                      diffState={diffs[version.id]}
                      currentBundles={currentBundles}
                      renaming={renaming?.id === version.id ? renaming : null}
                      onStartRename={() => setRenaming({ id: version.id, value: version.label || '', saving: false, error: '' })}
                      onRenameChange={(value) => setRenaming(prev => (prev ? { ...prev, value, error: '' } : prev))}
                      onRenameSave={saveRename}
                      onRenameCancel={() => setRenaming(null)}
                      onRestore={() => setConfirmRestore(version)}
                      restoring={restoringId === version.id}
                      busy={busy}
                    />
                  )
                })}
              </ul>
            </>
          )}
        </div>
        <div className="px-5 py-2.5 border-t border-white/[0.06] text-[11px] text-gray-600 flex items-center gap-1.5">
          <ArchiveRestore className="w-3 h-3 flex-shrink-0" />
          Restoring never loses anything: the current proposal is saved as a version first.
        </div>
      </aside>

      {/* Outside the sliding panel, so the dialog isn't placed inside its animation. */}
      <ConfirmDialog
        open={!!confirmRestore}
        title={confirmRestore ? `Restore v${confirmRestore.version_no}?` : ''}
        message="Your current proposal is saved as a version first. Only the proposal changes: the bid's tax, GPM and header fields stay as they are. Everyone editing this bid will see the change."
        confirmLabel="Restore this version"
        confirmVariant="restore"
        onConfirm={() => confirmRestore && restore(confirmRestore)}
        onCancel={() => setConfirmRestore(null)}
      />
    </div>,
    document.body,
  )
}
