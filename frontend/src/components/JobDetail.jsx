import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  ArrowLeft, Building2, MapPin, User, Percent, Hash,
  Loader2, FileSpreadsheet, Save, AlertTriangle
} from 'lucide-react'
import { api } from '../api'
import StepIndicator from './StepIndicator'
import FileUpload from './FileUpload'
import MaterialsTable from './MaterialsTable'
import QuoteUpload from './QuoteUpload'
import BidPreview from './BidPreview'

export default function JobDetail() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(true)
  const [step, setStep] = useState('info')
  const [rfmsLoading, setRfmsLoading] = useState(false)
  const [rfmsSuccess, setRfmsSuccess] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const loadJob = async () => {
    try {
      const data = await api.getJob(jobId)
      setJob(data)
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

  const handleRfmsUpload = async (file) => {
    setRfmsLoading(true)
    setError(null)
    try {
      await api.uploadRFMS(jobId, file)
      setRfmsSuccess(true)
      const updated = await api.getJob(jobId)
      setJob(updated)
      setTimeout(() => setStep('pricing'), 800)
    } catch (err) {
      setError(err.message)
    } finally {
      setRfmsLoading(false)
    }
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
          <h1 className="text-2xl font-extrabold text-white tracking-tight">{job.project_name}</h1>
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
          </div>
        </div>
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
                Upload your RFMS pivot table Excel export. We'll parse materials, quantities, and auto-calculate waste factors.
              </p>
              <FileUpload
                accept=".xlsx,.xls,.csv"
                label="Drop RFMS Excel File Here"
                description="Supports .xlsx, .xls, and .csv pivot table exports"
                icon={FileSpreadsheet}
                onUpload={handleRfmsUpload}
                loading={rfmsLoading}
                success={rfmsSuccess || job.materials?.length > 0}
                successMessage={`${job.materials?.length || 0} materials parsed with waste factors applied`}
              />
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
                <button onClick={() => setStep('info')} className="btn-primary">
                  <ArrowLeft className="w-4 h-4" /> Go to Step 1
                </button>
              </div>
            ) : (
            <>
            <div className="glass-card p-8">
              <h2 className="text-lg font-bold text-white mb-1">Vendor Quotes</h2>
              <p className="text-sm text-gray-500 mb-6">
                Upload vendor quote PDFs or emails. Our AI will extract product names and pricing.
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
              Calculate sundries, labor, and freight — then generate your professional PDF bid.
            </p>
            <BidPreview job={job} api={api} onGoBack={() => setStep('pricing')} />
          </div>
        )}
      </div>
    </div>
  )
}
