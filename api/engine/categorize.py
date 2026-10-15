"""Categorization pipeline: rules first, LLM fallback only for what rules
miss (section 5). Manual overrides write back a new rule, so the LLM's job
shrinks every month.

Transfers are categorized directly from the is_transfer flag, bypassing
rules and the LLM entirely — we already know they're not spend.
"""

import re

from sqlmodel import Session, select

from llm.categorizer import Categorizer
from models import Category, CategoryKind, MatchType, Rule, Transaction

_KNOWN_PREFIXES = re.compile(r"^(SQ \*|TST\*|DD \*|PAYPAL \*|POS |ACH |SP )", re.IGNORECASE)
_LEADING_NOISE = re.compile(r"^[\d\s*#.\-]+")
_ALPHA_RUN = re.compile(r"^([A-Za-z][A-Za-z&'.\-]*(?:\s+[A-Za-z][A-Za-z&'.\-]*){0,2})")


def normalize_merchant(description: str) -> str:
    """Best-effort deterministic normalization (e.g. "SQ *BLUE BOTTLE #4471"
    -> "Blue Bottle"). The LLM fallback refines this further for whatever
    transactions it also categorizes."""
    text = _KNOWN_PREFIXES.sub("", description.strip())
    text = _LEADING_NOISE.sub("", text)
    m = _ALPHA_RUN.match(text)
    token = m.group(1).strip() if m and len(m.group(1)) >= 3 else text[:20].strip()
    return token.title() if token else description.strip()[:20].title()


def populate_merchant_normalized(session: Session) -> int:
    txns = session.exec(select(Transaction).where(Transaction.merchant_normalized == None)).all()  # noqa: E711
    for t in txns:
        t.merchant_normalized = normalize_merchant(t.description_raw)
        session.add(t)
    session.commit()
    return len(txns)


def assign_transfer_categories(session: Session) -> int:
    transfer_cat = session.exec(select(Category).where(Category.kind == CategoryKind.transfer)).first()
    if transfer_cat is None:
        return 0
    txns = session.exec(
        select(Transaction).where(Transaction.is_transfer == True, Transaction.category_id == None)  # noqa: E711,E712
    ).all()
    for t in txns:
        t.category_id = transfer_cat.id
        session.add(t)
    session.commit()
    return len(txns)


def _rule_matches(rule: Rule, description: str) -> bool:
    if rule.match_type == MatchType.contains:
        return rule.match_pattern.lower() in description.lower()
    return re.search(rule.match_pattern, description, re.IGNORECASE) is not None


def apply_rules(session: Session) -> int:
    """Applies active rules (highest priority first) to uncategorized,
    non-transfer transactions. First matching rule wins."""
    rules = session.exec(select(Rule).order_by(Rule.priority.desc())).all()
    if not rules:
        return 0
    txns = session.exec(
        select(Transaction).where(
            Transaction.category_id == None,  # noqa: E711
            Transaction.is_transfer == False,  # noqa: E712
        )
    ).all()
    assigned = 0
    for t in txns:
        for rule in rules:
            if _rule_matches(rule, t.description_raw):
                t.category_id = rule.set_category_id
                session.add(t)
                assigned += 1
                break
    session.commit()
    return assigned


def run_llm_fallback(session: Session, categorizer: Categorizer, batch_size: int = 25) -> int:
    """Whatever rules didn't catch, in small batches — a 3B local model
    stays reliable at this scale, not at hundreds of rows in one prompt."""
    categories = session.exec(select(Category)).all()
    category_names = [c.name for c in categories]
    name_to_id = {c.name: c.id for c in categories}

    txns = session.exec(
        select(Transaction).where(
            Transaction.category_id == None,  # noqa: E711
            Transaction.is_transfer == False,  # noqa: E712
        )
    ).all()

    assigned = 0
    for i in range(0, len(txns), batch_size):
        batch = txns[i : i + batch_size]
        items = [(t.id, t.description_raw) for t in batch]
        suggestions = {s.transaction_id: s for s in categorizer.categorize_batch(items, category_names)}
        for t in batch:
            suggestion = suggestions.get(t.id)
            # LLM output is untrusted: an unknown category name is skipped,
            # whichever Categorizer implementation produced it.
            if suggestion is None or suggestion.category_name not in name_to_id:
                continue
            t.category_id = name_to_id[suggestion.category_name]
            # Deterministic normalization (populate_merchant_normalized) already
            # ran and is trustworthy; never let an LLM guess overwrite it — a
            # small model can anchor on an unrelated name it saw elsewhere in
            # the same run.
            if suggestion.merchant_normalized and not t.merchant_normalized:
                t.merchant_normalized = suggestion.merchant_normalized
            session.add(t)
            assigned += 1
        session.commit()
    return assigned


def create_rule_from_override(session: Session, txn: Transaction, category_id: int) -> Rule:
    """Manual override: assigns the category and writes back a rule keyed on
    the normalized merchant, so future imports from the same merchant
    auto-categorize without hitting the LLM."""
    pattern = txn.merchant_normalized or normalize_merchant(txn.description_raw)

    existing = session.exec(
        select(Rule).where(Rule.match_pattern == pattern, Rule.match_type == MatchType.contains)
    ).first()
    if existing:
        existing.set_category_id = category_id
        session.add(existing)
        rule = existing
    else:
        rule = Rule(match_pattern=pattern, match_type=MatchType.contains, set_category_id=category_id, priority=0)
        session.add(rule)

    txn.category_id = category_id
    if not txn.merchant_normalized:
        txn.merchant_normalized = pattern
    session.add(txn)

    session.commit()
    session.refresh(rule)
    return rule
