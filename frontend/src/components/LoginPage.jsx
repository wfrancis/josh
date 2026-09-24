import { useState } from 'react'
import { HardHat, LogIn, Loader2 } from 'lucide-react'
import { api } from '../api'

// TEMPORARY: everyone shares the "test" account (seeded by the server) for now,
// so the form comes pre-filled and one click gets you in. Remove these defaults
// once each person has their own username and PIN.
const STARTER_LOGIN = { username: 'test', pin: '1234' }

export default function LoginPage({ onLoggedIn, overlay = false, initialUsername = '' }) {
  const [username, setUsername] = useState(initialUsername || STARTER_LOGIN.username)
  const [pin, setPin] = useState(STARTER_LOGIN.pin)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !pin) {
      setError('Enter your username and PIN.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const user = await api.login(username.trim(), pin)
      onLoggedIn(user)
    } catch (err) {
      // Server replies carry a plain-English reason; network failures do not.
      setError(err.status && err.message !== 'Request failed'
        ? err.message
        : 'Could not log in right now. Check your connection and try again.')
      setBusy(false)
    }
  }

  const card = (
    <div className="w-full max-w-sm glass-card p-8 shadow-[0_8px_40px_rgba(0,0,0,0.35)]">
      <div className="flex items-center gap-3 mb-8">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-si-orange to-orange-600
                      flex items-center justify-center shadow-[0_2px_8px_rgba(255,95,0,0.3)]">
          <HardHat className="w-5 h-5 text-white" />
        </div>
        <div className="flex flex-col">
          <span className="text-[15px] font-extrabold tracking-[0.04em] text-white">STANDARD</span>
          <span className="text-[10px] font-semibold tracking-[0.15em] text-gray-500 uppercase">Bid Tool</span>
        </div>
      </div>

      <h1 id="login-title" className="text-xl font-bold text-white">
        {overlay ? 'Log in again' : 'Log in'}
      </h1>
      <p className="mt-1 text-sm text-gray-500">
        {overlay
          ? 'You were logged out. Log in to keep working where you left off.'
          : 'Enter your username and PIN.'}
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
        <div>
          <label htmlFor="login-username" className="label">Username</label>
          <input
            id="login-username"
            type="text"
            className="input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            maxLength={40}
            autoFocus
          />
        </div>
        <div>
          <label htmlFor="login-pin" className="label">PIN</label>
          <input
            id="login-pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            className="input tracking-[0.3em]"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            autoComplete="current-password"
            maxLength={12}
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-red-400">{error}</p>
        )}

        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
          {busy ? 'Logging in…' : 'Log in'}
        </button>
      </form>
    </div>
  )

  if (overlay) {
    return (
      <div
        className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="login-title"
      >
        {card}
      </div>
    )
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-4
                     bg-gradient-to-b from-si-bright/[0.04] via-transparent to-transparent">
      {card}
    </main>
  )
}
