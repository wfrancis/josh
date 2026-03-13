import { useState, useEffect } from 'react'
import {
  Settings, FileSpreadsheet, HardHat, Wrench, Info,
  Key, Brain, Layers, Loader2, Check, Eye, EyeOff,
  AlertTriangle
} from 'lucide-react'
import { api } from '../api'
import FileUpload from './FileUpload'

export default function SettingsPage() {
  const [laborLoading, setLaborLoading] = useState(false)
  const [laborSuccess, setLaborSuccess] = useState(false)
  const [laborError, setLaborError] = useState(null)
  const [laborCatalog, setLaborCatalog] = useState(null)
  const [catalogLoading, setCatalogLoading] = useState(true)

  // AI Settings state
  const [settingsLoading, setSettingsLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [apiKey, setApiKey] = useState('')
  const [apiKeySet, setApiKeySet] = useState(false)
  const [apiKeyMasked, setApiKeyMasked] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [editingKey, setEditingKey] = useState(false)
  const [model, setModel] = useState('gpt-5-mini')
  const [multiPassCount, setMultiPassCount] = useState(2)

  // Load settings on mount
  useEffect(() => {
    api.getSettings()
      .then(data => {
        setApiKeySet(data.openai_api_key_set)
        setApiKeyMasked(data.openai_api_key_masked)
        setModel(data.openai_model || 'gpt-5-mini')
        setMultiPassCount(data.multi_pass_count || 2)
      })
      .catch(console.error)
      .finally(() => setSettingsLoading(false))
  }, [])

  // Load labor catalog on mount
  useEffect(() => {
    api.getLaborCatalog()
      .then(data => setLaborCatalog(data))
      .catch(() => setLaborCatalog({ entries: [], count: 0 }))
      .finally(() => setCatalogLoading(false))
  }, [])

  const handleLaborUpload = async (file) => {
    setLaborLoading(true)
    setLaborError(null)
    try {
      await api.uploadLaborCatalog(file)
      setLaborSuccess(true)
      // Refresh the catalog preview
      const data = await api.getLaborCatalog()
      setLaborCatalog(data)
    } catch (err) {
      setLaborError(err.message)
    } finally {
      setLaborLoading(false)
    }
  }

  const handleSaveSettings = async () => {
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      const payload = {
        openai_model: model,
        multi_pass_count: multiPassCount,
      }
      // Only send API key if user actively edited it
      if (editingKey && apiKey) {
        payload.openai_api_key = apiKey
      }
      const result = await api.updateSettings(payload)
      setApiKeySet(result.openai_api_key_set)
      setApiKeyMasked(result.openai_api_key_masked)
      setEditingKey(false)
      setApiKey('')
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
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
        <p className="text-sm text-gray-500 mt-1">Defaults and catalogs</p>
      </div>

      <div className="space-y-6">
        {/* ── AI Configuration ─────────────────────────── */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-si-orange/10 flex items-center justify-center flex-shrink-0">
              <Brain className="w-5 h-5 text-si-orange" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">AI Configuration</h2>
              <p className="text-sm text-gray-500 mt-1">
                Configure OpenAI API key, model selection, and multi-pass accuracy settings.
              </p>
            </div>
          </div>

          {settingsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 text-gray-500 animate-spin" />
            </div>
          ) : (
            <div className="space-y-6">
              {/* API Key */}
              <div>
                <label className="label flex items-center gap-2">
                  <Key className="w-3.5 h-3.5" />
                  OpenAI API Key
                </label>
                {apiKeySet && !editingKey ? (
                  <div className="flex items-center gap-3">
                    <div className="input flex-1 flex items-center gap-2 text-gray-400 font-mono text-sm">
                      {showApiKey ? apiKeyMasked : '••••••••••••••••••••'}
                      <button onClick={() => setShowApiKey(!showApiKey)} className="ml-auto text-gray-500 hover:text-gray-300">
                        {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                    <button
                      onClick={() => setEditingKey(true)}
                      className="btn-ghost text-sm px-4 py-2.5"
                    >
                      Change
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <input
                      type="password"
                      className="input flex-1 font-mono text-sm"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="sk-..."
                      autoComplete="off"
                    />
                    {editingKey && (
                      <button
                        onClick={() => { setEditingKey(false); setApiKey('') }}
                        className="btn-ghost text-sm px-4 py-2.5"
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                )}
                <p className="text-xs text-gray-600 mt-2">
                  Your API key is stored securely on the server and never exposed to the browser.
                </p>
              </div>

              {/* Model Selection */}
              <div>
                <label className="label flex items-center gap-2">
                  <Brain className="w-3.5 h-3.5" />
                  AI Model
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setModel('gpt-5-mini')}
                    className={`p-4 rounded-xl border text-left transition-all ${
                      model === 'gpt-5-mini'
                        ? 'bg-si-bright/10 border-si-bright/30 ring-1 ring-si-bright/20'
                        : 'bg-white/[0.03] border-white/[0.06] hover:border-white/[0.12]'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <div className={`w-3 h-3 rounded-full ${model === 'gpt-5-mini' ? 'bg-si-bright' : 'bg-white/10'}`} />
                      <span className="text-sm font-semibold text-white">GPT-5 Mini</span>
                    </div>
                    <p className="text-xs text-gray-500 leading-relaxed">
                      Fast & cost-efficient. Great for standard quote parsing.
                    </p>
                  </button>
                  <button
                    onClick={() => setModel('gpt-5.4')}
                    className={`p-4 rounded-xl border text-left transition-all ${
                      model === 'gpt-5.4'
                        ? 'bg-si-orange/10 border-si-orange/30 ring-1 ring-si-orange/20'
                        : 'bg-white/[0.03] border-white/[0.06] hover:border-white/[0.12]'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <div className={`w-3 h-3 rounded-full ${model === 'gpt-5.4' ? 'bg-si-orange' : 'bg-white/10'}`} />
                      <span className="text-sm font-semibold text-white">GPT-5.4</span>
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-si-orange/15 text-si-orange uppercase tracking-wider">
                        Flagship
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 leading-relaxed">
                      Most capable model. Best accuracy for complex quotes.
                    </p>
                  </button>
                </div>
              </div>

              {/* Multi-Pass Count */}
              <div>
                <label className="label flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5" />
                  Multi-Pass Accuracy
                </label>
                <p className="text-xs text-gray-500 mb-3 leading-relaxed">
                  Run the AI multiple times on each quote and take the median price. More passes = higher accuracy but slower and more API usage.
                </p>
                <div className="flex items-center gap-2">
                  {[1, 2, 3, 4, 5].map(n => (
                    <button
                      key={n}
                      onClick={() => setMultiPassCount(n)}
                      className={`w-12 h-12 rounded-xl flex items-center justify-center text-sm font-bold transition-all ${
                        multiPassCount === n
                          ? 'bg-si-bright/15 border border-si-bright/30 text-si-bright ring-1 ring-si-bright/20'
                          : 'bg-white/[0.03] border border-white/[0.06] text-gray-500 hover:text-gray-300 hover:border-white/[0.12]'
                      }`}
                    >
                      {n}x
                    </button>
                  ))}
                </div>
                <div className="mt-2 text-xs text-gray-600">
                  {multiPassCount === 1 && 'Single pass — fastest, no redundancy check'}
                  {multiPassCount === 2 && '2 passes — recommended balance of accuracy & speed'}
                  {multiPassCount === 3 && '3 passes — higher accuracy, slower'}
                  {multiPassCount === 4 && '4 passes — high accuracy'}
                  {multiPassCount === 5 && '5 passes — maximum accuracy, slowest'}
                </div>
              </div>

              {/* Save Button */}
              <div className="flex items-center gap-3 pt-2">
                <button
                  onClick={handleSaveSettings}
                  disabled={saving}
                  className="btn-primary"
                >
                  {saving ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>
                  ) : saveSuccess ? (
                    <><Check className="w-4 h-4" /> Saved</>
                  ) : (
                    'Save AI Settings'
                  )}
                </button>
                {saveError && (
                  <span className="text-sm text-red-400 flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {saveError}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Labor Catalog ─────────────────────────────── */}
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
            onReset={() => setLaborSuccess(false)}
            loading={laborLoading}
            success={laborSuccess}
            successMessage="Labor catalog uploaded successfully"
          />
          {laborError && (
            <div className="mt-3 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
              {laborError}
            </div>
          )}

          {/* Labor Catalog Preview */}
          {catalogLoading ? (
            <div className="mt-4 flex items-center justify-center py-6">
              <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
            </div>
          ) : laborCatalog && laborCatalog.count > 0 ? (
            <div className="mt-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-bold text-gray-500 uppercase tracking-[0.12em]">
                  Loaded Rates
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400">
                  {laborCatalog.count} entries
                </span>
              </div>
              <div className="overflow-x-auto max-h-64 overflow-y-auto rounded-xl border border-white/[0.06]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900/95 backdrop-blur-sm">
                    <tr className="border-b border-white/[0.06]">
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Type</th>
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Description</th>
                      <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider">Cost</th>
                      <th className="py-2 px-3 text-left font-bold text-gray-500 uppercase tracking-wider">Unit</th>
                      <th className="py-2 px-3 text-right font-bold text-gray-500 uppercase tracking-wider">Markup</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.03]">
                    {laborCatalog.entries.map((entry, i) => (
                      <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-2 px-3 text-gray-300 font-medium">{entry.labor_type}</td>
                        <td className="py-2 px-3 text-gray-400">{entry.description}</td>
                        <td className="py-2 px-3 text-right tabular-nums text-gray-300">
                          ${(entry.cost || 0).toFixed(2)}
                        </td>
                        <td className="py-2 px-3 text-gray-500">{entry.unit}</td>
                        <td className="py-2 px-3 text-right tabular-nums text-gray-500">
                          {entry.gpm_markup ? `${(entry.gpm_markup * 100).toFixed(0)}%` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : !catalogLoading && (
            <div className="mt-4 text-center py-6 bg-white/[0.02] rounded-xl border border-white/[0.04]">
              <HardHat className="w-8 h-8 text-gray-600 mx-auto mb-2 opacity-40" />
              <p className="text-xs text-gray-500">No labor catalog loaded yet</p>
            </div>
          )}
        </div>

        {/* ── Business Rules Info ──────────────────────── */}
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
              These are configured in the server config. Edit waste factors, sundry rules, or freight rates there.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
