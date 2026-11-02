from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from wealthforge.models import (
    Asset,
    AssetClass,
    AssetKind,
    Currency,
    FxRate,
    Income,
    IncomeKind,
    Price,
    PriceSource,
    Trade,
    TradeSide,
)
from wealthforge.portfolio import PositionError, build_position, summarize

TODAY = date(2026, 11, 2)
BUY, SELL = TradeSide.BUY, TradeSide.SELL


def trade(
    id_: int, side: TradeSide, day: str, qty: str, price: str, fees: str = "0", asset_id: int = 1
) -> Trade:
    return Trade(id_, asset_id, side, date.fromisoformat(day), D(qty), D(price), D(fees))


def asset(
    id_: int,
    kind: AssetKind,
    currency: Currency = Currency.BRL,
    source: PriceSource = PriceSource.MANUAL,
) -> Asset:
    return Asset(id_, f"asset {id_}", kind, currency, None, source)


def price(asset_id: int, day: str, value: str, source: PriceSource = PriceSource.MANUAL) -> Price:
    return Price(asset_id, asset_id, date.fromisoformat(day), D(value), source)


def test_average_cost_includes_fees() -> None:
    pos = build_position(
        [
            trade(1, BUY, "2026-01-10", "100", "10.00", "5"),
            trade(2, BUY, "2026-02-10", "100", "12.00", "5"),
        ]
    )
    assert pos.quantity == 200
    assert pos.cost_basis == D("2210")
    assert pos.average_cost == D("11.05")


def test_sale_keeps_average_cost_and_books_realized_gain() -> None:
    pos = build_position(
        [
            trade(1, BUY, "2026-01-10", "100", "10"),
            trade(2, BUY, "2026-02-10", "100", "12"),
            trade(3, SELL, "2026-03-10", "50", "15", "2"),
        ]
    )
    assert pos.quantity == 150
    assert pos.average_cost == D("11")
    # 50 x 15 - 2 fees - 50 x 11 average cost
    assert pos.realized_gain == D("198")


def test_trades_are_replayed_in_date_order() -> None:
    pos = build_position(
        [
            trade(2, SELL, "2026-03-01", "10", "20"),
            trade(1, BUY, "2026-01-01", "10", "10"),
        ]
    )
    assert pos.quantity == 0
    assert pos.cost_basis == 0
    assert pos.realized_gain == D("100")
    assert not pos.is_open


def test_oversell_is_an_error() -> None:
    with pytest.raises(PositionError, match="exceeds"):
        build_position(
            [
                trade(1, BUY, "2026-01-01", "10", "10"),
                trade(2, SELL, "2026-01-02", "11", "10"),
            ]
        )


def test_summary_values_every_asset_class_in_brl() -> None:
    assets = [
        asset(1, AssetKind.STOCK, source=PriceSource.BRAPI),
        asset(2, AssetKind.ETF, Currency.USD, PriceSource.FINNHUB),
        asset(3, AssetKind.REAL_ESTATE),
        asset(4, AssetKind.BUSINESS),
    ]
    trades = [
        trade(1, BUY, "2026-01-01", "100", "10", asset_id=1),
        trade(2, BUY, "2026-01-01", "2", "100", asset_id=2),
        trade(3, BUY, "2025-01-01", "0.5", "400000", asset_id=3),  # half of a property
        trade(4, BUY, "2025-01-01", "0.25", "200000", asset_id=4),  # 25% of a company
    ]
    prices = {
        1: price(1, "2026-11-01", "12", PriceSource.BRAPI),
        2: price(2, "2026-11-01", "110", PriceSource.FINNHUB),
        3: price(3, "2026-06-01", "500000"),
        4: price(4, "2026-06-01", "240000"),
    }
    fx = {Currency.USD: FxRate(1, Currency.USD, date(2026, 10, 30), D("5.5"), "ptax")}
    income = [
        Income(1, 3, date(2026, 10, 5), IncomeKind.RENT, D("1500")),
        Income(2, 3, date(2025, 6, 5), IncomeKind.RENT, D("1400")),  # older than 12 months
        Income(3, 2, date(2026, 9, 1), IncomeKind.DIVIDEND, D("3")),
    ]

    summary = summarize(assets, trades, prices, income, fx, TODAY)

    values = {h.asset.id: h.market_value_base for h in summary.holdings}
    assert values == {1: D("1200"), 2: D("1210.0"), 3: D("250000"), 4: D("60000")}
    assert summary.total_value == D("312410.0")
    assert summary.total_cost == D("1000") + D("1100.0") + D("200000") + D("50000")
    assert summary.unrealized_gain == summary.total_value - summary.total_cost
    assert summary.income_12m == D("1500") + D("3") * D("5.5")
    assert summary.warnings == []

    by_class = {s.key: s.share for s in summary.by_class()}
    assert by_class[AssetClass.REAL_ESTATE.value] == D("250000") / D("312410.0")
    assert sum(s.share for s in summary.by_class()) == pytest.approx(1)
    assert [s.key for s in summary.by_currency()] == ["BRL", "USD"]
    assert summary.holdings[0].asset.id == 3  # sorted by value


def test_missing_fx_rate_excludes_asset_and_warns() -> None:
    assets = [asset(1, AssetKind.STOCK), asset(2, AssetKind.ETF, Currency.USD)]
    trades = [
        trade(1, BUY, "2026-01-01", "10", "10", asset_id=1),
        trade(2, BUY, "2026-01-01", "1", "100", asset_id=2),
    ]
    summary = summarize(assets, trades, {}, [], {}, TODAY)
    assert summary.total_value == D("100")
    assert any("USD/BRL" in w for w in summary.warnings)


def test_unpriced_asset_uses_cost_and_warns() -> None:
    summary = summarize(
        [asset(1, AssetKind.FUND)], [trade(1, BUY, "2026-01-01", "3", "50")], {}, [], {}, TODAY
    )
    [holding] = summary.holdings
    assert holding.market_value == D("150")
    assert holding.unrealized_gain is None
    assert any("no price" in w for w in summary.warnings)


def test_stale_automatic_price_warns() -> None:
    summary = summarize(
        [asset(1, AssetKind.STOCK, source=PriceSource.BRAPI)],
        [trade(1, BUY, "2026-01-01", "1", "10")],
        {1: price(1, "2026-10-01", "11", PriceSource.BRAPI)},
        [],
        {},
        TODAY,
    )
    assert summary.holdings[0].is_stale
    assert any("last price is from 2026-10-01" in w for w in summary.warnings)


def test_closed_positions_are_listed_separately() -> None:
    summary = summarize(
        [asset(1, AssetKind.STOCK), asset(2, AssetKind.STOCK)],
        [trade(1, BUY, "2026-01-01", "10", "10"), trade(2, SELL, "2026-02-01", "10", "13")],
        {},
        [],
        {},
        TODAY,
    )
    assert summary.holdings == []
    assert [h.asset.id for h in summary.closed] == [1]
    assert summary.realized_gain == D("30")


def test_inconsistent_history_is_reported_not_raised() -> None:
    summary = summarize(
        [asset(1, AssetKind.STOCK)], [trade(1, SELL, "2026-01-01", "1", "10")], {}, [], {}, TODAY
    )
    assert summary.holdings == []
    assert "exceeds" in summary.warnings[0]
