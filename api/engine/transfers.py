"""Transfer-pair detection. Moving $2,000 from checking to a credit
card is not spending — it's the same dollars changing accounts. Naive apps
show spend 2-3x real and you stop trusting the numbers.

Match: opposite-signed, equal amount, different accounts, within ±3 days.
Exact-amount match only for now — fee-adjusted transfers (e.g. wire fees)
aren't handled, since none of the ingested sources produce them yet.
"""

from collections import defaultdict
from datetime import timedelta

from sqlmodel import Session, select

from models import Transaction

WINDOW_DAYS = 3


def detect_transfers(session: Session) -> int:
    """Scans all untagged transactions and marks matched pairs. Returns the
    number of pairs matched. Idempotent — already-tagged rows are skipped."""
    candidates = session.exec(
        select(Transaction).where(
            Transaction.is_transfer == False,  # noqa: E712
            Transaction.transfer_pair_id == None,  # noqa: E711
        )
    ).all()

    buckets: dict[int, list[Transaction]] = defaultdict(list)
    for txn in candidates:
        buckets[abs(txn.amount_cents)].append(txn)

    matched_pairs = 0
    used_ids: set[int] = set()

    for group in buckets.values():
        group.sort(key=lambda t: t.posted_at)
        for i, t1 in enumerate(group):
            if t1.id in used_ids:
                continue
            for t2 in group[i + 1 :]:
                if t2.id in used_ids:
                    continue
                if t2.account_id == t1.account_id:
                    continue
                if t1.amount_cents != -t2.amount_cents:
                    continue
                if abs((t2.posted_at - t1.posted_at)) > timedelta(days=WINDOW_DAYS):
                    continue
                t1.is_transfer = True
                t2.is_transfer = True
                t1.transfer_pair_id = t2.id
                t2.transfer_pair_id = t1.id
                session.add(t1)
                session.add(t2)
                used_ids.add(t1.id)
                used_ids.add(t2.id)
                matched_pairs += 1
                break

    session.commit()
    return matched_pairs
