import { Component, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, History, RefreshCw, X } from 'lucide-react'

// Catches a History drawer that couldn't load (its file is missing after a new
// version went live, or the connection dropped) or crashed while showing.
// Without it the error reaches the page-level boundary, which replaces the
// whole bid page and throws away edits that aren't saved yet. This shows the
// problem inside the drawer instead and leaves the bid page alone.
export default class HistoryDrawerBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: false }
  }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(err) {
    console.error('History drawer failed to load:', err)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return <HistoryLoadFailed title={this.props.title} onRetry={this.props.onRetry} onClose={this.props.onClose} />
  }
}

// title: the drawer's name ("History" unless another drawer uses this boundary).
function HistoryLoadFailed({ title = 'History', onRetry, onClose }) {
  const retryRef = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  useEffect(() => {
    retryRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onCloseRef.current?.() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  return createPortal(
    <div className="fixed inset-0 z-[70] flex justify-end" role="dialog" aria-modal="true" aria-labelledby="history-load-failed-title">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" onClick={onClose} />
      <aside className="relative flex h-full w-full sm:max-w-[540px] flex-col bg-[#0B1122] border-l border-white/[0.08] shadow-2xl">
        <div className="flex items-start gap-3 px-5 pt-5 pb-3 border-b border-white/[0.06]">
          <div className="w-9 h-9 flex-shrink-0 rounded-xl bg-si-bright/10 border border-si-bright/15 flex items-center justify-center">
            <History className="w-4 h-4 text-blue-300" />
          </div>
          <h2 id="history-load-failed-title" className="flex-1 min-w-0 text-base font-bold text-white pt-1.5">{title}</h2>
          <button type="button" onClick={onClose} className="btn-ghost p-2 -mr-2" title="Close">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-5 py-16 text-center">
          <AlertTriangle className="w-6 h-6 text-amber-400 mx-auto mb-3" />
          <p className="text-sm text-gray-300">{title} couldn't be loaded.</p>
          <p className="text-xs text-gray-500 mt-1">
            Your work on this bid is still here. Check your connection, then try again.
          </p>
          <button ref={retryRef} type="button" onClick={onRetry} className="btn-secondary text-sm mt-4 inline-flex">
            <RefreshCw className="w-4 h-4" />
            Try again
          </button>
        </div>
      </aside>
    </div>,
    document.body,
  )
}
