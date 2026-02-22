import { useState, useEffect } from 'react'
import {
  onAuthStateChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
  GoogleAuthProvider,
  type User,
} from 'firebase/auth'
import { auth } from '../lib/firebase'

const provider = new GoogleAuthProvider()

export function useAuth() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    return onAuthStateChanged(auth, (u) => {
      setUser(u)
      setLoading(false)
    })
  }, [])

  const signInWithGoogle = async (): Promise<User> => {
    const result = await signInWithPopup(auth, provider)
    return result.user
  }

  const signOut = async () => {
    await firebaseSignOut(auth)
  }

  return { user, loading, signInWithGoogle, signOut }
}
