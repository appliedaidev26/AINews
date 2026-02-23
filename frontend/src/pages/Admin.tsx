import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { adminApi, type PipelineRun, type PipelineStage, type CoverageDay, type RssFeed, type SourcesResponse } from '../lib/api'

const STORAGE_KEY = 'ainews_admin_key'

const ALL_SOURCES = ['hn', 'reddit', 'arxiv'] as const
type SourceKey = typeof ALL_SOURCES[number]
const SOURCE_LABELS: Record<SourceKey, string> = {
  hn: 'Hacker News', reddit: 'Reddit', arxiv: 'Arxiv',
}
const POLL_RUNS_MS     = 15_000   // refresh full list every 15s
const POLL_RUN_MS      = 3_000    // poll active run every 3s for progress
const POLL_COVERAGE_MS = 60_000   // refresh coverage every 60s

const STAGE_LABELS: Record<PipelineStage, string> = {
  queued:    'Queued — waiting to start…',
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
  const stage = p.stage as PipelineStage | undefined

  const stageOrder: PipelineStage[] = ['fetching', 'filtering', 'deduping', 'saving', 'enriching']
  const currentIdx = stage ? stageOrder.indexOf(stage) : -1

  // Step values are only populated once the stage has *completed* (currentIdx > i),
  // so numbers always reflect finalized state. Exception: enriching shows live progress.
  const steps: { key: PipelineStage; label: string; value?: string }[] = [
    {
      key: 'fetching', label: 'Fetch',
      // p.fetched starts at 0 from running_totals; only meaningful once filtering begins
      value: currentIdx > 0 && p.fetched != null ? `${p.fetched}` : undefined,
    },
    {
      key: 'filtering', label: 'Filter',
      // p.new = running_totals["new"] = 0 while filtering is active (count not yet computed);
      // only reliable once deduping stage starts
      value: currentIdx > 1 && p.new != null ? `${p.new} new` : undefined,
    },
    {
      key: 'deduping', label: 'Dedup',
      // p.deduped is only emitted in the saving-stage payload; absent in enriching
      value: p.deduped != null ? `${p.deduped} uniq` : undefined,
    },
    {
      key: 'saving', label: 'Save',
      // p.saved during saving = previous dates' accumulated total (current date not yet flushed);
      // current_totals is applied once enriching starts, so only show then
      value: currentIdx > 3 && p.saved != null ? `${p.saved} saved` : undefined,
    },
    {
      key: 'enriching', label: 'Summarize',
      value: p.total_to_enrich != null ? `${p.enriched ?? 0}/${p.total_to_enrich}` : undefined,
    },
  ]

  const isMultiDate = (p.dates_total ?? 0) > 1
  // dates_completed = index of the date currently being processed (0-based)
  //   = number of dates fully completed so far
  const datesCompleted = p.dates_completed ?? 0
  const datesTotal     = p.dates_total ?? 1

  return (
    <div className="border border-gray-200 rounded p-4 space-y-3">
      {/* Multi-date progress: bar width = completed/total; text shows which date is active */}
      {isMultiDate && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>
              Date {datesCompleted + 1} / {datesTotal}
              {p.current_date ? ` — ${p.current_date}` : ''}
            </span>
            <span>{datesCompleted} / {datesTotal} complete</span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-300 rounded-full transition-all duration-500"
              style={{ width: `${(datesCompleted / datesTotal) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Stage label */}
      <p className="text-sm text-blue-700 font-medium animate-pulse">
        {stage ? STAGE_LABELS[stage] : 'Starting…'}
      </p>

      {/* Running counts — only show each value once its stage has completed */}
      <p className="text-xs text-gray-500 font-mono leading-relaxed">
        {[
          currentIdx > 0 && p.fetched        != null && `fetched ${p.fetched}`,
          currentIdx > 1 && p.new            != null && `${p.new} new`,
          currentIdx > 3 && p.saved          != null && `${p.saved} saved`,
          p.total_to_enrich                  != null && `enriched ${p.enriched ?? 0}/${p.total_to_enrich}`,
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
                {step.value != null && (
                  <span className="text-xs font-medium text-gray-700 text-center leading-tight">{step.value}</span>
                )}
              </div>
              {i < steps.length - 1 && (
                <div className={`h-px w-6 mb-4 ${done ? 'bg-green-400' : 'bg-gray-200'}`} />
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
          {/* Top row: HN, Reddit, Arxiv cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* Hacker News */}
            <div className="border border-gray-200 rounded p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-gray-700">Hacker News</p>
                <span className="text-xs px-1.5 py-0.5 rounded bg-green-50 text-green-700 border border-green-200">configured</span>
              </div>
              <p className="text-xs text-gray-500">Min score: <span className="font-medium text-gray-700">{ro?.hackernews.min_score ?? '—'}</span></p>
              <p className="text-xs text-gray-500">Keywords: <span className="font-medium text-gray-700">{ro?.hackernews.keyword_count ?? '—'}</span></p>
            </div>

            {/* Reddit */}
            <div className="border border-gray-200 rounded p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-gray-700">Reddit</p>
                {ro && (
                  ro.reddit.configured
                    ? <span className="text-xs px-1.5 py-0.5 rounded bg-green-50 text-green-700 border border-green-200">configured</span>
                    : <span className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">⚠ No API credentials</span>
                )}
              </div>
              {ro && (
                <>
                  <div className="flex flex-wrap gap-1 mb-1">
                    {ro.reddit.subreddits.map(s => (
                      <span key={s} className="category-badge bg-gray-50 text-gray-600 border-gray-200">r/{s}</span>
                    ))}
                  </div>
                  <p className="text-xs text-gray-500">Min upvotes: <span className="font-medium text-gray-700">{ro.reddit.min_upvotes}</span></p>
                </>
              )}
            </div>

            {/* Arxiv */}
            <div className="border border-gray-200 rounded p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-gray-700">Arxiv</p>
                <span className="text-xs px-1.5 py-0.5 rounded bg-green-50 text-green-700 border border-green-200">configured</span>
              </div>
              {ro && (
                <>
                  <div className="flex flex-wrap gap-1 mb-1">
                    {ro.arxiv.categories.map(c => (
                      <span key={c} className="category-badge bg-gray-50 text-gray-600 border-gray-200">{c}</span>
                    ))}
                  </div>
                  <p className="text-xs text-gray-500">Keywords: <span className="font-medium text-gray-700">{ro.arxiv.keyword_count}</span></p>
                </>
              )}
            </div>
          </div>

          {/* Blogs / RSS card — full width, contains the editable feeds table */}
          <div className="border border-gray-200 rounded p-3 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <p className="text-xs font-medium text-gray-700">Blogs / RSS</p>
                <span className="text-xs px-1.5 py-0.5 rounded bg-green-50 text-green-700 border border-green-200">configured</span>
              </div>
              <button
                onClick={() => { setShowAddForm(!showAddForm); setAddError('') }}
                className="text-xs text-indigo-600 hover:underline"
              >
                {showAddForm ? 'Cancel' : '+ Add Feed'}
              </button>
            </div>

            {showAddForm && (
              <form onSubmit={handleAdd} className="space-y-2">
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

            {sources && sources.rss_feeds.length > 0 ? (
              <div className="border border-gray-100 rounded overflow-x-auto">
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
            ) : (
              <p className="text-xs text-gray-400">No feeds configured. Add one above.</p>
            )}
          </div>
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

const ALL_SOURCE_KEYS = ['hn', 'reddit', 'arxiv', 'rss'] as const
const SOURCE_DISPLAY: Record<string, string> = {
  hn: 'Hacker News', reddit: 'Reddit', arxiv: 'Arxiv', rss: 'RSS/Blogs',
}

function RunDetailPanel({ run, feeds }: { run: PipelineRun; feeds: RssFeed[] }) {
  // Sources metadata lives in progress (set at creation) and is also copied to result on success.
  // progress is the authoritative source since it survives failed/cancelled runs too.
  const p = run.progress ?? {}
  const r = run.result ?? {}

  const sourcesUsed: string[] = p.sources_used ?? (r as { sources_used?: string[] }).sources_used ?? []
  const rssIdsUsed: number[] | null = p.rss_feed_ids_used !== undefined
    ? p.rss_feed_ids_used
    : ((r as { rss_feed_ids_used?: number[] | null }).rss_feed_ids_used ?? null)
  const rssFeedNamesUsed: Record<string, string> | null = p.rss_feed_names_used ?? null

  function rssFeedsLabel(): string {
    if (!sourcesUsed.includes('rss')) return ''
    if (rssIdsUsed === null) return 'all active feeds'
    if (rssIdsUsed.length === 0) return 'none'
    if (rssFeedNamesUsed) {
      const names = rssIdsUsed.map(id => rssFeedNamesUsed[String(id)] ?? `Feed #${id}`)
      return names.length <= 4
        ? names.join(', ')
        : `${names.slice(0, 4).join(', ')} +${names.length - 4} more`
    }
    // Fallback: look up from feeds list (for older runs without denormalized names)
    const feedMap = Object.fromEntries(feeds.map(f => [f.id, f.name]))
    const names = rssIdsUsed.map(id => feedMap[id] ?? `Feed #${id}`)
    return names.length <= 4
      ? names.join(', ')
      : `${names.slice(0, 4).join(', ')} +${names.length - 4} more`
  }

  const hasSourcesMeta = sourcesUsed.length > 0

  return (
    <div className="px-4 py-4 bg-gray-50 space-y-4">

      {/* Sources Used */}
      <div>
        <p className="text-xs font-medium text-gray-500 mb-1.5">Sources</p>
        {hasSourcesMeta ? (
          <>
            <div className="flex flex-wrap gap-1.5">
              {ALL_SOURCE_KEYS.map(src => {
                const active = sourcesUsed.includes(src)
                return (
                  <span key={src} className={`text-xs px-2 py-0.5 rounded border font-medium ${
                    active
                      ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
                      : 'bg-gray-100 text-gray-400 border-gray-200 line-through'
                  }`}>
                    {SOURCE_DISPLAY[src]}
                  </span>
                )
              })}
            </div>
            {sourcesUsed.includes('rss') && rssFeedsLabel() && (
              <p className="text-xs text-gray-400 mt-1.5">
                <span className="text-gray-500">Feeds:</span> {rssFeedsLabel()}
              </p>
            )}
          </>
        ) : (
          <p className="text-xs text-gray-400 italic">Not recorded (run predates this feature)</p>
        )}
      </div>

      {/* Stats */}
      {(run.status === 'success' || (run.result.fetched != null)) && (
        <div>
          <p className="text-xs font-medium text-gray-500 mb-1.5">Results</p>
          <div className="flex gap-6">
            {(['fetched', 'new', 'saved', 'enriched'] as const).map(k => (
              <div key={k} className="text-center">
                <p className="text-base font-semibold text-gray-900">{run.result[k] ?? '—'}</p>
                <p className="text-xs text-gray-400 capitalize">{k}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live progress for running runs */}
      {run.status === 'running' && <ProgressPanel run={run} />}

      {/* Timing */}
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-500">
        <span>Started: <span className="text-gray-700">{formatDate(run.started_at)}</span></span>
        {run.completed_at && (
          <span>Completed: <span className="text-gray-700">{formatDate(run.completed_at)}</span></span>
        )}
        {run.duration_seconds !== null && (
          <span>Duration: <span className="text-gray-700">{formatDuration(run.duration_seconds)}</span></span>
        )}
        <span>Triggered by: <span className="text-gray-700">{run.triggered_by}</span></span>
      </div>

      {/* Error */}
      {run.error_message && (
        <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 font-mono break-all">
          {run.error_message}
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
  const [clearConfirm, setClearConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)

  // Date-range form state — default both to today
  const [dateFrom, setDateFrom] = useState(isoDate(0))
  const [dateTo,   setDateTo]   = useState(isoDate(0))

  // Source selection state — all enabled by default
  const [selectedSources, setSelectedSources] = useState<Set<SourceKey>>(new Set(ALL_SOURCES))

  // RSS feed selection — loaded on auth; all selected by default
  const [feeds, setFeeds] = useState<RssFeed[]>([])
  const [selectedFeedIds, setSelectedFeedIds] = useState<Set<number>>(new Set())

  // Run History expand state
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null)

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

  // Load RSS feeds for the Run Pipeline form whenever authenticated
  useEffect(() => {
    if (!isAuthenticated) return
    adminApi.getSources(key).then(data => {
      setFeeds(data.rss_feeds)
      setSelectedFeedIds(new Set(data.rss_feeds.map(f => f.id)))
    }).catch(() => {})
  }, [isAuthenticated, key])

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
      // Build sources list: checked static sources + 'rss' if any feeds are selected
      const sourcesList: string[] = ALL_SOURCES.filter(s => selectedSources.has(s))
      if (selectedFeedIds.size > 0) sourcesList.push('rss')

      // Only send explicit feed IDs if it's a subset; omit (= undefined) to mean "all active feeds"
      const rssFeedIds = selectedFeedIds.size > 0 && selectedFeedIds.size < feeds.length
        ? [...selectedFeedIds].join(',')
        : undefined

      await adminApi.triggerIngest(key, {
        triggeredBy: 'api',
        dateFrom,
        dateTo,
        sources: sourcesList.join(','),
        rssFeedIds,
      })
      await fetchRuns(key)
    } catch (err) {
      if (err instanceof Error && err.message === 'ADMIN_FORBIDDEN') { clearKey(); return }
      setError(err instanceof Error ? err.message : 'Trigger failed')
    } finally {
      setTriggering(false)
    }
  }

  async function handleClearDb() {
    if (!clearConfirm) { setClearConfirm(true); return }
    setClearing(true)
    setClearConfirm(false)
    try {
      const res = await adminApi.clearDb(key)
      setRuns([])
      setError(null)
      alert(`Cleared: ${res.deleted.articles} articles, ${res.deleted.pipeline_runs} pipeline runs.`)
    } catch (err) {
      if (err instanceof Error && err.message === 'ADMIN_FORBIDDEN') { clearKey(); return }
      setError(err instanceof Error ? err.message : 'Clear failed')
    } finally {
      setClearing(false)
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
            <div className="col-span-full">
              <label className="block text-xs text-gray-500 mb-2">Sources</label>
              <div className="flex gap-6 flex-wrap">
                {/* Group 1: News & Community */}
                <div className="border border-gray-200 rounded p-2.5 flex-shrink-0">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-medium text-gray-600">News &amp; Community</span>
                    {!activeRun && (
                      <button
                        type="button"
                        onClick={() => {
                          if (selectedSources.size === ALL_SOURCES.length) {
                            setSelectedSources(new Set())
                          } else {
                            setSelectedSources(new Set(ALL_SOURCES))
                          }
                        }}
                        className="text-xs text-indigo-500 hover:underline"
                      >
                        {selectedSources.size === ALL_SOURCES.length ? 'none' : 'all'}
                      </button>
                    )}
                  </div>
                  <div className="flex flex-col gap-1.5">
                    {ALL_SOURCES.map(src => (
                      <label key={src} className={`flex items-center gap-1.5 text-xs cursor-pointer select-none ${!!activeRun ? 'opacity-50 cursor-not-allowed' : 'text-gray-600'}`}>
                        <input
                          type="checkbox"
                          checked={selectedSources.has(src)}
                          disabled={!!activeRun}
                          onChange={() => setSelectedSources(prev => {
                            const next = new Set(prev)
                            next.has(src) ? next.delete(src) : next.add(src)
                            return next
                          })}
                          className="accent-indigo-600 w-3 h-3"
                        />
                        {SOURCE_LABELS[src]}
                      </label>
                    ))}
                  </div>
                </div>

                {/* Group 2: Blogs / RSS */}
                {feeds.length > 0 && (
                  <div className="border border-gray-200 rounded p-2.5 flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs font-medium text-gray-600">Blogs / RSS</span>
                      {!activeRun && (
                        <button
                          type="button"
                          onClick={() => {
                            if (selectedFeedIds.size === feeds.length) {
                              setSelectedFeedIds(new Set())
                            } else {
                              setSelectedFeedIds(new Set(feeds.map(f => f.id)))
                            }
                          }}
                          className="text-xs text-indigo-500 hover:underline"
                        >
                          {selectedFeedIds.size === feeds.length ? 'none' : 'all'}
                        </button>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                      {feeds.map(feed => (
                        <label key={feed.id} className={`flex items-center gap-1.5 text-xs cursor-pointer select-none ${!!activeRun ? 'opacity-50 cursor-not-allowed' : 'text-gray-600'}`}>
                          <input
                            type="checkbox"
                            checked={selectedFeedIds.has(feed.id)}
                            disabled={!!activeRun}
                            onChange={() => setSelectedFeedIds(prev => {
                              const next = new Set(prev)
                              next.has(feed.id) ? next.delete(feed.id) : next.add(feed.id)
                              return next
                            })}
                            className="accent-indigo-600 w-3 h-3"
                          />
                          {feed.name}
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
            <button
              onClick={handleTrigger}
              disabled={!!activeRun || triggering || (selectedSources.size === 0 && selectedFeedIds.size === 0)}
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

        {/* Danger Zone */}
        <section className="border border-red-200 rounded p-4 space-y-2">
          <p className="text-xs font-semibold text-red-700 uppercase tracking-wide">Danger Zone</p>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-800">Clear Database</p>
              <p className="text-xs text-gray-500">Deletes all articles and pipeline run history. RSS feed sources and user profiles are preserved.</p>
            </div>
            <button
              onClick={handleClearDb}
              onBlur={() => setClearConfirm(false)}
              disabled={clearing || !!activeRun}
              className={`text-sm px-4 py-2 rounded border whitespace-nowrap transition-colors disabled:opacity-50 ${
                clearConfirm
                  ? 'bg-red-600 text-white border-red-600 hover:bg-red-700'
                  : 'border-red-300 text-red-600 hover:bg-red-50'
              }`}
            >
              {clearing ? 'Clearing…' : clearConfirm ? 'Confirm — delete all data' : 'Clear Database'}
            </button>
          </div>
        </section>

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
                    {['', '#', 'Status', 'Date range', 'Started', 'Duration', 'Fetched', 'New', 'Saved', 'Enriched'].map(h => (
                      <th key={h} className="text-left px-3 py-2 font-medium text-gray-500 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run, i) => {
                    const isLast = i === runs.length - 1
                    const isExpanded = expandedRunId === run.id
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
                        <tr
                          key={run.id}
                          onClick={() => setExpandedRunId(prev => prev === run.id ? null : run.id)}
                          className={`border-b ${isLast && !isExpanded ? 'border-transparent' : 'border-gray-100'} hover:bg-gray-50 cursor-pointer select-none`}
                        >
                          <td className="pl-3 pr-1 py-2 text-gray-300 text-xs">{isExpanded ? '▼' : '▶'}</td>
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
                        </tr>
                        {isExpanded && (
                          <tr key={`${run.id}-detail`} className={`border-b ${isLast ? 'border-transparent' : 'border-gray-100'}`}>
                            <td colSpan={10}>
                              <RunDetailPanel run={run} feeds={feeds} />
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
