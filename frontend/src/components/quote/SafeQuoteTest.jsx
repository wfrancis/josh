import { useEffect, useState } from 'react'
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
  Play,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import { api } from '../../api'
import {
  EmptyState,
  StatusPill,
  asArray,
  formatDate,
  normalizeStatus,
} from './QuoteUi'

const SCENARIOS = [
  ['all', 'Run every safety test'],
  ['normal_reply', 'Normal vendor reply'],
  ['changed_subject', 'Reply with changed subject'],
  ['standalone_email', 'New email, not a reply'],
  ['ambiguous_bid', 'Could belong to two bids'],
  ['partial_quote', 'Only some prices returned'],
  ['changed_price', 'Existing price changed'],
  ['wrong_unit', 'Wrong pricing unit'],
  ['duplicate_reply', 'Same reply received twice'],
  ['broken_attachment', 'Unreadable attachment'],
  ['no_response', 'No response and follow-ups'],
  ['materials_changed', 'Bid changed after send'],
  ['send_failure', 'Email could not send'],
]

export default function SafeQuoteTest({ jobs, defaultJobId }) {
  const [open, setOpen] = useState(false)
  const [jobId, setJobId] = useState(defaultJobId || '')
  const [scenario, setScenario] = useState('all')
  const [simulation, setSimulation] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (defaultJobId) setJobId(String(defaultJobId))
  }, [defaultJobId])

  const refreshRun = async (next) => {
    const runId = next?.id || next?.run_id
    const selectedJobId = next?.job_id || jobId
    if (!runId || !selectedJobId) return
    const loaded = await api.getQuoteSimulation(selectedJobId, runId)
    setSimulation(loaded)
  }

  const run = async () => {
    if (!jobId) {
      setError('Choose a bid first.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const created = await api.createQuoteSimulation(jobId, { scenario })
      await refreshRun(created)
    } catch (err) {
      setError(err.message || 'The safe test could not run.')
    } finally {
      setBusy(false)
    }
  }

  const rawResult = simulation?.result || simulation?.result_json || {}
  const result = typeof rawResult === 'string'
    ? (() => {
      try {
        return JSON.parse(rawResult)
      } catch {
        return {}
      }
    })()
    : rawResult
  const checks = asArray(result.checks)
  const scenarios = asArray(result.scenarios || result.scenario_results)
  const timeline = asArray(result.timeline || simulation?.timeline)
  const status = normalizeStatus(simulation?.status || result.status)
  const runId = simulation?.id || simulation?.run_id
  const simulationJobId = simulation?.job_id || jobId

  return (
    <section className="rounded-lg border border-white/[0.08] bg-white/[0.02]">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-gray-300">
          <ShieldCheck className="h-4 w-4 text-blue-400" />
          Safe Test
          <span className="text-xs font-normal text-gray-600">
            Fake mailbox. Real bids stay unchanged.
          </span>
        </span>
        {open
          ? <ChevronUp className="h-4 w-4 text-gray-500" />
          : <ChevronDown className="h-4 w-4 text-gray-500" />}
      </button>

      {open && (
        <div className="space-y-4 border-t border-white/[0.06] p-4">
          {error && (
            <div className="rounded-md border border-red-500/20 bg-red-500/[0.06] px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
            <label>
              <span className="mb-1.5 block text-xs font-semibold text-gray-500">
                Bid to copy
              </span>
              <select
                value={jobId}
                onChange={(event) => setJobId(event.target.value)}
                className="w-full rounded-md border border-white/[0.1] bg-[#0D1322] px-3 py-2.5 text-sm text-gray-300 outline-none focus:border-blue-400/50"
              >
                <option value="">Choose a bid</option>
                {jobs.map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.project_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="mb-1.5 block text-xs font-semibold text-gray-500">
                Test
              </span>
              <select
                value={scenario}
                onChange={(event) => setScenario(event.target.value)}
                className="w-full rounded-md border border-white/[0.1] bg-[#0D1322] px-3 py-2.5 text-sm text-gray-300 outline-none focus:border-blue-400/50"
              >
                {SCENARIOS.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={run}
              disabled={busy || !jobId}
              className="inline-flex items-center justify-center gap-2 rounded-md border border-blue-500/25 bg-blue-500/10 px-4 py-2.5 text-sm font-bold text-blue-200 hover:bg-blue-500/20 disabled:opacity-40"
            >
              {busy
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : <Play className="h-4 w-4" />}
              Run Safe Test
            </button>
          </div>

          {simulation ? (
            <div className="space-y-3 border-t border-white/[0.06] pt-4">
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill status={status} />
                <StatusPill
                  status={result.live_bid_unchanged === false ? 'fail' : 'pass'}
                  label="Real bid unchanged"
                />
                <StatusPill
                  status={Number(result.ai_calls || 0) === 0 ? 'pass' : 'fail'}
                  label="No AI calls"
                />
                {runId && (
                  <a
                    href={api.quoteSimulationReportUrl(simulationJobId, runId)}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-gray-400 hover:bg-white/[0.05] hover:text-white"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    Download Report
                  </a>
                )}
              </div>
              {[...checks, ...scenarios].length ? (
                <div className="divide-y divide-white/[0.05] border-y border-white/[0.06]">
                  {[...checks, ...scenarios].map((check, index) => {
                    const passed = check.passed ?? (
                      normalizeStatus(check.status) === 'pass'
                    )
                    return (
                      <div
                        key={check.id || check.scenario || index}
                        className="flex items-start gap-2 py-2.5 text-sm"
                      >
                        {passed
                          ? <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-400" />
                          : <XCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-400" />}
                        <div>
                          <p className="text-gray-300">
                            {check.label || check.name || check.scenario || `Check ${index + 1}`}
                          </p>
                          {(check.message || check.detail) && (
                            <p className="mt-0.5 text-xs text-gray-600">
                              {check.message || check.detail}
                            </p>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <EmptyState>The test did not return check details yet.</EmptyState>
              )}
              {timeline.length > 0 && (
                <div className="divide-y divide-white/[0.05]">
                  {timeline.slice(0, 8).map((event, index) => (
                    <div
                      key={event.id || index}
                      className="grid gap-1 py-2 text-xs sm:grid-cols-[140px_minmax(0,1fr)]"
                    >
                      <span className="text-gray-600">
                        {formatDate(event.at || event.created_at || event.time)}
                      </span>
                      <span className="text-gray-400">
                        {event.message || event.label || event.event}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-600">
              This uses a fake clock and fake mailbox. It cannot send real email or change the bid.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
