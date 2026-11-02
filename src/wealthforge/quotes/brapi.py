"""Quotes for B3-listed assets (stocks, FIIs, ETFs, BDRs) from brapi.dev.

Without a token, brapi.dev only serves its test tickers (PETR4, MGLU3, VALE3,
ITUB4). A free token from https://brapi.dev unlocks the rest; put it in the
BRAPI_TOKEN environment variable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx

from .base import Quote, QuoteError, get_json, parse_timestamp

URL = "https://brapi.dev/api/v2/stocks/quote"
NAME = "brapi.dev"


class BrapiProvider:
    def __init__(self, client: httpx.Client, token: str | None = None) -> None:
        self.client = client
        self.token = token

    def fetch(self, symbol: str, today: date) -> Quote:
        # One symbol per request keeps the free plan happy.
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            payload = get_json(
                self.client, URL, provider=NAME, params={"symbols": symbol}, headers=headers
            )
        except QuoteError as exc:
            if not self.token and "refused" in str(exc):
                raise QuoteError(
                    f"{exc}. Without BRAPI_TOKEN only the test tickers PETR4, MGLU3, "
                    "VALE3 and ITUB4 are available."
                ) from exc
            raise

        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            raise QuoteError(f"{NAME} returned no data for {symbol}")
        item = results[0]
        # v2 nests market fields under "data"; older responses had them at the top level.
        data = item.get("data") or item
        price = data.get("regularMarketPrice")
        if not isinstance(price, Decimal) or price <= 0:
            raise QuoteError(f"{NAME} has no price for {symbol}")
        return Quote(
            symbol=str(item.get("symbol") or symbol),
            price=price,
            currency=str(data.get("currency") or "BRL"),
            quote_date=parse_timestamp(data.get("regularMarketTime"), today),
        )
