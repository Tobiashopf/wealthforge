from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from wealthforge.db import Database
from wealthforge.service import PortfolioService

TODAY = date(2026, 11, 2)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    with Database(tmp_path / "test.db") as database:
        yield database


@pytest.fixture
def service(db: Database) -> PortfolioService:
    return PortfolioService(db)
