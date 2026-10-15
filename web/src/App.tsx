import { useEffect, useState } from 'react'
import { Dashboard } from './pages/Dashboard'
import { Categorize } from './pages/Categorize'
import { Afford } from './pages/Afford'
import type { HealthResponse } from './types'

type Page = 'dashboard' | 'categorize' | 'afford'

const PAGES: { id: Page; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'categorize', label: 'Categorize' },
  { id: 'afford', label: 'Afford' },
]

function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<HealthResponse>
      })
      .then(setHealth)
      .catch((err: Error) => setHealthError(err.message))
  }, [])

  return (
    <main className="min-h-svh bg-ground text-ink px-6 py-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-baseline gap-6">
            <h1 className="text-2xl font-medium">Personal Finance OS</h1>
            <nav className="flex gap-1">
              {PAGES.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPage(p.id)}
                  className={`px-3 py-1.5 rounded text-sm ${
                    page === p.id ? 'bg-panel text-ink' : 'text-ink-dim hover:text-ink'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </nav>
          </div>
          <p className="text-sm font-mono">
            API:{' '}
            {healthError ? (
              <span className="text-negative">error — {healthError}</span>
            ) : health ? (
              <span className="text-positive">{health.status}</span>
            ) : (
              <span className="text-ink-dim">checking…</span>
            )}
          </p>
        </div>

        {page === 'dashboard' && <Dashboard />}
        {page === 'categorize' && <Categorize />}
        {page === 'afford' && <Afford />}
      </div>
    </main>
  )
}

export default App
