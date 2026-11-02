"""Settings from environment variables, optionally loaded from a local .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: ``KEY=value`` lines, ``#`` comments.
    Variables that are already set in the environment win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def default_db_path() -> Path:
    if os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "wealthforge" / "wealthforge.db"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    brapi_token: str | None
    finnhub_token: str | None

    @classmethod
    def from_env(cls, db_path: Path | None = None) -> Settings:
        env_db = os.environ.get("WEALTHFORGE_DB")
        return cls(
            db_path=db_path or (Path(env_db).expanduser() if env_db else default_db_path()),
            brapi_token=os.environ.get("BRAPI_TOKEN") or None,
            finnhub_token=os.environ.get("FINNHUB_TOKEN") or None,
        )
