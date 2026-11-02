"""Domain types.

Every holding follows one model: ``quantity x unit price``.

* A stock or fund: quantity = shares, unit price = price per share.
* A property: quantity = the fraction you own (1 = whole, 0.5 = half),
  unit price = the value of the whole property.
* A business stake: quantity = your ownership fraction (0.25 = 25 %),
  unit price = the value of 100 % of the company.

That keeps the arithmetic identical for every kind of asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class AssetClass(str, Enum):
    FINANCIAL = "financial"
    REAL_ESTATE = "real_estate"
    BUSINESS = "business"

    @property
    def label(self) -> str:
        return {
            AssetClass.FINANCIAL: "Financial assets",
            AssetClass.REAL_ESTATE: "Real estate",
            AssetClass.BUSINESS: "Businesses",
        }[self]


class AssetKind(str, Enum):
    STOCK = "stock"
    REIT = "reit"  # FIIs in Brazil
    ETF = "etf"
    BDR = "bdr"
    FIXED_INCOME = "fixed_income"
    FUND = "fund"
    CRYPTO = "crypto"
    CASH = "cash"
    REAL_ESTATE = "real_estate"
    BUSINESS = "business"
    OTHER = "other"

    @property
    def asset_class(self) -> AssetClass:
        if self is AssetKind.REAL_ESTATE:
            return AssetClass.REAL_ESTATE
        if self is AssetKind.BUSINESS:
            return AssetClass.BUSINESS
        return AssetClass.FINANCIAL

    @property
    def label(self) -> str:
        return _KIND_LABELS[self]

    @property
    def uses_ownership_fraction(self) -> bool:
        """Properties and businesses are held as a fraction of the whole."""
        return self in (AssetKind.REAL_ESTATE, AssetKind.BUSINESS)

    @property
    def is_listed(self) -> bool:
        """Kinds that usually have a ticker and a market quote."""
        return self in (AssetKind.STOCK, AssetKind.REIT, AssetKind.ETF, AssetKind.BDR)


_KIND_LABELS = {
    AssetKind.STOCK: "Stock",
    AssetKind.REIT: "REIT / FII",
    AssetKind.ETF: "ETF",
    AssetKind.BDR: "BDR",
    AssetKind.FIXED_INCOME: "Fixed income",
    AssetKind.FUND: "Investment fund",
    AssetKind.CRYPTO: "Crypto",
    AssetKind.CASH: "Cash",
    AssetKind.REAL_ESTATE: "Real estate",
    AssetKind.BUSINESS: "Business stake",
    AssetKind.OTHER: "Other",
}


class Currency(str, Enum):
    BRL = "BRL"
    USD = "USD"


BASE_CURRENCY = Currency.BRL


class PriceSource(str, Enum):
    MANUAL = "manual"
    BRAPI = "brapi"  # Brazilian exchange (B3)
    FINNHUB = "finnhub"  # US exchanges

    @property
    def label(self) -> str:
        return {
            PriceSource.MANUAL: "Manual",
            PriceSource.BRAPI: "brapi.dev (B3)",
            PriceSource.FINNHUB: "Finnhub (US)",
        }[self]

    @property
    def is_automatic(self) -> bool:
        return self is not PriceSource.MANUAL


def default_price_source(kind: AssetKind, currency: Currency, ticker: str | None) -> PriceSource:
    if not ticker or not kind.is_listed:
        return PriceSource.MANUAL
    return PriceSource.BRAPI if currency is Currency.BRL else PriceSource.FINNHUB


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class IncomeKind(str, Enum):
    DIVIDEND = "dividend"
    INTEREST_ON_EQUITY = "jcp"  # Juros sobre capital próprio
    RENT = "rent"
    DISTRIBUTION = "distribution"  # profit distributed by a business
    INTEREST = "interest"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {
            IncomeKind.DIVIDEND: "Dividend",
            IncomeKind.INTEREST_ON_EQUITY: "JCP",
            IncomeKind.RENT: "Rent",
            IncomeKind.DISTRIBUTION: "Profit distribution",
            IncomeKind.INTEREST: "Interest",
            IncomeKind.OTHER: "Other",
        }[self]


@dataclass(frozen=True)
class Asset:
    id: int
    name: str
    kind: AssetKind
    currency: Currency
    ticker: str | None
    price_source: PriceSource
    notes: str = ""

    @property
    def asset_class(self) -> AssetClass:
        return self.kind.asset_class


@dataclass(frozen=True)
class Trade:
    id: int
    asset_id: int
    side: TradeSide
    trade_date: date
    quantity: Decimal
    unit_price: Decimal
    fees: Decimal = Decimal(0)


@dataclass(frozen=True)
class Price:
    id: int
    asset_id: int
    price_date: date
    unit_price: Decimal
    source: PriceSource


@dataclass(frozen=True)
class Income:
    id: int
    asset_id: int
    income_date: date
    kind: IncomeKind
    amount: Decimal
    note: str = ""


@dataclass(frozen=True)
class FxRate:
    """How many BRL one unit of ``currency`` is worth on ``rate_date``."""

    id: int
    currency: Currency
    rate_date: date
    rate: Decimal
    source: str
