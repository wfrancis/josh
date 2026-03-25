import { useState, useEffect } from 'react'
import {
  Settings, Info,
  Key, Brain, Layers, Loader2, Check, Eye, EyeOff,
  AlertTriangle, Mail, Server, Bell, ToggleLeft, ToggleRight
} from 'lucide-react'
import { api } from '../api'

export default function SettingsPage() {
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

  // Bid folder state
  const [bidFolderPath, setBidFolderPath] = useState('')

  // Email automation state
  const [emailEnabled, setEmailEnabled] = useState(false)
  const [emailSaving, setEmailSaving] = useState(false)
  const [emailSaveSuccess, setEmailSaveSuccess] = useState(false)
  const [emailConfig, setEmailConfig] = useState({
    smtp_host: '', smtp_port: '587', imap_host: '', imap_port: '993',
    email_address: '', email_password: '', sender_name: '', sender_signature: '',
    notify_quote_received: true, notify_all_quotes_received: true,
  })

  // Load settings on mount
  useEffect(() => {
    api.getSettings()
      .then(data => {
        setApiKeySet(data.openai_api_key_set)
        setApiKeyMasked(data.openai_api_key_masked)
        setModel(data.openai_model || 'gpt-5-mini')
        setMultiPassCount(data.multi_pass_count || 2)
        // Bid folder path
        if (data.bid_folder_path) setBidFolderPath(data.bid_folder_path)
        // Email automation settings
        if (data.email_automation_enabled === 'true') setEmailEnabled(true)
        if (data.email_config) {
          try { setEmailConfig(prev => ({ ...prev, ...JSON.parse(data.email_config) })) } catch {}
        }
      })
      .catch(console.error)
      .finally(() => setSettingsLoading(false))
  }, [])

  const handleSaveSettings = async () => {
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      const payload = {
        openai_model: model,
        multi_pass_count: multiPassCount,
        bid_folder_path: bidFolderPath,
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
    <div className="max-w-3xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
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

              {/* Bid Folder Path */}
              <div className="space-y-2">
                <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
                  Dropbox Bid Folder Path
                </label>
                <input
                  type="text"
                  value={bidFolderPath}
                  onChange={(e) => setBidFolderPath(e.target.value)}
                  placeholder="C:\Users\...\001-Bid Folder"
                  className="input w-full"
                />
                <div className="text-xs text-gray-500">
                  Local path to your Dropbox bid folder. Used by the Dropbox quote scanner.
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
                    'Save Settings'
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

        {/* ── Quote Email Automation ──────────────────── */}
        <div className="glass-card p-8">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-blue-500/10 flex items-center justify-center flex-shrink-0">
              <Mail className="w-5 h-5 text-blue-400" />
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-bold text-white">Quote Email Automation</h2>
              <p className="text-sm text-gray-500 mt-1">
                When enabled, AI will compose and send quote requests, and monitor your inbox for vendor responses.
              </p>
            </div>
          </div>

          <div className="space-y-5">
            {/* SMTP Settings */}
            <div>
              <label className="label flex items-center gap-2">
                <Server className="w-3.5 h-3.5" />
                SMTP (Sending Emails)
              </label>
              <div className="grid grid-cols-2 gap-3">
                <input className="input" placeholder="SMTP server (e.g., smtp.gmail.com)"
                  value={emailConfig.smtp_host}
                  onChange={e => setEmailConfig(c => ({ ...c, smtp_host: e.target.value }))} />
                <input className="input" placeholder="Port (587)" type="number"
                  value={emailConfig.smtp_port}
                  onChange={e => setEmailConfig(c => ({ ...c, smtp_port: e.target.value }))} />
              </div>
            </div>

            {/* IMAP Settings */}
            <div>
              <label className="label flex items-center gap-2">
                <Server className="w-3.5 h-3.5" />
                IMAP (Monitoring Inbox)
              </label>
              <div className="grid grid-cols-2 gap-3">
                <input className="input" placeholder="IMAP server (e.g., imap.gmail.com)"
                  value={emailConfig.imap_host}
                  onChange={e => setEmailConfig(c => ({ ...c, imap_host: e.target.value }))} />
                <input className="input" placeholder="Port (993)" type="number"
                  value={emailConfig.imap_port}
                  onChange={e => setEmailConfig(c => ({ ...c, imap_port: e.target.value }))} />
              </div>
            </div>

            {/* Credentials */}
            <div>
              <label className="label flex items-center gap-2">
                <Key className="w-3.5 h-3.5" />
                Email Credentials
              </label>
              <div className="grid grid-cols-2 gap-3">
                <input className="input" placeholder="Email address"
                  value={emailConfig.email_address}
                  onChange={e => setEmailConfig(c => ({ ...c, email_address: e.target.value }))} />
                <input className="input" type="password" placeholder="App password"
                  value={emailConfig.email_password}
                  onChange={e => setEmailConfig(c => ({ ...c, email_password: e.target.value }))} />
              </div>
            </div>

            {/* Sender Info */}
            <div>
              <label className="label">Sender Name</label>
              <input className="input" placeholder="e.g., Josh Dann"
                value={emailConfig.sender_name}
                onChange={e => setEmailConfig(c => ({ ...c, sender_name: e.target.value }))} />
            </div>
            <div>
              <label className="label">Email Signature</label>
              <textarea className="input min-h-[80px] resize-y" placeholder="Company signature block..."
                value={emailConfig.sender_signature}
                onChange={e => setEmailConfig(c => ({ ...c, sender_signature: e.target.value }))} />
            </div>

            {/* Notifications */}
            <div>
              <label className="label flex items-center gap-2">
                <Bell className="w-3.5 h-3.5" />
                Notifications
              </label>
              <div className="space-y-2">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input type="checkbox" checked={emailConfig.notify_quote_received}
                    onChange={e => setEmailConfig(c => ({ ...c, notify_quote_received: e.target.checked }))}
                    className="rounded border-gray-600 bg-transparent text-si-bright focus:ring-si-bright/40" />
                  <span className="text-sm text-gray-300">Notify when a vendor quote is received</span>
                </label>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input type="checkbox" checked={emailConfig.notify_all_quotes_received}
                    onChange={e => setEmailConfig(c => ({ ...c, notify_all_quotes_received: e.target.checked }))}
                    className="rounded border-gray-600 bg-transparent text-si-bright focus:ring-si-bright/40" />
                  <span className="text-sm text-gray-300">Notify when all quotes received for a job</span>
                </label>
              </div>
            </div>

            {/* Enable Toggle */}
            {(() => {
              const canEnable = emailConfig.smtp_host && emailConfig.imap_host &&
                emailConfig.email_address && emailConfig.email_password
              return (
                <div className={`p-4 rounded-xl border ${emailEnabled ? 'border-emerald-500/30 bg-emerald-500/[0.04]' : 'border-white/[0.06] bg-white/[0.02]'}`}>
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-sm font-semibold text-white">Enable Email Automation</span>
                      {!canEnable && (
                        <p className="text-xs text-amber-400 mt-1">Fill in SMTP, IMAP, email, and password to enable</p>
                      )}
                    </div>
                    <button
                      disabled={!canEnable}
                      onClick={() => setEmailEnabled(!emailEnabled)}
                      className={`transition-colors ${!canEnable ? 'opacity-30 cursor-not-allowed' : 'cursor-pointer'}`}
                    >
                      {emailEnabled
                        ? <ToggleRight className="w-10 h-10 text-emerald-400" />
                        : <ToggleLeft className="w-10 h-10 text-gray-600" />
                      }
                    </button>
                  </div>
                </div>
              )
            })()}

            {/* Save Email Settings */}
            <button
              onClick={async () => {
                setEmailSaving(true)
                try {
                  await api.updateSettings({
                    email_automation_enabled: emailEnabled ? 'true' : 'false',
                    email_config: JSON.stringify(emailConfig),
                  })
                  setEmailSaveSuccess(true)
                  setTimeout(() => setEmailSaveSuccess(false), 3000)
                } catch (err) {
                  setSaveError(err.message)
                } finally {
                  setEmailSaving(false)
                }
              }}
              disabled={emailSaving}
              className="btn-primary"
            >
              {emailSaving ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>
              ) : emailSaveSuccess ? (
                <><Check className="w-4 h-4" /> Saved</>
              ) : (
                'Save Email Settings'
              )}
            </button>
          </div>
        </div>

        {/* ── Internal Rates Link ──────────────────────── */}
        <div className="glass-card p-6">
          <div className="flex items-center gap-3 text-gray-400">
            <Info className="w-4 h-4 text-si-bright flex-shrink-0" />
            <p className="text-sm">
              Labor rates, material pricing, waste factors, sundries, and freight are managed on the{' '}
              <a href="/internal-rates" className="text-si-bright hover:underline font-medium">Internal Rates</a> page.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
