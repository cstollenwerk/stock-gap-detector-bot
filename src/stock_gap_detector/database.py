from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - dependency is installed in Docker.
    psycopg = None
    dict_row = None


BAR_COLUMNS = [
    "date",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "atr_14",
    "atr_14_percent",
]
MARKET_CLOSE_BUFFER = time(16, 0)


@dataclass(frozen=True)
class TickerGroup:
    theme: str
    sector: str | None = None


@dataclass(frozen=True)
class CandleDatabase:
    database_url: str

    def healthcheck(self) -> None:
        with self.connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def load_active_tickers(
        self,
        *,
        min_atr_pct: float | None = None,
        min_market_cap: int | None = None,
    ) -> list[str]:
        atr_filter = ""
        market_cap_filter = ""
        params: list[float | int] = []
        if min_atr_pct is not None:
            atr_filter = "AND atr_14_percent >= %s"
            params.append(min_atr_pct * 100)
        if min_market_cap is not None:
            market_cap_filter = "AND market_cap >= %s"
            params.append(min_market_cap)

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT symbol
                FROM tickers
                WHERE active = true
                {atr_filter}
                {market_cap_filter}
                ORDER BY symbol
                """,
                tuple(params),
            ).fetchall()
        return [str(row["symbol"]).strip().upper() for row in rows if str(row["symbol"]).strip()]

    def load_ticker_groups(self, tickers: list[str] | tuple[str, ...]) -> dict[str, TickerGroup]:
        if not tickers:
            return {}

        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH parent_rollups AS (
                    SELECT
                        gg.child_group_id,
                        min(parent.name) AS sector
                    FROM groups_groups gg
                    JOIN groups parent ON parent.id = gg.parent_group_id
                    WHERE gg.relationship_type = 'rollup'
                        AND parent.group_type = 'larger_group'
                        AND (parent.ignored = false OR parent.ignored IS NULL)
                    GROUP BY gg.child_group_id
                )
                SELECT
                    t.symbol AS ticker,
                    g.name AS theme,
                    parent_rollups.sector
                FROM tickers t
                JOIN tickers_groups tg ON tg.ticker_id = t.id
                JOIN groups g ON g.id = tg.group_id
                LEFT JOIN parent_rollups ON parent_rollups.child_group_id = g.id
                WHERE t.symbol = ANY(%s)
                    AND g.group_type = 'stock_group'
                    AND (g.ignored = false OR g.ignored IS NULL)
                ORDER BY t.symbol, tg.is_primary DESC, g.name
                """,
                ([ticker.upper() for ticker in tickers],),
            ).fetchall()

        groups: dict[str, TickerGroup] = {}
        for row in rows:
            ticker = str(row["ticker"]).strip().upper()
            if ticker and ticker not in groups:
                groups[ticker] = TickerGroup(
                    theme=str(row["theme"]).strip(),
                    sector=str(row["sector"]).strip() if row["sector"] else None,
                )
        return groups

    def load_recent_candles(
        self,
        *,
        tickers: list[str] | tuple[str, ...] | None,
        end_date: date | None,
        lookback_days: int,
        min_atr_pct: float | None = None,
        min_market_cap: int | None = None,
    ) -> pd.DataFrame:
        resolved_tickers = sorted(
            set(tickers or self.load_active_tickers(min_atr_pct=min_atr_pct, min_market_cap=min_market_cap))
        )
        if not resolved_tickers:
            logging.warning("No tickers were available for candle loading.")
            return pd.DataFrame(columns=BAR_COLUMNS)

        resolved_end_date = end_date or latest_completed_trading_day()
        start_date = resolved_end_date - timedelta(days=lookback_days)
        return self.load_candles(resolved_tickers, start_date, resolved_end_date, min_market_cap=min_market_cap)

    def load_candles(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        *,
        min_market_cap: int | None = None,
    ) -> pd.DataFrame:
        if not tickers:
            return pd.DataFrame(columns=BAR_COLUMNS)

        market_cap_filter = ""
        params: list[object] = [tickers, start_date, end_date]
        if min_market_cap is not None:
            market_cap_filter = "AND t.market_cap >= %s"
            params.append(min_market_cap)

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    o.date::text AS date,
                    t.symbol AS ticker,
                    o.open::double precision AS open,
                    o.high::double precision AS high,
                    o.low::double precision AS low,
                    o.close::double precision AS close,
                    o.adj_close::double precision AS adj_close,
                    o.volume,
                    t.atr_14::double precision AS atr_14,
                    t.atr_14_percent::double precision AS atr_14_percent
                FROM tickers_ohlcv o
                JOIN tickers t ON t.id = o.ticker_id
                WHERE t.symbol = ANY(%s)
                    AND o.date >= %s
                    AND o.date <= %s
                    {market_cap_filter}
                ORDER BY t.symbol, o.date
                """,
                tuple(params),
            ).fetchall()

        if not rows:
            logging.warning(
                "candle-db returned no rows for %s ticker(s) from %s to %s.",
                len(tickers),
                start_date.isoformat(),
                end_date.isoformat(),
            )
            return pd.DataFrame(columns=BAR_COLUMNS)
        return normalize_bars(pd.DataFrame(rows, columns=BAR_COLUMNS))

    def connect(self):
        if psycopg is None or dict_row is None:
            raise RuntimeError("psycopg is not installed. Run `pip install -r requirements.txt`.")
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)


def normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    normalized = bars[BAR_COLUMNS].copy()
    normalized["date"] = pd.to_datetime(normalized["date"]).dt.date.astype(str)
    normalized["ticker"] = normalized["ticker"].astype(str).str.upper()
    for column in ["open", "high", "low", "close", "adj_close", "volume", "atr_14", "atr_14_percent"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.dropna(subset=["date", "ticker", "open", "high", "low", "close"])
    return normalized.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")


def latest_completed_trading_day(now: datetime | None = None) -> date:
    eastern_now = now.astimezone(ZoneInfo("America/New_York")) if now else datetime.now(ZoneInfo("America/New_York"))
    candidate = eastern_now.date()
    if candidate.weekday() >= 5 or eastern_now.time() < MARKET_CLOSE_BUFFER:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate
