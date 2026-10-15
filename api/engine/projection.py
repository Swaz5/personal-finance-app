"""90-day forward cash projection for a single account. This is the
signature view — the trough chart.

Scoped to one account and inclusive of transfers: a card payment leaving
checking is real cash movement even though it's excluded from spend
math. Projects only the recurring patterns found directly on this
account's own transaction history — it does not reach into the
cross-account `recurring` table, which is transfer-excluded and mixes in
patterns that live on other accounts (e.g. a subscription charged to a
credit card doesn't move cash out of checking; the card *payment* does,
if that payment itself is regular enough to register as a pattern).

A pattern whose last occurrence is more than 2 cadence-cycles overdue is
treated as dead (e.g. income from a previous job) and excluded — otherwise
a merchant that stopped recurring a year ago gets extrapolated forever.

Known limitation: irregular-amount recurring cash outflows (e.g. a credit
card payment that varies with what was charged that cycle) won't clear
the amount-stability bar and so won't appear here — the projection will
understate real future outflows for accounts that rely on those.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from engine.recurring import find_patterns
from models import Balance, Transaction


@dataclass
class DayPoint:
    day: date
    balance_cents: int


@dataclass
class ProjectionResult:
    starting_balance_cents: int
    daily: list[DayPoint]
    trough: DayPoint
    patterns_used: int
    stale_patterns_excluded: int


STALE_CYCLES = 2


def _latest_balance(session: Session, account_id: int) -> int:
    balance = session.exec(
        select(Balance).where(Balance.account_id == account_id).order_by(Balance.as_of.desc())
    ).first()
    if balance is None:
        raise ValueError(f"no balance recorded for account {account_id}")
    return balance.current_cents


def project_cash_forward(
    session: Session,
    account_id: int,
    days: int = 90,
    as_of: date | None = None,
    hypothetical_amount_cents: int = 0,
    hypothetical_date: date | None = None,
) -> ProjectionResult:
    as_of = as_of or date.today()
    starting_balance = _latest_balance(session, account_id)

    txns = session.exec(select(Transaction).where(Transaction.account_id == account_id)).all()
    patterns = find_patterns(txns)

    active_patterns = []
    stale_count = 0
    for pattern in patterns.values():
        overdue_days = (as_of - pattern.next_expected).days
        if overdue_days > pattern.cadence_days * STALE_CYCLES:
            stale_count += 1
            continue
        active_patterns.append(pattern)

    # Expand each pattern into its expected occurrence dates within the window.
    events: dict[date, int] = {}
    window_end = as_of + timedelta(days=days)
    for pattern in active_patterns:
        occurrence = pattern.next_expected
        while occurrence <= window_end:
            if occurrence >= as_of:
                events[occurrence] = events.get(occurrence, 0) + pattern.median_amount_cents
            occurrence += timedelta(days=pattern.cadence_days)

    if hypothetical_amount_cents and hypothetical_date:
        events[hypothetical_date] = events.get(hypothetical_date, 0) - abs(hypothetical_amount_cents)

    balance = starting_balance
    daily: list[DayPoint] = []
    trough = DayPoint(day=as_of, balance_cents=starting_balance)
    for i in range(days + 1):
        day = as_of + timedelta(days=i)
        balance += events.get(day, 0)
        point = DayPoint(day=day, balance_cents=balance)
        daily.append(point)
        if point.balance_cents < trough.balance_cents:
            trough = point

    return ProjectionResult(
        starting_balance_cents=starting_balance,
        daily=daily,
        trough=trough,
        patterns_used=len(active_patterns),
        stale_patterns_excluded=stale_count,
    )
