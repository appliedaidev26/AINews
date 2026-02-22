const CATEGORIES = [
  'All',
  'Research',
  'Tools & Libraries',
  'Industry News',
  'Policy & Ethics',
  'Tutorials',
]

interface Props {
  active: string
  onChange: (cat: string) => void
}

export function CategoryFilter({ active, onChange }: Props) {
  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-none flex-wrap">
      {CATEGORIES.map((cat) => {
        const isActive = (cat === 'All' && active === '') || active === cat
        return (
          <button
            key={cat}
            onClick={() => onChange(cat === 'All' ? '' : cat)}
            className={`
              flex-shrink-0 px-2 py-0.5 text-xs rounded transition-colors
              ${isActive
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700'
              }
            `}
          >
            {cat}
          </button>
        )
      })}
    </div>
  )
}
