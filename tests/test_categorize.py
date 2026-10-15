import pytest
from sqlmodel import select

from engine.categorize import apply_rules, create_rule_from_override, normalize_merchant, run_llm_fallback
from llm.categorizer import CategorySuggestion
from models import Category, CategoryKind, Rule, Transaction


@pytest.mark.parametrize(
    "raw, merchant",
    [
        ("SQ *BLUE KETTLE COFFEE", "Blue Kettle Coffee"),
        ("TST* LUNA TAQUERIA", "Luna Taqueria"),
        ("DD *DOORDROP NOODLE HOUSE", "Doordrop Noodle House"),
        ("QUICKFUEL #2231", "Quickfuel"),
        ("POS GREENLEAF MARKET #114", "Greenleaf Market"),
    ],
)
def test_normalize_merchant(raw, merchant):
    assert normalize_merchant(raw) == merchant


def test_transfers_get_transfer_category(session):
    transfer_cat = session.exec(select(Category).where(Category.kind == CategoryKind.transfer)).one()
    transfers = session.exec(select(Transaction).where(Transaction.is_transfer == True)).all()  # noqa: E712
    assert transfers and all(t.category_id == transfer_cat.id for t in transfers)


def test_rules_leave_some_work_for_the_categorize_page(demo_db):
    _, report, _ = demo_db
    assert report.rules_assigned > 0
    assert report.still_uncategorized > 0


def test_correction_becomes_a_rule_for_future_imports(fresh_demo):
    session, _, _ = fresh_demo
    entertainment = session.exec(select(Category).where(Category.name == "Entertainment")).one()
    cinema = session.exec(select(Transaction).where(Transaction.merchant_normalized == "Pixel Cinemas")).all()
    assert len(cinema) > 1 and all(t.category_id is None for t in cinema)

    rule = create_rule_from_override(session, cinema[0], entertainment.id)
    assert rule.match_pattern == "Pixel Cinemas"
    assert session.exec(select(Rule).where(Rule.match_pattern == "Pixel Cinemas")).one()

    # The next rules pass picks up every other ticket from the same merchant.
    assert apply_rules(session) == len(cinema) - 1
    for t in cinema:
        session.refresh(t)
        assert t.category_id == entertainment.id


class FakeLLM:
    """Stands in for Ollama: answers every item, the first with a category
    that isn't on the list (which must be ignored)."""

    def categorize_batch(self, items, category_names):
        return [
            CategorySuggestion(
                transaction_id=tid,
                category_name="Not A Category" if i == 0 else "Shopping",
                merchant_normalized="LLM Guess",
            )
            for i, (tid, _desc) in enumerate(items)
        ]


def test_llm_fallback_only_fills_gaps_and_validates_output(fresh_demo):
    session, report, _ = fresh_demo
    assert report.still_uncategorized > 1
    assigned = run_llm_fallback(session, FakeLLM(), batch_size=1000)
    assert assigned == report.still_uncategorized - 1
    # Deterministic merchant names are never overwritten by an LLM guess.
    assert not session.exec(select(Transaction).where(Transaction.merchant_normalized == "LLM Guess")).all()
