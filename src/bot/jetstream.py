from __future__ import annotations

import json
import time

from .bluesky_client import Mention

_JETSTREAM_URL = "wss://jetstream2.us-east.bsky.network/subscribe"
_COLLECTION = "app.bsky.feed.post"
_FACET_MENTION = "app.bsky.richtext.facet#mention"
_RECONNECT_DELAYS_S = [1, 2, 5, 10, 30, 60]


def _build_url(cursor: int | None = None) -> str:
    url = f"{_JETSTREAM_URL}?wantedCollections={_COLLECTION}"
    if cursor is not None:
        url += f"&cursor={cursor}"
    return url


def _is_new_post(event: dict) -> bool:
    commit = event.get("commit", {})
    return (
        event.get("kind") == "commit"
        and commit.get("operation") == "create"
        and commit.get("collection") == _COLLECTION
    )


def mentions_bot(event: dict, bot_did: str) -> bool:
    """True if the post contains a facet @-mention of the bot's DID."""
    if not _is_new_post(event):
        return False
    record = event["commit"].get("record", {})
    for facet in record.get("facets", []):
        for feature in facet.get("features", []):
            if (
                feature.get("$type") == _FACET_MENTION
                and feature.get("did") == bot_did
            ):
                return True
    return False


def replies_to_bot(event: dict, bot_did: str) -> bool:
    """True if the post is a direct reply to one of the bot's posts."""
    if not _is_new_post(event):
        return False
    record = event["commit"].get("record", {})
    reply = record.get("reply")
    if not reply:
        return False
    parent_uri = reply.get("parent", {}).get("uri", "")
    return parent_uri.startswith(f"at://{bot_did}/")


def event_to_mention(event: dict, bot_did: str) -> Mention:
    commit = event["commit"]
    record = commit["record"]
    author_did = event["did"]
    uri = f"at://{author_did}/{_COLLECTION}/{commit['rkey']}"
    cid = commit["cid"]
    text = record.get("text", "")

    reply = record.get("reply")
    if reply:
        root = reply.get("root", {})
        parent = reply.get("parent", {})
        root_uri = root.get("uri", uri)
        root_cid = root.get("cid", cid)
        parent_uri = parent.get("uri", "")
        parent_cid = parent.get("cid", "")
    else:
        root_uri = uri
        root_cid = cid
        parent_uri = ""
        parent_cid = ""

    reason = "reply" if parent_uri.startswith(f"at://{bot_did}/") else "mention"

    return Mention(
        uri=uri,
        cid=cid,
        text=text,
        root_uri=root_uri,
        root_cid=root_cid,
        author_did=author_did,
        parent_uri=parent_uri,
        parent_cid=parent_cid,
        reason=reason,
    )


class JetstreamListener:
    def __init__(
        self,
        bot_did: str,
        cursor: int | None = None,
        sleep_fn=None,
    ) -> None:
        self._bot_did = bot_did
        self._cursor = cursor
        self._sleep = sleep_fn or time.sleep

    @property
    def cursor(self) -> int | None:
        return self._cursor

    def iter_mentions(self):
        """Yields Mention objects from Jetstream, reconnecting on disconnect."""
        try:
            import websocket
        except ImportError:
            raise RuntimeError(
                "websocket-client is required for Jetstream mode. "
                "Install it with: pip install -e '.[jetstream]'"
            )

        print(f"Jetstream: filtering for bot_did={self._bot_did}")
        attempt = 0
        event_count = 0
        post_count = 0
        facet_mention_count = 0
        while True:
            try:
                url = _build_url(self._cursor)
                ws = websocket.create_connection(url)
                attempt = 0
                print(f"Jetstream connected (cursor={self._cursor})")
                while True:
                    raw = ws.recv()
                    event = json.loads(raw)
                    time_us = event.get("time_us")
                    if time_us is not None:
                        self._cursor = time_us
                    event_count += 1
                    if _is_new_post(event):
                        post_count += 1
                        record = event["commit"].get("record", {})
                        mentioned_dids = [
                            feat.get("did")
                            for f in record.get("facets", [])
                            for feat in f.get("features", [])
                            if feat.get("$type") == _FACET_MENTION
                        ]
                        if mentioned_dids:
                            facet_mention_count += 1
                            print(
                                f"Jetstream: @-mention facet(s) from"
                                f" {event.get('did')}: {mentioned_dids}"
                            )
                    if event_count % 1_000 == 0:
                        print(
                            f"Jetstream: {event_count} events,"
                            f" {post_count} posts,"
                            f" {facet_mention_count} with @-mention facets"
                        )
                    if mentions_bot(event, self._bot_did) or replies_to_bot(
                        event, self._bot_did
                    ):
                        print(
                            f"Jetstream: mention matched from"
                            f" {event.get('did')} (event #{event_count})"
                        )
                        yield event_to_mention(event, self._bot_did)
            except Exception as err:
                delay = _RECONNECT_DELAYS_S[
                    min(attempt, len(_RECONNECT_DELAYS_S) - 1)
                ]
                attempt += 1
                print(
                    f"Jetstream error (attempt {attempt}): {err}."
                    f" Reconnecting in {delay}s..."
                )
                self._sleep(delay)
