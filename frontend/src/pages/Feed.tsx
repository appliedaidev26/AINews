import { useState, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Article } from '../lib/api'
import { ArticleCard } from '../components/ArticleCard'
import { Sidebar, type SidebarFilters } from '../components/Sidebar'
import { TrendingStrip } from '../components/TrendingStrip'
import { useUserProfile } from '../hooks/useUserProfile'
import { useAuth } from '../hooks/useAuth'

const ROLE_LABELS: Record<string, string> = {
  engineering_leader: 'Eng Leader',
  ml_engineer: 'ML Engineer',
  data_scientist: 'Data Scientist',
  software_engineer: 'Software Engineer',
  researcher: 'Researcher',
}

type DatePreset = 'today' | 'week' | 'month' | 'pick_month' | 'all'

const DATE_PRESETS: { value: DatePreset; label: string }[] = [
  { value: 'today',      label: 'Today' },
  { value: 'week',       label: 'This Week' },
  { value: 'month',      label: 'This Month' },
  { value: 'all',        label: 'All' },
]

function toISODate(d: Date): string {
  // Use local date parts to avoid UTC offset shifting the date (e.g. Jan 1 local → Dec 31 UTC in UTC+ zones)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// Generate last N calendar months as { value: 'YYYY-MM', label: 'Mon YYYY' }
function recentMonths(count = 12) {
  const months = []
  const d = new Date()
  for (let i = 0; i < count; i++) {
    const label = d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    months.push({ value, label })
    d.setMonth(d.getMonth() - 1)
  }
  return months
}

const MONTHS = recentMonths(12)

function dateRangeForPreset(preset: DatePreset, rangeFrom: string | null, rangeTo: string | null): { date_from?: string; date_to?: string } {
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const offset = (days: number) => {
    const d = new Date(today)
    d.setDate(d.getDate() - days)
    return toISODate(d)
  }

  switch (preset) {
    case 'today':  return { date_from: toISODate(today), date_to: toISODate(today) }
    case 'week':   return { date_from: offset(6), date_to: toISODate(today) }
    case 'month': {
      const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
      return { date_from: toISODate(firstOfMonth), date_to: toISODate(today) }
    }
    case 'all':    return {}
    case 'pick_month': {
      if (!rangeFrom && !rangeTo) return {}
      const from = rangeFrom ?? rangeTo!
      const to   = rangeTo   ?? rangeFrom!
      const [fy, fm] = from.split('-').map(Number)
      const [ty, tm] = to.split('-').map(Number)
      return {
        date_from: toISODate(new Date(fy, fm - 1, 1)),
        date_to:   toISODate(new Date(ty, tm, 0)),
      }
    }
  }
}

export function Feed() {
  const { profile } = useUserProfile()
  const { user, signOut } = useAuth()
  const [searchParams] = useSearchParams()
  const [articles, setArticles] = useState<Article[]>([])
  const [filters, setFilters] = useState<SidebarFilters>(() => {
    // Pre-populate tag filter when navigating from an article detail tag link (?tags=llms)
    const tag = searchParams.get('tags')
    return { category: '', topics: tag ? [tag] : [], sources: [], blogs: [] }
  })
  const [datePreset, setDatePreset] = useState<DatePreset>('all')
  const [rangeFrom, setRangeFrom] = useState<string | null>(MONTHS[0].value)
  const [rangeTo,   setRangeTo]   = useState<string | null>(MONTHS[0].value)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<'relevancy' | 'date'>(profile ? 'relevancy' : 'date')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  const PER_PAGE = 30

  const [feedNames, setFeedNames] = useState<string[]>([])

  useEffect(() => {
    api.getFeedNames()
      .then((res) => setFeedNames(res.feed_names))
      .catch(() => {})
  }, [])

  // Sync sortBy default when profile loads/unloads
  useEffect(() => {
    setSortBy(profile ? 'relevancy' : 'date')
  }, [profile])

  useEffect(() => {
    setPage(1)
  }, [filters, datePreset, rangeFrom, rangeTo, profile, sortBy])



  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const fetchFeed = async () => {
      try {
        const tagsParam = filters.topics.length > 0 ? filters.topics.join(',') : undefined
        const sourceParam = filters.sources.length > 0 ? filters.sources.join(',') : undefined
        const sourceNameParam = filters.blogs.length > 0 ? filters.blogs.join(',') : undefined
        const dateRange = dateRangeForPreset(datePreset, rangeFrom, rangeTo)

        if (profile) {
          const res = await api.getPersonalizedFeed({
            category: filters.category || undefined,
            tags: tagsParam,
            source_type: sourceParam,
            source_name: sourceNameParam,
            sort_by: sortBy,
            ...dateRange,
            page,
            per_page: PER_PAGE,
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
            source_name: sourceNameParam,
            sort_by: sortBy === 'relevancy' ? 'engagement' : 'date',
            ...dateRange,
            page,
            per_page: PER_PAGE,
          })
          if (!cancelled) {
            setArticles(res.articles)
            setTotal(res.total)
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
  }, [profile, filters, datePreset, rangeFrom, rangeTo, page, sortBy])

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

      {/* Date filter pills + Sort toggle */}
      <div className="flex items-center gap-1.5 mb-5 flex-wrap">
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
        {/* Month range picker — two selects in one bordered pill */}
        <div className={`flex items-center gap-1 px-2 py-0.5 rounded-full border transition-colors ${
          datePreset === 'pick_month'
            ? 'border-indigo-600'
            : 'border-gray-200 hover:border-gray-400'
        }`}>
          <select
            value={rangeFrom ?? ''}
            onChange={(e) => {
              const v = e.target.value
              setRangeFrom(v)
              if (rangeTo && v > rangeTo) setRangeTo(v)
              setDatePreset('pick_month')
              setPage(1)
            }}
            className={`text-xs appearance-none cursor-pointer bg-transparent outline-none ${
              datePreset === 'pick_month' ? 'text-indigo-600' : 'text-gray-500'
            }`}
          >
            <option value="" disabled>From…</option>
            {MONTHS.map(({ value, label }) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <span className={`text-xs ${datePreset === 'pick_month' ? 'text-indigo-400' : 'text-gray-300'}`}>–</span>
          <select
            value={rangeTo ?? ''}
            onChange={(e) => {
              const v = e.target.value
              setRangeTo(v)
              if (rangeFrom && v < rangeFrom) setRangeFrom(v)
              setDatePreset('pick_month')
              setPage(1)
            }}
            className={`text-xs appearance-none cursor-pointer bg-transparent outline-none ${
              datePreset === 'pick_month' ? 'text-indigo-600' : 'text-gray-500'
            }`}
          >
            <option value="" disabled>To…</option>
            {MONTHS.map(({ value, label }) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        {/* Sort dropdown — only shown when user has a profile */}
        {profile && (
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as 'relevancy' | 'date')}
            className="ml-auto text-xs rounded-full border border-gray-200 px-3 py-1 bg-transparent
                       text-gray-500 cursor-pointer outline-none hover:border-gray-400"
          >
            <option value="relevancy">Sort: Relevance</option>
            <option value="date">Sort: Date</option>
          </select>
        )}
      </div>

      {/* Trending strip */}
      <TrendingStrip />

      {/* Two-column layout */}
      <div className="flex gap-8">
        {/* Left sidebar */}
        <Sidebar filters={filters} onChange={(f) => { setFilters(f); setPage(1) }} feedNames={feedNames} />

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
            <div className="py-12 text-center space-y-1">
              <p className="text-sm text-gray-500">No articles to show.</p>
              {(filters.category || filters.topics.length > 0 || filters.sources.length > 0 || filters.blogs.length > 0) ? (
                <p className="text-xs text-gray-400">
                  Try{' '}
                  <button
                    onClick={() => setFilters({ category: '', topics: [], sources: [], blogs: [] })}
                    className="underline hover:text-gray-600"
                  >
                    clearing the filters
                  </button>
                  {' '}or selecting a different date range.
                </p>
              ) : (
                <p className="text-xs text-gray-400">Try selecting a wider date range.</p>
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

              {/* Article count */}
              {total > 0 && (
                <div className="mt-3 text-xs text-gray-400">
                  Showing {(page - 1) * PER_PAGE + 1}–{Math.min(page * PER_PAGE, total)} of {total} articles
                </div>
              )}

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-3 pt-4 border-t border-gray-100 text-xs text-gray-400">
                  <button
                    onClick={() => { setPage((p) => Math.max(1, p - 1)); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
                    disabled={page === 1}
                    className="hover:text-gray-700 disabled:opacity-30 transition-colors"
                  >
                    ← prev
                  </button>
                  <span>{page} / {totalPages}</span>
                  <button
                    onClick={() => { setPage((p) => Math.min(totalPages, p + 1)); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
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
