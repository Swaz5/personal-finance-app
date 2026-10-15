from sqlmodel import select

from models import Recurring


def test_detects_pay_rent_and_subscriptions(session):
    found = {r.merchant_normalized: r for r in session.exec(select(Recurring)).all()}
    assert found["Acme Analytics Inc"].cadence_days == 14
    assert found["Acme Analytics Inc"].expected_amount_cents > 0
    assert found["Maple Grove Apts"].expected_amount_cents == -165_000
    assert 28 <= found["Maple Grove Apts"].cadence_days <= 31
    assert {"Streambox Subscription", "Tunewave Premium", "Harbor Fitness Club"} <= found.keys()


def test_one_offs_are_not_recurring(session):
    names = {r.merchant_normalized for r in session.exec(select(Recurring)).all()}
    assert "Skyline Air" not in names
    assert "County Vehicle Registration" not in names
