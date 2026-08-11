import unittest
from datetime import datetime, timezone

from stock_gap_detector.discord_bot import (
    REPORT_INLINE_LIMIT,
    extract_ticker_lists_section,
    extract_named_ticker_sections,
    format_channel_messages,
    format_post_title,
    ordinal_day,
    send_report,
)


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

    def test_extract_named_ticker_sections_finds_support_and_resistance_blocks(self):
        sections = extract_named_ticker_sections(
            "\n".join(
                [
                    "## Ticker Lists",
                    "",
                    "Near Support Gaps",
                    "```",
                    "AAPL, MSFT",
                    "```",
                    "",
                    "Near Resistance Gaps",
                    "```",
                    "TSLA, NVDA",
                    "```",
                ]
            )
        )

        self.assertEqual(sections["Near Support Gaps"], "Near Support Gaps\n```\nAAPL, MSFT\n```")
        self.assertEqual(sections["Near Resistance Gaps"], "Near Resistance Gaps\n```\nTSLA, NVDA\n```")

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
                "",
                "Near Resistance Gaps",
                "```",
                "TSLA, NVDA",
                "```",
            ]
        )

        await send_report(channel, report, candidate_count=2, trigger="test")

        self.assertIn("Gap Candidates for", channel.messages[0]["content"])
        self.assertIn("Candidates: `2`", channel.messages[0]["content"])
        self.assertIn("Full report attached.", channel.messages[0]["content"])
        self.assertEqual(channel.messages[0]["file"].filename, "gap_report.txt")
        self.assertEqual(channel.messages[1]["content"], "Near Support Gaps\n```\nAAPL, MSFT\n```")
        self.assertIsNone(channel.messages[1]["file"])
        self.assertEqual(channel.messages[2]["content"], "Near Resistance Gaps\n```\nTSLA, NVDA\n```")
        self.assertIsNone(channel.messages[2]["file"])

    def test_format_channel_messages_posts_support_and_resistance_separately(self):
        messages = format_channel_messages(
            "Header",
            "\n".join(
                [
                    "## Ticker Lists",
                    "",
                    "Near Support Gaps",
                    "```",
                    "AAPL, MSFT",
                    "```",
                    "",
                    "Near Resistance Gaps",
                    "```",
                    "TSLA, NVDA",
                    "```",
                ]
            ),
        )

        self.assertEqual(len(messages), 2)
        self.assertIn("Near Support Gaps", messages[0])
        self.assertNotIn("Near Resistance Gaps", messages[0])
        self.assertEqual(messages[1], "Near Resistance Gaps\n```\nTSLA, NVDA\n```")

    def test_format_channel_messages_splits_oversized_ticker_section(self):
        tickers = ", ".join(f"TICK{i}" for i in range(700))
        messages = format_channel_messages("Header", f"## Ticker Lists\n\nNear Support Gaps\n```\n{tickers}\n```")

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= REPORT_INLINE_LIMIT for message in messages))
        self.assertIn("TICK0", messages[0])
        self.assertIn("TICK699", messages[-1])


class FakeChannel:
    def __init__(self):
        self.messages = []

    async def send(self, content, *, file=None):
        self.messages.append({"content": content, "file": file})


if __name__ == "__main__":
    unittest.main()
