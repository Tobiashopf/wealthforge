"""Quote providers are tested against recorded-style responses; no network is used."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from wealthforge.config import Settings
from wealthforge.db import Database
from wealthforge.models import Currency
from wealthforge.quotes.base import QuoteError
from wealthforge.quotes.brapi import BrapiProvider
from wealthforge.quotes.finnhub import FinnhubProvider
from wealthforge.quotes.ptax import fetch_usd_brl, ptax_url
from wealthforge.quotes.refresh import refresh_quotes
from wealthforge.service import PortfolioService

from .conftest import TODAY

Handler = Callable[[httpx.Request], httpx.Response]


def client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def brapi_body(symbol: str, price: float, currency: str = "BRL") -> dict:
    return {
        "results": [
            {
                "requestedSymbol": symbol,
                "symbol": symbol,
                "changed": False,
                "data": {
                    "shortName": f"{symbol} SA",
                    "currency": currency,
                    "regularMarketPrice": price,
                    "regularMarketTime": "2026-10-30T20:07:00.000Z",
                },
            }
        ],
        "requestedAt": "2026-11-02T13:00:00.000Z",
        "took": 120,
    }


def ptax_body(*rows: tuple[str, float]) -> dict:
    return {"value": [{"cotacaoVenda": rate, "dataHoraCotacao": stamp} for stamp, rate in rows]}


# -- brapi ---------------------------------------------------------------------


def test_brapi_parses_v2_response_and_sends_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=brapi_body("PETR4", 38.47))

    quote = BrapiProvider(client(handler), token="secret").fetch("PETR4", TODAY)
    assert quote.price == D("38.47")  # exact decimal, never a float
    assert quote.quote_date == date(2026, 10, 30)
    assert seen[0].url.params["symbols"] == "PETR4"
    assert seen[0].headers["Authorization"] == "Bearer secret"


def test_brapi_accepts_flat_v1_layout() -> None:
    body = {"results": [{"symbol": "VALE3", "currency": "BRL", "regularMarketPrice": 61.2}]}
    quote = BrapiProvider(client(lambda r: httpx.Response(200, json=body))).fetch("VALE3", TODAY)
    assert quote.price == D("61.2")
    assert quote.quote_date == TODAY  # no timestamp -> today


def test_brapi_without_token_explains_test_tickers() -> None:
    provider = BrapiProvider(client(lambda r: httpx.Response(401, json={"error": True})))
    with pytest.raises(QuoteError, match="PETR4, MGLU3, VALE3 and ITUB4"):
        provider.fetch("HGLG11", TODAY)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"results": []}),
        httpx.Response(200, json={"results": [{"symbol": "X", "data": {"currency": "BRL"}}]}),
        httpx.Response(200, text="<html>oops</html>"),
        httpx.Response(429),
        httpx.Response(500),
        httpx.Response(404),
    ],
)
def test_brapi_bad_responses_become_quote_errors(response: httpx.Response) -> None:
    with pytest.raises(QuoteError):
        BrapiProvider(client(lambda r: response), token="t").fetch("XPTO3", TODAY)


def test_network_errors_become_quote_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(QuoteError, match="could not be reached"):
        BrapiProvider(client(handler)).fetch("PETR4", TODAY)


# -- Finnhub -------------------------------------------------------------------


def test_finnhub_parses_quote() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = (
            '{"c": 561.3, "d": 1.2, "dp": 0.21, "h": 562, "l": 558, '
            '"o": 559, "pc": 560.1, "t": 1793736000}'
        )
        return httpx.Response(200, text=body)

    quote = FinnhubProvider(client(handler), token="k").fetch("VOO", TODAY)
    assert quote.price == D("561.3")
    assert quote.currency == "USD"
    assert seen[0].headers["X-Finnhub-Token"] == "k"
    assert "token" not in seen[0].url.params  # the key never goes into the URL


def test_finnhub_requires_token_and_rejects_unknown_symbols() -> None:
    with pytest.raises(QuoteError, match="FINNHUB_TOKEN"):
        FinnhubProvider(client(lambda r: httpx.Response(200))).fetch("VOO", TODAY)
    unknown = {"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}
    with pytest.raises(QuoteError, match="no price"):
        provider = FinnhubProvider(client(lambda r: httpx.Response(200, json=unknown)), "k")
        provider.fetch("ZZZZ", TODAY)


# -- PTAX ----------------------------------------------------------------------


def test_ptax_url_uses_bcb_date_format() -> None:
    url = ptax_url(date(2026, 10, 23), date(2026, 11, 2))
    assert "@dataInicial='10-23-2026'" in url
    assert "@dataFinalCotacao='11-02-2026'" in url
    assert "$format=json" in url


def test_ptax_picks_latest_bulletin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "CotacaoDolarPeriodo" in unquote(str(request.url))
        return httpx.Response(
            200,
            json=ptax_body(
                ("2026-10-29 13:05:22.811", 5.3911), ("2026-10-30 13:04:10.120", 5.4127)
            ),
        )

    assert fetch_usd_brl(client(handler), TODAY) == (date(2026, 10, 30), D("5.4127"))


def test_ptax_empty_period() -> None:
    with pytest.raises(QuoteError, match="no rate"):
        fetch_usd_brl(client(lambda r: httpx.Response(200, json={"value": []})), TODAY)


# -- refresh ---------------------------------------------------------------------


def fake_internet(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "brapi.dev":
        symbol = request.url.params["symbols"]
        if symbol == "FAIL3":
            return httpx.Response(500)
        return httpx.Response(200, json=brapi_body(symbol, 10.5))
    if host == "finnhub.io":
        return httpx.Response(200, text=json.dumps({"c": 100.25, "t": 1793736000}))
    if host == "olinda.bcb.gov.br":
        return httpx.Response(200, json=ptax_body(("2026-10-30 13:04:10.120", 5.4)))
    return httpx.Response(404)


def test_refresh_updates_open_automatic_positions(tmp_path: Path) -> None:
    with Database(tmp_path / "r.db") as db:
        service = PortfolioService(db)
        petr = service.create_asset("Petrobras", "stock", "BRL", "PETR4")
        voo = service.create_asset("S&P 500", "etf", "USD", "VOO")
        broken = service.create_asset("Broken", "stock", "BRL", "FAIL3")
        closed = service.create_asset("Sold", "stock", "BRL", "SOLD3")
        manual = service.create_asset("Flat", "real_estate", "BRL")
        for a in (petr, voo, broken, closed, manual):
            service.record_trade(a.id, "buy", "2026-01-05", "1", "9", today=TODAY)
        service.record_trade(closed.id, "sell", "2026-02-05", "1", "9", today=TODAY)

        settings = Settings(tmp_path / "r.db", brapi_token=None, finnhub_token="k")
        report = refresh_quotes(db, client(fake_internet), settings, TODAY)

        assert report.updated == ["PETR4", "VOO"]
        assert report.failed and report.failed[0].startswith("FAIL3:")
        assert not report.ok
        assert db.prices(petr.id)[0].unit_price == D("10.5")
        assert db.prices(closed.id) == []  # closed positions are not refreshed
        rate = db.latest_fx_rate(Currency.USD, TODAY)
        assert rate is not None and rate.rate == D("5.4") and rate.source == "ptax"
        assert any("USD/BRL 5.4" in line for line in report.lines())


def test_refresh_rejects_currency_mismatch(tmp_path: Path) -> None:
    with Database(tmp_path / "m.db") as db:
        service = PortfolioService(db)
        a = service.create_asset("Odd", "stock", "BRL", "ODD3")
        service.record_trade(a.id, "buy", "2026-01-05", "1", "9", today=TODAY)
        handler = lambda r: httpx.Response(200, json=brapi_body("ODD3", 3, currency="USD"))  # noqa: E731
        report = refresh_quotes(db, client(handler), Settings(tmp_path, None, None), TODAY)
        assert report.updated == []
        assert "quoted in USD" in report.failed[0]


def test_refresh_with_nothing_to_do(tmp_path: Path) -> None:
    with Database(tmp_path / "e.db") as db:
        report = refresh_quotes(db, client(fake_internet), Settings(tmp_path, None, None), TODAY)
    assert report.ok
    assert "Nothing to refresh" in report.lines()[0]
