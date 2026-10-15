from conftest import END
from engine.affordability import check_affordability
from engine.projection import project_cash_forward
from helpers import account_id


def _check(session, dollars, monthly=0):
    return check_affordability(
        session,
        account_id(session, "Demo Checking"),
        dollars * 100,
        purchase_date=END,
        recurring_monthly_cents=monthly * 100,
    )


def test_emergency_floor_is_three_months_of_fixed_costs(demo_db):
    _, report, _ = demo_db
    # Rent alone is $1,650/mo, so 3 months of fixed costs is above $4,950.
    assert report.emergency_floor_cents > 3 * 165_000


def test_small_purchase_is_green(session):
    result = _check(session, 300)
    assert result.verdict == "green"
    assert result.post_purchase_balance_cents == result.current_balance_cents - 30_000


def test_purchase_that_breaks_the_floor_is_red(session):
    result = _check(session, 6_000)
    assert result.verdict == "red"
    assert any("below your emergency floor" in r for r in result.reasons)


def test_financed_purchase_flags_savings_rate_drop(session):
    result = _check(session, 300, monthly=550)
    assert result.savings_effect is not None
    assert result.savings_effect.new_rate < result.savings_effect.old_rate
    assert result.verdict in ("yellow", "red")


def test_trough_drops_by_the_purchase_amount(session):
    acct = account_id(session, "Demo Checking")
    base = project_cash_forward(session, acct, as_of=END)
    hit = project_cash_forward(session, acct, as_of=END, hypothetical_amount_cents=100_000, hypothetical_date=END)
    assert len(base.daily) == 91
    assert base.patterns_used > 0
    assert hit.trough.balance_cents == base.trough.balance_cents - 100_000
