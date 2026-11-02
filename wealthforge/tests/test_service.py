from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from wealthforge.db import SCHEMA_VERSION, Database, NotFoundError
from wealthforge.models import AssetKind, Currency, PriceSource
from wealthforge.sample import load_sample
from wealthforge.service import PortfolioService, ValidationError

from .conftest import TODAY


def test_price_source_is_chosen_from_kind_currency_and_ticker(service: PortfolioService) -> None:
    b3 = service.create_asset("Petrobras", "stock", "BRL", " petr4 ")
    us = service.create_asset("S&P 500 ETF", "etf", "USD", "VOO")
    flat = service.create_asset("Flat", "real_estate", "BRL")
    assert (b3.ticker, b3.price_source) == ("PETR4", PriceSource.BRAPI)
    assert us.price_source is PriceSource.FINNHUB
    assert flat.price_source is PriceSource.MANUAL


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": " ", "kind": "stock"}, "name is required"),
        ({"name": "x" * 81, "kind": "stock"}, "longer than"),
        ({"name": "x", "kind": "spaceship"}, "spaceship"),
        ({"name": "x", "kind": "stock", "currency": "EUR"}, "EUR"),
        ({"name": "x", "kind": "stock", "price_source": "brapi"}, "needs a ticker"),
        (
            {
                "name": "x",
                "kind": "stock",
                "ticker": "AAPL",
                "currency": "USD",
                "price_source": "brapi",
            },
            "BRL",
        ),
        ({"name": "x", "kind": "stock", "ticker": "PETR4", "price_source": "finnhub"}, "USD"),
        ({"name": "x", "kind": "stock", "ticker": "DROP TABLE"}, "looks invalid"),
    ],
)
def test_asset_validation(service: PortfolioService, kwargs: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        service.create_asset(**kwargs)


def test_trade_validation(service: PortfolioService) -> None:
    stock = service.create_asset("Stock", "stock")
    with pytest.raises(ValidationError, match="future"):
        service.record_trade(stock.id, "buy", "2026-11-03", "1", "10", today=TODAY)
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        service.record_trade(stock.id, "buy", "02/11/2026", "1", "10", today=TODAY)
    with pytest.raises(ValidationError, match="quantity must be greater"):
        service.record_trade(stock.id, "buy", "2026-11-01", "0", "10", today=TODAY)
    with pytest.raises(ValidationError, match="side"):
        service.record_trade(stock.id, "short", "2026-11-01", "1", "10", today=TODAY)
    service.record_trade(stock.id, "buy", "2026-10-01", "10", "10", today=TODAY)
    with pytest.raises(ValidationError, match="exceeds"):
        service.record_trade(stock.id, "sell", "2026-10-02", "11", "10", today=TODAY)
    # A sale dated before the purchase is also rejected.
    with pytest.raises(ValidationError, match="exceeds"):
        service.record_trade(stock.id, "sell", "2026-09-01", "1", "10", today=TODAY)


def test_ownership_fraction_rules(service: PortfolioService) -> None:
    flat = service.create_asset("Flat", "real_estate")
    with pytest.raises(ValidationError, match="fraction you own"):
        service.record_trade(flat.id, "buy", "2026-01-01", "2", "300000", today=TODAY)
    service.record_trade(flat.id, "buy", "2026-01-01", "0.6", "300000", today=TODAY)
    with pytest.raises(ValidationError, match="more than 100%"):
        service.record_trade(flat.id, "buy", "2026-02-01", "0.5", "300000", today=TODAY)


def test_manual_purchase_also_records_a_value(service: PortfolioService, db: Database) -> None:
    flat = service.create_asset("Flat", AssetKind.REAL_ESTATE)
    service.record_trade(flat.id, "buy", "2026-01-01", "1", "300.000,00", "9.000,00", today=TODAY)
    [price] = db.prices(flat.id)
    assert price.unit_price == D("300000.00")
    assert price.price_date == date(2026, 1, 1)


def test_delete_trade_protects_later_sales(service: PortfolioService, db: Database) -> None:
    stock = service.create_asset("Stock", "stock")
    buy = service.record_trade(stock.id, "buy", "2026-10-01", "10", "10", today=TODAY)
    sale = service.record_trade(stock.id, "sell", "2026-10-02", "5", "12", today=TODAY)
    with pytest.raises(ValidationError, match="later sale"):
        service.delete_trade(buy.id)
    service.delete_trade(sale.id)
    service.delete_trade(buy.id)
    assert db.trades(stock.id) == []


def test_update_asset(service: PortfolioService) -> None:
    stock = service.create_asset("Stock", "stock", "BRL", "ABCD3")
    updated = service.update_asset(stock.id, "Renamed", "stock", "BRL", "ABCD4", None, "note")
    assert (updated.name, updated.ticker, updated.notes) == ("Renamed", "ABCD4", "note")
    service.record_trade(stock.id, "buy", "2026-10-01", "1", "10", today=TODAY)
    with pytest.raises(ValidationError, match="currency cannot change"):
        service.update_asset(stock.id, "Renamed", "stock", "USD", "ABCD4", "manual", "")


def test_income_and_fx(service: PortfolioService, db: Database) -> None:
    flat = service.create_asset("Flat", "real_estate")
    service.record_income(flat.id, "2026-10-05", "rent", "2.200,00", "October", today=TODAY)
    assert db.income(flat.id)[0].amount == D("2200.00")
    with pytest.raises(ValidationError, match="unknown income"):
        service.record_income(flat.id, "2026-10-05", "gift", "1", today=TODAY)

    service.record_fx_rate("USD", "2026-10-30", "5,4321", today=TODAY)
    rate = db.latest_fx_rate(Currency.USD, TODAY)
    assert rate is not None and rate.rate == D("5.4321")
    with pytest.raises(ValidationError, match="base currency"):
        service.record_fx_rate("BRL", "2026-10-30", "1", today=TODAY)


def test_deleting_an_asset_removes_its_history(service: PortfolioService, db: Database) -> None:
    stock = service.create_asset("Stock", "stock")
    service.record_trade(stock.id, "buy", "2026-10-01", "1", "10", today=TODAY)
    service.record_income(stock.id, "2026-10-05", "dividend", "1", today=TODAY)
    service.delete_asset(stock.id)
    assert db.trades() == [] and db.income() == []
    with pytest.raises(NotFoundError):
        db.get_asset(stock.id)


def test_prices_upsert_by_day(db: Database) -> None:
    a = db.add_asset("A", AssetKind.STOCK, Currency.BRL)
    db.set_price(a.id, date(2026, 11, 1), D("10"), PriceSource.MANUAL)
    db.set_price(a.id, date(2026, 11, 1), D("11"), PriceSource.BRAPI)
    db.set_price(a.id, date(2026, 10, 1), D("9"), PriceSource.MANUAL)
    assert len(db.prices(a.id)) == 2
    assert db.latest_prices(TODAY)[a.id].unit_price == D("11")
    assert db.latest_prices(date(2026, 10, 15))[a.id].unit_price == D("9")


def test_schema_version_guard(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(RuntimeError, match="newer Wealthforge"):
        Database(path)


def test_sample_portfolio_loads_once(service: PortfolioService) -> None:
    assert load_sample(service, TODAY) == 6
    summary = service.summary(TODAY)
    assert summary.warnings == []
    assert {s.key for s in summary.by_class()} == {"financial", "real_estate", "business"}
    with pytest.raises(ValueError, match="already has assets"):
        load_sample(service, TODAY)
