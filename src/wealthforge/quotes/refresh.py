"""Refresh every automatic price and the USD/BRL rate in one go."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import httpx

from ..config import Settings
from ..db import Database
from ..models import Currency, PriceSource
from ..portfolio import PositionError, build_position
from .base import Quote, QuoteError
from .brapi import BrapiProvider
from .finnhub import FinnhubProvider
from .ptax import NAME as PTAX_NAME
from .ptax import fetch_usd_brl


class Provider(Protocol):
    def fetch(self, symbol: str, today: date) -> Quote: ...


@dataclass
class RefreshReport:
    updated: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    fx: str | None = None

    @property
    def ok(self) -> bool:
        return not self.failed

    def lines(self) -> list[str]:
        out = []
        if self.updated:
            out.append("Updated: " + ", ".join(self.updated))
        if self.fx:
            out.append(self.fx)
        out.extend(f"Failed: {msg}" for msg in self.failed)
        if not out:
            out.append("Nothing to refresh: no open positions use an automatic price source.")
        return out


def refresh_quotes(
    db: Database,
    client: httpx.Client,
    settings: Settings,
    today: date,
    providers: dict[PriceSource, Provider] | None = None,
) -> RefreshReport:
    providers = providers or {
        PriceSource.BRAPI: BrapiProvider(client, settings.brapi_token),
        PriceSource.FINNHUB: FinnhubProvider(client, settings.finnhub_token),
    }
    report = RefreshReport()
    needs_usd = False

    for asset in db.list_assets():
        try:
            is_open = build_position(db.trades(asset.id)).is_open
        except PositionError:
            is_open = False
        if not is_open:
            continue
        if asset.currency is Currency.USD:
            needs_usd = True
        if not asset.price_source.is_automatic or not asset.ticker:
            continue
        provider = providers.get(asset.price_source)
        if provider is None:
            report.failed.append(f"{asset.name}: no provider for {asset.price_source.label}")
            continue
        try:
            quote = provider.fetch(asset.ticker, today)
        except QuoteError as exc:
            report.failed.append(f"{asset.ticker}: {exc}")
            continue
        if quote.currency.upper() != asset.currency.value:
            report.failed.append(
                f"{asset.ticker}: quoted in {quote.currency}, but the asset is in "
                f"{asset.currency.value}"
            )
            continue
        db.set_price(asset.id, min(quote.quote_date, today), quote.price, asset.price_source)
        report.updated.append(asset.ticker)

    if needs_usd:
        try:
            bulletin, rate = fetch_usd_brl(client, today)
        except QuoteError as exc:
            report.failed.append(f"USD/BRL: {exc}")
        else:
            db.set_fx_rate(Currency.USD, bulletin, rate, "ptax")
            report.fx = f"USD/BRL {rate} ({PTAX_NAME}, {bulletin:%Y-%m-%d})"
    return report
