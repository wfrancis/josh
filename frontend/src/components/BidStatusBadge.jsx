import { BID_STATUS_STYLES } from '../bidTracker'

export default function BidStatusBadge({ status, className = '' }) {
  const style = BID_STATUS_STYLES[status] || BID_STATUS_STYLES['Not started']
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-semibold border whitespace-nowrap ${style} ${className}`}>
      {status || 'Not started'}
    </span>
  )
}
