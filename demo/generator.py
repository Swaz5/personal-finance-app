"""Synthetic demo data — about six months of fake statements for three fake
accounts, written in exactly the CSV layouts the demo/mappings/*.yaml files
describe, so they go through the real importer unmodified.

Everything here is invented: institutions, merchants, amounts, share counts.
Output is deterministic for a given (end date, seed).

What it deliberately includes, so each engine has something to find:
- Transfers: a monthly card autopay (checking -> card) and a monthly
  contribution (checking -> brokerage), each landing on the other side a
  day later with the exact opposite amount.
- Duplicates: checking is exported as two overlapping files (an older
  download and a recent one), the way re-downloading a statement works.
  The overlapping rows are byte-identical, so dedup skips them.
- Recurring: biweekly pay, rent, utilities, subscriptions, loan payment.
- Brokerage: buys and dividends in VTI / VXUS / BND; the current position
  sizes are HOLDINGS below.

Usage:
    python demo/generator.py --out demo/statements --end 2026-10-14
"""

import argparse
import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

DEFAULT_SEED = 42
DAYS = 183

CHECKING = "Demo Checking"
CARD = "Demo Credit Card"
BROKERAGE = "Demo Brokerage"

# Current positions (made-up share counts) and uninvested cash.
HOLDINGS: list[tuple[str, float]] = [("VTI", 38.25), ("VXUS", 64.0), ("BND", 41.5)]
BROKERAGE_CASH_CENTS = 21_840

# Rough per-share prices used only for the synthetic buy rows and as an
# offline fallback when Yahoo Finance can't be reached. Not market data.
APPROX_PRICES: dict[str, tuple[float, str]] = {
    "VTI": (301.50, "Vanguard Total Stock Market ETF"),
    "VXUS": (68.20, "Vanguard Total International Stock ETF"),
    "BND": (73.10, "Vanguard Total Bond Market ETF"),
}

OPENING_CHECKING_CENTS = 485_000
OPENING_CARD_OWED_CENTS = 148_032
PAYCHECK_CENTS = 245_000
CONTRIBUTION_CENTS = 50_000


@dataclass
class Row:
    day: date
    description: str
    cents: int  # account perspective: outflow negative, inflow positive
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class ExportFile:
    account: str
    mapping: str
    file_name: str
    rows: int


@dataclass
class DemoSummary:
    start: date
    end: date
    files: list[ExportFile]
    balances_cents: dict[str, int]  # latest balance per account (card negative = owed)
    holdings: list[tuple[str, float]]
    brokerage_cash_cents: int
    duplicate_rows: int  # rows present in both checking exports
    transfer_pairs: int


class _Ledger:
    """Collects rows for one account and keeps (day, amount, description)
    unique, so the content hash only collapses rows that really are
    re-exports — never two genuine same-day coffees."""

    def __init__(self) -> None:
        self.rows: list[Row] = []
        self._seen: set[tuple[date, int, str]] = set()

    def add(self, day: date, description: str, cents: int, **extra: str) -> int:
        while (day, cents, description) in self._seen:
            cents += -1 if cents < 0 else 1
        self._seen.add((day, cents, description))
        self.rows.append(Row(day, description, cents, extra))
        return cents


def _business_day(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _cents(rng: random.Random, low: float, high: float) -> int:
    return round(rng.uniform(low, high) * 100)


def _money(cents: int) -> str:
    return f"{abs(cents) / 100:,.2f}"


def _signed_dollars(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _month_days(start: date, end: date, day_of_month: int) -> list[date]:
    out = []
    y, m = start.year, start.month
    while True:
        try:
            d = date(y, m, day_of_month)
        except ValueError:
            d = None
        if d and d > end:
            break
        if d and d >= start:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        if date(y, m, 1) > end:
            break
    return out


def _card_activity(rng: random.Random, card: _Ledger, start: date, end: date) -> None:
    """Everyday spending on the card. Amounts are card-account perspective
    (charges negative); the CSV writer flips them to issuer convention."""
    monthly = [
        (5, "STREAMBOX SUBSCRIPTION", 1549),
        (9, "TUNEWAVE PREMIUM", 1099),
        (17, "CLOUDVAULT STORAGE", 299),
        (1, "HARBOR FITNESS CLUB", 3900),
    ]
    for dom, desc, cents in monthly:
        for d in _month_days(start, end, dom):
            card.add(d, desc, -cents)

    day = start
    while day <= end:
        weekday = day.weekday()
        if weekday in (1, 5) or rng.random() < 0.08:
            card.add(day, f"GREENLEAF MARKET #{rng.choice([114, 207])}", -_cents(rng, 38, 142))
        if rng.random() < 0.06:
            card.add(day, "FRESHWAY GROCERY", -_cents(rng, 18, 64))
        if weekday < 5 and rng.random() < 0.45:
            card.add(day, "SQ *BLUE KETTLE COFFEE", -_cents(rng, 4.25, 7.80))
        if rng.random() < 0.14:
            card.add(day, "TST* LUNA TAQUERIA", -_cents(rng, 13, 34))
        if rng.random() < 0.09:
            card.add(day, "DD *DOORDROP NOODLE HOUSE", -_cents(rng, 21, 44))
        if rng.random() < 0.05:
            card.add(day, "PIZZERIA VESUVIO", -_cents(rng, 26, 58))
        if weekday == 6 or rng.random() < 0.04:
            card.add(day, "QUICKFUEL #2231", -_cents(rng, 34, 56))
        if rng.random() < 0.05:
            card.add(day, "METRO TRANSIT FARE", -_cents(rng, 2.5, 12))
        if rng.random() < 0.035:
            card.add(day, "NORTHWIND OUTFITTERS", -_cents(rng, 24, 160))
        if rng.random() < 0.02:
            card.add(day, "BRIGHTHOME GOODS", -_cents(rng, 15, 90))
        if rng.random() < 0.02:
            card.add(day, "PAPERLEAF BOOKS", -_cents(rng, 12, 38))
        if weekday >= 4 and rng.random() < 0.08:
            card.add(day, "PIXEL CINEMAS", -_cents(rng, 14, 32))
        if rng.random() < 0.02:
            card.add(day, "CORNER PHARMACY", -_cents(rng, 8, 45))
        if rng.random() < 0.016:
            card.add(day, "SHEAR GENIUS SALON", -_cents(rng, 35, 60))
        day += timedelta(days=1)

    # A handful of one-offs.
    span = (end - start).days
    trip = start + timedelta(days=rng.randint(40, span - 40))
    card.add(trip, "SKYLINE AIR 0427713", -_cents(rng, 240, 330))
    card.add(trip + timedelta(days=9), "HARBORVIEW INN", -_cents(rng, 280, 420))
    card.add(start + timedelta(days=rng.randint(10, span - 10)), "BRIGHTSMILE DENTAL", -_cents(rng, 90, 160))
    card.add(start + timedelta(days=rng.randint(10, span - 10)), "GOODROOTS COMMUNITY FUND", -5000)
    ret = start + timedelta(days=rng.randint(20, span - 5))
    card.add(ret, "NORTHWIND OUTFITTERS RETURN", _cents(rng, 30, 70))


def _checking_bills(rng: random.Random, checking: _Ledger, start: date, end: date) -> None:
    first_friday = start + timedelta(days=(4 - start.weekday()) % 7)
    d = first_friday
    while d <= end:
        checking.add(d, "ACME ANALYTICS INC DIRECT DEP", PAYCHECK_CENTS)
        d += timedelta(days=14)

    for d in _month_days(start, end, 1):
        checking.add(_business_day(d), "MAPLE GROVE APTS RENT", -165_000)
    for d in _month_days(start, end, 8):
        checking.add(_business_day(d), "CITY POWER & LIGHT", -_cents(rng, 96, 112))
    for d in _month_days(start, end, 12):
        checking.add(_business_day(d), "FIBERLINK INTERNET", -6500)
    for d in _month_days(start, end, 15):
        checking.add(_business_day(d), "NORTHSTAR STUDENT LOAN", -21_200)
    for d in _month_days(start, end, 20):
        checking.add(_business_day(d), "SAFEHARBOR AUTO INS", -11_840)

    day = start
    while day <= end:
        if rng.random() < 0.035:
            checking.add(day, "POS QUICKFUEL #2231", -_cents(rng, 30, 52))
        if rng.random() < 0.03:
            checking.add(day, "POS GREENLEAF MARKET #114", -_cents(rng, 22, 75))
        day += timedelta(days=1)

    span = (end - start).days
    checking.add(start + timedelta(days=rng.randint(10, span - 10)), "COUNTY VEHICLE REGISTRATION", -8_600)


def _brokerage_and_contributions(
    rng: random.Random, checking: _Ledger, brokerage: _Ledger, start: date, end: date
) -> int:
    pairs = 0
    symbols = ["VTI", "VXUS", "BND"]
    for i, d in enumerate(_month_days(start, end, 3)):
        out_day = _business_day(d)
        in_day = _business_day(out_day + timedelta(days=1))
        if in_day > end:
            break
        checking.add(out_day, "ONLINE TRANSFER TO DEMO BROKERAGE", -CONTRIBUTION_CENTS)
        brokerage.add(in_day, "TFR FROM DEMO BANK CHECKING", CONTRIBUTION_CENTS, Action="Funds Received")
        pairs += 1

        buy_day = _business_day(in_day + timedelta(days=1))
        if buy_day > end:
            continue
        symbol = symbols[i % len(symbols)]
        base_price, name = APPROX_PRICES[symbol]
        price = round(base_price * rng.uniform(0.97, 1.03), 2)
        qty = round(rng.uniform(430, 495) / price, 4)
        brokerage.add(
            buy_day,
            name.upper(),
            -round(qty * price * 100),
            Action="Buy",
            Symbol=symbol,
            Quantity=f"{qty:.4f}",
            Price=f"${price:,.2f}",
        )

    for d in _month_days(start, end, 1):
        bd = _business_day(d)
        brokerage.add(bd, "VANGUARD TOTAL BOND MARKET ETF", _cents(rng, 8.5, 9.8), Action="Dividend", Symbol="BND")
    for month in (3, 6, 9, 12):
        for year in {start.year, end.year}:
            d = _business_day(date(year, month, 26))
            if start <= d <= end:
                brokerage.add(d, "VANGUARD TOTAL STOCK MARKET ETF", _cents(rng, 34, 41), Action="Qualified Dividend", Symbol="VTI")
                brokerage.add(d, "VANGUARD TOTAL INTERNATIONAL STOCK ETF", _cents(rng, 18, 26), Action="Qualified Dividend", Symbol="VXUS")
    return pairs


def _card_payments(checking: _Ledger, card: _Ledger, start: date, end: date) -> tuple[int, int]:
    """Statement closes on the 1st; autopay on the 22nd pays that statement
    in full. Returns (pairs, card balance owed at end, as a negative)."""
    charges_by_day: dict[date, int] = {}
    for r in card.rows:
        charges_by_day[r.day] = charges_by_day.get(r.day, 0) + r.cents

    balance = -OPENING_CARD_OWED_CENTS  # card perspective: owed is negative
    statement = balance
    pairs = 0
    day = start
    while day <= end:
        if day.day == 1 and day != start:
            statement = balance
        if day.day == 22 and statement < 0:
            pay_day = _business_day(day)
            post_day = _business_day(pay_day + timedelta(days=1))
            if post_day <= end:
                amount = -statement
                checking.add(pay_day, "DEMO CARD AUTOPAY", -amount)
                card.add(post_day, "AUTOPAY PAYMENT - THANK YOU", amount)
                charges_by_day[post_day] = charges_by_day.get(post_day, 0) + amount
                pairs += 1
                statement = 0
        balance += charges_by_day.get(day, 0)
        day += timedelta(days=1)
    return pairs, balance


def _write_checking(path: Path, rows: list[Row], opening_cents: int, start: date, end: date) -> tuple[int, int]:
    """Writes rows in [start, end], newest first, with a running balance.
    Running balance is computed over the full history so overlapping
    exports agree row-for-row. Returns (row count, latest balance)."""
    ordered = sorted(rows, key=lambda r: (r.day, -r.cents, r.description))
    balance = opening_cents
    with_balance = []
    for r in ordered:
        balance += r.cents
        with_balance.append((r, balance))
    selected = [(r, b) for r, b in with_balance if start <= r.day <= end]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["Date", "Description", "Withdrawal", "Deposit", "Balance"])
        for r, b in reversed(selected):
            w.writerow([
                r.day.strftime("%m/%d/%Y"),
                r.description,
                _money(r.cents) if r.cents < 0 else "",
                _money(r.cents) if r.cents > 0 else "",
                _money(b),
            ])
    return len(selected), balance


def _write_card(path: Path, rows: list[Row]) -> int:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Trans Date", "Post Date", "Description", "Amount", "Category"])
        for r in sorted(rows, key=lambda r: (r.day, r.description), reverse=True):
            post = _business_day(r.day + timedelta(days=1))
            category = ("Payment" if "AUTOPAY" in r.description else "Credit") if r.cents > 0 else ""
            # Issuer convention: charges positive, payments/credits negative.
            w.writerow([r.day.strftime("%m/%d/%Y"), post.strftime("%m/%d/%Y"), r.description, f"{-r.cents / 100:.2f}", category])
    return len(rows)


def _write_brokerage(path: Path, rows: list[Row]) -> int:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["Date", "Action", "Symbol", "Description", "Quantity", "Price", "Amount"])
        for r in sorted(rows, key=lambda r: (r.day, r.description), reverse=True):
            w.writerow([
                r.day.strftime("%m/%d/%Y"),
                r.extra.get("Action", ""),
                r.extra.get("Symbol", ""),
                r.description,
                r.extra.get("Quantity", ""),
                r.extra.get("Price", ""),
                _signed_dollars(r.cents),
            ])
    return len(rows)


def generate(out_dir: Path, end: date | None = None, seed: int = DEFAULT_SEED) -> DemoSummary:
    end = end or date.today()
    start = end - timedelta(days=DAYS)
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    checking, card, brokerage = _Ledger(), _Ledger(), _Ledger()
    _card_activity(rng, card, start, end)
    _checking_bills(rng, checking, start, end)
    contribution_pairs = _brokerage_and_contributions(rng, checking, brokerage, start, end)
    autopay_pairs, card_balance = _card_payments(checking, card, start, end)

    # Two overlapping checking downloads -> the overlap is what dedup skips.
    older_end = end - timedelta(days=8)
    recent_start = end - timedelta(days=30)
    older_rows, _ = _write_checking(out_dir / "demo_checking_older.csv", checking.rows, OPENING_CHECKING_CENTS, start, older_end)
    recent_rows, checking_balance = _write_checking(out_dir / "demo_checking_recent.csv", checking.rows, OPENING_CHECKING_CENTS, recent_start, end)
    duplicate_rows = sum(1 for r in checking.rows if recent_start <= r.day <= older_end)

    card_rows = _write_card(out_dir / "demo_credit_card.csv", card.rows)
    brokerage_rows = _write_brokerage(out_dir / "demo_brokerage.csv", brokerage.rows)

    return DemoSummary(
        start=start,
        end=end,
        files=[
            ExportFile(CHECKING, "demo_checking.yaml", "demo_checking_older.csv", older_rows),
            ExportFile(CHECKING, "demo_checking.yaml", "demo_checking_recent.csv", recent_rows),
            ExportFile(CARD, "demo_credit_card.yaml", "demo_credit_card.csv", card_rows),
            ExportFile(BROKERAGE, "demo_brokerage.yaml", "demo_brokerage.csv", brokerage_rows),
        ],
        balances_cents={CHECKING: checking_balance, CARD: card_balance},
        holdings=list(HOLDINGS),
        brokerage_cash_cents=BROKERAGE_CASH_CENTS,
        duplicate_rows=duplicate_rows,
        transfer_pairs=contribution_pairs + autopay_pairs,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "statements")
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="last day of data (default: today)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    summary = generate(args.out, args.end, args.seed)
    for f in summary.files:
        print(f"{f.file_name:28} {f.rows:4} rows  ({f.account})")
    print(f"{summary.start} -> {summary.end}; {summary.duplicate_rows} overlapping checking rows; "
          f"{summary.transfer_pairs} transfer pairs")


if __name__ == "__main__":
    main()
