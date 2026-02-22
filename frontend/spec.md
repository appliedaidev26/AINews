# Plan: Onboarding Flow with Google Sign-In

## Context
The app currently uses anonymous UUIDs for session identity. We need a proper auth layer
(Google sign-in via Firebase Auth) gating access to the app, with a single-page onboarding
form that captures role/interests/focus for first-time users. Returning users skip onboarding
and go straight to the feed. The backend verifies Firebase ID tokens so user identity is
cryptographically trusted.

---

## User Flow

```
Visit app (any URL)
  └─ Not signed in → /login
       └─ Click "Continue with Google"
            └─ Google OAuth popup
                 ├─ Profile exists → /  (feed, skip onboarding)
                 └─ No profile    → /onboarding
                                       └─ Fill role + interests + focus
                                            └─ Submit → /  (feed)
```

---

## Architecture Decisions

- **session_id replaced by Google UID** — the Firebase-verified `uid` becomes the user's
  stable identity in the backend (stored in `UserProfile.session_id` column)
- **Only profile routes are protected** — `/articles` remain public; POST/GET `/profile/*`
  require a valid Bearer token
- **Firebase Admin SDK** verifies the token server-side; no JWT secret to manage manually
- **Frontend Firebase SDK** handles the Google OAuth popup and returns an ID token

---

## Files to Create

| File | Purpose |
|------|---------|
| `frontend/src/lib/firebase.ts` | Firebase app + Auth init |
| `frontend/src/hooks/useAuth.ts` | Auth state (user, loading, signIn, signOut) |
| `frontend/src/pages/Login.tsx` | Google sign-in landing page |
| `frontend/src/components/ProtectedRoute.tsx` | Redirects unauthenticated users to /login |

---

## Files to Modify

| File | Change |
|------|--------|
| `frontend/package.json` | Add `firebase` SDK |
| `frontend/src/App.tsx` | Add `/login` route; wrap Feed + Article + Onboarding in `<ProtectedRoute>` |
| `frontend/src/lib/api.ts` | Inject `Authorization: Bearer <idToken>` on profile API calls |
| `frontend/src/hooks/useUserProfile.ts` | Use Google UID as session_id (not random UUID); expose `hasProfile` for routing |
| `frontend/src/pages/Onboarding.tsx` | Pre-fill form if profile exists; on mount check profile → redirect to feed if already set |
| `backend/requirements.txt` | Add `firebase-admin` |
| `backend/config.py` | Add `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS` settings |
| `backend/api/main.py` | Initialize Firebase Admin on startup; expose `get_current_uid` dependency |
| `backend/api/routes/profile.py` | Use verified UID from token instead of client-provided session_id |
| `.env.example` | Add `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS` |

---

## Implementation Steps

### 1. Firebase project setup (manual — user does this once)
- Create Firebase project (or reuse existing)
- Enable Google as a Sign-In provider in Firebase Console → Authentication
- Copy the Firebase config object (apiKey, authDomain, projectId, etc.)
- Download a service account JSON for backend verification
- Set env vars: `VITE_FIREBASE_*` (frontend), `FIREBASE_PROJECT_ID` + `GOOGLE_APPLICATION_CREDENTIALS` (backend)

### 2. Backend: Firebase Admin + auth dependency

**`backend/requirements.txt`** — add:
```
firebase-admin>=6.5.0
```

**`backend/config.py`** — add fields:
```python
firebase_project_id: str = ""
google_application_credentials: str = ""  # path to service account JSON
```

**`backend/api/main.py`** — initialize on startup:
```python
import firebase_admin
from firebase_admin import credentials, auth as fb_auth

@app.on_event("startup")
async def startup():
    if settings.google_application_credentials:
        cred = credentials.Certificate(settings.google_application_credentials)
    else:
        cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
```

Add a FastAPI dependency:
```python
async def get_current_uid(authorization: str = Header(...)) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    decoded = fb_auth.verify_id_token(token)
    return decoded["uid"]
```

**`backend/api/routes/profile.py`** — replace `session_id` param with `uid = Depends(get_current_uid)`:
```python
@router.post("/profile")
async def save_profile(data: ProfileCreate, uid: str = Depends(get_current_uid), ...):
    # use uid instead of data.session_id
```

### 3. Frontend: Firebase SDK + Auth hook

**`frontend/src/lib/firebase.ts`**:
```ts
import { initializeApp } from 'firebase/app'
import { getAuth } from 'firebase/auth'

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
}

export const app = initializeApp(firebaseConfig)
export const auth = getAuth(app)
```

**`frontend/src/hooks/useAuth.ts`**:
```ts
// wraps onAuthStateChanged; exposes user, loading, signInWithGoogle(), signOut()
// signInWithGoogle uses GoogleAuthProvider + signInWithPopup
// returns idToken via user.getIdToken()
```

**`frontend/src/components/ProtectedRoute.tsx`**:
```ts
// if loading → spinner
// if !user → <Navigate to="/login" />
// else → <Outlet />
```

**`frontend/src/pages/Login.tsx`**:
```ts
// Centered card: app name/tagline + "Continue with Google" button
// On click: signInWithGoogle() → navigate based on profile existence
```

### 4. Frontend: API token injection

**`frontend/src/lib/api.ts`** — add a helper to get the current token:
```ts
import { auth } from './firebase'

async function authHeaders() {
  const user = auth.currentUser
  if (!user) return {}
  const token = await user.getIdToken()
  return { Authorization: `Bearer ${token}` }
}
// Add headers to profile POST and GET /profile/feed calls only
```

### 5. Frontend: Routing

**`frontend/src/App.tsx`**:
```tsx
<Routes>
  <Route path="/login" element={<Login />} />
  <Route element={<ProtectedRoute />}>
    <Route path="/" element={<Feed />} />
    <Route path="/article/:id" element={<Article />} />
    <Route path="/onboarding" element={<Onboarding />} />
  </Route>
</Routes>
```

### 6. Frontend: useUserProfile hook update

- Remove `crypto.randomUUID()` logic
- `session_id` = `auth.currentUser.uid` (Google UID)
- Add `hasProfile: boolean` state (set after checking localStorage or API)
- Expose `hasProfile` so Login page can route new vs returning users

### 7. Onboarding page update

- On mount: if `hasProfile` → navigate to `/`
- No other changes needed (form and submit logic unchanged)

---

## New env vars required

**Frontend (`.env.local`):**
```
VITE_FIREBASE_API_KEY=
VITE_FIREBASE_AUTH_DOMAIN=
VITE_FIREBASE_PROJECT_ID=
```

**Backend (`.env`):**
```
FIREBASE_PROJECT_ID=
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

---

## Verification

1. `npm install` in `frontend/` (adds firebase package)
2. Start backend: `uvicorn backend.api.main:app --reload` — confirm no startup errors
3. Start frontend: `npm run dev`
4. Visit `http://localhost:5173` → should redirect to `/login`
5. Click "Continue with Google" → Google popup → completes auth
6. First time: lands on `/onboarding`; fill form → submit → lands on `/`
7. Sign out and sign in again → lands directly on `/` (skips onboarding)
8. `curl` the profile endpoint without a token → expect 401
9. `curl` with a valid token → expect 200
