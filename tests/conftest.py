"""Tests run against synthetic demo data only — never data/finance.db.
FINANCE_DB_PATH is pointed at a temp file before any app module is
imported, so even the FastAPI app's own engine lands in the temp dir."""

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix="pf-tests-"))
os.environ["FINANCE_DB_PATH"] = str(_TMP / "app.db")
sys.path.insert(0, str(REPO_ROOT / "api"))
sys.path.insert(0, str(REPO_ROOT / "demo"))

from sqlmodel import Session, create_engine  # noqa: E402

import demo  # noqa: E402  (sets FINANCE_DEMO=1; DB path stays overridden)
import generator  # noqa: E402

# Fixed anchor date so every number the engines produce is reproducible.
END = date(2026, 10, 14)


def build(tmp: Path, end: date = END):
    db_path = tmp / "demo.db"
    statements = tmp / "statements"
    report = demo.build_demo(db_path, statements, end=end, fetch=demo.offline_prices)
    engine = create_engine(f"sqlite:///{db_path}")
    return engine, report, statements


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory):
    """Read-only shared demo database. Tests that write use fresh_demo."""
    engine, report, statements = build(tmp_path_factory.mktemp("shared"))
    yield engine, report, statements
    engine.dispose()


@pytest.fixture
def session(demo_db):
    engine, _, _ = demo_db
    with Session(engine) as s:
        yield s


@pytest.fixture
def fresh_demo(tmp_path):
    engine, report, statements = build(tmp_path)
    with Session(engine) as s:
        yield s, report, statements
    engine.dispose()


@pytest.fixture(scope="session")
def summary(tmp_path_factory):
    return generator.generate(tmp_path_factory.mktemp("gen"), end=END)
