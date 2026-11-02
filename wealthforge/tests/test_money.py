from __future__ import annotations

from decimal import Decimal as D

import pytest

from wealthforge.models import Currency
from wealthforge.money import (
    format_money,
    format_ownership,
    format_percent,
    format_quantity,
    parse_decimal,
    parse_non_negative,
    parse_positive,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1234.56", D("1234.56")),
        ("1.234,56", D("1234.56")),
        ("1,234.56", D("1234.56")),
        ("0,5", D("0.5")),
        ("1.234.567", D("1234567")),
        ("1,234,567", D("1234567")),
        ("R$ 2.500,00", D("2500.00")),
        ("US$ 99.9", D("99.9")),
        ("  42 ", D("42")),
        ("-3,5", D("-3.5")),
    ],
)
def test_parse_decimal_accepts_brazilian_and_us_styles(text: str, expected: D) -> None:
    assert parse_decimal(text) == expected


def test_parse_decimal_refuses_to_guess_thousands() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        parse_decimal("1.800")
    with pytest.raises(ValueError, match="ambiguous"):
        parse_decimal("2,500")
    assert parse_decimal("0.125") == D("0.125")  # a leading zero is clearly decimal
    assert parse_decimal("1.80") == D("1.80")


@pytest.mark.parametrize("text", ["", "abc", "1.2.3,4,5", "NaN", "Infinity"])
def test_parse_decimal_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        parse_decimal(text)


def test_parse_positive_and_non_negative() -> None:
    assert parse_positive("1,5", field="qty") == D("1.5")
    with pytest.raises(ValueError, match="qty must be greater than zero"):
        parse_positive("0", field="qty")
    assert parse_non_negative("", field="fees") == 0
    with pytest.raises(ValueError, match="cannot be negative"):
        parse_non_negative("-1", field="fees")


def test_format_money() -> None:
    assert format_money(D("1234567.891"), Currency.BRL) == "R$ 1.234.567,89"
    assert format_money(D("1234.5"), Currency.USD) == "US$ 1,234.50"
    assert format_money(D("-10"), "BRL") == "-R$ 10,00"
    assert format_money(D("-0.001"), Currency.BRL) == "R$ 0,00"
    assert format_money(None, Currency.BRL) == "-"


def test_format_quantity_and_percent() -> None:
    assert format_quantity(D("200")) == "200"
    assert format_quantity(D("1.2E+2")) == "120"
    assert format_quantity(D("3.2000")) == "3.2"
    assert format_ownership(D("0.25")) == "25%"
    assert format_ownership(D("1")) == "100%"
    assert format_percent(D("0.1234")) == "12.3%"
    assert format_percent(None) == "-"
