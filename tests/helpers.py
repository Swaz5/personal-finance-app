from sqlmodel import Session, select

from models import Account


def account_id(session: Session, name: str) -> int:
    return session.exec(select(Account).where(Account.name == name)).one().id
