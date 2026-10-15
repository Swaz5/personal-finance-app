from sqlmodel import select

import paths
from helpers import account_id
from importers.base import ingest
from importers.csv_import import load_mapping, parse_csv
from models import Transaction


def test_overlapping_exports_skip_exactly_the_overlap(demo_db, summary):
    _, report, _ = demo_db
    recent = next(line for line in report.imports if line.file_name == "demo_checking_recent.csv")
    assert recent.skipped_duplicates == summary.duplicate_rows
    assert recent.inserted == recent.parsed - summary.duplicate_rows
    others = [line for line in report.imports if line.file_name != "demo_checking_recent.csv"]
    assert all(line.skipped_duplicates == 0 for line in others)


def test_reimporting_a_file_inserts_nothing(fresh_demo):
    session, _, statements = fresh_demo
    card = account_id(session, "Demo Credit Card")
    before = len(session.exec(select(Transaction)).all())
    mapping = load_mapping(paths.DEMO_DIR / "mappings" / "demo_credit_card.yaml")
    raw = parse_csv(statements / "demo_credit_card.csv", mapping, account_id=card)
    result = ingest(session, card, source="csv", file_name="again.csv", raw_transactions=raw)
    assert result.inserted == 0
    assert result.skipped_duplicates == len(raw)
    assert len(session.exec(select(Transaction)).all()) == before
