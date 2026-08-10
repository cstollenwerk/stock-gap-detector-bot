import unittest

from stock_gap_detector.detector import GapCandidate
from stock_gap_detector.main import format_report


class ReportTests(unittest.TestCase):
    def test_report_includes_ticker_lists(self):
        report = format_report(
            [
                candidate("FCN", "support", 0.004),
                candidate("JKHY", "support", 0.003),
                candidate("DX", "resistance", 0.002),
                candidate("ULS", "resistance", 0.005),
            ]
        )

        self.assertIn("Near Support Gaps\n```\nJKHY, FCN\n```", report)
        self.assertIn("Near Resistance Gaps\n```\nDX, ULS\n```", report)


def candidate(ticker: str, gap_type: str, distance_pct: float) -> GapCandidate:
    return GapCandidate(
        ticker=ticker,
        date="2026-08-10",
        close=100.0,
        gap_type=gap_type,
        gap_date="2026-08-01",
        gap_top=101.0,
        gap_bottom=99.0,
        distance_pct=distance_pct,
        touched=True,
        reason="test",
        metadata={},
    )


if __name__ == "__main__":
    unittest.main()
