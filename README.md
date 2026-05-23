# Bluesky Scryfall Bot

A Bluesky bot that looks up Magic: The Gathering cards via the [Scryfall API](https://scryfall.com/docs/api) and replies with card details, prices, rulings, legality, or card images.

## Usage

Mention the bot in any Bluesky post with card names wrapped in double brackets:

```
@yourbot.bsky.social [[Lightning Bolt]]
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
```

### Run

```bash
python -m bot.main
```

The bot polls for new mentions every 5 seconds. On first run it skips all pre-existing notifications; on subsequent runs it resumes from `state.json` in the project root.

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
  bluesky_client.py — atproto wrapper (auth, notifications, replies)
  card_lookup.py    — Scryfall API client with rate limiting
  card_formatter.py — formats card data into reply text
  query_parser.py   — parses [[card]] syntax from post text
  metrics.py        — lightweight metric recording
```

## Rate limiting

The bot enforces Scryfall's 1 request/second policy between API calls and backs off 30 seconds on HTTP 429 responses.
