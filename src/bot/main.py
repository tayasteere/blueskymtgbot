import json
import os
import sys
from pathlib import Path

from atproto import Client

from .bluesky_client import BlueskyClient
from .bot import Bot
from .card_lookup import CardLookup

# Resolves to the project root (three levels up from src/bot/main.py)
_STATE_FILE = Path(__file__).parent.parent.parent / "state.json"


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


def main() -> None:
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_APP_PASSWORD")
    user_agent = os.environ.get("SCRYFALL_USER_AGENT")

    if not handle or not password or not user_agent:
        raise RuntimeError(
            "Required env vars: BLUESKY_HANDLE, BLUESKY_APP_PASSWORD, SCRYFALL_USER_AGENT"
        )

    agent = Client()
    bluesky = BlueskyClient(agent, _FileStateStore(_STATE_FILE))
    bluesky.login(handle, password)

    card_lookup = CardLookup(user_agent=user_agent)
    bot = Bot(bluesky, card_lookup)
    bot.start()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"Fatal error: {err}", file=sys.stderr)
        sys.exit(1)
