import { useEffect, useMemo, useState } from 'react'
import { TroughChart } from '../components/TroughChart'
import type { AccountItem, AffordabilityResult, RetirementResult } from '../types'
import { VERDICT_LABEL, VERDICT_STYLES, formatCents } from '../types'

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(t)
  }, [value, delayMs])
  return debounced
}

export function Afford() {
  const [accounts, setAccounts] = useState<AccountItem[]>([])
  const [retirement, setRetirement] = useState<RetirementResult | null>(null)

  const [affAccountId, setAffAccountId] = useState<number | null>(null)
  const [affAmount, setAffAmount] = useState('')
  const [affDate, setAffDate] = useState('')
  const [affRecurring, setAffRecurring] = useState('')
  const [affResult, setAffResult] = useState<AffordabilityResult | null>(null)
  const [affError, setAffError] = useState<string | null>(null)
  const [affLoading, setAffLoading] = useState(false)

  useEffect(() => {
    fetch('/api/accounts')
      .then((r) => r.json() as Promise<AccountItem[]>)
      .then((accts) => {
        setAccounts(accts)
        if (accts.length > 0) setAffAccountId(accts[0].id)
      })
    fetch('/api/goals')
      .then((r) => r.json() as Promise<{ id: number; kind: string }[]>)
      .then((goals) => {
        const retirementGoal = goals.find((g) => g.kind === 'retirement')
        if (retirementGoal) {
          fetch(`/api/retirement/projection?goal_id=${retirementGoal.id}`)
            .then((r) => r.json() as Promise<RetirementResult>)
            .then(setRetirement)
        }
      })
  }, [])

  const debouncedAmount = useDebounced(affAmount, 400)
  const debouncedRecurring = useDebounced(affRecurring, 400)

  useEffect(() => {
    if (!affAccountId || !debouncedAmount) {
      setAffResult(null)
      return
    }
    let cancelled = false
    setAffLoading(true)
    setAffError(null)
    const params = new URLSearchParams({
      account_id: String(affAccountId),
      amount_cents: String(Math.round(Number(debouncedAmount) * 100)),
    })
    if (affDate) params.set('purchase_date', affDate)
    if (debouncedRecurring) params.set('recurring_monthly_cents', String(Math.round(Number(debouncedRecurring) * 100)))
    fetch(`/api/affordability/check?${params}`, { method: 'POST' })
      .then((res) => {
        if (cancelled) return
        if (!res.ok) {
          setAffError(`HTTP ${res.status}`)
          return
        }
        return res.json().then((data: AffordabilityResult) => {
          if (!cancelled) setAffResult(data)
        })
      })
      .finally(() => {
        if (!cancelled) setAffLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [affAccountId, debouncedAmount, affDate, debouncedRecurring])

  const affAccount = useMemo(() => accounts.find((a) => a.id === affAccountId), [accounts, affAccountId])

  return (
    <div>
      <div className="bg-panel border border-line rounded p-4 mb-6">
        <h2 className="text-lg font-medium mb-4">Can I afford it?</h2>
        <div className="flex flex-wrap items-end gap-3 mb-4">
          <label className="text-sm">
            <span className="block text-ink-dim mb-1">Account</span>
            <select
              className="bg-ground border border-line rounded px-2 py-1.5 font-mono"
              value={affAccountId ?? ''}
              onChange={(e) => setAffAccountId(Number(e.target.value))}
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-ink-dim mb-1">If I spend ($)</span>
            <input
              type="number"
              className="bg-ground border border-line rounded px-2 py-1.5 w-32 font-mono"
              value={affAmount}
              onChange={(e) => setAffAmount(e.target.value)}
              placeholder="5000"
              autoFocus
            />
          </label>
          <label className="text-sm">
            <span className="block text-ink-dim mb-1">On (optional)</span>
            <input
              type="date"
              className="bg-ground border border-line rounded px-2 py-1.5 font-mono"
              value={affDate}
              onChange={(e) => setAffDate(e.target.value)}
            />
          </label>
          <label className="text-sm">
            <span className="block text-ink-dim mb-1">+ new monthly payment ($, if financed)</span>
            <input
              type="number"
              className="bg-ground border border-line rounded px-2 py-1.5 w-44 font-mono"
              value={affRecurring}
              onChange={(e) => setAffRecurring(e.target.value)}
              placeholder="550"
            />
          </label>
          {affLoading && <span className="text-ink-dim text-sm">computing…</span>}
        </div>

        {affError && <p className="text-negative text-sm mb-3">{affError}</p>}

        {affResult ? (
          <>
            <div className="flex items-center gap-3 mb-3">
              <div className={`inline-block border rounded px-3 py-1 text-sm ${VERDICT_STYLES[affResult.verdict]}`}>
                {VERDICT_LABEL[affResult.verdict]}
              </div>
              <span className="text-ink-dim text-sm">on {affAccount?.name ?? 'this account'}</span>
            </div>
            <TroughChart
              daily={affResult.projection.daily}
              floorCents={affResult.emergency_floor_cents}
              troughDay={affResult.projection.trough.day}
            />
            <ul className="text-sm space-y-1 mt-3">
              {affResult.reasons.map((r, i) => (
                <li key={i} className="text-ink">
                  {r}
                </li>
              ))}
            </ul>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm mt-3 font-mono">
              <div>
                <div className="text-ink-dim font-sans">Current balance</div>
                <div>{formatCents(affResult.current_balance_cents)}</div>
              </div>
              <div>
                <div className="text-ink-dim font-sans">Post-purchase</div>
                <div>{formatCents(affResult.post_purchase_balance_cents)}</div>
              </div>
              <div>
                <div className="text-ink-dim font-sans">Emergency floor</div>
                <div>{formatCents(affResult.emergency_floor_cents)}</div>
              </div>
              <div>
                <div className="text-ink-dim font-sans">Opportunity cost, 10y</div>
                <div>{formatCents(affResult.opportunity_cost_cents['10'] ?? 0)}</div>
              </div>
            </div>
            {affResult.savings_effect && (
              <p className="text-sm mt-3">
                <span className="text-ink-dim">Savings rate: </span>
                {(affResult.savings_effect.old_rate * 100).toFixed(1)}% →{' '}
                {(affResult.savings_effect.new_rate * 100).toFixed(1)}%
              </p>
            )}
            <p className="text-ink-dim text-xs mt-3">
              Uses {affResult.projection.patterns_used} active recurring pattern(s) on this account (
              {affResult.projection.stale_patterns_excluded} excluded as no-longer-active).
            </p>
          </>
        ) : (
          <p className="text-ink-dim text-sm">Enter an amount to see the 90-day trough shift.</p>
        )}
      </div>

      {retirement && (
        <div className="bg-panel border border-line rounded p-4">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-lg font-medium">Retirement pacing</h2>
            <span className="text-ink-dim text-sm font-mono">
              {formatCents(retirement.target_amount_cents)} by {retirement.target_date} ({retirement.years}y)
            </span>
          </div>
          <p className="text-ink-dim text-sm mb-3">
            Invested today: {formatCents(retirement.current_invested_cents)} · trailing monthly contribution:{' '}
            {formatCents(retirement.monthly_contribution_cents)}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {retirement.scenarios.map((s) => (
              <div key={s.real_return} className="border border-line rounded p-3">
                <div className="text-ink-dim text-sm mb-1">{(s.real_return * 100).toFixed(0)}% real return</div>
                <div className="text-xl mb-1 font-mono">{formatCents(s.projected_value_cents)}</div>
                <div className={s.on_track ? 'text-positive text-sm' : 'text-negative text-sm'}>
                  {s.on_track ? 'on track' : `short by ${formatCents(-s.gap_or_surplus_cents)}`}
                </div>
                <div className="text-ink-dim text-xs mt-2">
                  Coast FI: {formatCents(s.coast_fi_cents)}
                  {s.is_coasting && <span className="text-positive"> — already coasting</span>}
                </div>
              </div>
            ))}
          </div>
          <p className="text-ink-dim text-xs mt-3">
            Scenario tool, not a prediction. Contribution rate is your trailing 3-month actual net cash flow,
            annualized — not a promise you'll keep saving at this rate.
          </p>
        </div>
      )}
    </div>
  )
}
