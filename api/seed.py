"""Default category tree and settings singleton. Idempotent — safe to call on
every startup. 15-20 categories max, coarse enough to actually maintain.
"""

from pathlib import Path

import yaml
from sqlmodel import Session, select

from models import Account, AccountType, Category, CategoryKind, Institution, InstitutionKind, Settings

DEFAULT_CATEGORIES: list[tuple[str, CategoryKind]] = [
    ("Income", CategoryKind.income),
    ("Housing", CategoryKind.fixed),
    ("Utilities", CategoryKind.fixed),
    ("Insurance", CategoryKind.fixed),
    ("Debt Payments", CategoryKind.fixed),
    ("Subscriptions", CategoryKind.fixed),
    ("Groceries", CategoryKind.variable),
    ("Transportation", CategoryKind.variable),
    ("Healthcare", CategoryKind.variable),
    ("Personal Care", CategoryKind.variable),
    ("Dining Out", CategoryKind.discretionary),
    ("Entertainment", CategoryKind.discretionary),
    ("Shopping", CategoryKind.discretionary),
    ("Travel", CategoryKind.discretionary),
    ("Gifts & Donations", CategoryKind.discretionary),
    ("Transfer", CategoryKind.transfer),
]


def seed_categories(session: Session) -> None:
    if session.exec(select(Category)).first():
        return
    for name, kind in DEFAULT_CATEGORIES:
        session.add(Category(name=name, kind=kind))
    session.commit()


def seed_settings(session: Session) -> None:
    if session.get(Settings, 1):
        return
    session.add(Settings(id=1))
    session.commit()


def seed_accounts_from_config(session: Session, config_path: Path) -> None:
    """Upserts institutions/accounts from config/accounts.yaml, matched by
    name so re-running after edits updates rather than duplicates."""
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    for inst_raw in raw.get("institutions") or []:
        institution = session.exec(
            select(Institution).where(Institution.name == inst_raw["name"])
        ).first()
        if institution is None:
            institution = Institution(name=inst_raw["name"], kind=InstitutionKind(inst_raw["kind"]))
            session.add(institution)
            session.flush()
        else:
            institution.kind = InstitutionKind(inst_raw["kind"])

        for acc_raw in inst_raw.get("accounts") or []:
            account = session.exec(
                select(Account).where(
                    Account.institution_id == institution.id,
                    Account.name == acc_raw["name"],
                )
            ).first()
            if account is None:
                account = Account(
                    institution_id=institution.id,
                    name=acc_raw["name"],
                    type=AccountType(acc_raw["type"]),
                    include_in_net_worth=acc_raw.get("include_in_net_worth", True),
                )
                session.add(account)
            else:
                account.type = AccountType(acc_raw["type"])
                account.include_in_net_worth = acc_raw.get("include_in_net_worth", True)

    session.commit()
