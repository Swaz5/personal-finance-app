"""SQLModel table definitions.

Money is always int cents. Sign convention: from the account's
perspective, outflow negative, inflow positive. Enforced at the importer
boundary, not here.
"""

from datetime import date, datetime
from enum import Enum

from sqlmodel import Field, SQLModel


class InstitutionKind(str, Enum):
    bank = "bank"
    brokerage = "brokerage"
    card = "card"
    loan = "loan"


class AccountType(str, Enum):
    checking = "checking"
    savings = "savings"
    credit = "credit"
    brokerage = "brokerage"
    retirement = "retirement"
    loan = "loan"


class CategoryKind(str, Enum):
    income = "income"
    fixed = "fixed"
    variable = "variable"
    discretionary = "discretionary"
    transfer = "transfer"


class MatchType(str, Enum):
    contains = "contains"
    regex = "regex"


class Institution(SQLModel, table=True):
    __tablename__ = "institutions"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    kind: InstitutionKind


class Account(SQLModel, table=True):
    __tablename__ = "accounts"

    id: int | None = Field(default=None, primary_key=True)
    institution_id: int = Field(foreign_key="institutions.id")
    name: str
    type: AccountType
    currency: str = Field(default="USD")
    external_id: str | None = None
    is_active: bool = Field(default=True)
    include_in_net_worth: bool = Field(default=True)


class Balance(SQLModel, table=True):
    """Time series, not a column on accounts — needed for net worth over time.

    Sign convention: current_cents is the account's contribution to net worth.
    Positive for asset accounts (checking, savings, brokerage, retirement),
    negative for liability accounts (credit, loan) — a card balance owed is
    stored negative so summing every account's latest balance directly
    yields net worth, no per-consumer special-casing on account.type.
    """

    __tablename__ = "balances"

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id", index=True)
    as_of: date = Field(index=True)
    current_cents: int
    available_cents: int | None = None


class Category(SQLModel, table=True):
    __tablename__ = "categories"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    parent_id: int | None = Field(default=None, foreign_key="categories.id")
    kind: CategoryKind


class ImportBatch(SQLModel, table=True):
    __tablename__ = "import_batches"

    id: int | None = Field(default=None, primary_key=True)
    source: str
    imported_at: datetime = Field(default_factory=datetime.utcnow)
    file_name: str
    row_count: int


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id", index=True)
    posted_at: date = Field(index=True)
    amount_cents: int
    description_raw: str
    merchant_normalized: str | None = None
    category_id: int | None = Field(default=None, foreign_key="categories.id")
    is_transfer: bool = Field(default=False, index=True)
    transfer_pair_id: int | None = Field(default=None, foreign_key="transactions.id")
    external_id: str | None = None
    import_batch_id: int | None = Field(default=None, foreign_key="import_batches.id")
    content_hash: str = Field(index=True, unique=True)


class Rule(SQLModel, table=True):
    __tablename__ = "rules"

    id: int | None = Field(default=None, primary_key=True)
    match_pattern: str
    match_type: MatchType
    set_category_id: int = Field(foreign_key="categories.id")
    priority: int = Field(default=0)


class Security(SQLModel, table=True):
    __tablename__ = "securities"

    symbol: str = Field(primary_key=True)
    name: str
    asset_class: str | None = None


class Holding(SQLModel, table=True):
    """Time series, like balances — snapshot per as_of date."""

    __tablename__ = "holdings"

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id", index=True)
    as_of: date = Field(index=True)
    symbol: str = Field(foreign_key="securities.symbol")
    quantity: float
    cost_basis_cents: int | None = None
    market_value_cents: int


class Recurring(SQLModel, table=True):
    __tablename__ = "recurring"

    id: int | None = Field(default=None, primary_key=True)
    merchant_normalized: str
    expected_amount_cents: int
    cadence_days: int
    last_seen: date
    next_expected: date
    confidence: float


class Goal(SQLModel, table=True):
    __tablename__ = "goals"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    target_amount_cents: int
    target_date: date | None = None
    kind: str


class Settings(SQLModel, table=True):
    """Singleton row, id fixed at 1."""

    __tablename__ = "settings"

    id: int | None = Field(default=1, primary_key=True)
    emergency_floor_cents: int = Field(default=0)
    target_retirement_date: date | None = None
    assumed_real_return: float = Field(default=0.05)
