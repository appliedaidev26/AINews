import { Link } from 'react-router-dom'
import type { Article } from '../lib/api'

interface Props {
  article: Article
  showRelevancy?: boolean
}

function categoryClass(category: string | null): string {
  if (!category) return 'category-badge'
  const key = category.toLowerCase()
  if (key.startsWith('research')) return 'category-badge-research'
  if (key.startsWith('tools')) return 'category-badge-tools'
  if (key.startsWith('industry')) return 'category-badge-industry'
  if (key.startsWith('policy')) return 'category-badge-policy'
  if (key.startsWith('tutorial')) return 'category-badge-tutorials'
  return 'category-badge'
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function ArticleCard({ article, showRelevancy = false }: Props) {
  const bullets = article.summary_bullets?.slice(0, 2) ?? []
  const tags = article.tags?.slice(0, 4) ?? []

  return (
    <div className="py-2.5 border-b border-gray-100 last:border-0 -mx-2 px-2 rounded hover:bg-gray-50 transition-colors">
      {/* Title row: badge + title */}
      <div className="flex items-baseline gap-2 mb-0.5">
        {article.category && (
          <span className={`${categoryClass(article.category)} flex-shrink-0`}>{article.category}</span>
        )}
        <Link
          to={`/article/${article.id}`}
          className="font-medium text-gray-900 hover:text-accent leading-snug"
        >
          {article.title}
        </Link>
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-1 text-xs text-gray-400 mb-1">
        {showRelevancy && article.relevancy_score !== undefined && article.relevancy_score > 0 && (
          <span className="text-accent font-medium mr-1">
            {Math.round(article.relevancy_score * 100)}%
          </span>
        )}
        <span>{article.source_name}</span>
        {article.engagement_signal > 0 && (
          <>
            <span>·</span>
            <span>{article.engagement_signal} pts</span>
          </>
        )}
        <span>·</span>
        <span>{formatDate(article.published_at || article.digest_date)}</span>
        <a
          href={article.original_url}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-0.5 text-gray-300 hover:text-accent"
          title="Open original"
        >
          ↗
        </a>
      </div>

      {/* Bullet preview */}
      {bullets.length > 0 && (
        <ul className="text-xs text-gray-500 space-y-0.5 mb-1.5 pl-0.5">
          {bullets.map((bullet, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="text-gray-300 flex-shrink-0 select-none">–</span>
              <span>{bullet}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Tags */}
      {tags.length > 0 && (
        <div className="flex gap-1 flex-wrap">
          {tags.map((tag) => (
            <span key={tag} className="tag-pill">{tag}</span>
          ))}
        </div>
      )}
    </div>
  )
}
