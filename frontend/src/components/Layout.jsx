import { useState, useEffect, useRef } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { LayoutDashboard, FolderOpen, Settings, HardHat, Menu, X, Search, DollarSign, Bell, Building2 } from 'lucide-react'
import { api } from '../api'

function NavItem({ to, icon: Icon, label, active, onClick }) {
  return (
    <Link
      to={to}
      onClick={onClick}
      className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200
        ${active
          ? 'bg-white/[0.08] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
          : 'text-gray-500 hover:text-gray-300 hover:bg-white/[0.04]'
        }`}
    >
      <Icon className="w-[18px] h-[18px]" />
      {label}
    </Link>
  )
}

function SidebarContent({ location, onNavigate }) {
  const navigate = useNavigate()
  const [searchQuery, setSearchQuery] = useState('')
  const [results, setResults] = useState(null)
  const searchRef = useRef(null)

  useEffect(() => {
    if (!searchQuery || searchQuery.length < 2) { setResults(null); return }
    const timer = setTimeout(async () => {
      try {
        const data = await api.search(searchQuery)
        setResults(data)
      } catch { setResults(null) }
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  useEffect(() => {
    function handleKey(e) {
      if (e.key === 'Escape') { setSearchQuery(''); setResults(null) }
    }
    function handleClickOutside(e) {
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        setResults(null)
      }
    }
    document.addEventListener('keydown', handleKey)
    document.addEventListener('mousedown', handleClickOutside)
    return () => { document.removeEventListener('keydown', handleKey); document.removeEventListener('mousedown', handleClickOutside) }
  }, [])

  return (
    <>
      {/* Logo */}
      <div className="px-5 py-6">
        <Link to="/" onClick={onNavigate} className="flex items-center gap-3 group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-si-orange to-orange-600
                        flex items-center justify-center shadow-[0_2px_8px_rgba(255,95,0,0.3)]
                        group-hover:shadow-[0_4px_16px_rgba(255,95,0,0.4)] transition-shadow">
            <HardHat className="w-5 h-5 text-white" />
          </div>
          <div className="flex flex-col">
            <span className="text-[15px] font-extrabold tracking-[0.04em] text-white">STANDARD</span>
            <span className="text-[10px] font-semibold tracking-[0.15em] text-gray-500 uppercase">Bid Tool</span>
          </div>
        </Link>
      </div>

      {/* Search */}
      <div className="px-3 mb-4" ref={searchRef}>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search..."
            className="w-full pl-9 pr-3 py-2 text-sm bg-white/[0.04] border border-white/[0.06] rounded-xl
                       text-gray-300 placeholder-gray-600 focus:outline-none focus:border-white/[0.12]
                       focus:bg-white/[0.06] transition-colors"
          />
        </div>
        {results && (results.jobs?.length > 0 || results.materials?.length > 0) && (
          <div className="mt-2 max-h-64 overflow-y-auto bg-[#0d1429] border border-white/[0.08] rounded-xl shadow-2xl">
            {results.jobs?.length > 0 && (
              <div>
                <div className="px-3 pt-2 pb-1 text-[10px] font-bold text-gray-600 uppercase tracking-[0.15em]">Jobs</div>
                {results.jobs.map((job) => (
                  <button key={job.id} onClick={() => { navigate(`/jobs/${job.slug || job.id}`); setSearchQuery(''); setResults(null); onNavigate?.() }}
                    className="w-full text-left px-3 py-2 hover:bg-white/[0.06] transition-colors">
                    <div className="text-sm text-gray-200 truncate">{job.project_name}</div>
                    {job.gc_name && <div className="text-xs text-gray-500">{job.gc_name}</div>}
                  </button>
                ))}
              </div>
            )}
            {results.materials?.length > 0 && (
              <div>
                <div className="px-3 pt-2 pb-1 text-[10px] font-bold text-gray-600 uppercase tracking-[0.15em]">Materials</div>
                {results.materials.map((group, i) => (
                  <div key={i}>
                    <div className="px-3 pt-1.5 pb-0.5 text-[10px] text-gray-500 truncate">{group.project_name}</div>
                    {group.matches?.slice(0, 3).map((m, j) => (
                      <button key={j} onClick={() => { navigate(`/jobs/${group.slug || group.job_id}`); setSearchQuery(''); setResults(null); onNavigate?.() }}
                        className="w-full text-left px-3 py-1.5 hover:bg-white/[0.06] transition-colors">
                        <div className="text-sm text-gray-200 truncate">{m.description || m.item_code}</div>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 space-y-1">
        <div className="px-3 py-2 text-[10px] font-bold text-gray-600 uppercase tracking-[0.15em]">
          Workspace
        </div>
        <NavItem to="/" icon={LayoutDashboard} label="Dashboard" active={location.pathname === '/'} onClick={onNavigate} />
        <NavItem to="/jobs" icon={FolderOpen} label="All Jobs" active={location.pathname === '/jobs' || location.pathname.startsWith('/jobs/')} onClick={onNavigate} />
      </nav>

      {/* Bottom section */}
      <div className="px-3 pb-4 space-y-1">
        <NavItem to="/pricing-rules" icon={DollarSign} label="Pricing & Rules" active={location.pathname === '/pricing-rules'} onClick={onNavigate} />
        <NavItem to="/vendor-contacts" icon={Building2} label="Vendor Contacts" active={location.pathname === '/vendor-contacts'} onClick={onNavigate} />
        <NavItem to="/settings" icon={Settings} label="Settings" active={location.pathname === '/settings'} onClick={onNavigate} />
        <div className="px-3 pt-2 text-[10px] text-gray-600">
          v1.0 · Standard Interiors
        </div>
      </div>
    </>
  )
}

function NotificationBell() {
  const [notifications, setNotifications] = useState([])
  const [open, setOpen] = useState(false)
  const bellRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    const load = () => api.getNotifications(true).then(setNotifications).catch(() => {})
    load()
    const interval = setInterval(load, 30000) // poll every 30s
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (!open) return
    const handleClick = (e) => { if (bellRef.current && !bellRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const unreadCount = notifications.length

  const handleRead = async (n) => {
    await api.markNotificationRead(n.id).catch(() => {})
    setNotifications(prev => prev.filter(x => x.id !== n.id))
    if (n.job_id) {
      navigate(`/jobs/${n.job_id}`)
      setOpen(false)
    }
  }

  return (
    <div className="relative" ref={bellRef}>
      <button onClick={() => setOpen(!open)} className="relative p-1.5 text-gray-500 hover:text-gray-300 transition-colors">
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-si-orange text-white text-[9px] font-bold flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-[#0d1429] border border-white/[0.08] rounded-xl shadow-2xl z-50 overflow-hidden">
          <div className="px-4 py-3 border-b border-white/[0.06]">
            <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">Notifications</span>
          </div>
          {notifications.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-gray-500">No new notifications</div>
          ) : (
            <div className="max-h-64 overflow-y-auto">
              {notifications.map(n => (
                <button key={n.id} onClick={() => handleRead(n)}
                  className="w-full text-left px-4 py-3 hover:bg-white/[0.04] transition-colors border-b border-white/[0.03] last:border-b-0">
                  <p className="text-sm text-gray-200">{n.message}</p>
                  <p className="text-[10px] text-gray-500 mt-1">{new Date(n.created_at).toLocaleString()}</p>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TestModeBanner() {
  const [testMode, setTestMode] = useState(false)
  const [toggling, setToggling] = useState(false)

  useEffect(() => {
    api.simStatus().then(s => setTestMode(!!s.test_mode)).catch(() => {})
  }, [])

  const handleToggle = async () => {
    setToggling(true)
    try {
      await api.updateSettings({ vendor_quote_test_mode: testMode ? 'false' : 'true' })
      setTestMode(!testMode)
    } catch (err) {
      console.error('Failed to toggle test mode:', err)
    } finally {
      setToggling(false)
    }
  }

  if (!testMode) return null

  return (
    <div className="bg-amber-500 text-black px-4 py-2 flex items-center justify-center gap-3 text-sm font-bold tracking-wide z-[100] relative">
      <span className="text-lg">&#9888;</span>
      <span>TEST MODE — Vendor emails route to Simulator, not real vendors.</span>
      <button
        onClick={handleToggle}
        disabled={toggling}
        className="ml-2 px-3 py-1 rounded-lg bg-black/20 hover:bg-black/30 text-black font-semibold text-xs transition-colors disabled:opacity-50"
      >
        {toggling ? 'Switching...' : 'Switch to Live \u2192'}
      </button>
    </div>
  )
}

export default function Layout({ children }) {
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="min-h-screen flex flex-col">
      <TestModeBanner />
      <div className="flex flex-1 min-h-0">
      {/* ── Desktop Sidebar ──────────────────────────── */}
      <aside className="hidden md:flex w-[260px] flex-shrink-0 bg-[#080C19] border-r border-white/[0.04] flex-col relative">
        <SidebarContent location={location} onNavigate={() => {}} />
        <div className="absolute top-6 right-5">
          <NotificationBell />
        </div>
      </aside>

      {/* ── Mobile Sidebar Overlay ────────────────────── */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <aside className="relative w-[280px] h-full bg-[#080C19] border-r border-white/[0.04] flex flex-col animate-slide-in-left">
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute top-4 right-4 p-2 text-gray-500 hover:text-white"
            >
              <X className="w-5 h-5" />
            </button>
            <SidebarContent location={location} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      {/* ── Main Content ───────────────────────────────── */}
      <main className="flex-1 min-w-0 overflow-y-auto h-screen">
        {/* Mobile header bar */}
        <div className="md:hidden sticky top-0 z-40 flex items-center gap-3 px-4 py-3 bg-[#080C19]/95 backdrop-blur-md border-b border-white/[0.04]">
          <button onClick={() => setMobileOpen(true)} className="p-1.5 text-gray-400 hover:text-white">
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2 flex-1">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-si-orange to-orange-600 flex items-center justify-center">
              <HardHat className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold text-white tracking-wide">STANDARD</span>
          </div>
          <NotificationBell />
        </div>
        {/* Ambient glow */}
        <div className="fixed top-0 left-0 md:left-[260px] right-0 h-[400px] pointer-events-none z-0
                      bg-gradient-to-b from-si-bright/[0.03] via-transparent to-transparent" />
        <div className="relative z-10">
          {children}
        </div>
      </main>
      </div>
    </div>
  )
}
