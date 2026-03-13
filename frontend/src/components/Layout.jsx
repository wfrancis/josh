import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { LayoutDashboard, FolderOpen, Settings, HardHat, Menu, X } from 'lucide-react'

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
        <NavItem to="/settings" icon={Settings} label="Settings" active={location.pathname === '/settings'} onClick={onNavigate} />
        <div className="px-3 pt-2 text-[10px] text-gray-600">
          v1.0 · Standard Interiors
        </div>
      </div>
    </>
  )
}

export default function Layout({ children }) {
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="min-h-screen flex">
      {/* ── Desktop Sidebar ──────────────────────────── */}
      <aside className="hidden md:flex w-[260px] flex-shrink-0 bg-[#080C19] border-r border-white/[0.04] flex-col">
        <SidebarContent location={location} onNavigate={() => {}} />
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
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-si-orange to-orange-600 flex items-center justify-center">
              <HardHat className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold text-white tracking-wide">STANDARD</span>
          </div>
        </div>
        {/* Ambient glow */}
        <div className="fixed top-0 left-0 md:left-[260px] right-0 h-[400px] pointer-events-none z-0
                      bg-gradient-to-b from-si-bright/[0.03] via-transparent to-transparent" />
        <div className="relative z-10">
          {children}
        </div>
      </main>
    </div>
  )
}
