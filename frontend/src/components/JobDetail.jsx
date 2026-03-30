import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  ArrowLeft, Building2, MapPin, User, Percent, Hash,
  Loader2, FileSpreadsheet, Save, AlertTriangle, Trash2,
  StickyNote, ChevronDown, ChevronUp, Cpu, CheckCircle2, X, Upload, Download, Copy,
  Pencil
} from 'lucide-react'
import { api } from '../api'
import StepIndicator from './StepIndicator'

import MaterialsTable from './MaterialsTable'
import BidPreview from './BidPreview'
import ProposalEditor from './ProposalEditor'
import QuoteUpload from './QuoteUpload'
import VendorQuoteFlow from './VendorQuoteFlow'
import QuoteTracker from './QuoteTracker'
import StatusBadge, { getJobStatus } from './StatusBadge'
import ConfirmDialog from './ConfirmDialog'
import ActivityLog from './ActivityLog'

export default function JobDetail() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(true)
  const [step, setStep] = useState('takeoff')
  const [rfmsLoading, setRfmsLoading] = useState(false)
  const [rfmsSuccess, setRfmsSuccess] = useState(false)
  const [stagedFiles, setStagedFiles] = useState([])
  const rfmsInputRef = useRef(null)
  const quoteSectionRef = useRef(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [notesOpen, setNotesOpen] = useState(false)
  const [notes, setNotes] = useState('')
  const [aiSettings, setAiSettings] = useState(null)
  const [confirmDialog, setConfirmDialog] = useState(null)
  const [isDirty, setIsDirty] = useState(false)
  const [quotePanel, setQuotePanel] = useState(null) // null | 'request' | 'upload'
  const [quotePreSelectedIds, setQuotePreSelectedIds] = useState(null)
  const [quoteMaterial, setQuoteMaterial] = useState(null) // single-material quote modal
  const [quoteCopied, setQuoteCopied] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editForm, setEditForm] = useState({})
  const [editSaving, setEditSaving] = useState(false)
  const [quoteRequests, setQuoteRequests] = useState([])

  const loadJob = async () => {
    try {
      const data = await api.getJob(jobId)
      setJob(data)
      setNotes(data.notes || '')
      setNotesOpen(!!data.notes)
      if (data.materials?.length > 0) setRfmsSuccess(true)
      if (data.bundles?.length > 0 || data.bid_data) setStep('bid')
      else if (data.materials?.length > 0) setStep('takeoff')
      // Load quote requests for status tracking
      api.listQuoteRequests(data.id).then(setQuoteRequests).catch(console.error)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadJob() }, [jobId])
  useEffect(() => { api.getSettings().then(setAiSettings).catch(() => {}) }, [])

  const startEditing = () => {
    setEditForm({
      project_name: job.project_name || '',
      gc_name: job.gc_name || '',
      address: job.address || '',
      city: job.city || '',
      state: job.state || '',
      zip: job.zip || '',
      salesperson: job.salesperson || '',
      tax_rate: job.tax_rate ? (job.tax_rate * 100).toFixed(2) : '',
      gpm_pct: job.gpm_pct ? (job.gpm_pct * 100).toFixed(2) : '',
      unit_count: job.unit_count || '',
      tub_shower_count: job.tub_shower_count || '',
      architect: job.architect || '',
      designer: job.designer || '',
      textura_fee: job.textura_fee || 0,
    })
    setEditing(true)
  }

  const cancelEditing = () => {
    setEditing(false)
    setEditForm({})
  }

  const saveEditing = async () => {
    setEditSaving(true)
    try {
      const updates = {
        project_name: editForm.project_name || job.project_name,
        gc_name: editForm.gc_name || null,
        address: editForm.address || null,
        city: editForm.city || null,
        state: editForm.state || null,
        zip: editForm.zip || null,
        salesperson: editForm.salesperson || null,
        tax_rate: editForm.tax_rate ? parseFloat(editForm.tax_rate) / 100 : 0,
        gpm_pct: editForm.gpm_pct ? parseFloat(editForm.gpm_pct) / 100 : 0,
        unit_count: editForm.unit_count ? parseInt(editForm.unit_count) : 0,
        tub_shower_count: editForm.tub_shower_count ? parseInt(editForm.tub_shower_count) : 0,
        architect: editForm.architect || null,
        designer: editForm.designer || null,
        textura_fee: editForm.textura_fee ? 1 : 0,
      }
      await api.updateJob(jobId, updates)
      const updated = await api.getJob(jobId)
      setJob(updated)
      setEditing(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setEditSaving(false)
    }
  }

  useEffect(() => {
    const handler = (e) => {
      if (isDirty) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

  const handleRfmsUpload = async (fileList) => {
    setRfmsLoading(true)
    setError(null)
    try {
      await api.uploadRFMS(jobId, fileList)
      const updated = await api.getJob(jobId)
      setJob(updated)
      setRfmsSuccess(true)
      setStagedFiles([])
      // Stay on takeoff step — user reviews materials here
    } catch (err) {
      setError(err.message)
    } finally {
      setRfmsLoading(false)
    }
  }

  // Stage a file and auto-trigger when both are ready
  const stageRfmsFile = useCallback((newFiles) => {
    const incoming = Array.isArray(newFiles) ? newFiles : [newFiles]
    setStagedFiles(prev => {
      const combined = [...prev, ...incoming].slice(0, 2)
      // Auto-trigger upload when we hit 2 files
      if (combined.length >= 2) {
        setTimeout(() => handleRfmsUpload(combined), 300)
      }
      return combined
    })
  }, [jobId])

  const handleRfmsDrop = useCallback((e) => {
    e.preventDefault(); e.stopPropagation()
    const dropped = Array.from(e.dataTransfer.files)
    if (dropped.length) stageRfmsFile(dropped)
  }, [stageRfmsFile])

  const handleRfmsFileSelect = (e) => {
    const selected = Array.from(e.target.files)
    if (selected.length) stageRfmsFile(selected)
    if (rfmsInputRef.current) rfmsInputRef.current.value = ''
  }

  const removeStaged = (idx) => {
    setStagedFiles(prev => prev.filter((_, i) => i !== idx))
  }

  const handleMaterialsUpdate = (materials) => {
    setJob(j => ({ ...j, materials }))
    setIsDirty(true)
  }

  // Auto-save: debounce 1.5s after any material edit
  const autoSaveRef = useRef(null)
  useEffect(() => {
    if (!isDirty || !job?.materials?.length) return
    clearTimeout(autoSaveRef.current)
    autoSaveRef.current = setTimeout(async () => {
      try {
        setSaving(true)
        const result = await api.updateMaterials(jobId, job.materials)
        setJob(j => ({ ...j, materials: result.materials }))
        setIsDirty(false)
      } catch (err) {
        console.error('Auto-save failed:', err)
      } finally {
        setSaving(false)
      }
    }, 1500)
    return () => clearTimeout(autoSaveRef.current)
  }, [isDirty, job?.materials])

  const handleSavePricing = async () => {
    clearTimeout(autoSaveRef.current)
    setSaving(true)
    setError(null)
    try {
      const result = await api.updateMaterials(jobId, job.materials)
      setJob(j => ({ ...j, materials: result.materials }))
      setIsDirty(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const getCompletedSteps = () => {
    const completed = []
    if (job?.materials?.length > 0) completed.push('takeoff')
    if (job?.bundles?.length > 0 || job?.bid_data) completed.push('bid')
    return completed
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-40">
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    )
  }

  if (!job) {
    return (
      <div className="max-w-5xl mx-auto px-8 py-12 text-center">
        <p className="text-gray-500">Job not found</p>
        <Link to="/" className="text-si-bright hover:underline mt-2 inline-block">Back to Dashboard</Link>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-8 py-6 sm:py-8">
      {/* Header */}
      <div className="flex items-start gap-4 mb-8">
        <button onClick={() => navigate('/')} className="btn-ghost p-2 mt-0.5">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          {editing ? (
            /* ── Edit Mode ── */
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <input
                  type="text"
                  value={editForm.project_name}
                  onChange={e => setEditForm(f => ({ ...f, project_name: e.target.value }))}
                  className="text-xl sm:text-2xl font-extrabold text-white tracking-tight bg-transparent border-b-2 border-si-bright/50 focus:border-si-bright outline-none w-full pb-1"
                  placeholder="Project Name"
                  autoFocus
                />
                <StatusBadge status={getJobStatus(job)} />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">General Contractor</span>
                  <input type="text" value={editForm.gc_name} onChange={e => setEditForm(f => ({ ...f, gc_name: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="GC Name" />
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">Address</span>
                  <input type="text" value={editForm.address} onChange={e => setEditForm(f => ({ ...f, address: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="Street Address" />
                </label>
                <div className="grid grid-cols-3 gap-2">
                  <label className="block col-span-1">
                    <span className="text-xs text-gray-500 mb-1 block">City</span>
                    <input type="text" value={editForm.city} onChange={e => setEditForm(f => ({ ...f, city: e.target.value }))}
                      className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                      placeholder="City" />
                  </label>
                  <label className="block col-span-1">
                    <span className="text-xs text-gray-500 mb-1 block">State</span>
                    <input type="text" value={editForm.state} onChange={e => setEditForm(f => ({ ...f, state: e.target.value }))}
                      className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                      placeholder="ST" />
                  </label>
                  <label className="block col-span-1">
                    <span className="text-xs text-gray-500 mb-1 block">ZIP</span>
                    <input type="text" value={editForm.zip} onChange={e => setEditForm(f => ({ ...f, zip: e.target.value }))}
                      className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                      placeholder="ZIP" />
                  </label>
                </div>
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">Salesperson</span>
                  <input type="text" value={editForm.salesperson} onChange={e => setEditForm(f => ({ ...f, salesperson: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="Salesperson" />
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">Tax Rate (%)</span>
                  <input type="number" step="0.01" value={editForm.tax_rate} onChange={e => setEditForm(f => ({ ...f, tax_rate: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="9.15" />
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">GPM (%)</span>
                  <input type="number" step="0.01" value={editForm.gpm_pct} onChange={e => setEditForm(f => ({ ...f, gpm_pct: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="23" />
                </label>
                <label className="flex items-center gap-3 py-2">
                  <input type="checkbox" checked={!!editForm.textura_fee} onChange={e => setEditForm(f => ({ ...f, textura_fee: e.target.checked ? 1 : 0 }))}
                    className="w-4 h-4 rounded border-white/10 bg-white/[0.04] text-si-accent focus:ring-si-accent/50" />
                  <span className="text-xs text-gray-500">Textura Fee (0.22%)</span>
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">Unit Count</span>
                  <input type="number" value={editForm.unit_count} onChange={e => setEditForm(f => ({ ...f, unit_count: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="0" />
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">Tubs/Showers per Unit</span>
                  <input type="number" value={editForm.tub_shower_count} onChange={e => setEditForm(f => ({ ...f, tub_shower_count: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="0" />
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">Architect</span>
                  <input type="text" value={editForm.architect} onChange={e => setEditForm(f => ({ ...f, architect: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="Architect" />
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 mb-1 block">Designer</span>
                  <input type="text" value={editForm.designer} onChange={e => setEditForm(f => ({ ...f, designer: e.target.value }))}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-si-bright/50 focus:outline-none"
                    placeholder="Designer" />
                </label>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={saveEditing} disabled={editSaving || !editForm.project_name?.trim()}
                  className="btn-primary text-sm px-4 py-2 flex items-center gap-2">
                  {editSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                  Save Changes
                </button>
                <button onClick={cancelEditing} className="btn-ghost text-sm px-4 py-2">Cancel</button>
              </div>
            </div>
          ) : (
            /* ── Display Mode ── */
            <>
              <div className="flex items-center gap-3">
                <h1 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight">{job.project_name}</h1>
                <StatusBadge status={getJobStatus(job)} />
              </div>
              <div className="flex flex-wrap items-center gap-4 mt-2 text-sm text-gray-500">
                {job.gc_name && (
                  <span className="flex items-center gap-1.5">
                    <Building2 className="w-3.5 h-3.5" /> {job.gc_name}
                  </span>
                )}
                {(job.city || job.state) && (
                  <span className="flex items-center gap-1.5">
                    <MapPin className="w-3.5 h-3.5" />
                    {[job.address, job.city, job.state, job.zip].filter(Boolean).join(', ')}
                  </span>
                )}
                {job.salesperson && (
                  <span className="flex items-center gap-1.5">
                    <User className="w-3.5 h-3.5" /> {job.salesperson}
                  </span>
                )}
                {job.tax_rate > 0 && (
                  <span className="flex items-center gap-1.5">
                    <Percent className="w-3.5 h-3.5" /> {(job.tax_rate * 100).toFixed(2)}% tax
                  </span>
                )}
                {job.gpm_pct > 0 && (
                  <span className="flex items-center gap-1.5">
                    <Percent className="w-3.5 h-3.5" /> {(job.gpm_pct * 100).toFixed(0)}% GPM
                  </span>
                )}
                {job.unit_count > 0 && (
                  <span className="flex items-center gap-1.5">
                    <Hash className="w-3.5 h-3.5" /> {job.unit_count} units
                  </span>
                )}
                {job.tub_shower_count > 0 && (
                  <span className="flex items-center gap-1.5">
                    <Hash className="w-3.5 h-3.5" /> {job.tub_shower_count} tubs/showers per unit
                  </span>
                )}
                {aiSettings && (
                  <span className="flex items-center gap-1.5">
                    <Cpu className="w-3.5 h-3.5" /> {aiSettings.openai_model} · {aiSettings.multi_pass_count}x
                  </span>
                )}
              </div>
            </>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!editing && (
            <button
              onClick={startEditing}
              className="btn-ghost p-2 mt-0.5 text-gray-500 hover:text-si-bright hover:bg-si-bright/10"
              title="Edit job details"
            >
              <Pencil className="w-5 h-5" />
            </button>
          )}
          <button
            onClick={() => setConfirmDialog({
              title: 'Duplicate Job',
              message: `This will create a copy of "${job.project_name}" with all materials, pricing, and settings. The new job will start as a Draft.`,
              confirmLabel: 'Duplicate Job',
              confirmVariant: 'info',
              onConfirm: () => {
                setConfirmDialog(null)
                api.duplicateJob(jobId).then(r => navigate(`/jobs/${r.slug || r.id}`)).catch(err => setError(err.message))
              }
            })}
            className="btn-ghost p-2 mt-0.5 text-gray-500 hover:text-si-bright hover:bg-si-bright/10"
            title="Duplicate job"
          >
            <Copy className="w-5 h-5" />
          </button>
        <button
          onClick={() => setConfirmDialog({
            title: 'Delete Job',
            message: `Are you sure you want to delete "${job.project_name}"? All materials, pricing, quotes, and bid data will be permanently removed. This cannot be undone.`,
            confirmLabel: 'Delete Job',
            confirmVariant: 'danger',
            onConfirm: () => {
              setConfirmDialog(null)
              api.deleteJob(jobId).then(() => navigate('/')).catch(err => setError(err.message))
            }
          })}
          className="btn-ghost p-2 mt-0.5 text-gray-500 hover:text-red-400 hover:bg-red-500/10"
          title="Delete job"
        >
          <Trash2 className="w-5 h-5" />
        </button>
        </div>
      </div>

      {/* Notes */}
      <div className="mb-4">
        <button
          onClick={() => setNotesOpen(!notesOpen)}
          className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-300 transition-colors"
        >
          <StickyNote className="w-3.5 h-3.5" />
          {notesOpen ? 'Hide' : 'Show'} Notes
          {notesOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
        {notesOpen && (
          <textarea
            className="input w-full mt-2 min-h-[80px] text-sm resize-y"
            placeholder="Add notes about this job..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => api.updateNotes(jobId, notes).catch(() => {})}
          />
        )}
      </div>

      {/* Stepper */}
      <div className="glass-card px-3 sm:px-6 py-3 sm:py-4 mb-6 sm:mb-8">
        <StepIndicator
          current={step}
          onStepClick={setStep}
          completedSteps={getCompletedSteps()}
          disabledSteps={job.materials?.length > 0 && job.materials.some(m => !m.unit_price || m.unit_price === 0) ? ['bid'] : []}
        />
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 mb-6 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
          <button onClick={() => setError(null)} className="ml-auto text-red-500/60 hover:text-red-400">dismiss</button>
        </div>
      )}

      {/* Step Content */}
      <div className="animate-fade-in" key={step}>
        {step === 'takeoff' && (
          <div className="space-y-6">
            {/* RFMS Upload */}
            <div className={`glass-card ${rfmsSuccess ? 'p-4' : 'p-4 sm:p-8'}`}>
              {!rfmsSuccess && (
                <>
                  <h2 className="text-lg font-bold text-white mb-1">Upload RFMS Takeoff</h2>
                  <p className="text-sm text-gray-500 mb-4 sm:mb-6">
                    Upload RFMS pivot table files (.xlsx). Materials, waste factors, and pricing are applied automatically.
                  </p>
                </>
              )}

              {rfmsSuccess ? (
                <div className="flex items-center gap-3 px-4 py-3 bg-emerald-500/[0.06] border border-emerald-500/20 rounded-xl">
                  <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />
                  <span className="text-sm font-medium text-emerald-300 flex-1">
                    {job.materials?.length || 0} materials parsed with waste factors applied
                  </span>
                  <button
                    onClick={() => { setStagedFiles([]); setRfmsSuccess(false) }}
                    className="text-xs text-emerald-500/70 hover:text-emerald-400 transition-colors"
                  >Upload new files</button>
                </div>
              ) : rfmsLoading ? (
                <div className="upload-zone text-center py-10">
                  <div className="relative w-16 h-16 mx-auto mb-5">
                    <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-si-bright/20 to-blue-500/20 animate-pulse" />
                    <div className="relative w-full h-full rounded-2xl bg-white/[0.04] flex items-center justify-center border border-white/[0.08]"
                         style={{ animation: 'pulse-glow 2s ease-in-out infinite' }}>
                      <svg className="w-8 h-8 text-si-bright" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
                      </svg>
                    </div>
                  </div>
                  <p className="text-sm font-medium text-white mb-1">AI is analyzing your files</p>
                  <div className="flex items-center justify-center gap-1 mb-4">
                    <span className="text-xs text-gray-500">Classifying materials</span>
                    <span className="flex gap-0.5 ml-1">
                      <span className="ai-dot w-1 h-1 rounded-full bg-si-bright inline-block" />
                      <span className="ai-dot w-1 h-1 rounded-full bg-si-bright inline-block" />
                      <span className="ai-dot w-1 h-1 rounded-full bg-si-bright inline-block" />
                    </span>
                  </div>
                  <div className="w-48 h-1 mx-auto rounded-full overflow-hidden bg-white/[0.06]">
                    <div className="ai-thinking-bar h-full rounded-full" />
                  </div>
                </div>
              ) : (
                <div
                  className="upload-zone text-center cursor-pointer"
                  onDragEnter={(e) => { e.preventDefault(); e.stopPropagation() }}
                  onDragLeave={(e) => { e.preventDefault(); e.stopPropagation() }}
                  onDragOver={(e) => { e.preventDefault(); e.stopPropagation() }}
                  onDrop={handleRfmsDrop}
                  onClick={() => rfmsInputRef.current?.click()}
                >
                  <input ref={rfmsInputRef} type="file" accept=".xlsx,.xls,.csv" multiple
                         onChange={handleRfmsFileSelect} className="hidden" />

                  {stagedFiles.length === 0 ? (
                    <>
                      <div className="w-14 h-14 rounded-2xl bg-si-bright/[0.08] flex items-center justify-center mx-auto mb-4 border border-si-bright/[0.1]">
                        <FileSpreadsheet className="w-7 h-7 text-si-bright" />
                      </div>
                      <p className="text-sm font-semibold text-gray-200 mb-1">Drop RFMS file 1 of 2</p>
                      <p className="text-xs text-gray-500">Units file or Common Areas file (.xlsx)</p>
                    </>
                  ) : (
                    <>
                      <div className="w-14 h-14 rounded-2xl bg-emerald-500/[0.12] flex items-center justify-center mx-auto mb-4 border border-emerald-500/[0.2]">
                        <Upload className="w-7 h-7 text-emerald-400" />
                      </div>
                      <p className="text-sm font-semibold text-emerald-300 mb-1">
                        1 of 2 files received — drop the second file
                      </p>
                      <p className="text-xs text-gray-500">Processing starts automatically when both files are uploaded</p>
                    </>
                  )}
                </div>
              )}

              {/* Staged file indicators */}
              {stagedFiles.length > 0 && !rfmsLoading && !rfmsSuccess && (
                <div className="mt-3 space-y-2">
                  {stagedFiles.map((f, i) => (
                    <div key={i} className="flex items-center gap-2 px-3 py-2 bg-emerald-500/[0.06] border border-emerald-500/[0.15] rounded-xl text-sm">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      <span className="flex-1 truncate text-emerald-300">{f.name}</span>
                      <span className="text-xs text-gray-600">{(f.size / 1024).toFixed(0)} KB</span>
                      <button onClick={(e) => { e.stopPropagation(); removeStaged(i) }}
                        className="p-0.5 hover:bg-white/[0.06] rounded">
                        <X className="w-3.5 h-3.5 text-gray-500" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {job.materials?.length > 0 && (
                <button
                  onClick={() => setConfirmDialog({
                    title: 'Clear All Materials',
                    message: `This will delete all ${job.materials?.length || 0} materials and any associated pricing. You'll need to re-upload your RFMS files.`,
                    confirmLabel: 'Clear Materials',
                    confirmVariant: 'danger',
                    onConfirm: async () => {
                      setConfirmDialog(null)
                      await api.updateMaterials(jobId, [])
                      const updated = await api.getJob(jobId)
                      setJob(updated)
                      setRfmsSuccess(false)
                      setStagedFiles([])
                    }
                  })}
                  className="mt-3 text-xs text-gray-500 hover:text-red-400 transition-colors"
                >
                  Clear materials &amp; start over
                </button>
              )}
            </div>


            {/* Vendor Quotes Section — above materials table for discoverability */}
            {job.materials?.length > 0 && (() => {
              const unpricedCount = job.materials.filter(m => !m.unit_price || m.unit_price === 0).length
              return unpricedCount > 0 || job.quotes?.length > 0 ? (
                <div ref={quoteSectionRef} className="glass-card p-4 sm:p-6 animate-slide-up">
                  {/* Unpriced banner */}
                  {unpricedCount > 0 && (
                    <div className="flex items-center gap-3 px-4 py-3 mb-4 bg-amber-500/10 border border-amber-500/20 rounded-xl">
                      <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
                      <span className="text-sm text-amber-300">
                        <strong>{unpricedCount}</strong> of {job.materials.length} materials need vendor pricing
                      </span>
                    </div>
                  )}

                  {/* Quote Tracker — always visible when requests exist */}
                  <QuoteTracker job={job} onRefresh={loadJob} onUploadQuote={() => setQuotePanel('upload')} />

                  {/* Action buttons */}
                  {!quotePanel && (
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setQuotePanel('request')}
                        className="btn-secondary text-sm flex items-center gap-2"
                      >
                        <Copy className="w-4 h-4" />
                        Request Quotes
                      </button>
                      <button
                        onClick={() => setQuotePanel('upload')}
                        className="btn-secondary text-sm flex items-center gap-2"
                      >
                        <Upload className="w-4 h-4" />
                        Upload Vendor Response
                      </button>
                    </div>
                  )}

                  {/* Quote Upload Panel */}
                  {quotePanel === 'upload' && (
                    <div>
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-bold text-white">Upload Vendor Response</h3>
                        <button onClick={() => setQuotePanel(null)}
                          className="text-xs text-gray-500 hover:text-gray-300 transition-colors">
                          Close
                        </button>
                      </div>
                      <QuoteUpload
                        jobId={job.id}
                        api={api}
                        existingQuotes={job.quotes || []}
                        onQuotesParsed={() => loadJob()}
                        onQuotesCleared={() => loadJob()}
                      />
                    </div>
                  )}
                </div>
              ) : null
            })()}

            {/* Materials Table */}
            {job.materials?.length > 0 && (
              <div className="glass-card p-4 sm:p-6 animate-slide-up">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xs font-bold text-gray-500 uppercase tracking-[0.15em]">
                    Materials ({job.materials.length})
                  </h3>
                  <div className="flex items-center gap-2">
                    {isDirty && (
                      <span className="text-xs text-amber-400 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                        Unsaved
                      </span>
                    )}
                    <a href={api.exportMaterialsCsvUrl(jobId)} download
                       className="btn-ghost text-xs px-2.5 py-1.5 text-gray-500 hover:text-gray-300"
                       title="Export CSV">
                      <Download className="w-4 h-4" />
                      CSV
                    </a>
                    <button onClick={handleSavePricing} disabled={saving} className="btn-secondary text-sm">
                      {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                      Save
                    </button>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <MaterialsTable
                    materials={job.materials}
                    editable
                    quoteRequests={quoteRequests}
                    onUpdate={handleMaterialsUpdate}
                    onRequestQuote={(material) => {
                      setQuoteMaterial(material)
                      setQuoteCopied(false)
                    }}
                    onRequestAllQuotes={() => {
                      setQuotePanel('request')
                    }}
                    onAiEstimate={async (materialIdx) => {
                      try {
                        const result = await api.estimatePrice(job.id, materialIdx)
                        await loadJob()
                      } catch (err) {
                        console.error('AI estimate failed:', err)
                        setError(err.message)
                      }
                    }}
                  />
                </div>
              </div>
            )}

            {/* Continue to Bid */}
            {job.materials?.length > 0 && (() => {
              const unpricedCount = job.materials.filter(m => !m.unit_price || m.unit_price === 0).length
              return (
                <div className="text-center pt-2 animate-fade-in">
                  {unpricedCount > 0 && (
                    <p className="text-xs text-amber-400 mb-2">
                      All materials must be priced before generating a bid
                    </p>
                  )}
                  <button
                    onClick={async () => { if (isDirty) await handleSavePricing(); setStep('bid') }}
                    className="btn-primary"
                    disabled={unpricedCount > 0}
                  >
                    Continue to Bid Generation
                  </button>
                </div>
              )
            })()}
          </div>
        )}

        {step === 'bid' && (
          <div className="glass-card p-4 sm:p-8">
            <ProposalEditor job={job} api={api} onGoBack={() => setStep('takeoff')} />
          </div>
        )}
      </div>

      <ActivityLog jobId={job.id} />

      <ConfirmDialog {...confirmDialog} open={!!confirmDialog} onCancel={() => setConfirmDialog(null)} />

      {/* Vendor Quote Flow Modal — rendered outside animated containers to avoid transform containing block issues */}
      {quotePanel === 'request' && job && (
        <VendorQuoteFlow
          job={job}
          onClose={() => { setQuotePanel(null); setQuotePreSelectedIds(null) }}
          onQuoteRequestCreated={() => loadJob()}
        />
      )}

      {/* Single-material quote request modal */}
      {quoteMaterial && job && (() => {
        const m = quoteMaterial
        const qty = Math.round((m.installed_qty || m.order_qty || 0) * 100) / 100
        const desc = [m.item_code, m.description].filter(Boolean).join(' - ')
        const lines = [
          `Project: ${job.project_name || ''}`,
          ...(job.architect ? [`Architect: ${job.architect}`] : []),
          ...(job.designer ? [`Designer: ${job.designer}`] : []),
          ...([job.address, job.city, job.state, job.zip].filter(Boolean).length
            ? [`Location: ${[job.address, job.city, job.state, job.zip].filter(Boolean).join(', ')}`]
            : []),
          ...(job.gc_name ? [`GC: ${job.gc_name}`] : []),
          '',
          'We are bidding the above project and need pricing on the following material:',
          '',
          `• ${desc}${qty ? ` — ${qty} ${m.unit || ''}` : ''}`,
          '',
          'Please include unit pricing, freight, and lead times.',
          'Thank you!',
        ]
        const text = lines.join('\n')
        const handleCopy = async () => {
          try {
            await navigator.clipboard.writeText(text)
          } catch {
            const ta = document.createElement('textarea')
            ta.value = text
            document.body.appendChild(ta)
            ta.select()
            document.execCommand('copy')
            document.body.removeChild(ta)
          }
          setQuoteCopied(true)
          setTimeout(() => setQuoteCopied(false), 3000)
        }
        return (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setQuoteMaterial(null)}>
            <div className="bg-[#12121a] border border-white/10 rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Copy className="w-4 h-4 text-si-bright" />
                  <h3 className="text-sm font-bold text-white">Quote Request</h3>
                </div>
                <button onClick={() => setQuoteMaterial(null)} className="text-gray-500 hover:text-gray-300 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="bg-white/[0.04] border border-white/[0.06] rounded-lg px-3 py-2">
                <p className="text-sm text-gray-200 font-medium truncate">{desc}</p>
                <p className="text-xs text-gray-500 mt-0.5">{qty} {m.unit || ''}</p>
              </div>

              <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-4">
                <pre className="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">{text}</pre>
              </div>

              <button
                onClick={handleCopy}
                className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
                  quoteCopied
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                    : 'bg-gradient-to-b from-si-orange to-orange-600 text-white shadow-[0_1px_2px_rgba(0,0,0,0.4)] hover:from-orange-500 hover:to-orange-700'
                }`}
              >
                {quoteCopied ? (
                  <><CheckCircle2 className="w-4 h-4" /> Copied to Clipboard</>
                ) : (
                  <><Copy className="w-4 h-4" /> Copy Quote Request</>
                )}
              </button>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
