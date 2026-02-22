import type { ArticleDetail as ArticleDetailType } from '../lib/api'
import { Link } from 'react-router-dom'

interface Props {
  article: ArticleDetailType
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

export function ArticleDetail({ article }: Props) {
  return (
    <div className="max-w-2xl mx-auto">
      {/* Meta row */}
      <div className="flex items-center gap-2 text-xs text-gray-400 mb-3 flex-wrap">
        {article.category && (
          <span className="category-badge">{article.category}</span>
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
      </div>

      {/* Title */}
      <h1 className="text-xl font-bold text-gray-900 leading-snug mb-3">
        {article.title}
      </h1>

      {/* Attribution */}
      <div className="flex items-center gap-3 text-xs text-gray-400 pb-4 mb-5 border-b border-gray-200">
        {article.author && (
          <span>by <span className="text-gray-600">{article.author}</span></span>
        )}
        <a
          href={article.original_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:text-accent-dark font-medium"
        >
          Read original ↗
        </a>
        <span className="text-gray-300 truncate max-w-xs hidden sm:block">
          {article.original_url}
        </span>
      </div>

      {/* Summary */}
      {article.summary_bullets?.length > 0 && (
        <section className="mb-5">
          <p className="section-heading">Summary</p>
          <ul className="space-y-1.5">
            {article.summary_bullets.map((bullet, i) => (
              <li key={i} className="flex gap-2.5 text-sm text-gray-700">
                <span className="text-gray-300 flex-shrink-0 select-none mt-0.5">—</span>
                <span>{bullet}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Why it Matters */}
      {article.why_it_matters && (
        <section className="mb-5">
          <p className="section-heading">Why it Matters</p>
          <p className="text-sm text-gray-700 leading-relaxed bg-gray-50 border border-gray-200 rounded px-3 py-2.5">
            {article.why_it_matters}
          </p>
        </section>
      )}

      {/* Notable Quotes */}
      {article.annotations?.length > 0 && (
        <section className="mb-5">
          <p className="section-heading">Notable Quotes</p>
          <div className="space-y-2.5">
            {article.annotations.map((quote, i) => (
              <blockquote
                key={i}
                className="border-l-2 border-accent pl-3 text-sm text-gray-600 italic leading-relaxed"
              >
                {quote}
              </blockquote>
            ))}
          </div>
        </section>
      )}

      {/* Tags */}
      {article.tags?.length > 0 && (
        <div className="flex gap-1.5 flex-wrap mb-5">
          {article.tags.map((tag) => (
            <span key={tag} className="tag-pill">{tag}</span>
          ))}
        </div>
      )}

      {/* Related Articles */}
      {article.related_articles?.length > 0 && (
        <section>
          <div className="divider" />
          <p className="section-heading">Related</p>
          <ul className="space-y-1.5">
            {article.related_articles.map((rel) => (
              <li key={rel.id} className="flex items-baseline gap-2 text-sm">
                <span className="text-gray-300 select-none flex-shrink-0">→</span>
                <Link
                  to={`/article/${rel.id}`}
                  className="text-gray-800 hover:text-accent"
                >
                  {rel.title}
                </Link>
                {rel.category && (
                  <span className="category-badge flex-shrink-0">{rel.category}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
