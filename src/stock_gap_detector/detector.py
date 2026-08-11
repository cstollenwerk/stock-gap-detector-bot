from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd


ATR_PERIOD = 14


@dataclass
class ActiveGap:
    ticker: str
    kind: str
    gap_date: date
    original_top: float
    original_bottom: float
    current_top: float
    current_bottom: float
    touched: bool = False
    touch_count: int = 0

    @property
    def up(self) -> bool:
        return self.kind == "support"

    @property
    def midpoint(self) -> float:
        return (self.current_top + self.current_bottom) / 2

    @property
    def width_pct(self) -> float:
        return (self.current_top - self.current_bottom) / self.midpoint if self.midpoint else 0.0


@dataclass(frozen=True)
class GapCandidate:
    ticker: str
    date: str
    close: float
    gap_type: str
    gap_date: str
    gap_top: float
    gap_bottom: float
    distance_pct: float
    touched: bool
    reason: str
    metadata: dict[str, float | int | str | bool]
    theme: str | None = None
    sector: str | None = None
    atr_14: float | None = None
    atr_pct: float | None = None
    within_one_atr: bool = False
    touch_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class GapDetector:
    def __init__(
        self,
        *,
        min_bars: int,
        proximity_pct: float = 0.01,
        gap_limit: int = 50,
        lookback_days: int = 365,
    ) -> None:
        self.min_bars = min_bars
        self.proximity_pct = proximity_pct
        self.gap_limit = gap_limit
        self.lookback_days = lookback_days

    def analyze(self, candles: pd.DataFrame) -> list[GapCandidate]:
        candidates: list[GapCandidate] = []
        if candles.empty:
            return candidates

        for ticker, frame in candles.groupby("ticker", sort=True):
            ticker_candidates = self.analyze_ticker(str(ticker), frame.sort_values("date").copy())
            candidates.extend(ticker_candidates)
        return candidates

    def analyze_ticker(self, ticker: str, candles: pd.DataFrame) -> list[GapCandidate]:
        """Return active gap zones whose latest close is within one 14-day ATR."""
        if len(candles) < self.min_bars:
            return []

        frame = candles.sort_values("date").reset_index(drop=True)
        active_gaps = self.calculate_active_gaps(ticker, frame)
        if not active_gaps:
            return []

        latest = frame.iloc[-1]
        latest_date = str(latest["date"])
        latest_close = float(latest["close"])
        atr_14 = average_true_range(frame, period=ATR_PERIOD)
        atr_pct = atr_14 / latest_close if latest_close and atr_14 is not None else None
        candidates = []

        for gap in active_gaps:
            if gap.gap_date.isoformat() == latest_date:
                continue

            distance_to_gap = distance_to_gap_value(latest_close, gap)
            distance_pct = distance_to_gap / latest_close if latest_close else 0.0
            within_one_atr = atr_14 is not None and distance_to_gap <= atr_14
            if not within_one_atr:
                continue

            candidates.append(
                GapCandidate(
                    ticker=ticker,
                    date=latest_date,
                    close=latest_close,
                    gap_type=gap.kind,
                    gap_date=gap.gap_date.isoformat(),
                    gap_top=round(gap.current_top, 4),
                    gap_bottom=round(gap.current_bottom, 4),
                    distance_pct=distance_pct,
                    touched=gap.touched,
                    reason=f"latest close is within one 14-day ATR of an active {gap.kind} gap",
                    metadata={
                        "gap_midpoint": round(gap.midpoint, 4),
                        "original_top": round(gap.original_top, 4),
                        "original_bottom": round(gap.original_bottom, 4),
                        "gap_width_pct": gap.width_pct,
                        "distance_pct": distance_pct,
                        "distance_to_gap": round(distance_to_gap, 4),
                        "touched": gap.touched,
                        "touch_count": gap.touch_count,
                        "within_one_atr": within_one_atr,
                        **atr_metadata(atr_14, atr_pct),
                    },
                    atr_14=round(atr_14, 4) if atr_14 is not None else None,
                    atr_pct=atr_pct,
                    within_one_atr=within_one_atr,
                    touch_count=gap.touch_count,
                )
            )

        return sorted(candidates, key=lambda candidate: (candidate.distance_pct, candidate.ticker, candidate.gap_date))

    def calculate_active_gaps(self, ticker: str, candles: pd.DataFrame) -> list[ActiveGap]:
        frame = candles.reset_index(drop=True)
        active_gaps: list[ActiveGap] = []
        previous_close: float | None = None

        rows = frame[["date", "high", "low", "close"]].itertuples(index=False, name=None)
        for raw_date, high, low, close in rows:
            current_date = pd.to_datetime(raw_date).date()
            high = float(high)
            low = float(low)
            close = float(close)

            active_gaps = [
                gap
                for gap in (process_gap(gap, current_date, close, high, low, self.lookback_days) for gap in active_gaps)
                if gap is not None
            ]

            if previous_close is not None:
                if low > previous_close:
                    active_gaps.append(
                        ActiveGap(
                            ticker=ticker,
                            kind="support",
                            gap_date=current_date,
                            original_top=low,
                            original_bottom=previous_close,
                            current_top=low,
                            current_bottom=previous_close,
                        )
                    )
                elif high < previous_close:
                    active_gaps.append(
                        ActiveGap(
                            ticker=ticker,
                            kind="resistance",
                            gap_date=current_date,
                            original_top=previous_close,
                            original_bottom=high,
                            current_top=previous_close,
                            current_bottom=high,
                        )
                    )

            if len(active_gaps) > self.gap_limit:
                active_gaps = active_gaps[-self.gap_limit :]

            previous_close = close

        return active_gaps


def process_gap(
    gap: ActiveGap,
    current_date: date,
    close: float,
    high: float,
    low: float,
    lookback_days: int,
) -> ActiveGap | None:
    gap_age_days = (current_date - gap.gap_date).days
    if gap_age_days >= lookback_days:
        return None

    if gap.up:
        if close <= gap.original_bottom:
            return None
        if gap.original_bottom < close < gap.current_top:
            gap.current_top = close
        if low <= gap.current_top:
            gap.touched = True
            gap.touch_count += 1
    else:
        if close >= gap.original_top:
            return None
        if gap.current_bottom < close < gap.original_top:
            gap.current_bottom = close
        if high >= gap.current_bottom:
            gap.touched = True
            gap.touch_count += 1

    return gap


def distance_to_gap_value(close: float, gap: ActiveGap) -> float:
    if gap.current_bottom <= close <= gap.current_top:
        return 0.0
    if close > gap.current_top:
        return abs(close - gap.current_top)
    return abs(gap.current_bottom - close)


def distance_to_gap_pct(close: float, gap: ActiveGap) -> float:
    return distance_to_gap_value(close, gap) / close if close else 0.0


def average_true_range(candles: pd.DataFrame, *, period: int = ATR_PERIOD) -> float | None:
    if candles.empty:
        return None

    frame = candles.sort_values("date").reset_index(drop=True)
    previous_close: float | None = None
    true_ranges: list[float] = []

    for high, low, close in frame[["high", "low", "close"]].itertuples(index=False, name=None):
        high = float(high)
        low = float(low)
        close = float(close)
        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(true_range)
        previous_close = close

    if not true_ranges:
        return None
    return sum(true_ranges[-period:]) / min(period, len(true_ranges))


def atr_metadata(atr_14: float | None, atr_pct: float | None) -> dict[str, float]:
    if atr_14 is None or atr_pct is None:
        return {}
    return {"atr_14": round(atr_14, 4), "atr_pct": atr_pct}
