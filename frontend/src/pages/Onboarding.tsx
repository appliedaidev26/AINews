import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { OnboardingFlow } from '../components/OnboardingFlow'
import { useUserProfile } from '../hooks/useUserProfile'

export function Onboarding() {
  const navigate = useNavigate()
  const { hasProfile, loading, saveProfile } = useUserProfile()

  // Returning users who already completed onboarding go straight to feed
  useEffect(() => {
    if (hasProfile) navigate('/', { replace: true })
  }, [hasProfile, navigate])

  const handleComplete = async (data: { role: string; interests: string[]; focus: string }) => {
    try {
      await saveProfile(data)
      navigate('/')
    } catch (err) {
      console.error('Failed to save profile:', err)
      alert('Failed to save your profile. Please try again.')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-lg">
        <OnboardingFlow onComplete={handleComplete} loading={loading} />
      </div>
    </div>
  )
}
