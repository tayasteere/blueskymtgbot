from unittest.mock import MagicMock, patch

from bot.bluesky_client import Mention, PostRef
from bot.bot import Bot
from bot.config import BotConfig, RateLimitConfig
from bot.rate_limiter import RateLimiter


def _make_mention(
    text="[[Lightning Bolt]]",
    uri="at://m1",
    cid="c1",
    root_uri="at://root",
    root_cid="croot",
    author_did="did:plc:user1",
):
    return Mention(
        uri=uri,
        cid=cid,
        text=text,
        root_uri=root_uri,
        root_cid=root_cid,
        author_did=author_did,
    )


def _make_bluesky(mentions=None):
    bluesky = MagicMock()
    bluesky.get_new_mentions.return_value = mentions if mentions is not None else []
    bluesky.reply_to_mention.return_value = PostRef(uri="at://reply/1", cid="cr1")
    bluesky.reply_in_thread.return_value = PostRef(uri="at://reply/2", cid="cr2")
    bluesky.upload_image.return_value = MagicMock()
    return bluesky


_DEFAULT_CARD = {
    "name": "Lightning Bolt",
    "mana_cost": "{R}",
    "type_line": "Instant",
    "oracle_text": "Deals 3 damage.",
    "rarity": "common",
    "set": "m10",
}


def _make_card_lookup(card=None, rulings=None, image=None):
    lookup = MagicMock()
    lookup.find_card.return_value = card or _DEFAULT_CARD
    lookup.random_card.return_value = _DEFAULT_CARD
    lookup.find_rulings.return_value = rulings if rulings is not None else []
    lookup.fetch_image.return_value = image
    return lookup


def _make_rate_limiter(blocked_dids=None):
    return RateLimiter(RateLimitConfig(), blocked_dids=blocked_dids)


def _make_bot(
    bluesky=None,
    card_lookup=None,
    rate_limiter=None,
    sleep_fn=None,
    blocks_initialized=True,
):
    return Bot(
        bluesky=bluesky or _make_bluesky(),
        card_lookup=card_lookup or _make_card_lookup(),
        rate_limiter=rate_limiter or _make_rate_limiter(),
        config=BotConfig(),
        sleep_fn=sleep_fn or (lambda _: None),
        blocks_initialized=blocks_initialized,
    )


# ── normal mode ───────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_normal_mode_replies_with_card_text(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "Lightning Bolt" in text


@patch("bot.bot.record_metric")
def test_normal_mode_attaches_image(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    lookup = _make_card_lookup(image=b"\xff\xd8img")
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.upload_image.assert_called_once()
    image_arg = bluesky.reply_to_mention.call_args[0][2]
    assert image_arg is not None


@patch("bot.bot.record_metric")
def test_normal_mode_no_image_when_fetch_returns_none(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    lookup = _make_card_lookup(image=None)
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    args = bluesky.reply_to_mention.call_args[0]
    image_arg = args[2] if len(args) > 2 else None
    assert image_arg is None


@patch("bot.bot.record_metric")
def test_normal_mode_threads_overflow_text(mock_metric):
    long_oracle = "word " * 70  # well over 300 chars
    card = {
        "name": "Long Card",
        "type_line": "Sorcery",
        "oracle_text": long_oracle,
        "rarity": "rare",
        "set": "tst",
    }
    bluesky = _make_bluesky([_make_mention("[[Long Card]]")])
    lookup = _make_card_lookup(card=card)
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    assert bluesky.reply_in_thread.call_count >= 1


# ── prices mode ───────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_prices_mode_no_image(mock_metric):
    card = {
        "name": "Lightning Bolt",
        "set_name": "Magic 2010",
        "rarity": "common",
        "set": "m10",
        "prices": {"usd": "1.50"},
    }
    bluesky = _make_bluesky([_make_mention("[[$Lightning Bolt]]")])
    lookup = _make_card_lookup(card=card)
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.upload_image.assert_not_called()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "$1.50" in text


# ── legality mode ─────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_legality_mode_no_image(mock_metric):
    card = {
        "name": "Lightning Bolt",
        "legalities": {"modern": "legal"},
    }
    bluesky = _make_bluesky([_make_mention("[[#Lightning Bolt]]")])
    lookup = _make_card_lookup(card=card)
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.upload_image.assert_not_called()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "Legalities" in text


# ── rulings mode ──────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_rulings_mode_calls_find_rulings(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[?Lightning Bolt]]")])
    lookup = _make_card_lookup()
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    lookup.find_rulings.assert_called_once()


@patch("bot.bot.record_metric")
def test_rulings_mode_no_image(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[?Lightning Bolt]]")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    bluesky.upload_image.assert_not_called()


# ── image mode ────────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_image_mode_replies_with_card_name(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[!Lightning Bolt]]")])
    lookup = _make_card_lookup(image=b"\xff\xd8img")
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert text == "Lightning Bolt"


# ── card not found ────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_card_not_found_replies_with_message(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[zzzzz]]")])
    lookup = _make_card_lookup(card=None)
    lookup.find_card.return_value = None
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "zzzzz" in text


# ── metrics ───────────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_records_mention_processed_metric(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    _make_bot(bluesky=bluesky).process_mentions()
    mock_metric.assert_any_call("MentionProcessed")


@patch("bot.bot.record_metric")
def test_records_card_lookup_metric_with_mode(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[$Lightning Bolt]]")])
    _make_bot(bluesky=bluesky).process_mentions()
    mock_metric.assert_any_call("CardLookup", {"Mode": "prices"})


@patch("bot.bot.record_metric")
def test_records_card_not_found_metric(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[zzzzz]]")])
    lookup = _make_card_lookup()
    lookup.find_card.return_value = None
    _make_bot(bluesky=bluesky, card_lookup=lookup).process_mentions()
    mock_metric.assert_any_call("CardNotFound", {"Mode": "normal"})


@patch("bot.bot.record_metric")
def test_records_processing_error_metric(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    lookup = _make_card_lookup()
    lookup.find_card.side_effect = RuntimeError("API down")
    _make_bot(bluesky=bluesky, card_lookup=lookup).process_mentions()
    mock_metric.assert_any_call("ProcessingError")


@patch("bot.bot.record_metric")
def test_records_reply_error_metric(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    lookup = _make_card_lookup()
    lookup.find_card.side_effect = RuntimeError("API down")
    bluesky.reply_to_mention.side_effect = RuntimeError("Bluesky down")
    _make_bot(bluesky=bluesky, card_lookup=lookup).process_mentions()
    mock_metric.assert_any_call("ReplyError")


# ── multi-card and limits ─────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_no_queries_in_mention_skipped(mock_metric):
    bluesky = _make_bluesky([_make_mention("hello there")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_not_called()
    mock_metric.assert_not_called()


@patch("bot.bot.record_metric")
def test_max_cards_per_mention_enforced(mock_metric):
    text = "[[A]] [[B]] [[C]] [[D]] [[E]]"
    bluesky = _make_bluesky([_make_mention(text)])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    # 4 card replies + 1 limit notice = 5 calls
    assert bluesky.reply_to_mention.call_count == 5


@patch("bot.bot.record_metric")
def test_limit_notice_text(mock_metric):
    text = "[[A]] [[B]] [[C]] [[D]] [[E]]"
    bluesky = _make_bluesky([_make_mention(text)])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    last_text = bluesky.reply_to_mention.call_args[0][1]
    assert "Only 4 cards" in last_text


# ── rulings mode (additional) ─────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_rulings_mode_card_not_found_replies_with_message(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[?zzzzz]]")])
    lookup = _make_card_lookup()
    lookup.find_card.return_value = None
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "zzzzz" in text


@patch("bot.bot.record_metric")
def test_rulings_mode_threads_overflow_text(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[?Lightning Bolt]]")])
    long_ruling = {
        "source": "wotc",
        "published_at": "2023-01-01",
        "comment": "word " * 70,
    }
    lookup = _make_card_lookup(rulings=[long_ruling])
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    assert bluesky.reply_in_thread.call_count >= 1


# ── image mode (additional) ───────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_image_mode_card_not_found_replies_with_message(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[!zzzzz]]")])
    lookup = _make_card_lookup()
    lookup.find_card.return_value = None
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "zzzzz" in text


@patch("bot.bot.record_metric")
def test_image_mode_fetch_error_still_replies(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[!Lightning Bolt]]")])
    lookup = _make_card_lookup()
    lookup.fetch_image.side_effect = RuntimeError("network error")
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert text == "Lightning Bolt"


# ── normal mode (additional) ──────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_normal_mode_image_fetch_error_still_replies(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    lookup = _make_card_lookup()
    lookup.fetch_image.side_effect = RuntimeError("network error")
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()
    args = bluesky.reply_to_mention.call_args[0]
    image_arg = args[2] if len(args) > 2 else None
    assert image_arg is None


# ── card limit error handling ─────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_card_limit_reply_error_silently_caught(mock_metric):
    text = "[[A]] [[B]] [[C]] [[D]] [[E]]"
    bluesky = _make_bluesky([_make_mention(text)])
    bluesky.reply_to_mention.side_effect = [
        PostRef(uri="at://r/1", cid="c1"),
        PostRef(uri="at://r/2", cid="c2"),
        PostRef(uri="at://r/3", cid="c3"),
        PostRef(uri="at://r/4", cid="c4"),
        RuntimeError("limit reply failed"),
    ]
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()  # must not raise


# ── random mode ───────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_random_mode_calls_random_card_not_find_card(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[*]]")])
    lookup = _make_card_lookup()
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    lookup.random_card.assert_called_once()
    lookup.find_card.assert_not_called()


@patch("bot.bot.record_metric")
def test_random_mode_replies_with_card_text(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[*]]")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "Lightning Bolt" in text


@patch("bot.bot.record_metric")
def test_random_mode_attaches_image(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[*]]")])
    lookup = _make_card_lookup(image=b"\xff\xd8img")
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.upload_image.assert_called_once()
    image_arg = bluesky.reply_to_mention.call_args[0][2]
    assert image_arg is not None


@patch("bot.bot.record_metric")
def test_random_mode_no_image_when_fetch_returns_none(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[*]]")])
    lookup = _make_card_lookup(image=None)
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    args = bluesky.reply_to_mention.call_args[0]
    image_arg = args[2] if len(args) > 2 else None
    assert image_arg is None


@patch("bot.bot.record_metric")
def test_random_mode_records_metric(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[*]]")])
    _make_bot(bluesky=bluesky).process_mentions()
    mock_metric.assert_any_call("CardLookup", {"Mode": "random"})


@patch("bot.bot.record_metric")
def test_random_mode_error_sends_error_reply(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[*]]")])
    lookup = _make_card_lookup()
    lookup.random_card.side_effect = RuntimeError("Scryfall down")
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    mock_metric.assert_any_call("ProcessingError")
    bluesky.reply_to_mention.assert_called_once()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "went wrong" in text


# ── lazy block list loading ───────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_block_list_fetched_when_not_initialized(mock_metric):
    bluesky = _make_bluesky([])
    bluesky.fetch_blocked_dids.return_value = {"did:plc:bad"}
    rate_limiter = _make_rate_limiter()
    bot = _make_bot(
        bluesky=bluesky, rate_limiter=rate_limiter, blocks_initialized=False
    )
    bot.process_mentions()
    bluesky.fetch_blocked_dids.assert_called_once()
    assert rate_limiter.is_blocked("did:plc:bad")
    mock_metric.assert_any_call("BlockListLoaded")


@patch("bot.bot.record_metric")
def test_block_list_not_fetched_when_already_initialized(mock_metric):
    bluesky = _make_bluesky([])
    bot = _make_bot(bluesky=bluesky, blocks_initialized=True)
    bot.process_mentions()
    bluesky.fetch_blocked_dids.assert_not_called()


@patch("bot.bot.record_metric")
def test_block_list_fetch_failure_continues_processing(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    bluesky.fetch_blocked_dids.side_effect = RuntimeError("network error")
    bot = _make_bot(bluesky=bluesky, blocks_initialized=False)
    bot.process_mentions()
    mock_metric.assert_any_call("BlockListLoadFailed")
    bluesky.reply_to_mention.assert_called_once()


@patch("bot.bot.record_metric")
def test_block_list_retried_on_next_cycle_after_failure(mock_metric):
    bluesky = _make_bluesky([])
    bluesky.fetch_blocked_dids.side_effect = [
        RuntimeError("first failure"),
        {"did:plc:bad"},
    ]
    rate_limiter = _make_rate_limiter()
    bot = _make_bot(
        bluesky=bluesky, rate_limiter=rate_limiter, blocks_initialized=False
    )
    bot.process_mentions()
    assert not rate_limiter.is_blocked("did:plc:bad")
    bot.process_mentions()
    assert rate_limiter.is_blocked("did:plc:bad")


@patch("bot.bot.record_metric")
def test_block_list_not_retried_after_success(mock_metric):
    bluesky = _make_bluesky([])
    bluesky.fetch_blocked_dids.return_value = set()
    bot = _make_bot(bluesky=bluesky, blocks_initialized=False)
    bot.process_mentions()
    bot.process_mentions()
    assert bluesky.fetch_blocked_dids.call_count == 1


# ── rate limiting ─────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_rate_limited_mention_silently_dropped(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    rate_limiter = MagicMock()
    rate_limiter.record_mention.return_value = MagicMock(
        allowed=False, should_warn=False, should_block=False
    )
    bot = _make_bot(bluesky=bluesky, rate_limiter=rate_limiter)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_not_called()
    mock_metric.assert_any_call("RateLimitDrop")


@patch("bot.bot.record_metric")
def test_rate_limit_warning_sends_reply(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    rate_limiter = MagicMock()
    rate_limiter.record_mention.return_value = MagicMock(
        allowed=False, should_warn=True, should_block=False
    )
    bot = _make_bot(bluesky=bluesky, rate_limiter=rate_limiter)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "slow down" in text
    mock_metric.assert_any_call("RateLimitWarning")


@patch("bot.bot.record_metric")
def test_rate_limit_warning_reply_error_silently_caught(_):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    bluesky.reply_to_mention.side_effect = RuntimeError("network error")
    rate_limiter = MagicMock()
    rate_limiter.record_mention.return_value = MagicMock(
        allowed=False, should_warn=True, should_block=False
    )
    bot = _make_bot(bluesky=bluesky, rate_limiter=rate_limiter)
    bot.process_mentions()  # must not raise


@patch("bot.bot.record_metric")
def test_block_calls_bluesky_block_user(mock_metric):
    mention = _make_mention("[[Lightning Bolt]]", author_did="did:plc:badactor")
    bluesky = _make_bluesky([mention])
    rate_limiter = MagicMock()
    rate_limiter.record_mention.return_value = MagicMock(
        allowed=False, should_warn=False, should_block=True
    )
    bot = _make_bot(bluesky=bluesky, rate_limiter=rate_limiter)
    bot.process_mentions()
    bluesky.block_user.assert_called_once_with("did:plc:badactor")
    bluesky.reply_to_mention.assert_not_called()
    mock_metric.assert_any_call("UserBlocked")


@patch("bot.bot.record_metric")
def test_block_error_silently_caught(_):
    mention = _make_mention("[[Lightning Bolt]]", author_did="did:plc:badactor")
    bluesky = _make_bluesky([mention])
    bluesky.block_user.side_effect = RuntimeError("api error")
    rate_limiter = MagicMock()
    rate_limiter.record_mention.return_value = MagicMock(
        allowed=False, should_warn=False, should_block=True
    )
    bot = _make_bot(bluesky=bluesky, rate_limiter=rate_limiter)
    bot.process_mentions()  # must not raise


# ── start() ───────────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_start_calls_process_mentions_then_sleeps(mock_metric):
    bluesky = _make_bluesky([])
    sleep_calls = []

    def one_shot_sleep(s):
        sleep_calls.append(s)
        raise RuntimeError("stop loop")

    bot = _make_bot(bluesky=bluesky, sleep_fn=one_shot_sleep)
    try:
        bot.start()
    except RuntimeError:
        pass

    bluesky.get_new_mentions.assert_called_once()
    assert len(sleep_calls) == 1


@patch("bot.bot.record_metric")
def test_start_catches_process_mentions_exception(mock_metric):
    bluesky = _make_bluesky()
    bluesky.get_new_mentions.side_effect = RuntimeError("poll error")
    sleep_calls = []

    def one_shot_sleep(s):
        sleep_calls.append(s)
        raise RuntimeError("stop loop")

    bot = _make_bot(bluesky=bluesky, sleep_fn=one_shot_sleep)
    try:
        bot.start()
    except RuntimeError:
        pass

    assert len(sleep_calls) == 1
