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
  summary_bullets: string[]
  annotations: string[]
  why_it_matters: string | null
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
  getArticles: (params?: { digest_date?: string; category?: string; tags?: string; source_type?: string; page?: number; per_page?: number }) =>
    get<{ articles: Article[]; page: number; per_page: number }>('/articles', params as Record<string, string | number>),

  getArticle: (id: number) => get<ArticleDetail>(`/articles/${id}`),

  getDigestToday: (category?: string) =>
    get<DigestResponse>('/digest/today', category ? { category } : undefined),

  getDigest: (date: string, category?: string) =>
    get<DigestResponse>(`/digest/${date}`, category ? { category } : undefined),

  saveProfile: (profile: Omit<UserProfile, 'session_id'>) =>
    authPost<UserProfile>('/profile', profile),

  getPersonalizedFeed: (params?: { category?: string; tags?: string; source_type?: string; page?: number }) =>
    authGet<FeedResponse>('/profile/feed', params as Record<string, string | number>),
}

// --- Admin types ---
export interface PipelineRunResult { fetched: number; new: number; saved: number; enriched: number; date: string }
export type PipelineStage = 'fetching' | 'filtering' | 'deduping' | 'saving' | 'enriching'
export interface PipelineProgress {
  stage: PipelineStage
  fetched?: number
  new?: number
  deduped?: number
  saved?: number
  enriched?: number
  total_to_enrich?: number
}
export interface PipelineRun {
  id: number
  started_at: string
  completed_at: string | null
  status: 'running' | 'success' | 'failed' | 'cancelled'
  target_date: string
  triggered_by: string
  result: Partial<PipelineRunResult>
  progress: Partial<PipelineProgress>
  error_message: string | null
  duration_seconds: number | null
}
export interface RunsResponse { runs: PipelineRun[]; total: number }

// --- Admin API helpers ---
async function adminFetch<T>(method: string, path: string, key: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)))
  const res = await fetch(url.toString(), { method, headers: { 'X-Admin-Key': key } })
  if (res.status === 403) throw new Error('ADMIN_FORBIDDEN')
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

export const adminApi = {
  getRuns: (key: string, limit = 50) =>
    adminFetch<RunsResponse>('GET', '/admin/runs', key, { limit }),
  getRun: (key: string, runId: number) =>
    adminFetch<PipelineRun>('GET', `/admin/runs/${runId}`, key),
  triggerIngest: (key: string, triggeredBy = 'api', targetDate?: string) =>
    adminFetch<{ status: string; date: string; run_id: number }>(
      'POST', '/admin/ingest', key,
      { triggered_by: triggeredBy, ...(targetDate ? { target_date: targetDate } : {}) }
    ),
  cancelRun: (key: string, runId: number) =>
    adminFetch<{ status: string; run_id: number }>('POST', `/admin/runs/${runId}/cancel`, key),
}
