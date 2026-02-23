import { useState } from 'react'
import type { ArticleDetail as ArticleDetailType } from '../lib/api'
import { Link } from 'react-router-dom'

interface Props {
  article: ArticleDetailType
}

const ROLE_LABELS: Record<string, string> = {
  ml_engineer:        'ML Engineer',
  engineering_leader: 'Eng Leader',
  data_scientist:     'Data Scientist',
  software_engineer:  'Software Eng',
  researcher:         'Researcher',
}

const ROLE_ORDER = ['ml_engineer', 'engineering_leader', 'data_scientist', 'software_engineer', 'researcher']

// A1: shared color helper — consistent with feed and trending strip
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

function AudienceBars({ scores }: { scores: Record<string, number> }) {
  const sorted = ROLE_ORDER.filter(r => scores[r] != null)
    .map(r => ({ role: r, score: scores[r] }))
    .sort((a, b) => b.score - a.score)

  return (
    <div className="space-y-1.5">
      {sorted.map(({ role, score }) => (
        <div key={role} className="flex items-center gap-2">
          <span className="text-xs text-gray-500 w-28 flex-shrink-0">{ROLE_LABELS[role] ?? role}</span>
          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-indigo-400"
              style={{ width: `${Math.round(score * 100)}%` }}
            />
          </div>
          <span className="text-xs text-gray-400 w-7 text-right">{Math.round(score * 100)}%</span>
        </div>
      ))}
    </div>
  )
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function formatShortDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function ArticleDetail({ article }: Props) {
  const topRelated = article.related_articles?.[0] ?? null
  const [showAudience, setShowAudience] = useState(false)

  return (
    <div className="max-w-2xl mx-auto">
      {/* Meta row — A1: colored category badge */}
      <div className="flex items-center gap-2 text-xs text-gray-400 mb-3 flex-wrap">
        {article.category && (
          <span className={categoryClass(article.category)}>{article.category}</span>
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

      {/* Attribution — E1: raw URL removed */}
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

      {/* Practical Takeaway */}
      {article.practical_takeaway && (
        <section className="mb-5">
          <p className="section-heading">Practical Takeaway</p>
          <p className="text-sm text-gray-700 leading-relaxed bg-indigo-50 border-l-2 border-indigo-300 pl-3 pr-3 py-2.5 rounded-r">
            {article.practical_takeaway}
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

      {/* Tags — B1: link to feed filtered by this tag */}
      {article.tags?.length > 0 && (
        <div className="flex gap-1.5 flex-wrap mb-5">
          {article.tags.map((tag) => (
            <Link
              key={tag}
              to={`/?tags=${encodeURIComponent(tag)}`}
              className="tag-pill hover:border-indigo-300 hover:text-indigo-600 transition-colors"
            >
              {tag}
            </Link>
          ))}
        </div>
      )}

      {/* Audience Relevance — C1: collapsed by default */}
      {article.audience_scores && Object.keys(article.audience_scores).length > 0 && (
        <section className="mb-5">
          <button
            onClick={() => setShowAudience((o) => !o)}
            className="section-heading flex items-center gap-1 w-full text-left"
          >
            Relevance by Role
            <span className="text-gray-300 ml-0.5">{showAudience ? '▾' : '▸'}</span>
          </button>
          {showAudience && (
            <div className="mt-2">
              <AudienceBars scores={article.audience_scores} />
            </div>
          )}
        </section>
      )}

      {/* Related Articles — B3: add colored badge, source, date */}
      {article.related_articles?.length > 0 && (
        <section>
          <div className="divider" />
          <p className="section-heading">Related</p>
          <ul className="space-y-3">
            {article.related_articles.map((rel) => (
              <li key={rel.id} className="flex items-start gap-2">
                <span className="text-gray-300 select-none flex-shrink-0 mt-0.5">→</span>
                <div>
                  <Link
                    to={`/article/${rel.id}`}
                    className="text-sm text-gray-800 hover:text-accent leading-snug block"
                  >
                    {rel.title}
                  </Link>
                  <div className="flex items-center gap-1.5 mt-1">
                    {rel.category && (
                      <span className={categoryClass(rel.category)}>{rel.category}</span>
                    )}
                    <span className="text-xs text-gray-400">{rel.source_name}</span>
                    {rel.digest_date && (
                      <span className="text-xs text-gray-300">· {formatShortDate(rel.digest_date)}</span>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* D2: Up next card — top related article as a clear continue-reading CTA */}
      {topRelated && (
        <div className="mt-6">
          <p className="section-heading mb-2">Up next</p>
          <Link
            to={`/article/${topRelated.id}`}
            className="block border border-gray-200 rounded p-3 hover:border-indigo-300 transition-colors group"
          >
            <div className="flex items-center gap-1.5 mb-1.5">
              {topRelated.category && (
                <span className={categoryClass(topRelated.category)}>{topRelated.category}</span>
              )}
              <span className="text-xs text-gray-400">{topRelated.source_name}</span>
              {topRelated.digest_date && (
                <span className="text-xs text-gray-300">· {formatShortDate(topRelated.digest_date)}</span>
              )}
            </div>
            <p className="text-sm font-medium text-gray-800 group-hover:text-indigo-600 leading-snug">
              {topRelated.title}
            </p>
          </Link>
        </div>
      )}

      {/* B2: Read original — repeated at the bottom after the user has read everything */}
      <div className="mt-5 pt-4 border-t border-gray-100">
        <a
          href={article.original_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-medium text-accent hover:text-accent-dark transition-colors"
        >
          Read original article ↗
        </a>
      </div>
    </div>
  )
}
