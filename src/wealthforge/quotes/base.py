from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(10.0)
USER_AGENT = "wealthforge (+https://github.com/Tobiashopf/wealthforge)"


class QuoteError(Exception):
    """A provider could not return a usable quote. The message is user-facing."""


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: Decimal
    currency: str
    quote_date: date


def get_json(
    client: httpx.Client,
    url: str,
    *,
    provider: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET a JSON document, parsing numbers as Decimal and translating failures."""
    try:
        response = client.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise QuoteError(f"{provider} could not be reached ({exc.__class__.__name__})") from exc

    if response.status_code in (401, 403):
        raise QuoteError(f"{provider} refused the request (HTTP {response.status_code})")
    if response.status_code == 429:
        raise QuoteError(f"{provider} rate limit reached; try again in a minute")
    if response.status_code == 404:
        raise QuoteError(f"{provider} does not know this symbol")
    if response.status_code >= 400:
        raise QuoteError(f"{provider} returned HTTP {response.status_code}")
    try:
        return json.loads(response.text, parse_float=Decimal, parse_int=Decimal)
    except json.JSONDecodeError as exc:
        raise QuoteError(f"{provider} returned an invalid response") from exc


def parse_timestamp(value: Any, fallback: date) -> date:
    """Accept ISO-8601 strings or Unix seconds; fall back if missing."""
    if value in (None, "", 0):
        return fallback
    try:
        if isinstance(value, (int, float, Decimal)):
            return datetime.fromtimestamp(float(value)).date()
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).date()
    except (ValueError, OSError, OverflowError):
        return fallback
