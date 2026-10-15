"""SQLite engine + session wiring. Table schema lives in models.py (Phase 1).
Which database file is used (real vs. demo) is decided in paths.py."""

from collections.abc import Generator

from sqlmodel import SQLModel, Session, create_engine

from paths import DB_PATH

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    from seed import seed_categories, seed_settings

    with Session(engine) as session:
        seed_categories(session)
        seed_settings(session)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
