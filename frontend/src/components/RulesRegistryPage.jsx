import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle, Archive, BookOpen, CheckCircle2, ClipboardCheck, Filter, History,
  Loader2, Mic, MicOff, Pencil, PlayCircle, Plus, RefreshCw, Save, Search, ShieldCheck,
  SlidersHorizontal, Wand2, X
} from 'lucide-react'
import { api } from '../api'

const ALL = 'all'
const FALLBACK_STAGES = ['classification', 'pricing', 'sundry', 'labor', 'proposal', 'audit']
const FALLBACK_STATUSES = ['draft', 'approved', 'implemented', 'tested', 'active', 'disabled', 'archived', 'deprecated']
const FALLBACK_CATEGORIES = ['material', 'pricing', 'labor', 'sundry', 'freight', 'tax', 'proposal']

const EMPTY_FORM = {
  rule_id: '',
  name: '',
  category: 'material',
  stage: 'classification',
  status: 'draft',
  priority: 0,
  source: 'Josh lesson',
  description: '',
  condition_json: '{}',
  action_json: '{}',
  effective_from: '',
  effective_to: '',
  implementation_ref: '',
  test_ref: '',
  notes: '',
  changed_by: 'Josh',
  change_note: '',
}

function normalizeRules(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.rules)) return data.rules
  if (Array.isArray(data?.items)) return data.items
  if (Array.isArray(data?.data)) return data.data
  return []
}

function normalizeVersions(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.versions)) return data.versions
  return []
}

function normalizeRulesets(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.versions)) return data.versions
  return []
}

function uniqueFrom(rules, field, fallback) {
  const values = new Set(fallback)
  rules.forEach((rule) => {
    const value = rule?.[field]
    if (value) values.add(String(value))
  })
  return [...values].sort((a, b) => a.localeCompare(b))
}

function labelize(value) {
  if (!value) return 'Unspecified'
  return String(value).replace(/[_-]/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

function shortDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function slugify(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '.')
    .replace(/^\.+|\.+$/g, '')
}

function statusClass(status) {
  const key = String(status || '').toLowerCase()
  if (key === 'active' || key === 'enabled') return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/15'
  if (key === 'tested') return 'bg-cyan-500/10 text-cyan-300 border-cyan-500/15'
  if (key === 'implemented' || key === 'approved') return 'bg-blue-500/10 text-blue-300 border-blue-500/15'
  if (key === 'draft') return 'bg-amber-500/10 text-amber-400 border-amber-500/15'
  if (key === 'disabled' || key === 'inactive') return 'bg-gray-500/10 text-gray-500 border-gray-500/15'
  if (key === 'archived') return 'bg-blue-500/10 text-blue-300 border-blue-500/15'
  return 'bg-red-500/10 text-red-400 border-red-500/15'
}

function summarizeRule(rule) {
  return rule?.summary || rule?.description || rule?.intent || rule?.name || 'No description provided.'
}

function parseJsonLike(value) {
  if (!value) return {}
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return {}
  }
}

function listify(values) {
  if (!Array.isArray(values)) return ''
  return values.map((item) => labelize(item)).join(', ')
}

function plainWhen(rule) {
  const condition = parseJsonLike(rule?.condition_json || rule?.conditions || rule?.when || rule?.match || rule?.criteria)
  const parts = []

  if (condition.material_type_in?.length) parts.push(`when the material type is ${listify(condition.material_type_in)}`)
  if (condition.material_type) parts.push(`when the material type is ${labelize(condition.material_type)}`)
  if (condition.item_code_prefix_in?.length) parts.push(`when the item code starts with ${condition.item_code_prefix_in.join(', ')}`)
  if (condition.tile_min_edge_inches_lte != null) parts.push(`when the smallest parsed tile edge is ${condition.tile_min_edge_inches_lte} inches or less`)
  if (condition.parsed_tile_dimensions_required) parts.push('when parsed tile dimensions are available')
  if (condition.tax_rate_gt != null) parts.push('when sales tax is turned on')
  if (condition.proposal_data_contains_any?.length) parts.push('when the proposal already has saved deletion choices')
  if (condition.description_contains_mm_thickness) parts.push('when the description includes sound mat thickness')
  if (condition.company_rates_key) parts.push(`when ${labelize(condition.company_rates_key)} rates are saved`)

  if (parts.length === 0) return 'Uses the saved matching conditions for this rule.'
  return parts.join(' and ').replace(/^when /, 'When ') + '.'
}

function plainAction(rule) {
  const action = parseJsonLike(rule?.action_json || rule?.actions || rule?.then || rule?.apply || rule?.outputs)
  if (action.set && typeof action.set === 'object') {
    const values = Object.entries(action.set).map(([key, value]) => {
      const label = labelize(String(key).replace(/^is_/, ''))
      return `${label} to ${value === true ? 'yes' : value === false ? 'no' : value}`
    })
    return `Sets ${values.join(', ')}.`
  }
  if (action.taxable_components?.length) return `Taxes ${listify(action.taxable_components)} and excludes ${listify(action.exclude_components || [])}.`
  if (action.tier_order?.length || action.tiers?.length) return 'Chooses the matching labor tier before calculating labor.'
  if (action.preserve_deleted_flags_on_regenerate) return 'Keeps deleted bundles and deleted materials from coming back when the proposal is regenerated.'
  if (action.load_sundry_rules_from) return 'Uses saved company sundry rules first, then falls back to the default setup.'
  return 'Applies the saved action for this rule.'
}

function plainExample(rule) {
  const when = plainWhen(rule)
  const action = plainAction(rule)
  if (rule?.rule_id?.includes('mosaic')) return 'If RFMS sends a tile like 2x12, Josh treats it as mosaic instead of regular field tile.'
  if (rule?.rule_id?.includes('tax_excludes_labor')) return 'If the proposal includes labor and material, tax is calculated on material-side dollars, not labor.'
  if (rule?.rule_id?.includes('deleted_bundles')) return 'If Josh removed a bundle, regenerating the proposal will not silently add it back.'
  return `${when} ${action}`.trim()
}

function ruleAppliesTo(rule) {
  return [rule?.stage, rule?.category].filter(Boolean).map(labelize).join(' · ') || 'Estimating'
}

function isActiveStatus(status) {
  const key = String(status || '').toLowerCase()
  return key === 'active' || key === 'enabled'
}

function jsonText(value) {
  if (value == null || value === '') return '{}'
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  return JSON.stringify(value, null, 2)
}

function formatWhen(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function SelectFilter({ icon: Icon, label, value, values, onChange }) {
  const allLabel = label === 'status' ? 'On / Off' : label
  return (
    <label className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2">
      <Icon className="w-4 h-4 text-gray-600" />
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="bg-transparent text-xs text-gray-300 focus:outline-none"
      >
        <option value={ALL}>All {allLabel}</option>
        {values.map((item) => (
          <option key={item} value={item}>{labelize(item)}</option>
        ))}
      </select>
    </label>
  )
}

function DetailBlock({ label, value }) {
  if (value == null || value === '') return null
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600 mb-1.5">{label}</p>
      <pre className="rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2 text-xs text-gray-300 whitespace-pre-wrap overflow-x-auto">{text}</pre>
    </div>
  )
}

function VersionHistory({ history, loading }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <History className="w-3.5 h-3.5 text-gray-600" />
        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Version History</p>
      </div>
      {loading ? (
        <div className="flex items-center gap-2 rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2 text-xs text-gray-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Loading history...
        </div>
      ) : history.length === 0 ? (
        <div className="rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2 text-xs text-gray-500">
          No saved versions yet.
        </div>
      ) : (
        <div className="space-y-2">
          {history.slice(0, 6).map((item) => (
            <div key={`${item.version}-${item.id}`} className="rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-bold text-white">v{item.version}</span>
                <span className="text-[10px] uppercase tracking-wider text-gray-600">{labelize(item.change_type)}</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500">
                <span>{formatWhen(item.created_at)}</span>
                {item.changed_by && <span>by {item.changed_by}</span>}
              </div>
              {item.change_note && <p className="mt-1 text-xs text-gray-400">{item.change_note}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function DetailsDisclosure({ title, children, defaultOpen = false }) {
  return (
    <details open={defaultOpen} className="rounded-lg border border-white/[0.06] bg-white/[0.025]">
      <summary className="cursor-pointer px-3 py-2 text-xs font-bold text-gray-300 hover:text-white">
        {title}
      </summary>
      <div className="border-t border-white/[0.06] p-3 space-y-3">
        {children}
      </div>
    </details>
  )
}

function RuleDetail({ rule, history, historyLoading, onEdit, onArchive }) {
  if (!rule) {
    return (
      <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-6 text-center">
        <BookOpen className="w-8 h-8 text-gray-700 mx-auto mb-3" />
        <p className="text-sm text-gray-500">Pick a rule to see what it does and where it applies.</p>
      </div>
    )
  }

  const ruleId = rule.id || rule.rule_id || rule.key
  const conditions = rule.condition_json || rule.conditions || rule.when || rule.match || rule.criteria
  const actions = rule.action_json || rule.actions || rule.then || rule.apply || rule.outputs
  const archived = String(rule.status || '').toLowerCase() === 'archived'
  const customRule = String(ruleId || '').startsWith('custom.')
  const needsWiring = customRule && isActiveStatus(rule.status) && (!rule.implementation_ref || !rule.test_ref)

  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] overflow-hidden">
      <div className="border-b border-white/[0.06] px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-white truncate">{rule.name || rule.title || ruleId || 'Untitled rule'}</h2>
            <p className="text-xs text-gray-400 mt-1 leading-relaxed">{summarizeRule(rule)}</p>
          </div>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border uppercase tracking-wider ${statusClass(rule.status)}`}>
            {isActiveStatus(rule.status) ? 'On' : labelize(rule.status || 'unknown')}
          </span>
        </div>
        {needsWiring && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/15 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            <ShieldCheck className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>This custom rule is marked active, but it still needs real implementation and test links before it can safely affect bids.</span>
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onEdit(rule)}
            className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.04] px-2.5 py-1.5 text-xs font-medium text-gray-200 hover:bg-white/[0.08]"
          >
            <Pencil className="w-3.5 h-3.5" />
            Edit Rule
          </button>
          {!archived && (
            <button
              type="button"
              onClick={() => onArchive(rule)}
              className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/20 bg-blue-500/10 px-2.5 py-1.5 text-xs font-medium text-blue-200 hover:bg-blue-500/15"
            >
              <Archive className="w-3.5 h-3.5" />
              Archive Rule
            </button>
          )}
        </div>
      </div>
      <div className="p-4 space-y-4">
        <div className="grid gap-3">
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">When this applies</p>
            <p className="mt-1 text-sm text-gray-200 leading-relaxed">{plainWhen(rule)}</p>
          </div>
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">What Josh does</p>
            <p className="mt-1 text-sm text-gray-200 leading-relaxed">{plainAction(rule)}</p>
          </div>
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Example</p>
            <p className="mt-1 text-sm text-gray-200 leading-relaxed">{plainExample(rule)}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Used in</p>
            <p className="text-gray-300 mt-1">{ruleAppliesTo(rule)}</p>
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Version</p>
            <p className="text-gray-300 mt-1">v{rule.version || rule.revision || 1}</p>
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Updated</p>
            <p className="text-gray-300 mt-1">{formatWhen(rule.updated_at)}</p>
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Rule Type</p>
            <p className="text-gray-300 mt-1">{labelize(rule.category)}</p>
          </div>
        </div>

        <RulesAuditHarness selectedRule={rule} />

        <DetailsDisclosure title="History">
          <VersionHistory history={history} loading={historyLoading} />
        </DetailsDisclosure>

        <DetailsDisclosure title="Developer details">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Rule ID</p>
              <p className="text-gray-300 mt-1 font-mono truncate">{ruleId || '-'}</p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Priority</p>
              <p className="text-gray-300 mt-1">{rule.priority ?? 0}</p>
            </div>
          </div>
          {rule.formula && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600 mb-1.5">Formula</p>
              <pre className="rounded-md border border-white/[0.06] bg-black/20 px-3 py-2 text-xs text-blue-200 overflow-x-auto">{rule.formula}</pre>
            </div>
          )}
          <DetailBlock label="When this applies JSON" value={conditions} />
          <DetailBlock label="What Josh does JSON" value={actions} />
          <DetailBlock label="Source" value={rule.source || rule.source_ref || rule.owner} />
          <DetailBlock label="Implementation" value={rule.implementation_ref} />
          <DetailBlock label="Test" value={rule.test_ref} />
          <DetailBlock label="Notes" value={rule.notes} />
        </DetailsDisclosure>
      </div>
    </div>
  )
}

function RuleEditorModal({ mode, rule, onClose, onSave }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [lessonText, setLessonText] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [draftInfo, setDraftInfo] = useState(null)
  const [listening, setListening] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const recognitionRef = useRef(null)
  const lessonTextareaRef = useRef(null)

  useEffect(() => {
    if (mode === 'edit' && rule) {
      setForm({
        rule_id: rule.rule_id || rule.id || '',
        name: rule.name || '',
        category: rule.category || 'material',
        stage: rule.stage || 'classification',
        status: rule.status || 'active',
        priority: rule.priority ?? 0,
        source: rule.source || '',
        description: rule.description || '',
        condition_json: jsonText(rule.condition_json),
        action_json: jsonText(rule.action_json),
        effective_from: rule.effective_from || '',
        effective_to: rule.effective_to || '',
        implementation_ref: rule.implementation_ref || '',
        test_ref: rule.test_ref || '',
        notes: rule.notes || '',
        changed_by: 'Josh',
        change_note: '',
      })
    } else {
      setForm(EMPTY_FORM)
    }
    setError(null)
    setLessonText('')
    setDraftInfo(null)
    setListening(false)
    setSaving(false)
  }, [mode, rule])

  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
      }
    }
  }, [])

  const update = (field, value) => {
    setForm((current) => {
      const next = { ...current, [field]: value }
      if (mode === 'create' && field === 'name' && !current.rule_id) {
        next.rule_id = `custom.${slugify(value)}`
      }
      return next
    })
  }

  const applyDraft = (draft, meta = {}) => {
    if (!draft) return
    setForm((current) => ({
      ...current,
      rule_id: draft.rule_id || current.rule_id,
      name: draft.name || current.name,
      category: draft.category || current.category,
      stage: draft.stage || current.stage,
      status: 'draft',
      priority: draft.priority ?? current.priority,
      source: draft.source || 'Josh spoken lesson',
      description: draft.description || current.description,
      condition_json: jsonText(draft.condition_json || {}),
      action_json: jsonText(draft.action_json || {}),
      notes: draft.notes || current.notes,
      changed_by: draft.changed_by || current.changed_by || 'Josh',
      change_note: draft.change_note || current.change_note || 'Initial spoken lesson from Josh.',
    }))
    setDraftInfo(meta)
  }

  const startListening = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setError('Voice input is not available in this browser. Type the lesson instead.')
      return
    }
    setError(null)
    const baseText = (lessonTextareaRef.current?.value || lessonText).trim()
    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognition.onresult = (event) => {
      let spoken = ''
      for (let i = 0; i < event.results.length; i += 1) {
        spoken += event.results[i][0].transcript
      }
      setLessonText([baseText, spoken.trim()].filter(Boolean).join(' ').trim())
    }
    recognition.onerror = (event) => {
      setError(event.error ? `Voice input stopped: ${event.error}` : 'Voice input stopped.')
      setListening(false)
    }
    recognition.onend = () => setListening(false)
    recognitionRef.current = recognition
    setListening(true)
    recognition.start()
  }

  const stopListening = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop()
    }
    setListening(false)
  }

  const draftFromLesson = async () => {
    const lesson = (lessonTextareaRef.current?.value || lessonText).trim()
    if (lesson.length < 8) {
      setError('Type or speak the rule first.')
      return
    }
    setError(null)
    setDrafting(true)
    try {
      const data = await api.draftRuleFromLesson({
        lesson_text: lesson,
        changed_by: form.changed_by || 'Josh',
      })
      applyDraft(data.draft, {
        assumptions: data.assumptions || [],
        needs_review: data.needs_review !== false,
        transcript: data.transcript || lesson,
      })
    } catch (err) {
      setError(err.message || 'Could not draft the rule.')
    } finally {
      setDrafting(false)
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    setError(null)

    let conditionJson
    let actionJson
    try {
      conditionJson = JSON.parse(form.condition_json || '{}')
      actionJson = JSON.parse(form.action_json || '{}')
    } catch (err) {
      setError('Condition and action must be valid JSON.')
      return
    }

    const payload = {
      name: form.name.trim(),
      category: form.category.trim(),
      stage: form.stage.trim(),
      status: form.status.trim(),
      priority: Number(form.priority) || 0,
      condition_json: conditionJson,
      action_json: actionJson,
      source: form.source.trim(),
      description: form.description.trim(),
      effective_from: form.effective_from || null,
      effective_to: form.effective_to || null,
      implementation_ref: form.implementation_ref.trim(),
      test_ref: form.test_ref.trim(),
      notes: form.notes.trim(),
      changed_by: form.changed_by.trim() || 'Josh',
      change_note: form.change_note.trim() || (mode === 'create' ? 'Rule created from registry.' : 'Rule edited from registry.'),
    }

    if (!payload.name) {
      setError('Rule name is required.')
      return
    }

    if (mode === 'create') {
      payload.rule_id = form.rule_id.trim()
      payload.version = 1
      if (!payload.rule_id) {
        setError('Rule ID is required.')
        return
      }
    }

    setSaving(true)
    try {
      await onSave(payload)
    } catch (err) {
      setError(err.message || 'Could not save rule.')
      setSaving(false)
    }
  }

  const title = mode === 'create' ? 'Add Rule' : `Edit v${Number(rule?.version || 1) + 1}`

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 px-4 py-6 sm:py-10">
      <form onSubmit={submit} className="w-full max-w-4xl rounded-lg border border-white/[0.08] bg-[#111827] shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-white/[0.08] px-4 py-3">
          <div>
            <h2 className="text-base font-bold text-white">{title}</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {mode === 'create' ? 'Speak or type the lesson, then review the draft before it goes live.' : 'Edits save as the next version.'}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-gray-400 hover:bg-white/[0.06] hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        {mode === 'create' && (
          <div className="border-b border-white/[0.08] p-4">
            <div className="rounded-lg border border-blue-500/15 bg-blue-500/[0.06] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <Wand2 className="w-4 h-4 text-blue-300" />
                  <h3 className="text-sm font-bold text-white">Josh Lesson</h3>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={listening ? stopListening : startListening}
                    className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium ${
                      listening
                        ? 'border-red-500/20 bg-red-500/10 text-red-200 hover:bg-red-500/15'
                        : 'border-white/[0.08] bg-white/[0.04] text-gray-200 hover:bg-white/[0.08]'
                    }`}
                  >
                    {listening ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
                    {listening ? 'Stop' : 'Speak'}
                  </button>
                  <button
                    type="button"
                    onClick={draftFromLesson}
                    disabled={drafting}
                    className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/20 bg-blue-500/15 px-2.5 py-1.5 text-xs font-semibold text-blue-200 hover:bg-blue-500/25 disabled:opacity-50"
                  >
                    {drafting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
                    Draft Rule
                  </button>
                </div>
              </div>
              <textarea
                ref={lessonTextareaRef}
                value={lessonText}
                onChange={(event) => {
                  setLessonText(event.target.value)
                  if (error) setError(null)
                }}
                rows={4}
                placeholder='Example: When tile is 2x12, treat it as mosaic and use mosaic labor.'
                className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
              />
              {draftInfo?.needs_review && (
                <div className="mt-2 rounded-md border border-amber-500/15 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  Draft saved as review-first. It will not be active until Josh chooses to activate it.
                </div>
              )}
              {draftInfo?.assumptions?.length > 0 && (
                <div className="mt-2 rounded-md border border-white/[0.06] bg-white/[0.03] px-3 py-2">
                  <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-gray-500">Assumptions</p>
                  <ul className="space-y-1 text-xs text-gray-300">
                    {draftInfo.assumptions.slice(0, 4).map((item, index) => (
                      <li key={`${index}-${item}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="p-4 space-y-4">
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] p-4">
            <div className="mb-3">
              <h3 className="text-sm font-bold text-white">Plain-English rule</h3>
              <p className="text-xs text-gray-500 mt-0.5">This is the part Josh should read first.</p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Rule Name</span>
                <input
                  value={form.name}
                  onChange={(event) => update('name', event.target.value)}
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Status</span>
                <select
                  value={form.status}
                  onChange={(event) => update('status', event.target.value)}
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-300/40"
                >
                  {FALLBACK_STATUSES.map((item) => <option key={item} value={item}>{item === 'active' ? 'Active / On' : labelize(item)}</option>)}
                </select>
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Rule Type</span>
                <input
                  value={form.category}
                  onChange={(event) => update('category', event.target.value)}
                  list="rule-categories"
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Where It Applies</span>
                <input
                  value={form.stage}
                  onChange={(event) => update('stage', event.target.value)}
                  list="rule-stages"
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5 md:col-span-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">What The Rule Does</span>
                <textarea
                  value={form.description}
                  onChange={(event) => update('description', event.target.value)}
                  rows={3}
                  placeholder="Example: Treat 2x12 tile as mosaic so it uses mosaic labor."
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
                />
              </label>
            </div>
          </div>

          <details className="rounded-lg border border-white/[0.06] bg-white/[0.02]">
            <summary className="cursor-pointer px-4 py-3 text-sm font-bold text-gray-300 hover:text-white">
              Advanced setup
            </summary>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 border-t border-white/[0.06] p-4">
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Rule ID</span>
                <input
                  value={form.rule_id}
                  onChange={(event) => update('rule_id', event.target.value)}
                  disabled={mode === 'edit'}
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40 disabled:opacity-60"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Priority</span>
                <input
                  type="number"
                  value={form.priority}
                  onChange={(event) => update('priority', event.target.value)}
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">When This Applies JSON</span>
                <textarea
                  value={form.condition_json}
                  onChange={(event) => update('condition_json', event.target.value)}
                  rows={8}
                  className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-3 py-2 font-mono text-xs text-blue-100 focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">What Josh Does JSON</span>
                <textarea
                  value={form.action_json}
                  onChange={(event) => update('action_json', event.target.value)}
                  rows={8}
                  className="w-full rounded-lg border border-white/[0.08] bg-black/20 px-3 py-2 font-mono text-xs text-blue-100 focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Source</span>
                <input
                  value={form.source}
                  onChange={(event) => update('source', event.target.value)}
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Implementation Ref</span>
                <input
                  value={form.implementation_ref}
                  onChange={(event) => update('implementation_ref', event.target.value)}
                  placeholder="Code path, evaluator, or ticket"
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5 md:col-span-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Test Ref</span>
                <input
                  value={form.test_ref}
                  onChange={(event) => update('test_ref', event.target.value)}
                  placeholder="Harness case, Chrome test, or acceptance evidence"
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Changed By</span>
                <input
                  value={form.changed_by}
                  onChange={(event) => update('changed_by', event.target.value)}
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5 md:col-span-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Change Note</span>
                <input
                  value={form.change_note}
                  onChange={(event) => update('change_note', event.target.value)}
                  placeholder="Why this rule changed"
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
                />
              </label>
              <label className="space-y-1.5 md:col-span-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Notes</span>
                <textarea
                  value={form.notes}
                  onChange={(event) => update('notes', event.target.value)}
                  rows={2}
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-300/40"
                />
              </label>
            </div>
          </details>
        </div>

        <datalist id="rule-categories">
          {FALLBACK_CATEGORIES.map((item) => <option key={item} value={item} />)}
        </datalist>
        <datalist id="rule-stages">
          {FALLBACK_STAGES.map((item) => <option key={item} value={item} />)}
        </datalist>

        {form.rule_id.startsWith('custom.') && form.status === 'active' && (!form.implementation_ref.trim() || !form.test_ref.trim()) && (
          <div className="mx-4 mb-4 flex items-center gap-2 rounded-lg border border-blue-500/15 bg-blue-500/10 px-3 py-2 text-sm text-blue-200">
            <ShieldCheck className="w-4 h-4 flex-shrink-0" />
            <span>Custom rules need implementation and test refs that point to real repo files before they can become active.</span>
          </div>
        )}

        {error && (
          <div className="mx-4 mb-4 flex items-center gap-2 rounded-lg border border-amber-500/15 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-white/[0.08] px-4 py-3">
          <button type="button" onClick={onClose} className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs font-medium text-gray-300 hover:bg-white/[0.08]">
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500/15 border border-blue-500/20 px-3 py-2 text-xs font-semibold text-blue-200 hover:bg-blue-500/25 disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save
          </button>
        </div>
      </form>
    </div>
  )
}

function RulesAuditHarness({ selectedRule = null }) {
  const [jobId, setJobId] = useState('')
  const [field, setField] = useState('grand_total')
  const [stage, setStage] = useState(selectedRule?.stage || 'pricing')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (selectedRule?.stage) setStage(selectedRule.stage)
  }, [selectedRule?.stage])

  const runHarness = async () => {
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const data = await api.runRulesAuditHarness({
        job_id: jobId || null,
        field: field || null,
        stage: stage || null,
      })
      setResult(data)
    } catch (err) {
      setError(err.message || 'Audit harness endpoint unavailable')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <ClipboardCheck className="w-4 h-4 text-blue-300" />
          <h2 className="text-sm font-bold text-white">Test this rule on a job</h2>
        </div>
      </div>
      <p className="mb-3 text-xs text-gray-500">
        Pick a job and value to check. This shows whether the rule path has audit proof for that estimate.
      </p>
      {selectedRule && (
        <p className="mb-3 text-xs text-blue-200">
          Testing: {selectedRule.name || selectedRule.rule_id || selectedRule.id}
        </p>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_1fr_auto] gap-2">
        <input
          value={jobId}
          onChange={(event) => setJobId(event.target.value)}
          placeholder="Job"
          className="rounded-lg border border-white/[0.06] bg-white/[0.04] px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
        />
        <input
          value={field}
          onChange={(event) => setField(event.target.value)}
          placeholder="Value to check"
          className="rounded-lg border border-white/[0.06] bg-white/[0.04] px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
        />
        <select
          value={stage}
          onChange={(event) => setStage(event.target.value)}
          className="rounded-lg border border-white/[0.06] bg-white/[0.04] px-3 py-2 text-xs text-gray-300 focus:outline-none focus:border-blue-300/40"
        >
          {FALLBACK_STAGES.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
        </select>
        <button
          onClick={runHarness}
          disabled={running}
          className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-500/15 border border-blue-500/20 px-3 py-2 text-xs font-semibold text-blue-200 hover:bg-blue-500/25 disabled:opacity-50"
        >
          {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}
          Test
        </button>
      </div>
      {error && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-500/15 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {result && (
        <div className="mt-3 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-3">
          <div className={`mb-3 rounded-md border px-3 py-2 text-xs ${
            result.summary?.field_found
              ? 'border-emerald-500/15 bg-emerald-500/10 text-emerald-200'
              : 'border-amber-500/15 bg-amber-500/10 text-amber-200'
          }`}>
            {result.summary?.field_found
              ? 'Audit proof found for this value.'
              : 'No audit proof found for this value yet.'}
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Rules</p>
              <p className="text-sm font-bold text-white">{result.rule_count ?? 0}</p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Traces</p>
              <p className="text-sm font-bold text-white">{result.trace_count ?? 0}</p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Value</p>
              <p className={result.summary?.field_found ? 'text-sm font-bold text-emerald-300' : 'text-sm font-bold text-amber-300'}>
                {result.summary?.field_found ? 'Found' : 'Missing'}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Latest Run</p>
              <p className="text-sm font-bold text-white">{labelize(result.summary?.run_type || result.latest_run?.run_type || 'none')}</p>
            </div>
          </div>
          {result.field_trace && (
            <div className="mt-3 grid gap-2 text-xs text-gray-300 md:grid-cols-2">
              <DetailBlock label="Formula" value={result.field_trace.formula} />
              <DetailBlock label="Result" value={result.field_trace.result ?? result.field_trace.result_value} />
              <DetailBlock label="Source" value={result.field_trace.source} />
              <DetailBlock label="Rule" value={result.field_trace.rule_id} />
              <div className="md:col-span-2">
                <DetailBlock label="Inputs" value={result.field_trace.inputs} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function RulesetVersionPanel({ rulesets, loading, onRefresh, onRollback }) {
  const current = rulesets[0]
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-blue-300" />
            <h2 className="text-sm font-bold text-white">Rule Set History</h2>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {current ? `Current rule set v${current.version} tracks ${current.rule_count} rules, ${current.active_count} on.` : 'No rule set snapshot yet.'}
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.04] px-2.5 py-1.5 text-xs font-medium text-gray-300 hover:bg-white/[0.08] disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {rulesets.slice(0, 6).map((item, index) => (
          <div key={item.version} className="rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold text-white">Rule set v{item.version}</span>
              <span className="text-[10px] uppercase tracking-wider text-gray-600">{labelize(item.change_type)}</span>
            </div>
            <div className="mt-1 text-[11px] text-gray-500">{formatWhen(item.created_at)}</div>
            {item.change_note && <p className="mt-1 line-clamp-2 text-xs text-gray-400">{item.change_note}</p>}
            <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-gray-500">
              <span>{item.rule_count} rules</span>
              {index === 0 ? (
                <span className="text-emerald-300">Current</span>
              ) : (
                <button
                  type="button"
                  onClick={() => onRollback(item)}
                  className="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-amber-200 hover:bg-amber-500/15"
                >
                  Review Rollback
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function RollbackConfirmModal({ ruleset, onClose, onConfirm }) {
  const [working, setWorking] = useState(false)
  if (!ruleset) return null

  const confirm = async () => {
    setWorking(true)
    try {
      await onConfirm(ruleset)
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className="w-full max-w-lg rounded-lg border border-white/[0.08] bg-[#111827] shadow-2xl">
        <div className="border-b border-white/[0.08] px-4 py-3">
          <h2 className="text-base font-bold text-white">Roll back the whole rule set?</h2>
          <p className="mt-1 text-xs text-gray-500">This changes every rule together and creates a new current version.</p>
        </div>
        <div className="space-y-3 p-4">
          <div className="rounded-lg border border-amber-500/15 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
            You are reviewing a rollback to rule set v{ruleset.version}.
          </div>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Created</p>
              <p className="mt-1 text-gray-300">{formatWhen(ruleset.created_at)}</p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Rules</p>
              <p className="mt-1 text-gray-300">{ruleset.rule_count} total · {ruleset.active_count} on</p>
            </div>
          </div>
          {ruleset.change_note && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Note</p>
              <p className="mt-1 text-sm text-gray-300">{ruleset.change_note}</p>
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-white/[0.08] px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={working}
            className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs font-medium text-gray-300 hover:bg-white/[0.08] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={working}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/15 px-3 py-2 text-xs font-semibold text-amber-100 hover:bg-amber-500/25 disabled:opacity-50"
          >
            {working ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <History className="w-3.5 h-3.5" />}
            Roll Back Rule Set
          </button>
        </div>
      </div>
    </div>
  )
}

export default function RulesRegistryPage() {
  const [rules, setRules] = useState([])
  const [panel, setPanel] = useState('rules')
  const [status, setStatus] = useState(ALL)
  const [category, setCategory] = useState(ALL)
  const [stage, setStage] = useState(ALL)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [rulesets, setRulesets] = useState([])
  const [rulesetsLoading, setRulesetsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [editor, setEditor] = useState(null)
  const [rollbackTarget, setRollbackTarget] = useState(null)

  const loadRules = async (preferredId = selectedId) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listRules({ status, category, stage })
      const nextRules = normalizeRules(data)
      const hasPreferred = preferredId && nextRules.some((rule) => (rule.id || rule.rule_id || rule.key) === preferredId)
      const nextSelectedId = hasPreferred ? preferredId : (nextRules[0]?.id || nextRules[0]?.rule_id || null)
      setRules(nextRules)
      setSelectedId(nextSelectedId)
      return nextSelectedId
    } catch (err) {
      setRules([])
      setSelectedId(null)
      setError(err.message || 'Rules endpoint unavailable')
      return null
    } finally {
      setLoading(false)
    }
  }

  const loadRulesets = async () => {
    setRulesetsLoading(true)
    try {
      const data = await api.listRulesets({ limit: 12 })
      setRulesets(normalizeRulesets(data))
    } catch {
      setRulesets([])
    } finally {
      setRulesetsLoading(false)
    }
  }

  useEffect(() => {
    loadRules(selectedId)
    loadRulesets()
  }, [status, category, stage])

  const statusOptions = useMemo(() => uniqueFrom(rules, 'status', FALLBACK_STATUSES), [rules])
  const categoryOptions = useMemo(() => uniqueFrom(rules, 'category', FALLBACK_CATEGORIES), [rules])
  const stageOptions = useMemo(() => uniqueFrom(rules, 'stage', FALLBACK_STAGES), [rules])
  const currentRuleset = rulesets[0]

  const filteredRules = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rules.filter((rule) => {
      if (status !== ALL && rule.status !== status) return false
      if (category !== ALL && rule.category !== category) return false
      if (stage !== ALL && rule.stage !== stage) return false
      if (!q) return true
      return [rule.id, rule.rule_id, rule.key, rule.name, rule.title, rule.description, rule.summary, rule.category, rule.stage]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(q))
    })
  }, [rules, status, category, stage, query])

  const selectedRule = filteredRules.find((rule) => (rule.id || rule.rule_id || rule.key) === selectedId) || filteredRules[0]
  const selectedRuleId = selectedRule?.id || selectedRule?.rule_id || selectedRule?.key

  const loadHistory = async (ruleId) => {
    if (!ruleId) {
      setHistory([])
      return
    }
    setHistoryLoading(true)
    try {
      const data = await api.getRuleVersions(ruleId)
      setHistory(normalizeVersions(data))
    } catch {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    let active = true
    const refresh = async () => {
      if (!selectedRuleId) {
        if (active) setHistory([])
        return
      }
      setHistoryLoading(true)
      try {
        const data = await api.getRuleVersions(selectedRuleId)
        if (active) setHistory(normalizeVersions(data))
      } catch {
        if (active) setHistory([])
      } finally {
        if (active) setHistoryLoading(false)
      }
    }
    refresh()
    return () => {
      active = false
    }
  }, [selectedRuleId])

  const saveRule = async (payload) => {
    const saved = editor.mode === 'create'
      ? await api.createRule(payload)
      : await api.updateRule(editor.rule.rule_id || editor.rule.id, payload)
    const savedId = saved.rule_id || saved.id || payload.rule_id || selectedRuleId
    setEditor(null)
    setNotice(editor.mode === 'create' ? 'Rule added.' : `Rule saved as v${saved.version || ''}.`)
    const visibleId = await loadRules(savedId)
    await loadRulesets()
    await loadHistory(visibleId || savedId)
  }

  const archiveSelectedRule = async (rule) => {
    const ruleId = rule.rule_id || rule.id
    if (!ruleId) return
    if (!window.confirm(`Archive ${rule.name || ruleId}?`)) return
    try {
      const saved = await api.archiveRule(ruleId, {
        changed_by: 'Josh',
        change_note: 'Rule archived from registry.',
      })
      setNotice(`Rule archived as v${saved.version || ''}.`)
      const visibleId = await loadRules(ruleId)
      await loadRulesets()
      await loadHistory(visibleId || ruleId)
    } catch (err) {
      setError(err.message || 'Could not archive rule.')
    }
  }

  const rollbackRuleset = async (ruleset) => {
    if (!ruleset?.version) return
    try {
      const result = await api.rollbackRuleset(ruleset.version, {
        changed_by: 'Josh',
        change_note: `Rolled registry back to ruleset v${ruleset.version}.`,
      })
      setRollbackTarget(null)
      setNotice(`Ruleset rolled back to v${ruleset.version}; current is v${result.new_version}.`)
      const visibleId = await loadRules(selectedRuleId)
      await loadRulesets()
      await loadHistory(visibleId || selectedRuleId)
    } catch (err) {
      setError(err.message || 'Could not roll back ruleset.')
    }
  }

  return (
    <>
      <div className="max-w-7xl mx-auto px-4 sm:px-8 py-6 sm:py-10 space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold text-white tracking-tight flex items-center gap-3">
              <ShieldCheck className="w-6 h-6 text-blue-300" />
              Estimating Rules
            </h1>
            <p className="text-sm text-gray-500 mt-1">Review, test, and update the rules Josh uses when building estimates.</p>
            <p className="mt-2 text-xs text-gray-600">
              {currentRuleset
                ? `Current rule set: v${currentRuleset.version} · ${currentRuleset.active_count} on · updated ${shortDate(currentRuleset.created_at)}`
                : 'Current rule set is loading...'}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setEditor({ mode: 'create', rule: null })}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-500/15 border border-blue-500/20 px-3 py-2 text-xs font-semibold text-blue-200 hover:bg-blue-500/25"
            >
              <Plus className="w-4 h-4" />
              Add Rule
            </button>
            <button
              onClick={() => loadRules(selectedRuleId)}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs font-medium text-gray-300 hover:bg-white/[0.08] disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] p-1">
          {[
            ['rules', 'Rules'],
            ['versions', 'Rule Set History'],
            ['test', 'Test Rules'],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setPanel(key)}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
                panel === key
                  ? 'bg-blue-500/15 text-blue-100 border border-blue-500/20'
                  : 'text-gray-500 hover:bg-white/[0.04] hover:text-gray-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {panel === 'rules' && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[240px] flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search rules..."
              className="w-full rounded-lg border border-white/[0.06] bg-white/[0.04] py-2 pl-9 pr-3 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-300/40"
            />
          </div>
          <SelectFilter icon={CheckCircle2} label="status" value={status} values={statusOptions} onChange={setStatus} />
          <SelectFilter icon={Filter} label="rule type" value={category} values={categoryOptions} onChange={setCategory} />
          <SelectFilter icon={SlidersHorizontal} label="where it applies" value={stage} values={stageOptions} onChange={setStage} />
        </div>
        )}

        {notice && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-emerald-500/15 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
            <span>{notice}</span>
            <button type="button" onClick={() => setNotice(null)} className="text-emerald-300/70 hover:text-emerald-200">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-500/15 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span>Rules registry unavailable: {error}</span>
          </div>
        )}

        {panel === 'versions' && (
        <RulesetVersionPanel
            rulesets={rulesets}
            loading={rulesetsLoading}
            onRefresh={loadRulesets}
            onRollback={setRollbackTarget}
          />
        )}

        {panel === 'test' && (
          <RulesAuditHarness selectedRule={selectedRule} />
        )}

        {panel === 'rules' && (
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_430px] gap-4">
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] px-4 py-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Rules</span>
              <span className="text-[10px] text-gray-600">{filteredRules.length} shown</span>
            </div>
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-500">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading rules...
              </div>
            ) : filteredRules.length === 0 ? (
              <div className="py-12 text-center">
                <BookOpen className="w-9 h-9 text-gray-700 mx-auto mb-3" />
                <p className="text-sm text-gray-500">{rules.length === 0 ? 'No rules returned yet.' : 'No rules match these filters.'}</p>
              </div>
            ) : (
              <div className="divide-y divide-white/[0.04]">
                {filteredRules.map((rule) => {
                  const id = rule.id || rule.rule_id || rule.key || rule.name
                  const active = selectedRule && (selectedRule.id || selectedRule.rule_id || selectedRule.key || selectedRule.name) === id
                  return (
                    <button
                      key={id}
                      onClick={() => setSelectedId(id)}
                      className={`block w-full px-4 py-3 text-left transition-colors ${
                        active ? 'bg-blue-500/[0.08]' : 'hover:bg-white/[0.035]'
                      }`}
                    >
                      <span className="flex items-start justify-between gap-3">
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-white">{rule.name || rule.title || id}</span>
                          <span className="mt-1 block text-xs text-gray-400 leading-relaxed">{summarizeRule(rule)}</span>
                        </span>
                        <span className={`flex-shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-md border uppercase tracking-wider ${statusClass(rule.status)}`}>
                          {isActiveStatus(rule.status) ? 'On' : labelize(rule.status || 'unknown')}
                        </span>
                      </span>
                      <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500">
                        <span>{ruleAppliesTo(rule)}</span>
                        <span>v{rule.version || 1}</span>
                        <span>Updated {shortDate(rule.updated_at)}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <RuleDetail
            rule={selectedRule}
            history={history}
            historyLoading={historyLoading}
            onEdit={(rule) => setEditor({ mode: 'edit', rule })}
            onArchive={archiveSelectedRule}
          />
        </div>
        )}
      </div>

      {editor && (
        <RuleEditorModal
          mode={editor.mode}
          rule={editor.rule}
          onClose={() => setEditor(null)}
          onSave={saveRule}
        />
      )}
      <RollbackConfirmModal
        ruleset={rollbackTarget}
        onClose={() => setRollbackTarget(null)}
        onConfirm={rollbackRuleset}
      />
    </>
  )
}
