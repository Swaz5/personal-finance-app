"""Current price lookup for holdings market value (Phase 5). Yahoo Finance's
public chart endpoint — no API key, no signup. Current price only; this
does not fetch history (see BUILD_PLAN.md Phase 5 notes on the net worth
chart's brokerage approximation).
"""

import json
import urllib.error
import urllib.request

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def fetch_price(symbol: str) -> tuple[float, str] | None:
    """Returns (price, long_name) or None if the symbol can't be resolved."""
    req = urllib.request.Request(
        YAHOO_CHART_URL.format(symbol=symbol), headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError:
        return None

    result = body.get("chart", {}).get("result")
    if not result:
        return None
    meta = result[0].get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    name = meta.get("longName") or meta.get("shortName") or symbol
    return float(price), name
