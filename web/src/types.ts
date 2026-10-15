export type HealthResponse = { status: string }

export type Category = {
  id: number
  name: string
  kind: string
  parent_id: number | null
}

export type Transaction = {
  id: number
  account_id: number
  posted_at: string
  amount_cents: number
  description_raw: string
  merchant_normalized: string | null
  category_id: number | null
  is_transfer: boolean
}

export type RecurringItem = {
  id: number
  merchant_normalized: string
  expected_amount_cents: number
  cadence_days: number
  last_seen: string
  next_expected: string
  confidence: number
}

export type AccountItem = {
  id: number
  name: string
  type: string
}

export type AccountBalance = {
  account_id: number
  name: string
  type: string
  include_in_net_worth: boolean
  current_cents: number | null
  as_of: string | null
}

export type SavingsEffect = {
  old_rate: number
  new_rate: number
  monthly_income_cents: number
  recurring_monthly_cents: number
}

export type DayPoint = { day: string; balance_cents: number }

export type AffordabilityResult = {
  verdict: 'green' | 'yellow' | 'red'
  reasons: string[]
  current_balance_cents: number
  post_purchase_balance_cents: number
  emergency_floor_cents: number
  projection: {
    daily: DayPoint[]
    trough: DayPoint
    patterns_used: number
    stale_patterns_excluded: number
  }
  savings_effect: SavingsEffect | null
  opportunity_cost_cents: Record<string, number>
}

export const VERDICT_LABEL: Record<AffordabilityResult['verdict'], string> = {
  green: 'Looks fine',
  yellow: 'Close call',
  red: "Can't afford it",
}

export const VERDICT_STYLES: Record<AffordabilityResult['verdict'], string> = {
  green: 'bg-positive/15 text-positive border-positive/40',
  yellow: 'bg-flag/15 text-flag border-flag/40',
  red: 'bg-negative/15 text-negative border-negative/40',
}

export type NetWorthPoint = {
  day: string
  net_worth_cents: number
}

export type RetirementScenario = {
  real_return: number
  projected_value_cents: number
  coast_fi_cents: number
  on_track: boolean
  is_coasting: boolean
  gap_or_surplus_cents: number
}

export type RetirementResult = {
  target_amount_cents: number
  target_date: string
  years: number
  current_invested_cents: number
  monthly_contribution_cents: number
  annual_contribution_cents: number
  scenarios: RetirementScenario[]
}

export type CategoryBar = {
  category_id: number
  category: string
  kind: string
  current_cents: number
  median_cents: number
}

export function formatCents(cents: number): string {
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function formatShort(cents: number): string {
  const abs = Math.abs(cents)
  if (abs >= 100_000_00) return `$${(cents / 100_00_00).toFixed(1)}M`
  if (abs >= 100_000) return `$${(cents / 100_000).toFixed(1)}K`
  return formatCents(cents)
}
