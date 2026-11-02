"""USD/BRL exchange rate (PTAX) from the Banco Central do Brasil open-data API.

No key needed. PTAX only exists on business days, so we ask for the last ten
days and keep the most recent bulletin.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx

from .base import QuoteError, get_json

BASE = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata"
NAME = "Banco Central (PTAX)"
LOOKBACK_DAYS = 10


def ptax_url(start: date, end: date) -> str:
    return (
        f"{BASE}/CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
        f"?@dataInicial='{start:%m-%d-%Y}'&@dataFinalCotacao='{end:%m-%d-%Y}'"
        "&$format=json&$select=cotacaoVenda,dataHoraCotacao"
    )


def fetch_usd_brl(client: httpx.Client, today: date) -> tuple[date, Decimal]:
    """Return (bulletin date, selling rate) of the latest PTAX bulletin."""
    url = ptax_url(today - timedelta(days=LOOKBACK_DAYS), today)
    payload = get_json(client, url, provider=NAME)
    values = payload.get("value") if isinstance(payload, dict) else None
    if not values:
        raise QuoteError(f"{NAME} returned no rate for the last {LOOKBACK_DAYS} days")
    latest = max(values, key=lambda v: str(v.get("dataHoraCotacao", "")))
    rate = latest.get("cotacaoVenda")
    stamp = latest.get("dataHoraCotacao")
    if not isinstance(rate, Decimal) or rate <= 0 or not stamp:
        raise QuoteError(f"{NAME} returned an invalid rate")
    try:
        bulletin = datetime.strptime(str(stamp)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise QuoteError(f"{NAME} returned an invalid date") from exc
    return bulletin, rate
