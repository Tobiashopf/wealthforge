"""Local web interface (FastAPI + server-rendered Jinja2 templates)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..config import Settings
from ..db import Database, NotFoundError
from ..models import (
    BASE_CURRENCY,
    AssetClass,
    AssetKind,
    Currency,
    IncomeKind,
    PriceSource,
    TradeSide,
)
from ..money import format_money, format_ownership, format_percent, format_quantity
from ..portfolio import build_position
from ..quotes import refresh_quotes
from ..service import PortfolioService, ValidationError

HERE = Path(__file__).parent


def _redirect(url: str, **params: str) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v})
    return RedirectResponse(f"{url}?{query}" if query else url, status_code=303)


def _signed(value: Decimal | None, currency: Currency | str) -> str:
    if value is None:
        return "-"
    text = format_money(value, currency)
    return f"+{text}" if value > 0 else text


def create_app(
    settings: Settings,
    *,
    today: Callable[[], date] = date.today,
    http_client: Callable[[], httpx.Client] = httpx.Client,
) -> FastAPI:
    db = Database(settings.db_path)
    service = PortfolioService(db)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        db.close()

    app = FastAPI(
        title="Wealthforge", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.state.db = db

    templates = Jinja2Templates(directory=HERE / "templates")
    env = templates.env
    env.filters["money"] = format_money
    env.filters["signed"] = _signed
    env.filters["qty"] = format_quantity
    env.filters["pct"] = format_percent
    env.filters["ownership"] = format_ownership
    env.globals.update(
        version=__version__,
        base=BASE_CURRENCY,
        AssetKind=AssetKind,
        AssetClass=AssetClass,
        Currency=Currency,
        PriceSource=PriceSource,
        IncomeKind=IncomeKind,
        TradeSide=TradeSide,
    )

    def render(
        request: Request, name: str, status_code: int = 200, **context: object
    ) -> HTMLResponse:
        context.setdefault("msg", request.query_params.get("msg"))
        context.setdefault("error", request.query_params.get("error"))
        context.setdefault("today", today())
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError) -> HTMLResponse:
        return render(request, "not_found.html", status_code=404, message=str(exc))

    # -- dashboard -----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        summary = service.summary(today())
        return render(
            request,
            "dashboard.html",
            summary=summary,
            has_assets=bool(db.list_assets()),
            usd_rates=db.fx_rates(Currency.USD, limit=5),
        )

    @app.post("/refresh")
    def refresh(request: Request) -> Response:
        with http_client() as client:
            report = refresh_quotes(db, client, settings, today())
        params = (
            {"msg": " | ".join(report.lines())}
            if report.ok
            else {"error": " | ".join(report.lines())}
        )
        return _redirect("/", **params)

    @app.post("/fx")
    def add_fx(
        currency: Annotated[str, Form()],
        rate_date: Annotated[str, Form()],
        rate: Annotated[str, Form()],
    ) -> Response:
        try:
            saved = service.record_fx_rate(currency, rate_date, rate, today=today())
        except ValidationError as exc:
            return _redirect("/", error=str(exc))
        return _redirect(
            "/", msg=f"Saved {saved.currency.value}/BRL {saved.rate} for {saved.rate_date}"
        )

    # -- assets --------------------------------------------------------------

    @app.get("/assets/new", response_class=HTMLResponse)
    def new_asset(request: Request) -> HTMLResponse:
        return render(request, "asset_form.html", asset=None, form={})

    @app.post("/assets", response_model=None)
    def create_asset(
        request: Request,
        name: Annotated[str, Form()] = "",
        kind: Annotated[str, Form()] = "stock",
        currency: Annotated[str, Form()] = "BRL",
        ticker: Annotated[str, Form()] = "",
        price_source: Annotated[str, Form()] = "",
        notes: Annotated[str, Form()] = "",
    ) -> Response:
        try:
            asset = service.create_asset(name, kind, currency, ticker, price_source or None, notes)
        except ValidationError as exc:
            form = {
                "name": name,
                "kind": kind,
                "currency": currency,
                "ticker": ticker,
                "price_source": price_source,
                "notes": notes,
            }
            return render(request, "asset_form.html", 422, asset=None, form=form, error=str(exc))
        return _redirect(
            f"/assets/{asset.id}", msg="Asset created. Now record how you acquired it."
        )

    @app.get("/assets/{asset_id}", response_class=HTMLResponse)
    def asset_detail(request: Request, asset_id: int) -> HTMLResponse:
        asset = db.get_asset(asset_id)
        summary = service.summary(today())
        holding = next(
            (h for h in [*summary.holdings, *summary.closed] if h.asset.id == asset_id), None
        )
        trades = db.trades(asset_id)
        try:
            position = build_position(trades)
        except ValueError:
            position = None
        return render(
            request,
            "asset_detail.html",
            asset=asset,
            holding=holding,
            position=position,
            weight=summary.weight(holding) if holding else None,
            trades=list(reversed(trades)),
            prices=db.prices(asset_id),
            income=db.income(asset_id),
        )

    @app.get("/assets/{asset_id}/edit", response_class=HTMLResponse)
    def edit_asset(request: Request, asset_id: int) -> HTMLResponse:
        asset = db.get_asset(asset_id)
        form = {
            "name": asset.name,
            "kind": asset.kind.value,
            "currency": asset.currency.value,
            "ticker": asset.ticker or "",
            "price_source": asset.price_source.value,
            "notes": asset.notes,
        }
        return render(request, "asset_form.html", asset=asset, form=form)

    @app.post("/assets/{asset_id}", response_model=None)
    def update_asset(
        request: Request,
        asset_id: int,
        name: Annotated[str, Form()] = "",
        kind: Annotated[str, Form()] = "stock",
        currency: Annotated[str, Form()] = "BRL",
        ticker: Annotated[str, Form()] = "",
        price_source: Annotated[str, Form()] = "",
        notes: Annotated[str, Form()] = "",
    ) -> Response:
        asset = db.get_asset(asset_id)
        try:
            service.update_asset(
                asset_id, name, kind, currency, ticker, price_source or None, notes
            )
        except ValidationError as exc:
            form = {
                "name": name,
                "kind": kind,
                "currency": currency,
                "ticker": ticker,
                "price_source": price_source,
                "notes": notes,
            }
            return render(request, "asset_form.html", 422, asset=asset, form=form, error=str(exc))
        return _redirect(f"/assets/{asset_id}", msg="Asset updated.")

    @app.post("/assets/{asset_id}/delete")
    def delete_asset(asset_id: int) -> Response:
        asset = db.get_asset(asset_id)
        service.delete_asset(asset_id)
        return _redirect("/", msg=f"Deleted {asset.name} and its history.")

    # -- trades, prices, income ----------------------------------------------

    @app.post("/assets/{asset_id}/trades")
    def add_trade(
        asset_id: int,
        side: Annotated[str, Form()],
        trade_date: Annotated[str, Form()],
        quantity: Annotated[str, Form()],
        unit_price: Annotated[str, Form()],
        fees: Annotated[str, Form()] = "",
    ) -> Response:
        try:
            service.record_trade(
                asset_id, side, trade_date, quantity, unit_price, fees, today=today()
            )
        except ValidationError as exc:
            return _redirect(f"/assets/{asset_id}", error=str(exc))
        return _redirect(f"/assets/{asset_id}", msg="Transaction saved.")

    @app.post("/trades/{trade_id}/delete")
    def delete_trade(trade_id: int, asset_id: Annotated[int, Form()]) -> Response:
        try:
            service.delete_trade(trade_id)
        except ValidationError as exc:
            return _redirect(f"/assets/{asset_id}", error=str(exc))
        return _redirect(f"/assets/{asset_id}", msg="Transaction deleted.")

    @app.post("/assets/{asset_id}/prices")
    def add_price(
        asset_id: int,
        price_date: Annotated[str, Form()],
        unit_price: Annotated[str, Form()],
    ) -> Response:
        try:
            service.record_price(asset_id, price_date, unit_price, today=today())
        except ValidationError as exc:
            return _redirect(f"/assets/{asset_id}", error=str(exc))
        return _redirect(f"/assets/{asset_id}", msg="Value saved.")

    @app.post("/prices/{price_id}/delete")
    def delete_price(price_id: int, asset_id: Annotated[int, Form()]) -> Response:
        db.delete_price(price_id)
        return _redirect(f"/assets/{asset_id}", msg="Value deleted.")

    @app.post("/assets/{asset_id}/income")
    def add_income(
        asset_id: int,
        income_date: Annotated[str, Form()],
        kind: Annotated[str, Form()],
        amount: Annotated[str, Form()],
        note: Annotated[str, Form()] = "",
    ) -> Response:
        try:
            service.record_income(asset_id, income_date, kind, amount, note, today=today())
        except ValidationError as exc:
            return _redirect(f"/assets/{asset_id}", error=str(exc))
        return _redirect(f"/assets/{asset_id}", msg="Income saved.")

    @app.post("/income/{income_id}/delete")
    def delete_income(income_id: int, asset_id: Annotated[int, Form()]) -> Response:
        db.delete_income(income_id)
        return _redirect(f"/assets/{asset_id}", msg="Income deleted.")

    return app
