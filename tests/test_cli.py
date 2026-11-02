from __future__ import annotations

import os
from pathlib import Path

import pytest

from wealthforge import __version__
from wealthforge.cli import main
from wealthforge.config import Settings, load_dotenv


def test_demo_then_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "demo.db"
    assert main(["demo", "--db", str(db)]) == 0
    assert "Loaded 6 fictional assets" in capsys.readouterr().out
    assert main(["summary", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "Net worth: R$" in out
    assert "Two-bedroom apartment (sample)" in out
    # A second demo load into the same file is refused.
    assert main(["demo", "--db", str(db)]) == 1


def test_summary_of_empty_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary", "--db", str(tmp_path / "empty.db")]) == 0
    assert "No open positions" in capsys.readouterr().out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_dotenv_does_not_override_real_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nBRAPI_TOKEN='from-file'\nFINNHUB_TOKEN=from-file\nnot a line\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BRAPI_TOKEN", raising=False)
    monkeypatch.setenv("FINNHUB_TOKEN", "from-env")
    load_dotenv(env_file)
    assert os.environ["BRAPI_TOKEN"] == "from-file"
    assert os.environ["FINNHUB_TOKEN"] == "from-env"
    monkeypatch.delenv("BRAPI_TOKEN")


def test_settings_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEALTHFORGE_DB", str(tmp_path / "x.db"))
    monkeypatch.setenv("BRAPI_TOKEN", "")
    settings = Settings.from_env()
    assert settings.db_path == tmp_path / "x.db"
    assert settings.brapi_token is None
    assert Settings.from_env(tmp_path / "y.db").db_path == tmp_path / "y.db"
