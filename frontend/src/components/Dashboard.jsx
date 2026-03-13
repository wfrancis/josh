import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Plus, Briefcase, FileText, DollarSign, Clock,
  ChevronRight, Building2, User, Loader2, HardHat,
  Upload, FileSpreadsheet, Calculator, FileDown,
  ArrowRight, Sparkles
} from 'lucide-react'
import { api } from '../api'
import StatusBadge, { getJobStatus } from './StatusBadge'

/* ── Stat Card ─────────────────────────────────────────── */
function StatCard({ icon: Icon, label, value, gradient }) {
  return (
    <div className="glass-card p-5 relative overflow-hidden group">
      <div className={`absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500
                       bg-gradient-to-br ${gradient}`} />
      <div className="relative flex items-center gap-4">
        <div className="w-11 h-11 rounded-xl bg-white/[0.06] flex items-center justify-center">
          <Icon className="w-5 h-5 text-gray-300" />
        </div>
        <div>
          <div className="text-3xl font-extrabold text-white tabular-nums tracking-tight">{value}</div>
          <div className="text-xs text-gray-500 font-medium mt-0.5">{label}</div>
        </div>
      </div>
    </div>
  )
}

/* ── Workflow Step ──────────────────────────────────────── */
function WorkflowStep({ step, icon: Icon, title, desc, accent }) {
  return (
    <div className="flex flex-col items-center text-center group">
      <div className={`w-14 h-14 rounded-2xl flex items-center justify-center mb-4
                       bg-gradient-to-br ${accent} shadow-lg transition-transform group-hover:scale-110`}>
        <Icon className="w-6 h-6 text-white" />
      </div>
      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-[0.15em] mb-1">Step {step}</div>
      <div className="text-sm font-semibold text-gray-200">{title}</div>
      <div className="text-xs text-gray-500 mt-1 max-w-[160px] leading-relaxed">{desc}</div>
    </div>
  )
}

/* ── Empty State ───────────────────────────────────────── */
function EmptyState({ onCreate }) {
  return (
    <div className="animate-fade-in">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-3xl glass-card p-12 mb-8">
        {/* Background glow */}
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-si-orange/[0.06] rounded-full blur-[100px] -translate-y-1/2 translate-x-1/4" />
        <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-si-bright/[0.04] rounded-full blur-[80px] translate-y-1/2 -translate-x-1/4" />

        <div className="relative max-w-xl">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-si-orange/10 border border-si-orange/20 text-si-orange text-xs font-semibold mb-6">
            <Sparkles className="w-3.5 h-3.5" />
            AI-Powered Bid Generation
          </div>
          <h1 className="text-4xl font-extrabold text-white tracking-tight leading-[1.1] mb-4">
            Professional flooring bids<br />
            <span className="bg-clip-text text-transparent bg-gradient-to-r from-si-orange to-amber-400">
              in minutes, not hours.
            </span>
          </h1>
          <p className="text-gray-400 text-base leading-relaxed mb-8 max-w-lg">
            Upload your RFMS takeoff and vendor quotes. We handle waste calculations,
            sundries, labor pricing, and generate a ready-to-send PDF bid.
          </p>
          <button onClick={onCreate} className="btn-primary text-base px-8 py-3.5 glow-orange">
            <Plus className="w-5 h-5" />
            Create Your First Bid
          </button>
        </div>
      </div>

      {/* Workflow */}
      <div className="glass-card p-8">
        <div className="text-center mb-8">
          <h2 className="text-lg font-bold text-white">How it works</h2>
          <p className="text-sm text-gray-500 mt-1">Three steps from takeoff to bid</p>
        </div>
        <div className="flex items-start justify-center gap-6">
          <WorkflowStep step={1} icon={FileSpreadsheet} title="Upload Takeoff" desc="Import your RFMS Excel. Materials auto-parsed with waste factors." accent="from-si-bright to-blue-600" />
          <div className="flex items-center pt-10">
            <ArrowRight className="w-5 h-5 text-gray-600" />
          </div>
          <WorkflowStep step={2} icon={Upload} title="Add Quotes" desc="Upload vendor PDFs. AI extracts product names and pricing." accent="from-violet-500 to-purple-600" />
          <div className="flex items-center pt-10">
            <ArrowRight className="w-5 h-5 text-gray-600" />
          </div>
          <WorkflowStep step={3} icon={FileDown} title="Generate Bid" desc="Auto-calculates sundries, labor, freight. Download a professional PDF." accent="from-si-orange to-orange-600" />
        </div>
      </div>
    </div>
  )
}

/* ── Create Job Modal ──────────────────────────────────── */
function CreateJobModal({ open, onClose, onCreated }) {
  const [form, setForm] = useState({
    project_name: '', gc_name: '', address: '', city: '', state: '', zip: '',
    tax_rate: 0, unit_count: 0, salesperson: '',
  })
  const [saving, setSaving] = useState(false)

  if (!open) return null

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      const result = await api.createJob({
        ...form,
        tax_rate: parseFloat(form.tax_rate) / 100 || 0,
        unit_count: parseInt(form.unit_count) || 0,
      })
      onCreated(result.id)
    } catch (err) {
      alert(err.message)
    } finally {
      setSaving(false)
    }
  }

  const set = (key) => (e) => setForm(f => ({ ...f, [key]: e.target.value }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-md" onClick={onClose} />
      <div className="relative w-full max-w-lg animate-slide-up">
        {/* Glow */}
        <div className="absolute -inset-1 bg-gradient-to-b from-si-orange/20 to-transparent rounded-3xl blur-xl opacity-50" />

        <div className="relative bg-[#111827] border border-white/[0.08] rounded-2xl shadow-2xl p-7">
          <h2 className="text-xl font-bold text-white mb-6">New Job</h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">Project Name *</label>
              <input className="input" value={form.project_name} onChange={set('project_name')} required
                     placeholder="e.g., Oakwood Apartments Phase 2" autoFocus />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">General Contractor</label>
                <input className="input" value={form.gc_name} onChange={set('gc_name')} placeholder="GC name" />
              </div>
              <div>
                <label className="label">Salesperson</label>
                <input className="input" value={form.salesperson} onChange={set('salesperson')} placeholder="Your name" />
              </div>
            </div>
            <div>
              <label className="label">Address</label>
              <input className="input" value={form.address} onChange={set('address')} placeholder="Street address" />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="label">City</label>
                <input className="input" value={form.city} onChange={set('city')} />
              </div>
              <div>
                <label className="label">State</label>
                <input className="input" value={form.state} onChange={set('state')} />
              </div>
              <div>
                <label className="label">ZIP</label>
                <input className="input" value={form.zip} onChange={set('zip')} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">Tax Rate (%)</label>
                <input className="input" type="number" step="0.01" min="0" max="20"
                       value={form.tax_rate} onChange={set('tax_rate')} placeholder="0.00" />
              </div>
              <div>
                <label className="label">Unit Count</label>
                <input className="input" type="number" min="0"
                       value={form.unit_count} onChange={set('unit_count')} placeholder="0" />
              </div>
            </div>
            <div className="flex gap-3 pt-3">
              <button type="button" onClick={onClose} className="btn-ghost flex-1 py-3">Cancel</button>
              <button type="submit" disabled={saving || !form.project_name} className="btn-primary flex-1 py-3">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                Create Job
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

/* ── Dashboard ─────────────────────────────────────────── */
export default function Dashboard() {
  const navigate = useNavigate()
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    api.listJobs()
      .then(setJobs)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const completedJobs = jobs.filter(j => j.bundles?.length > 0).length

  if (loading) {
    return (
      <div className="flex items-center justify-center py-40">
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-8 py-10">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-extrabold text-white tracking-tight">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Manage your flooring bids</p>
        </div>
        {jobs.length > 0 && (
          <button onClick={() => setShowCreate(true)} className="btn-primary">
            <Plus className="w-4 h-4" />
            New Job
          </button>
        )}
      </div>

      {/* Stats */}
      {jobs.length > 0 && (
        <div className="grid grid-cols-3 gap-4 mb-8">
          <StatCard icon={Briefcase} label="Total Jobs" value={jobs.length}
                    gradient="from-si-bright/[0.06] to-transparent" />
          <StatCard icon={FileText} label="Bids Generated" value={completedJobs}
                    gradient="from-emerald-500/[0.06] to-transparent" />
          <StatCard icon={Clock} label="In Progress" value={jobs.length - completedJobs}
                    gradient="from-amber-500/[0.06] to-transparent" />
        </div>
      )}

      {/* Content */}
      {jobs.length === 0 ? (
        <EmptyState onCreate={() => setShowCreate(true)} />
      ) : (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-bold text-gray-500 uppercase tracking-[0.15em]">Recent Jobs</h2>
          </div>
          <div className="space-y-2">
            {jobs.map((job, i) => {
              const status = getJobStatus(job)
              return (
                <div
                  key={job.id}
                  onClick={() => navigate(`/jobs/${job.id}`)}
                  className="glass-card-hover p-4 flex items-center gap-4 animate-fade-in cursor-pointer"
                  style={{ animationDelay: `${i * 50}ms` }}
                >
                  <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-si-navy/40 to-si-navy/20
                                flex items-center justify-center flex-shrink-0 border border-white/[0.04]">
                    <Building2 className="w-5 h-5 text-gray-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-white text-[15px]">{job.project_name}</div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                      {job.gc_name && (
                        <span className="flex items-center gap-1">
                          <Building2 className="w-3 h-3" />
                          {job.gc_name}
                        </span>
                      )}
                      {job.salesperson && (
                        <span className="flex items-center gap-1">
                          <User className="w-3 h-3" />
                          {job.salesperson}
                        </span>
                      )}
                      <span>{new Date(job.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                  <StatusBadge status={status} />
                  <ChevronRight className="w-4 h-4 text-gray-600" />
                </div>
              )
            })}
          </div>
        </div>
      )}

      <CreateJobModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(id) => { setShowCreate(false); navigate(`/jobs/${id}`) }}
      />
    </div>
  )
}
