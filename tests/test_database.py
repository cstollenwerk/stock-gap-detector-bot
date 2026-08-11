from datetime import date, datetime, timezone
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from stock_gap_detector.database import BAR_COLUMNS, CandleDatabase, TickerGroup, latest_completed_trading_day, normalize_bars


class DatabaseTests(unittest.TestCase):
    def test_latest_completed_trading_day_uses_market_close_boundary(self):
        before_close = datetime(2026, 7, 20, 19, 59, tzinfo=timezone.utc)
        at_close = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)

        self.assertEqual(latest_completed_trading_day(before_close), date(2026, 7, 17))
        self.assertEqual(latest_completed_trading_day(at_close), date(2026, 7, 20))

    def test_normalize_bars_orders_and_coerces_rows(self):
        rows = pd.DataFrame(
            [
                {
                    "date": "2026-07-16",
                    "ticker": "msft",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "adj_close": "100.5",
                    "volume": "1000",
                },
                {
                    "date": "2026-07-15",
                    "ticker": "AAPL",
                    "open": "200",
                    "high": "201",
                    "low": "199",
                    "close": "200.5",
                    "adj_close": "200.5",
                    "volume": "2000",
                },
            ],
            columns=BAR_COLUMNS,
        )

        normalized = normalize_bars(rows)

        self.assertEqual(normalized["ticker"].tolist(), ["AAPL", "MSFT"])
        self.assertEqual(normalized["close"].tolist(), [200.5, 100.5])

    @patch("stock_gap_detector.database.dict_row", object())
    @patch("stock_gap_detector.database.psycopg")
    def test_load_active_tickers_reads_active_symbols(self, psycopg):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.execute.return_value.fetchall.return_value = [{"symbol": "AAPL"}, {"symbol": "msft"}]
        psycopg.connect.return_value = connection

        tickers = CandleDatabase("postgresql://example/candle_db").load_active_tickers()

        self.assertEqual(tickers, ["AAPL", "MSFT"])

    @patch("stock_gap_detector.database.dict_row", object())
    @patch("stock_gap_detector.database.psycopg")
    def test_load_ticker_groups_reads_primary_theme_and_sector(self, psycopg):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.execute.return_value.fetchall.return_value = [
            {"ticker": "NVDA", "theme": "MAG 7", "sector": "AI Infrastructure"},
            {"ticker": "NVDA", "theme": "SEMI - AI & ACCELERATORS", "sector": "Semiconductors"},
            {"ticker": "VRT", "theme": "DATA CENTER COOLING", "sector": "AI Infrastructure"},
        ]
        psycopg.connect.return_value = connection

        groups = CandleDatabase("postgresql://example/candle_db").load_ticker_groups(["NVDA", "VRT"])

        self.assertEqual(
            groups,
            {
                "NVDA": TickerGroup(theme="MAG 7", sector="AI Infrastructure"),
                "VRT": TickerGroup(theme="DATA CENTER COOLING", sector="AI Infrastructure"),
            },
        )

    @patch("stock_gap_detector.database.dict_row", object())
    @patch("stock_gap_detector.database.psycopg")
    def test_load_candles_queries_candle_db(self, psycopg):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.execute.return_value.fetchall.return_value = [
            {
                "date": "2026-07-15",
                "ticker": "AAPL",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "adj_close": 100.5,
                "volume": 1000,
            }
        ]
        psycopg.connect.return_value = connection

        bars = CandleDatabase("postgresql://example/candle_db").load_candles(
            ["AAPL"],
            date(2026, 7, 1),
            date(2026, 7, 15),
        )

        self.assertEqual(bars["ticker"].tolist(), ["AAPL"])
        connection.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
