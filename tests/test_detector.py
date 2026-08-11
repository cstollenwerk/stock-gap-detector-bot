import unittest

import pandas as pd

from stock_gap_detector.detector import GapDetector, average_true_range


class DetectorTests(unittest.TestCase):
    def test_empty_candles_return_no_candidates(self):
        self.assertEqual(GapDetector(min_bars=60).analyze(pd.DataFrame()), [])

    def test_placeholder_detector_returns_no_candidates(self):
        rows = [
            {
                "date": f"2026-07-{day:02d}",
                "ticker": "AAPL",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "adj_close": 100.5,
                "volume": 1000,
            }
            for day in range(1, 16)
        ]

        self.assertEqual(GapDetector(min_bars=10).analyze(pd.DataFrame(rows)), [])

    def test_detects_latest_close_near_active_support_gap(self):
        rows = [
            candle("2026-07-01", "AAPL", high=101, low=99, close=100),
            candle("2026-07-02", "AAPL", high=110, low=105, close=108),
            candle("2026-07-03", "AAPL", high=108, low=104, close=105.8),
        ]

        candidates = GapDetector(min_bars=3, proximity_pct=0.01).analyze(pd.DataFrame(rows))

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].gap_type, "support")
        self.assertEqual(candidates[0].gap_bottom, 100)
        self.assertEqual(candidates[0].gap_top, 105)
        self.assertTrue(candidates[0].touched)
        self.assertTrue(candidates[0].within_one_atr)
        self.assertAlmostEqual(candidates[0].atr_14, 5.3333, places=4)
        self.assertAlmostEqual(candidates[0].metadata["distance_to_gap"], 0.8)
        self.assertEqual(candidates[0].touch_count, 1)

    def test_detects_latest_close_near_active_resistance_gap(self):
        rows = [
            candle("2026-07-01", "MSFT", high=101, low=99, close=100),
            candle("2026-07-02", "MSFT", high=95, low=90, close=92),
            candle("2026-07-03", "MSFT", high=95.5, low=92, close=94.2),
        ]

        candidates = GapDetector(min_bars=3, proximity_pct=0.01).analyze(pd.DataFrame(rows))

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].gap_type, "resistance")
        self.assertEqual(candidates[0].gap_bottom, 95)
        self.assertEqual(candidates[0].gap_top, 100)
        self.assertTrue(candidates[0].touched)
        self.assertEqual(candidates[0].touch_count, 1)

    def test_filled_gap_is_removed(self):
        rows = [
            candle("2026-07-01", "NVDA", high=101, low=99, close=100),
            candle("2026-07-02", "NVDA", high=110, low=105, close=108),
            candle("2026-07-03", "NVDA", high=109, low=98, close=99),
        ]

        candidates = GapDetector(min_bars=3, proximity_pct=0.05).analyze(pd.DataFrame(rows))

        self.assertEqual(candidates, [])

    def test_latest_close_inside_gap_is_included_as_zero_distance(self):
        rows = [
            candle("2026-07-01", "TSLA", high=101, low=99, close=100),
            candle("2026-07-02", "TSLA", high=110, low=105, close=108),
            candle("2026-07-03", "TSLA", high=108, low=103, close=104),
        ]

        candidates = GapDetector(min_bars=3, proximity_pct=0.01).analyze(pd.DataFrame(rows))

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].distance_pct, 0.0)
        self.assertEqual(candidates[0].metadata["distance_to_gap"], 0.0)

    def test_gap_over_fixed_proximity_is_included_when_within_one_atr(self):
        rows = [
            candle("2026-07-01", "NVDA", high=101, low=99, close=100),
            candle("2026-07-02", "NVDA", high=110, low=105, close=108),
            candle("2026-07-03", "NVDA", high=111, low=105, close=110),
        ]

        candidates = GapDetector(min_bars=3, proximity_pct=0.01).analyze(pd.DataFrame(rows))

        self.assertEqual(len(candidates), 1)
        self.assertGreater(candidates[0].distance_pct, 0.01)
        self.assertLessEqual(candidates[0].distance_pct, candidates[0].atr_pct)
        self.assertTrue(candidates[0].within_one_atr)

    def test_current_day_gap_is_excluded(self):
        rows = [
            candle("2026-07-01", "JXN", high=101, low=99, close=100),
            candle("2026-07-02", "JXN", high=110, low=105, close=105.5),
        ]

        candidates = GapDetector(min_bars=2, proximity_pct=0.01).analyze(pd.DataFrame(rows))

        self.assertEqual(candidates, [])

    def test_average_true_range_includes_gaps_from_previous_close(self):
        rows = [
            candle("2026-07-01", "AAPL", high=101, low=99, close=100),
            candle("2026-07-02", "AAPL", high=110, low=105, close=108),
            candle("2026-07-03", "AAPL", high=108, low=104, close=105.8),
        ]

        self.assertAlmostEqual(average_true_range(pd.DataFrame(rows), period=14), 5.333333333333333)

    def test_touch_count_increments_once_per_respected_day(self):
        rows = [
            candle("2026-07-01", "AAPL", high=101, low=99, close=100),
            candle("2026-07-02", "AAPL", high=110, low=105, close=108),
            candle("2026-07-03", "AAPL", high=108, low=104.5, close=106),
            candle("2026-07-04", "AAPL", high=108, low=104.8, close=105.8),
        ]

        candidates = GapDetector(min_bars=4, proximity_pct=0.01).analyze(pd.DataFrame(rows))

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].touch_count, 2)
        self.assertEqual(candidates[0].metadata["touch_count"], 2)


def candle(date: str, ticker: str, *, high: float, low: float, close: float) -> dict[str, object]:
    return {
        "date": date,
        "ticker": ticker,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "adj_close": close,
        "volume": 1000,
    }


if __name__ == "__main__":
    unittest.main()
