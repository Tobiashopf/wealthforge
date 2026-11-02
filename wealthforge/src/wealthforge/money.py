"""Parsing and formatting of decimal amounts. Money never touches floats."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import Currency

CENT = Decimal("0.01")

_SYMBOLS = {Currency.BRL: "R$", Currency.USD: "US$"}


def parse_decimal(text: str | int | float | Decimal, *, field: str = "value") -> Decimal:
    """Parse numbers typed by a person in either Brazilian or US style.

    ``1.234,56`` and ``1,234.56`` both become ``Decimal("1234.56")``.
    ``0,5`` and ``0.5`` become ``Decimal("0.5")``.
    ``1.800`` is rejected as ambiguous (thousands in Brazil, decimals in the US).
    """
    if isinstance(text, Decimal):
        return text
    if isinstance(text, int):
        return Decimal(text)
    if isinstance(text, float):
        return Decimal(str(text))

    cleaned = re.sub(r"[\s]|R\$|US\$|\$", "", text.strip())
    if not cleaned:
        raise ValueError(f"{field} is required")

    if "," in cleaned and "." in cleaned:
        # Whichever separator comes last is the decimal separator.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned or "." in cleaned:
        sep = "," if "," in cleaned else "."
        if cleaned.count(sep) > 1:
            cleaned = cleaned.replace(sep, "")  # 1.234.567 or 1,234,567
        else:
            integer, fraction = cleaned.split(sep)
            if len(fraction) == 3 and integer.lstrip("-+") not in ("", "0"):
                # "1.800" is 1800 in Brazil and 1.8 in the US: refuse to guess.
                raise ValueError(
                    f"{field}: {text!r} is ambiguous; write it as "
                    f"{integer}{fraction} or with cents, e.g. {integer}.{fraction},00"
                )
            cleaned = f"{integer}.{fraction}"

    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"{field}: {text!r} is not a number") from None
    if not value.is_finite():
        raise ValueError(f"{field}: {text!r} is not a number")
    return value


def parse_positive(text: str | Decimal, *, field: str) -> Decimal:
    value = parse_decimal(text, field=field)
    if value <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return value


def parse_non_negative(text: str | Decimal, *, field: str) -> Decimal:
    if isinstance(text, str) and not text.strip():
        return Decimal(0)
    value = parse_decimal(text, field=field)
    if value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def round_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _group(number: Decimal, thousands: str, decimal_sep: str) -> str:
    text = f"{abs(round_cents(number)):,.2f}"  # 1,234.56
    integer, frac = text.split(".")
    return integer.replace(",", thousands) + decimal_sep + frac


def format_money(value: Decimal | None, currency: Currency | str) -> str:
    """``R$ 1.234,56`` for BRL and ``US$ 1,234.56`` for USD."""
    if value is None:
        return "-"
    currency = Currency(currency)
    thousands, decimal_sep = (".", ",") if currency is Currency.BRL else (",", ".")
    body = _group(value, thousands, decimal_sep)
    sign = "-" if round_cents(value) < 0 else ""
    return f"{sign}{_SYMBOLS[currency]} {body}"


def format_quantity(value: Decimal) -> str:
    """Drop trailing zeros: ``10`` instead of ``10.000000``."""
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        return f"{int(normalized):,}"
    return f"{normalized:,f}"


def format_ownership(fraction: Decimal) -> str:
    """``0.25`` -> ``25%``, ``0.3333`` -> ``33.33%``."""
    return f"{format_quantity(fraction * 100)}%"


def format_percent(value: Decimal | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.{digits}f}%"
