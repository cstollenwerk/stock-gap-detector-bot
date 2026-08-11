from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in normal use.
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOG_FILE = DATA_DIR / "stock_gap_detector.log"
RESULTS_FILE = DATA_DIR / "gap_candidates.json"
REPORT_FILE = DATA_DIR / "gap_report.md"
EASTERN_TZ = ZoneInfo("America/New_York")

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8-sig")


@dataclass(frozen=True)
class Config:
    database_url: str
    lookback_days: int = 365
    min_bars: int = 60
    proximity_pct: float = 0.01
    gap_limit: int = 50
    run_interval_minutes: int = 1440
    tickers: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Config":
        database_url = database_url_from_env()
        if not database_url:
            raise RuntimeError(
                "Database credentials are not set. Provide STOCK_GAP_DETECTOR_DB_HOST, "
                "STOCK_GAP_DETECTOR_DB_NAME, STOCK_GAP_DETECTOR_DB_USER, and "
                "STOCK_GAP_DETECTOR_DB_PASSWORD, or provide STOCK_GAP_DETECTOR_CANDLE_DB_URL."
            )

        return cls(
            database_url=database_url,
            lookback_days=env_int("STOCK_GAP_DETECTOR_LOOKBACK_DAYS", 365),
            min_bars=env_int("STOCK_GAP_DETECTOR_MIN_BARS", 60),
            proximity_pct=env_float("STOCK_GAP_DETECTOR_PROXIMITY_PCT", 0.01),
            gap_limit=env_int("STOCK_GAP_DETECTOR_GAP_LIMIT", 50),
            run_interval_minutes=env_int("STOCK_GAP_DETECTOR_RUN_INTERVAL_MINUTES", 1440),
            tickers=parse_tickers(env_value("STOCK_GAP_DETECTOR_TICKERS")),
        )


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    channel_id: int
    guild_id: int | None = None
    command_name: str = "gapreport"
    report_time: time = time(hour=20, minute=0, tzinfo=EASTERN_TZ)

    @classmethod
    def from_env(cls) -> "DiscordConfig":
        token = env_value("STOCK_GAP_DETECTOR_DISCORD_TOKEN", "DISCORD_TOKEN")
        channel_id = env_int("STOCK_GAP_DETECTOR_DISCORD_CHANNEL_ID", 0)
        if not token:
            raise RuntimeError("Discord token is not set. Provide STOCK_GAP_DETECTOR_DISCORD_TOKEN.")
        if not channel_id:
            raise RuntimeError("Discord channel ID is not set. Provide STOCK_GAP_DETECTOR_DISCORD_CHANNEL_ID.")

        guild_id = env_int("STOCK_GAP_DETECTOR_DISCORD_GUILD_ID", 0) or None
        command_name = env_value("STOCK_GAP_DETECTOR_DISCORD_COMMAND_NAME") or "gapreport"
        return cls(token=token, channel_id=channel_id, guild_id=guild_id, command_name=command_name)


def env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def database_url_from_env() -> str:
    discrete_url = database_url_from_parts()
    if discrete_url:
        return discrete_url
    return env_value(
        "STOCK_GAP_DETECTOR_CANDLE_DB_URL",
        "CANDLE_DB_DATABASE_URL",
        "MARKET_OVERWATCH_CANDLE_DB_URL",
        "DATABASE_URL",
    )


def database_url_from_parts() -> str:
    raw_host = env_value("STOCK_GAP_DETECTOR_DB_HOST")
    database = env_value("STOCK_GAP_DETECTOR_DB_NAME")
    user = env_value("STOCK_GAP_DETECTOR_DB_USER")
    password = env_value("STOCK_GAP_DETECTOR_DB_PASSWORD")
    if not any([raw_host, database, user, password]):
        return ""
    host = raw_host or "localhost"
    missing = [
        name
        for name, value in {
            "STOCK_GAP_DETECTOR_DB_NAME": database,
            "STOCK_GAP_DETECTOR_DB_USER": user,
            "STOCK_GAP_DETECTOR_DB_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Incomplete database settings. Missing: {', '.join(missing)}.")
    port = env_int("STOCK_GAP_DETECTOR_DB_PORT", 5432)
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(database, safe='')}"


def env_int(name: str, default: int) -> int:
    value = env_value(name)
    if not value:
        return default
    try:
        return max(1, int(value))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = env_value(name)
    if not value:
        return default
    try:
        return max(0.0, float(value))
    except ValueError:
        return default


def parse_tickers(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    tickers = [ticker.strip().upper() for ticker in value.split(",")]
    return tuple(dict.fromkeys(ticker for ticker in tickers if ticker))
