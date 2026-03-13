import { Link, useLocation } from 'react-router-dom'
import { LayoutDashboard, FolderOpen, Settings, HardHat, Zap } from 'lucide-react'

function NavItem({ to, icon: Icon, label, active }) {
  return (
    <Link
      to={to}
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

export default function Layout({ children }) {
  const location = useLocation()

  return (
    <div className="min-h-screen flex">
      {/* ── Sidebar ────────────────────────────────────── */}
      <aside className="w-[260px] flex-shrink-0 bg-[#080C19] border-r border-white/[0.04] flex flex-col">
        {/* Logo */}
        <div className="px-5 py-6">
          <Link to="/" className="flex items-center gap-3 group">
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
          <NavItem to="/" icon={LayoutDashboard} label="Dashboard" active={location.pathname === '/'} />
          <NavItem to="/jobs" icon={FolderOpen} label="All Jobs" active={location.pathname === '/jobs' || location.pathname.startsWith('/jobs/')} />
        </nav>

        {/* Bottom section */}
        <div className="px-3 pb-4 space-y-1">
          <div className="mx-3 mb-3 px-3 py-3 rounded-xl bg-gradient-to-br from-si-bright/10 to-si-bright/5 border border-si-bright/10">
            <div className="flex items-center gap-2 text-si-bright text-xs font-semibold mb-1">
              <Zap className="w-3.5 h-3.5" />
              AI-Powered
            </div>
            <p className="text-[11px] text-gray-500 leading-relaxed">
              Quotes parsed automatically with AI. Upload PDFs and let us extract pricing.
            </p>
          </div>
          <NavItem to="/settings" icon={Settings} label="Settings" active={location.pathname === '/settings'} />
          <div className="px-3 pt-2 text-[10px] text-gray-600">
            v1.0 · Standard Interiors
          </div>
        </div>
      </aside>

      {/* ── Main Content ───────────────────────────────── */}
      <main className="flex-1 min-w-0 overflow-y-auto h-screen">
        {/* Ambient glow */}
        <div className="fixed top-0 left-[260px] right-0 h-[400px] pointer-events-none z-0
                      bg-gradient-to-b from-si-bright/[0.03] via-transparent to-transparent" />
        <div className="relative z-10">
          {children}
        </div>
      </main>
    </div>
  )
}
