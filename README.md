# Bluesky Scryfall Bot

[![CI](https://github.com/tayasteere/blueskyscryfallbot/actions/workflows/ci.yml/badge.svg)](https://github.com/tayasteere/blueskyscryfallbot/actions/workflows/ci.yml)

A Bluesky bot that looks up Magic: The Gathering cards via the [Scryfall API](https://scryfall.com/docs/api) and replies with card details, prices, rulings, legality, or card images.

## Usage

Mention the bot in any Bluesky post with card names wrapped in double brackets:

```
@scryfallbot.bsky.social [[Lightning Bolt]]
```

### Query syntax

| Prefix | Mode | Example |
|--------|------|---------|
| *(none)* | Card text + image | `[[Lightning Bolt]]` |
| `!` | Image only | `[[!Lightning Bolt]]` |
| `$` | Prices (USD, EUR, MTGO TIX) | `[[$Lightning Bolt]]` |
| `?` | Official rulings | `[[?Lightning Bolt]]` |
| `#` | Format legalities | `[[#Lightning Bolt]]` |
| `*` | Random card (text + image) | `[[*]]` |

You can pin a specific printing using set code and collector number:

```
[[Lightning Bolt|lea]]          ← by set code
[[Lightning Bolt|lea|62]]       ← by set code + collector number
```

Up to **4 cards** can be looked up per mention. Additional cards require a separate mention.

## Setup

### Prerequisites

- Python 3.11+
- A Bluesky account and an [app password](https://bsky.app/settings/app-passwords)

### Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### Configure

Set the following environment variables:

```
BLUESKY_HANDLE=yourbot.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
SCRYFALL_USER_AGENT=YourBotName/1.0
```

`SCRYFALL_USER_AGENT` identifies your bot to Scryfall. Use a unique name — Scryfall tracks usage per user agent, so running multiple bots with the same string conflates their traffic.

### Run

```bash
python -m bot.main
```

The bot polls for new mentions every 5 seconds. On first run it skips all pre-existing notifications; on subsequent runs it resumes from `state.json` in the project root.

## Deployment

### Docker (recommended)

Build and run with Docker Compose:

```bash
touch state.json   # ensure the state file exists before mounting
docker compose up -d
```

Create a `.env` file in the project root with your credentials:

```
BLUESKY_HANDLE=yourbot.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
SCRYFALL_USER_AGENT=YourBotName/1.0
```

`state.json` is mounted from the host so it survives container restarts. `config.toml` is mounted read-only; edit it on the host and restart the container to apply changes.

To rebuild after a code change:

```bash
docker compose up -d --build
```

### systemd (Linux)

For a VPS without Docker, create `/etc/systemd/system/scryfallbot.service`:

```ini
[Unit]
Description=Bluesky Scryfall Bot
After=network.target

[Service]
User=scryfallbot
WorkingDirectory=/opt/scryfallbot
EnvironmentFile=/opt/scryfallbot/.env
ExecStart=/opt/scryfallbot/.venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
systemctl daemon-reload
systemctl enable --now scryfallbot
journalctl -fu scryfallbot   # follow logs
```

### AWS

The bot emits metrics in [CloudWatch Embedded Metric Format](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatchEmbedded_Metrics_Format.html). On EC2 with the [CloudWatch agent](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Install-CloudWatch-Agent.html) configured to collect stdout, metrics are ingested automatically with no extra code. The Docker image works on EC2 as-is.

## Configuration

Bot behaviour can be tuned by placing a `config.toml` file in the project root. All keys are optional — omitting a key uses the default shown below.

```toml
[bot]
poll_interval_seconds = 5   # how often to check for new mentions
max_cards_per_mention = 4   # maximum cards looked up in a single mention
metrics_enabled = true      # set to false to disable metric output

[rate_limiting]
window_seconds = 60              # length of the rate limit window
max_mentions_per_window = 5      # mentions allowed per user per window
violation_window_seconds = 600   # window over which violations are counted
violations_before_warning = 3    # violations before a warning reply is sent
violations_before_block = 5      # violations before the user is blocked
```

If no `config.toml` is present the defaults above are used.

## Abuse prevention

The bot tracks mentions per user and enforces a rate limit to prevent spam.

- **Rate limiting** — each user may send up to 5 mentions per 60-second window. Mentions beyond this are silently dropped.
- **Warnings** — after 3 rate limit violations within a 10-minute window, the user receives a single warning reply.
- **Blocking** — after 5 violations, the user is permanently blocked via the Bluesky API. Blocks persist across restarts; the bot fetches the existing block list from Bluesky on startup.

All thresholds are configurable via `config.toml`.

## Development

Install dev dependencies:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
pytest --cov=bot  # with coverage
```

Lint:

```bash
ruff check src tests
```

## Project structure

```
src/bot/
  main.py           — entry point, wires up dependencies
  bot.py            — poll loop and mention processing logic
  bluesky_client.py — atproto wrapper (auth, notifications, replies, blocks)
  card_lookup.py    — Scryfall API client with rate limiting
  card_formatter.py — formats card data into reply text
  query_parser.py   — parses [[card]] syntax from post text
  rate_limiter.py   — per-user rate limiting and block decisions
  config.py         — configuration dataclasses and config.toml loader
  metrics.py        — lightweight metric recording
```

## License

Copyright 2026 Taya Steere. Licensed under the [Apache License, Version 2.0](LICENSE).

## Metrics

The bot emits metrics in [CloudWatch Embedded Metric Format (EMF)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatchEmbedded_Metrics_Format.html) — structured JSON written to stdout. On AWS (Lambda or EC2 with the CloudWatch agent), these are automatically ingested as CloudWatch metrics. Outside of AWS they appear as JSON log lines and are otherwise harmless.

Metrics can be disabled by setting `metrics_enabled = false` in `config.toml`.

### Metric events

| Metric | Description |
|---|---|
| `MentionProcessed` | A mention containing at least one card query was processed |
| `CardLookup` | A card was looked up; includes `Mode` dimension (`normal`, `image`, `prices`, `rulings`, `legality`, `random`) |
| `CardNotFound` | Scryfall returned no match for the query |
| `ScryfallApiError` | Scryfall returned an unexpected error response |
| `ImageFetchFailure` | Card image could not be fetched |
| `RateLimitHit` | Scryfall rate limit (429) was hit; the bot backed off and retried |
| `RateLimitDrop` | A user mention was dropped due to per-user rate limiting |
| `RateLimitWarning` | A warning reply was sent to a user approaching the block threshold |
| `UserBlocked` | A user was permanently blocked via the Bluesky API |
| `BlockListLoaded` | The block list was successfully fetched after a delayed startup |
| `BlockListLoadFailed` | Block list fetch failed during a poll cycle; will retry next cycle |
| `BlockListLoadSkipped` | Block list could not be fetched at startup; bot started with an empty list |
| `LoginFailed` | Authentication was rejected — check credentials |
| `LoginRetry` | A transient login error occurred; the bot is retrying |
| `ProcessingError` | An unexpected error occurred while processing a mention |
| `ReplyError` | A reply could not be sent after a processing error |

## Scryfall API rate limiting

The bot enforces Scryfall's 1 request/second policy between API calls and backs off 30 seconds on HTTP 429 responses.
