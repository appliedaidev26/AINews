import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { adminApi, type PipelineRun, type PipelineStage } from '../lib/api'

const STORAGE_KEY = 'ainews_admin_key'
const POLL_RUNS_MS = 15_000   // refresh full list every 15s
const POLL_RUN_MS  = 3_000    // poll active run every 3s for progress

const STAGE_LABELS: Record<PipelineStage, string> = {
  fetching:  'Fetching articles from HN, Reddit, Arxiv, RSS…',
  filtering: 'Filtering already-seen articles…',
  deduping:  'Deduplicating similar articles…',
  saving:    'Saving to database…',
  enriching: 'Summarizing with Gemini…',
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}m ${s}s`
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function StatusBadge({ status }: { status: PipelineRun['status'] }) {
  const classes: Record<string, string> = {
    running:   'category-badge bg-blue-50 text-blue-700 border-blue-200',
    success:   'category-badge bg-green-50 text-green-700 border-green-200',
    failed:    'category-badge bg-red-50 text-red-700 border-red-200',
    cancelled: 'category-badge bg-gray-50 text-gray-500 border-gray-200',
  }
  const icons: Record<string, string> = {
    running: '●', success: '✓', failed: '✗', cancelled: '○',
  }
  return (
    <span className={`${classes[status] ?? 'category-badge'} ${status === 'running' ? 'animate-pulse' : ''}`}>
      {icons[status] ?? '?'} {status}
    </span>
  )
}

function ProgressPanel({ run }: { run: PipelineRun }) {
  const p = run.progress ?? {}
  const stage = p.stage

  const steps: { key: PipelineStage; label: string; value?: string }[] = [
    { key: 'fetching',  label: 'Fetch',      value: p.fetched != null ? `${p.fetched} articles` : undefined },
    { key: 'filtering', label: 'Filter',      value: p.fetched != null && p.new != null ? `${p.new} new of ${p.fetched}` : undefined },
    { key: 'deduping',  label: 'Dedup',       value: p.deduped != null ? `${p.deduped} unique` : undefined },
    { key: 'saving',    label: 'Save',         value: p.saved != null ? `${p.saved} saved` : undefined },
    { key: 'enriching', label: 'Summarize',   value: p.total_to_enrich != null ? `${p.enriched ?? 0} / ${p.total_to_enrich}` : undefined },
  ]

  const stageOrder: PipelineStage[] = ['fetching', 'filtering', 'deduping', 'saving', 'enriching']
  const currentIdx = stage ? stageOrder.indexOf(stage) : -1

  return (
    <div className="border border-gray-200 rounded p-4 space-y-3">
      {/* Stage label */}
      <p className="text-sm text-blue-700 font-medium animate-pulse">
        {stage ? STAGE_LABELS[stage] : 'Starting…'}
      </p>

      {/* Step pills */}
      <div className="flex items-center gap-0">
        {steps.map((step, i) => {
          const done    = currentIdx > i
          const active  = currentIdx === i
          const pending = currentIdx < i
          return (
            <div key={step.key} className="flex items-center">
              <div className={`flex flex-col items-center min-w-[80px] ${pending ? 'opacity-30' : ''}`}>
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold border
                  ${done    ? 'bg-green-500 border-green-500 text-white' : ''}
                  ${active  ? 'bg-blue-500 border-blue-500 text-white animate-pulse' : ''}
                  ${pending ? 'bg-white border-gray-300 text-gray-400' : ''}
                `}>
                  {done ? '✓' : i + 1}
                </div>
                <span className="text-xs text-gray-500 mt-1 text-center leading-tight">{step.label}</span>
                {step.value && (done || active) && (
                  <span className="text-xs font-medium text-gray-700 text-center leading-tight">{step.value}</span>
                )}
              </div>
              {i < steps.length - 1 && (
                <div className={`h-px w-6 mb-4 ${currentIdx > i ? 'bg-green-400' : 'bg-gray-200'}`} />
              )}
            </div>
          )
        })}
      </div>

      {/* Enrichment progress bar */}
      {stage === 'enriching' && p.total_to_enrich != null && p.total_to_enrich > 0 && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-500">
            <span>Enriched {p.enriched ?? 0} of {p.total_to_enrich}</span>
            <span>{Math.round(((p.enriched ?? 0) / p.total_to_enrich) * 100)}%</span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500 rounded-full transition-all duration-500"
              style={{ width: `${((p.enriched ?? 0) / p.total_to_enrich) * 100}%` }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export function Admin() {
  const [key, setKey] = useState<string>(() => localStorage.getItem(STORAGE_KEY) ?? '')
  const [keyInput, setKeyInput] = useState('')
  const [keyError, setKeyError] = useState('')
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  const [runs, setRuns] = useState<PipelineRun[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  const runsIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const runIntervalRef  = useRef<ReturnType<typeof setInterval> | null>(null)

  const activeRun = runs[0]?.status === 'running' ? runs[0] : null
  const latestSuccess = runs.find(r => r.status === 'success') ?? null

  function clearKey() {
    localStorage.removeItem(STORAGE_KEY)
    setKey('')
    setIsAuthenticated(false)
    setRuns([])
  }

  async function fetchRuns(adminKey: string): Promise<boolean> {
    try {
      const data = await adminApi.getRuns(adminKey)
      setRuns(data.runs)
      setError(null)
      return true
    } catch (err) {
      if (err instanceof Error && err.message === 'ADMIN_FORBIDDEN') {
        clearKey()
        setKeyError('Admin key rejected')
        return false
      }
      setKeyError(err instanceof Error ? err.message : 'Unknown error')
      return false
    }
  }

  // Fast-poll the active run for progress updates
  useEffect(() => {
    if (!isAuthenticated || !activeRun) {
      if (runIntervalRef.current) {
        clearInterval(runIntervalRef.current)
        runIntervalRef.current = null
      }
      return
    }

    const pollRun = async () => {
      try {
        const updated = await adminApi.getRun(key, activeRun.id)
        setRuns(prev => prev.map(r => r.id === updated.id ? updated : r))
        // If now finished, do a full refresh to get correct ordering/status
        if (updated.status !== 'running') {
          fetchRuns(key)
          clearInterval(runIntervalRef.current!)
          runIntervalRef.current = null
        }
      } catch { /* ignore transient errors */ }
    }

    if (runIntervalRef.current) return // already polling
    runIntervalRef.current = setInterval(pollRun, POLL_RUN_MS)

    return () => {
      if (runIntervalRef.current) {
        clearInterval(runIntervalRef.current)
        runIntervalRef.current = null
      }
    }
  }, [isAuthenticated, activeRun?.id, key])

  // Slow-poll the full run list
  useEffect(() => {
    if (!isAuthenticated) return
    if (runsIntervalRef.current) return
    runsIntervalRef.current = setInterval(() => fetchRuns(key), POLL_RUNS_MS)
    return () => {
      if (runsIntervalRef.current) {
        clearInterval(runsIntervalRef.current)
        runsIntervalRef.current = null
      }
    }
  }, [isAuthenticated, key])

  async function handleKeySubmit(e: React.FormEvent) {
    e.preventDefault()
    setKeyError('')
    setLoading(true)
    const trimmed = keyInput.trim()
    const ok = await fetchRuns(trimmed)
    setLoading(false)
    if (ok) {
      localStorage.setItem(STORAGE_KEY, trimmed)
      setKey(trimmed)
      setIsAuthenticated(true)
    }
  }

  useEffect(() => {
    if (!key) return
    setLoading(true)
    fetchRuns(key).then(ok => {
      setLoading(false)
      if (ok) setIsAuthenticated(true)
    })
  }, [])

  async function handleTrigger() {
    setTriggering(true)
    try {
      await adminApi.triggerIngest(key, 'api')
      await fetchRuns(key)
    } catch (err) {
      if (err instanceof Error && err.message === 'ADMIN_FORBIDDEN') { clearKey(); return }
      setError(err instanceof Error ? err.message : 'Trigger failed')
    } finally {
      setTriggering(false)
    }
  }

  async function handleCancel(runId: number) {
    setCancelling(true)
    try {
      await adminApi.cancelRun(key, runId)
      await fetchRuns(key)
    } catch (err) {
      if (err instanceof Error && err.message === 'ADMIN_FORBIDDEN') { clearKey(); return }
      setError(err instanceof Error ? err.message : 'Cancel failed')
    } finally {
      setCancelling(false)
    }
  }

  // --- Key gate ---
  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="w-full max-w-sm border border-gray-200 rounded p-8">
          <h1 className="text-base font-semibold text-gray-900 mb-6">AI News Admin</h1>
          <form onSubmit={handleKeySubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Admin Key</label>
              <input
                type="password"
                value={keyInput}
                onChange={e => setKeyInput(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
                placeholder="Enter admin key"
                autoFocus
              />
            </div>
            {keyError && <p className="text-xs text-red-600">{keyError}</p>}
            <button
              type="submit"
              disabled={loading || !keyInput.trim()}
              className="w-full bg-indigo-600 text-white text-sm py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? 'Checking...' : 'Sign in'}
            </button>
          </form>
        </div>
      </div>
    )
  }

  // --- Dashboard ---
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <h1 className="text-sm font-semibold text-gray-900">AI News Admin</h1>
        <div className="flex items-center gap-4">
          <Link to="/" className="text-xs text-indigo-600 hover:underline">← Feed</Link>
          <button onClick={clearKey} className="text-xs text-gray-500 hover:text-gray-800">Sign out</button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-8">
        {error && (
          <div className="text-xs text-red-600 border border-red-200 bg-red-50 rounded px-3 py-2">{error}</div>
        )}

        {/* Actions */}
        <section className="flex items-center gap-3">
          <button
            onClick={handleTrigger}
            disabled={!!activeRun || triggering}
            className="bg-indigo-600 text-white text-sm px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {triggering ? 'Starting…' : 'Run Pipeline Now'}
          </button>
          {activeRun && (
            <button
              onClick={() => handleCancel(activeRun.id)}
              disabled={cancelling}
              className="border border-red-300 text-red-600 text-sm px-4 py-2 rounded hover:bg-red-50 disabled:opacity-50"
            >
              {cancelling ? 'Stopping…' : `Stop Run #${activeRun.id}`}
            </button>
          )}
        </section>

        {/* Live progress */}
        {activeRun && (
          <section>
            <p className="section-heading">Run #{activeRun.id} · {activeRun.target_date}</p>
            <ProgressPanel run={activeRun} />
          </section>
        )}

        {/* Last run summary */}
        {latestSuccess && latestSuccess !== activeRun && (
          <section>
            <p className="section-heading">Last Successful Run</p>
            <div className="border border-gray-200 rounded p-4 text-sm text-gray-700">
              <div className="flex gap-6 mb-2">
                {(['fetched', 'new', 'saved', 'enriched'] as const).map(k => (
                  <div key={k} className="text-center">
                    <p className="text-lg font-semibold text-gray-900">{latestSuccess.result[k] ?? '—'}</p>
                    <p className="text-xs text-gray-400 capitalize">{k}</p>
                  </div>
                ))}
              </div>
              <p className="text-xs text-gray-400">
                via {latestSuccess.triggered_by} · {formatDuration(latestSuccess.duration_seconds)} · {formatDate(latestSuccess.started_at)}
              </p>
            </div>
          </section>
        )}

        {/* Run history */}
        <section>
          <p className="section-heading">Run History</p>
          {runs.length === 0 ? (
            <p className="text-sm text-gray-400">No runs yet.</p>
          ) : (
            <div className="border border-gray-200 rounded overflow-x-auto">
              <table className="w-full text-xs text-gray-700">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    {['#', 'Status', 'Date', 'Started', 'Duration', 'Fetched', 'New', 'Saved', 'Enriched', 'By'].map(h => (
                      <th key={h} className="text-left px-3 py-2 font-medium text-gray-500 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run, i) => {
                    const isLast = i === runs.length - 1
                    const hasFailed = run.status === 'failed' && run.error_message
                    return (
                      <>
                        <tr key={run.id} className={`border-b ${isLast ? 'border-transparent' : 'border-gray-100'} hover:bg-gray-50`}>
                          <td className="px-3 py-2 text-gray-400">{run.id}</td>
                          <td className="px-3 py-2 whitespace-nowrap"><StatusBadge status={run.status} /></td>
                          <td className="px-3 py-2 whitespace-nowrap">{run.target_date}</td>
                          <td className="px-3 py-2 whitespace-nowrap">{formatDate(run.started_at)}</td>
                          <td className="px-3 py-2 whitespace-nowrap">{formatDuration(run.duration_seconds)}</td>
                          <td className="px-3 py-2">{run.result.fetched ?? '—'}</td>
                          <td className="px-3 py-2">{run.result.new ?? '—'}</td>
                          <td className="px-3 py-2">{run.result.saved ?? '—'}</td>
                          <td className="px-3 py-2">{run.result.enriched ?? '—'}</td>
                          <td className="px-3 py-2 text-gray-400">{run.triggered_by}</td>
                        </tr>
                        {hasFailed && (
                          <tr key={`${run.id}-err`} className={`border-b ${isLast ? 'border-transparent' : 'border-gray-100'} bg-red-50`}>
                            <td />
                            <td colSpan={9} className="px-3 py-1.5 text-red-600 text-xs">
                              Run #{run.id} error: {run.error_message}
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
