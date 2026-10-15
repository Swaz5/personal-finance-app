from datetime import timedelta

from sqlmodel import select

import generator
from conftest import END
from engine.holdings import Position, refresh_holdings, seed_holdings
from helpers import account_id
from models import Holding


def test_demo_holdings_seeded(session, summary):
    acct = account_id(session, "Demo Brokerage")
    rows = session.exec(select(Holding).where(Holding.account_id == acct)).all()
    assert {(h.symbol, h.quantity) for h in rows} == set(summary.holdings)


def test_refresh_reprices_same_positions_and_keeps_cash(fresh_demo):
    session, _, _ = fresh_demo
    acct = account_id(session, "Demo Brokerage")
    result = refresh_holdings(session, acct, as_of=END + timedelta(days=1), fetch=lambda s: (200.0, s))
    total_shares = sum(q for _, q in generator.HOLDINGS)
    assert result.market_value_cents == round(total_shares * 200.0 * 100)
    assert result.total_balance_cents - result.market_value_cents == generator.BROKERAGE_CASH_CENTS


def test_unpriced_symbols_are_reported_not_fatal(fresh_demo):
    session, _, _ = fresh_demo
    acct = account_id(session, "Demo Brokerage")

    def fetch(symbol):
        return (100.0, symbol) if symbol == "VTI" else None

    result = seed_holdings(session, acct, [Position("VTI", 1), Position("NOPE", 5)], 0, fetch=fetch)
    assert result.priced == ["VTI"]
    assert result.unpriced == ["NOPE"]
