from __future__ import annotations

import time
from dataclasses import dataclass

from .config import RateLimitConfig


@dataclass
class RateLimitDecision:
    allowed: bool
    should_warn: bool = False
    should_block: bool = False


class RateLimiter:
    def __init__(
        self,
        config: RateLimitConfig,
        blocked_dids: set[str] | None = None,
        clock_fn=None,
    ) -> None:
        self._config = config
        self._blocked: set[str] = blocked_dids or set()
        self._clock = clock_fn or time.monotonic
        self._mention_timestamps: dict[str, list[float]] = {}
        self._violation_timestamps: dict[str, list[float]] = {}
        self._warned: set[str] = set()

    def is_blocked(self, did: str) -> bool:
        return did in self._blocked

    def populate_blocked(self, dids: set[str]) -> None:
        self._blocked.update(dids)

    def record_mention(self, did: str) -> RateLimitDecision:
        if did in self._blocked:
            return RateLimitDecision(allowed=False)

        now = self._clock()

        mentions = self._mention_timestamps.setdefault(did, [])
        cutoff = now - self._config.window_seconds
        mentions[:] = [t for t in mentions if t > cutoff]

        if len(mentions) < self._config.max_mentions_per_window:
            mentions.append(now)
            return RateLimitDecision(allowed=True)

        violations = self._violation_timestamps.setdefault(did, [])
        vcutoff = now - self._config.violation_window_seconds
        violations[:] = [t for t in violations if t > vcutoff]
        violations.append(now)

        n = len(violations)

        if n >= self._config.violations_before_block:
            self._blocked.add(did)
            return RateLimitDecision(allowed=False, should_block=True)

        if n >= self._config.violations_before_warning and did not in self._warned:
            self._warned.add(did)
            return RateLimitDecision(allowed=False, should_warn=True)

        return RateLimitDecision(allowed=False)
