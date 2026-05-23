import json
import os
import sys
import time
from pathlib import Path

from atproto import Client
from atproto.exceptions import BadRequestError, UnauthorizedError

from .bluesky_client import BlueskyClient
from .bot import Bot
from .card_lookup import CardLookup
from .config import load_config
from .metrics import record_metric
from .metrics import set_enabled as set_metrics_enabled
from .rate_limiter import RateLimiter

# Resolves to the project root (three levels up from src/bot/main.py)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_STATE_FILE = _PROJECT_ROOT / "state.json"
_CONFIG_FILE = _PROJECT_ROOT / "config.toml"

# Login retry backoff in seconds: 30s, 60s, 120s, 240s, then capped at 300s.
_LOGIN_BACKOFF_S = [30, 60, 120, 240, 300]


class _FileStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> str | None:
        try:
            data = json.loads(self._path.read_text())
            return data.get("lastSeenAt")
        except Exception:
            # Missing or unreadable file is expected on first run
            return None

    def save(self, last_seen_at: str) -> None:
        self._path.write_text(json.dumps({"lastSeenAt": last_seen_at}))


def _login_with_retry(bluesky: BlueskyClient, handle: str, password: str) -> None:
    backoffs = iter(_LOGIN_BACKOFF_S)
    attempt = 0
    while True:
        try:
            bluesky.login(handle, password)
            return
        except (UnauthorizedError, BadRequestError) as err:
            record_metric("LoginFailed")
            print(f"Fatal: authentication rejected: {err}", file=sys.stderr)
            sys.exit(1)
        except Exception as err:
            wait = next(backoffs, _LOGIN_BACKOFF_S[-1])
            attempt += 1
            record_metric("LoginRetry")
            print(
                f"Login failed (attempt {attempt}), retrying in {wait}s: {err}",
                file=sys.stderr,
            )
            time.sleep(wait)


def main() -> None:
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_APP_PASSWORD")
    user_agent = os.environ.get("SCRYFALL_USER_AGENT")

    if not handle or not password or not user_agent:
        raise RuntimeError(
            "Required env vars: BLUESKY_HANDLE, BLUESKY_APP_PASSWORD,"
            " SCRYFALL_USER_AGENT"
        )

    config = load_config(_CONFIG_FILE)
    set_metrics_enabled(config.metrics_enabled)

    agent = Client()
    bluesky = BlueskyClient(agent, _FileStateStore(_STATE_FILE))
    _login_with_retry(bluesky, handle, password)

    blocks_initialized = True
    try:
        blocked_dids = bluesky.fetch_blocked_dids()
    except Exception as err:
        record_metric("BlockListLoadSkipped")
        print(
            f"Warning: could not fetch block list at startup, will retry: {err}",
            file=sys.stderr,
        )
        blocked_dids = set()
        blocks_initialized = False

    rate_limiter = RateLimiter(config.rate_limiting, blocked_dids=blocked_dids)
    card_lookup = CardLookup(user_agent=user_agent)
    bot = Bot(
        bluesky,
        card_lookup,
        rate_limiter,
        config,
        blocks_initialized=blocks_initialized,
    )
    bot.start()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"Fatal error: {err}", file=sys.stderr)
        sys.exit(1)
