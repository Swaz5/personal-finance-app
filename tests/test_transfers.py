from datetime import timedelta

from sqlmodel import select

from engine.transfers import WINDOW_DAYS, detect_transfers
from models import Transaction


def test_finds_every_planted_transfer(demo_db, summary):
    _, report, _ = demo_db
    assert report.transfer_pairs == summary.transfer_pairs


def test_pairs_are_opposite_cross_account_and_close(session):
    transfers = session.exec(select(Transaction).where(Transaction.is_transfer == True)).all()  # noqa: E712
    by_id = {t.id: t for t in transfers}
    assert transfers
    for t in transfers:
        other = by_id[t.transfer_pair_id]
        assert other.transfer_pair_id == t.id
        assert other.amount_cents == -t.amount_cents
        assert other.account_id != t.account_id
        assert abs(other.posted_at - t.posted_at) <= timedelta(days=WINDOW_DAYS)
    # No false positives: only the planted autopay / contribution rows pair up.
    assert {t.description_raw for t in transfers} == {
        "DEMO CARD AUTOPAY",
        "AUTOPAY PAYMENT - THANK YOU",
        "ONLINE TRANSFER TO DEMO BROKERAGE",
        "Funds Received - TFR FROM DEMO BANK CHECKING",
    }


def test_detection_is_idempotent(fresh_demo):
    session, _, _ = fresh_demo
    assert detect_transfers(session) == 0
