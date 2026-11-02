"""Made-up demo data. Every name, quantity and value here is fictional."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

from .models import AssetKind, Currency, IncomeKind, PriceSource
from .service import PortfolioService


def load_sample(service: PortfolioService, today: date) -> int:
    """Fill an empty database with a small fictional portfolio. Returns the
    number of assets created."""
    if service.db.list_assets():
        raise ValueError("the database already has assets; use an empty database for the demo")

    def ago(days: int) -> date:
        return today - timedelta(days=days)

    db = service.db
    record = service.record_trade

    petr = service.create_asset("Petrobras PN", AssetKind.STOCK, Currency.BRL, "PETR4")
    record(petr.id, "buy", ago(600), "100", "30.50", "4.90", today=today)
    record(petr.id, "buy", ago(400), "50", "36.20", "4.90", today=today)
    record(petr.id, "sell", ago(200), "30", "39.00", "4.90", today=today)
    db.set_price(petr.id, ago(1), D("38.75"), PriceSource.BRAPI)
    service.record_income(petr.id, ago(150), "dividend", "112.40", today=today)
    service.record_income(petr.id, ago(60), "jcp", "58.10", today=today)

    itub = service.create_asset("Itau Unibanco PN", AssetKind.STOCK, Currency.BRL, "ITUB4")
    record(itub.id, "buy", ago(500), "200", "28.10", "4.90", today=today)
    db.set_price(itub.id, ago(1), D("34.20"), PriceSource.BRAPI)
    service.record_income(itub.id, ago(30), "dividend", "41.60", today=today)

    bond = service.create_asset(
        "Inflation-linked government bond 2035",
        AssetKind.FIXED_INCOME,
        Currency.BRL,
        notes="Sample entry: update its value from your broker statement.",
    )
    record(bond.id, "buy", ago(700), "3.2", "3100", today=today)
    service.record_price(bond.id, ago(20), "3480", today=today)

    etf = service.create_asset("Vanguard S&P 500 ETF", AssetKind.ETF, Currency.USD, "VOO")
    record(etf.id, "buy", ago(300), "5", "480.00", "1.00", today=today)
    db.set_price(etf.id, ago(1), D("561.30"), PriceSource.FINNHUB)
    service.record_fx_rate(Currency.USD, ago(1), "5.42", today=today)

    flat = service.create_asset(
        "Two-bedroom apartment (sample)",
        AssetKind.REAL_ESTATE,
        Currency.BRL,
        notes="Rented out. Value updated from a broker estimate once a year.",
    )
    record(flat.id, "buy", ago(1500), "1", "450000", "18000", today=today)
    service.record_price(flat.id, ago(90), "520000", today=today)
    for month in range(6):
        service.record_income(flat.id, ago(15 + 30 * month), "rent", "2200", today=today)

    cafe = service.create_asset(
        "Neighbourhood coffee shop (25% stake, sample)",
        AssetKind.BUSINESS,
        Currency.BRL,
        notes="Quantity is the ownership fraction; price is the value of 100% of the business.",
    )
    record(cafe.id, "buy", ago(900), "0.25", "400000", today=today)
    service.record_price(cafe.id, ago(120), "520000", today=today)
    service.record_income(cafe.id, ago(100), IncomeKind.DISTRIBUTION, "6000", today=today)
    service.record_income(cafe.id, ago(10), IncomeKind.DISTRIBUTION, "7500", today=today)

    return len(db.list_assets())
