# Stock Gap Detector Bot

Discord bot for reading daily candle data from the same candle-db used by
`market-overwatch` and posting a stock gap report.

The detector currently loads active tickers and OHLCV rows from Postgres, then
passes each ticker's candle history through the active gap detector. The bot
posts the report every day at 8:00 PM Eastern and exposes `/gapreport` to run it
manually.

## Environment

Create a `.env` file from `.env.example`:

```env
STOCK_GAP_DETECTOR_DB_HOST=localhost
STOCK_GAP_DETECTOR_DB_PORT=5432
STOCK_GAP_DETECTOR_DB_NAME=candle_db
STOCK_GAP_DETECTOR_DB_USER=candle_user
STOCK_GAP_DETECTOR_DB_PASSWORD=put_the_password_here

STOCK_GAP_DETECTOR_DISCORD_TOKEN=put_the_discord_bot_token_here
STOCK_GAP_DETECTOR_DISCORD_CHANNEL_ID=123456789012345678

# Optional, but useful while developing because guild slash commands sync faster.
STOCK_GAP_DETECTOR_DISCORD_GUILD_ID=123456789012345678

STOCK_GAP_DETECTOR_LOOKBACK_DAYS=365
STOCK_GAP_DETECTOR_MIN_BARS=60
STOCK_GAP_DETECTOR_GAP_LIMIT=50
```

You can also use `STOCK_GAP_DETECTOR_CANDLE_DB_URL` instead of the separate DB
fields. If the separate DB fields are present, they take priority over the URL.
The URL setting also falls back to `CANDLE_DB_DATABASE_URL`,
`MARKET_OVERWATCH_CANDLE_DB_URL`, and `DATABASE_URL`.

If `STOCK_GAP_DETECTOR_DB_NAME`, `STOCK_GAP_DETECTOR_DB_USER`, and
`STOCK_GAP_DETECTOR_DB_PASSWORD` are set but `STOCK_GAP_DETECTOR_DB_HOST` is
omitted, the bot assumes `localhost`.

Optional ticker filter:

```env
STOCK_GAP_DETECTOR_TICKERS=AAPL,MSFT,NVDA
```

## Run With Docker

```bash
docker compose up -d --build
```

From inside Docker, use `host.docker.internal` when candle-db publishes Postgres
on the host machine. Use `localhost` when running the bot directly on the same
host as Postgres.

## Run Locally

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m stock_gap_detector.main
```

For a one-time detector run without Discord:

```bash
python -m stock_gap_detector.main --once
```

For the older interval worker without Discord:

```bash
python -m stock_gap_detector.main --loop
```

## Discord

Create a Discord application and bot token, invite the bot to your server, and
set `STOCK_GAP_DETECTOR_DISCORD_TOKEN` plus
`STOCK_GAP_DETECTOR_DISCORD_CHANNEL_ID` in `.env`.

Discord posts show the ticker-list section in the channel with a dated title,
and attach the full report as `gap_report.txt` for the sector breakdown and
candidate details.

The bot registers a `/gapreport` slash command. If
`STOCK_GAP_DETECTOR_DISCORD_GUILD_ID` is set, the command syncs to that server
quickly; without it, the command is registered globally and Discord may take
longer to show it.

## Output

Each run writes detector results to:

```text
data/gap_candidates.json
data/gap_report.md
```

The detector calculates active gap-up support zones and gap-down resistance
zones using the TradingView logic in the supplied Daily Gaps script. A ticker is
included when its latest close is within the stored 14-day ATR of a touched active
gap, and the report output keeps only candidates with stored `ATR14% >= 5%`.

Here is the install link:
https://discord.com/oauth2/authorize?client_id=1536559237512302672&permissions=35840&integration_type=0&scope=bot+applications.commands
