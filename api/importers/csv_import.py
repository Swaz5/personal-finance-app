"""Phase 1 importer: one YAML mapping per institution's CSV export.

Some banks give a single signed amount column; others split debit/credit
into two columns. Both are handled. Every mapping must normalize to the
sign convention in base.py before rows leave parse_csv — this module is
the boundary, so it enforces rule 2, not anything downstream.
"""

import csv as csv_module
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from importers.base import RawTransaction


@dataclass
class MappingConfig:
    institution: str
    date_column: str
    date_format: str
    description_column: str
    amount_mode: str  # "single" | "split"
    amount_column: str | None = None
    negate: bool = False  # flip sign of amount_column if the source's convention is inverted
    debit_column: str | None = None
    credit_column: str | None = None
    description_extra_column: str | None = None  # prefixed onto description_raw, e.g. an "Action" column
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    skip_rows: int = 0

    def __post_init__(self) -> None:
        if self.amount_mode not in ("single", "split"):
            raise ValueError(f"amount_mode must be 'single' or 'split', got {self.amount_mode!r}")
        if self.amount_mode == "single" and not self.amount_column:
            raise ValueError("amount_mode 'single' requires amount_column")
        if self.amount_mode == "split" and not (self.debit_column and self.credit_column):
            raise ValueError("amount_mode 'split' requires debit_column and credit_column")


def load_mapping(path: Path) -> MappingConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return MappingConfig(**raw)


_AMOUNT_STRIP = re.compile(r"[^0-9.\-]")


def _parse_amount_to_cents(value: str) -> int | None:
    """Handles "$1,234.56", "-1,234.56", "(1,234.56)" (parens = negative), blanks."""
    value = value.strip()
    if not value:
        return None
    negative = value.startswith("(") and value.endswith(")")
    cleaned = _AMOUNT_STRIP.sub("", value)
    if not cleaned or cleaned == "-":
        return None
    cents = round(float(cleaned) * 100)
    return -abs(cents) if negative else cents


def parse_csv(csv_path: Path, mapping: MappingConfig, account_id: int) -> list[RawTransaction]:
    transactions: list[RawTransaction] = []
    with open(csv_path, encoding=mapping.encoding, newline="") as f:
        for _ in range(mapping.skip_rows):
            next(f)
        reader = csv_module.DictReader(f, delimiter=mapping.delimiter)
        for row in reader:
            posted_at = datetime.strptime(row[mapping.date_column].strip(), mapping.date_format).date()
            description = row[mapping.description_column].strip()
            if mapping.description_extra_column:
                extra = row[mapping.description_extra_column].strip()
                if extra:
                    description = f"{extra} - {description}" if description else extra

            if mapping.amount_mode == "single":
                amount_cents = _parse_amount_to_cents(row[mapping.amount_column])
                if amount_cents is None:
                    continue
                if mapping.negate:
                    amount_cents = -amount_cents
            else:
                debit = _parse_amount_to_cents(row[mapping.debit_column])
                credit = _parse_amount_to_cents(row[mapping.credit_column])
                if debit:
                    amount_cents = -abs(debit)
                elif credit:
                    amount_cents = abs(credit)
                else:
                    continue

            transactions.append(
                RawTransaction(
                    account_id=account_id,
                    posted_at=posted_at,
                    amount_cents=amount_cents,
                    description_raw=description,
                )
            )
    return transactions
