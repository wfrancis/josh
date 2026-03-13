import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  ArrowLeft, Building2, MapPin, User, Percent, Hash,
  Loader2, FileSpreadsheet, Save, AlertTriangle, Trash2,
  StickyNote, ChevronDown, ChevronUp, Cpu, CheckCircle2, X, Upload
} from 'lucide-react'
import { api } from '../api'
import StepIndicator from './StepIndicator'

import MaterialsTable from './MaterialsTable'
import QuoteUpload from './QuoteUpload'
import BidPreview from './BidPreview'
import StatusBadge, { getJobStatus } from './StatusBadge'

export default function JobDetail() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(true)
  const [step, setStep] = useState('info')
  const [rfmsLoading, setRfmsLoading] = useState(false)
  const [rfmsSuccess, setRfmsSuccess] = useState(false)
  const [stagedFiles, setStagedFiles] = useState([])
  const rfmsInputRef = useRef(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [notesOpen, setNotesOpen] = useState(false)
  const [notes, setNotes] = useState('')
  const [aiSettings, setAiSettings] = useState(null)

  const loadJob = async () => {
    try {
      const data = await api.getJob(jobId)
      setJob(data)
      setNotes(data.notes || '')
      setNotesOpen(!!data.notes)
      if (data.bundles?.length > 0) setStep('bid')
      else if (data.materials?.some(m => m.unit_price > 0)) setStep('pricing')
      else if (data.materials?.length > 0) setStep('pricing')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadJob() }, [jobId])
  useEffect(() => { api.getSettings().then(setAiSettings).catch(() => {}) }, [])

  const handleRfmsUpload = async (fileList) => {
    setRfmsLoading(true)
    setError(null)
    try {
      await api.uploadRFMS(jobId, fileList)
      const updated = await api.getJob(jobId)
      setJob(updated)
      setRfmsSuccess(true)
      setStagedFiles([])
      setTimeout(() => setStep('pricing'), 800)
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
  }

  const handleSavePricing = async () => {
    setSaving(true)
    setError(null)
    try {
      const result = await api.updateMaterials(jobId, job.materials)
      setJob(j => ({ ...j, materials: result.materials }))
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const getCompletedSteps = () => {
    const completed = []
    if (job?.materials?.length > 0) completed.push('info')
    if (job?.materials?.some(m => m.unit_price > 0)) completed.push('pricing')
    if (job?.bundles?.length > 0) completed.push('bid')
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
    <div className="max-w-5xl mx-auto px-8 py-8">
      {/* Header */}
      <div className="flex items-start gap-4 mb-8">
        <button onClick={() => navigate('/')} className="btn-ghost p-2 mt-0.5">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold text-white tracking-tight">{job.project_name}</h1>
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
                <Percent className="w-3.5 h-3.5" /> {(job.tax_rate * 100).toFixed(1)}% tax
              </span>
            )}
            {job.unit_count > 0 && (
              <span className="flex items-center gap-1.5">
                <Hash className="w-3.5 h-3.5" /> {job.unit_count} units
              </span>
            )}
            {aiSettings && (
              <span className="flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5" /> {aiSettings.openai_model} · {aiSettings.multi_pass_count}x
              </span>
            )}
          </div>
        </div>
        <button
          onClick={() => {
            if (window.confirm(`Delete "${job.project_name}"? This cannot be undone.`)) {
              api.deleteJob(job.id).then(() => navigate('/')).catch(err => setError(err.message))
            }
          }}
          className="btn-ghost p-2 mt-0.5 text-gray-500 hover:text-red-400 hover:bg-red-500/10"
          title="Delete job"
        >
          <Trash2 className="w-5 h-5" />
        </button>
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
      <div className="glass-card px-6 py-4 mb-8">
        <StepIndicator current={step} onStepClick={setStep} completedSteps={getCompletedSteps()} />
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
        {step === 'info' && (
          <div className="space-y-6">
            <div className="glass-card p-8">
              <h2 className="text-lg font-bold text-white mb-1">Upload RFMS Takeoff</h2>
              <p className="text-sm text-gray-500 mb-6">
                Upload both RFMS pivot table files (.xlsx). Materials and waste factors are parsed automatically.
              </p>

              {rfmsSuccess ? (
                <div className="upload-zone !border-emerald-500/30 !bg-emerald-500/[0.04] text-center">
                  <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
                  <p className="text-sm font-medium text-emerald-300">
                    {job.materials?.length || 0} materials parsed with waste factors applied
                  </p>
                  <button
                    onClick={() => { setStagedFiles([]); setRfmsSuccess(false) }}
                    className="mt-2 text-xs text-emerald-500 hover:text-emerald-400 underline"
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
                  onClick={async () => {
                    if (!window.confirm('Clear all materials and start over?')) return
                    await api.updateMaterials(jobId, [])
                    const updated = await api.getJob(jobId)
                    setJob(updated)
                    setRfmsSuccess(false)
                    setStagedFiles([])
                  }}
                  className="mt-3 text-xs text-gray-500 hover:text-red-400 transition-colors"
                >
                  Clear materials &amp; start over
                </button>
              )}
            </div>

            {job.materials?.length > 0 && (
              <div className="glass-card p-6 animate-slide-up">
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-[0.15em] mb-4">
                  Materials ({job.materials.length})
                </h3>
                <MaterialsTable materials={job.materials} readOnly />
              </div>
            )}
          </div>
        )}

        {step === 'pricing' && (
          <div className="space-y-6">
            {!job.materials?.length ? (
              <div className="text-center py-16 glass-card">
                <FileSpreadsheet className="w-12 h-12 text-gray-600 mx-auto mb-4" />
                <p className="text-gray-400 font-medium">Upload your RFMS takeoff first</p>
                <p className="text-sm text-gray-600 mt-1 mb-4">Materials need to be imported before adding pricing</p>
                <button onClick={() => setStep('info')}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-si-bright/10 border border-si-bright/20 text-si-bright text-sm font-medium hover:bg-si-bright/15 transition-colors">
                  <ArrowLeft className="w-4 h-4" /> Go to Step 1
                </button>
              </div>
            ) : (
            <>
            <div className="glass-card p-8">
              <h2 className="text-lg font-bold text-white mb-1">Vendor Quotes</h2>
              <p className="text-sm text-gray-500 mb-6">
                Upload vendor quote PDFs. Pricing will be extracted automatically.
              </p>
              <QuoteUpload jobId={jobId} api={api} />
            </div>

            {job.materials?.length > 0 && (
              <div className="glass-card p-6">
                <div className="flex items-center justify-between mb-5">
                  <h3 className="text-xs font-bold text-gray-500 uppercase tracking-[0.15em]">
                    Set Material Pricing
                  </h3>
                  <button onClick={handleSavePricing} disabled={saving} className="btn-secondary text-sm">
                    {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                    Save Prices
                  </button>
                </div>
                <MaterialsTable materials={job.materials} onUpdate={handleMaterialsUpdate} />
              </div>
            )}

            {job.materials?.some(m => m.unit_price > 0) && (
              <div className="text-center pt-2 animate-fade-in">
                <button
                  onClick={async () => { await handleSavePricing(); setStep('bid') }}
                  className="btn-primary"
                >
                  Save & Continue to Bid Generation
                </button>
              </div>
            )}
            </>
            )}
          </div>
        )}

        {step === 'bid' && (
          <div className="glass-card p-8">
            <h2 className="text-lg font-bold text-white mb-1">Generate Bid</h2>
            <p className="text-sm text-gray-500 mb-6">
              Calculate sundries, labor, and freight, then generate the bid PDF.
            </p>
            <BidPreview job={job} api={api} onGoBack={() => setStep('pricing')} />
          </div>
        )}
      </div>
    </div>
  )
}
