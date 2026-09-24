import { useCallback, useEffect, useState } from 'react'
import {
  Users, UserPlus, KeyRound, ShieldCheck, ShieldOff, UserMinus, RotateCcw, Pencil,
  Loader2, AlertTriangle, CheckCircle2, Lock, History, X,
} from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { formatWhen } from '../bidTracker'
import ConfirmDialog from './ConfirmDialog'

// Same rules as the server (models.clean_username / clean_pin), checked here
// first so mistakes show up before anything is sent.
const USERNAME_RULE = 'Username must be 2-40 letters, numbers, dots, dashes or underscores (no spaces).'
const PIN_RULE = 'PIN must be 4-12 digits, numbers only.'
const MAX_NAME_LENGTH = 80

function usernameProblem(username) {
  const value = username.trim()
  if (!/^[A-Za-z0-9._-]{2,40}$/.test(value) || !/[A-Za-z0-9]/.test(value)) return USERNAME_RULE
  return ''
}

function pinProblem(pin) {
  return /^[0-9]{4,12}$/.test(pin.trim()) ? '' : PIN_RULE
}

function nameProblem(name) {
  return name.trim().length > MAX_NAME_LENGTH ? `Name must be ${MAX_NAME_LENGTH} characters or fewer.` : ''
}

const sameUser = (a, b) => (a || '').toLowerCase() === (b || '').toLowerCase()
const personName = (person) => person.display_name || person.username

function Notice({ notice, onClose }) {
  if (!notice) return null
  const success = notice.tone === 'success'
  const Icon = success ? CheckCircle2 : AlertTriangle
  return (
    <div
      role={success ? 'status' : 'alert'}
      className={`flex items-start gap-2 px-4 py-3 mb-6 rounded-xl text-sm border
        ${success ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-red-500/10 border-red-500/20 text-red-400'}`}
    >
      <Icon className="w-4 h-4 flex-shrink-0 mt-0.5" />
      <span className="flex-1">{notice.text}</span>
      <button type="button" onClick={onClose} title="Dismiss" className="flex-shrink-0 opacity-70 hover:opacity-100">
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

function AddPersonForm({ onAdded }) {
  const [form, setForm] = useState({ display_name: '', username: '', pin: '', is_admin: false })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (field) => (e) => setForm(prev => ({ ...prev, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    const problem = nameProblem(form.display_name) || usernameProblem(form.username) || pinProblem(form.pin)
    if (problem) { setError(problem); return }
    setBusy(true)
    setError('')
    try {
      const person = await api.addPerson({
        display_name: form.display_name.trim(),
        username: form.username.trim(),
        pin: form.pin.trim(),
        is_admin: form.is_admin,
      })
      setForm({ display_name: '', username: '', pin: '', is_admin: false })
      onAdded(person)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="glass-card p-5 sm:p-6 mb-8" noValidate>
      <div className="flex items-center gap-2 mb-4">
        <UserPlus className="w-4 h-4 text-gray-400" />
        <h2 className="text-base font-bold text-white">Add person</h2>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label htmlFor="add-name" className="label">Name</label>
          <input
            id="add-name"
            type="text"
            className="input"
            value={form.display_name}
            onChange={set('display_name')}
            placeholder="e.g. Jane Smith"
            maxLength={MAX_NAME_LENGTH}
            autoComplete="off"
          />
        </div>
        <div>
          <label htmlFor="add-username" className="label">Username</label>
          <input
            id="add-username"
            type="text"
            className="input"
            value={form.username}
            onChange={set('username')}
            placeholder="e.g. jsmith"
            maxLength={40}
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
          />
          <p className="mt-1.5 text-xs text-gray-500">What they type to log in. No spaces.</p>
        </div>
        <div>
          <label htmlFor="add-pin" className="label">PIN</label>
          <input
            id="add-pin"
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            className="input tracking-[0.3em]"
            value={form.pin}
            onChange={set('pin')}
            placeholder="4-12 digits"
            maxLength={12}
            autoComplete="off"
          />
          <p className="mt-1.5 text-xs text-gray-500">Tell them this PIN. You can reset it later.</p>
        </div>
      </div>
      <div className="mt-4 flex flex-col sm:flex-row sm:items-center gap-4">
        <label className="inline-flex items-start gap-2.5 text-sm text-gray-300 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={form.is_admin}
            onChange={set('is_admin')}
            className="mt-0.5 w-4 h-4 rounded accent-si-orange"
          />
          <span>
            Admin
            <span className="block text-xs text-gray-500">Can add and remove people and reset PINs.</span>
          </span>
        </label>
        <button type="submit" className="btn-primary sm:ml-auto" disabled={busy}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
          {busy ? 'Adding…' : 'Add person'}
        </button>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-red-400">{error}</p>}
    </form>
  )
}

// A small pop-up with one text box: new PIN, or a new name.
function FieldDialog({ title, message, label, initialValue = '', inputProps = {}, validate, confirmLabel, onSubmit, onCancel }) {
  const [value, setValue] = useState(initialValue)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onCancel() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onCancel])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const problem = validate ? validate(value) : ''
    if (problem) { setError(problem); return }
    setBusy(true)
    setError('')
    try {
      await onSubmit(value.trim())
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="field-dialog-title">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={busy ? undefined : onCancel} />
      <form onSubmit={handleSubmit} noValidate className="relative glass-card p-6 max-w-md w-full mx-4 animate-fade-in shadow-2xl">
        <button type="button" onClick={onCancel} disabled={busy} className="absolute top-4 right-4 text-gray-500 hover:text-gray-300">
          <X className="w-4 h-4" />
        </button>
        <h3 id="field-dialog-title" className="text-lg font-bold text-white mb-1 pr-6">{title}</h3>
        {message && <p className="text-sm text-gray-400">{message}</p>}
        <div className="mt-5">
          <label htmlFor="field-dialog-input" className="label">{label}</label>
          <input
            id="field-dialog-input"
            type="text"
            className="input"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoComplete="off"
            autoFocus
            {...inputProps}
          />
        </div>
        {error && <p role="alert" className="mt-3 text-sm text-red-400">{error}</p>}
        <div className="flex justify-end gap-3 mt-6">
          <button type="button" onClick={onCancel} disabled={busy}
            className="px-4 py-2 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-white/[0.06] transition-colors">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="btn-primary px-4 py-2 text-sm">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />}
            {confirmLabel}
          </button>
        </div>
      </form>
    </div>
  )
}

function RoleBadge({ isAdmin }) {
  return isAdmin
    ? <span className="badge-progress"><ShieldCheck className="w-3.5 h-3.5" />Admin</span>
    : <span className="badge-draft">User</span>
}

function ActiveBadge({ active }) {
  return active
    ? <span className="badge-complete">Active</span>
    : <span className="badge-blocked">Removed</span>
}

function OnlineDot({ online }) {
  return (
    <span
      title={online ? 'Online now' : 'Not online'}
      className={`inline-block w-2 h-2 rounded-full flex-shrink-0
        ${online ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.6)]' : 'bg-gray-700'}`}
    >
      <span className="sr-only">{online ? 'Online now' : 'Not online'}</span>
    </span>
  )
}

function RowButton({ icon: Icon, label, onClick, disabled, title, tone = 'default' }) {
  const toneClass = tone === 'danger'
    ? 'text-red-400/90 hover:text-red-300 hover:bg-red-500/10'
    : 'text-gray-400 hover:text-gray-200 hover:bg-white/[0.06]'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors
        disabled:opacity-35 disabled:cursor-not-allowed disabled:hover:bg-transparent ${toneClass}`}
    >
      <Icon className="w-3.5 h-3.5" />
      {label}
    </button>
  )
}

function Dash() {
  return <span className="text-gray-600">—</span>
}

function PeopleTable({ people, currentUsername, activeAdminCount, busyUsername, onAsk, removed = false }) {
  return (
    <div className="glass-card overflow-x-auto">
      <table className="w-full min-w-[860px] text-sm">
        <thead>
          <tr className="text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider">
            <th className="px-4 py-3">Name</th>
            <th className="px-3 py-3">Username</th>
            <th className="px-3 py-3">Role</th>
            <th className="px-3 py-3">Status</th>
            <th className="px-3 py-3">Last login</th>
            <th className="px-4 py-3 text-right"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {people.map(person => {
            const isYou = sameUser(person.username, currentUsername)
            const onlyAdmin = person.is_admin && person.active && activeAdminCount <= 1
            const busy = busyUsername === person.username
            const locked = !!busyUsername
            return (
              <tr key={person.username} className="border-t border-white/[0.05] align-middle">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2.5">
                    {!removed && <OnlineDot online={person.online} />}
                    <span className={`font-semibold ${removed ? 'text-gray-400' : 'text-white'}`}>{personName(person)}</span>
                    {isYou && <span className="text-xs text-gray-500">(you)</span>}
                    {!removed && (
                      <button
                        type="button"
                        onClick={() => onAsk('rename', person)}
                        disabled={locked}
                        title="Change name"
                        className="p-1 rounded-md text-gray-600 hover:text-gray-300 hover:bg-white/[0.06] disabled:opacity-35"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                </td>
                <td className="px-3 py-3 font-mono text-[13px] text-gray-300">{person.username}</td>
                <td className="px-3 py-3"><RoleBadge isAdmin={person.is_admin} /></td>
                <td className="px-3 py-3"><ActiveBadge active={person.active} /></td>
                <td className="px-3 py-3 whitespace-nowrap text-gray-300" title={person.created_at ? `Added ${formatWhen(person.created_at)}` : undefined}>
                  {person.last_login_at ? formatWhen(person.last_login_at) : <span className="text-gray-500">Never</span>}
                </td>
                <td className="px-4 py-2 text-right">
                  <div className="inline-flex items-center justify-end gap-1">
                    {busy && <Loader2 className="w-4 h-4 text-gray-500 animate-spin mr-1" />}
                    {removed ? (
                      <RowButton icon={RotateCcw} label="Restore" onClick={() => onAsk('restore', person)} disabled={locked} />
                    ) : (
                      <>
                        <RowButton icon={KeyRound} label="Reset PIN" onClick={() => onAsk('reset', person)} disabled={locked} />
                        {person.is_admin ? (
                          <RowButton
                            icon={ShieldOff}
                            label="Remove admin"
                            onClick={() => onAsk('remove_admin', person)}
                            disabled={locked || onlyAdmin}
                            title={onlyAdmin ? 'This is the only admin. Make someone else an admin first.' : undefined}
                          />
                        ) : (
                          <RowButton icon={ShieldCheck} label="Make admin" onClick={() => onAsk('make_admin', person)} disabled={locked} />
                        )}
                        <RowButton
                          icon={UserMinus}
                          label="Remove"
                          tone="danger"
                          onClick={() => onAsk('remove', person)}
                          disabled={locked || isYou || onlyAdmin}
                          title={isYou ? "You can't remove yourself." : onlyAdmin ? 'This is the only admin. Make someone else an admin first.' : undefined}
                        />
                      </>
                    )}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function describeChange(entry) {
  const actor = entry.actor_name || entry.username
  const target = entry.target_name || entry.target_username
  const d = entry.details || {}
  switch (entry.action) {
    case 'added': return `${actor} added ${target}${d.is_admin ? ' as an admin' : ''}`
    case 'removed': return `${actor} removed ${target}`
    case 'restored': return `${actor} restored ${target}`
    case 'reset_pin': return `${actor} reset ${target}'s PIN`
    case 'renamed': return `${actor} renamed ${d.from || entry.target_username} to ${d.to || target}`
    case 'made_admin': return `${actor} made ${target} an admin`
    case 'removed_admin': return `${actor} removed admin from ${target}`
    case 'startup_admin':
      return (d.changes || []).includes('created')
        ? `${target} was set up as an admin from the server settings`
        : `There were no admins, so ${target} was made an admin again from the server settings`
    default: return `${actor || 'Someone'} changed ${target}`
  }
}

function RecentChanges({ entries }) {
  if (!entries || entries.length === 0) return null
  return (
    <section className="mt-10">
      <div className="flex items-center gap-2 mb-3">
        <History className="w-4 h-4 text-gray-400" />
        <h2 className="text-base font-bold text-white">Recent changes</h2>
      </div>
      <ul className="glass-card divide-y divide-white/[0.05]">
        {entries.slice(0, 15).map(entry => (
          <li key={entry.id} className="flex flex-col sm:flex-row sm:items-center gap-0.5 sm:gap-4 px-4 py-2.5 text-sm">
            <span className="text-gray-300 flex-1 min-w-0">{describeChange(entry)}</span>
            <span className="text-xs text-gray-500 whitespace-nowrap">{formatWhen(entry.created_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function UsersPage() {
  const { user, refreshUser } = useAuth()
  const isAdmin = !!user?.is_admin
  const [people, setPeople] = useState(null)
  const [log, setLog] = useState([])
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState(null)
  const [asking, setAsking] = useState(null)   // { kind, person } for the open pop-up
  const [busyUsername, setBusyUsername] = useState(null)

  const load = useCallback(async () => {
    try {
      const [list, changes] = await Promise.all([api.listPeople(), api.getPeopleLog().catch(() => [])])
      setPeople(list)
      setLog(changes)
      setLoadError('')
    } catch (err) {
      setLoadError(err.message)
      refreshUser() // e.g. someone took admin away in the meantime
    }
  }, [refreshUser])

  useEffect(() => {
    if (isAdmin) load()
  }, [isAdmin, load])

  const closeAsk = useCallback(() => setAsking(null), [])

  const run = async (person, action, successText, { refreshMe = false } = {}) => {
    setAsking(null)
    setBusyUsername(person.username)
    setNotice(null)
    let reload = true
    try {
      await action()
      setNotice({ tone: 'success', text: successText })
      if (refreshMe) {
        // You just gave up your own admin access: this page turns into "Admins only".
        reload = false
        await refreshUser()
      }
    } catch (err) {
      setNotice({ tone: 'error', text: err.message })
    } finally {
      setBusyUsername(null)
      if (reload) load()
    }
  }

  if (!isAdmin) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-8 py-16">
        <div className="glass-card p-8 text-center">
          <Lock className="w-10 h-10 text-gray-600 mx-auto mb-4" />
          <h1 className="text-xl font-bold text-white">Admins only</h1>
          <p className="text-sm text-gray-500 mt-2">
            Only admins can add or remove people. Ask an admin if you need a login added or a PIN reset.
          </p>
        </div>
      </div>
    )
  }

  const currentUsername = user.username
  const activePeople = (people || []).filter(p => p.active)
  const removedPeople = (people || []).filter(p => !p.active)
  const activeAdminCount = activePeople.filter(p => p.is_admin).length
  const onlineCount = activePeople.filter(p => p.online).length

  const confirmProps = (() => {
    if (!asking) return null
    const { kind, person } = asking
    const name = personName(person)
    const isYou = sameUser(person.username, currentUsername)
    if (kind === 'remove') {
      return {
        title: `Remove ${name}?`,
        message: `${name} will be logged out right away and won't be able to log in. Their name stays on past work, and you can restore them later.`,
        confirmLabel: 'Remove',
        confirmVariant: 'danger',
        onConfirm: () => run(person, () => api.removePerson(person.username),
          `Removed ${name}. They've been logged out and can't log in.`),
      }
    }
    if (kind === 'make_admin') {
      return {
        title: `Make ${name} an admin?`,
        message: `${name} will be able to add and remove people, reset PINs and change who is an admin.`,
        confirmLabel: 'Make admin',
        confirmVariant: 'warning',
        onConfirm: () => run(person, () => api.updatePerson(person.username, { is_admin: true }),
          `${name} is now an admin.`),
      }
    }
    if (kind === 'remove_admin') {
      return {
        title: isYou ? 'Remove your own admin access?' : `Remove admin from ${name}?`,
        message: isYou
          ? "You'll still be able to log in and use the tool, but you won't be able to open this page or manage people."
          : `${name} will still be able to log in and use the tool, but won't be able to manage people.`,
        confirmLabel: 'Remove admin',
        confirmVariant: 'warning',
        onConfirm: () => run(person, () => api.updatePerson(person.username, { is_admin: false }),
          isYou ? 'You are no longer an admin.' : `${name} is no longer an admin.`,
          { refreshMe: isYou }),
      }
    }
    return null
  })()

  const fieldDialog = (() => {
    if (!asking) return null
    const { kind, person } = asking
    const name = personName(person)
    const isYou = sameUser(person.username, currentUsername)
    if (kind === 'reset') {
      return (
        <FieldDialog
          title={isYou ? 'Reset your PIN' : `Reset ${name}'s PIN`}
          message={isYou
            ? 'Your other devices will be logged out. This one stays logged in.'
            : `${name} will be logged out everywhere and will need the new PIN to log back in. Tell them the new PIN.`}
          label="New PIN"
          inputProps={{ inputMode: 'numeric', pattern: '[0-9]*', maxLength: 12, placeholder: '4-12 digits', className: 'input tracking-[0.3em]' }}
          validate={pinProblem}
          confirmLabel="Save new PIN"
          onCancel={closeAsk}
          onSubmit={async (pin) => {
            setBusyUsername(person.username)
            try {
              await api.resetPersonPin(person.username, pin)
            } finally {
              setBusyUsername(null)
            }
            setAsking(null)
            setNotice({
              tone: 'success',
              text: isYou
                ? 'Your PIN was changed. Your other devices were logged out.'
                : `New PIN saved for ${name}. They've been logged out and need the new PIN to log back in.`,
            })
            load()
          }}
        />
      )
    }
    if (kind === 'rename') {
      return (
        <FieldDialog
          title={isYou ? 'Change your name' : `Change ${name}'s name`}
          message="This is the name shown in the sidebar and on job activity. Their username stays the same."
          label="Name"
          initialValue={person.display_name || ''}
          inputProps={{ maxLength: MAX_NAME_LENGTH, placeholder: person.username }}
          validate={nameProblem}
          confirmLabel="Save name"
          onCancel={closeAsk}
          onSubmit={async (newName) => {
            await api.updatePerson(person.username, { display_name: newName })
            setAsking(null)
            setNotice({ tone: 'success', text: `Saved. ${person.username} now shows as ${newName || person.username}.` })
            if (isYou) refreshUser()
            load()
          }}
        />
      )
    }
    return null
  })()

  const handleAsk = (kind, person) => {
    if (kind === 'restore') {
      const name = personName(person)
      run(person, () => api.restorePerson(person.username), `Restored ${name}. They can log in again with their old PIN.`)
      return
    }
    setAsking({ kind, person })
  }

  return (
    <>
      <div className="max-w-6xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="mb-6 sm:mb-8 flex flex-col sm:flex-row sm:items-end gap-2">
          <div>
            <h1 className="text-2xl font-extrabold text-white tracking-tight">Users</h1>
            <p className="text-sm text-gray-500 mt-1">Add people who can log in, reset PINs, and remove access.</p>
          </div>
          {people && (
            <div className="sm:ml-auto flex items-center gap-2 text-xs text-gray-500">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              {onlineCount} online now · {activePeople.length} active
            </div>
          )}
        </div>

        <Notice notice={notice} onClose={() => setNotice(null)} />

        <AddPersonForm
          onAdded={(person) => {
            setNotice({
              tone: 'success',
              text: `Added ${personName(person)}${person.is_admin ? ' as an admin' : ''}. They can log in with username ${person.username} and the PIN you set.`,
            })
            load()
          }}
        />

        {loadError && (
          <div className="flex items-center gap-2 px-4 py-3 mb-6 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {loadError}
          </div>
        )}

        {people === null && !loadError ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
          </div>
        ) : people && (
          <>
            <section>
              <div className="flex items-center gap-2 mb-3">
                <Users className="w-4 h-4 text-gray-400" />
                <h2 className="text-base font-bold text-white">People</h2>
                <span className="text-sm text-gray-500 tabular-nums">{activePeople.length}</span>
              </div>
              {activePeople.length === 0 ? (
                <div className="glass-card p-8 text-center text-sm text-gray-500">No one can log in yet.</div>
              ) : (
                <PeopleTable
                  people={activePeople}
                  currentUsername={currentUsername}
                  activeAdminCount={activeAdminCount}
                  busyUsername={busyUsername}
                  onAsk={handleAsk}
                />
              )}
            </section>

            {removedPeople.length > 0 && (
              <section className="mt-10">
                <div className="flex items-center gap-2 mb-1">
                  <UserMinus className="w-4 h-4 text-gray-400" />
                  <h2 className="text-base font-bold text-white">Removed</h2>
                  <span className="text-sm text-gray-500 tabular-nums">{removedPeople.length}</span>
                </div>
                <p className="text-xs text-gray-500 mb-3">These people can't log in. Restore someone to let them back in with their old PIN.</p>
                <PeopleTable
                  people={removedPeople}
                  currentUsername={currentUsername}
                  activeAdminCount={activeAdminCount}
                  busyUsername={busyUsername}
                  onAsk={handleAsk}
                  removed
                />
              </section>
            )}

            <RecentChanges entries={log} />
          </>
        )}
      </div>

      {/* Pop-ups sit outside the page content so nothing animated can trap them. */}
      <ConfirmDialog open={!!confirmProps} onCancel={closeAsk} {...(confirmProps || {})} />
      {fieldDialog}
    </>
  )
}
