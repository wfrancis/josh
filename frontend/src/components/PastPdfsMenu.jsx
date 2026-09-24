import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, ChevronDown, FileClock, FileDown, Loader2 } from 'lucide-react'
import { api } from '../api'
import { formatMoney, formatWhen } from '../bidTracker'

// "Past PDFs": every PDF made for this bid is kept. Lists them newest first
// (when, who, total) with a link to open each one. refreshKey: bump it after a
// new PDF is made so an open list picks it up.

function fileSize(bytes) {
  const size = Number(bytes)
  if (!Number.isFinite(size) || size <= 0) return ''
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export default function PastPdfsMenu({ jobId, kind = 'proposal_pdf', refreshKey = 0 }) {
  const [open, setOpen] = useState(false)
  // The list lines up with the button's right edge, unless that would push it
  // off the left of a narrow screen.
  const [alignLeft, setAlignLeft] = useState(false)
  const buttonRef = useRef(null)
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const rootRef = useRef(null)

  const load = useCallback(async () => {
    if (!jobId) return
    setLoading(true)
    setError('')
    try {
      const list = await api.listJobArtifacts(jobId, kind)
      setItems(Array.isArray(list) ? list : Array.isArray(list?.items) ? list.items : [])
    } catch (err) {
      setError(err.message || "Past PDFs couldn't be loaded.")
    } finally {
      setLoading(false)
    }
  }, [jobId, kind])

  // Load when opened, and again when a new PDF was made while open.
  useEffect(() => { if (open) load() }, [open, load, refreshKey])

  useEffect(() => {
    if (!open) return undefined
    const onClick = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        ref={buttonRef}
        onClick={() => {
          if (!open && buttonRef.current) {
            const menuWidth = Math.min(352, window.innerWidth - 32)
            setAlignLeft(buttonRef.current.getBoundingClientRect().right < menuWidth + 16)
          }
          setOpen(value => !value)
        }}
        aria-expanded={open}
        aria-haspopup="true"
        className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] text-gray-300 font-medium rounded-xl px-4 py-2.5 text-sm transition-colors"
        title="Every PDF made for this bid is kept"
      >
        <FileClock className="w-4 h-4" />
        Past PDFs
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div
          className={`absolute ${alignLeft ? 'left-0' : 'right-0'} bottom-full mb-2 w-[min(22rem,calc(100vw-2rem))] bg-[#0d1429] border border-white/[0.08] rounded-xl shadow-2xl z-40 overflow-hidden`}
          role="menu"
        >
          <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center gap-2">
            <span className="text-xs font-bold text-gray-400 uppercase tracking-wider flex-1">Past PDFs</span>
            {loading && items && <Loader2 className="w-3.5 h-3.5 text-gray-500 animate-spin" />}
          </div>
          {error ? (
            <div className="px-4 py-5 text-center">
              <p className="text-xs text-red-400">{error}</p>
              <button type="button" onClick={load} className="mt-2 text-xs font-medium text-si-bright hover:text-blue-300">Try again</button>
            </div>
          ) : items === null ? (
            <div className="flex justify-center py-6"><Loader2 className="w-4 h-4 text-gray-600 animate-spin" /></div>
          ) : items.length === 0 ? (
            <p className="px-4 py-5 text-center text-xs text-gray-500">No PDFs made yet. Use Generate PDF to make one.</p>
          ) : (
            <ul className="max-h-72 overflow-y-auto py-1">
              {items.map((item, index) => {
                const size = fileSize(item.size)
                const who = item.created_by_name || item.created_by
                const latest = typeof item.is_latest === 'boolean' ? item.is_latest : index === 0
                if (item.file_missing) {
                  // Kept in the list so the print history stays complete, but there's nothing to open.
                  return (
                    <li key={item.id} className="flex items-start gap-3 px-4 py-2.5 opacity-70" title="This PDF's file is missing from storage">
                      <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm text-gray-300">{formatWhen(item.created_at) || 'Unknown date'}</span>
                        <span className="block text-[11px] text-amber-400/80">File missing from storage, so it can't be opened.{latest ? ' Make the PDF again.' : ''}</span>
                      </span>
                      {item.grand_total !== null && item.grand_total !== undefined && (
                        <span className="text-sm text-gray-400 tabular-nums whitespace-nowrap">{formatMoney(item.grand_total)}</span>
                      )}
                    </li>
                  )
                }
                return (
                  <li key={item.id}>
                    <a
                      href={item.download_url || api.jobArtifactDownloadUrl(jobId, item.id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      role="menuitem"
                      className="flex items-start gap-3 px-4 py-2.5 hover:bg-white/[0.05] transition-colors"
                    >
                      <FileDown className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                      <span className="flex-1 min-w-0">
                        <span className="flex items-center gap-2">
                          <span className="text-sm text-gray-200">{formatWhen(item.created_at) || 'Unknown date'}</span>
                          {latest && (
                            <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300">Latest</span>
                          )}
                        </span>
                        <span className="block text-[11px] text-gray-500 truncate">
                          {[who, size].filter(Boolean).join(' · ') || ' '}
                        </span>
                      </span>
                      {item.grand_total !== null && item.grand_total !== undefined && (
                        <span className="text-sm text-gray-300 tabular-nums whitespace-nowrap">{formatMoney(item.grand_total)}</span>
                      )}
                    </a>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
