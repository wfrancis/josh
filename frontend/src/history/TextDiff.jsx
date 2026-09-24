import { useMemo, useState } from 'react'

// Word-by-word before/after for text changes: removed words struck through in
// red, added words in green, the rest as it was. Uses a small longest-common-
// subsequence diff (no extra package needed).

// Above this many word pairs the middle of the text is shown as replaced
// whole, so a huge paste can't freeze the page.
const MAX_DIFF_CELLS = 1_500_000
// Unchanged stretches longer than this are shortened, with a "Show all" button.
const LONG_SAME = 220
const KEEP_CONTEXT = 80

function tokenize(text) {
  return String(text ?? '').match(/\s+|[^\s]+/g) || []
}

// Longest common subsequence of two token lists -> [{ type: 'same'|'del'|'ins', tokens }].
export function diffTokens(a, b) {
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start++
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB-- }

  const ops = []
  const push = (type, token) => {
    const last = ops[ops.length - 1]
    if (last && last.type === type) last.tokens.push(token)
    else ops.push({ type, tokens: [token] })
  }
  for (let i = 0; i < start; i++) push('same', a[i])

  const midA = a.slice(start, endA)
  const midB = b.slice(start, endB)
  const n = midA.length
  const m = midB.length
  if (n > 0 && m > 0 && n * m <= MAX_DIFF_CELLS) {
    // lengths[i][j] = LCS length of midA[i..] and midB[j..], one flat array.
    const width = m + 1
    const lengths = new Uint32Array((n + 1) * width)
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        lengths[i * width + j] = midA[i] === midB[j]
          ? lengths[(i + 1) * width + j + 1] + 1
          : Math.max(lengths[(i + 1) * width + j], lengths[i * width + j + 1])
      }
    }
    let i = 0
    let j = 0
    while (i < n && j < m) {
      if (midA[i] === midB[j]) { push('same', midA[i]); i++; j++ }
      else if (lengths[(i + 1) * width + j] >= lengths[i * width + j + 1]) { push('del', midA[i]); i++ }
      else { push('ins', midB[j]); j++ }
    }
    while (i < n) push('del', midA[i++])
    while (j < m) push('ins', midB[j++])
  } else {
    midA.forEach(token => push('del', token))
    midB.forEach(token => push('ins', token))
  }
  for (let i = endA; i < a.length; i++) push('same', a[i])
  return ops
}

// Pull whitespace-only "same" runs between two changes into the change, so
// "old words" -> "new words" reads as one replacement instead of confetti.
function tidy(ops) {
  const out = []
  let block = null
  const flush = () => {
    if (!block) return
    if (block.del.length) out.push({ type: 'del', text: block.del.join('') })
    if (block.ins.length) out.push({ type: 'ins', text: block.ins.join('') })
    block = null
  }
  ops.forEach((op, index) => {
    if (op.type === 'same') {
      const next = ops[index + 1]
      const isGap = block && next && next.type !== 'same' && op.tokens.every(token => /^\s+$/.test(token))
      if (isGap) {
        block.del.push(...op.tokens)
        block.ins.push(...op.tokens)
        return
      }
      flush()
      out.push({ type: 'same', text: op.tokens.join('') })
      return
    }
    if (!block) block = { del: [], ins: [] }
    block[op.type].push(...op.tokens)
  })
  flush()
  return out
}

export function diffWords(before, after) {
  return tidy(diffTokens(tokenize(before), tokenize(after)))
}

function SameText({ text, first, last, expanded }) {
  if (expanded || text.length <= LONG_SAME) return <span className="text-gray-400">{text}</span>
  const head = first ? '' : text.slice(0, KEEP_CONTEXT)
  const tail = last ? '' : text.slice(-KEEP_CONTEXT)
  return (
    <span className="text-gray-400">
      {head}
      <span className="text-gray-600 select-none"> … </span>
      {tail}
    </span>
  )
}

export default function TextDiff({ before, after, className = '' }) {
  const [expanded, setExpanded] = useState(false)
  const parts = useMemo(() => diffWords(before, after), [before, after])
  const hasLongStretch = parts.some(part => part.type === 'same' && part.text.length > LONG_SAME)

  if (parts.length === 0) return <span className="text-xs text-gray-600 italic">(blank)</span>

  return (
    <div className={`text-[13px] leading-relaxed whitespace-pre-wrap break-words ${className}`}>
      {parts.map((part, index) => {
        if (part.type === 'same') {
          return <SameText key={index} text={part.text} first={index === 0} last={index === parts.length - 1} expanded={expanded} />
        }
        if (part.type === 'del') {
          return (
            <del key={index} className="rounded-sm bg-red-500/15 text-red-300 decoration-red-400/60 px-0.5">
              {part.text}
            </del>
          )
        }
        return (
          <ins key={index} className="rounded-sm bg-emerald-500/15 text-emerald-300 no-underline px-0.5">
            {part.text}
          </ins>
        )
      })}
      {hasLongStretch && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setExpanded(v => !v) }}
          className="ml-2 text-[11px] font-medium text-si-bright hover:text-blue-300 whitespace-nowrap"
        >
          {expanded ? 'Show less' : 'Show all text'}
        </button>
      )}
    </div>
  )
}
