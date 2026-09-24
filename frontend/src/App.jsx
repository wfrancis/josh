import { Component, Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react'
import { api, setAuthRequiredHandler } from './api'
import { AuthContext } from './auth'
import Layout from './components/Layout'
import LoginPage from './components/LoginPage'
import Dashboard from './components/Dashboard'
import AllJobs from './components/AllJobs'

const PAGE_RELOAD_KEY = 'si-page-files-reload'

// Heavier pages load on first visit, so the first screen opens faster.
// After a new version goes live, an open tab can ask for page files that no
// longer exist; reload once to pick up the new version instead of failing.
function lazyPage(load) {
  return lazy(() => load().then(
    (module) => {
      try { sessionStorage.removeItem(PAGE_RELOAD_KEY) } catch { /* storage blocked */ }
      return module
    },
    (err) => {
      // Only one automatic reload per 30 s, so a real outage can't cause a reload loop.
      let alreadyReloaded = true
      try {
        const last = Number(sessionStorage.getItem(PAGE_RELOAD_KEY)) || 0
        alreadyReloaded = Date.now() - last < 30000
        if (!alreadyReloaded) sessionStorage.setItem(PAGE_RELOAD_KEY, String(Date.now()))
      } catch { /* storage blocked: don't risk a reload loop */ }
      if (!alreadyReloaded) {
        window.location.reload()
        return new Promise(() => {})
      }
      throw err
    },
  ))
}

const BidTracker = lazyPage(() => import('./components/BidTracker'))
const JobDetail = lazyPage(() => import('./components/JobDetail'))
const SettingsPage = lazyPage(() => import('./components/SettingsPage'))
const PricingRulesPage = lazyPage(() => import('./components/PricingRulesPage'))
const VendorContactsPage = lazyPage(() => import('./components/VendorContactsPage'))
const RulesRegistryPage = lazyPage(() => import('./components/RulesRegistryPage'))
const UsersPage = lazyPage(() => import('./components/UsersPage'))
const AuditPage = lazyPage(() => import('./components/AuditPage'))
const DeletedBidsPage = lazyPage(() => import('./components/DeletedBidsPage'))

function PageLoading() {
  return (
    <div className="flex items-center justify-center py-40">
      <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
    </div>
  )
}

// Shows a reload prompt when a page's files can't be loaded (e.g. the connection
// dropped), instead of a blank screen. Clears when the person goes to another page.
class PageLoadBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: false }
  }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(err) {
    console.error('Page failed to load:', err)
  }

  componentDidUpdate(prevProps) {
    if (this.state.failed && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ failed: false })
    }
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="max-w-md mx-auto px-4 py-24 text-center">
        <AlertTriangle className="w-6 h-6 text-amber-400 mx-auto mb-3" />
        <p className="text-sm text-gray-300">This page couldn't be loaded.</p>
        <p className="text-xs text-gray-500 mt-1">Check your connection, then reload.</p>
        <button onClick={() => window.location.reload()} className="btn-secondary text-sm mt-4 inline-flex">
          <RefreshCw className="w-4 h-4" />
          Reload
        </button>
      </div>
    )
  }
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)
  // Set when the server says the session ended while the app was open.
  const [sessionLost, setSessionLost] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.getCurrentUser()
      .then((me) => { if (!cancelled) setUser(me) })
      .catch(() => {})
      .finally(() => { if (!cancelled) setChecking(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    setAuthRequiredHandler(() => setSessionLost(true))
    return () => setAuthRequiredHandler(null)
  }, [])

  const handleLoggedIn = useCallback((me) => {
    setUser(me)
    setSessionLost(false)
  }, [])

  const logout = useCallback(async () => {
    try { await api.logout() } catch { /* already logged out */ }
    setUser(null)
    setSessionLost(false)
    navigate('/')
  }, [navigate])

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.getCurrentUser()
      if (me) setUser(me)
    } catch { /* keep what we have */ }
  }, [])

  const auth = useMemo(() => ({ user, logout, refreshUser }), [user, logout, refreshUser])

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-gray-600 animate-spin" />
      </div>
    )
  }

  // Not logged in: show the login page at the current address, so after
  // logging in they land on the page they were trying to open.
  if (!user) {
    return <LoginPage onLoggedIn={handleLoggedIn} />
  }

  return (
    <AuthContext.Provider value={auth}>
      <Layout>
        <PageLoadBoundary resetKey={location.pathname}>
          <Suspense fallback={<PageLoading />}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/jobs" element={<AllJobs />} />
              <Route path="/bids" element={<BidTracker />} />
              <Route path="/jobs/:jobId" element={<JobDetail />} />
              <Route path="/pricing-rules" element={<PricingRulesPage />} />
              <Route path="/rules" element={<RulesRegistryPage />} />
              <Route path="/internal-rates" element={<PricingRulesPage />} />
              <Route path="/vendor-contacts" element={<VendorContactsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/users" element={<UsersPage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="/deleted-bids" element={<DeletedBidsPage />} />
            </Routes>
          </Suspense>
        </PageLoadBoundary>
      </Layout>
      {/* Session ended mid-work: log in over the page so unsaved edits stay put. */}
      {sessionLost && (
        <LoginPage overlay initialUsername={user.username} onLoggedIn={handleLoggedIn} />
      )}
    </AuthContext.Provider>
  )
}
