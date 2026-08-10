from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd


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
        """Return active gap zones whose latest close is within the configured distance."""
        if len(candles) < self.min_bars:
            return []

        frame = candles.sort_values("date").reset_index(drop=True)
        active_gaps = self.calculate_active_gaps(ticker, frame)
        if not active_gaps:
            return []

        latest = frame.iloc[-1]
        latest_date = str(latest["date"])
        latest_close = float(latest["close"])
        candidates = []

        for gap in active_gaps:
            if gap.gap_date.isoformat() == latest_date:
                continue

            distance_pct = distance_to_gap_pct(latest_close, gap)
            if distance_pct <= 0 or distance_pct > self.proximity_pct:
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
                    reason=f"latest close is within {self.proximity_pct:.2%} of an active {gap.kind} gap",
                    metadata={
                        "gap_midpoint": round(gap.midpoint, 4),
                        "original_top": round(gap.original_top, 4),
                        "original_bottom": round(gap.original_bottom, 4),
                        "gap_width_pct": gap.width_pct,
                        "distance_pct": distance_pct,
                        "touched": gap.touched,
                    },
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
    else:
        if close >= gap.original_top:
            return None
        if gap.current_bottom < close < gap.original_top:
            gap.current_bottom = close
        if high >= gap.current_bottom:
            gap.touched = True

    return gap


def distance_to_gap_pct(close: float, gap: ActiveGap) -> float:
    if gap.current_bottom <= close <= gap.current_top:
        return 0.0
    if close > gap.current_top:
        return abs(close - gap.current_top) / close
    return abs(gap.current_bottom - close) / close
