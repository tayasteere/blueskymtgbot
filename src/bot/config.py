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
    rate_limiting: RateLimitConfig = field(default_factory=RateLimitConfig)


def load_config(path: Path) -> BotConfig:
    if not path.exists():
        return BotConfig()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    bot = data.get("bot", {})
    rl = data.get("rate_limiting", {})

    return BotConfig(
        poll_interval_seconds=bot.get("poll_interval_seconds", 5.0),
        max_cards_per_mention=bot.get("max_cards_per_mention", 4),
        metrics_enabled=bot.get("metrics_enabled", True),
        rate_limiting=RateLimitConfig(
            window_seconds=rl.get("window_seconds", 60.0),
            max_mentions_per_window=rl.get("max_mentions_per_window", 5),
            violation_window_seconds=rl.get("violation_window_seconds", 600.0),
            violations_before_warning=rl.get("violations_before_warning", 3),
            violations_before_block=rl.get("violations_before_block", 5),
        ),
    )
