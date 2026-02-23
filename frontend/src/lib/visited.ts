// Shared localStorage-backed visited article tracking (TTL: 7 days)
const VISITED_KEY = 'ainews_visited'
const VISITED_TTL_MS = 7 * 24 * 60 * 60 * 1000

export function getVisitedIds(): Set<number> {
  try {
    const raw = localStorage.getItem(VISITED_KEY)
    if (!raw) return new Set()
    const entries: [number, number][] = JSON.parse(raw)
    const now = Date.now()
    return new Set(entries.filter(([, ts]) => now - ts < VISITED_TTL_MS).map(([id]) => id))
  } catch {
    return new Set()
  }
}

export function markVisited(id: number): void {
  try {
    const raw = localStorage.getItem(VISITED_KEY)
    const entries: [number, number][] = raw ? JSON.parse(raw) : []
    const now = Date.now()
    const filtered = entries.filter(([eid, ts]) => eid !== id && now - ts < VISITED_TTL_MS)
    filtered.push([id, now])
    localStorage.setItem(VISITED_KEY, JSON.stringify(filtered))
  } catch {
    // localStorage unavailable — silently ignore
  }
}
