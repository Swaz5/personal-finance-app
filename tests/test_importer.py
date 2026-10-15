from pathlib import Path

import pytest

import paths
from importers.csv_import import MappingConfig, _parse_amount_to_cents, load_mapping, parse_csv

MAPPINGS = paths.DEMO_DIR / "mappings"


@pytest.mark.parametrize(
    "raw, cents",
    [
        ("12.34", 1234),
        ("-12.34", -1234),
        ("$1,234.56", 123456),
        ("-$500.00", -50000),
        ("(1,234.56)", -123456),
        ("", None),
        ("  ", None),
    ],
)
def test_amount_parsing(raw, cents):
    assert _parse_amount_to_cents(raw) == cents


@pytest.mark.parametrize(
    "kwargs",
    [
        {"amount_mode": "single"},
        {"amount_mode": "split", "debit_column": "w"},
        {"amount_mode": "both"},
    ],
)
def test_mapping_validation(kwargs):
    with pytest.raises(ValueError):
        MappingConfig(institution="x", date_column="d", date_format="%Y", description_column="c", **kwargs)


def _parse(statements: Path, file_name: str, mapping: str):
    return parse_csv(statements / file_name, load_mapping(MAPPINGS / mapping), account_id=1)


def test_split_mode_checking(demo_db):
    _, _, statements = demo_db
    rows = _parse(statements, "demo_checking_older.csv", "demo_checking.yaml")
    rent = [r for r in rows if "RENT" in r.description_raw]
    pay = [r for r in rows if "DIRECT DEP" in r.description_raw]
    assert rent and all(r.amount_cents == -165_000 for r in rent)  # withdrawal -> negative
    assert pay and all(r.amount_cents > 0 for r in pay)  # deposit -> positive


def test_negated_card_convention(demo_db):
    _, _, statements = demo_db
    rows = _parse(statements, "demo_credit_card.csv", "demo_credit_card.yaml")
    payments = [r for r in rows if "AUTOPAY PAYMENT" in r.description_raw]
    purchases = [r for r in rows if "GREENLEAF" in r.description_raw]
    assert payments and all(r.amount_cents > 0 for r in payments)
    assert purchases and all(r.amount_cents < 0 for r in purchases)


def test_extra_description_column_brokerage(demo_db):
    _, _, statements = demo_db
    rows = _parse(statements, "demo_brokerage.csv", "demo_brokerage.yaml")
    buys = [r for r in rows if r.description_raw.startswith("Buy - ")]
    assert buys and all(r.amount_cents < 0 for r in buys)
    assert any(r.description_raw.startswith("Dividend - ") and r.amount_cents > 0 for r in rows)
