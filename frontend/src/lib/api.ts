import { auth } from './firebase'

// In dev, Vite proxies /api → localhost:8000 (strips /api prefix)
// In prod, VITE_API_URL points directly to Cloud Run (no /api prefix)
const BASE = import.meta.env.VITE_API_URL ?? '/api'

export interface Article {
  id: number
  title: string
  original_url: string
  source_name: string
  source_type: string
  author: string | null
  published_at: string | null
  digest_date: string | null
  summary: string | null
  summary_bullets: string[]
  annotations: string[]
  why_it_matters: string | null
  practical_takeaway: string | null
  category: string | null
  tags: string[]
  audience_scores: Record<string, number>
  related_article_ids: number[]
  engagement_signal: number
  is_enriched: number
  relevancy_score?: number
}

export interface ArticleDetail extends Article {
  related_articles: {
    id: number
    title: string
    category: string | null
    source_name: string
    digest_date: string | null
  }[]
}

export interface UserProfile {
  session_id: string
  role: string
  interests: string[]
  focus: string
}

export interface FeedResponse {
  session_id: string
  page: number
  per_page: number
  total: number
  articles: Article[]
}

export interface DigestResponse {
  date: string
  total: number
  categories: Record<string, number>
  articles: Article[]
}

export interface TrendingArticle extends Article { trending_score: number }
export interface TrendingResponse { hours: number; limit: number; articles: TrendingArticle[] }

async function authHeaders(): Promise<Record<string, string>> {
  const user = auth.currentUser
  if (!user) return {}
  const token = await user.getIdToken()
  return { Authorization: `Bearer ${token}` }
}

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

async function authGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString(), { headers: await authHeaders() })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

async function authPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...await authHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json()
}

export const api = {
  getArticles: (params?: { digest_date?: string; date_from?: string; date_to?: string; category?: string; tags?: string; source_type?: string; source_name?: string; page?: number; per_page?: number }) =>
    get<{ articles: Article[]; page: number; per_page: number }>('/articles', params as Record<string, string | number>),

  getArticle: (id: number) => get<ArticleDetail>(`/articles/${id}`),

  getTrending: (params?: { hours?: number; limit?: number }) =>
    get<TrendingResponse>('/articles/trending', params as Record<string, string | number>),

  getFeedNames: () =>
    get<{ feed_names: string[] }>('/articles/source-names'),

  getDigestToday: (category?: string) =>
    get<DigestResponse>('/digest/today', category ? { category } : undefined),

  getDigest: (date: string, category?: string) =>
    get<DigestResponse>(`/digest/${date}`, category ? { category } : undefined),

  saveProfile: (profile: Omit<UserProfile, 'session_id'>) =>
    authPost<UserProfile>('/profile', profile),

  getPersonalizedFeed: (params?: { category?: string; tags?: string; source_type?: string; source_name?: string; date_from?: string; date_to?: string; page?: number }) =>
    authGet<FeedResponse>('/profile/feed', params as Record<string, string | number>),
}

// --- Admin types ---
export interface PipelineRunResult {
  fetched: number; new: number; saved: number; enriched: number
  date_from: string; date_to: string
  sources_used?: string[]
  rss_feed_ids_used?: number[] | null
}
export type PipelineStage = 'fetching' | 'filtering' | 'deduping' | 'saving' | 'enriching' | 'queued'
export type RunType = 'ingestion' | 'backfill' | 'enrichment' | 'retry'
export interface PipelineProgress {
  run_type?: RunType
  stage: PipelineStage
  fetched?: number
  new?: number
  deduped?: number
  saved?: number
  enriched?: number
  total_to_enrich?: number
  current_date?: string
  dates_completed?: number
  dates_total?: number
  date_from?: string
  date_to?: string
  // Sources metadata — written at run creation, always present
  sources_used?: string[]
  rss_feed_ids_used?: number[] | null
  rss_feed_names_used?: Record<string, string> | null  // keyed by feed id (string from JSON)
}
export interface PipelineRun {
  id: number
  started_at: string
  completed_at: string | null
  status: 'queued' | 'running' | 'success' | 'partial' | 'failed' | 'cancelled'
  target_date: string
  date_to: string | null
  triggered_by: string
  total_tasks: number | null
  result: Partial<PipelineRunResult>
  progress: Partial<PipelineProgress>
  error_message: string | null
  duration_seconds: number | null
}
export interface RunsResponse { runs: PipelineRun[]; total: number }

export interface PipelineTaskRun {
  id: number
  run_id: number
  source: string
  date: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  articles_saved: number | null
  error_message: string | null
  updated_at: string | null
}

export interface TasksResponse {
  run: PipelineRun
  tasks: PipelineTaskRun[]
}

export interface EnrichStatus {
  total_saved: number
  enriched: number
  vectorized: number
}

export interface QueueRunResponse {
  status: string
  run_id: number
  total_tasks: number
  enqueued: number
  failed_to_enqueue: number
  date_from: string
  date_to: string
  sources: string[]
}

export interface CoverageDay {
  date: string; total: number; enriched: number; pending: number; failed: number
}
export interface CoverageResponse { coverage: CoverageDay[] }

// --- Sources types ---
export interface RssFeed {
  id: number
  name: string
  url: string
  is_active: boolean
  created_at: string | null
  updated_at: string | null
}

export interface SourcesResponse {
  rss_feeds: RssFeed[]
  readonly: {
    hackernews: { min_score: number; keyword_count: number }
    reddit: { subreddits: string[]; min_upvotes: number; configured: boolean }
    arxiv: { categories: string[]; keyword_count: number }
  }
}

// --- Admin API helpers ---
async function adminFetch<T>(method: string, path: string, key: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)))
  const res = await fetch(url.toString(), { method, headers: { 'X-Admin-Key': key } })
  if (res.status === 403) throw new Error('ADMIN_FORBIDDEN')
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

async function adminFetchBody<T>(method: string, path: string, key: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'X-Admin-Key': key, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (res.status === 403) throw new Error('ADMIN_FORBIDDEN')
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new Error(data?.detail ?? `API error ${res.status}`)
  }
  return res.json()
}

export const adminApi = {
  getRuns: (key: string, limit = 50) =>
    adminFetch<RunsResponse>('GET', '/admin/runs', key, { limit }),
  getRun: (key: string, runId: number) =>
    adminFetch<PipelineRun>('GET', `/admin/runs/${runId}`, key),
  triggerIngest: (key: string, opts: {
    triggeredBy?: string;
    dateFrom?: string;       // YYYY-MM-DD
    dateTo?: string;         // YYYY-MM-DD
    sources?: string;        // comma-separated: "hn,reddit,arxiv,rss"
    rssFeedIds?: string;     // comma-separated feed IDs; omit for all active feeds
    populateTrending?: boolean;
  } = {}) =>
    adminFetch<{ status: string; date_from: string; date_to: string; run_id: number; sources: string[] }>(
      'POST', '/admin/ingest', key, {
        triggered_by: opts.triggeredBy ?? 'api',
        ...(opts.dateFrom   ? { date_from:    opts.dateFrom   } : {}),
        ...(opts.dateTo     ? { date_to:      opts.dateTo     } : {}),
        // Always send sources so the backend never falls back to its "all 4" default
        sources: opts.sources || 'hn,reddit,arxiv,rss',
        ...(opts.rssFeedIds ? { rss_feed_ids: opts.rssFeedIds } : {}),
        ...(opts.populateTrending ? { populate_trending: 'true' } : {}),
      }
    ),
  cancelRun: (key: string, runId: number) =>
    adminFetch<{ status: string; run_id: number }>('POST', `/admin/runs/${runId}/cancel`, key),
  getCoverage: (key: string, days = 90) =>
    adminFetch<CoverageResponse>('GET', '/admin/coverage', key, { days }),
  getSources: (key: string) =>
    adminFetch<SourcesResponse>('GET', '/admin/sources', key),
  addRssFeed: (key: string, feed: { name: string; url: string }) =>
    adminFetchBody<RssFeed>('POST', '/admin/sources/rss', key, feed),
  updateRssFeed: (key: string, id: number, feed: { name: string; url: string; is_active: boolean }) =>
    adminFetchBody<RssFeed>('PUT', `/admin/sources/rss/${id}`, key, feed),
  deleteRssFeed: (key: string, id: number) =>
    adminFetch<{ status: string; id: number }>('DELETE', `/admin/sources/rss/${id}`, key),
  clearDb: (key: string) =>
    adminFetch<{ status: string; deleted: { articles: number; pipeline_runs: number } }>('POST', '/admin/clear-db', key),
  enrichPending: (key: string, params?: { date_from?: string; date_to?: string }) =>
    adminFetch<{ status: string; run_id?: number; article_count: number }>(
      'POST', '/admin/enrich-pending', key,
      params && Object.keys(params).length ? params as Record<string, string> : {}
    ),

  retryFailed: async (key: string, params?: { date_from?: string; date_to?: string }) => {
    const p = new URLSearchParams()
    if (params?.date_from) p.set('date_from', params.date_from)
    if (params?.date_to) p.set('date_to', params.date_to)
    const qs = p.toString() ? `?${p}` : ''
    const res = await fetch(`${BASE}/admin/retry-failed${qs}`, {
      method: 'POST',
      headers: { 'X-Admin-Key': key },
    })
    if (res.status === 403) throw new Error('ADMIN_FORBIDDEN')
    if (!res.ok) throw new Error(await res.text())
    return res.json() as Promise<{ status: string; run_id?: number; article_count: number; date_from?: string; date_to?: string }>
  },

  queueRun: (key: string, opts: {
    dateFrom?: string
    dateTo?: string
    sources?: string
    triggeredBy?: string
  } = {}) =>
    adminFetch<QueueRunResponse>('POST', '/admin/queue-run', key, {
      ...(opts.dateFrom    ? { date_from:    opts.dateFrom    } : {}),
      ...(opts.dateTo      ? { date_to:      opts.dateTo      } : {}),
      ...(opts.sources     ? { sources:      opts.sources     } : {}),
      ...(opts.triggeredBy ? { triggered_by: opts.triggeredBy } : {}),
    }),

  getRunTasks: (key: string, runId: number) =>
    adminFetch<TasksResponse>('GET', `/admin/runs/${runId}/tasks`, key),

  getRunEnrichStatus: (key: string, runId: number) =>
    adminFetch<EnrichStatus>('GET', `/admin/runs/${runId}/enrich-status`, key),

  retryRunTasks: (key: string, runId: number) =>
    adminFetch<{ status: string; retried: number; total_failed: number }>(
      'POST', `/admin/runs/${runId}/tasks/retry`, key
    ),

  retrySingleTask: (key: string, runId: number, source: string, taskDate: string) =>
    adminFetch<{ status: string; run_id: number; source: string; date: string }>(
      'POST', `/admin/runs/${runId}/tasks/${source}/${taskDate}/retry`, key
    ),
}
