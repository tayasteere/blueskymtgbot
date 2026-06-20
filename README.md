# Bluesky MTG Bot

[![CI](https://github.com/tayasteere/blueskymtgbot/actions/workflows/ci.yml/badge.svg)](https://github.com/tayasteere/blueskymtgbot/actions/workflows/ci.yml)

A Bluesky bot that looks up Magic: The Gathering cards via the [Scryfall API](https://scryfall.com/docs/api) and replies with card details, prices, rulings, legality, or card images.

> **Running or deploying the bot?** See [OPERATORS.md](OPERATORS.md).

## Usage

Mention the bot in any Bluesky post with card names wrapped in double brackets:

```
@mtgbot.bsky.social [[Lightning Bolt]]
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
[[Lightning Bolt|lea]]        ← by set code
[[Lightning Bolt|lea|62]]     ← by set code + collector number
```

Up to **4 cards** can be looked up per mention. If you include more, the bot replies with a count of how many were skipped — use a separate mention for those.

### Help

Mention the bot with the word **help** (and no `[[...]]` card lookups) to see a quick reference:

```
@mtgbot.bsky.social help
```

### Card not found

If a card name doesn't match anything on Scryfall, the bot will suggest the closest match it can find:

```
No card found for "lighning blt". Did you mean [[Lightning Bolt]]?
```

### Long responses

Some cards have lengthy rulings or oracle text. The bot automatically splits long replies into a numbered thread — `(1/3)`, `(2/3)`, `(3/3)` — so you always know where you are in the sequence.

## Trivia

Mention the bot with the word **trivia** anywhere in your post to receive a random MTG trivia question:

```
@mtgbot.bsky.social trivia
```

Reply to the bot's question post with your answer — no need to @-mention the bot again. The bot will tell you whether you were correct and reveal the answer.

Questions cover card rules text, flavor text, mana costs, power/toughness, colors, keywords, rarity, set names, and more.

## License

Copyright 2026 Taya Steere. Licensed under the [Apache License, Version 2.0](LICENSE).
