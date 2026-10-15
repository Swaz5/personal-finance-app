"""Retirement pacing — a scenario tool, not a prediction.
Three real (inflation-adjusted) return scenarios, never one number. A
single point estimate on a 30-year projection is false precision.

Coast FI: the amount that, left untouched from today, reaches the target
at a given assumed return with no further contributions. If your current
invested balance already clears it, you could stop contributing and still
hit the goal under that assumption — a more actionable number than a
raw target.

Uses whatever accounts are typed brokerage/retirement as "invested"
balance, and the trailing actual net cash flow (from cashflow.py) as the ongoing
contribution rate — this app has no 401k/employer-match data to compute
the "second version" of savings rate the plan mentions, so it isn't
attempted; the contribution rate here is the plain net income minus
spending, annualized.
"""

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from engine.cashflow import trailing_monthly_net
from models import Account, AccountType, Balance

REAL_RETURN_SCENARIOS = (0.04, 0.05, 0.06)
INVESTED_ACCOUNT_TYPES = (AccountType.brokerage, AccountType.retirement)


@dataclass
class RetirementScenario:
    real_return: float
    projected_value_cents: int
    coast_fi_cents: int
    on_track: bool  # projected value (with continued contributions) reaches target
    is_coasting: bool  # current balance alone already clears coast FI — could stop contributing
    gap_or_surplus_cents: int  # projected_value - target; positive = surplus


@dataclass
class RetirementResult:
    target_amount_cents: int
    target_date: date
    years: float
    current_invested_cents: int
    monthly_contribution_cents: int
    annual_contribution_cents: int
    scenarios: list[RetirementScenario]


def _invested_balance(session: Session) -> int:
    accounts = session.exec(select(Account).where(Account.type.in_(INVESTED_ACCOUNT_TYPES))).all()  # type: ignore[attr-defined]
    total = 0
    for account in accounts:
        latest = session.exec(
            select(Balance).where(Balance.account_id == account.id).order_by(Balance.as_of.desc())
        ).first()
        if latest:
            total += latest.current_cents
    return total


def _future_value(current_cents: int, annual_contribution_cents: int, years: float, rate: float) -> int:
    growth = (1 + rate) ** years
    fv = current_cents * growth
    if rate != 0:
        fv += annual_contribution_cents * ((growth - 1) / rate)
    else:
        fv += annual_contribution_cents * years
    return round(fv)


def _coast_fi(target_cents: int, years: float, rate: float) -> int:
    return round(target_cents / ((1 + rate) ** years))


def project_retirement(
    session: Session,
    target_amount_cents: int,
    target_date: date,
    as_of: date | None = None,
    contribution_months: int = 3,
) -> RetirementResult:
    as_of = as_of or date.today()
    years = (target_date - as_of).days / 365.25
    if years <= 0:
        raise ValueError("target_date must be in the future")

    current_invested = _invested_balance(session)
    avg_monthly_net, _ = trailing_monthly_net(session, months=contribution_months, as_of=as_of)
    annual_contribution = avg_monthly_net * 12

    scenarios = []
    for rate in REAL_RETURN_SCENARIOS:
        projected = _future_value(current_invested, annual_contribution, years, rate)
        coast_fi = _coast_fi(target_amount_cents, years, rate)
        scenarios.append(
            RetirementScenario(
                real_return=rate,
                projected_value_cents=projected,
                coast_fi_cents=coast_fi,
                on_track=projected >= target_amount_cents,
                is_coasting=current_invested >= coast_fi,
                gap_or_surplus_cents=projected - target_amount_cents,
            )
        )

    return RetirementResult(
        target_amount_cents=target_amount_cents,
        target_date=target_date,
        years=round(years, 1),
        current_invested_cents=current_invested,
        monthly_contribution_cents=avg_monthly_net,
        annual_contribution_cents=annual_contribution,
        scenarios=scenarios,
    )
