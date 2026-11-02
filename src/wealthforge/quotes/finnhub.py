"""Quotes for US-listed stocks and ETFs from Finnhub (free API key required).

Get a free key at https://finnhub.io and put it in FINNHUB_TOKEN.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx

from .base import Quote, QuoteError, get_json, parse_timestamp

URL = "https://finnhub.io/api/v1/quote"
NAME = "Finnhub"


class FinnhubProvider:
    def __init__(self, client: httpx.Client, token: str | None = None) -> None:
        self.client = client
        self.token = token

    def fetch(self, symbol: str, today: date) -> Quote:
        if not self.token:
            raise QuoteError("Finnhub needs a free API key in FINNHUB_TOKEN")
        payload = get_json(
            self.client,
            URL,
            provider=NAME,
            params={"symbol": symbol},
            headers={"X-Finnhub-Token": self.token},
        )
        if not isinstance(payload, dict):
            raise QuoteError(f"{NAME} returned an invalid response for {symbol}")
        # "c" is the current price; Finnhub answers 0 for unknown symbols.
        price = payload.get("c")
        if not isinstance(price, Decimal) or price <= 0:
            raise QuoteError(f"{NAME} has no price for {symbol}")
        return Quote(
            symbol=symbol,
            price=price,
            currency="USD",
            quote_date=parse_timestamp(payload.get("t"), today),
        )
