from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from fastapi.middleware.cors import CORSMiddleware

from db import get_session, init_db
from engine.affordability import AffordabilityResult, check_affordability
from engine.cashflow import (
    monthly_spend_by_category,
    monthly_totals_by_kind,
    trailing_fixed_expense_monthly,
    trailing_median_by_category,
)
from engine.categorize import (
    apply_rules,
    assign_transfer_categories,
    create_rule_from_override,
    populate_merchant_normalized,
    run_llm_fallback,
)
from engine.holdings import Position, SeedResult, refresh_holdings, seed_holdings
from engine.networth import NetWorthPoint, net_worth_series
from engine.projection import ProjectionResult, project_cash_forward
from engine.recurring import detect_recurring
from engine.retirement import RetirementResult, project_retirement
from engine.transfers import detect_transfers
from importers.base import ingest
from importers.csv_import import load_mapping, parse_csv
from llm.categorizer import OllamaCategorizer
from models import Account, Balance, Category, Goal, Holding, Institution, Recurring, Rule, Settings, Transaction
from paths import ACCOUNTS_CONFIG, DEMO_MODE, MAPPINGS_DIR, REPO_ROOT, STATEMENTS_DIR
from seed import seed_accounts_from_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Personal Finance OS", lifespan=lifespan)

# Vite dev server only. This API is bound to 127.0.0.1 — see run instructions.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SessionDep = Annotated[Session, Depends(get_session)]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "demo" if DEMO_MODE else "real"}


@app.post("/api/accounts/reload")
def reload_accounts(session: SessionDep) -> dict[str, str]:
    """Re-reads config/accounts.yaml and upserts institutions/accounts."""
    if not ACCOUNTS_CONFIG.exists():
        raise HTTPException(404, f"{ACCOUNTS_CONFIG} not found")
    seed_accounts_from_config(session, ACCOUNTS_CONFIG)
    return {"status": "ok"}


@app.get("/api/institutions")
def list_institutions(session: SessionDep) -> list[Institution]:
    return list(session.exec(select(Institution)).all())


@app.get("/api/accounts")
def list_accounts(session: SessionDep) -> list[Account]:
    return list(session.exec(select(Account)).all())


@app.get("/api/transactions")
def list_transactions(
    session: SessionDep,
    account_id: int | None = None,
    uncategorized_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[Transaction]:
    query = select(Transaction).order_by(Transaction.posted_at.desc())
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if uncategorized_only:
        query = query.where(Transaction.category_id == None)  # noqa: E711
    return list(session.exec(query.offset(offset).limit(limit)).all())


@app.post("/api/import/csv")
def import_csv(session: SessionDep, account_id: int, mapping_name: str, file_name: str) -> dict:
    """file_name is relative to data/statements/, mapping_name is relative to
    config/mappings/ (both without extension assumptions — pass full names)."""
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, f"account {account_id} not found")

    csv_path = STATEMENTS_DIR / file_name
    mapping_path = MAPPINGS_DIR / mapping_name
    if not csv_path.exists():
        raise HTTPException(404, f"{csv_path} not found")
    if not mapping_path.exists():
        raise HTTPException(404, f"{mapping_path} not found")

    mapping = load_mapping(mapping_path)
    raw_transactions = parse_csv(csv_path, mapping, account_id)
    result = ingest(session, account_id, source="csv", file_name=file_name, raw_transactions=raw_transactions)

    return {
        "batch_id": result.batch.id,
        "parsed": len(raw_transactions),
        "inserted": result.inserted,
        "skipped_duplicates": result.skipped_duplicates,
    }


@app.post("/api/transfers/detect")
def run_transfer_detection(session: SessionDep) -> dict[str, int]:
    matched = detect_transfers(session)
    return {"pairs_matched": matched}


@app.post("/api/balances")
def record_balance(
    session: SessionDep, account_id: int, as_of: date, current_cents: int, available_cents: int | None = None
) -> Balance:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, f"account {account_id} not found")
    balance = Balance(account_id=account_id, as_of=as_of, current_cents=current_cents, available_cents=available_cents)
    session.add(balance)
    session.commit()
    session.refresh(balance)
    return balance


@app.get("/api/balances")
def list_balances(session: SessionDep, account_id: int | None = None) -> list[Balance]:
    query = select(Balance).order_by(Balance.as_of.desc())
    if account_id is not None:
        query = query.where(Balance.account_id == account_id)
    return list(session.exec(query).all())


@app.get("/api/accounts/current")
def list_current_account_balances(session: SessionDep) -> list[dict]:
    """One row per account with its latest known balance — the dashboard's
    account cards. Cheap alternative to the 12-month net worth reconstruction
    when all you need is where things stand right now."""
    accounts = session.exec(select(Account)).all()
    rows = []
    for account in accounts:
        latest = session.exec(
            select(Balance).where(Balance.account_id == account.id).order_by(Balance.as_of.desc())
        ).first()
        rows.append(
            {
                "account_id": account.id,
                "name": account.name,
                "type": account.type.value,
                "include_in_net_worth": account.include_in_net_worth,
                "current_cents": latest.current_cents if latest else None,
                "as_of": latest.as_of.isoformat() if latest else None,
            }
        )
    return rows


@app.get("/api/categories")
def list_categories(session: SessionDep) -> list[Category]:
    return list(session.exec(select(Category)).all())


@app.post("/api/categorize/run")
def run_categorization(session: SessionDep) -> dict[str, int]:
    """Transfers first (no rules/LLM needed), then merchant normalization,
    then rules. Whatever's left after this needs the LLM fallback or a
    manual override."""
    transfers_assigned = assign_transfer_categories(session)
    normalized = populate_merchant_normalized(session)
    rules_assigned = apply_rules(session)
    remaining = session.exec(select(Transaction).where(Transaction.category_id == None)).all()  # noqa: E711
    return {
        "transfers_assigned": transfers_assigned,
        "merchants_normalized": normalized,
        "rules_assigned": rules_assigned,
        "still_uncategorized": len(remaining),
    }


@app.post("/api/transactions/{transaction_id}/categorize")
def categorize_transaction(session: SessionDep, transaction_id: int, category_id: int) -> dict:
    txn = session.get(Transaction, transaction_id)
    if txn is None:
        raise HTTPException(404, f"transaction {transaction_id} not found")
    category = session.get(Category, category_id)
    if category is None:
        raise HTTPException(404, f"category {category_id} not found")

    rule = create_rule_from_override(session, txn, category_id)
    session.refresh(txn)
    return {"transaction": txn, "rule": rule}


@app.get("/api/rules")
def list_rules(session: SessionDep) -> list[Rule]:
    return list(session.exec(select(Rule).order_by(Rule.priority.desc())).all())


@app.post("/api/categorize/llm-fallback")
def run_llm_categorization(session: SessionDep) -> dict[str, int]:
    """Whatever's left after /api/categorize/run — sent to the local Ollama
    model in small batches. Requires Ollama running on 127.0.0.1:11434."""
    categorizer = OllamaCategorizer()
    assigned = run_llm_fallback(session, categorizer)
    remaining = session.exec(select(Transaction).where(Transaction.category_id == None)).all()  # noqa: E711
    return {"llm_assigned": assigned, "still_uncategorized": len(remaining)}


@app.get("/api/cashflow/monthly")
def get_monthly_cashflow(session: SessionDep, year: int, month: int) -> dict[str, int]:
    return monthly_totals_by_kind(session, year, month)


@app.get("/api/cashflow/trailing-median")
def get_trailing_median(session: SessionDep, months: int = 6) -> dict[str, dict]:
    medians = trailing_median_by_category(session, months=months)
    categories = {c.id: c for c in session.exec(select(Category)).all()}
    return {
        str(cat_id): {"category": categories[cat_id].name, "median_cents": cents}
        for cat_id, cents in medians.items()
        if cat_id in categories
    }


@app.get("/api/cashflow/category-bars")
def get_category_bars(
    session: SessionDep, year: int | None = None, month: int | None = None, trailing_months: int = 6
) -> list[dict]:
    """This month vs. your normal, per spend category — the ghost-marker bar
    chart (section 7). Defaults to the current calendar month."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    current = monthly_spend_by_category(session, year, month)
    medians = trailing_median_by_category(session, months=trailing_months)
    categories = {c.id: c for c in session.exec(select(Category)).all()}

    category_ids = set(current) | set(medians)
    rows = []
    for cat_id in category_ids:
        cat = categories.get(cat_id)
        if cat is None:
            continue
        rows.append(
            {
                "category_id": cat_id,
                "category": cat.name,
                "kind": cat.kind.value,
                "current_cents": current.get(cat_id, 0),
                "median_cents": medians.get(cat_id, 0),
            }
        )
    rows.sort(key=lambda r: r["current_cents"], reverse=True)
    return rows


@app.post("/api/recurring/detect")
def run_recurring_detection(session: SessionDep) -> dict[str, int]:
    count = detect_recurring(session)
    return {"recurring_found": count}


@app.get("/api/recurring")
def list_recurring(session: SessionDep) -> list[Recurring]:
    return list(session.exec(select(Recurring).order_by(Recurring.confidence.desc())).all())


@app.get("/api/settings")
def get_settings(session: SessionDep) -> Settings:
    settings = session.get(Settings, 1)
    if settings is None:
        raise HTTPException(404, "settings row missing")
    return settings


@app.post("/api/settings/emergency-floor")
def set_emergency_floor(session: SessionDep, months: int, trailing_months: int = 6) -> dict:
    """Floor = N months of trailing median fixed expenses (section 4).
    Recomputes and overwrites settings.emergency_floor_cents."""
    monthly_fixed = trailing_fixed_expense_monthly(session, months=trailing_months)
    floor_cents = monthly_fixed * months
    settings = session.get(Settings, 1)
    settings.emergency_floor_cents = floor_cents
    session.add(settings)
    session.commit()
    return {
        "months": months,
        "trailing_monthly_fixed_cents": monthly_fixed,
        "emergency_floor_cents": floor_cents,
    }


@app.get("/api/projection")
def get_projection(
    session: SessionDep,
    account_id: int,
    days: int = 90,
    purchase_cents: int = 0,
    purchase_date: date | None = None,
) -> ProjectionResult:
    return project_cash_forward(
        session,
        account_id,
        days=days,
        hypothetical_amount_cents=purchase_cents,
        hypothetical_date=purchase_date,
    )


@app.post("/api/affordability/check")
def run_affordability_check(
    session: SessionDep,
    account_id: int,
    amount_cents: int,
    purchase_date: date | None = None,
    recurring_monthly_cents: int = 0,
) -> AffordabilityResult:
    return check_affordability(
        session,
        account_id,
        amount_cents,
        purchase_date=purchase_date,
        recurring_monthly_cents=recurring_monthly_cents,
    )


class PositionIn(BaseModel):
    symbol: str
    quantity: float


class SeedHoldingsRequest(BaseModel):
    account_id: int
    cash_cents: int
    positions: list[PositionIn]


@app.post("/api/holdings/seed")
def seed_holdings_endpoint(session: SessionDep, body: SeedHoldingsRequest) -> SeedResult:
    positions = [Position(symbol=p.symbol, quantity=p.quantity) for p in body.positions]
    return seed_holdings(session, body.account_id, positions, body.cash_cents)


@app.post("/api/holdings/refresh")
def refresh_holdings_endpoint(session: SessionDep, account_id: int, cash_cents: int | None = None) -> SeedResult:
    try:
        return refresh_holdings(session, account_id, cash_cents=cash_cents)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/holdings")
def list_holdings(session: SessionDep, account_id: int | None = None) -> list[Holding]:
    query = select(Holding).order_by(Holding.as_of.desc())
    if account_id is not None:
        query = query.where(Holding.account_id == account_id)
    return list(session.exec(query).all())


@app.get("/api/networth/history")
def get_net_worth_history(session: SessionDep, months: int = 12) -> list[NetWorthPoint]:
    return net_worth_series(session, months=months)


class GoalIn(BaseModel):
    name: str
    target_amount_cents: int
    target_date: date | None = None
    kind: str


@app.post("/api/goals")
def create_goal(session: SessionDep, body: GoalIn) -> Goal:
    goal = Goal(**body.model_dump())
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


@app.get("/api/goals")
def list_goals(session: SessionDep) -> list[Goal]:
    return list(session.exec(select(Goal)).all())


@app.get("/api/retirement/projection")
def get_retirement_projection(
    session: SessionDep,
    goal_id: int | None = None,
    target_amount_cents: int | None = None,
    target_date: date | None = None,
) -> RetirementResult:
    if goal_id is not None:
        goal = session.get(Goal, goal_id)
        if goal is None:
            raise HTTPException(404, f"goal {goal_id} not found")
        target_amount_cents = goal.target_amount_cents
        target_date = goal.target_date
    if target_amount_cents is None or target_date is None:
        raise HTTPException(400, "provide goal_id, or both target_amount_cents and target_date")
    return project_retirement(session, target_amount_cents, target_date)


# Serves the built web app (npm run build) so the tray launcher only needs
# one process. Mounted last — every /api/* route above takes precedence.
# Absent during normal `npm run dev` work, where Vite serves the frontend
# and proxies /api/* to this server instead.
WEB_DIST = REPO_ROOT / "web" / "dist"
if WEB_DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
