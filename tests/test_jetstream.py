import json
import sys
from unittest.mock import MagicMock

from bot.jetstream import (
    JetstreamListener,
    event_to_mention,
    mentions_bot,
    replies_to_bot,
)

BOT_DID = "did:plc:bot123"
USER_DID = "did:plc:user456"
OTHER_DID = "did:plc:other789"


def _post_event(
    author_did=USER_DID,
    text="hello",
    facets=None,
    reply=None,
    operation="create",
    collection="app.bsky.feed.post",
    rkey="abc123",
    cid="bafyreiabc",
    time_us=1_000_000,
):
    event = {
        "did": author_did,
        "time_us": time_us,
        "kind": "commit",
        "commit": {
            "operation": operation,
            "collection": collection,
            "rkey": rkey,
            "cid": cid,
            "record": {
                "text": text,
                "facets": facets or [],
            },
        },
    }
    if reply:
        event["commit"]["record"]["reply"] = reply
    return event


def _mention_facet(did=BOT_DID):
    return {
        "$type": "app.bsky.richtext.facet",
        "index": {"byteStart": 0, "byteEnd": 5},
        "features": [{"$type": "app.bsky.richtext.facet#mention", "did": did}],
    }


def _reply_ref(root_uri, root_cid, parent_uri, parent_cid):
    return {
        "root": {"uri": root_uri, "cid": root_cid},
        "parent": {"uri": parent_uri, "cid": parent_cid},
    }


# ── mentions_bot ──────────────────────────────────────────────────────────────


def test_mentions_bot_facet_matching_did_returns_true():
    event = _post_event(facets=[_mention_facet(BOT_DID)])
    assert mentions_bot(event, BOT_DID)


def test_mentions_bot_no_facets_returns_false():
    event = _post_event()
    assert not mentions_bot(event, BOT_DID)


def test_mentions_bot_facet_different_did_returns_false():
    event = _post_event(facets=[_mention_facet(OTHER_DID)])
    assert not mentions_bot(event, BOT_DID)


def test_mentions_bot_non_commit_returns_false():
    assert not mentions_bot({"kind": "identity"}, BOT_DID)


def test_mentions_bot_delete_operation_returns_false():
    event = _post_event(facets=[_mention_facet(BOT_DID)], operation="delete")
    assert not mentions_bot(event, BOT_DID)


def test_mentions_bot_wrong_collection_returns_false():
    event = _post_event(
        facets=[_mention_facet(BOT_DID)],
        collection="app.bsky.graph.follow",
    )
    assert not mentions_bot(event, BOT_DID)


# ── replies_to_bot ────────────────────────────────────────────────────────────


def test_replies_to_bot_parent_is_bot_post_returns_true():
    ref = _reply_ref(
        f"at://{BOT_DID}/app.bsky.feed.post/root1",
        "rcid1",
        f"at://{BOT_DID}/app.bsky.feed.post/post1",
        "pcid1",
    )
    assert replies_to_bot(_post_event(reply=ref), BOT_DID)


def test_replies_to_bot_parent_is_other_user_returns_false():
    ref = _reply_ref(
        f"at://{OTHER_DID}/app.bsky.feed.post/root1",
        "rcid1",
        f"at://{OTHER_DID}/app.bsky.feed.post/post1",
        "pcid1",
    )
    assert not replies_to_bot(_post_event(reply=ref), BOT_DID)


def test_replies_to_bot_no_reply_field_returns_false():
    assert not replies_to_bot(_post_event(), BOT_DID)


def test_replies_to_bot_non_commit_returns_false():
    assert not replies_to_bot({"kind": "identity"}, BOT_DID)


# ── event_to_mention ──────────────────────────────────────────────────────────


def test_event_to_mention_basic_fields():
    event = _post_event(author_did=USER_DID, text="hi @bot", rkey="post1", cid="cid1")
    m = event_to_mention(event, BOT_DID)
    assert m.author_did == USER_DID
    assert m.text == "hi @bot"
    assert m.uri == f"at://{USER_DID}/app.bsky.feed.post/post1"
    assert m.cid == "cid1"


def test_event_to_mention_no_reply_sets_root_to_self():
    event = _post_event(rkey="post1", cid="cid1")
    m = event_to_mention(event, BOT_DID)
    assert m.root_uri == m.uri
    assert m.root_cid == m.cid
    assert m.parent_uri == ""
    assert m.parent_cid == ""


def test_event_to_mention_reason_mention_when_not_reply_to_bot():
    event = _post_event(facets=[_mention_facet(BOT_DID)])
    m = event_to_mention(event, BOT_DID)
    assert m.reason == "mention"


def test_event_to_mention_reason_reply_when_parent_is_bot():
    ref = _reply_ref(
        f"at://{BOT_DID}/app.bsky.feed.post/root1",
        "rcid",
        f"at://{BOT_DID}/app.bsky.feed.post/post1",
        "pcid",
    )
    m = event_to_mention(_post_event(reply=ref), BOT_DID)
    assert m.reason == "reply"
    assert m.parent_uri == f"at://{BOT_DID}/app.bsky.feed.post/post1"


def test_event_to_mention_reply_to_other_is_mention_reason():
    ref = _reply_ref(
        f"at://{OTHER_DID}/app.bsky.feed.post/root1",
        "rcid",
        f"at://{OTHER_DID}/app.bsky.feed.post/post1",
        "pcid",
    )
    m = event_to_mention(_post_event(reply=ref), BOT_DID)
    assert m.reason == "mention"


def test_event_to_mention_reply_sets_root_and_parent():
    ref = _reply_ref(
        "at://did:plc:x/app.bsky.feed.post/root",
        "rcid",
        "at://did:plc:x/app.bsky.feed.post/parent",
        "pcid",
    )
    m = event_to_mention(_post_event(reply=ref), BOT_DID)
    assert m.root_uri == "at://did:plc:x/app.bsky.feed.post/root"
    assert m.parent_uri == "at://did:plc:x/app.bsky.feed.post/parent"


# ── JetstreamListener ─────────────────────────────────────────────────────────


def _make_mock_websocket(events: list[dict], then_raise=None):
    """Returns a mock websocket module whose create_connection yields events."""
    messages = [json.dumps(e) for e in events]
    if then_raise:
        messages.append(None)  # sentinel

    class _WS:
        def __init__(self):
            self._iter = iter(messages)

        def recv(self):
            msg = next(self._iter)
            if msg is None:
                raise then_raise
            return msg

    mock_ws_mod = MagicMock()
    mock_ws_mod.create_connection.return_value = _WS()
    return mock_ws_mod


def test_listener_yields_bot_mention(monkeypatch):
    event = _post_event(
        author_did=USER_DID,
        facets=[_mention_facet(BOT_DID)],
        time_us=1_000,
    )
    mock_ws = _make_mock_websocket([event], then_raise=Exception("done"))
    monkeypatch.setitem(sys.modules, "websocket", mock_ws)

    listener = JetstreamListener(BOT_DID, sleep_fn=lambda _: None)
    mentions = []
    for m in listener.iter_mentions():
        mentions.append(m)
        break  # stop after first

    assert len(mentions) == 1
    assert mentions[0].author_did == USER_DID


def test_listener_skips_non_bot_events(monkeypatch):
    unrelated = _post_event(author_did=USER_DID, text="just chatting", time_us=1_000)
    bot_mention = _post_event(
        author_did=USER_DID,
        facets=[_mention_facet(BOT_DID)],
        rkey="post2",
        time_us=2_000,
    )
    mock_ws = _make_mock_websocket(
        [unrelated, bot_mention], then_raise=Exception("done")
    )
    monkeypatch.setitem(sys.modules, "websocket", mock_ws)

    listener = JetstreamListener(BOT_DID, sleep_fn=lambda _: None)
    mentions = []
    for m in listener.iter_mentions():
        mentions.append(m)
        break

    assert len(mentions) == 1
    assert mentions[0].uri.endswith("post2")


def test_listener_updates_cursor(monkeypatch):
    event = _post_event(facets=[_mention_facet(BOT_DID)], time_us=99_000)
    mock_ws = _make_mock_websocket([event], then_raise=Exception("done"))
    monkeypatch.setitem(sys.modules, "websocket", mock_ws)

    listener = JetstreamListener(BOT_DID, sleep_fn=lambda _: None)
    for _ in listener.iter_mentions():
        break

    assert listener.cursor == 99_000


def test_listener_reconnects_after_error(monkeypatch):
    good_event = _post_event(facets=[_mention_facet(BOT_DID)], time_us=1_000)

    call_count = {"n": 0}

    class _WS:
        def recv(self):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("disconnect")
            return json.dumps(good_event)

    mock_ws_mod = MagicMock()
    mock_ws_mod.create_connection.return_value = _WS()
    monkeypatch.setitem(sys.modules, "websocket", mock_ws_mod)

    sleep_calls = []
    listener = JetstreamListener(BOT_DID, sleep_fn=lambda s: sleep_calls.append(s))
    for _ in listener.iter_mentions():
        break

    assert len(sleep_calls) >= 1  # slept before reconnect


def test_listener_raises_on_missing_websocket_client(monkeypatch):
    import pytest

    monkeypatch.setitem(sys.modules, "websocket", None)

    class _FailImport(JetstreamListener):
        def iter_mentions(self):
            raise ImportError("No module named 'websocket'")

    listener = _FailImport(BOT_DID)
    with pytest.raises((ImportError, RuntimeError)):
        next(iter(listener.iter_mentions()))
