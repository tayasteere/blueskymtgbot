# Operators Guide

This document covers everything needed to set up, deploy, configure, and maintain the Bluesky MTG Bot.

> **End-user docs** (query syntax, trivia, etc.) live in [README.md](README.md).

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

Set the following environment variables (or add them to a `.env` file):

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

The bot polls for new mentions every 5 seconds. On first run it skips all pre-existing notifications; on subsequent runs it resumes from `state.json` in the project root. Pending trivia questions are persisted in `trivia_state.json`.

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

For a VPS without Docker, create `/etc/systemd/system/mtgbot.service`:

```ini
[Unit]
Description=Bluesky Scryfall Bot
After=network.target

[Service]
User=mtgbot
WorkingDirectory=/opt/mtgbot
EnvironmentFile=/opt/mtgbot/.env
ExecStart=/opt/mtgbot/.venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
systemctl daemon-reload
systemctl enable --now mtgbot
journalctl -fu mtgbot   # follow logs
```

### AWS

The bot emits metrics in [CloudWatch Embedded Metric Format](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatchEmbedded_Metrics_Format.html). On EC2 with the [CloudWatch agent](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Install-CloudWatch-Agent.html) configured to collect stdout, metrics are ingested automatically with no extra code. The Docker image works on EC2 as-is.

## Configuration

Bot behaviour can be tuned by placing a `config.toml` file in the project root. All keys are optional — omitting a key uses the default shown below.

```toml
[bot]
poll_interval_seconds = 5   # how often to check for new mentions (polling mode only)
max_cards_per_mention = 4   # maximum cards looked up in a single mention
metrics_enabled = true      # set to false to disable metric output
cache_ttl_seconds = 3600    # Scryfall response cache lifetime; 0 disables caching
use_jetstream = false       # set to true to use Jetstream instead of polling
jetstream_url = "wss://jetstream1.us-east.bsky.network/subscribe"  # or jetstream2

[rate_limiting]
window_seconds = 60              # length of the rate limit window
max_mentions_per_window = 5      # mentions allowed per user per window
violation_window_seconds = 600   # window over which violations are counted
violations_before_warning = 3    # violations before a warning reply is sent
violations_before_block = 5      # violations before the user is blocked

[trivia]
# Path to the pre-generated question bank (see Question bank format below).
# Set to a local file path for development or an S3 URI for production.
# Leave as "<unconfigured>" (the default) to disable trivia entirely.
question_bank_path = "<unconfigured>"
timeout_hours = 24.0   # how long before an unanswered question expires
```

If no `config.toml` is present the defaults above are used.

### Question bank format

The trivia question bank is a [JSONL](https://jsonlines.org/) file — one JSON object per line. The bot loads it entirely into memory at startup; the file is never modified by the bot.

Each line must contain the following fields:

| Field | Type | Description |
|---|---|---|
| `question` | string | The trivia question text (≤ 280 characters) |
| `answer` | string | The canonical correct answer |
| `category` | string | Question category key (see below) |
| `answer_type` | string | How the answer is matched (see below) |
| `card_name` | string | Name of the MTG card the question is about |
| `oracle_id` | string | Scryfall oracle ID |

Example line:

```json
{"question": "Which red instant bears the flavor text: \"Chandra never believed in using her 'inside voice.'\"?", "answer": "Chandra's Outrage", "category": "flavor_text", "answer_type": "card_name", "card_name": "Chandra's Outrage", "oracle_id": "47437865-0032-4f47-b0ab-034cc841bb84"}
```

**Question categories and answer types:**

| `category` | `answer_type` | What the user must supply |
|---|---|---|
| `rules_text` | `card_name` | The card's name |
| `flavor_text` | `card_name` | The card's name |
| `keywords_guess` | `card_name` | The card's name |
| `type_guess` | `subtype` | The card's subtype(s) |
| `power_toughness` | `power_toughness` | Power/toughness as `X/Y` |
| `mana_cost` | `mana_cost` | Mana cost e.g. `{2}{B}{B}` or `2BB` |
| `cmc` | `cmc` | Mana value as a number |
| `colors` | `colors` | Color name(s) or code(s) e.g. `Red` or `R` |
| `color_identity` | `color_identity` | Color identity name(s) or code(s) |
| `rarity` | `rarity` | `Common`, `Uncommon`, `Rare`, or `Mythic Rare` |
| `set_name` | `set_name` | Set name, set code, or a partial name |
| `type_line` | `type_line` | Full card type line |
| `keywords` | `keywords` | Keyword abilities |

Answer matching is case-insensitive and lenient where it makes sense: mana cost curly braces are optional, color codes (`W U B R G C`) are accepted alongside full names, multi-word answers are order-independent for subtypes/keywords/colors, and partial set names (e.g. `Betrayers`) match the full set name. Double-faced card names accept either face.

### Loading from S3

Set `question_bank_path` to an S3 URI to load the question bank from S3 at startup:

```toml
[trivia]
question_bank_path = "s3://your-bucket/question_bank.jsonl"
```

Install the `boto3` dependency:

```bash
pip install -e ".[s3]"
```

AWS credentials are resolved via the standard boto3 chain (environment variables, IAM role, instance profile). On EC2 or ECS with an appropriate IAM role attached, no extra configuration is needed.

## Abuse prevention

The bot tracks mentions per user and enforces a rate limit to prevent spam.

- **Rate limiting** — each user may send up to 5 mentions per 60-second window. Mentions beyond this are silently dropped.
- **Warnings** — after 3 rate limit violations within a 10-minute window, the user receives a single warning reply.
- **Blocking** — after 5 violations, the user is permanently blocked via the Bluesky API. Blocks persist across restarts; the bot fetches the existing block list from Bluesky on startup.

All thresholds are configurable via `config.toml`.

## Jetstream mode

By default the bot polls Bluesky's notification API every 5 seconds. Enabling Jetstream replaces polling with a persistent WebSocket connection to [Bluesky's Jetstream service](https://github.com/bluesky-social/jetstream), delivering mentions in real time (typically sub-second latency).

### Enable

Set `use_jetstream = true` in `config.toml` and install the extra dependency:

```bash
pip install -e ".[jetstream]"
```

### How it works

Jetstream streams all posts on the network. The bot filters locally for posts that either @-mention its DID (via AT Protocol facets) or are direct replies to one of its posts (needed for trivia answers). The `poll_interval_seconds` setting is ignored in Jetstream mode.

### Cursor persistence

The bot saves a Jetstream cursor (Unix microseconds timestamp) to `state.json` after each processed mention. On restart it resumes from that cursor, replaying any mentions that arrived while the bot was offline. On first run with no saved cursor, the bot starts from the current moment and skips older posts.

### Trade-offs

| | Polling | Jetstream |
|---|---|---|
| Latency | Up to 5 seconds | < 1 second |
| Bandwidth | Low (only your notifications) | Higher (filters all posts locally) |
| Complexity | Simple HTTP | WebSocket + reconnect logic |
| Dependency | None extra | `websocket-client` |

Jetstream is most valuable for bots where response latency matters. For low-traffic bots where 5-second lag is acceptable, polling is simpler.

## Scryfall API behaviour

### Rate limiting

The bot enforces Scryfall's 1 request/second policy between API calls and backs off 30 seconds on HTTP 429 responses.

### Response caching

Card lookups, autocomplete suggestions, and rulings are cached in memory for **1 hour** by default. This reduces Scryfall API calls when the same card is looked up repeatedly. Random card results are never cached. Not-found results (typos, bad card names) are also cached so repeated bad queries don't generate extra API calls.

The cache is in-process and does not persist across restarts. The TTL can be changed via `config.toml` — set `cache_ttl_seconds = 0` to disable caching entirely.

## Development

Install dev dependencies:

```bash
pip install -e ".[dev]"
```

Run tests and lint together (always do both before committing):

```bash
python -m ruff check .
python -m pytest tests/
```

With coverage:

```bash
pytest --cov=bot
```

## Project structure

```
src/bot/
  main.py           — entry point, wires up dependencies
  bot.py            — poll loop and mention processing logic
  bluesky_client.py — atproto wrapper (auth, notifications, replies, blocks)
  card_lookup.py    — Scryfall API client with rate limiting and response cache
  card_formatter.py — formats card data into reply text; handles thread splitting
  query_parser.py   — parses [[card]] syntax from post text
  rate_limiter.py   — per-user rate limiting and block decisions
  config.py         — configuration dataclasses and config.toml loader
  metrics.py        — lightweight metric recording
  trivia.py         — trivia question loading, answer matching, pending question state
```

## Metrics

The bot emits metrics in [CloudWatch Embedded Metric Format (EMF)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatchEmbedded_Metrics_Format.html) — structured JSON written to stdout. On AWS (Lambda or EC2 with the CloudWatch agent), these are automatically ingested as CloudWatch metrics. Outside of AWS they appear as JSON log lines and are otherwise harmless.

Metrics can be disabled by setting `metrics_enabled = false` in `config.toml`.

### Metric events

| Metric | Description |
|---|---|
| `MentionProcessed` | A mention containing at least one card query was processed |
| `CardsInMention` | Number of card queries in a processed mention (value 1–4); useful for tracking multi-card usage |
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
| `TriviaQuestionAsked` | A trivia question was sent to a user |
| `TriviaAnswered` | A trivia answer was received; includes `Correct` dimension (`True` / `False`) |
