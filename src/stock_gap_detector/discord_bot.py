from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from io import BytesIO
from typing import Callable

import discord
from discord import app_commands
from discord.ext import tasks

from stock_gap_detector.config import EASTERN_TZ, REPORT_FILE, DiscordConfig


REPORT_INLINE_LIMIT = 1800
TICKER_LISTS_HEADER = "## Ticker Lists"
TICKER_LIST_LABELS = ("Near Support Gaps", "Near Resistance Gaps")
ReportRunner = Callable[[], tuple[str, int]]


class StockGapDiscordBot(discord.Client):
    def __init__(self, discord_config: DiscordConfig, report_runner: ReportRunner) -> None:
        super().__init__(intents=discord.Intents.default())
        self.discord_config = discord_config
        self.report_runner = report_runner
        self.tree = app_commands.CommandTree(self)
        self.report_lock = asyncio.Lock()
        self.daily_report.change_interval(time=discord_config.report_time)

    async def setup_hook(self) -> None:
        command = build_gapreport_command(self, self.discord_config.command_name)
        if self.discord_config.guild_id:
            guild = discord.Object(id=self.discord_config.guild_id)
            self.tree.add_command(command, guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("Synced /%s command to guild %s.", self.discord_config.command_name, guild.id)
        else:
            self.tree.add_command(command)
            await self.tree.sync()
            logging.info("Synced global /%s command.", self.discord_config.command_name)

        if not self.daily_report.is_running():
            self.daily_report.start()

    async def on_ready(self) -> None:
        logging.info(
            "Discord bot connected as %s. Posting reports to channel %s.",
            self.user,
            self.discord_config.channel_id,
        )

    @tasks.loop()
    async def daily_report(self) -> None:
        await self.run_and_post_report(trigger="scheduled")

    @daily_report.before_loop
    async def before_daily_report(self) -> None:
        await self.wait_until_ready()

    async def handle_manual_report(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await self.run_and_post_report(trigger=f"manual run requested by {interaction.user}")
        except Exception as exc:
            logging.exception("Manual Discord report failed: %s", exc)
            await interaction.followup.send(f"Report run failed: `{exc}`", ephemeral=True)
            return

        await interaction.followup.send(message, ephemeral=True)

    async def run_and_post_report(self, *, trigger: str) -> str:
        async with self.report_lock:
            report_text, candidate_count = await asyncio.to_thread(self.report_runner)
            channel = await self.resolve_report_channel()
            await send_report(
                channel,
                report_text,
                candidate_count,
                trigger,
                attach_full_report=self.discord_config.attach_full_report,
            )
            logging.info("Posted %s report with %s candidate(s).", trigger, candidate_count)
            return f"Posted the stock gap report to <#{self.discord_config.channel_id}> with {candidate_count} candidate(s)."

    async def resolve_report_channel(self):
        channel = self.get_channel(self.discord_config.channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.discord_config.channel_id)
        if not hasattr(channel, "send"):
            raise RuntimeError(f"Configured Discord channel {self.discord_config.channel_id} cannot receive messages.")
        return channel


def build_gapreport_command(bot: StockGapDiscordBot, command_name: str) -> app_commands.Command:
    @app_commands.command(name=command_name, description="Run the stock gap detector report now.")
    async def gapreport(interaction: discord.Interaction) -> None:
        await bot.handle_manual_report(interaction)

    return gapreport


async def send_report(
    channel,
    report_text: str,
    candidate_count: int,
    trigger: str,
    *,
    attach_full_report: bool = False,
) -> None:
    _ = candidate_count
    _ = trigger
    header = f"# {format_post_title()}"
    ticker_lists = extract_ticker_lists_section(report_text)
    if attach_full_report:
        await channel.send(
            header,
            file=discord.File(BytesIO(report_text.encode("utf-8")), filename=REPORT_FILE.with_suffix(".txt").name),
        )
    else:
        await channel.send(header)

    for message in format_ticker_list_messages(ticker_lists):
        await channel.send(message)


def extract_ticker_lists_section(report_text: str) -> str:
    _, separator, ticker_lists = report_text.partition(TICKER_LISTS_HEADER)
    if not separator:
        return report_text.strip()
    return f"{TICKER_LISTS_HEADER}{ticker_lists}".strip()


def format_channel_messages(header: str, ticker_lists: str) -> list[str]:
    section_messages = format_ticker_list_messages(ticker_lists)
    first_message = f"{header}\n\n{section_messages[0]}"
    if len(first_message) <= REPORT_INLINE_LIMIT:
        return [first_message, *section_messages[1:]]

    first_limit = REPORT_INLINE_LIMIT - len(header) - 2
    chunks = split_message(section_messages[0], first_limit)
    messages = [f"{header}\n\n{chunks[0]}"]
    messages.extend(chunks[1:])
    messages.extend(section_messages[1:])
    return messages


def format_ticker_list_messages(ticker_lists: str) -> list[str]:
    sections = extract_named_ticker_sections(ticker_lists)
    if not sections:
        return split_message(ticker_lists)

    messages: list[str] = []
    for label in TICKER_LIST_LABELS:
        tickers = sections.get(label)
        if tickers is None:
            continue
        section = format_ticker_section(label, tickers)
        messages.extend(split_message(section))
    return messages or split_message(ticker_lists)


def extract_named_ticker_sections(ticker_lists: str) -> dict[str, str]:
    lines = ticker_lists.splitlines()
    sections: dict[str, str] = {}
    for index, line in enumerate(lines):
        label = line.strip()
        if label not in TICKER_LIST_LABELS:
            continue

        end_index = len(lines)
        for next_index in range(index + 1, len(lines)):
            if lines[next_index].strip() in TICKER_LIST_LABELS:
                end_index = next_index
                break
        sections[label] = extract_code_block_text(lines[index + 1 : end_index])
    return sections


def extract_code_block_text(lines: list[str]) -> str:
    ticker_lines = [line.strip() for line in lines if line.strip() and line.strip() != "```"]
    return " ".join(ticker_lines) if ticker_lines else "No matches."


def format_ticker_section(label: str, tickers: str) -> str:
    ticker_count = count_tickers(tickers)
    return "\n".join(
        [
            f"## {label} `{ticker_count}`",
            "",
            "```",
            tickers,
            "```",
        ]
    )


def count_tickers(tickers: str) -> int:
    if tickers == "No matches.":
        return 0
    return len([ticker for ticker in tickers.split(",") if ticker.strip()])


def split_message(text: str, limit: int = REPORT_INLINE_LIMIT) -> list[str]:
    if limit < 1:
        raise ValueError("Message chunk limit must be at least 1.")

    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        remaining = line
        while True:
            available = limit - len(current) - (1 if current else 0)
            if available < 1:
                chunks.append(current)
                current = ""
                available = limit

            part, remaining = split_line_for_available_space(remaining, available)
            candidate = part if not current else f"{current}\n{part}"
            if len(candidate) <= limit:
                current = candidate
            else:
                chunks.append(current)
                current = part

            if not remaining:
                break
            chunks.append(current)
            current = ""

    if current:
        chunks.append(current)
    return chunks or [""]


def split_line_for_available_space(line: str, available: int) -> tuple[str, str]:
    if len(line) <= available:
        return line, ""
    if ", " not in line:
        return line[:available], line[available:]

    split_at = line.rfind(", ", 0, available + 1)
    if split_at <= 0:
        return line[:available], line[available:]
    return line[:split_at], line[split_at + 2 :]


def format_post_title(now: datetime | None = None) -> str:
    post_time = now.astimezone(EASTERN_TZ) if now else datetime.now(EASTERN_TZ)
    return f"Gap Candidates for {post_time.strftime('%A %B')} {ordinal_day(post_time.day)}, {post_time.year}"


def ordinal_day(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def run_discord_bot(discord_config: DiscordConfig, report_runner: ReportRunner) -> None:
    bot = StockGapDiscordBot(discord_config, report_runner)
    bot.run(discord_config.token)
