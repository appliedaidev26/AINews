import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Feed } from './pages/Feed'
import { Article } from './pages/Article'
import { Onboarding } from './pages/Onboarding'
import { Login } from './pages/Login'
import { Admin } from './pages/Admin'
import { ProtectedRoute } from './components/ProtectedRoute'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/admin" element={<Admin />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Feed />} />
          <Route path="/article/:id" element={<Article />} />
          <Route path="/onboarding" element={<Onboarding />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
