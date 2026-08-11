from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import replace
from datetime import date

from stock_gap_detector.config import DATA_DIR, LOG_FILE, REPORT_FILE, RESULTS_FILE, Config, DiscordConfig
from stock_gap_detector.database import CandleDatabase, latest_completed_trading_day
from stock_gap_detector.detector import GapCandidate, GapDetector


MIN_ATR_PCT = 0.05
MIN_MARKET_CAP = 1_000_000_000


def configure_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )


def run_once(config: Config, *, end_date: date | None = None) -> list[GapCandidate]:
    run_started_at = time.perf_counter()
    database = CandleDatabase(config.database_url)

    load_started_at = time.perf_counter()
    candles = database.load_recent_candles(
        tickers=config.tickers,
        end_date=end_date,
        lookback_days=config.lookback_days,
        min_atr_pct=MIN_ATR_PCT if not config.tickers else None,
        min_market_cap=MIN_MARKET_CAP,
    )
    ticker_count = int(candles["ticker"].nunique()) if not candles.empty else 0
    logging.info(
        "Loaded %s candle row(s) for %s ticker(s) in %.2fs.",
        len(candles),
        ticker_count,
        time.perf_counter() - load_started_at,
    )

    detector = GapDetector(
        min_bars=config.min_bars,
        proximity_pct=config.proximity_pct,
        gap_limit=config.gap_limit,
        lookback_days=config.lookback_days,
    )
    analyze_started_at = time.perf_counter()
    candidates = detector.analyze(candles)
    logging.info("Analyzed candles in %.2fs.", time.perf_counter() - analyze_started_at)

    filter_started_at = time.perf_counter()
    before_touch_filter = len(candidates)
    candidates = filter_touched_candidates(candidates)
    logging.info("Dropped %s untouched candidate(s).", before_touch_filter - len(candidates))
    before_atr_filter = len(candidates)
    candidates = filter_min_atr_pct(candidates)
    logging.info("Dropped %s candidate(s) below %.2f%% ATR.", before_atr_filter - len(candidates), MIN_ATR_PCT * 100)
    logging.info("Filtered candidates in %.2fs.", time.perf_counter() - filter_started_at)

    metadata_started_at = time.perf_counter()
    candidates = add_group_metadata(candidates, database)
    logging.info("Loaded candidate group metadata in %.2fs.", time.perf_counter() - metadata_started_at)

    write_started_at = time.perf_counter()
    write_candidates(candidates)
    logging.info("Wrote report files in %.2fs.", time.perf_counter() - write_started_at)
    logging.info("Detector produced %s candidate(s).", len(candidates))
    logging.info("Detector run completed in %.2fs.", time.perf_counter() - run_started_at)
    return candidates


def filter_touched_candidates(candidates: list[GapCandidate]) -> list[GapCandidate]:
    return [candidate for candidate in candidates if candidate.touched]


def filter_min_atr_pct(candidates: list[GapCandidate], min_atr_pct: float = MIN_ATR_PCT) -> list[GapCandidate]:
    return [candidate for candidate in candidates if candidate.atr_pct is not None and candidate.atr_pct >= min_atr_pct]


def add_group_metadata(candidates: list[GapCandidate], database: CandleDatabase) -> list[GapCandidate]:
    tickers = sorted({candidate.ticker for candidate in candidates})
    ticker_groups = database.load_ticker_groups(tickers)
    return [
        replace(candidate, theme=group.theme, sector=group.sector) if (group := ticker_groups.get(candidate.ticker)) else candidate
        for candidate in candidates
    ]


def write_candidates(candidates: list[GapCandidate]) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "candidate_count": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    RESULTS_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_FILE.write_text(format_report(candidates), encoding="utf-8")
    logging.info("Wrote %s.", RESULTS_FILE)
    logging.info("Wrote %s.", REPORT_FILE)


def run_report_for_discord(config: Config) -> tuple[str, int]:
    candidates = run_once(config)
    return format_report(candidates), len(candidates)


def format_report(candidates: list[GapCandidate]) -> str:
    if not candidates:
        return "# Stock Gap Detector\n\nNo stocks are currently near active support or resistance gaps.\n"

    support = [candidate for candidate in candidates if candidate.gap_type == "support"]
    resistance = [candidate for candidate in candidates if candidate.gap_type == "resistance"]
    latest_date = max(candidate.date for candidate in candidates)
    lines = [
        "# Stock Gap Detector",
        "",
        f"Latest close date: {latest_date}",
        "",
        "## Sector Breakdown",
        "",
        *format_sector_breakdown(candidates),
        "",
        "## Near Support Gaps",
        "",
        *format_candidate_lines(support),
        "",
        "## Near Resistance Gaps",
        "",
        *format_candidate_lines(resistance),
        "",
        "## Ticker Lists",
        "",
        "Near Support Gaps",
        "```",
        format_ticker_list(support),
        "```",
        "",
        "Near Resistance Gaps",
        "```",
        format_ticker_list(resistance),
        "```",
        "",
    ]
    return "\n".join(lines)


def format_sector_breakdown(candidates: list[GapCandidate]) -> list[str]:
    buckets: dict[str, list[GapCandidate]] = defaultdict(list)
    for candidate in candidates:
        buckets[sector_label(candidate)].append(candidate)

    lines: list[str] = []
    for label, group_candidates in sorted(buckets.items(), key=lambda item: group_sort_key(item[0], item[1])):
        support_count = sum(1 for candidate in group_candidates if candidate.gap_type == "support")
        resistance_count = sum(1 for candidate in group_candidates if candidate.gap_type == "resistance")
        net_count = support_count - resistance_count
        lines.extend(
            [
                f"### {label} (net {net_count:+d}, support {support_count}, resistance {resistance_count})",
                "",
                *format_candidate_lines(group_candidates),
                "",
            ]
        )
    return lines[:-1] if lines else ["No matches."]


def sector_label(candidate: GapCandidate) -> str:
    return candidate.sector or "Unmapped"


def group_sort_key(label: str, candidates: list[GapCandidate]) -> tuple[int, int, int, float, str]:
    support_count = sum(1 for candidate in candidates if candidate.gap_type == "support")
    resistance_count = sum(1 for candidate in candidates if candidate.gap_type == "resistance")
    net_count = support_count - resistance_count
    touch_count = sum(candidate.touch_count for candidate in candidates)
    average_distance = sum(candidate.distance_pct for candidate in candidates) / len(candidates)
    return (-net_count, -touch_count, -support_count, resistance_count, average_distance, label)


def format_candidate_lines(candidates: list[GapCandidate]) -> list[str]:
    if not candidates:
        return ["No matches."]
    return [
        (
            f"- **{candidate.ticker}** close `{candidate.close:.2f}` is "
            f"`{candidate.distance_pct:.2%}` from {candidate.gap_type} gap "
            f"`{candidate.gap_bottom:.2f}-{candidate.gap_top:.2f}` "
            f"(gap date `{candidate.gap_date}`, touches `{candidate.touch_count}`{format_atr_flag(candidate)})"
        )
        for candidate in sorted(candidates, key=candidate_sort_key)
    ]


def candidate_sort_key(candidate: GapCandidate) -> tuple[int, float, str, str]:
    return (-candidate.touch_count, candidate.distance_pct, candidate.ticker, candidate.gap_date)


def format_atr_flag(candidate: GapCandidate) -> str:
    if candidate.atr_pct is None:
        return ""
    within_label = "yes" if candidate.within_one_atr else "no"
    return f", 1ATR `{within_label}`, ATR14% `{candidate.atr_pct:.2%}`"


def format_ticker_list(candidates: list[GapCandidate]) -> str:
    tickers = unique_tickers(candidate.ticker for candidate in sorted(candidates, key=candidate_sort_key))
    return ", ".join(tickers) if tickers else "No matches."


def unique_tickers(tickers) -> list[str]:
    return list(dict.fromkeys(tickers))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read candle-db candles and run stock gap detection.")
    parser.add_argument("--once", action="store_true", help="Run one detector pass and exit.")
    parser.add_argument("--loop", action="store_true", help="Run the legacy interval worker without Discord.")
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Override the latest completed trading day with YYYY-MM-DD.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging()
    config = Config.from_env()

    if args.once:
        run_once(config, end_date=args.end_date)
        return

    if not args.loop:
        if args.end_date is not None:
            raise RuntimeError("--end-date is only supported with --once or --loop.")
        from stock_gap_detector.discord_bot import run_discord_bot

        discord_config = DiscordConfig.from_env()
        logging.info(
            "Starting Discord bot. Scheduled report time: %s Eastern. Channel: %s.",
            discord_config.report_time.strftime("%H:%M"),
            discord_config.channel_id,
        )
        run_discord_bot(discord_config, lambda: run_report_for_discord(config))
        return

    logging.info(
        "Starting stock gap detector loop. Interval: %s minute(s). Latest completed session: %s.",
        config.run_interval_minutes,
        latest_completed_trading_day().isoformat(),
    )
    while True:
        try:
            run_once(config, end_date=args.end_date)
        except Exception as exc:
            logging.exception("Detector run failed: %s", exc)
        time.sleep(config.run_interval_minutes * 60)


if __name__ == "__main__":
    main()
