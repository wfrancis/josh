import { AlertTriangle, Copy, Trash2, X } from 'lucide-react'

const VARIANT_STYLES = {
  danger: {
    icon: <Trash2 className="w-5 h-5 text-red-400" />,
    iconBg: 'bg-red-500/10 border border-red-500/20',
    button: 'bg-red-500/15 border border-red-500/25 text-red-400 hover:bg-red-500/25',
  },
  info: {
    icon: <Copy className="w-5 h-5 text-blue-400" />,
    iconBg: 'bg-blue-500/10 border border-blue-500/20',
    button: 'bg-blue-500/15 border border-blue-500/25 text-blue-400 hover:bg-blue-500/25',
  },
  warning: {
    icon: <AlertTriangle className="w-5 h-5 text-amber-400" />,
    iconBg: 'bg-amber-500/10 border border-amber-500/20',
    button: 'bg-amber-500/15 border border-amber-500/25 text-amber-400 hover:bg-amber-500/25',
  },
}

export default function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', confirmVariant = 'danger', onConfirm, onCancel }) {
  if (!open) return null

  const variant = VARIANT_STYLES[confirmVariant] || VARIANT_STYLES.warning

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative glass-card p-6 max-w-md w-full mx-4 animate-fade-in shadow-2xl">
        <button onClick={onCancel} className="absolute top-4 right-4 text-gray-500 hover:text-gray-300">
          <X className="w-4 h-4" />
        </button>
        <div className="flex items-start gap-4">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${variant.iconBg}`}>
            {variant.icon}
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-bold text-white mb-1">{title}</h3>
            <p className="text-sm text-gray-400">{message}</p>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <button onClick={onCancel} className="px-4 py-2 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-white/[0.06] transition-colors">
            Cancel
          </button>
          <button onClick={onConfirm} className={`px-4 py-2 rounded-xl text-sm font-bold transition-colors ${variant.button}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
