import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, Trash2, X } from 'lucide-react'

// Asks why a bid (or several) is being deleted. Deleting only hides the bid:
// it moves to Deleted bids and an admin can restore it. The reason is required
// and saved with the delete, so everyone can see why it went.
// onConfirm(reason) may return a promise; the dialog stays open (showing the
// error) if it fails.

export const DELETE_REASON_MAX = 500

export default function DeleteBidDialog({ open, bidName = '', count = 1, onConfirm, onCancel }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [touched, setTouched] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setReason('')
    setBusy(false)
    setError('')
    setTouched(false)
    const timer = setTimeout(() => inputRef.current?.focus(), 30)
    return () => clearTimeout(timer)
  }, [open])

  const onCancelRef = useRef(onCancel)
  onCancelRef.current = onCancel
  const busyRef = useRef(busy)
  busyRef.current = busy
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => { if (e.key === 'Escape' && !busyRef.current) onCancelRef.current?.() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  if (!open) return null

  const many = count > 1
  const trimmed = reason.trim()
  const tooLong = trimmed.length > DELETE_REASON_MAX
  const problem = !trimmed ? 'Please say why, so others know.' : tooLong ? `Keep it to ${DELETE_REASON_MAX} characters or fewer.` : ''

  const submit = async (e) => {
    e?.preventDefault()
    setTouched(true)
    if (problem || busy) return
    setBusy(true)
    setError('')
    try {
      await onConfirm?.(trimmed)
    } catch (err) {
      setError(err?.message || "The bid couldn't be deleted. Try again.")
      setBusy(false)
    }
  }

  const title = many ? `Delete ${count} bids?` : 'Delete this bid?'
  const what = many ? 'These bids move' : 'This moves the bid'

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="delete-bid-title">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => { if (!busy) onCancel?.() }} />
      <form onSubmit={submit} noValidate className="relative glass-card p-6 max-w-md w-full mx-4 shadow-2xl bg-[#0d1429]">
        <button type="button" onClick={onCancel} disabled={busy} className="absolute top-4 right-4 text-gray-500 hover:text-gray-300" title="Cancel">
          <X className="w-4 h-4" />
        </button>
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 bg-red-500/10 border border-red-500/20">
            <Trash2 className="w-5 h-5 text-red-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 id="delete-bid-title" className="text-lg font-bold text-white mb-1">{title}</h3>
            {!many && bidName && <p className="text-sm text-gray-300 font-medium break-words">{bidName}</p>}
            <p className="text-sm text-gray-400 mt-1">
              {what} to Deleted bids. An admin can restore {many ? 'them' : 'it'}.
            </p>
          </div>
        </div>

        <label className="block mt-5">
          <span className="text-xs font-medium text-gray-400 mb-1.5 block">{many ? 'Why are they being deleted?' : 'Why is it being deleted?'}</span>
          <textarea
            ref={inputRef}
            value={reason}
            onChange={e => setReason(e.target.value)}
            onBlur={() => setTouched(true)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e) }}
            rows={3}
            maxLength={DELETE_REASON_MAX + 50}
            placeholder="For example: duplicate of another bid, entered by mistake, GC cancelled the project"
            className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none resize-y"
            aria-invalid={touched && !!problem}
            disabled={busy}
          />
        </label>
        <div className="flex items-start justify-between gap-3 mt-1 min-h-[1rem]">
          <p className="text-xs text-red-400">{touched && problem ? problem : ''}</p>
          <p className={`text-[11px] flex-shrink-0 ${tooLong ? 'text-red-400' : 'text-gray-600'}`}>{trimmed.length}/{DELETE_REASON_MAX}</p>
        </div>
        {error && <p role="alert" className="text-xs text-red-400 mt-2">{error}</p>}

        <div className="flex justify-end gap-3 mt-5">
          <button type="button" onClick={onCancel} disabled={busy} className="px-4 py-2 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-white/[0.06] transition-colors">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || (touched && !!problem)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold transition-colors bg-red-500/15 border border-red-500/25 text-red-400 hover:bg-red-500/25 disabled:opacity-50"
          >
            {busy && <Loader2 className="w-4 h-4 animate-spin" />}
            {many ? `Delete ${count} bids` : 'Delete bid'}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  )
}
