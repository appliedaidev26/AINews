import { useState } from 'react'

const CATEGORIES = [
  { value: '', label: 'All' },
  { value: 'Research', label: 'Research' },
  { value: 'Tools & Libraries', label: 'Tools & Libraries' },
  { value: 'Industry News', label: 'Industry News' },
  { value: 'Policy & Ethics', label: 'Policy & Ethics' },
  { value: 'Tutorials', label: 'Tutorials' },
]

const TOPICS = [
  'LLMs', 'Computer Vision', 'MLOps', 'Open Source',
  'Research Papers', 'Policy & Ethics', 'Tutorials', 'Robotics', 'Fine-tuning',
  'RAG', 'Agents',
]

const SOURCES = [
  { value: 'hn', label: 'Hacker News' },
  { value: 'reddit', label: 'Reddit' },
  { value: 'arxiv', label: 'Arxiv' },
  { value: 'grok', label: 'Grok' },
]

const BLOGS = [
  'OpenAI Blog',
  'Anthropic Blog',
  'Google DeepMind',
  'HuggingFace Blog',
  'Google AI Blog',
  'Meta AI Blog',
  'The Gradient',
  'Import AI',
  'Simon Willison',
  'Towards Data Science',
]

export interface SidebarFilters {
  category: string
  topics: string[]
  sources: string[]
  blogs: string[]
}

interface Props {
  filters: SidebarFilters
  onChange: (filters: SidebarFilters) => void
  feedNames?: string[]   // dynamic feed names loaded from backend; falls back to BLOGS
}

function ActiveCount({ count }: { count: number }) {
  if (count === 0) return null
  return (
    <span className="ml-1 text-xs font-semibold bg-indigo-100 text-indigo-600 px-1.5 py-0.5 rounded-full leading-none normal-case tracking-normal">
      {count}
    </span>
  )
}

export function Sidebar({ filters, onChange, feedNames }: Props) {
  const effectiveBlogs = feedNames && feedNames.length > 0 ? feedNames : BLOGS
  const [blogsOpen, setBlogsOpen] = useState(true)

  const setCategory = (value: string) =>
    onChange({ ...filters, category: value })

  const toggleTopic = (topic: string) => {
    const topics = filters.topics.includes(topic)
      ? filters.topics.filter((t) => t !== topic)
      : [...filters.topics, topic]
    onChange({ ...filters, topics })
  }

  const toggleSource = (source: string) => {
    const sources = filters.sources.includes(source)
      ? filters.sources.filter((s) => s !== source)
      : [...filters.sources, source]
    onChange({ ...filters, sources })
  }

  const toggleBlog = (blog: string) => {
    const blogs = filters.blogs.includes(blog)
      ? filters.blogs.filter((b) => b !== blog)
      : [...filters.blogs, blog]
    onChange({ ...filters, blogs })
  }

  const hasActiveFilters =
    filters.category !== '' ||
    filters.topics.length > 0 ||
    filters.sources.length > 0 ||
    filters.blogs.length > 0

  return (
    <aside className="w-44 flex-shrink-0 pr-6">
      {hasActiveFilters && (
        <button
          onClick={() => onChange({ category: '', topics: [], sources: [], blogs: [] })}
          className="text-xs text-accent hover:text-accent-dark mb-4 block"
        >
          ✕ Clear filters
        </button>
      )}

      {/* Categories */}
      <div className="mb-6">
        <div className="section-heading">Category</div>
        <ul className="space-y-1.5">
          {CATEGORIES.map((cat) => (
            <li key={cat.value}>
              <button
                onClick={() => setCategory(cat.value)}
                className={`
                  text-xs w-full text-left transition-colors
                  ${filters.category === cat.value
                    ? 'text-gray-900 font-semibold'
                    : 'text-gray-500 hover:text-gray-800'
                  }
                `}
              >
                {filters.category === cat.value && (
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent mr-1.5 mb-0.5" />
                )}
                {cat.label}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {/* Topics */}
      <div className="mb-6">
        <div className="section-heading flex items-center justify-between">
          <span>Topics<ActiveCount count={filters.topics.length} /></span>
        </div>
        <ul className="space-y-1.5">
          {TOPICS.map((topic) => {
            const active = filters.topics.includes(topic)
            return (
              <li key={topic}>
                <label className="flex items-center gap-1.5 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => toggleTopic(topic)}
                    className="accent-blue-600 w-3 h-3 flex-shrink-0"
                  />
                  <span className={`text-xs transition-colors ${active ? 'text-gray-900 font-medium' : 'text-gray-500 group-hover:text-gray-800'}`}>
                    {topic}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
      </div>

      {/* Sources */}
      <div className="mb-6">
        <div className="section-heading flex items-center justify-between">
          <span>Sources<ActiveCount count={filters.sources.length} /></span>
        </div>
        <ul className="space-y-1.5">
          {SOURCES.map((src) => {
            const active = filters.sources.includes(src.value)
            return (
              <li key={src.value}>
                <label className="flex items-center gap-1.5 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => toggleSource(src.value)}
                    className="accent-blue-600 w-3 h-3 flex-shrink-0"
                  />
                  <span className={`text-xs transition-colors ${active ? 'text-gray-900 font-medium' : 'text-gray-500 group-hover:text-gray-800'}`}>
                    {src.label}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
      </div>

      {/* Blogs — collapsible */}
      <div className="mb-6">
        <button
          onClick={() => setBlogsOpen((o) => !o)}
          className="section-heading flex items-center justify-between w-full text-left"
        >
          <span>Blogs<ActiveCount count={filters.blogs.length} /></span>
          <span className="text-gray-300 ml-1">{blogsOpen ? '▾' : '▸'}</span>
        </button>
        {blogsOpen && (
          <ul className="space-y-1.5">
            {effectiveBlogs.map((blog) => {
              const active = filters.blogs.includes(blog)
              return (
                <li key={blog}>
                  <label className="flex items-center gap-1.5 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => toggleBlog(blog)}
                      className="accent-blue-600 w-3 h-3 flex-shrink-0"
                    />
                    <span className={`text-xs transition-colors ${active ? 'text-gray-900 font-medium' : 'text-gray-500 group-hover:text-gray-800'}`}>
                      {blog}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </aside>
  )
}
