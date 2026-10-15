"""Recurring bill/subscription detection. Load-bearing, not a nice-to-have —
the Phase 4 projection engine trusts this list to know what's coming.

Group by normalized merchant (and sign, so a merchant's charges and its
occasional refunds don't get averaged together), require >=3 occurrences
with stable amount (within 10% of the median) and consistent gap (within
4 days of the median gap). Confidence is how well the group satisfies both.

The pattern-finding core (_stability) is shared with projection.py, which
needs the same math scoped to one account and inclusive of transfers — a
credit card payment leaving checking is real cash movement even though
it's excluded from spend categorization (rule 3).
"""

import statistics
from dataclasses import dataclass
from collections import defaultdict
from datetime import date, timedelta

from sqlmodel import Session, select

from models import Recurring, Transaction

AMOUNT_TOLERANCE = 0.10
GAP_TOLERANCE_DAYS = 4
MIN_OCCURRENCES = 3
MIN_CONFIDENCE = 0.5


@dataclass
class Pattern:
    median_amount_cents: int
    cadence_days: int
    last_seen: date
    next_expected: date
    confidence: float


def _stability(group: list[Transaction]) -> Pattern | None:
    """Core stability scoring for one (merchant, sign) group. Returns None if
    it doesn't clear the occurrence/amount/gap/confidence bars."""
    if len(group) < MIN_OCCURRENCES:
        return None
    group = sorted(group, key=lambda t: t.posted_at)

    amounts = [t.amount_cents for t in group]
    median_amount = statistics.median(amounts)
    if median_amount == 0:
        return None
    amount_ok = [abs(a - median_amount) <= abs(median_amount) * AMOUNT_TOLERANCE for a in amounts]
    if sum(amount_ok) < MIN_OCCURRENCES:
        return None
    amount_stability = sum(amount_ok) / len(amounts)

    dates = [t.posted_at for t in group]
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    if not gaps:
        return None
    median_gap = statistics.median(gaps)
    if median_gap <= 0:
        return None
    gap_ok = [abs(g - median_gap) <= GAP_TOLERANCE_DAYS for g in gaps]
    gap_stability = sum(gap_ok) / len(gaps)

    confidence = round(amount_stability * gap_stability, 3)
    if confidence < MIN_CONFIDENCE:
        return None

    last_seen = dates[-1]
    next_expected = last_seen + timedelta(days=round(median_gap))
    return Pattern(
        median_amount_cents=round(median_amount),
        cadence_days=round(median_gap),
        last_seen=last_seen,
        next_expected=next_expected,
        confidence=confidence,
    )


def find_patterns(txns: list[Transaction]) -> dict[tuple[str, bool], Pattern]:
    """Groups transactions by (merchant_normalized, is_positive) and scores
    each group. Caller decides what to feed in (which account, whether to
    include transfers) — this function is just the math."""
    groups: dict[tuple[str, bool], list[Transaction]] = defaultdict(list)
    for t in txns:
        if not t.merchant_normalized:
            continue
        groups[(t.merchant_normalized, t.amount_cents >= 0)].append(t)

    results = {}
    for key, group in groups.items():
        pattern = _stability(group)
        if pattern is not None:
            results[key] = pattern
    return results


def detect_recurring(session: Session) -> int:
    """Populates the persisted `recurring` table: cross-account, non-transfer
    only (this is for bill/subscription awareness, not cash-balance math)."""
    txns = session.exec(
        select(Transaction).where(
            Transaction.is_transfer == False,  # noqa: E712
            Transaction.merchant_normalized != None,  # noqa: E711
        )
    ).all()

    patterns = find_patterns(txns)

    upserted = 0
    for (merchant, _is_positive), pattern in patterns.items():
        existing = session.exec(
            select(Recurring).where(Recurring.merchant_normalized == merchant)
        ).first()
        if existing:
            existing.expected_amount_cents = pattern.median_amount_cents
            existing.cadence_days = pattern.cadence_days
            existing.last_seen = pattern.last_seen
            existing.next_expected = pattern.next_expected
            existing.confidence = pattern.confidence
            session.add(existing)
        else:
            session.add(
                Recurring(
                    merchant_normalized=merchant,
                    expected_amount_cents=pattern.median_amount_cents,
                    cadence_days=pattern.cadence_days,
                    last_seen=pattern.last_seen,
                    next_expected=pattern.next_expected,
                    confidence=pattern.confidence,
                )
            )
        upserted += 1

    session.commit()
    return upserted
