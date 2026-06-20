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
from .trivia import TriviaManager

# Resolves to the project root (three levels up from src/bot/main.py)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_STATE_FILE = _PROJECT_ROOT / "state.json"
_TRIVIA_STATE_FILE = _PROJECT_ROOT / "trivia_state.json"
_CONFIG_FILE = _PROJECT_ROOT / "config.toml"

# Login retry backoff in seconds: 30s, 60s, 120s, 240s, then capped at 300s.
_LOGIN_BACKOFF_S = [30, 60, 120, 240, 300]


class _FileStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _read(self) -> dict:
        try:
            return json.loads(self._path.read_text())
        except Exception:
            return {}

    def load(self) -> str | None:
        return self._read().get("lastSeenAt")

    def save(self, last_seen_at: str) -> None:
        data = self._read()
        data["lastSeenAt"] = last_seen_at
        self._path.write_text(json.dumps(data))

    def load_jetstream_cursor(self) -> int | None:
        return self._read().get("jetstreamCursor")

    def save_jetstream_cursor(self, cursor: int | None) -> None:
        if cursor is None:
            return
        try:
            data = self._read()
            data["jetstreamCursor"] = cursor
            self._path.write_text(json.dumps(data))
        except Exception as err:
            print(f"Warning: could not save Jetstream cursor: {err}", file=sys.stderr)


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


def _load_trivia_state(trivia_manager: TriviaManager) -> None:
    try:
        data = json.loads(_TRIVIA_STATE_FILE.read_text())
        trivia_manager.load_state(data)
        print(f"Trivia: restored {len(data)} pending question(s) from disk")
    except FileNotFoundError:
        pass
    except Exception as err:
        print(f"Warning: could not load trivia state: {err}", file=sys.stderr)


def _save_trivia_state(trivia_manager: TriviaManager) -> None:
    try:
        _TRIVIA_STATE_FILE.write_text(json.dumps(trivia_manager.dump_state()))
    except Exception as err:
        print(f"Warning: could not save trivia state: {err}", file=sys.stderr)


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

    trivia_manager: TriviaManager | None = None
    trivia_state_saver = None

    if config.trivia_question_bank_path:
        trivia_manager = TriviaManager(
            config.trivia_question_bank_path,
            timeout_hours=config.trivia_timeout_hours,
        )
        trivia_manager.load_questions()
        if trivia_manager.has_questions():
            _load_trivia_state(trivia_manager)
            trivia_manager.expire_old()

            def trivia_state_saver() -> None:
                _save_trivia_state(trivia_manager)
        else:
            trivia_manager = None

    rate_limiter = RateLimiter(config.rate_limiting, blocked_dids=blocked_dids)
    card_lookup = CardLookup(user_agent=user_agent, cache_ttl=config.cache_ttl_seconds)

    jetstream_listener = None
    jetstream_cursor_saver = None
    if config.use_jetstream:
        from .jetstream import JetstreamListener

        state_store = _FileStateStore(_STATE_FILE)
        cursor = state_store.load_jetstream_cursor()
        jetstream_listener = JetstreamListener(
            bot_did=bluesky.bot_did,
            cursor=cursor,
        )
        jetstream_cursor_saver = state_store.save_jetstream_cursor

    bot = Bot(
        bluesky,
        card_lookup,
        rate_limiter,
        config,
        blocks_initialized=blocks_initialized,
        trivia_manager=trivia_manager,
        trivia_state_saver=trivia_state_saver,
        jetstream_listener=jetstream_listener,
        jetstream_cursor_saver=jetstream_cursor_saver,
    )
    bot.start()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"Fatal error: {err}", file=sys.stderr)
        sys.exit(1)
