import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Feed } from './pages/Feed'
import { Article } from './pages/Article'
import { Onboarding } from './pages/Onboarding'
import { Login } from './pages/Login'
import { Admin } from './pages/Admin'
import { BackfillDetail } from './pages/BackfillDetail'
import { ProtectedRoute } from './components/ProtectedRoute'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/admin/backfill/:runId" element={<BackfillDetail />} />
        <Route path="/admin/runs" element={<Navigate to="/admin" replace />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Feed />} />
          <Route path="/article/:id" element={<Article />} />
          <Route path="/onboarding" element={<Onboarding />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
