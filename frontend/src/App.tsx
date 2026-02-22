import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Feed } from './pages/Feed'
import { Article } from './pages/Article'
import { Onboarding } from './pages/Onboarding'
import { Login } from './pages/Login'
import { ProtectedRoute } from './components/ProtectedRoute'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Feed />} />
          <Route path="/article/:id" element={<Article />} />
          <Route path="/onboarding" element={<Onboarding />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
