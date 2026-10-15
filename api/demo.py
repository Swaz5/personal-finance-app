"""One command to try the app with synthetic data:

    python demo.py              # build a fresh data/demo.db, then serve it
    python demo.py --build-only # just build
    python demo.py --offline    # don't call Yahoo Finance; use static demo prices

Generates ~6 months of fake statements (demo/generator.py) and pushes them
through the same path real data takes: CSV mapping -> importer (with
dedup) -> transfer detection -> rules -> recurring detection -> balances,
holdings, emergency floor, retirement goal. Never touches data/finance.db.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# Must be set before paths/db are imported anywhere in this process.
os.environ["FINANCE_DEMO"] = "1"

import yaml  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

import paths  # noqa: E402
from engine.cashflow import trailing_fixed_expense_monthly  # noqa: E402
from engine.categorize import apply_rules, assign_transfer_categories, populate_merchant_normalized  # noqa: E402
from engine.holdings import PriceFetcher, Position, seed_holdings  # noqa: E402
from engine.prices import fetch_price  # noqa: E402
from engine.recurring import detect_recurring  # noqa: E402
from engine.transfers import detect_transfers  # noqa: E402
from importers.base import ingest  # noqa: E402
from importers.csv_import import load_mapping, parse_csv  # noqa: E402
from models import Account, Balance, Category, Goal, MatchType, Rule, Settings, Transaction  # noqa: E402
from seed import seed_accounts_from_config, seed_categories, seed_settings  # noqa: E402

sys.path.insert(0, str(paths.DEMO_DIR))
import generator  # noqa: E402

EMERGENCY_FLOOR_MONTHS = 3
RETIREMENT_TARGET_CENTS = 90_000_000
RETIREMENT_YEARS = 30


@dataclass
class ImportLine:
    file_name: str
    parsed: int
    inserted: int
    skipped_duplicates: int


@dataclass
class BuildReport:
    imports: list[ImportLine] = field(default_factory=list)
    transfer_pairs: int = 0
    rules_assigned: int = 0
    still_uncategorized: int = 0
    recurring_found: int = 0
    priced_live: list[str] = field(default_factory=list)
    priced_offline: list[str] = field(default_factory=list)
    emergency_floor_cents: int = 0
    balances_cents: dict[str, int] = field(default_factory=dict)


def offline_prices(symbol: str) -> tuple[float, str] | None:
    return generator.APPROX_PRICES.get(symbol)


def _with_fallback(report: BuildReport) -> PriceFetcher:
    def fetch(symbol: str) -> tuple[float, str] | None:
        live = fetch_price(symbol)
        if live is not None:
            report.priced_live.append(symbol)
            return live
        report.priced_offline.append(symbol)
        return offline_prices(symbol)

    return fetch


def _seed_rules(session: Session, rules_path: Path) -> None:
    with open(rules_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    by_name = {c.name: c.id for c in session.exec(select(Category)).all()}
    for r in raw.get("rules") or []:
        session.add(Rule(match_pattern=r["pattern"], match_type=MatchType.contains, set_category_id=by_name[r["category"]]))
    session.commit()


def build_demo(
    db_path: Path,
    statements_dir: Path,
    end: date | None = None,
    fetch: PriceFetcher | None = None,
) -> BuildReport:
    """Builds a fresh demo database at db_path. `fetch` overrides price
    lookup (tests pass offline_prices); default is live with offline fallback."""
    end = end or date.today()
    report = BuildReport()
    fetch = fetch or _with_fallback(report)

    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    summary = generator.generate(statements_dir, end=end)

    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_categories(session)
        seed_settings(session)
        seed_accounts_from_config(session, paths.DEMO_DIR / "accounts.yaml")
        accounts = {a.name: a for a in session.exec(select(Account)).all()}

        for export in summary.files:
            account = accounts[export.account]
            mapping = load_mapping(paths.DEMO_DIR / "mappings" / export.mapping)
            raw = parse_csv(statements_dir / export.file_name, mapping, account.id)
            result = ingest(session, account.id, source="csv", file_name=export.file_name, raw_transactions=raw)
            report.imports.append(ImportLine(export.file_name, len(raw), result.inserted, result.skipped_duplicates))

        report.transfer_pairs = detect_transfers(session)
        _seed_rules(session, paths.DEMO_DIR / "rules.yaml")
        assign_transfer_categories(session)
        populate_merchant_normalized(session)
        report.rules_assigned = apply_rules(session)
        report.still_uncategorized = len(
            session.exec(select(Transaction).where(Transaction.category_id == None)).all()  # noqa: E711
        )
        report.recurring_found = detect_recurring(session)

        for name, cents in summary.balances_cents.items():
            session.add(Balance(account_id=accounts[name].id, as_of=end, current_cents=cents))
        session.commit()

        brokerage = accounts[generator.BROKERAGE]
        positions = [Position(symbol=s, quantity=q) for s, q in summary.holdings]
        seeded = seed_holdings(session, brokerage.id, positions, summary.brokerage_cash_cents, as_of=end, fetch=fetch)

        settings = session.get(Settings, 1)
        settings.emergency_floor_cents = trailing_fixed_expense_monthly(session, months=6, as_of=end) * EMERGENCY_FLOOR_MONTHS
        report.emergency_floor_cents = settings.emergency_floor_cents
        session.add(settings)
        session.add(
            Goal(
                name="Retirement",
                target_amount_cents=RETIREMENT_TARGET_CENTS,
                target_date=end + timedelta(days=round(365.25 * RETIREMENT_YEARS)),
                kind="retirement",
            )
        )
        session.commit()

        report.balances_cents = dict(summary.balances_cents)
        report.balances_cents[generator.BROKERAGE] = seeded.total_balance_cents
    engine.dispose()
    return report


def _print_report(report: BuildReport, db_path: Path) -> None:
    print(f"Built {db_path}")
    for line in report.imports:
        print(f"  {line.file_name:28} parsed {line.parsed:4}  inserted {line.inserted:4}  skipped duplicates {line.skipped_duplicates}")
    print(f"  transfer pairs matched: {report.transfer_pairs}")
    print(f"  categorized by rules: {report.rules_assigned}  (left for you / the LLM fallback: {report.still_uncategorized})")
    print(f"  recurring patterns: {report.recurring_found}")
    if report.priced_live:
        print(f"  live prices (Yahoo Finance): {', '.join(report.priced_live)}")
    if report.priced_offline:
        print(f"  offline demo prices: {', '.join(report.priced_offline)}")
    for name, cents in report.balances_cents.items():
        print(f"  {name:18} {cents / 100:>12,.2f}")
    print(f"  emergency floor ({EMERGENCY_FLOOR_MONTHS} months of fixed costs): {report.emergency_floor_cents / 100:,.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build-only", action="store_true", help="build the demo database and exit")
    parser.add_argument("--offline", action="store_true", help="use static demo prices instead of Yahoo Finance")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    report = build_demo(paths.DB_PATH, paths.STATEMENTS_DIR, fetch=offline_prices if args.offline else None)
    _print_report(report, paths.DB_PATH)
    if args.build_only:
        return

    if not (paths.REPO_ROOT / "web" / "dist").exists():
        print("\nweb/dist not found — run `npm install && npm run build` in web/ to get the UI on this port,")
        print("or `npm run dev` there and open the URL it prints. API docs: /docs")
    print(f"\nDemo running at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
