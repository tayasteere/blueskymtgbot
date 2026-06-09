from unittest.mock import MagicMock

from atproto_client.models.blob_ref import BlobRef

from bot.bluesky_client import BlueskyClient, Mention, PostRef


def _make_blob_ref() -> BlobRef:
    return BlobRef(mimeType="image/jpeg", size=1024, ref=b"fakecid")


def _make_notification(
    uri, cid, reason, text, indexed_at, reply=None, author_did="did:plc:test"
):
    n = MagicMock()
    n.uri = uri
    n.cid = cid
    n.reason = reason
    n.indexed_at = indexed_at
    n.record = MagicMock()
    n.record.text = text
    n.record.reply = reply
    n.author = MagicMock()
    n.author.did = author_did
    return n


T_OLD = "2020-01-01T00:00:00.000Z"
T_BEFORE = "2030-01-01T00:00:00.000Z"
T_JAN2 = "2030-01-02T00:00:00.000Z"
T_JAN3 = "2030-01-03T00:00:00.000Z"
T_JAN5 = "2030-01-05T00:00:00.000Z"


def _make_agent(notifications=None):
    agent = MagicMock()
    agent.app.bsky.notification.list_notifications.return_value = MagicMock(
        notifications=notifications or []
    )
    agent.send_post.return_value = MagicMock(uri="at://post/1", cid="cid1")
    agent.upload_blob.return_value = MagicMock(blob=_make_blob_ref())
    return agent


# ── login ─────────────────────────────────────────────────────────────────────


def test_login_delegates_to_agent():
    agent = _make_agent()
    client = BlueskyClient(agent)
    client.login("user.bsky.social", "app-password")
    agent.login.assert_called_once_with("user.bsky.social", "app-password")


# ── cold start ────────────────────────────────────────────────────────────────


def test_cold_start_skips_old_notifications():
    notif = _make_notification("at://old", "c0", "mention", "hi", T_OLD)
    agent = _make_agent([notif])
    client = BlueskyClient(agent)
    # _last_seen_at is set to now, which is after 2020, so old notif is filtered out
    mentions = client.get_new_mentions()
    assert mentions == []


def test_state_store_cursor_loaded_on_init():
    store = MagicMock()
    store.load.return_value = "2025-01-01T00:00:00.000Z"
    agent = _make_agent()
    client = BlueskyClient(agent, store)
    assert client._last_seen_at == "2025-01-01T00:00:00.000Z"


def test_no_state_store_defaults_to_now():
    agent = _make_agent()
    client = BlueskyClient(agent)
    # Should be a recent ISO timestamp
    assert "2026" in client._last_seen_at or "2025" in client._last_seen_at


# ── get_new_mentions ──────────────────────────────────────────────────────────


def test_returns_mention_and_reply_notifications():
    notifs = [
        _make_notification("at://1", "c1", "mention", "hello", T_JAN2),
        _make_notification("at://2", "c2", "reply", "a reply", T_JAN2),
        _make_notification("at://3", "c3", "like", "liked", T_JAN2),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    mentions = client.get_new_mentions()
    assert len(mentions) == 2
    assert {m.uri for m in mentions} == {"at://1", "at://2"}


def test_filters_by_cursor():
    notifs = [
        _make_notification("at://new", "c1", "mention", "hi", T_JAN3),
        _make_notification("at://old", "c2", "mention", "old", T_BEFORE),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_JAN2
    mentions = client.get_new_mentions()
    assert len(mentions) == 1
    assert mentions[0].uri == "at://new"


def test_cursor_advances_to_latest():
    notifs = [
        _make_notification("at://1", "c1", "mention", "hi", T_JAN5),
    ]
    agent = _make_agent(notifs)
    store = MagicMock()
    store.load.return_value = T_BEFORE
    client = BlueskyClient(agent, store)
    client.get_new_mentions()
    assert client._last_seen_at == T_JAN5
    store.save.assert_called_once_with(T_JAN5)


def test_cursor_not_saved_when_no_state_store():
    notifs = [
        _make_notification("at://1", "c1", "mention", "hi", T_JAN5),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    client.get_new_mentions()  # should not raise


def test_mention_text_extracted():
    notifs = [
        _make_notification("at://1", "c1", "mention", "check [[Bolt]]", T_JAN2),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    mentions = client.get_new_mentions()
    assert mentions[0].text == "check [[Bolt]]"


def test_root_ref_defaults_to_mention_when_not_a_reply():
    notifs = [
        _make_notification("at://1", "c1", "mention", "hi", T_JAN2, reply=None),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    m = client.get_new_mentions()[0]
    assert m.root_uri == "at://1"
    assert m.root_cid == "c1"


def test_root_ref_from_reply_when_nested():
    reply_mock = MagicMock()
    reply_mock.root.uri = "at://root"
    reply_mock.root.cid = "croot"
    notifs = [
        _make_notification("at://1", "c1", "mention", "hi", T_JAN2, reply=reply_mock),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = "2030-01-01T00:00:00.000Z"
    m = client.get_new_mentions()[0]
    assert m.root_uri == "at://root"
    assert m.root_cid == "croot"


# ── upload_image ──────────────────────────────────────────────────────────────


def test_upload_image_returns_blob():
    agent = _make_agent()
    client = BlueskyClient(agent)
    blob = client.upload_image(b"\xff\xd8image", "image/jpeg")
    assert isinstance(blob, BlobRef)
    agent.upload_blob.assert_called_once_with(b"\xff\xd8image")


# ── reply_to_mention ──────────────────────────────────────────────────────────


def _make_mention_obj():
    return Mention(
        uri="at://m1",
        cid="cm1",
        text="hi",
        root_uri="at://root",
        root_cid="croot",
        author_did="did:plc:test",
        parent_uri="",
        parent_cid="",
        reason="mention",
    )


def test_reply_to_mention_calls_send_post():
    agent = _make_agent()
    client = BlueskyClient(agent)
    client.reply_to_mention(_make_mention_obj(), "Hello!")
    agent.send_post.assert_called_once()
    call_kwargs = agent.send_post.call_args.kwargs
    assert call_kwargs["text"] == "Hello!"
    assert call_kwargs["reply_to"] is not None


def test_reply_to_mention_returns_post_ref():
    agent = _make_agent()
    client = BlueskyClient(agent)
    result = client.reply_to_mention(_make_mention_obj(), "Hello!")
    assert isinstance(result, PostRef)
    assert result.uri == "at://post/1"
    assert result.cid == "cid1"


def test_reply_to_mention_with_image_passes_embed():
    agent = _make_agent()
    client = BlueskyClient(agent)
    client.reply_to_mention(
        _make_mention_obj(),
        "Card!",
        image={"blob": _make_blob_ref(), "alt": "alt text"},
    )
    call_kwargs = agent.send_post.call_args.kwargs
    assert call_kwargs.get("embed") is not None


def test_reply_to_mention_without_image_no_embed():
    agent = _make_agent()
    client = BlueskyClient(agent)
    client.reply_to_mention(_make_mention_obj(), "Hello!")
    call_kwargs = agent.send_post.call_args.kwargs
    assert call_kwargs.get("embed") is None


# ── reply_in_thread ───────────────────────────────────────────────────────────


def test_reply_in_thread_returns_post_ref():
    agent = _make_agent()
    client = BlueskyClient(agent)
    root = PostRef(uri="at://root", cid="croot")
    parent = PostRef(uri="at://parent", cid="cparent")
    result = client.reply_in_thread(root, parent, "continuation")
    assert isinstance(result, PostRef)
    assert result.uri == "at://post/1"


def test_reply_in_thread_calls_send_post_with_text():
    agent = _make_agent()
    client = BlueskyClient(agent)
    root = PostRef(uri="at://root", cid="croot")
    parent = PostRef(uri="at://parent", cid="cparent")
    client.reply_in_thread(root, parent, "part 2")
    call_kwargs = agent.send_post.call_args.kwargs
    assert call_kwargs["text"] == "part 2"
    assert call_kwargs["reply_to"] is not None


# ── author_did ────────────────────────────────────────────────────────────────


def test_author_did_extracted_from_notification():
    notifs = [
        _make_notification(
            "at://1", "c1", "mention", "hi", T_JAN2, author_did="did:plc:abc123"
        )
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    m = client.get_new_mentions()[0]
    assert m.author_did == "did:plc:abc123"


# ── fetch_blocked_dids ────────────────────────────────────────────────────────


def test_fetch_blocked_dids_returns_set_of_dids():
    agent = _make_agent()
    blocked1, blocked2 = MagicMock(did="did:plc:bad1"), MagicMock(did="did:plc:bad2")
    agent.app.bsky.graph.get_blocks.return_value = MagicMock(
        blocks=[blocked1, blocked2], cursor=None
    )
    client = BlueskyClient(agent)
    result = client.fetch_blocked_dids()
    assert result == {"did:plc:bad1", "did:plc:bad2"}


def test_fetch_blocked_dids_paginates():
    agent = _make_agent()
    page1 = MagicMock(blocks=[MagicMock(did="did:plc:bad1")], cursor="next")
    page2 = MagicMock(blocks=[MagicMock(did="did:plc:bad2")], cursor=None)
    agent.app.bsky.graph.get_blocks.side_effect = [page1, page2]
    client = BlueskyClient(agent)
    result = client.fetch_blocked_dids()
    assert result == {"did:plc:bad1", "did:plc:bad2"}
    assert agent.app.bsky.graph.get_blocks.call_count == 2


def test_fetch_blocked_dids_empty():
    agent = _make_agent()
    agent.app.bsky.graph.get_blocks.return_value = MagicMock(blocks=[], cursor=None)
    client = BlueskyClient(agent)
    assert client.fetch_blocked_dids() == set()


# ── parent_uri / parent_cid / reason ─────────────────────────────────────────


def test_parent_uri_populated_from_reply():
    reply_mock = MagicMock()
    reply_mock.root.uri = "at://root"
    reply_mock.root.cid = "croot"
    reply_mock.parent.uri = "at://parent"
    reply_mock.parent.cid = "cparent"
    notifs = [
        _make_notification("at://1", "c1", "reply", "hi", T_JAN2, reply=reply_mock),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    m = client.get_new_mentions()[0]
    assert m.parent_uri == "at://parent"
    assert m.parent_cid == "cparent"


def test_parent_uri_empty_when_not_a_reply():
    notifs = [
        _make_notification("at://1", "c1", "mention", "hi", T_JAN2, reply=None),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    m = client.get_new_mentions()[0]
    assert m.parent_uri == ""
    assert m.parent_cid == ""


def test_reason_set_on_mention():
    notifs = [
        _make_notification("at://1", "c1", "mention", "hi", T_JAN2),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    m = client.get_new_mentions()[0]
    assert m.reason == "mention"


def test_reason_set_on_reply():
    reply_mock = MagicMock()
    reply_mock.root.uri = "at://root"
    reply_mock.root.cid = "croot"
    reply_mock.parent.uri = "at://parent"
    reply_mock.parent.cid = "cparent"
    notifs = [
        _make_notification("at://1", "c1", "reply", "hi", T_JAN2, reply=reply_mock),
    ]
    agent = _make_agent(notifs)
    client = BlueskyClient(agent)
    client._last_seen_at = T_BEFORE
    m = client.get_new_mentions()[0]
    assert m.reason == "reply"


# ── block_user ────────────────────────────────────────────────────────────────


def test_block_user_calls_create_record():
    agent = _make_agent()
    agent.me.did = "did:plc:botdid"
    client = BlueskyClient(agent)
    client.block_user("did:plc:badactor")
    agent.com.atproto.repo.create_record.assert_called_once()
    call_args = agent.com.atproto.repo.create_record.call_args[0][0]
    assert call_args.repo == "did:plc:botdid"
    assert call_args.collection == "app.bsky.graph.block"
    assert call_args.record.subject == "did:plc:badactor"
