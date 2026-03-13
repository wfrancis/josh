import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  Plus, Building2, User, Loader2, ChevronRight,
  Search, FolderOpen, Trash2
} from 'lucide-react'
import { api } from '../api'
import StatusBadge, { getJobStatus } from './StatusBadge'

export default function AllJobs() {
  const navigate = useNavigate()
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    api.listJobs()
      .then(setJobs)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const filtered = jobs.filter(j => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      j.project_name?.toLowerCase().includes(q) ||
      j.gc_name?.toLowerCase().includes(q) ||
      j.salesperson?.toLowerCase().includes(q) ||
      j.city?.toLowerCase().includes(q)
    )
  })

  const toggleSelect = (id, e) => {
    e.stopPropagation()
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === filtered.length) setSelected(new Set())
    else setSelected(new Set(filtered.map(j => j.id)))
  }

  const handleBulkDelete = async () => {
    if (!window.confirm(`Delete ${selected.size} job${selected.size !== 1 ? 's' : ''}? This cannot be undone.`)) return
    setDeleting(true)
    try {
      await api.bulkDeleteJobs([...selected])
      setJobs(prev => prev.filter(j => !selected.has(j.id)))
      setSelected(new Set())
    } catch (err) {
      console.error(err)
    } finally {
      setDeleting(false)
    }
  }

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
          <h1 className="text-2xl font-extrabold text-white tracking-tight">All Jobs</h1>
          <p className="text-sm text-gray-500 mt-1">{jobs.length} job{jobs.length !== 1 ? 's' : ''} total</p>
        </div>
        <button onClick={() => navigate('/?new=1')} className="btn-primary">
          <Plus className="w-4 h-4" />
          New Job
        </button>
      </div>

      {/* Search */}
      {jobs.length > 0 && (
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by project, GC, salesperson, or city..."
              className="input pl-11 w-full"
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer select-none whitespace-nowrap">
            <input
              type="checkbox"
              checked={filtered.length > 0 && selected.size === filtered.length}
              onChange={toggleAll}
              className="accent-si-bright w-4 h-4 rounded"
            />
            Select all
          </label>
        </div>
      )}

      {/* Jobs List */}
      {filtered.length === 0 ? (
        <div className="text-center py-16 glass-card">
          <FolderOpen className="w-12 h-12 text-gray-600 mx-auto mb-4" />
          {search ? (
            <>
              <p className="text-gray-400 font-medium">No jobs match "{search}"</p>
              <button onClick={() => setSearch('')} className="text-sm text-si-bright hover:underline mt-2">
                Clear search
              </button>
            </>
          ) : (
            <>
              <p className="text-gray-400 font-medium">No jobs yet</p>
              <p className="text-sm text-gray-600 mt-1">Create your first job from the Dashboard</p>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((job, i) => {
            const status = getJobStatus(job)
            return (
              <div
                key={job.id}
                onClick={() => navigate(`/jobs/${job.id}`)}
                className="glass-card-hover p-4 flex items-center gap-4 animate-fade-in cursor-pointer"
                style={{ animationDelay: `${i * 40}ms` }}
              >
                <input
                  type="checkbox"
                  checked={selected.has(job.id)}
                  onChange={(e) => toggleSelect(job.id, e)}
                  onClick={(e) => e.stopPropagation()}
                  className="accent-si-bright w-4 h-4 rounded flex-shrink-0"
                />
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
                    {(job.city || job.state) && (
                      <span>{[job.city, job.state].filter(Boolean).join(', ')}</span>
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
      )}
      {/* Floating bulk action bar */}
      {selected.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-slide-up">
          <div className="flex items-center gap-4 px-6 py-3 rounded-2xl bg-gray-900/95 backdrop-blur-xl border border-white/[0.08] shadow-2xl">
            <span className="text-sm text-gray-300 font-medium">
              {selected.size} selected
            </span>
            <button
              onClick={handleBulkDelete}
              disabled={deleting}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-red-500/15 border border-red-500/25 text-red-400 text-sm font-medium hover:bg-red-500/25 transition-colors disabled:opacity-50"
            >
              {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              Delete
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="text-sm text-gray-500 hover:text-gray-300 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
