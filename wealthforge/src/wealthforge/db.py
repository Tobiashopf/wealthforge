"""SQLite persistence. Amounts are stored as TEXT so Decimal values survive intact."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import (
    Asset,
    AssetKind,
    Currency,
    FxRate,
    Income,
    IncomeKind,
    Price,
    PriceSource,
    Trade,
    TradeSide,
)

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE assets (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL,
    currency     TEXT NOT NULL,
    ticker       TEXT,
    price_source TEXT NOT NULL,
    notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE trades (
    id         INTEGER PRIMARY KEY,
    asset_id   INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    side       TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    trade_date TEXT NOT NULL,
    quantity   TEXT NOT NULL,
    unit_price TEXT NOT NULL,
    fees       TEXT NOT NULL DEFAULT '0'
);
CREATE INDEX trades_asset ON trades(asset_id, trade_date);

CREATE TABLE prices (
    id         INTEGER PRIMARY KEY,
    asset_id   INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    price_date TEXT NOT NULL,
    unit_price TEXT NOT NULL,
    source     TEXT NOT NULL,
    UNIQUE (asset_id, price_date)
);

CREATE TABLE income (
    id          INTEGER PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    income_date TEXT NOT NULL,
    kind        TEXT NOT NULL,
    amount      TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX income_asset ON income(asset_id, income_date);

CREATE TABLE fx_rates (
    id        INTEGER PRIMARY KEY,
    currency  TEXT NOT NULL,
    rate_date TEXT NOT NULL,
    rate      TEXT NOT NULL,
    source    TEXT NOT NULL,
    UNIQUE (currency, rate_date)
);
"""


class NotFoundError(LookupError):
    pass


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"{self.path} was created by a newer Wealthforge (schema {version})")
        if version == 0:
            with self._conn:
                self._conn.executescript(_SCHEMA_V1)
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # -- assets --------------------------------------------------------------

    @staticmethod
    def _asset(row: sqlite3.Row) -> Asset:
        return Asset(
            id=row["id"],
            name=row["name"],
            kind=AssetKind(row["kind"]),
            currency=Currency(row["currency"]),
            ticker=row["ticker"],
            price_source=PriceSource(row["price_source"]),
            notes=row["notes"],
        )

    def add_asset(
        self,
        name: str,
        kind: AssetKind,
        currency: Currency,
        ticker: str | None = None,
        price_source: PriceSource = PriceSource.MANUAL,
        notes: str = "",
    ) -> Asset:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO assets (name, kind, currency, ticker, price_source, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, kind.value, currency.value, ticker, price_source.value, notes),
            )
        return self.get_asset(int(cur.lastrowid or 0))

    def update_asset(self, asset: Asset) -> Asset:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE assets SET name = ?, kind = ?, currency = ?, ticker = ?, "
                "price_source = ?, notes = ? WHERE id = ?",
                (
                    asset.name,
                    asset.kind.value,
                    asset.currency.value,
                    asset.ticker,
                    asset.price_source.value,
                    asset.notes,
                    asset.id,
                ),
            )
        return self.get_asset(asset.id)

    def get_asset(self, asset_id: int) -> Asset:
        row = self._conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"asset {asset_id} not found")
        return self._asset(row)

    def list_assets(self) -> list[Asset]:
        rows = self._conn.execute("SELECT * FROM assets ORDER BY name COLLATE NOCASE, id")
        return [self._asset(row) for row in rows]

    def delete_asset(self, asset_id: int) -> None:
        self.get_asset(asset_id)
        with self.transaction() as conn:
            conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))

    # -- trades --------------------------------------------------------------

    @staticmethod
    def _trade(row: sqlite3.Row) -> Trade:
        return Trade(
            id=row["id"],
            asset_id=row["asset_id"],
            side=TradeSide(row["side"]),
            trade_date=date.fromisoformat(row["trade_date"]),
            quantity=Decimal(row["quantity"]),
            unit_price=Decimal(row["unit_price"]),
            fees=Decimal(row["fees"]),
        )

    def add_trade(
        self,
        asset_id: int,
        side: TradeSide,
        trade_date: date,
        quantity: Decimal,
        unit_price: Decimal,
        fees: Decimal = Decimal(0),
    ) -> Trade:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO trades (asset_id, side, trade_date, quantity, unit_price, fees) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    asset_id,
                    side.value,
                    trade_date.isoformat(),
                    str(quantity),
                    str(unit_price),
                    str(fees),
                ),
            )
        row = self._conn.execute("SELECT * FROM trades WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._trade(row)

    def trades(self, asset_id: int | None = None) -> list[Trade]:
        sql = "SELECT * FROM trades"
        params: tuple[object, ...] = ()
        if asset_id is not None:
            sql += " WHERE asset_id = ?"
            params = (asset_id,)
        sql += " ORDER BY trade_date, id"
        return [self._trade(row) for row in self._conn.execute(sql, params)]

    def delete_trade(self, trade_id: int) -> Trade:
        row = self._conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"trade {trade_id} not found")
        with self.transaction() as conn:
            conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        return self._trade(row)

    # -- prices --------------------------------------------------------------

    @staticmethod
    def _price(row: sqlite3.Row) -> Price:
        return Price(
            id=row["id"],
            asset_id=row["asset_id"],
            price_date=date.fromisoformat(row["price_date"]),
            unit_price=Decimal(row["unit_price"]),
            source=PriceSource(row["source"]),
        )

    def set_price(
        self, asset_id: int, price_date: date, unit_price: Decimal, source: PriceSource
    ) -> Price:
        """Insert or replace the price of an asset on a given day."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO prices (asset_id, price_date, unit_price, source) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (asset_id, price_date) DO UPDATE SET "
                "unit_price = excluded.unit_price, source = excluded.source",
                (asset_id, price_date.isoformat(), str(unit_price), source.value),
            )
        row = self._conn.execute(
            "SELECT * FROM prices WHERE asset_id = ? AND price_date = ?",
            (asset_id, price_date.isoformat()),
        ).fetchone()
        return self._price(row)

    def prices(self, asset_id: int) -> list[Price]:
        rows = self._conn.execute(
            "SELECT * FROM prices WHERE asset_id = ? ORDER BY price_date DESC", (asset_id,)
        )
        return [self._price(row) for row in rows]

    def latest_prices(self, on_or_before: date) -> dict[int, Price]:
        """Most recent price of every asset, as of a date."""
        rows = self._conn.execute(
            "SELECT p.* FROM prices p JOIN ("
            "  SELECT asset_id, MAX(price_date) AS d FROM prices WHERE price_date <= ? "
            "  GROUP BY asset_id"
            ") last ON last.asset_id = p.asset_id AND last.d = p.price_date",
            (on_or_before.isoformat(),),
        )
        return {row["asset_id"]: self._price(row) for row in rows}

    def delete_price(self, price_id: int) -> None:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM prices WHERE id = ?", (price_id,))
        if cur.rowcount == 0:
            raise NotFoundError(f"price {price_id} not found")

    # -- income --------------------------------------------------------------

    @staticmethod
    def _income(row: sqlite3.Row) -> Income:
        return Income(
            id=row["id"],
            asset_id=row["asset_id"],
            income_date=date.fromisoformat(row["income_date"]),
            kind=IncomeKind(row["kind"]),
            amount=Decimal(row["amount"]),
            note=row["note"],
        )

    def add_income(
        self, asset_id: int, income_date: date, kind: IncomeKind, amount: Decimal, note: str = ""
    ) -> Income:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO income (asset_id, income_date, kind, amount, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (asset_id, income_date.isoformat(), kind.value, str(amount), note),
            )
        row = self._conn.execute("SELECT * FROM income WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._income(row)

    def income(self, asset_id: int | None = None) -> list[Income]:
        sql = "SELECT * FROM income"
        params: tuple[object, ...] = ()
        if asset_id is not None:
            sql += " WHERE asset_id = ?"
            params = (asset_id,)
        sql += " ORDER BY income_date DESC, id DESC"
        return [self._income(row) for row in self._conn.execute(sql, params)]

    def delete_income(self, income_id: int) -> None:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM income WHERE id = ?", (income_id,))
        if cur.rowcount == 0:
            raise NotFoundError(f"income {income_id} not found")

    # -- exchange rates ------------------------------------------------------

    @staticmethod
    def _fx(row: sqlite3.Row) -> FxRate:
        return FxRate(
            id=row["id"],
            currency=Currency(row["currency"]),
            rate_date=date.fromisoformat(row["rate_date"]),
            rate=Decimal(row["rate"]),
            source=row["source"],
        )

    def set_fx_rate(
        self, currency: Currency, rate_date: date, rate: Decimal, source: str
    ) -> FxRate:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO fx_rates (currency, rate_date, rate, source) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (currency, rate_date) DO UPDATE SET "
                "rate = excluded.rate, source = excluded.source",
                (currency.value, rate_date.isoformat(), str(rate), source),
            )
        latest = self.latest_fx_rate(currency, rate_date)
        assert latest is not None
        return latest

    def latest_fx_rate(self, currency: Currency, on_or_before: date) -> FxRate | None:
        row = self._conn.execute(
            "SELECT * FROM fx_rates WHERE currency = ? AND rate_date <= ? "
            "ORDER BY rate_date DESC LIMIT 1",
            (currency.value, on_or_before.isoformat()),
        ).fetchone()
        return self._fx(row) if row else None

    def fx_rates(self, currency: Currency, limit: int = 30) -> list[FxRate]:
        rows = self._conn.execute(
            "SELECT * FROM fx_rates WHERE currency = ? ORDER BY rate_date DESC LIMIT ?",
            (currency.value, limit),
        )
        return [self._fx(row) for row in rows]
