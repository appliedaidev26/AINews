import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api, type Article } from '../lib/api'
import { ArticleCard } from '../components/ArticleCard'
import { Sidebar, type SidebarFilters } from '../components/Sidebar'
import { useUserProfile } from '../hooks/useUserProfile'
import { useAuth } from '../hooks/useAuth'

const ROLE_LABELS: Record<string, string> = {
  engineering_leader: 'Eng Leader',
  ml_engineer: 'ML Engineer',
  data_scientist: 'Data Scientist',
  software_engineer: 'Software Engineer',
  researcher: 'Researcher',
}

type DatePreset = 'today' | 'yesterday' | 'week' | 'month' | 'all'

const DATE_PRESETS: { value: DatePreset; label: string }[] = [
  { value: 'today',     label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'week',      label: 'This Week' },
  { value: 'month',     label: 'This Month' },
  { value: 'all',       label: 'All' },
]

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function dateRangeForPreset(preset: DatePreset): { date_from?: string; date_to?: string } {
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const offset = (days: number) => {
    const d = new Date(today)
    d.setDate(d.getDate() - days)
    return toISODate(d)
  }

  switch (preset) {
    case 'today':     return { date_from: toISODate(today), date_to: toISODate(today) }
    case 'yesterday': return { date_from: offset(1), date_to: offset(1) }
    case 'week':      return { date_from: offset(6), date_to: toISODate(today) }
    case 'month':     return { date_from: offset(29), date_to: toISODate(today) }
    case 'all':       return {}
  }
}

export function Feed() {
  const { profile } = useUserProfile()
  const { user, signOut } = useAuth()
  const [articles, setArticles] = useState<Article[]>([])
  const [filters, setFilters] = useState<SidebarFilters>({ category: '', topics: [], sources: [] })
  const [datePreset, setDatePreset] = useState<DatePreset>('today')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  const PER_PAGE = 30

  useEffect(() => {
    setPage(1)
  }, [filters, datePreset, profile])



  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const fetchFeed = async () => {
      try {
        const tagsParam = filters.topics.length > 0 ? filters.topics.join(',') : undefined
        const sourceParam = filters.sources.length > 0 ? filters.sources.join(',') : undefined
        const dateRange = dateRangeForPreset(datePreset)

        if (profile) {
          const res = await api.getPersonalizedFeed({
            category: filters.category || undefined,
            tags: tagsParam,
            source_type: sourceParam,
            ...dateRange,
            page,
          })
          if (!cancelled) {
            setArticles(res.articles)
            setTotal(res.total)
          }
        } else {
          const res = await api.getArticles({
            category: filters.category || undefined,
            tags: tagsParam,
            source_type: sourceParam,
            ...dateRange,
            page,
            per_page: PER_PAGE,
          })
          if (!cancelled) {
            setArticles(res.articles)
            setTotal(res.articles.length + (page - 1) * PER_PAGE)
          }
        }
      } catch {
        if (!cancelled) setError('Could not load articles. Is the API running?')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchFeed()
    return () => { cancelled = true }
  }, [profile, filters, datePreset, page])

  const totalPages = Math.ceil(total / PER_PAGE)

  const welcomeName = user?.displayName?.split(' ')[0] ?? user?.email?.split('@')[0] ?? ''

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-6 pb-3 border-b border-gray-200">
        <div className="flex items-baseline gap-3">
          <h1 className="text-base font-bold text-gray-900 tracking-tight">AI News</h1>
          {welcomeName && (
            <span className="text-xs text-gray-400">Welcome, {welcomeName}</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>{new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</span>
          {profile ? (
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 bg-accent text-white rounded text-xs font-medium">
                {ROLE_LABELS[profile.role] ?? profile.role}
              </span>
              <Link to="/onboarding" className="text-gray-400 hover:text-accent">edit</Link>
              <button onClick={signOut} className="text-gray-300 hover:text-gray-500">sign out</button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 border border-gray-200 rounded text-xs text-gray-400">
                {user?.displayName ?? user?.email?.split('@')[0] ?? 'Guest'}
              </span>
              <Link to="/onboarding" className="text-accent hover:text-accent-dark font-medium">
                personalize →
              </Link>
              <button onClick={signOut} className="text-gray-300 hover:text-gray-500">sign out</button>
            </div>
          )}
        </div>
      </div>

      {/* Date filter pills */}
      <div className="flex items-center gap-1.5 mb-5">
        {DATE_PRESETS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => { setDatePreset(value); setPage(1) }}
            className={`px-3 py-1 text-xs rounded-full border transition-colors ${
              datePreset === value
                ? 'bg-indigo-600 text-white border-indigo-600'
                : 'border-gray-200 text-gray-500 hover:border-gray-400 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Two-column layout */}
      <div className="flex gap-8">
        {/* Left sidebar */}
        <Sidebar filters={filters} onChange={(f) => { setFilters(f); setPage(1) }} />

        {/* Right: article feed */}
        <div className="flex-1 min-w-0">
          {/* Loading skeleton */}
          {loading && (
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="py-2.5 border-b border-gray-100 animate-pulse">
                  <div className="flex gap-2 mb-1">
                    <div className="h-4 bg-gray-100 rounded w-16" />
                    <div className="h-4 bg-gray-100 rounded w-3/4" />
                  </div>
                  <div className="h-3 bg-gray-100 rounded w-1/3 mb-1" />
                  <div className="h-3 bg-gray-100 rounded w-full" />
                </div>
              ))}
            </div>
          )}

          {error && (
            <div className="text-xs text-red-600 py-4">{error}</div>
          )}

          {!loading && !error && articles.length === 0 && (
            <div className="py-12 text-center text-gray-400 text-sm">
              No articles found.{' '}
              {(filters.category || filters.topics.length > 0 || filters.sources.length > 0) && (
                <button
                  onClick={() => setFilters({ category: '', topics: [], sources: [] })}
                  className="underline hover:text-gray-600"
                >
                  Clear filters
                </button>
              )}
            </div>
          )}

          {/* Article list */}
          {!loading && !error && articles.length > 0 && (
            <>
              <div>
                {articles.map((article) => (
                  <ArticleCard
                    key={article.id}
                    article={article}
                    showRelevancy={!!profile}
                  />
                ))}
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-6 pt-4 border-t border-gray-100 text-xs text-gray-400">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="hover:text-gray-700 disabled:opacity-30 transition-colors"
                  >
                    ← prev
                  </button>
                  <span>{page} / {totalPages}</span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="hover:text-gray-700 disabled:opacity-30 transition-colors"
                  >
                    next →
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
