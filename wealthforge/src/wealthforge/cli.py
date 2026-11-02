"""Command line: start the web app, refresh quotes, print a summary, load demo data."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import httpx

from . import __version__
from .config import Settings, load_dotenv
from .db import Database
from .models import BASE_CURRENCY
from .money import format_money, format_percent
from .quotes import refresh_quotes
from .sample import load_sample
from .service import PortfolioService


def _settings(args: argparse.Namespace) -> Settings:
    return Settings.from_env(args.db)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web.app import create_app

    settings = _settings(args)
    app = create_app(settings)
    url = f"http://{args.host}:{args.port}"
    print(f"Wealthforge is running at {url}  (database: {settings.db_path})")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    settings = _settings(args)
    with Database(settings.db_path) as db, httpx.Client() as client:
        report = refresh_quotes(db, client, settings, date.today())
    for line in report.lines():
        print(line)
    return 0 if report.ok else 1


def cmd_summary(args: argparse.Namespace) -> int:
    settings = _settings(args)
    with Database(settings.db_path) as db:
        summary = PortfolioService(db).summary(date.today())
    rows = [
        (
            h.asset.name,
            h.asset.kind.label,
            format_money(h.market_value_base, BASE_CURRENCY),
            format_percent(summary.weight(h)),
        )
        for h in summary.holdings
    ]
    if not rows:
        print("No open positions. Start the app with 'wealthforge serve' to add assets.")
        return 0
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for name, kind, value, weight in rows:
        print(
            f"{name.ljust(widths[0])}  {kind.ljust(widths[1])}  "
            f"{value.rjust(widths[2])}  {weight.rjust(widths[3])}"
        )
    print()
    print(f"Net worth: {format_money(summary.total_value, BASE_CURRENCY)}")
    for warning in summary.warnings:
        print(f"! {warning}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    settings = _settings(args)
    with Database(settings.db_path) as db:
        try:
            count = load_sample(PortfolioService(db), date.today())
        except ValueError as exc:
            print(f"wealthforge: error: {exc}", file=sys.stderr)
            return 1
    print(f"Loaded {count} fictional assets into {settings.db_path}")
    print(f"Open them with: wealthforge serve --db {settings.db_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wealthforge",
        description="Organize investments, real estate and business stakes in one local app.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument(
            "--db",
            type=Path,
            help="SQLite file (default: $WEALTHFORGE_DB or your user data folder)",
        )
        return p

    p = command("serve", "start the web app on this computer")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    p.set_defaults(func=cmd_serve)

    p = command("refresh", "update automatic prices and the USD/BRL rate")
    p.set_defaults(func=cmd_refresh)
    command("summary", "print your holdings and net worth").set_defaults(func=cmd_summary)
    command("demo", "load a fictional sample portfolio into an empty database").set_defaults(
        func=cmd_demo
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")
    args = build_parser().parse_args(argv)
    return int(args.func(args))


def run() -> None:
    sys.exit(main())
