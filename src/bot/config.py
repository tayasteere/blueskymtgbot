from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RateLimitConfig:
    window_seconds: float = 60.0
    max_mentions_per_window: int = 5
    violation_window_seconds: float = 600.0
    violations_before_warning: int = 3
    violations_before_block: int = 5


@dataclass
class BotConfig:
    poll_interval_seconds: float = 5.0
    max_cards_per_mention: int = 4
    metrics_enabled: bool = True
    cache_ttl_seconds: float = 3600.0
    use_jetstream: bool = False
    jetstream_url: str = "wss://jetstream1.us-east.bsky.network/subscribe"
    rate_limiting: RateLimitConfig = field(default_factory=RateLimitConfig)
    trivia_question_bank_path: str | None = None
    trivia_timeout_hours: float = 24.0


_TRIVIA_PATH_SENTINEL = "<unconfigured>"


def _resolve_trivia_path(value: str | None) -> str | None:
    if not value or value.strip() == _TRIVIA_PATH_SENTINEL:
        return None
    return value


def load_config(path: Path) -> BotConfig:
    if not path.exists():
        return BotConfig()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    bot = data.get("bot", {})
    rl = data.get("rate_limiting", {})
    trivia = data.get("trivia", {})

    return BotConfig(
        poll_interval_seconds=bot.get("poll_interval_seconds", 5.0),
        max_cards_per_mention=bot.get("max_cards_per_mention", 4),
        metrics_enabled=bot.get("metrics_enabled", True),
        cache_ttl_seconds=bot.get("cache_ttl_seconds", 3600.0),
        use_jetstream=bot.get("use_jetstream", False),
        jetstream_url=bot.get(
            "jetstream_url",
            "wss://jetstream1.us-east.bsky.network/subscribe",
        ),
        rate_limiting=RateLimitConfig(
            window_seconds=rl.get("window_seconds", 60.0),
            max_mentions_per_window=rl.get("max_mentions_per_window", 5),
            violation_window_seconds=rl.get("violation_window_seconds", 600.0),
            violations_before_warning=rl.get("violations_before_warning", 3),
            violations_before_block=rl.get("violations_before_block", 5),
        ),
        trivia_question_bank_path=_resolve_trivia_path(trivia.get("question_bank_path")),
        trivia_timeout_hours=trivia.get("timeout_hours", 24.0),
    )
