import { useState, useEffect, useCallback } from 'react'
import { auth } from '../lib/firebase'
import { api, type UserProfile } from '../lib/api'

export const profileStorageKey = (uid: string) => `ainews_profile_${uid}`

export function useUserProfile() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(false)

  // Load persisted profile from localStorage once auth is ready
  useEffect(() => {
    const user = auth.currentUser
    if (!user) return
    const stored = localStorage.getItem(profileStorageKey(user.uid))
    if (stored) {
      try {
        setProfile(JSON.parse(stored))
      } catch {
        localStorage.removeItem(profileStorageKey(user.uid))
      }
    }
  }, [])

  const saveProfile = useCallback(async (data: Omit<UserProfile, 'session_id'>) => {
    const user = auth.currentUser
    if (!user) throw new Error('Not authenticated')
    setLoading(true)
    try {
      await api.saveProfile(data)
      const stored: UserProfile = { ...data, session_id: user.uid }
      localStorage.setItem(profileStorageKey(user.uid), JSON.stringify(stored))
      setProfile(stored)
    } finally {
      setLoading(false)
    }
  }, [])

  const clearProfile = useCallback(() => {
    const user = auth.currentUser
    if (user) localStorage.removeItem(profileStorageKey(user.uid))
    setProfile(null)
  }, [])

  return { profile, hasProfile: profile !== null, loading, saveProfile, clearProfile }
}
