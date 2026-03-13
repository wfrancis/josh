import { Circle, Upload, DollarSign, FileCheck } from 'lucide-react'

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
    label: 'Bid Ready',
    className: 'badge-complete',
    icon: FileCheck,
  },
}

export function getJobStatus(job) {
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
