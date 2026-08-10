from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date

from stock_gap_detector.config import DATA_DIR, LOG_FILE, REPORT_FILE, RESULTS_FILE, Config
from stock_gap_detector.database import CandleDatabase, latest_completed_trading_day
from stock_gap_detector.detector import GapCandidate, GapDetector


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
    database = CandleDatabase(config.database_url)
    database.healthcheck()

    candles = database.load_recent_candles(
        tickers=config.tickers,
        end_date=end_date,
        lookback_days=config.lookback_days,
    )
    ticker_count = int(candles["ticker"].nunique()) if not candles.empty else 0
    logging.info("Loaded %s candle row(s) for %s ticker(s).", len(candles), ticker_count)

    detector = GapDetector(
        min_bars=config.min_bars,
        proximity_pct=config.proximity_pct,
        gap_limit=config.gap_limit,
        lookback_days=config.lookback_days,
    )
    candidates = detector.analyze(candles)
    write_candidates(candidates)
    logging.info("Detector produced %s candidate(s).", len(candidates))
    return candidates


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


def format_candidate_lines(candidates: list[GapCandidate]) -> list[str]:
    if not candidates:
        return ["No matches."]
    return [
        (
            f"- **{candidate.ticker}** close `{candidate.close:.2f}` is "
            f"`{candidate.distance_pct:.2%}` from {candidate.gap_type} gap "
            f"`{candidate.gap_bottom:.2f}-{candidate.gap_top:.2f}` "
            f"(gap date `{candidate.gap_date}`, touched `{candidate.touched}`)"
        )
        for candidate in sorted(candidates, key=lambda item: (item.distance_pct, item.ticker))
    ]


def format_ticker_list(candidates: list[GapCandidate]) -> str:
    tickers = unique_tickers(candidate.ticker for candidate in sorted(candidates, key=lambda item: item.distance_pct))
    return ", ".join(tickers) if tickers else "No matches."


def unique_tickers(tickers) -> list[str]:
    return list(dict.fromkeys(tickers))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read candle-db candles and run stock gap detection.")
    parser.add_argument("--once", action="store_true", help="Run one detector pass and exit.")
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
