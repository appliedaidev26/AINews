import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { api, type TrendingArticle } from '../lib/api'
import { getVisitedIds, markVisited } from '../lib/visited'

const HOUR_OPTIONS = [
  { value: 24,  label: '24h' },
  { value: 48,  label: '48h' },
  { value: 168, label: '7d'  },
]

// One card (w-52 = 208px) + one gap (gap-3 = 12px)
const CARD_STEP = 220

function categoryClass(category: string | null): string {
  if (!category) return 'category-badge'
  const key = category.toLowerCase()
  if (key.startsWith('research')) return 'category-badge-research'
  if (key.startsWith('tools'))    return 'category-badge-tools'
  if (key.startsWith('industry')) return 'category-badge-industry'
  if (key.startsWith('policy'))   return 'category-badge-policy'
  if (key.startsWith('tutorial')) return 'category-badge-tutorials'
  return 'category-badge'
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function TrendingStrip() {
  const [hours, setHours] = useState(48)
  const [articles, setArticles] = useState<TrendingArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [visitedIds, setVisitedIds] = useState<Set<number>>(() => getVisitedIds())
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setLoading(true)
    api.getTrending({ hours, limit: 8 })
      .then((res) => setArticles(res.articles))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [hours])

  // Update scroll-arrow visibility on load and while scrolling
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const update = () => {
      setCanScrollLeft(el.scrollLeft > 0)
      setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1)
    }

    // Small delay so the DOM has settled after articles render
    const timer = setTimeout(update, 50)
    el.addEventListener('scroll', update, { passive: true })
    return () => {
      clearTimeout(timer)
      el.removeEventListener('scroll', update)
    }
  }, [articles])

  const scroll = (dir: 1 | -1) => {
    scrollRef.current?.scrollBy({ left: dir * CARD_STEP, behavior: 'smooth' })
  }

  const handleVisit = (id: number) => {
    markVisited(id)
    setVisitedIds((prev) => new Set([...prev, id]))
  }

  if (!loading && articles.length === 0) return null

  return (
    <div className="mb-5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Trending</span>
        <div className="flex items-center gap-3">
          {/* Scroll arrows */}
          <div className="flex items-center gap-0.5">
            <button
              onClick={() => scroll(-1)}
              disabled={!canScrollLeft}
              className="text-base leading-none text-gray-300 hover:text-gray-600 disabled:opacity-25 disabled:cursor-default px-0.5 transition-colors"
              aria-label="Scroll left"
            >
              ‹
            </button>
            <button
              onClick={() => scroll(1)}
              disabled={!canScrollRight}
              className="text-base leading-none text-gray-300 hover:text-gray-600 disabled:opacity-25 disabled:cursor-default px-0.5 transition-colors"
              aria-label="Scroll right"
            >
              ›
            </button>
          </div>
          {/* Time window toggle */}
          <div className="flex items-center gap-0.5">
            {HOUR_OPTIONS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setHours(value)}
                className={`text-xs px-2 py-0.5 rounded transition-colors ${
                  hours === value
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-400 hover:text-gray-600'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="relative">
        <div ref={scrollRef} className="flex gap-3 overflow-x-auto pb-2">
          {loading
            ? Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="w-52 flex-shrink-0 border border-gray-200 rounded p-3 animate-pulse">
                  <div className="h-3 bg-gray-100 rounded w-16 mb-2" />
                  <div className="h-4 bg-gray-100 rounded w-full mb-1" />
                  <div className="h-4 bg-gray-100 rounded w-3/4 mb-2" />
                  <div className="h-3 bg-gray-100 rounded w-1/2" />
                </div>
              ))
            : articles.map((article, idx) => {
                const visited = visitedIds.has(article.id)
                const pubDate = formatDate(article.published_at || article.digest_date)
                return (
                  <Link
                    key={article.id}
                    to={`/article/${article.id}`}
                    onClick={() => handleVisit(article.id)}
                    className="w-52 flex-shrink-0 border border-gray-200 rounded p-3 hover:border-indigo-300 transition-colors group"
                  >
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <span className="text-xs font-bold text-gray-300">#{idx + 1}</span>
                      {article.category && (
                        <span className={categoryClass(article.category)}>{article.category}</span>
                      )}
                    </div>
                    <p className={`text-xs font-medium line-clamp-2 group-hover:text-indigo-600 mb-1.5 leading-snug ${
                      visited ? 'text-gray-400' : 'text-gray-800'
                    }`}>
                      {article.title}
                    </p>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400 truncate">
                        {article.source_name}
                        {pubDate && <span className="text-gray-300"> · {pubDate}</span>}
                      </span>
                      {article.engagement_signal > 0 && (
                        <span className="text-xs text-gray-300 ml-2 flex-shrink-0">{article.engagement_signal} pts</span>
                      )}
                    </div>
                  </Link>
                )
              })}
        </div>
        {/* Edge fades — left appears once user has scrolled right */}
        {canScrollLeft && (
          <div className="pointer-events-none absolute inset-y-0 left-0 w-10 bg-gradient-to-r from-white to-transparent" />
        )}
        <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-white to-transparent" />
      </div>
    </div>
  )
}
