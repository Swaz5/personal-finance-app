from datetime import timedelta

import generator
from conftest import END


def test_same_seed_and_date_is_byte_identical(tmp_path):
    a = generator.generate(tmp_path / "a", end=END)
    generator.generate(tmp_path / "b", end=END)
    for f in a.files:
        assert (tmp_path / "a" / f.file_name).read_bytes() == (tmp_path / "b" / f.file_name).read_bytes()


def test_covers_about_six_months(summary):
    assert summary.end == END
    assert timedelta(days=175) <= summary.end - summary.start <= timedelta(days=190)


def test_plants_duplicates_and_transfers(summary):
    assert summary.duplicate_rows > 0
    assert summary.transfer_pairs >= 10  # ~6 autopays + ~6 brokerage contributions


def test_holdings_are_common_etfs(summary):
    assert {s for s, _ in summary.holdings} == {"VTI", "VXUS", "BND"}
