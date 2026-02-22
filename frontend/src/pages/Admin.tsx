import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { adminApi, type PipelineRun, type PipelineStage, type CoverageDay, type RssFeed, type SourcesResponse } from '../lib/api'

const STORAGE_KEY = 'ainews_admin_key'
const POLL_RUNS_MS     = 15_000   // refresh full list every 15s
const POLL_RUN_MS      = 3_000    // poll active run every 3s for progress
const POLL_COVERAGE_MS = 60_000   // refresh coverage every 60s

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

/** Returns YYYY-MM-DD for today offset by `offsetDays`. */
function isoDate(offsetDays = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  return d.toISOString().slice(0, 10)
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
    { key: 'fetching',  label: 'Fetch',    value: p.fetched != null ? `${p.fetched} articles` : undefined },
    { key: 'filtering', label: 'Filter',   value: p.fetched != null && p.new != null ? `${p.new} new of ${p.fetched}` : undefined },
    { key: 'deduping',  label: 'Dedup',    value: p.deduped != null ? `${p.deduped} unique` : undefined },
    { key: 'saving',    label: 'Save',     value: p.saved != null ? `${p.saved} saved` : undefined },
    { key: 'enriching', label: 'Summarize', value: p.total_to_enrich != null ? `${p.enriched ?? 0} / ${p.total_to_enrich}` : undefined },
  ]

  const stageOrder: PipelineStage[] = ['fetching', 'filtering', 'deduping', 'saving', 'enriching']
  const currentIdx = stage ? stageOrder.indexOf(stage) : -1

  const isMultiDate = p.dates_total != null && p.dates_total > 1

  return (
    <div className="border border-gray-200 rounded p-4 space-y-3">
      {/* Date-range progress */}
      {isMultiDate && (
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            Processing date {(p.dates_completed ?? 0) + 1} / {p.dates_total}
            {p.current_date ? ` — ${p.current_date}` : ''}
          </span>
          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-300 rounded-full transition-all duration-500"
              style={{ width: `${(((p.dates_completed ?? 0) + 1) / (p.dates_total ?? 1)) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Stage label */}
      <p className="text-sm text-blue-700 font-medium animate-pulse">
        {stage ? STAGE_LABELS[stage] : 'Starting…'}
      </p>

      {/* Running status line */}
      <p className="text-xs text-gray-500 font-mono leading-relaxed">
        {[
          p.fetched   != null                         && `fetched ${p.fetched}`,
          p.new       != null                         && `${p.new} new`,
          p.deduped   != null                         && `${p.deduped} unique`,
          p.saved     != null                         && `${p.saved} saved`,
          p.total_to_enrich != null                   && `enriched ${p.enriched ?? 0}/${p.total_to_enrich}`,
        ].filter(Boolean).join(' · ') || 'Starting…'}
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

function CoverageStatusDot({ day }: { day: CoverageDay }) {
  if (day.failed > 0) return <span className="text-red-500 text-sm">⚠</span>
  if (day.pending > 0) return <span className="text-yellow-500 text-sm">●</span>
  if (day.enriched === day.total && day.total > 0) return <span className="text-green-500 text-sm">✓</span>
  return <span className="text-gray-300 text-sm">○</span>
}

function SourcesPanel({ adminKey }: { adminKey: string }) {
  const [sources, setSources] = useState<SourcesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [showAddForm, setShowAddForm] = useState(false)
  const [addName, setAddName] = useState('')
  const [addUrl, setAddUrl] = useState('')
  const [addError, setAddError] = useState('')
  const [adding, setAdding] = useState(false)
  const [togglingId, setTogglingId] = useState<number | null>(null)

  async function loadSources() {
    try {
      const data = await adminApi.getSources(adminKey)
      setSources(data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => { loadSources() }, [adminKey])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    setAddError('')
    setAdding(true)
    try {
      await adminApi.addRssFeed(adminKey, { name: addName.trim(), url: addUrl.trim() })
      setAddName('')
      setAddUrl('')
      setShowAddForm(false)
      await loadSources()
    } catch (err) {
      setAddError(err instanceof Error ? err.message : 'Failed to add feed')
    } finally { setAdding(false) }
  }

  async function handleDelete(id: number, name: string) {
    if (!window.confirm(`Delete "${name}"?`)) return
    try {
      await adminApi.deleteRssFeed(adminKey, id)
      await loadSources()
    } catch { /* ignore */ }
  }

  async function handleToggle(feed: RssFeed) {
    setTogglingId(feed.id)
    try {
      await adminApi.updateRssFeed(adminKey, feed.id, {
        name: feed.name,
        url: feed.url,
        is_active: !feed.is_active,
      })
      await loadSources()
    } catch { /* ignore */ }
    finally { setTogglingId(null) }
  }

  const ro = sources?.readonly

  return (
    <section className="space-y-4">
      <p className="section-heading">Sources</p>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <>
          {/* RSS Feeds — editable */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-gray-600">RSS Feeds</p>
              <button
                onClick={() => { setShowAddForm(!showAddForm); setAddError('') }}
                className="text-xs text-indigo-600 hover:underline"
              >
                {showAddForm ? 'Cancel' : '+ Add Feed'}
              </button>
            </div>

            {showAddForm && (
              <form onSubmit={handleAdd} className="border border-gray-200 rounded p-3 space-y-2">
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Feed name"
                    value={addName}
                    onChange={e => setAddName(e.target.value)}
                    className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-indigo-500"
                  />
                  <input
                    type="text"
                    placeholder="https://example.com/feed.xml"
                    value={addUrl}
                    onChange={e => setAddUrl(e.target.value)}
                    className="flex-[2] border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-indigo-500"
                  />
                  <button
                    type="submit"
                    disabled={adding || !addName.trim() || !addUrl.trim()}
                    className="bg-indigo-600 text-white text-sm px-3 py-1.5 rounded hover:bg-indigo-700 disabled:opacity-50 whitespace-nowrap"
                  >
                    {adding ? 'Validating…' : 'Validate & Add'}
                  </button>
                </div>
                {addError && <p className="text-xs text-red-600">{addError}</p>}
              </form>
            )}

            {sources && sources.rss_feeds.length > 0 && (
              <div className="border border-gray-200 rounded overflow-x-auto">
                <table className="w-full text-xs text-gray-700">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      {['Name', 'URL', 'Active', ''].map(h => (
                        <th key={h} className="text-left px-3 py-2 font-medium text-gray-500 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sources.rss_feeds.map((feed, i) => (
                      <tr key={feed.id} className={`border-b ${i === sources.rss_feeds.length - 1 ? 'border-transparent' : 'border-gray-100'} hover:bg-gray-50`}>
                        <td className="px-3 py-2">{feed.name}</td>
                        <td className="px-3 py-2 font-mono text-xs text-gray-500 max-w-xs truncate">{feed.url}</td>
                        <td className="px-3 py-2">
                          <button
                            onClick={() => handleToggle(feed)}
                            disabled={togglingId === feed.id}
                            className={`text-xs px-2 py-0.5 rounded border ${
                              feed.is_active
                                ? 'bg-green-50 text-green-700 border-green-200'
                                : 'bg-gray-50 text-gray-400 border-gray-200'
                            } disabled:opacity-50`}
                          >
                            {feed.is_active ? 'on' : 'off'}
                          </button>
                        </td>
                        <td className="px-3 py-2">
                          <button
                            onClick={() => handleDelete(feed.id, feed.name)}
                            className="text-xs text-red-500 hover:text-red-700"
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Read-only source cards */}
          {ro && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="border border-gray-200 rounded p-3">
                <p className="text-xs font-medium text-gray-600 mb-2">HackerNews</p>
                <p className="text-xs text-gray-500">Min score: <span className="font-medium text-gray-700">{ro.hackernews.min_score}</span></p>
                <p className="text-xs text-gray-500">Keywords: <span className="font-medium text-gray-700">{ro.hackernews.keyword_count}</span></p>
              </div>
              <div className="border border-gray-200 rounded p-3">
                <p className="text-xs font-medium text-gray-600 mb-2">Reddit</p>
                <div className="flex flex-wrap gap-1 mb-1">
                  {ro.reddit.subreddits.map(s => (
                    <span key={s} className="category-badge bg-gray-50 text-gray-600 border-gray-200">r/{s}</span>
                  ))}
                </div>
                <p className="text-xs text-gray-500">Min upvotes: <span className="font-medium text-gray-700">{ro.reddit.min_upvotes}</span></p>
              </div>
              <div className="border border-gray-200 rounded p-3">
                <p className="text-xs font-medium text-gray-600 mb-2">Arxiv</p>
                <div className="flex flex-wrap gap-1 mb-1">
                  {ro.arxiv.categories.map(c => (
                    <span key={c} className="category-badge bg-gray-50 text-gray-600 border-gray-200">{c}</span>
                  ))}
                </div>
                <p className="text-xs text-gray-500">Keywords: <span className="font-medium text-gray-700">{ro.arxiv.keyword_count}</span></p>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function CoveragePanel({ adminKey }: { adminKey: string }) {
  const [coverage, setCoverage] = useState<CoverageDay[]>([])
  const [loading, setLoading] = useState(true)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function loadCoverage() {
    try {
      const data = await adminApi.getCoverage(adminKey)
      setCoverage(data.coverage)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => {
    loadCoverage()
    intervalRef.current = setInterval(loadCoverage, POLL_COVERAGE_MS)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [adminKey])

  return (
    <section>
      <p className="section-heading">Data Coverage (last 90 days)</p>
      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : coverage.length === 0 ? (
        <p className="text-sm text-gray-400">No data yet.</p>
      ) : (
        <div className="border border-gray-200 rounded overflow-x-auto">
          <table className="w-full text-xs text-gray-700">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['Date', 'Total', 'Enriched', 'Pending', 'Failed', ''].map(h => (
                  <th key={h} className="text-left px-3 py-2 font-medium text-gray-500 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {coverage.map((day, i) => (
                <tr key={day.date} className={`border-b ${i === coverage.length - 1 ? 'border-transparent' : 'border-gray-100'} hover:bg-gray-50`}>
                  <td className="px-3 py-2 font-mono">{day.date}</td>
                  <td className="px-3 py-2">{day.total}</td>
                  <td className="px-3 py-2 text-green-700">{day.enriched}</td>
                  <td className="px-3 py-2 text-yellow-700">{day.pending}</td>
                  <td className="px-3 py-2 text-red-700">{day.failed}</td>
                  <td className="px-3 py-2"><CoverageStatusDot day={day} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
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

  // Date-range form state — default both to today
  const [dateFrom, setDateFrom] = useState(isoDate(0))
  const [dateTo,   setDateTo]   = useState(isoDate(0))

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
        if (updated.status !== 'running') {
          fetchRuns(key)
          clearInterval(runIntervalRef.current!)
          runIntervalRef.current = null
        }
      } catch { /* ignore transient errors */ }
    }

    if (runIntervalRef.current) return
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

  function handleDateFromChange(val: string) {
    setDateFrom(val)
    // Clamp: dateTo must not be before dateFrom
    if (dateTo < val) setDateTo(val)
  }

  function handleDateToChange(val: string) {
    setDateTo(val)
    // Clamp: dateFrom must not be after dateTo
    if (dateFrom > val) setDateFrom(val)
  }

  async function handleTrigger() {
    setTriggering(true)
    try {
      await adminApi.triggerIngest(key, {
        triggeredBy: 'api',
        dateFrom,
        dateTo,
      })
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

        {/* Actions — date-range form */}
        <section className="space-y-3">
          <p className="section-heading">Run Pipeline</p>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">From</label>
              <input
                type="date"
                value={dateFrom}
                max={isoDate(0)}
                onChange={e => handleDateFromChange(e.target.value)}
                disabled={!!activeRun}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-indigo-500 disabled:opacity-50"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">To</label>
              <input
                type="date"
                value={dateTo}
                min={dateFrom}
                max={isoDate(0)}
                onChange={e => handleDateToChange(e.target.value)}
                disabled={!!activeRun}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-indigo-500 disabled:opacity-50"
              />
            </div>
            <button
              onClick={handleTrigger}
              disabled={!!activeRun || triggering}
              className="bg-indigo-600 text-white text-sm px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
            >
              {triggering ? 'Starting…' : 'Run Pipeline'}
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
          </div>
        </section>

        {/* Live progress */}
        {activeRun && (
          <section>
            <p className="section-heading">
              Run #{activeRun.id} · {activeRun.target_date}
              {activeRun.date_to && activeRun.date_to !== activeRun.target_date
                ? ` → ${activeRun.date_to}`
                : ''}
            </p>
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
                {latestSuccess.date_to && latestSuccess.date_to !== latestSuccess.target_date
                  ? ` · ${latestSuccess.target_date} → ${latestSuccess.date_to}`
                  : ` · ${latestSuccess.target_date}`}
              </p>
            </div>
          </section>
        )}

        {/* Sources panel */}
        <SourcesPanel adminKey={key} />

        {/* Coverage panel */}
        <CoveragePanel adminKey={key} />

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
                    {['#', 'Status', 'Date range', 'Started', 'Duration', 'Fetched', 'New', 'Saved', 'Enriched', 'By'].map(h => (
                      <th key={h} className="text-left px-3 py-2 font-medium text-gray-500 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run, i) => {
                    const isLast = i === runs.length - 1
                    const hasFailed = run.status === 'failed' && run.error_message
                    const dateFrom = run.target_date
                    const dateTo   = run.date_to
                                  ?? run.progress?.date_to
                                  ?? run.result.date_to
                                  ?? run.target_date
                    const isBackfill = dateTo !== dateFrom
                    const dayCount = isBackfill
                      ? Math.round((new Date(dateTo).getTime() - new Date(dateFrom).getTime()) / 86_400_000) + 1
                      : null
                    return (
                      <>
                        <tr key={run.id} className={`border-b ${isLast ? 'border-transparent' : 'border-gray-100'} hover:bg-gray-50`}>
                          <td className="px-3 py-2 text-gray-400">{run.id}</td>
                          <td className="px-3 py-2 whitespace-nowrap"><StatusBadge status={run.status} /></td>
                          <td className="px-3 py-2 whitespace-nowrap">
                            <span className="font-mono">{dateFrom}</span>
                            <span className="text-gray-400 mx-1">→</span>
                            <span className="font-mono">{dateTo}</span>
                            {isBackfill && (
                              <span className="ml-2 text-xs bg-indigo-50 text-indigo-600 border border-indigo-200 rounded px-1.5 py-0.5">
                                backfill · {dayCount}d
                              </span>
                            )}
                          </td>
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
