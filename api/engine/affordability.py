"""The payoff feature. Four factors, a verdict with the actual numbers
attached — never a vibe. See BUILD_PLAN.md section 4.

1. Post-purchase cash vs. emergency floor.
2. Effect on the 90-day cash trough.
3. Recurring vs. one-time — new monthly payment's effect on savings rate.
4. Opportunity cost — what the amount compounds to at the assumed real
   return over 10/20/30 years.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from sqlmodel import Session

from engine.cashflow import monthly_totals_by_kind
from engine.projection import ProjectionResult, project_cash_forward
from models import Settings

TROUGH_BUFFER = 0.20  # within 20% above the floor still counts as a close call
SAVINGS_RATE_DROP_YELLOW = 0.05  # 5 percentage points
OPPORTUNITY_COST_YEARS = (10, 20, 30)

Verdict = Literal["green", "yellow", "red"]


@dataclass
class SavingsRateEffect:
    old_rate: float
    new_rate: float
    monthly_income_cents: int
    recurring_monthly_cents: int


@dataclass
class AffordabilityResult:
    verdict: Verdict
    reasons: list[str]
    current_balance_cents: int
    post_purchase_balance_cents: int
    emergency_floor_cents: int
    projection: ProjectionResult
    savings_effect: SavingsRateEffect | None
    opportunity_cost_cents: dict[int, int] = field(default_factory=dict)


def _recent_savings_rate(session: Session, months: int, as_of: date) -> tuple[float, int]:
    """Average savings rate over the last N complete calendar months
    (excludes the current, likely-partial month). Returns (rate, avg_monthly_income_cents)."""
    year, month = as_of.year, as_of.month
    totals = []
    for i in range(1, months + 1):
        total = year * 12 + (month - 1) - i
        y, m = total // 12, total % 12 + 1
        totals.append(monthly_totals_by_kind(session, y, m))

    incomes = [t.get("income", 0) for t in totals]
    avg_income = round(sum(incomes) / len(incomes)) if incomes else 0
    if avg_income == 0:
        return 0.0, 0

    nets = [
        t.get("income", 0) + t.get("fixed", 0) + t.get("variable", 0) + t.get("discretionary", 0)
        for t in totals
    ]
    avg_net = sum(nets) / len(nets)
    return avg_net / avg_income, avg_income


def check_affordability(
    session: Session,
    account_id: int,
    amount_cents: int,
    purchase_date: date | None = None,
    recurring_monthly_cents: int = 0,
    savings_rate_months: int = 3,
) -> AffordabilityResult:
    amount_cents = abs(amount_cents)
    purchase_date = purchase_date or date.today()

    projection = project_cash_forward(
        session,
        account_id,
        days=90,
        as_of=purchase_date,
        hypothetical_amount_cents=amount_cents,
        hypothetical_date=purchase_date,
    )
    current_balance = projection.starting_balance_cents
    post_purchase_balance = current_balance - amount_cents

    settings = session.get(Settings, 1)
    floor = settings.emergency_floor_cents if settings else 0

    savings_effect = None
    if recurring_monthly_cents:
        old_rate, avg_income = _recent_savings_rate(session, savings_rate_months, purchase_date)
        if avg_income > 0:
            new_rate = old_rate - (recurring_monthly_cents / avg_income)
            savings_effect = SavingsRateEffect(
                old_rate=round(old_rate, 4),
                new_rate=round(new_rate, 4),
                monthly_income_cents=avg_income,
                recurring_monthly_cents=recurring_monthly_cents,
            )

    opportunity_cost = {}
    if settings:
        for years in OPPORTUNITY_COST_YEARS:
            opportunity_cost[years] = round(amount_cents * (1 + settings.assumed_real_return) ** years)

    reasons: list[str] = []
    verdict: Verdict = "green"

    if post_purchase_balance < floor:
        verdict = "red"
        reasons.append(
            f"Post-purchase balance (${post_purchase_balance / 100:,.2f}) would be below "
            f"your emergency floor (${floor / 100:,.2f})."
        )
    if projection.trough.balance_cents < floor:
        verdict = "red"
        reasons.append(
            f"The 90-day projection dips to ${projection.trough.balance_cents / 100:,.2f} "
            f"on {projection.trough.day}, below your floor."
        )
    elif projection.trough.balance_cents < floor * (1 + TROUGH_BUFFER):
        if verdict != "red":
            verdict = "yellow"
        reasons.append(
            f"The 90-day trough (${projection.trough.balance_cents / 100:,.2f} on "
            f"{projection.trough.day}) is close to your floor, within a {TROUGH_BUFFER:.0%} buffer."
        )

    if savings_effect and (savings_effect.old_rate - savings_effect.new_rate) >= SAVINGS_RATE_DROP_YELLOW:
        if verdict == "green":
            verdict = "yellow"
        reasons.append(
            f"Savings rate would drop from {savings_effect.old_rate:.1%} to "
            f"{savings_effect.new_rate:.1%} ({(savings_effect.old_rate - savings_effect.new_rate):.1%} drop)."
        )
    if savings_effect and savings_effect.new_rate < 0:
        verdict = "red"
        reasons.append("New recurring cost would push savings rate negative.")

    if not reasons:
        reasons.append(
            f"Post-purchase balance (${post_purchase_balance / 100:,.2f}) stays comfortably "
            f"above your floor (${floor / 100:,.2f}), and the 90-day trough "
            f"(${projection.trough.balance_cents / 100:,.2f}) does too."
        )

    return AffordabilityResult(
        verdict=verdict,
        reasons=reasons,
        current_balance_cents=current_balance,
        post_purchase_balance_cents=post_purchase_balance,
        emergency_floor_cents=floor,
        projection=projection,
        savings_effect=savings_effect,
        opportunity_cost_cents=opportunity_cost,
    )
