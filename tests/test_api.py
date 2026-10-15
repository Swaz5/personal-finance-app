"""Smoke test through FastAPI, on a demo database built for *today* — the
endpoints default their dates to date.today()."""

import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import demo


@pytest.fixture(scope="module")
def client():
    db_path = Path(os.environ["FINANCE_DB_PATH"])
    demo.build_demo(db_path, db_path.parent / "api-statements", end=date.today(), fetch=demo.offline_prices)
    import main

    with TestClient(main.app) as c:
        yield c


def _account(client, name):
    return next(a for a in client.get("/api/accounts").json() if a["name"] == name)


def test_health_reports_demo_mode(client):
    assert client.get("/api/health").json() == {"status": "ok", "mode": "demo"}


def test_dashboard_endpoints(client):
    accounts = client.get("/api/accounts/current").json()
    assert {a["name"] for a in accounts} == {"Demo Checking", "Demo Credit Card", "Demo Brokerage"}
    assert all(a["current_cents"] is not None for a in accounts)
    assert len(client.get("/api/networth/history?months=12").json()) > 300
    assert client.get("/api/cashflow/category-bars").status_code == 200
    assert client.get("/api/recurring").json()


def test_afford_and_retirement(client):
    checking = _account(client, "Demo Checking")
    r = client.post(f"/api/affordability/check?account_id={checking['id']}&amount_cents=30000")
    assert r.status_code == 200
    assert r.json()["verdict"] in ("green", "yellow", "red")
    goal = client.get("/api/goals").json()[0]
    assert len(client.get(f"/api/retirement/projection?goal_id={goal['id']}").json()["scenarios"]) == 3


def test_refresh_without_holdings_is_400(client):
    checking = _account(client, "Demo Checking")
    assert client.post(f"/api/holdings/refresh?account_id={checking['id']}").status_code == 400
