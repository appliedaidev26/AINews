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
  { value: 'rss', label: 'Blogs & RSS' },
]

export interface SidebarFilters {
  category: string
  topics: string[]
  sources: string[]
}

interface Props {
  filters: SidebarFilters
  onChange: (filters: SidebarFilters) => void
}

export function Sidebar({ filters, onChange }: Props) {
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

  const hasActiveFilters =
    filters.category !== '' || filters.topics.length > 0 || filters.sources.length > 0

  return (
    <aside className="w-44 flex-shrink-0 pr-6">
      {hasActiveFilters && (
        <button
          onClick={() => onChange({ category: '', topics: [], sources: [] })}
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
        <div className="section-heading">Topics</div>
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
        <div className="section-heading">Sources</div>
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
    </aside>
  )
}
