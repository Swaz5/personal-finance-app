import { useCallback, useEffect, useState } from 'react'
import type { Category, RecurringItem, Transaction } from '../types'
import { formatCents } from '../types'

export function Categorize() {
  const [categories, setCategories] = useState<Category[]>([])
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [recurring, setRecurring] = useState<RecurringItem[]>([])
  const [loading, setLoading] = useState(false)
  const [runStatus, setRunStatus] = useState<string | null>(null)
  const [recurringStatus, setRecurringStatus] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [cats, txns, rec] = await Promise.all([
        fetch('/api/categories').then((r) => r.json() as Promise<Category[]>),
        fetch('/api/transactions?limit=2000').then((r) => r.json() as Promise<Transaction[]>),
        fetch('/api/recurring').then((r) => r.json() as Promise<RecurringItem[]>),
      ])
      setCategories(cats)
      setTransactions(txns)
      setRecurring(rec)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const total = transactions.length
  const categorized = transactions.filter((t) => t.category_id !== null).length
  const pct = total > 0 ? ((categorized / total) * 100).toFixed(1) : '0.0'
  const uncategorized = transactions
    .filter((t) => t.category_id === null)
    .sort((a, b) => (a.posted_at < b.posted_at ? 1 : -1))

  async function runRules() {
    setRunStatus('running rules + transfers…')
    const res = await fetch('/api/categorize/run', { method: 'POST' })
    const data = await res.json()
    setRunStatus(
      `transfers: ${data.transfers_assigned}, rules: ${data.rules_assigned}, still uncategorized: ${data.still_uncategorized}`,
    )
    await refresh()
  }

  async function runLlm() {
    setRunStatus('running LLM fallback (this can take a while on CPU)…')
    const res = await fetch('/api/categorize/llm-fallback', { method: 'POST' })
    if (!res.ok) {
      setRunStatus(`LLM fallback failed: HTTP ${res.status}`)
      await refresh()
      return
    }
    const data = await res.json()
    setRunStatus(`LLM assigned: ${data.llm_assigned}, still uncategorized: ${data.still_uncategorized}`)
    await refresh()
  }

  async function categorize(txnId: number, categoryId: number) {
    await fetch(`/api/transactions/${txnId}/categorize?category_id=${categoryId}`, { method: 'POST' })
    setTransactions((prev) => prev.map((t) => (t.id === txnId ? { ...t, category_id: categoryId } : t)))
  }

  async function runRecurring() {
    setRecurringStatus('scanning…')
    const res = await fetch('/api/recurring/detect', { method: 'POST' })
    const data = await res.json()
    setRecurringStatus(`found ${data.recurring_found} recurring patterns`)
    await refresh()
  }

  return (
    <div>
      <div className="bg-panel border border-line rounded p-4 mb-6">
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-3xl font-mono">{pct}%</span>
            <span className="text-ink-dim ml-2">
              categorized ({categorized} / {total})
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={runRules}
              disabled={loading}
              className="bg-ground hover:bg-line border border-line px-3 py-1.5 rounded text-sm disabled:opacity-50"
            >
              Run rules + transfers
            </button>
            <button
              onClick={runLlm}
              disabled={loading}
              className="bg-ground hover:bg-line border border-line px-3 py-1.5 rounded text-sm disabled:opacity-50"
            >
              Run LLM fallback
            </button>
          </div>
        </div>
        <div className="w-full bg-line rounded-full h-2">
          <div className="bg-positive h-2 rounded-full transition-all" style={{ width: `${pct}%` }} />
        </div>
        {runStatus && <p className="text-ink-dim text-xs mt-2">{runStatus}</p>}
      </div>

      <h2 className="text-lg mb-2 font-medium">Needs a category ({uncategorized.length})</h2>
      <div className="border border-line rounded divide-y divide-line mb-8">
        {uncategorized.length === 0 && !loading && (
          <p className="p-4 text-ink-dim text-sm">Nothing left to categorize.</p>
        )}
        {uncategorized.map((t) => (
          <div key={t.id} className="flex items-center gap-3 p-3 text-sm">
            <span className="text-ink-dim w-24 shrink-0 font-mono">{t.posted_at}</span>
            <span className="flex-1 truncate">{t.description_raw}</span>
            <span className={`w-24 text-right shrink-0 font-mono ${t.amount_cents < 0 ? 'text-negative' : 'text-positive'}`}>
              {formatCents(t.amount_cents)}
            </span>
            <select
              className="bg-ground border border-line rounded px-2 py-1 text-sm"
              defaultValue=""
              onChange={(e) => {
                const id = Number(e.target.value)
                if (id) categorize(t.id, id)
              }}
            >
              <option value="" disabled>
                category…
              </option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-medium">Recurring ({recurring.length})</h2>
        <button
          onClick={runRecurring}
          disabled={loading}
          className="bg-panel hover:bg-line border border-line px-3 py-1.5 rounded text-sm disabled:opacity-50"
        >
          Re-scan
        </button>
      </div>
      {recurringStatus && <p className="text-ink-dim text-xs mb-2">{recurringStatus}</p>}
      <div className="border border-line rounded divide-y divide-line">
        {recurring.length === 0 && !loading && <p className="p-4 text-ink-dim text-sm">No recurring patterns detected yet.</p>}
        {recurring
          .slice()
          .sort((a, b) => b.confidence - a.confidence)
          .map((r) => (
            <div key={r.id} className="flex items-center gap-3 p-3 text-sm">
              <span className="flex-1 truncate">{r.merchant_normalized}</span>
              <span className={`w-24 text-right shrink-0 font-mono ${r.expected_amount_cents < 0 ? 'text-negative' : 'text-positive'}`}>
                {formatCents(r.expected_amount_cents)}
              </span>
              <span className="text-ink-dim w-20 shrink-0 text-right font-mono">every {r.cadence_days}d</span>
              <span className="text-ink-dim w-24 shrink-0 text-right font-mono">next {r.next_expected}</span>
              <span className="text-ink-dim w-16 shrink-0 text-right font-mono">{(r.confidence * 100).toFixed(0)}%</span>
            </div>
          ))}
      </div>
    </div>
  )
}
