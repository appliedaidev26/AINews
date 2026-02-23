import { Link } from 'react-router-dom'
import { type TrendingArticle } from '../lib/api'

interface Props {
  articles: TrendingArticle[]
  loading: boolean
}

export function TrendingStrip({ articles, loading }: Props) {
  if (!loading && articles.length === 0) return null

  return (
    <div className="mb-5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Trending</span>
        <span className="text-xs text-gray-300">Last 48h</span>
      </div>
      <div className="relative">
        <div className="flex gap-3 overflow-x-auto pb-2">
          {loading
            ? Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="w-52 flex-shrink-0 border border-gray-200 rounded p-3 animate-pulse">
                  <div className="h-3 bg-gray-100 rounded w-16 mb-2" />
                  <div className="h-4 bg-gray-100 rounded w-full mb-1" />
                  <div className="h-4 bg-gray-100 rounded w-3/4 mb-2" />
                  <div className="h-3 bg-gray-100 rounded w-1/2" />
                </div>
              ))
            : articles.map((article, idx) => (
                <Link
                  key={article.id}
                  to={`/article/${article.id}`}
                  className="w-52 flex-shrink-0 border border-gray-200 rounded p-3 hover:border-indigo-300 transition-colors group"
                >
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <span className="text-xs font-bold text-gray-300">#{idx + 1}</span>
                    {article.category && (
                      <span className="text-xs px-1.5 py-0.5 bg-gray-50 text-gray-400 border border-gray-100 rounded">
                        {article.category}
                      </span>
                    )}
                  </div>
                  <p className="text-xs font-medium text-gray-800 line-clamp-2 group-hover:text-indigo-600 mb-1.5 leading-snug">
                    {article.title}
                  </p>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-400 truncate">{article.source_name}</span>
                    {article.engagement_signal > 0 && (
                      <span className="text-xs text-gray-300 ml-2 flex-shrink-0">{article.engagement_signal} pts</span>
                    )}
                  </div>
                </Link>
              ))}
        </div>
        {/* Right-edge fade signals more content is scrollable */}
        <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-white to-transparent" />
      </div>
    </div>
  )
}
