"""Use cases: validate input, write to the database, build the summary.

The web layer and the CLI both go through this module, so validation rules
live in one place.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from .db import Database
from .models import (
    Asset,
    AssetKind,
    Currency,
    FxRate,
    Income,
    IncomeKind,
    Price,
    PriceSource,
    Trade,
    TradeSide,
    default_price_source,
)
from .money import parse_non_negative, parse_positive
from .portfolio import PositionError, Summary, build_position, summarize

MAX_NAME = 80
MAX_NOTES = 2000


class ValidationError(ValueError):
    """Input that cannot be saved. The message is safe to show to the user."""


def _clean_ticker(ticker: str | None) -> str | None:
    if ticker is None:
        return None
    cleaned = ticker.strip().upper()
    if not cleaned:
        return None
    if len(cleaned) > 20 or not all(c.isalnum() or c in ".-" for c in cleaned):
        raise ValidationError(f"ticker {ticker!r} looks invalid")
    return cleaned


def _parse_date(value: str | date, field: str, today: date) -> date:
    if isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(value.strip())
        except ValueError:
            raise ValidationError(f"{field}: use the format YYYY-MM-DD") from None
    if parsed > today:
        raise ValidationError(f"{field} cannot be in the future")
    return parsed


def _number(func, value: str | Decimal, field: str) -> Decimal:  # type: ignore[no-untyped-def]
    try:
        return func(value, field=field)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None


class PortfolioService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- assets --------------------------------------------------------------

    def _validated_asset_fields(
        self,
        name: str,
        kind: str | AssetKind,
        currency: str | Currency,
        ticker: str | None,
        price_source: str | PriceSource | None,
        notes: str,
    ) -> tuple[str, AssetKind, Currency, str | None, PriceSource, str]:
        name = " ".join(name.split())
        if not name:
            raise ValidationError("name is required")
        if len(name) > MAX_NAME:
            raise ValidationError(f"name cannot be longer than {MAX_NAME} characters")
        try:
            kind = AssetKind(kind)
            currency = Currency(currency)
            source = PriceSource(price_source) if price_source else None
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        ticker = _clean_ticker(ticker)
        if source is None:
            source = default_price_source(kind, currency, ticker)
        if source.is_automatic and not ticker:
            raise ValidationError(f"{source.label} needs a ticker")
        if source is PriceSource.BRAPI and currency is not Currency.BRL:
            raise ValidationError("brapi.dev quotes B3 assets, which are priced in BRL")
        if source is PriceSource.FINNHUB and currency is not Currency.USD:
            raise ValidationError("Finnhub quotes US assets, which are priced in USD")
        notes = notes.strip()
        if len(notes) > MAX_NOTES:
            raise ValidationError(f"notes cannot be longer than {MAX_NOTES} characters")
        return name, kind, currency, ticker, source, notes

    def create_asset(
        self,
        name: str,
        kind: str | AssetKind,
        currency: str | Currency = Currency.BRL,
        ticker: str | None = None,
        price_source: str | PriceSource | None = None,
        notes: str = "",
    ) -> Asset:
        fields = self._validated_asset_fields(name, kind, currency, ticker, price_source, notes)
        name, kind, currency, ticker, source, notes = fields
        return self.db.add_asset(name, kind, currency, ticker, source, notes)

    def update_asset(
        self,
        asset_id: int,
        name: str,
        kind: str | AssetKind,
        currency: str | Currency,
        ticker: str | None,
        price_source: str | PriceSource | None,
        notes: str,
    ) -> Asset:
        current = self.db.get_asset(asset_id)
        name, kind, currency, ticker, source, notes = self._validated_asset_fields(
            name, kind, currency, ticker, price_source, notes
        )
        if currency is not current.currency and self.db.trades(asset_id):
            raise ValidationError("the currency cannot change once the asset has trades")
        updated = replace(
            current,
            name=name,
            kind=kind,
            currency=currency,
            ticker=ticker,
            price_source=source,
            notes=notes,
        )
        return self.db.update_asset(updated)

    def delete_asset(self, asset_id: int) -> None:
        self.db.delete_asset(asset_id)

    # -- trades --------------------------------------------------------------

    def record_trade(
        self,
        asset_id: int,
        side: str | TradeSide,
        trade_date: str | date,
        quantity: str | Decimal,
        unit_price: str | Decimal,
        fees: str | Decimal = "",
        *,
        today: date,
    ) -> Trade:
        asset = self.db.get_asset(asset_id)
        try:
            side = TradeSide(side)
        except ValueError:
            raise ValidationError("side must be 'buy' or 'sell'") from None
        when = _parse_date(trade_date, "date", today)
        qty = _number(parse_positive, quantity, "quantity")
        price = _number(parse_positive, unit_price, "unit price")
        fee = _number(parse_non_negative, fees, "fees")
        if asset.kind.uses_ownership_fraction and qty > 1:
            raise ValidationError(
                "for real estate and businesses, quantity is the fraction you own "
                "(1 = 100%, 0.25 = 25%)"
            )

        # Make sure the history stays consistent with the new trade included.
        candidate = Trade(0, asset_id, side, when, qty, price, fee)
        try:
            position = build_position([*self.db.trades(asset_id), candidate])
        except PositionError as exc:
            raise ValidationError(str(exc)) from None
        if asset.kind.uses_ownership_fraction and position.quantity > 1:
            raise ValidationError("you cannot own more than 100% of an asset")

        trade = self.db.add_trade(asset_id, side, when, qty, price, fee)
        # For manually priced assets a purchase is also the best known value on
        # that day, unless a valuation was already recorded for it.
        if (
            asset.price_source is PriceSource.MANUAL
            and side is TradeSide.BUY
            and not any(p.price_date == when for p in self.db.prices(asset_id))
        ):
            self.db.set_price(asset_id, when, price, PriceSource.MANUAL)
        return trade

    def delete_trade(self, trade_id: int) -> Trade:
        trades = self.db.trades()
        target = next((t for t in trades if t.id == trade_id), None)
        if target is None:
            raise ValidationError(f"trade {trade_id} not found")
        remaining = [t for t in trades if t.asset_id == target.asset_id and t.id != trade_id]
        try:
            build_position(remaining)
        except PositionError:
            raise ValidationError(
                "deleting this purchase would leave a later sale without enough quantity"
            ) from None
        return self.db.delete_trade(trade_id)

    # -- prices --------------------------------------------------------------

    def record_price(
        self, asset_id: int, price_date: str | date, unit_price: str | Decimal, *, today: date
    ) -> Price:
        self.db.get_asset(asset_id)
        when = _parse_date(price_date, "date", today)
        price = _number(parse_positive, unit_price, "price")
        return self.db.set_price(asset_id, when, price, PriceSource.MANUAL)

    # -- income --------------------------------------------------------------

    def record_income(
        self,
        asset_id: int,
        income_date: str | date,
        kind: str | IncomeKind,
        amount: str | Decimal,
        note: str = "",
        *,
        today: date,
    ) -> Income:
        self.db.get_asset(asset_id)
        when = _parse_date(income_date, "date", today)
        try:
            income_kind = IncomeKind(kind)
        except ValueError:
            raise ValidationError(f"unknown income type {kind!r}") from None
        value = _number(parse_positive, amount, "amount")
        return self.db.add_income(asset_id, when, income_kind, value, note.strip()[:200])

    # -- exchange rates ------------------------------------------------------

    def record_fx_rate(
        self, currency: str | Currency, rate_date: str | date, rate: str | Decimal, *, today: date
    ) -> FxRate:
        try:
            code = Currency(currency)
        except ValueError:
            raise ValidationError(f"unknown currency {currency!r}") from None
        if code is Currency.BRL:
            raise ValidationError("BRL is the base currency")
        when = _parse_date(rate_date, "date", today)
        value = _number(parse_positive, rate, "rate")
        return self.db.set_fx_rate(code, when, value, "manual")

    # -- reporting -----------------------------------------------------------

    def summary(self, as_of: date) -> Summary:
        fx: dict[Currency, FxRate] = {}
        for currency in Currency:
            if currency is Currency.BRL:
                continue
            rate = self.db.latest_fx_rate(currency, as_of)
            if rate:
                fx[currency] = rate
        return summarize(
            assets=self.db.list_assets(),
            trades=self.db.trades(),
            latest_prices=self.db.latest_prices(as_of),
            income=self.db.income(),
            fx_rates=fx,
            as_of=as_of,
        )
