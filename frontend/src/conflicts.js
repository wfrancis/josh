// Lines a slow step (quote matching, vendor lookup, AI estimate) skipped
// because someone else changed them while it ran. The server sends them as
// `conflicts`: [{ item_code, message, ... }]. Their change was kept.

const SHOWN = 3

// One plain-English note for the person who ran the step, or '' when nothing was skipped.
export function conflictNotice(conflicts) {
  const list = Array.isArray(conflicts) ? conflicts.filter(item => item && typeof item === 'object') : []
  if (list.length === 0) return ''
  const lines = list.slice(0, SHOWN).map(item => (
    typeof item.message === 'string' && item.message.trim()
      ? item.message.trim()
      : `${item.item_code || 'A line'} was changed by someone else while this was running, so their change was kept.`
  ))
  const more = list.length - SHOWN
  if (more > 0) lines.push(`${more} more line${more === 1 ? ' was' : 's were'} skipped the same way.`)
  return lines.join(' ')
}
