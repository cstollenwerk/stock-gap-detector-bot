from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from io import BytesIO
from typing import Callable

import discord
from discord import app_commands
from discord.ext import tasks

from stock_gap_detector.config import EASTERN_TZ, DiscordConfig, REPORT_FILE


REPORT_INLINE_LIMIT = 1800
TICKER_LISTS_HEADER = "## Ticker Lists"
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
            await send_report(channel, report_text, candidate_count, trigger)
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


async def send_report(channel, report_text: str, candidate_count: int, trigger: str) -> None:
    header = f"**{format_post_title()}** ({trigger})\nCandidates: `{candidate_count}`"
    ticker_lists = extract_ticker_lists_section(report_text)
    message = format_channel_message(header, ticker_lists)
    payload = BytesIO(report_text.encode("utf-8"))
    await channel.send(
        message,
        file=discord.File(payload, filename=REPORT_FILE.with_suffix(".txt").name),
    )


def extract_ticker_lists_section(report_text: str) -> str:
    _, separator, ticker_lists = report_text.partition(TICKER_LISTS_HEADER)
    if not separator:
        return report_text.strip()
    return f"{TICKER_LISTS_HEADER}{ticker_lists}".strip()


def format_channel_message(header: str, ticker_lists: str) -> str:
    message = f"{header}\n\n{ticker_lists}"
    if len(message) <= REPORT_INLINE_LIMIT:
        return message
    return f"{header}\n\nTicker lists are attached because they are too long for one Discord message."


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
