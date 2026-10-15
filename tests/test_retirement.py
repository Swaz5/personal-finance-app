from datetime import date

from conftest import END
from engine.retirement import REAL_RETURN_SCENARIOS, project_retirement


def test_three_scenarios_ordered_by_return(session):
    result = project_retirement(session, 90_000_000, date(2056, 10, 14), as_of=END)
    assert [s.real_return for s in result.scenarios] == list(REAL_RETURN_SCENARIOS)
    values = [s.projected_value_cents for s in result.scenarios]
    assert values == sorted(values)
    coast = [s.coast_fi_cents for s in result.scenarios]
    assert coast == sorted(coast, reverse=True)
    assert result.current_invested_cents > 0
    for s in result.scenarios:
        assert s.on_track == (s.gap_or_surplus_cents >= 0)
