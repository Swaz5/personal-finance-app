"""Net worth over time (Phase 5). Checking/savings/credit balances are
reconstructed exactly by walking backward from the latest known balance
and undoing each day's transactions — real history, not an estimate.

Brokerage and any account with no transaction history (e.g. an old
account whose statements aren't available) can't be reconstructed this
way, so their current balance is held flat across the whole lookback
window. This is a known, deliberate approximation — see BUILD_PLAN.md
Phase 5 notes. It means past net worth is understated for accounts that
have genuinely grown, and the chart's shape near "today" is trustworthy
while further back it increasingly reflects only the accounts we can
actually reconstruct.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from models import Account, Balance, Transaction

RECONSTRUCTABLE_TYPES = {"checking", "savings", "credit"}


@dataclass
class NetWorthPoint:
    day: date
    net_worth_cents: int


def _reconstruct_daily_balance(
    session: Session, account_id: int, start_date: date, end_date: date
) -> dict[date, int]:
    anchor = session.exec(
        select(Balance)
        .where(Balance.account_id == account_id, Balance.as_of <= end_date)
        .order_by(Balance.as_of.desc())
    ).first()
    if anchor is None:
        return {}

    txns = session.exec(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.posted_at >= start_date,
            Transaction.posted_at <= anchor.as_of,
        )
    ).all()
    daily_delta: dict[date, int] = defaultdict(int)
    for t in txns:
        daily_delta[t.posted_at] += t.amount_cents

    series: dict[date, int] = {}
    balance = anchor.current_cents
    day = anchor.as_of
    while day >= start_date:
        series[day] = balance
        balance -= daily_delta.get(day, 0)
        day -= timedelta(days=1)
    return series


def _flat_balance(session: Session, account_id: int, end_date: date) -> int | None:
    anchor = session.exec(
        select(Balance)
        .where(Balance.account_id == account_id, Balance.as_of <= end_date)
        .order_by(Balance.as_of.desc())
    ).first()
    return anchor.current_cents if anchor else None


def net_worth_series(session: Session, months: int = 12, as_of: date | None = None) -> list[NetWorthPoint]:
    as_of = as_of or date.today()
    start_date = as_of - timedelta(days=30 * months)

    accounts = session.exec(select(Account).where(Account.include_in_net_worth == True)).all()  # noqa: E712

    per_account_series: dict[int, dict[date, int]] = {}
    for account in accounts:
        if account.type in RECONSTRUCTABLE_TYPES:
            series = _reconstruct_daily_balance(session, account.id, start_date, as_of)
            if series:
                per_account_series[account.id] = series
                continue
        flat = _flat_balance(session, account.id, as_of)
        if flat is not None:
            per_account_series[account.id] = {}
            per_account_series[account.id]["__flat__"] = flat  # type: ignore[index]

    points: list[NetWorthPoint] = []
    day = start_date
    while day <= as_of:
        total = 0
        for account_id, series in per_account_series.items():
            if "__flat__" in series:
                total += series["__flat__"]
                continue
            if day in series:
                total += series[day]
            else:
                # before this account's earliest reconstructed day, or a gap —
                # use the nearest earlier known point, else nearest later.
                earlier = [d for d in series if d <= day]
                if earlier:
                    total += series[max(earlier)]
                else:
                    later = [d for d in series if d > day]
                    if later:
                        total += series[min(later)]
        points.append(NetWorthPoint(day=day, net_worth_cents=total))
        day += timedelta(days=1)

    return points
