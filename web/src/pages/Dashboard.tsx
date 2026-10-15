import { useCallback, useEffect, useState } from 'react'
import { CategoryBars } from '../components/CategoryBars'
import { NetWorthChart } from '../components/NetWorthChart'
import type { AccountBalance, CategoryBar, NetWorthPoint, RecurringItem, Transaction } from '../types'
import { formatCents } from '../types'

const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  checking: 'Checking',
  savings: 'Savings',
  credit: 'Credit card',
  brokerage: 'Brokerage',
  retirement: 'Retirement',
  loan: 'Loan',
}

function timeAgo(dateStr: string): string {
  const days = Math.round((Date.now() - new Date(dateStr + 'T00:00:00').getTime()) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  return `${Math.round(days / 30)}mo ago`
}

export function Dashboard() {
  const [netWorth, setNetWorth] = useState<NetWorthPoint[]>([])
  const [balances, setBalances] = useState<AccountBalance[]>([])
  const [recent, setRecent] = useState<Transaction[]>([])
  const [categoryBars, setCategoryBars] = useState<CategoryBar[]>([])
  const [recurring, setRecurring] = useState<RecurringItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    const [nw, bal, txns, bars, rec] = await Promise.all([
      fetch('/api/networth/history?months=12').then((r) => r.json() as Promise<NetWorthPoint[]>),
      fetch('/api/accounts/current').then((r) => r.json() as Promise<AccountBalance[]>),
      fetch('/api/transactions?limit=20').then((r) => r.json() as Promise<Transaction[]>),
      fetch('/api/cashflow/category-bars').then((r) => r.json() as Promise<CategoryBar[]>),
      fetch('/api/recurring').then((r) => r.json() as Promise<RecurringItem[]>),
    ])
    setNetWorth(nw)
    setBalances(bal)
    setRecent(txns)
    setCategoryBars(bars)
    setRecurring(rec)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function refreshPrices() {
    const brokerages = balances.filter((b) => b.type === 'brokerage' || b.type === 'retirement')
    if (brokerages.length === 0) {
      setRefreshStatus('no brokerage accounts to refresh')
      return
    }
    setRefreshStatus('refreshing prices…')
    let total = 0
    for (const b of brokerages) {
      const res = await fetch(`/api/holdings/refresh?account_id=${b.account_id}`, { method: 'POST' })
      if (!res.ok) {
        // 400 when an account has no holdings seeded yet; skip it rather than fail the whole refresh
        continue
      }
      const data = await res.json()
      total += data.total_balance_cents
    }
    setRefreshStatus(`brokerage now ${formatCents(total)}`)
    await load()
  }

  const currentNetWorth = netWorth.length > 0 ? netWorth[netWorth.length - 1].net_worth_cents : null
  const monthAgoIdx = Math.max(0, netWorth.length - 31)
  const monthAgoNetWorth = netWorth.length > 0 ? netWorth[monthAgoIdx].net_worth_cents : null
  const monthDelta = currentNetWorth !== null && monthAgoNetWorth !== null ? currentNetWorth - monthAgoNetWorth : null

  const assets = balances.filter((b) => b.include_in_net_worth && (b.current_cents ?? 0) >= 0)
  const liabilities = balances.filter((b) => b.include_in_net_worth && (b.current_cents ?? 0) < 0)

  const topRecurring = recurring
    .slice()
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 5)

  return (
    <div className="space-y-6">
      {/* Hero: net worth with the trend as an ambient backdrop */}
      <div className="relative bg-panel border border-line rounded-lg p-6 overflow-hidden">
        <div className="absolute inset-0 opacity-60">
          {netWorth.length > 1 && <NetWorthChart points={netWorth} height={220} />}
        </div>
        <div className="relative flex items-start justify-between">
          <div>
            <div className="text-ink-dim text-sm mb-1">Net worth</div>
            <div className="text-5xl font-mono font-medium">
              {currentNetWorth !== null ? formatCents(currentNetWorth) : loading ? '…' : '—'}
            </div>
            {monthDelta !== null && (
              <div className={`text-sm mt-1 font-mono ${monthDelta >= 0 ? 'text-positive' : 'text-negative'}`}>
                {monthDelta >= 0 ? '+' : ''}
                {formatCents(monthDelta)} in the last 30 days
              </div>
            )}
          </div>
          <div className="text-right">
            <button
              onClick={refreshPrices}
              disabled={loading}
              className="bg-ground hover:bg-line border border-line px-3 py-1.5 rounded text-sm disabled:opacity-50"
            >
              Refresh brokerage prices
            </button>
            {refreshStatus && <p className="text-ink-dim text-xs mt-2">{refreshStatus}</p>}
          </div>
        </div>
      </div>

      {/* Accounts grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {assets.map((a) => (
          <div key={a.account_id} className="bg-panel border border-line rounded-lg p-4">
            <div className="text-ink-dim text-xs mb-1">{ACCOUNT_TYPE_LABEL[a.type] ?? a.type}</div>
            <div className="text-sm text-ink truncate mb-2">{a.name}</div>
            <div className="text-xl font-mono">{a.current_cents !== null ? formatCents(a.current_cents) : '—'}</div>
          </div>
        ))}
        {liabilities.map((a) => (
          <div key={a.account_id} className="bg-panel border border-negative/30 rounded-lg p-4">
            <div className="text-ink-dim text-xs mb-1">{ACCOUNT_TYPE_LABEL[a.type] ?? a.type} · owed</div>
            <div className="text-sm text-ink truncate mb-2">{a.name}</div>
            <div className="text-xl font-mono text-negative">{a.current_cents !== null ? formatCents(-a.current_cents) : '—'}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent activity */}
        <div className="bg-panel border border-line rounded-lg p-4">
          <h2 className="text-lg font-medium mb-3">Recent activity</h2>
          <div className="divide-y divide-line -mx-4">
            {recent.length === 0 && !loading && <p className="px-4 text-ink-dim text-sm">No transactions yet.</p>}
            {recent.map((t) => (
              <div key={t.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                <span className="text-ink-dim w-14 shrink-0 font-mono text-xs">{timeAgo(t.posted_at)}</span>
                <span className="flex-1 truncate">{t.merchant_normalized ?? t.description_raw}</span>
                <span className={`shrink-0 font-mono ${t.amount_cents < 0 ? 'text-negative' : 'text-positive'}`}>
                  {formatCents(t.amount_cents)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* This month vs. normal */}
        <div className="bg-panel border border-line rounded-lg p-4">
          <h2 className="text-lg font-medium mb-3">This month vs. your normal</h2>
          <CategoryBars rows={categoryBars} />
        </div>
      </div>

      {/* Recurring preview */}
      <div className="bg-panel border border-line rounded-lg p-4">
        <h2 className="text-lg font-medium mb-3">Recurring</h2>
        <div className="divide-y divide-line -mx-4">
          {topRecurring.length === 0 && !loading && <p className="px-4 text-ink-dim text-sm">Nothing detected yet.</p>}
          {topRecurring.map((r) => (
            <div key={r.id} className="flex items-center gap-3 px-4 py-2 text-sm">
              <span className="flex-1 truncate">{r.merchant_normalized}</span>
              <span className={`w-24 text-right shrink-0 font-mono ${r.expected_amount_cents < 0 ? 'text-negative' : 'text-positive'}`}>
                {formatCents(r.expected_amount_cents)}
              </span>
              <span className="text-ink-dim w-24 shrink-0 text-right font-mono text-xs">every {r.cadence_days}d</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
