"""Holdings + brokerage balance orchestration (Phase 5, manual-entry path).
Seeds positions once, then refresh re-prices the same positions going
forward. Quantity changes (new buys/sells) require re-seeding — this app
doesn't parse share quantities out of the CSV importer (Phase 1 only
captured cash effect), so it can't detect position changes on its own.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from engine.prices import fetch_price
from models import Account, Balance, Holding, Security

PriceFetcher = Callable[[str], tuple[float, str] | None]


@dataclass
class Position:
    symbol: str
    quantity: float


@dataclass
class SeedResult:
    priced: list[str]
    unpriced: list[str]
    market_value_cents: int
    total_balance_cents: int


def _upsert_security(session: Session, symbol: str, name: str) -> None:
    existing = session.get(Security, symbol)
    if existing:
        existing.name = name
        session.add(existing)
    else:
        session.add(Security(symbol=symbol, name=name, asset_class="equity"))


def seed_holdings(
    session: Session,
    account_id: int,
    positions: list[Position],
    cash_cents: int,
    as_of: date | None = None,
    fetch: PriceFetcher = fetch_price,
) -> SeedResult:
    as_of = as_of or date.today()
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError(f"account {account_id} not found")

    priced: list[str] = []
    unpriced: list[str] = []
    market_value_total = 0

    for pos in positions:
        result = fetch(pos.symbol)
        if result is None:
            unpriced.append(pos.symbol)
            continue
        price, name = result
        _upsert_security(session, pos.symbol, name)
        market_value_cents = round(pos.quantity * price * 100)
        market_value_total += market_value_cents
        session.add(
            Holding(
                account_id=account_id,
                as_of=as_of,
                symbol=pos.symbol,
                quantity=pos.quantity,
                market_value_cents=market_value_cents,
            )
        )
        priced.append(pos.symbol)

    total_balance = market_value_total + cash_cents
    session.add(Balance(account_id=account_id, as_of=as_of, current_cents=total_balance))
    session.commit()

    return SeedResult(
        priced=priced,
        unpriced=unpriced,
        market_value_cents=market_value_total,
        total_balance_cents=total_balance,
    )


def refresh_holdings(
    session: Session,
    account_id: int,
    cash_cents: int | None = None,
    as_of: date | None = None,
    fetch: PriceFetcher = fetch_price,
) -> SeedResult:
    """Re-prices whatever symbols/quantities appeared in the most recent
    holdings snapshot for this account."""
    as_of = as_of or date.today()
    latest_date = session.exec(
        select(Holding.as_of).where(Holding.account_id == account_id).order_by(Holding.as_of.desc())
    ).first()
    if latest_date is None:
        raise ValueError(f"no holdings recorded yet for account {account_id} — call seed_holdings first")

    latest_holdings = session.exec(
        select(Holding).where(Holding.account_id == account_id, Holding.as_of == latest_date)
    ).all()

    if cash_cents is None:
        latest_balance = session.exec(
            select(Balance).where(Balance.account_id == account_id).order_by(Balance.as_of.desc())
        ).first()
        prior_market_value = sum(h.market_value_cents for h in latest_holdings)
        cash_cents = (latest_balance.current_cents - prior_market_value) if latest_balance else 0

    positions = [Position(symbol=h.symbol, quantity=h.quantity) for h in latest_holdings]
    return seed_holdings(session, account_id, positions, cash_cents, as_of=as_of, fetch=fetch)
