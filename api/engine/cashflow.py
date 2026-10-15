"""Cash flow: income, fixed/variable/discretionary splits, trailing medians.

Rule 5: medians, not means — one Costco run or one annual insurance payment
shouldn't move a category's "normal." Months with zero activity count as $0
in the window, not as missing — skipping a category some months shouldn't
inflate its baseline by only averaging over the months you used it.
"""

import statistics
from collections import defaultdict
from datetime import date

from sqlmodel import Session, select

from models import Category, CategoryKind, Transaction


def _category_kind_map(session: Session) -> dict[int, CategoryKind]:
    cats = session.exec(select(Category)).all()
    return {c.id: c.kind for c in cats}


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def monthly_totals_by_kind(session: Session, year: int, month: int) -> dict[str, int]:
    """{kind: total_cents} for one calendar month. Transfers are their own
    kind and never appear here — they're not spend or income."""
    start, end = _month_bounds(year, month)
    kind_map = _category_kind_map(session)
    txns = session.exec(
        select(Transaction).where(
            Transaction.posted_at >= start,
            Transaction.posted_at < end,
            Transaction.is_transfer == False,  # noqa: E712
            Transaction.category_id != None,  # noqa: E711
        )
    ).all()
    totals: dict[str, int] = defaultdict(int)
    for t in txns:
        kind = kind_map.get(t.category_id)
        if kind is None or kind == CategoryKind.transfer:
            continue
        totals[kind.value] += t.amount_cents
    return dict(totals)


def trailing_median_by_category(
    session: Session, months: int = 6, as_of: date | None = None
) -> dict[int, int]:
    """Median monthly spend per category over the trailing N calendar months
    (income and transfer kinds excluded — this baseline is for spend)."""
    as_of = as_of or date.today()
    kind_map = _category_kind_map(session)

    window_start_year, window_start_month = _add_months(as_of.year, as_of.month, -(months - 1))
    window_start, _ = _month_bounds(window_start_year, window_start_month)
    _, window_end = _month_bounds(as_of.year, as_of.month)

    month_keys: list[tuple[int, int]] = []
    y, m = window_start_year, window_start_month
    for _ in range(months):
        month_keys.append((y, m))
        y, m = _add_months(y, m, 1)

    txns = session.exec(
        select(Transaction).where(
            Transaction.posted_at >= window_start,
            Transaction.posted_at < window_end,
            Transaction.is_transfer == False,  # noqa: E712
            Transaction.category_id != None,  # noqa: E711
        )
    ).all()

    buckets: dict[int, dict[tuple[int, int], int]] = defaultdict(lambda: defaultdict(int))
    categories_seen: set[int] = set()
    for t in txns:
        kind = kind_map.get(t.category_id)
        if kind is None or kind in (CategoryKind.transfer, CategoryKind.income):
            continue
        key = (t.posted_at.year, t.posted_at.month)
        buckets[t.category_id][key] += abs(t.amount_cents)
        categories_seen.add(t.category_id)

    medians: dict[int, int] = {}
    for cat_id in categories_seen:
        values = [buckets[cat_id].get(k, 0) for k in month_keys]
        medians[cat_id] = round(statistics.median(values))
    return medians


def monthly_spend_by_category(session: Session, year: int, month: int) -> dict[int, int]:
    """{category_id: spend_cents} (positive magnitude) for one calendar month,
    spend categories only (income/transfer excluded) — pairs with
    trailing_median_by_category for "this month vs. your normal" (section 7)."""
    start, end = _month_bounds(year, month)
    kind_map = _category_kind_map(session)
    txns = session.exec(
        select(Transaction).where(
            Transaction.posted_at >= start,
            Transaction.posted_at < end,
            Transaction.is_transfer == False,  # noqa: E712
            Transaction.category_id != None,  # noqa: E711
        )
    ).all()
    totals: dict[int, int] = defaultdict(int)
    for t in txns:
        kind = kind_map.get(t.category_id)
        if kind is None or kind in (CategoryKind.transfer, CategoryKind.income):
            continue
        totals[t.category_id] += abs(t.amount_cents)
    return dict(totals)


def trailing_fixed_expense_monthly(session: Session, months: int = 6, as_of: date | None = None) -> int:
    """Sum of trailing medians across fixed-kind categories only — the input
    to the emergency floor (N months of fixed expenses, section 4)."""
    kind_map = _category_kind_map(session)
    medians = trailing_median_by_category(session, months=months, as_of=as_of)
    return sum(cents for cat_id, cents in medians.items() if kind_map.get(cat_id) == CategoryKind.fixed)


def trailing_monthly_net(session: Session, months: int = 3, as_of: date | None = None) -> tuple[int, int]:
    """Average monthly net cash flow (income + fixed + variable + discretionary,
    all already signed) over the last N *complete* calendar months — excludes
    the current, likely-partial month. Returns (avg_net_cents, avg_income_cents)."""
    as_of = as_of or date.today()
    year, month = as_of.year, as_of.month
    totals = []
    for i in range(1, months + 1):
        total = year * 12 + (month - 1) - i
        y, m = total // 12, total % 12 + 1
        totals.append(monthly_totals_by_kind(session, y, m))

    incomes = [t.get("income", 0) for t in totals]
    avg_income = round(sum(incomes) / len(incomes)) if incomes else 0

    nets = [
        t.get("income", 0) + t.get("fixed", 0) + t.get("variable", 0) + t.get("discretionary", 0)
        for t in totals
    ]
    avg_net = round(sum(nets) / len(nets)) if nets else 0
    return avg_net, avg_income
