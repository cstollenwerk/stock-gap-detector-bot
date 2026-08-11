import unittest
from datetime import datetime, timezone

from stock_gap_detector.discord_bot import extract_ticker_lists_section, format_post_title, ordinal_day, send_report


class DiscordReportTests(unittest.IsolatedAsyncioTestCase):
    def test_format_post_title_includes_eastern_post_date(self):
        title = format_post_title(datetime(2026, 4, 17, 23, 0, tzinfo=timezone.utc))

        self.assertEqual(title, "Gap Candidates for Friday April 17th, 2026")

    def test_ordinal_day_formats_suffixes(self):
        self.assertEqual(ordinal_day(1), "1st")
        self.assertEqual(ordinal_day(2), "2nd")
        self.assertEqual(ordinal_day(3), "3rd")
        self.assertEqual(ordinal_day(11), "11th")
        self.assertEqual(ordinal_day(22), "22nd")

    def test_extract_ticker_lists_section_returns_everything_after_header(self):
        report = "\n".join(
            [
                "# Stock Gap Detector",
                "",
                "## Sector Breakdown",
                "",
                "details",
                "",
                "## Ticker Lists",
                "",
                "Near Support Gaps",
                "```",
                "AAPL, MSFT",
                "```",
            ]
        )

        self.assertEqual(
            extract_ticker_lists_section(report),
            "## Ticker Lists\n\nNear Support Gaps\n```\nAAPL, MSFT\n```",
        )

    async def test_send_report_posts_ticker_lists_and_attaches_full_txt_report(self):
        channel = FakeChannel()
        report = "\n".join(
            [
                "# Stock Gap Detector",
                "",
                "## Sector Breakdown",
                "",
                "full breakdown",
                "",
                "## Ticker Lists",
                "",
                "Near Support Gaps",
                "```",
                "AAPL, MSFT",
                "```",
            ]
        )

        await send_report(channel, report, candidate_count=2, trigger="test")

        self.assertIn("Gap Candidates for", channel.content)
        self.assertNotIn("full breakdown", channel.content)
        self.assertIn("## Ticker Lists", channel.content)
        self.assertIn("AAPL, MSFT", channel.content)
        self.assertEqual(channel.file.filename, "gap_report.txt")


class FakeChannel:
    def __init__(self):
        self.content = ""
        self.file = None

    async def send(self, content, *, file=None):
        self.content = content
        self.file = file


if __name__ == "__main__":
    unittest.main()
