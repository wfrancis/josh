import { useCallback, useEffect, useMemo, useState } from 'react'
import { Routes, Route, useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { api, setAuthRequiredHandler } from './api'
import { AuthContext } from './auth'
import Layout from './components/Layout'
import LoginPage from './components/LoginPage'
import Dashboard from './components/Dashboard'
import AllJobs from './components/AllJobs'
import BidTracker from './components/BidTracker'
import JobDetail from './components/JobDetail'
import SettingsPage from './components/SettingsPage'
import InternalRatesPage from './components/InternalRatesPage'
import PricingRulesPage from './components/PricingRulesPage'
import VendorContactsPage from './components/VendorContactsPage'
import RulesRegistryPage from './components/RulesRegistryPage'

export default function App() {
  const navigate = useNavigate()
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

  const auth = useMemo(() => ({ user, logout }), [user, logout])

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
        </Routes>
      </Layout>
      {/* Session ended mid-work: log in over the page so unsaved edits stay put. */}
      {sessionLost && (
        <LoginPage overlay initialUsername={user.username} onLoggedIn={handleLoggedIn} />
      )}
    </AuthContext.Provider>
  )
}
