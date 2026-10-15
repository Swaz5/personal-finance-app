"""LLM fallback for categorization — only for transactions the rules engine
missed (section 5). The LLM classifies text; it never computes a number
that appears in a financial decision.

Ollama keeps this fully on-device per the privacy note. Swap in an
Anthropic-backed implementation of the same Categorizer protocol later if
you decide that tradeoff is worth it — nothing else in the pipeline needs
to change.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

OLLAMA_HOST = "http://127.0.0.1:11434"


@dataclass
class CategorySuggestion:
    transaction_id: int
    category_name: str
    merchant_normalized: str | None = None


class Categorizer(Protocol):
    def categorize_batch(
        self, items: list[tuple[int, str]], category_names: list[str]
    ) -> list[CategorySuggestion]: ...


class OllamaCategorizer:
    def __init__(self, model: str = "llama3.2:3b", host: str = OLLAMA_HOST):
        self.model = model
        self.host = host

    def categorize_batch(
        self, items: list[tuple[int, str]], category_names: list[str]
    ) -> list[CategorySuggestion]:
        if not items:
            return []

        lines = "\n".join(f"{tid}: {desc}" for tid, desc in items)
        categories_list = ", ".join(category_names)
        prompt = (
            "You are categorizing personal finance transactions. For each "
            "transaction below (format: id: description), pick exactly one "
            f"category from this fixed list: {categories_list}. Also strip any "
            "payment-processor prefix, store number, or transaction code from "
            "the description and give back just the clean merchant name, "
            "title-cased. Base it only on that transaction's own description "
            "— never reuse a name from a different transaction or from these "
            "instructions.\n\n"
            f"Transactions:\n{lines}\n\n"
            'Respond with ONLY a JSON object of the form '
            '{"<id>": {"category": "<name>", "merchant": "<name>"}, ...} '
            "covering every id given. No other text."
        )
        payload = json.dumps(
            {"model": self.model, "prompt": prompt, "stream": False, "format": "json"}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/generate", data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama request failed — is it running? {e}") from e

        try:
            parsed = json.loads(body.get("response", "{}"))
        except json.JSONDecodeError:
            return []

        valid_categories = set(category_names)
        suggestions = []
        for tid_str, val in parsed.items():
            try:
                tid = int(tid_str)
            except (TypeError, ValueError):
                continue
            if not isinstance(val, dict):
                continue
            category = val.get("category")
            if category not in valid_categories:
                continue
            suggestions.append(
                CategorySuggestion(
                    transaction_id=tid, category_name=category, merchant_normalized=val.get("merchant")
                )
            )
        return suggestions
