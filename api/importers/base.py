"""Importer contract. Every source (CSV, SnapTrade, SimpleFIN) conforms to this
so the source is swappable.

Sign convention, enforced here at the boundary: from the account's
perspective, outflow negative, inflow positive. A credit card purchase is
negative; a payment to the card is positive. Every importer must normalize
to this before a RawTransaction leaves it — nothing downstream re-checks it.
"""

import hashlib
from dataclasses import dataclass
from datetime import date

from typing import Protocol

from sqlmodel import Session, select

from models import ImportBatch, Transaction


@dataclass
class RawTransaction:
    account_id: int
    posted_at: date
    amount_cents: int  # outflow negative, inflow positive
    description_raw: str
    external_id: str | None = None


@dataclass
class RawBalance:
    account_id: int
    as_of: date
    current_cents: int
    available_cents: int | None = None


class Importer(Protocol):
    def fetch(self, since: date) -> list[RawTransaction]: ...
    def balances(self) -> list[RawBalance]: ...


def content_hash(account_id: int, posted_at: date, amount_cents: int, description_raw: str) -> str:
    """Dedup key. API sources should prefer a stable external_id when
    available and fall back to this."""
    raw = f"{account_id}|{posted_at.isoformat()}|{amount_cents}|{description_raw}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class ImportResult:
    batch: ImportBatch
    inserted: int
    skipped_duplicates: int


def ingest(
    session: Session,
    account_id: int,
    source: str,
    file_name: str,
    raw_transactions: list[RawTransaction],
) -> ImportResult:
    """Shared write path for every importer: dedup via content hash,
    record the batch, insert only new rows. CSVs overlap on re-download —
    without this every average downstream is poisoned by duplicates."""
    batch = ImportBatch(source=source, file_name=file_name, row_count=0)
    session.add(batch)
    session.flush()  # assigns batch.id without committing

    inserted = 0
    skipped = 0
    for raw in raw_transactions:
        chash = content_hash(raw.account_id, raw.posted_at, raw.amount_cents, raw.description_raw)
        exists = session.exec(select(Transaction).where(Transaction.content_hash == chash)).first()
        if exists:
            skipped += 1
            continue
        session.add(
            Transaction(
                account_id=raw.account_id,
                posted_at=raw.posted_at,
                amount_cents=raw.amount_cents,
                description_raw=raw.description_raw,
                external_id=raw.external_id,
                import_batch_id=batch.id,
                content_hash=chash,
            )
        )
        inserted += 1

    batch.row_count = inserted
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return ImportResult(batch=batch, inserted=inserted, skipped_duplicates=skipped)
