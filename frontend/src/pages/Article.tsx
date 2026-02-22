import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api, type ArticleDetail as ArticleDetailType } from '../lib/api'
import { ArticleDetail } from '../components/ArticleDetail'

export function Article() {
  const { id } = useParams<{ id: string }>()
  const [article, setArticle] = useState<ArticleDetailType | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setLoading(true)

    api.getArticle(Number(id))
      .then((data) => { if (!cancelled) setArticle(data) })
      .catch(() => { if (!cancelled) setError('Article not found') })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [id])

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      {/* Back nav */}
      <div className="mb-5 pb-3 border-b border-gray-200">
        <Link to="/" className="text-xs text-gray-400 hover:text-gray-700 transition-colors">
          ← back to feed
        </Link>
      </div>

      {loading && (
        <div className="animate-pulse space-y-3">
          <div className="flex gap-2 mb-2">
            <div className="h-4 bg-gray-100 rounded w-20" />
            <div className="h-4 bg-gray-100 rounded w-1/3" />
          </div>
          <div className="h-6 bg-gray-100 rounded w-3/4" />
          <div className="h-3 bg-gray-100 rounded w-full mt-4" />
          <div className="h-3 bg-gray-100 rounded w-5/6" />
          <div className="h-3 bg-gray-100 rounded w-4/6" />
        </div>
      )}

      {error && (
        <p className="text-xs text-red-500">{error}</p>
      )}

      {!loading && !error && article && <ArticleDetail article={article} />}
    </div>
  )
}
