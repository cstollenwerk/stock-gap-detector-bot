import unittest

from stock_gap_detector.detector import GapCandidate
from stock_gap_detector.main import filter_min_atr_pct, filter_touched_candidates, format_report


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

    def test_report_breaks_down_candidates_by_larger_group_strength(self):
        report = format_report(
            [
                candidate("NVDA", "support", 0.004, sector="AI Infrastructure", theme="MAG 7"),
                candidate("VRT", "support", 0.002, sector="AI Infrastructure", theme="DATA CENTER COOLING"),
                candidate("AES", "resistance", 0.001, sector="Power & Utilities", theme="UTILITIES"),
                candidate("NEE", "resistance", 0.003, sector="Power & Utilities", theme="UTILITIES"),
            ]
        )

        ai_position = report.index("### AI Infrastructure")
        utilities_position = report.index("### Power & Utilities")

        self.assertLess(ai_position, utilities_position)
        self.assertIn("- **VRT** close `100.00` is `0.20%` from support gap", report)
        self.assertIn("### AI Infrastructure (net +2, support 2, resistance 0)", report)
        self.assertIn("### Power & Utilities (net -2, support 0, resistance 2)", report)

    def test_filter_touched_candidates_drops_untouched_gaps(self):
        candidates = [
            candidate("VRT", "support", 0.002, touched=True),
            candidate("ACA", "support", 0.005, touched=False),
        ]

        self.assertEqual([candidate.ticker for candidate in filter_touched_candidates(candidates)], ["VRT"])

    def test_filter_min_atr_pct_drops_low_atr_candidates(self):
        candidates = [
            candidate("VRT", "support", 0.002, atr_pct=0.05),
            candidate("PSA", "support", 0.003, atr_pct=0.0263),
            candidate("ACA", "support", 0.004, atr_pct=None),
        ]

        self.assertEqual([candidate.ticker for candidate in filter_min_atr_pct(candidates)], ["VRT"])

    def test_report_includes_atr_flag_when_available(self):
        report = format_report([candidate("VRT", "support", 0.002, atr_pct=0.0425, within_one_atr=True)])

        self.assertIn("1ATR `yes`, ATR14% `4.25%`", report)

    def test_report_orders_candidates_by_touch_count_before_distance(self):
        report = format_report(
            [
                candidate("NVDA", "support", 0.001, touch_count=1),
                candidate("VRT", "support", 0.004, touch_count=3),
            ]
        )

        self.assertLess(report.index("**VRT**"), report.index("**NVDA**"))
        self.assertIn("touches `3`", report)


def candidate(
    ticker: str,
    gap_type: str,
    distance_pct: float,
    *,
    sector: str | None = None,
    theme: str | None = None,
    atr_14: float | None = None,
    atr_pct: float | None = None,
    within_one_atr: bool = False,
    touched: bool = True,
    touch_count: int = 0,
) -> GapCandidate:
    return GapCandidate(
        ticker=ticker,
        date="2026-08-10",
        close=100.0,
        gap_type=gap_type,
        gap_date="2026-08-01",
        gap_top=101.0,
        gap_bottom=99.0,
        distance_pct=distance_pct,
        touched=touched,
        reason="test",
        metadata={},
        theme=theme,
        sector=sector,
        atr_14=atr_14,
        atr_pct=atr_pct if atr_pct is not None else atr_14 / 100 if atr_14 is not None else None,
        within_one_atr=within_one_atr,
        touch_count=touch_count,
    )


if __name__ == "__main__":
    unittest.main()
