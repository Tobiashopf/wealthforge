from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wealthforge.config import Settings
from wealthforge.web.app import create_app

from .conftest import TODAY
from .test_quotes import fake_internet


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(tmp_path / "web.db", brapi_token=None, finnhub_token="k")
    app = create_app(
        settings,
        today=lambda: TODAY,
        http_client=lambda: httpx.Client(transport=httpx.MockTransport(fake_internet)),
    )
    with TestClient(app, follow_redirects=False) as client:
        yield client


def create(client: TestClient, **form: str) -> int:
    response = client.post("/assets", data=form)
    assert response.status_code == 303, response.text
    return int(response.headers["location"].split("/")[2].split("?")[0])


def test_empty_dashboard_invites_first_asset(app_client: TestClient) -> None:
    page = app_client.get("/")
    assert page.status_code == 200
    assert "Add your first asset" in page.text


def test_full_flow_for_a_property(app_client: TestClient) -> None:
    asset_id = create(app_client, name="Beach flat", kind="real_estate", currency="BRL")

    r = app_client.post(
        f"/assets/{asset_id}/trades",
        data={
            "side": "buy",
            "trade_date": "2025-03-01",
            "quantity": "0,5",
            "unit_price": "600.000,00",
            "fees": "12.000,00",
        },
    )
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    app_client.post(
        f"/assets/{asset_id}/prices", data={"price_date": "2026-09-01", "unit_price": "700000"}
    )
    app_client.post(
        f"/assets/{asset_id}/income",
        data={"income_date": "2026-10-10", "kind": "rent", "amount": "1.800,00"},
    )

    detail = app_client.get(f"/assets/{asset_id}").text
    assert "50% owned" in detail
    assert "R$ 350.000,00" in detail  # 50% of 700k
    assert "R$ 1.800,00" in detail

    dashboard = app_client.get("/").text
    assert "R$ 350.000,00" in dashboard
    assert "Real estate" in dashboard


def test_validation_errors_are_shown(app_client: TestClient) -> None:
    r = app_client.post("/assets", data={"name": "", "kind": "stock", "currency": "BRL"})
    assert r.status_code == 422
    assert "name is required" in r.text

    asset_id = create(app_client, name="Stock", kind="stock", currency="BRL")
    r = app_client.post(
        f"/assets/{asset_id}/trades",
        data={"side": "sell", "trade_date": "2026-10-01", "quantity": "1", "unit_price": "10"},
    )
    assert "error=" in r.headers["location"]
    page = app_client.get(r.headers["location"]).text
    assert "exceeds" in page


def test_refresh_button_updates_prices(app_client: TestClient) -> None:
    asset_id = create(app_client, name="Petrobras", kind="stock", currency="BRL", ticker="PETR4")
    app_client.post(
        f"/assets/{asset_id}/trades",
        data={"side": "buy", "trade_date": "2026-10-01", "quantity": "100", "unit_price": "9"},
    )
    r = app_client.post("/refresh")
    assert r.status_code == 303
    assert "Updated" in app_client.get(r.headers["location"]).text
    assert "R$ 1.050,00" in app_client.get("/").text  # 100 x 10.50


def test_manual_fx_rate(app_client: TestClient) -> None:
    r = app_client.post("/fx", data={"currency": "USD", "rate_date": "2026-11-01", "rate": "5,5"})
    assert "msg=" in r.headers["location"]
    assert "5.5" in app_client.get("/").text
    r = app_client.post("/fx", data={"currency": "USD", "rate_date": "2026-11-01", "rate": "-1"})
    assert "error=" in r.headers["location"]


def test_edit_and_delete(app_client: TestClient) -> None:
    asset_id = create(app_client, name="Old name", kind="fund", currency="BRL")
    app_client.post(
        f"/assets/{asset_id}",
        data={"name": "New name", "kind": "fund", "currency": "BRL", "notes": "hello"},
    )
    assert "New name" in app_client.get(f"/assets/{asset_id}").text

    app_client.post(
        f"/assets/{asset_id}/trades",
        data={"side": "buy", "trade_date": "2026-10-01", "quantity": "1", "unit_price": "10"},
    )
    app_client.post(f"/assets/{asset_id}/delete")
    assert app_client.get(f"/assets/{asset_id}").status_code == 404


def test_static_files_are_served(app_client: TestClient) -> None:
    assert app_client.get("/static/style.css").status_code == 200
    assert app_client.get("/static/app.js").status_code == 200


def test_decimal_values_render_without_floats(app_client: TestClient) -> None:
    asset_id = create(app_client, name="Bond", kind="fixed_income", currency="BRL")
    app_client.post(
        f"/assets/{asset_id}/trades",
        data={"side": "buy", "trade_date": "2026-10-01", "quantity": "3", "unit_price": "0,1"},
    )
    # 3 x 0.1 must be exactly 0.30, not 0.30000000000000004
    assert "R$ 0,30" in app_client.get(f"/assets/{asset_id}").text
    assert D("0.1") * 3 == D("0.3")
