import { Circle, Upload, DollarSign, FileCheck, ShieldAlert, ShieldCheck, AlertTriangle } from 'lucide-react'

const STATUS_CONFIG = {
  draft: {
    label: 'Draft',
    className: 'badge-draft',
    icon: Circle,
  },
  materials: {
    label: 'Materials',
    className: 'badge-progress',
    icon: Upload,
  },
  priced: {
    label: 'Priced',
    className: 'badge-priced',
    icon: DollarSign,
  },
  complete: {
    label: 'Ready to Send',
    className: 'badge-complete',
    icon: FileCheck,
  },
  blocked: {
    label: 'Needs Review',
    className: 'badge-priced',
    icon: ShieldAlert,
  },
  warning: {
    label: 'Needs Review',
    className: 'badge-priced',
    icon: ShieldAlert,
  },
  ready: {
    label: 'Ready to Send',
    className: 'badge-complete',
    icon: FileCheck,
  },
  golden: {
    label: 'Golden Verified',
    className: 'badge-complete',
    icon: ShieldCheck,
  },
  drift: {
    label: 'Drift Detected',
    className: 'badge-priced',
    icon: AlertTriangle,
  },
  incomparable: {
    label: 'Engine Changed',
    className: 'badge-priced',
    icon: AlertTriangle,
  },
}

export function getJobStatus(job) {
  if (job.readiness) {
    if (job.readiness.blocking_count > 0 || job.readiness.status === 'blocked') return 'blocked'
    if (job.readiness.status === 'warning') return 'warning'
    if (['fail', 'drift', 'incomparable'].includes(job.readiness.golden_status)) return 'drift'
    if (job.readiness.golden_status === 'golden_verified') return 'golden'
    return 'ready'
  }
  if (job.bundles?.length > 0) return 'complete'
  const hasPriced = job.materials?.some(m => m.unit_price > 0)
  if (hasPriced) return 'priced'
  if (job.materials?.length > 0) return 'materials'
  return 'draft'
}

export default function StatusBadge({ status }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.draft
  const Icon = config.icon
  return (
    <span className={config.className}>
      <Icon className="w-3 h-3 mr-1" />
      {config.label}
    </span>
  )
}
