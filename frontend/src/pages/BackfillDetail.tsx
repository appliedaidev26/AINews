import { useEffect, useState, useCallback, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { adminApi, PipelineRun, PipelineTaskRun, PipelineProgress, EnrichStatus } from '../lib/api'

const STORAGE_KEY = 'ainews_admin_key'
const POLL_MS = 3000

const SOURCE_ORDER = ['hn', 'reddit', 'arxiv', 'rss'] as const
const SOURCE_LABELS: Record<string, string> = {
  hn:     'HN',
  reddit: 'Reddit',
  arxiv:  'Arxiv',
  rss:    'RSS',
}

type TaskStatus = PipelineTaskRun['status']

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function statusCell(status: TaskStatus): { bg: string; text: string; label: string; pulse: boolean } {
  switch (status) {
    case 'success':   return { bg: 'bg-green-50',  text: 'text-green-700',  label: '✓', pulse: false }
    case 'running':   return { bg: 'bg-blue-50',   text: 'text-blue-700',   label: '●', pulse: true  }
    case 'failed':    return { bg: 'bg-red-50',    text: 'text-red-700',    label: '✗', pulse: false }
    case 'cancelled': return { bg: 'bg-gray-50',   text: 'text-gray-400',   label: '—', pulse: false }
    default:          return { bg: 'bg-gray-100',  text: 'text-gray-400',   label: '○', pulse: false }
  }
}

function runStatusBadge(status: PipelineRun['status']) {
  const cls: Record<string, string> = {
    queued:    'bg-yellow-50 text-yellow-700 border-yellow-200',
    running:   'bg-blue-50 text-blue-700 border-blue-200',
    success:   'bg-green-50 text-green-700 border-green-200',
    partial:   'bg-orange-50 text-orange-700 border-orange-200',
    failed:    'bg-red-50 text-red-700 border-red-200',
    cancelled: 'bg-gray-50 text-gray-500 border-gray-200',
  }
  const dot: Record<string, string> = {
    queued: '⏳', running: '●', success: '✓', partial: '⚠', failed: '✗', cancelled: '—',
  }
  return (
    <span className={`inline-flex items-center gap-1 text-xs border rounded px-2 py-0.5 font-medium ${cls[status] ?? cls.running}`}>
      <span>{dot[status] ?? '?'}</span>
      <span>{status}</span>
    </span>
  )
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}m ${s}s`
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function ProgressBar({ value, max, className = '' }: { value: number; max: number; className?: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className={`w-full bg-gray-100 rounded-full h-2.5 ${className}`}>
      <div
        className="bg-indigo-600 h-2.5 rounded-full transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// In-process run view (no Cloud Tasks)
// ---------------------------------------------------------------------------

const PIPELINE_STAGES = ['fetching', 'filtering', 'deduping', 'saving', 'enriching'] as const
const STAGE_LABELS: Record<string, string> = {
  queued:    'Queued',
  fetching:  'Fetching',
  filtering: 'Filtering',
  deduping:  'Deduplicating',
  saving:    'Saving',
  enriching: 'Enriching',
}

function stageIndex(stage: string | undefined): number {
  if (!stage) return -1
  return PIPELINE_STAGES.indexOf(stage as typeof PIPELINE_STAGES[number])
}

function InProcessView({ run, enrichStatus }: { run: PipelineRun; enrichStatus: EnrichStatus | null }) {
  const p = run.progress as Partial<PipelineProgress>
  const currentStageIdx = stageIndex(p.stage)
  const isFinished = run.status === 'success' || run.status === 'failed' || run.status === 'cancelled'

  return (
    <div className="space-y-4">
      {/* Stage stepper */}
      <div className="border border-gray-200 rounded p-4 space-y-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Pipeline Stages</p>
        <div className="flex items-center gap-1">
          {PIPELINE_STAGES.map((stage, i) => {
            const idx = i
            let state: 'done' | 'active' | 'pending'
            if (isFinished) {
              state = run.status === 'success' ? 'done' : (idx <= currentStageIdx ? 'done' : 'pending')
            } else if (idx < currentStageIdx) {
              state = 'done'
            } else if (idx === currentStageIdx) {
              state = 'active'
            } else {
              state = 'pending'
            }

            const bgCls = state === 'done'
              ? 'bg-green-100 text-green-700 border-green-200'
              : state === 'active'
                ? 'bg-blue-100 text-blue-700 border-blue-200'
                : 'bg-gray-50 text-gray-400 border-gray-200'

            return (
              <div key={stage} className="flex items-center gap-1 flex-1">
                <div className={`flex-1 border rounded px-2 py-1.5 text-center text-xs font-medium ${bgCls} ${state === 'active' ? 'animate-pulse' : ''}`}>
                  {state === 'done' && '✓ '}{STAGE_LABELS[stage]}
                </div>
                {i < PIPELINE_STAGES.length - 1 && (
                  <span className="text-gray-300 text-xs shrink-0">→</span>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Date progress */}
      {(p.dates_total ?? 0) > 0 && (
        <div className="border border-gray-200 rounded p-4 space-y-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Date Progress</p>
          <ProgressBar
            value={isFinished ? (p.dates_total ?? 0) : (p.dates_completed ?? 0)}
            max={p.dates_total ?? 0}
          />
          <p className="text-sm text-gray-700">
            {isFinished ? (
              <span>Processed <span className="font-semibold">{p.dates_total}</span> date{(p.dates_total ?? 0) !== 1 ? 's' : ''}</span>
            ) : (
              <>
                <span>Processing date </span>
                <span className="font-semibold">{(p.dates_completed ?? 0) + 1}</span>
                <span className="text-gray-400"> / {p.dates_total}</span>
                {p.current_date && (
                  <span className="ml-2 font-mono text-xs text-gray-500">({p.current_date})</span>
                )}
              </>
            )}
          </p>
        </div>
      )}

      {/* Live counts */}
      <div className="border border-gray-200 rounded p-4">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Article Counts</p>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[
            { label: 'Fetched',  value: isFinished ? run.result.fetched : p.fetched },
            { label: 'New',      value: isFinished ? run.result.new : p.new },
            { label: 'Deduped',  value: p.deduped },
            { label: 'Saved',    value: isFinished ? run.result.saved : p.saved },
            { label: 'Enriched', value: isFinished ? run.result.enriched : p.enriched },
          ].map(({ label, value }) => (
            <div key={label} className="text-center">
              <p className="text-lg font-semibold text-gray-900">{value ?? '—'}</p>
              <p className="text-xs text-gray-500">{label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Sources used */}
      {p.sources_used && p.sources_used.length > 0 && (
        <div className="border border-gray-200 rounded p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Sources</p>
          <div className="flex gap-2">
            {p.sources_used.map(src => (
              <span key={src} className="text-xs border border-gray-200 rounded px-2 py-0.5 text-gray-700">
                {SOURCE_LABELS[src] ?? src}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Enrichment/vectorization status (from enrich-status endpoint) */}
      {enrichStatus && enrichStatus.total_saved > 0 && (
        <div className="border border-gray-200 rounded p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Enrichment & Vectorization</p>
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-600 w-32 shrink-0">Enrich (Gemini)</span>
              <ProgressBar value={enrichStatus.enriched} max={enrichStatus.total_saved} className="flex-1" />
              <span className="text-xs text-gray-500 w-28 text-right shrink-0">
                {enrichStatus.enriched} / {enrichStatus.total_saved}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-600 w-32 shrink-0">Vectorize (Vertex)</span>
              <ProgressBar value={enrichStatus.vectorized} max={enrichStatus.total_saved} className="flex-1" />
              <span className="text-xs text-gray-500 w-28 text-right shrink-0">
                {enrichStatus.vectorized} / {enrichStatus.total_saved}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Error message */}
      {run.error_message && (
        <div className="border border-red-200 bg-red-50 rounded p-3">
          <p className="text-xs font-semibold text-red-700 uppercase tracking-wide mb-1">Error</p>
          <p className="text-sm text-red-600 font-mono whitespace-pre-wrap">{run.error_message}</p>
        </div>
      )}

      {/* Duration */}
      {isFinished && run.duration_seconds != null && (
        <p className="text-xs text-gray-400">Completed in {formatDuration(run.duration_seconds)}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cloud Tasks run view (historical)
// ---------------------------------------------------------------------------

function OverallBar({ tasks, totalTasks }: { tasks: PipelineTaskRun[]; totalTasks: number }) {
  const done = tasks.filter(t => t.status === 'success' || t.status === 'failed' || t.status === 'cancelled').length
  const pct = totalTasks > 0 ? Math.round((done / totalTasks) * 100) : 0
  return (
    <div className="border border-gray-200 rounded p-4 space-y-2">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Overall Progress</p>
      <ProgressBar value={done} max={totalTasks} />
      <p className="text-sm text-gray-700">
        <span className="font-semibold">{done}</span>
        <span className="text-gray-400"> / {totalTasks} tasks</span>
        <span className="ml-2 text-gray-400">({pct}%)</span>
      </p>
    </div>
  )
}

function SourceBars({ tasks }: { tasks: PipelineTaskRun[] }) {
  const bySource: Record<string, PipelineTaskRun[]> = {}
  for (const t of tasks) {
    if (!bySource[t.source]) bySource[t.source] = []
    bySource[t.source].push(t)
  }

  return (
    <div className="border border-gray-200 rounded p-4 space-y-3">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">By Source</p>
      {SOURCE_ORDER.map(src => {
        const srcTasks = bySource[src] ?? []
        if (srcTasks.length === 0) return null
        const done = srcTasks.filter(t => t.status === 'success' || t.status === 'failed').length
        const articles = srcTasks.reduce((s, t) => s + (t.articles_saved ?? 0), 0)
        const pct = srcTasks.length > 0 ? Math.round((done / srcTasks.length) * 100) : 0
        return (
          <div key={src} className="flex items-center gap-3">
            <span className="text-xs text-gray-600 w-16 shrink-0">{SOURCE_LABELS[src] ?? src}</span>
            <ProgressBar value={done} max={srcTasks.length} className="flex-1" />
            <span className="text-xs text-gray-500 w-24 text-right shrink-0">
              {done}/{srcTasks.length} · {pct}% · {articles} art.
            </span>
          </div>
        )
      })}
    </div>
  )
}

function TaskGrid({
  tasks,
  adminKey,
  runId,
  dateFrom,
  dateTo,
  onRetry,
}: {
  tasks: PipelineTaskRun[]
  adminKey: string
  runId: number
  dateFrom: string
  dateTo: string
  onRetry: () => void
}) {
  const [retrying, setRetrying] = useState<string | null>(null)
  const [optimistic, setOptimistic] = useState<Record<string, TaskStatus>>({})

  const dates = useMemo(() => {
    // Generate all dates in the run's range, not just dates with task records
    const ds: string[] = []
    const start = new Date(dateFrom + 'T00:00:00')
    const end = new Date(dateTo + 'T00:00:00')
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      ds.push(d.toISOString().slice(0, 10))
    }
    // If no range dates (e.g. single-date run), fall back to task record dates
    if (ds.length === 0) {
      return [...new Set(tasks.map(t => t.date))].sort()
    }
    return ds
  }, [dateFrom, dateTo, tasks])

  const byKey = useMemo(() => {
    const m: Record<string, PipelineTaskRun> = {}
    for (const t of tasks) m[`${t.source}:${t.date}`] = t
    return m
  }, [tasks])

  const handleRetry = async (source: string, d: string) => {
    const key = `${source}:${d}`
    setRetrying(key)
    setOptimistic(prev => ({ ...prev, [key]: 'pending' }))
    try {
      await adminApi.retrySingleTask(adminKey, runId, source, d)
      onRetry()
    } catch (e) {
      setOptimistic(prev => { const n = { ...prev }; delete n[key]; return n })
    } finally {
      setRetrying(null)
    }
  }

  return (
    <div className="border border-gray-200 rounded overflow-auto">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 pt-3 pb-2">Task Grid</p>
      <table className="w-full text-xs">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="text-left px-4 py-2 text-gray-500 font-medium whitespace-nowrap">Date</th>
            {SOURCE_ORDER.map(src => (
              <th key={src} className="px-3 py-2 text-gray-500 font-medium text-center">{SOURCE_LABELS[src]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dates.map((d, i) => (
            <tr key={d} className={`border-b ${i === dates.length - 1 ? 'border-transparent' : 'border-gray-100'}`}>
              <td className="px-4 py-1.5 font-mono text-gray-600 whitespace-nowrap">{d}</td>
              {SOURCE_ORDER.map(src => {
                const task = byKey[`${src}:${d}`]
                const cellKey = `${src}:${d}`
                const effectiveStatus: TaskStatus = optimistic[cellKey] ?? task?.status ?? 'pending'
                const { bg, text, label, pulse } = statusCell(effectiveStatus)
                const isRetrying = retrying === cellKey
                return (
                  <td key={src} className="px-3 py-1.5 text-center">
                    <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 ${bg} ${text} ${pulse ? 'animate-pulse' : ''}`}>
                      <span>{label}</span>
                      {effectiveStatus === 'failed' && (
                        <button
                          onClick={() => handleRetry(src, d)}
                          disabled={isRetrying}
                          className="ml-1 underline text-red-600 hover:text-red-800 disabled:opacity-50"
                          title="Retry this task"
                        >
                          {isRetrying ? '…' : '↺'}
                        </button>
                      )}
                    </span>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-4 py-2 text-xs text-gray-400 flex gap-4">
        <span><span className="text-green-600">✓</span> success</span>
        <span><span className="text-blue-600">●</span> running</span>
        <span><span className="text-red-600">✗</span> failed</span>
        <span><span className="text-gray-400">○</span> pending</span>
      </div>
    </div>
  )
}

function AsyncPipelineStatus({ enrichStatus }: { enrichStatus: EnrichStatus | null }) {
  if (!enrichStatus) return null
  const { total_saved, enriched, vectorized } = enrichStatus
  return (
    <div className="border border-gray-200 rounded p-4 space-y-3">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Post-Save Pipeline (async via Pub/Sub)</p>
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-600 w-32 shrink-0">Enrich (Gemini)</span>
          <ProgressBar value={enriched} max={total_saved} className="flex-1" />
          <span className="text-xs text-gray-500 w-28 text-right shrink-0">
            {enriched} / {total_saved} articles
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-600 w-32 shrink-0">Vectorize (Vertex)</span>
          <ProgressBar value={vectorized} max={total_saved} className="flex-1" />
          <span className="text-xs text-gray-500 w-28 text-right shrink-0">
            {vectorized} / {total_saved} articles
          </span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function BackfillDetail() {
  const { runId } = useParams<{ runId: string }>()
  const [adminKey] = useState(() => localStorage.getItem(STORAGE_KEY) ?? '')

  const [run, setRun] = useState<PipelineRun | null>(null)
  const [tasks, setTasks] = useState<PipelineTaskRun[]>([])
  const [enrichStatus, setEnrichStatus] = useState<EnrichStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retryingAll, setRetryingAll] = useState(false)

  const isActive = run?.status === 'running' || run?.status === 'queued'
  // Legacy in-process runs: no total_tasks AND no task records — show old stepper view
  // New in-process runs set total_tasks and create PipelineTaskRun records, so they use the task grid
  const isLegacyInProcess = run?.total_tasks == null && tasks.length === 0

  const fetchData = useCallback(async () => {
    if (!adminKey || !runId) return
    try {
      const id = parseInt(runId, 10)
      if (isLegacyInProcess && run) {
        // Legacy in-process: just refresh the run + enrich status (no task rows)
        const [runResp, enrichResp] = await Promise.all([
          adminApi.getRun(adminKey, id),
          adminApi.getRunEnrichStatus(adminKey, id),
        ])
        setRun(runResp)
        setEnrichStatus(enrichResp)
      } else {
        // Task-grid view (Cloud Tasks or new in-process): fetch tasks + enrich status
        const [tasksResp, enrichResp] = await Promise.all([
          adminApi.getRunTasks(adminKey, id),
          adminApi.getRunEnrichStatus(adminKey, id),
        ])
        setRun(tasksResp.run)
        setTasks(tasksResp.tasks)
        setEnrichStatus(enrichResp)
      }
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [adminKey, runId, isLegacyInProcess, run])

  // Initial load — always fetch tasks to determine mode
  useEffect(() => {
    if (!adminKey || !runId) return
    const id = parseInt(runId, 10)
    let cancelled = false
    ;(async () => {
      try {
        const [tasksResp, enrichResp] = await Promise.all([
          adminApi.getRunTasks(adminKey, id),
          adminApi.getRunEnrichStatus(adminKey, id),
        ])
        if (cancelled) return
        setRun(tasksResp.run)
        setTasks(tasksResp.tasks)
        setEnrichStatus(enrichResp)
        setError(null)
      } catch (e: unknown) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
      }
    })()
    return () => { cancelled = true }
  }, [adminKey, runId])

  // Polling for active runs
  useEffect(() => {
    if (!isActive || !run) return
    const interval = setInterval(fetchData, POLL_MS)
    return () => clearInterval(interval)
  }, [fetchData, isActive, run])

  const handleRetryAll = async () => {
    if (!adminKey || !runId) return
    setRetryingAll(true)
    try {
      await adminApi.retryRunTasks(adminKey, parseInt(runId, 10))
      await fetchData()
    } finally {
      setRetryingAll(false)
    }
  }

  if (!adminKey) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-gray-500">
        No admin key — go to <Link to="/admin" className="text-indigo-600 underline ml-1">/admin</Link>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen p-8">
        <Link to="/admin" className="text-xs text-indigo-600 hover:underline">← Run History</Link>
        <p className="mt-4 text-sm text-red-600">{error}</p>
      </div>
    )
  }

  if (!run) {
    return (
      <div className="min-h-screen p-8 text-sm text-gray-400">Loading…</div>
    )
  }

  const failedTasks = tasks.filter(t => t.status === 'failed')
  const totalTasks = run.total_tasks ?? tasks.length
  const dateFrom = run.target_date
  const dateTo = run.date_to ?? run.target_date

  return (
    <div className="min-h-screen bg-white font-sans">
      {/* Header */}
      <header className="border-b border-gray-200 px-6 py-3 flex items-center gap-4">
        <Link to="/admin" className="text-xs text-indigo-600 hover:underline">← Run History</Link>
        <div className="flex-1">
          <span className="text-sm font-semibold text-gray-900 mr-3">Run #{run.id}</span>
          <span className="text-xs text-gray-500 mr-3">
            {dateFrom}
            {dateTo !== dateFrom ? ` → ${dateTo}` : ''}
          </span>
          {runStatusBadge(run.status)}
        </div>
        <span className="text-xs text-gray-400">{formatDate(run.started_at)}</span>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6 space-y-4">
        {isLegacyInProcess ? (
          /* Legacy in-process pipeline view (old runs without per-source tracking) */
          <InProcessView run={run} enrichStatus={enrichStatus} />
        ) : (
          /* Cloud Tasks view (historical runs) */
          <>
            {/* Failed banner */}
            {failedTasks.length > 0 && (
              <div className="border border-red-200 bg-red-50 rounded p-3 flex items-center justify-between">
                <span className="text-sm text-red-700 font-medium">
                  {failedTasks.length} task{failedTasks.length !== 1 ? 's' : ''} failed
                </span>
                <button
                  onClick={handleRetryAll}
                  disabled={retryingAll}
                  className="text-xs border border-red-300 text-red-700 px-3 py-1 rounded hover:bg-red-100 disabled:opacity-50"
                >
                  {retryingAll ? 'Retrying…' : 'Retry All Failed'}
                </button>
              </div>
            )}

            {/* Live progress (in-process runs with progress data) */}
            {run.progress?.stage && (
              <div className="border border-gray-200 rounded p-4 space-y-2">
                <div className="flex items-center gap-4">
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Pipeline Progress</p>
                  <span className="text-xs border border-blue-200 bg-blue-50 text-blue-700 rounded px-2 py-0.5 font-medium">
                    {STAGE_LABELS[run.progress.stage] ?? run.progress.stage}
                    {run.progress.current_date && <span className="ml-1 font-mono text-blue-500">({run.progress.current_date})</span>}
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-2">
                  {[
                    { label: 'Fetched',  value: run.progress.fetched },
                    { label: 'New',      value: run.progress.new },
                    { label: 'Saved',    value: run.progress.saved },
                    { label: 'Enriched', value: run.progress.enriched },
                    { label: 'Dates',    value: `${run.progress.dates_completed ?? 0}/${run.progress.dates_total ?? '?'}` },
                  ].map(({ label, value }) => (
                    <div key={label} className="text-center">
                      <p className="text-lg font-semibold text-gray-900">{value ?? '—'}</p>
                      <p className="text-xs text-gray-500">{label}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Overall progress */}
            <OverallBar tasks={tasks} totalTasks={totalTasks} />

            {/* Per-source bars */}
            {tasks.length > 0 && <SourceBars tasks={tasks} />}

            {/* Task grid */}
            <TaskGrid
              tasks={tasks}
              adminKey={adminKey}
              runId={run.id}
              dateFrom={dateFrom}
              dateTo={dateTo}
              onRetry={fetchData}
            />

            {/* Async pipeline status */}
            <AsyncPipelineStatus enrichStatus={enrichStatus} />

            {/* Run-level error message */}
            {run.error_message && (
              <div className="border border-red-200 bg-red-50 rounded p-3">
                <p className="text-xs font-semibold text-red-700 uppercase tracking-wide mb-1">Error</p>
                <p className="text-sm text-red-600 font-mono whitespace-pre-wrap">{run.error_message}</p>
              </div>
            )}

            {/* Failed tasks detail */}
            {failedTasks.length > 0 && (
              <div className="border border-gray-200 rounded overflow-hidden">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 pt-3 pb-2">
                  Failed Tasks
                </p>
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      {['Source', 'Date', 'Error', ''].map(h => (
                        <th key={h} className="text-left px-4 py-2 text-gray-500 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {failedTasks.map((t, i) => (
                      <tr key={t.id} className={`border-b ${i === failedTasks.length - 1 ? 'border-transparent' : 'border-gray-100'}`}>
                        <td className="px-4 py-2">{SOURCE_LABELS[t.source] ?? t.source}</td>
                        <td className="px-4 py-2 font-mono">{t.date}</td>
                        <td className="px-4 py-2 text-red-600 max-w-sm truncate" title={t.error_message ?? ''}>
                          {t.error_message ?? '—'}
                        </td>
                        <td className="px-4 py-2">
                          <RetryButton adminKey={adminKey} runId={run.id} task={t} onRetry={fetchData} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}

function RetryButton({
  adminKey, runId, task, onRetry,
}: {
  adminKey: string
  runId: number
  task: PipelineTaskRun
  onRetry: () => void
}) {
  const [loading, setLoading] = useState(false)

  const handleClick = async () => {
    setLoading(true)
    try {
      await adminApi.retrySingleTask(adminKey, runId, task.source, task.date)
      onRetry()
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="text-xs border border-gray-200 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-50 disabled:opacity-50"
    >
      {loading ? '…' : '↺ Retry'}
    </button>
  )
}
