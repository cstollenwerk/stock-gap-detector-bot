# Stock Gap Detector Bot

Base worker for reading daily candle data from the same candle-db used by
`market-overwatch`.

The detector currently loads active tickers and OHLCV rows from Postgres, then
passes each ticker's candle history through a small analysis hook. Add your gap,
support, and resistance logic in `src/stock_gap_detector/detector.py`.

## Environment

Create a `.env` file from `.env.example`:

```env
STOCK_GAP_DETECTOR_DB_HOST=pi-server.local
STOCK_GAP_DETECTOR_DB_PORT=5432
STOCK_GAP_DETECTOR_DB_NAME=candle_db
STOCK_GAP_DETECTOR_DB_USER=candle_user
STOCK_GAP_DETECTOR_DB_PASSWORD=put_the_password_here

STOCK_GAP_DETECTOR_LOOKBACK_DAYS=365
STOCK_GAP_DETECTOR_PROXIMITY_PCT=0.01
STOCK_GAP_DETECTOR_RUN_INTERVAL_MINUTES=1440
```

You can also use `STOCK_GAP_DETECTOR_CANDLE_DB_URL` instead of the separate DB
fields. If the separate DB fields are present, they take priority over the URL.
The URL setting also falls back to `CANDLE_DB_DATABASE_URL`,
`MARKET_OVERWATCH_CANDLE_DB_URL`, and `DATABASE_URL`.

Optional ticker filter:

```env
STOCK_GAP_DETECTOR_TICKERS=AAPL,MSFT,NVDA
```

## Run With Docker

```bash
docker compose up -d --build
```

From inside Docker, use `host.docker.internal` when candle-db publishes Postgres
on the host machine.

## Run Locally

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m stock_gap_detector.main --once
```

## Output

Each run writes detector results to:

```text
data/gap_candidates.json
data/gap_report.md
```

The detector calculates active gap-up support zones and gap-down resistance
zones using the TradingView logic in the supplied Daily Gaps script. A ticker is
included when its latest close is within `STOCK_GAP_DETECTOR_PROXIMITY_PCT` of
an active gap.
