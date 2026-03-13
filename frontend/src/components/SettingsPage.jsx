import { useState } from 'react'
import {
  Settings, Upload, FileSpreadsheet, CheckCircle2,
  HardHat, Wrench, Info
} from 'lucide-react'
import { api } from '../api'
import FileUpload from './FileUpload'

export default function SettingsPage() {
  const [laborLoading, setLaborLoading] = useState(false)
  const [laborSuccess, setLaborSuccess] = useState(false)
  const [laborError, setLaborError] = useState(null)

  const handleLaborUpload = async (file) => {
    setLaborLoading(true)
    setLaborError(null)
    try {
      await api.uploadLaborCatalog(file)
      setLaborSuccess(true)
    } catch (err) {
      setLaborError(err.message)
    } finally {
      setLaborLoading(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-10">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-extrabold text-white tracking-tight flex items-center gap-3">
          <Settings className="w-6 h-6 text-gray-400" />
          Settings
        </h1>
        <p className="text-sm text-gray-500 mt-1">Configure your bid tool defaults and catalogs</p>
      </div>

      <div className="space-y-6">
        {/* Labor Catalog */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-violet-500/10 flex items-center justify-center flex-shrink-0">
              <HardHat className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Labor Catalog</h2>
              <p className="text-sm text-gray-500 mt-1">
                Upload your labor rate catalog Excel file. This sets the per-unit labor rates used when generating bids.
              </p>
            </div>
          </div>
          <FileUpload
            accept=".xlsx,.xls,.csv"
            label="Upload Labor Catalog"
            description="Excel file with labor rates per material type"
            icon={FileSpreadsheet}
            onUpload={handleLaborUpload}
            loading={laborLoading}
            success={laborSuccess}
            successMessage="Labor catalog uploaded successfully"
          />
          {laborError && (
            <div className="mt-3 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
              {laborError}
            </div>
          )}
        </div>

        {/* Business Rules Info */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-5">
            <div className="w-11 h-11 rounded-xl bg-si-bright/10 flex items-center justify-center flex-shrink-0">
              <Wrench className="w-5 h-5 text-si-bright" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Business Rules</h2>
              <p className="text-sm text-gray-500 mt-1">
                Built-in calculations for waste factors, sundries, and freight.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'Waste Factors', desc: 'Auto-applied per material type (carpet, LVT, tile, etc.)' },
              { label: 'Sundry Rules', desc: 'Adhesive, seam sealer, transition strips auto-calculated' },
              { label: 'Freight Rates', desc: 'Per-unit shipping costs based on material category' },
              { label: 'Bid Templates', desc: 'Pre-written scope descriptions for each bundle type' },
            ].map(item => (
              <div key={item.label} className="p-4 bg-white/[0.03] rounded-xl border border-white/[0.04]">
                <div className="text-sm font-semibold text-gray-200 mb-1">{item.label}</div>
                <div className="text-xs text-gray-500 leading-relaxed">{item.desc}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-start gap-2 px-4 py-3 bg-si-bright/[0.04] border border-si-bright/10 rounded-xl">
            <Info className="w-4 h-4 text-si-bright flex-shrink-0 mt-0.5" />
            <p className="text-xs text-gray-400 leading-relaxed">
              Business rules are configured server-side. Contact your admin to adjust waste factors,
              sundry rules, or freight rates.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
