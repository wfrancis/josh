import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, ArchiveRestore, Loader2, Lock, RefreshCw, Search, Trash2 } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { formatMoney, formatWhen } from '../bidTracker'
import ConfirmDialog from './ConfirmDialog'

// Admins only: bids people deleted. Deleting only hides a bid, so nothing is
// lost; Restore puts it back in All Jobs for everyone.

function Dash() {
  return <span className="text-gray-600">—</span>
}

export default function DeletedBidsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isAdmin = !!user?.is_admin
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [asking, setAsking] = useState(null)
  const [restoringId, setRestoringId] = useState(null)
  const [restoreError, setRestoreError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const list = await api.listDeletedJobs()
      setRows(Array.isArray(list) ? list : [])
    } catch (err) {
      setError(err.message || "Deleted bids couldn't be loaded.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (isAdmin) load() }, [isAdmin, load])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q || !rows) return rows || []
    return rows.filter(row => [row.project_name, row.gc_name, row.deleted_by_name, row.deleted_by, row.delete_reason]
      .some(value => String(value || '').toLowerCase().includes(q)))
  }, [rows, search])

  const restore = async (row) => {
    setAsking(null)
    setRestoringId(row.id)
    setRestoreError('')
    try {
      const job = await api.restoreJob(row.id)
      navigate(`/jobs/${job?.slug || row.slug || row.id}`)
    } catch (err) {
      setRestoreError(`"${row.project_name || 'This bid'}" couldn't be restored: ${err.message || 'try again.'}`)
      setRestoringId(null)
    }
  }

  if (!isAdmin) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-8 py-16">
        <div className="glass-card p-8 text-center">
          <Lock className="w-10 h-10 text-gray-600 mx-auto mb-4" />
          <h1 className="text-xl font-bold text-white">Admins only</h1>
          <p className="text-sm text-gray-500 mt-2">
            Only admins can see and restore deleted bids. Ask an admin if a bid was deleted by mistake.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
      <div className="mb-6 sm:mb-8 flex flex-col sm:flex-row sm:items-end gap-3">
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-extrabold text-white tracking-tight">Deleted bids</h1>
          <p className="text-sm text-gray-500 mt-1">
            Deleting a bid only hides it. Restore one to put it back in All Jobs, with all its history.
          </p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="btn-secondary text-sm self-start sm:self-auto">
          <RefreshCw className={`w-4 h-4 ${loading && rows ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {restoreError && (
        <div role="alert" className="flex items-start gap-2 px-4 py-3 mb-6 rounded-xl text-sm border bg-red-500/10 border-red-500/20 text-red-400">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="flex-1">{restoreError}</span>
        </div>
      )}

      {rows === null && !error ? (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
        </div>
      ) : error && !rows ? (
        <div className="glass-card p-8 text-center">
          <AlertTriangle className="w-6 h-6 text-amber-400 mx-auto mb-3" />
          <p className="text-sm text-gray-300">{error}</p>
          <button type="button" onClick={load} className="btn-secondary text-sm mt-4 inline-flex">
            <RefreshCw className="w-4 h-4" /> Try again
          </button>
        </div>
      ) : rows && rows.length === 0 ? (
        <div className="glass-card p-10 text-center">
          <Trash2 className="w-10 h-10 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400 font-medium">No deleted bids</p>
          <p className="text-sm text-gray-600 mt-1">When someone deletes a bid, it shows up here so an admin can restore it.</p>
        </div>
      ) : (
        <>
          <div className="relative mb-4">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by bid, GC, who deleted it, or reason..."
              className="input pl-11 w-full"
            />
          </div>
          {error && <p className="text-xs text-red-400 mb-3">{error}</p>}
          <div className="glass-card overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="text-left text-[11px] font-bold text-gray-500 uppercase tracking-wider">
                  <th className="px-4 py-3">Bid</th>
                  <th className="px-3 py-3">GC</th>
                  <th className="px-3 py-3">Deleted by</th>
                  <th className="px-3 py-3">When</th>
                  <th className="px-3 py-3">Reason</th>
                  <th className="px-3 py-3 text-right">Total</th>
                  <th className="px-4 py-3 text-right"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(row => {
                  const busy = restoringId === row.id
                  return (
                    <tr key={row.id} className="border-t border-white/[0.05] align-top">
                      <td className="px-4 py-3">
                        <Link
                          to={`/jobs/${row.id}`}
                          className="font-semibold text-white hover:text-si-bright break-words"
                          title="Open this bid (read-only while it is deleted)"
                        >
                          {row.project_name || `Bid #${row.id}`}
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-gray-400">{row.gc_name || <Dash />}</td>
                      <td className="px-3 py-3 text-gray-300">{row.deleted_by_name || row.deleted_by || <Dash />}</td>
                      <td className="px-3 py-3 text-gray-400 whitespace-nowrap">{formatWhen(row.deleted_at) || <Dash />}</td>
                      <td className="px-3 py-3 text-gray-400 max-w-[18rem]">
                        <span className="break-words whitespace-pre-wrap">{row.delete_reason || <Dash />}</span>
                      </td>
                      <td className="px-3 py-3 text-right text-gray-300 tabular-nums whitespace-nowrap">
                        {row.grand_total != null && row.grand_total !== '' ? formatMoney(row.grand_total) : <Dash />}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => setAsking(row)}
                          disabled={restoringId !== null}
                          className="btn-secondary text-xs px-3 py-1.5 inline-flex"
                        >
                          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArchiveRestore className="w-3.5 h-3.5" />}
                          Restore
                        </button>
                      </td>
                    </tr>
                  )
                })}
                {filtered.length === 0 && (
                  <tr className="border-t border-white/[0.05]">
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                      No deleted bids match "{search}".
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-gray-600 mt-3">
            {rows.length} deleted bid{rows.length === 1 ? '' : 's'}
          </p>
        </>
      )}

      <ConfirmDialog
        open={!!asking}
        title="Restore this bid?"
        message={asking ? `"${asking.project_name || 'This bid'}" goes back to All Jobs and everyone can work on it again.` : ''}
        confirmLabel="Restore bid"
        confirmVariant="restore"
        onConfirm={() => asking && restore(asking)}
        onCancel={() => setAsking(null)}
      />
    </div>
  )
}
