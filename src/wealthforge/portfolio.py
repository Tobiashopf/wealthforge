"""Portfolio arithmetic: positions, valuation and allocation.

The maths is deliberately plain:

* average cost (Brazilian "preço médio"): buys add to the cost basis; a sale
  removes ``quantity x average cost`` and books the difference as realized gain;
* market value = quantity x latest unit price;
* values in USD are converted to BRL with the latest stored exchange rate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .models import (
    BASE_CURRENCY,
    Asset,
    AssetClass,
    Currency,
    FxRate,
    Income,
    Price,
    Trade,
    TradeSide,
)

ZERO = Decimal(0)
STALE_AFTER = timedelta(days=7)
STALE_AFTER_MANUAL = timedelta(days=365)


class PositionError(ValueError):
    pass


@dataclass
class Position:
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    realized_gain: Decimal = ZERO

    @property
    def average_cost(self) -> Decimal | None:
        return self.cost_basis / self.quantity if self.quantity else None

    @property
    def is_open(self) -> bool:
        return self.quantity > 0


def build_position(trades: Iterable[Trade]) -> Position:
    """Replay trades in date order. Raises PositionError on an oversell."""
    pos = Position()
    for trade in sorted(trades, key=lambda t: (t.trade_date, t.id)):
        if trade.side is TradeSide.BUY:
            pos.quantity += trade.quantity
            pos.cost_basis += trade.quantity * trade.unit_price + trade.fees
        else:
            if trade.quantity > pos.quantity:
                raise PositionError(
                    f"sale on {trade.trade_date} of {trade.quantity} exceeds the "
                    f"{pos.quantity} held at that date"
                )
            average = pos.cost_basis / pos.quantity
            removed_cost = trade.quantity * average
            proceeds = trade.quantity * trade.unit_price - trade.fees
            pos.realized_gain += proceeds - removed_cost
            pos.quantity -= trade.quantity
            pos.cost_basis -= removed_cost
            if pos.quantity == 0:
                pos.cost_basis = ZERO
    return pos


@dataclass
class Holding:
    asset: Asset
    position: Position
    price: Price | None
    fx_rate: Decimal | None  # BRL per unit of the asset's currency; 1 for BRL
    income_total: Decimal = ZERO
    income_12m: Decimal = ZERO
    as_of: date | None = None

    @property
    def has_price(self) -> bool:
        return self.price is not None

    @property
    def unit_price(self) -> Decimal | None:
        return self.price.unit_price if self.price else None

    @property
    def market_value(self) -> Decimal:
        """Value in the asset's own currency. Without a price, falls back to cost."""
        if self.price is None:
            return self.position.cost_basis
        return self.position.quantity * self.price.unit_price

    @property
    def unrealized_gain(self) -> Decimal | None:
        if self.price is None or not self.position.is_open:
            return None
        return self.market_value - self.position.cost_basis

    @property
    def unrealized_pct(self) -> Decimal | None:
        gain = self.unrealized_gain
        if gain is None or not self.position.cost_basis:
            return None
        return gain / self.position.cost_basis

    def to_base(self, amount: Decimal) -> Decimal | None:
        return amount * self.fx_rate if self.fx_rate is not None else None

    @property
    def market_value_base(self) -> Decimal | None:
        return self.to_base(self.market_value)

    @property
    def cost_basis_base(self) -> Decimal | None:
        return self.to_base(self.position.cost_basis)

    @property
    def is_stale(self) -> bool:
        if self.price is None or self.as_of is None:
            return False
        limit = STALE_AFTER if self.asset.price_source.is_automatic else STALE_AFTER_MANUAL
        return self.as_of - self.price.price_date > limit


@dataclass
class Slice:
    key: str
    label: str
    value: Decimal
    share: Decimal


@dataclass
class Summary:
    as_of: date
    holdings: list[Holding]
    closed: list[Holding]
    fx_rates: dict[Currency, FxRate]
    warnings: list[str] = field(default_factory=list)

    def _sum(self, values: Iterable[Decimal | None]) -> Decimal:
        return sum((v for v in values if v is not None), ZERO)

    @property
    def total_value(self) -> Decimal:
        return self._sum(h.market_value_base for h in self.holdings)

    @property
    def total_cost(self) -> Decimal:
        return self._sum(h.cost_basis_base for h in self.holdings)

    @property
    def unrealized_gain(self) -> Decimal:
        return self._sum(
            h.to_base(h.unrealized_gain) for h in self.holdings if h.unrealized_gain is not None
        )

    @property
    def income_12m(self) -> Decimal:
        return self._sum(h.to_base(h.income_12m) for h in [*self.holdings, *self.closed])

    @property
    def realized_gain(self) -> Decimal:
        return self._sum(
            h.to_base(h.position.realized_gain) for h in [*self.holdings, *self.closed]
        )

    def weight(self, holding: Holding) -> Decimal | None:
        value = holding.market_value_base
        if value is None or not self.total_value:
            return None
        return value / self.total_value

    def _slices(self, groups: dict[str, tuple[str, Decimal]]) -> list[Slice]:
        total = self.total_value
        slices = [
            Slice(key, label, value, value / total if total else ZERO)
            for key, (label, value) in groups.items()
            if value
        ]
        return sorted(slices, key=lambda s: s.value, reverse=True)

    def by_class(self) -> list[Slice]:
        groups: dict[str, tuple[str, Decimal]] = {}
        for h in self.holdings:
            value = h.market_value_base
            if value is None:
                continue
            cls: AssetClass = h.asset.asset_class
            label, current = groups.get(cls.value, (cls.label, ZERO))
            groups[cls.value] = (label, current + value)
        return self._slices(groups)

    def by_kind(self) -> list[Slice]:
        groups: dict[str, tuple[str, Decimal]] = {}
        for h in self.holdings:
            value = h.market_value_base
            if value is None:
                continue
            label, current = groups.get(h.asset.kind.value, (h.asset.kind.label, ZERO))
            groups[h.asset.kind.value] = (label, current + value)
        return self._slices(groups)

    def by_currency(self) -> list[Slice]:
        groups: dict[str, tuple[str, Decimal]] = {}
        for h in self.holdings:
            value = h.market_value_base
            if value is None:
                continue
            code = h.asset.currency.value
            label, current = groups.get(code, (code, ZERO))
            groups[code] = (label, current + value)
        return self._slices(groups)


def summarize(
    assets: Iterable[Asset],
    trades: Iterable[Trade],
    latest_prices: dict[int, Price],
    income: Iterable[Income],
    fx_rates: dict[Currency, FxRate],
    as_of: date,
) -> Summary:
    trades_by_asset: dict[int, list[Trade]] = {}
    for trade in trades:
        trades_by_asset.setdefault(trade.asset_id, []).append(trade)

    income_total: dict[int, Decimal] = {}
    income_12m: dict[int, Decimal] = {}
    year_ago = as_of - timedelta(days=365)
    for item in income:
        if item.income_date > as_of:
            continue
        income_total[item.asset_id] = income_total.get(item.asset_id, ZERO) + item.amount
        if item.income_date > year_ago:
            income_12m[item.asset_id] = income_12m.get(item.asset_id, ZERO) + item.amount

    summary = Summary(as_of=as_of, holdings=[], closed=[], fx_rates=dict(fx_rates))
    missing_fx: set[Currency] = set()

    for asset in assets:
        try:
            position = build_position(trades_by_asset.get(asset.id, []))
        except PositionError as exc:
            summary.warnings.append(f"{asset.name}: {exc}")
            continue

        if asset.currency is BASE_CURRENCY:
            rate: Decimal | None = Decimal(1)
        elif asset.currency in fx_rates:
            rate = fx_rates[asset.currency].rate
        else:
            rate = None
            missing_fx.add(asset.currency)

        holding = Holding(
            asset=asset,
            position=position,
            price=latest_prices.get(asset.id),
            fx_rate=rate,
            income_total=income_total.get(asset.id, ZERO),
            income_12m=income_12m.get(asset.id, ZERO),
            as_of=as_of,
        )
        if position.is_open:
            summary.holdings.append(holding)
            if holding.price is None:
                summary.warnings.append(
                    f"{asset.name} has no price yet; its cost is used as its value."
                )
            elif holding.is_stale:
                summary.warnings.append(
                    f"{asset.name}: last price is from {holding.price.price_date:%Y-%m-%d}."
                )
        elif trades_by_asset.get(asset.id):
            summary.closed.append(holding)

    for currency in sorted(missing_fx, key=lambda c: c.value):
        summary.warnings.append(
            f"No {currency.value}/BRL exchange rate yet: {currency.value} assets are left "
            "out of the totals. Refresh quotes or add a rate."
        )

    summary.holdings.sort(key=lambda h: h.market_value_base or ZERO, reverse=True)
    return summary
