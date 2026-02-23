import { useState } from 'react'

const ROLES = [
  { id: 'engineering_leader', label: 'Engineering Leader' },
  { id: 'ml_engineer', label: 'ML Engineer' },
  { id: 'data_scientist', label: 'Data Scientist' },
  { id: 'software_engineer', label: 'Software Engineer' },
  { id: 'researcher', label: 'Researcher' },
]

const INTERESTS = [
  'LLMs', 'Computer Vision', 'MLOps', 'Policy & Ethics',
  'Open Source', 'Research Papers', 'Industry News', 'Tutorials', 'Robotics',
]

const FOCUSES = [
  { id: 'keeping_up', label: 'Keeping up with the field' },
  { id: 'practitioner', label: 'Hands-on practitioner' },
  { id: 'team_leader', label: 'Leading a team building AI' },
]

interface Props {
  onComplete: (data: { role: string; interests: string[]; focus: string }) => void
  loading?: boolean
}

export function OnboardingFlow({ onComplete, loading = false }: Props) {
  const [role, setRole] = useState('')
  const [interests, setInterests] = useState<string[]>([])
  const [focus, setFocus] = useState('')

  const toggleInterest = (interest: string) => {
    setInterests((prev) =>
      prev.includes(interest) ? prev.filter((i) => i !== interest) : [...prev, interest]
    )
  }

  const canSubmit = role && interests.length > 0 && focus && !loading

  return (
    <div className="max-w-lg mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Personalize your feed</h1>
        <p className="text-sm text-gray-500">Takes about 30 seconds — no account required</p>
      </div>

      {/* Role */}
      <section className="mb-7">
        <div className="text-xs text-gray-400 mb-1">Step 1 of 3</div>
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
          I am a...
        </h2>
        <div className="flex flex-wrap gap-2">
          {ROLES.map((r) => (
            <button
              key={r.id}
              onClick={() => setRole(r.id)}
              className={`
                px-4 py-2 text-sm rounded border transition-colors
                ${role === r.id
                  ? 'bg-accent text-white border-accent'
                  : 'bg-white text-gray-700 border-gray-200 hover:border-accent hover:text-accent'
                }
              `}
            >
              {r.label}
            </button>
          ))}
        </div>
      </section>

      {/* Interests */}
      <section className="mb-7">
        <div className="text-xs text-gray-400 mb-1">Step 2 of 3</div>
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
          I care about... <span className="text-gray-400 font-normal normal-case">(pick any)</span>
        </h2>
        <div className="flex flex-wrap gap-2">
          {INTERESTS.map((interest) => (
            <button
              key={interest}
              onClick={() => toggleInterest(interest)}
              className={`
                px-3 py-1.5 text-sm rounded border transition-colors
                ${interests.includes(interest)
                  ? 'bg-accent-light text-accent border-accent'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-accent hover:text-accent'
                }
              `}
            >
              {interest}
            </button>
          ))}
        </div>
      </section>

      {/* Focus */}
      <section className="mb-8">
        <div className="text-xs text-gray-400 mb-1">Step 3 of 3</div>
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
          My focus is...
        </h2>
        <div className="flex flex-wrap gap-2">
          {FOCUSES.map((f) => (
            <button
              key={f.id}
              onClick={() => setFocus(f.id)}
              className={`
                px-4 py-2 text-sm rounded border transition-colors
                ${focus === f.id
                  ? 'bg-accent text-white border-accent'
                  : 'bg-white text-gray-700 border-gray-200 hover:border-accent hover:text-accent'
                }
              `}
            >
              {f.label}
            </button>
          ))}
        </div>
      </section>

      <button
        onClick={() => canSubmit && onComplete({ role, interests, focus })}
        disabled={!canSubmit}
        className={`
          w-full py-3 rounded text-sm font-semibold transition-colors
          ${canSubmit
            ? 'bg-accent text-white hover:bg-accent-dark'
            : 'bg-gray-100 text-gray-400 cursor-not-allowed'
          }
        `}
      >
        {loading ? 'Saving...' : 'Take me to my feed →'}
      </button>
    </div>
  )
}
