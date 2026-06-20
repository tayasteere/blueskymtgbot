from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from bot.bluesky_client import Mention, PostRef
from bot.bot import Bot
from bot.config import BotConfig, RateLimitConfig
from bot.rate_limiter import RateLimiter
from bot.trivia import PendingQuestion, TriviaManager, TriviaQuestion


def _make_mention(
    text="[[Lightning Bolt]]",
    uri="at://m1",
    cid="c1",
    root_uri="at://root",
    root_cid="croot",
    author_did="did:plc:user1",
    parent_uri="",
    parent_cid="",
    reason="mention",
):
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


def _make_card_lookup(card=None, rulings=None, images=None):
    lookup = MagicMock()
    lookup.find_card.return_value = card or _DEFAULT_CARD
    lookup.random_card.return_value = _DEFAULT_CARD
    lookup.find_rulings.return_value = rulings if rulings is not None else []
    lookup.fetch_images.return_value = images if images is not None else []
    lookup.autocomplete.return_value = None
    return lookup


def _make_rate_limiter(blocked_dids=None):
    return RateLimiter(RateLimitConfig(), blocked_dids=blocked_dids)


def _make_bot(
    bluesky=None,
    card_lookup=None,
    rate_limiter=None,
    sleep_fn=None,
    blocks_initialized=True,
    trivia_manager=None,
    trivia_state_saver=None,
):
    return Bot(
        bluesky=bluesky or _make_bluesky(),
        card_lookup=card_lookup or _make_card_lookup(),
        rate_limiter=rate_limiter or _make_rate_limiter(),
        config=BotConfig(),
        sleep_fn=sleep_fn or (lambda _: None),
        blocks_initialized=blocks_initialized,
        trivia_manager=trivia_manager,
        trivia_state_saver=trivia_state_saver,
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
    lookup = _make_card_lookup(images=[b"\xff\xd8img"])
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.upload_image.assert_called_once()
    images_arg = bluesky.reply_to_mention.call_args[0][2]
    assert images_arg is not None


@patch("bot.bot.record_metric")
def test_normal_mode_no_image_when_fetch_returns_empty(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    lookup = _make_card_lookup(images=[])
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    args = bluesky.reply_to_mention.call_args[0]
    images_arg = args[2] if len(args) > 2 else None
    assert images_arg is None


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
    lookup = _make_card_lookup(images=[b"\xff\xd8img"])
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


@patch("bot.bot.record_metric")
def test_card_not_found_includes_suggestion_when_available(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[lighning blt]]")])
    lookup = _make_card_lookup(card=None)
    lookup.find_card.return_value = None
    lookup.autocomplete.return_value = "Lightning Bolt"
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "[[Lightning Bolt]]" in text


@patch("bot.bot.record_metric")
def test_card_not_found_no_brackets_when_autocomplete_returns_none(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[zzzzz]]")])
    lookup = _make_card_lookup(card=None)
    lookup.find_card.return_value = None
    lookup.autocomplete.return_value = None
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "[[" not in text


@patch("bot.bot.record_metric")
def test_card_not_found_autocomplete_error_still_replies(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[zzzzz]]")])
    lookup = _make_card_lookup(card=None)
    lookup.find_card.return_value = None
    lookup.autocomplete.side_effect = RuntimeError("API error")
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()  # must not raise
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
def test_limit_notice_singular(mock_metric):
    text = "[[A]] [[B]] [[C]] [[D]] [[E]]"  # 5 queries → 1 omitted
    bluesky = _make_bluesky([_make_mention(text)])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    last_text = bluesky.reply_to_mention.call_args[0][1]
    assert "1 card omitted" in last_text
    assert "max 4" in last_text


@patch("bot.bot.record_metric")
def test_limit_notice_plural(mock_metric):
    text = "[[A]] [[B]] [[C]] [[D]] [[E]] [[F]]"  # 6 queries → 2 omitted
    bluesky = _make_bluesky([_make_mention(text)])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    last_text = bluesky.reply_to_mention.call_args[0][1]
    assert "2 cards omitted" in last_text
    assert "max 4" in last_text


# ── thread part numbering ─────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_threaded_rulings_include_part_numbers(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[?Lightning Bolt]]")])
    long_ruling = {
        "source": "wotc",
        "published_at": "2023-01-01",
        "comment": "word " * 70,
    }
    lookup = _make_card_lookup(rulings=[long_ruling])
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    first_text = bluesky.reply_to_mention.call_args[0][1]
    thread_text = bluesky.reply_in_thread.call_args[0][2]
    assert "(1/" in first_text
    assert "(2/" in thread_text


@patch("bot.bot.record_metric")
def test_single_chunk_card_has_no_part_number(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[Lightning Bolt]]")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "(1/" not in text


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
    lookup.fetch_images.side_effect = RuntimeError("network error")
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
    lookup.fetch_images.side_effect = RuntimeError("network error")
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()
    args = bluesky.reply_to_mention.call_args[0]
    images_arg = args[2] if len(args) > 2 else None
    assert images_arg is None


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
    lookup = _make_card_lookup(images=[b"\xff\xd8img"])
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    bluesky.upload_image.assert_called_once()
    images_arg = bluesky.reply_to_mention.call_args[0][2]
    assert images_arg is not None


@patch("bot.bot.record_metric")
def test_random_mode_no_image_when_fetch_returns_empty(mock_metric):
    bluesky = _make_bluesky([_make_mention("[[*]]")])
    lookup = _make_card_lookup(images=[])
    bot = _make_bot(bluesky=bluesky, card_lookup=lookup)
    bot.process_mentions()
    args = bluesky.reply_to_mention.call_args[0]
    images_arg = args[2] if len(args) > 2 else None
    assert images_arg is None


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


# ── trivia ────────────────────────────────────────────────────────────────────

_TRIVIA_POST_URI = "at://bot/post/trivia1"


def _make_trivia_manager(has_questions=True):
    mgr = MagicMock(spec=TriviaManager)
    mgr.has_questions.return_value = has_questions
    mgr.get_pending.return_value = None
    mgr.get_random_question.return_value = TriviaQuestion(
        question="Which instant deals 3 damage?",
        answer="Lightning Bolt",
        category="rules_text",
        answer_type="card_name",
        card_name="Lightning Bolt",
        oracle_id="abc",
    )
    return mgr


def _make_pending_question(trivia_post_uri=_TRIVIA_POST_URI):
    return PendingQuestion(
        question="Which instant deals 3 damage?",
        answer="Lightning Bolt",
        category="rules_text",
        answer_type="card_name",
        card_name="Lightning Bolt",
        trivia_post_uri=trivia_post_uri,
        asked_at=datetime.now(timezone.utc),
    )


@patch("bot.bot.record_metric")
def test_trivia_trigger_sends_question(mock_metric):
    mention = _make_mention(text="@bot trivia please")
    bluesky = _make_bluesky([mention])
    bluesky.reply_to_mention.return_value = PostRef(uri=_TRIVIA_POST_URI, cid="c1")
    mgr = _make_trivia_manager()
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "Which instant deals 3 damage?" in text


@patch("bot.bot.record_metric")
def test_trivia_trigger_records_metric(mock_metric):
    mention = _make_mention(text="trivia")
    bluesky = _make_bluesky([mention])
    bluesky.reply_to_mention.return_value = PostRef(uri=_TRIVIA_POST_URI, cid="c1")
    mgr = _make_trivia_manager()
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    mock_metric.assert_any_call("TriviaQuestionAsked")


@patch("bot.bot.record_metric")
def test_trivia_trigger_calls_set_pending(mock_metric):
    mention = _make_mention(text="trivia")
    bluesky = _make_bluesky([mention])
    bluesky.reply_to_mention.return_value = PostRef(uri=_TRIVIA_POST_URI, cid="c1")
    mgr = _make_trivia_manager()
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    mgr.set_pending.assert_called_once()
    args = mgr.set_pending.call_args[0]
    assert args[0] == "did:plc:user1"
    assert args[2] == _TRIVIA_POST_URI


@patch("bot.bot.record_metric")
def test_trivia_empty_bank_replies_with_message(mock_metric):
    mention = _make_mention(text="trivia")
    bluesky = _make_bluesky([mention])
    mgr = _make_trivia_manager(has_questions=False)
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "empty" in text.lower()


@patch("bot.bot.record_metric")
def test_trivia_trigger_case_insensitive(mock_metric):
    mention = _make_mention(text="TRIVIA")
    bluesky = _make_bluesky([mention])
    bluesky.reply_to_mention.return_value = PostRef(uri=_TRIVIA_POST_URI, cid="c1")
    mgr = _make_trivia_manager()
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    mgr.get_random_question.assert_called_once()


@patch("bot.bot.record_metric")
def test_plain_reply_matching_trivia_post_evaluated_as_answer(mock_metric):
    reply = _make_mention(
        text="Lightning Bolt",
        uri="at://user/reply/1",
        parent_uri=_TRIVIA_POST_URI,
        reason="reply",
    )
    bluesky = _make_bluesky([reply])
    mgr = _make_trivia_manager()
    mgr.get_pending.return_value = _make_pending_question()
    mgr.check_answer.return_value = True
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    mgr.check_answer.assert_called_once()
    mgr.resolve_pending.assert_called_once_with("did:plc:user1")
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "Correct" in text


@patch("bot.bot.record_metric")
def test_plain_reply_wrong_answer_replies_with_answer(mock_metric):
    reply = _make_mention(
        text="Counterspell",
        parent_uri=_TRIVIA_POST_URI,
        reason="reply",
    )
    bluesky = _make_bluesky([reply])
    mgr = _make_trivia_manager()
    mgr.get_pending.return_value = _make_pending_question()
    mgr.check_answer.return_value = False
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "Not quite" in text
    assert "Lightning Bolt" in text


@patch("bot.bot.record_metric")
def test_plain_reply_non_trivia_post_ignored(mock_metric):
    reply = _make_mention(
        text="some reply",
        parent_uri="at://bot/post/other",
        reason="reply",
    )
    bluesky = _make_bluesky([reply])
    mgr = _make_trivia_manager()
    mgr.get_pending.return_value = _make_pending_question(
        trivia_post_uri=_TRIVIA_POST_URI
    )
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    # Parent URI doesn't match → not a trivia answer, reason=="reply" → skip entirely
    bluesky.reply_to_mention.assert_not_called()


@patch("bot.bot.record_metric")
def test_plain_reply_no_pending_question_ignored(mock_metric):
    reply = _make_mention(
        text="Lightning Bolt",
        parent_uri=_TRIVIA_POST_URI,
        reason="reply",
    )
    bluesky = _make_bluesky([reply])
    mgr = _make_trivia_manager()
    mgr.get_pending.return_value = None  # no pending question
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_not_called()


@patch("bot.bot.record_metric")
def test_trivia_answer_bypasses_rate_limiter(mock_metric):
    reply = _make_mention(
        text="Lightning Bolt",
        parent_uri=_TRIVIA_POST_URI,
        reason="reply",
    )
    bluesky = _make_bluesky([reply])
    rate_limiter = MagicMock()
    mgr = _make_trivia_manager()
    mgr.get_pending.return_value = _make_pending_question()
    mgr.check_answer.return_value = True
    bot = _make_bot(bluesky=bluesky, rate_limiter=rate_limiter, trivia_manager=mgr)
    bot.process_mentions()
    rate_limiter.record_mention.assert_not_called()


@patch("bot.bot.record_metric")
def test_trivia_state_saver_called_after_question_asked(mock_metric):
    mention = _make_mention(text="trivia")
    bluesky = _make_bluesky([mention])
    bluesky.reply_to_mention.return_value = PostRef(uri=_TRIVIA_POST_URI, cid="c1")
    mgr = _make_trivia_manager()
    saver_calls = []
    bot = _make_bot(
        bluesky=bluesky,
        trivia_manager=mgr,
        trivia_state_saver=lambda: saver_calls.append(1),
    )
    bot.process_mentions()
    assert len(saver_calls) == 1


@patch("bot.bot.record_metric")
def test_trivia_state_saver_called_after_answer(mock_metric):
    reply = _make_mention(
        text="Lightning Bolt",
        parent_uri=_TRIVIA_POST_URI,
        reason="reply",
    )
    bluesky = _make_bluesky([reply])
    mgr = _make_trivia_manager()
    mgr.get_pending.return_value = _make_pending_question()
    mgr.check_answer.return_value = True
    saver_calls = []
    bot = _make_bot(
        bluesky=bluesky,
        trivia_manager=mgr,
        trivia_state_saver=lambda: saver_calls.append(1),
    )
    bot.process_mentions()
    assert len(saver_calls) == 1


@patch("bot.bot.record_metric")
def test_trivia_long_question_splits_into_thread(mock_metric):
    # "🃏 [Rules] " prefix = 10 chars; 295-char question → 305 total > 300
    long_question = "x" * 295
    mention = _make_mention(text="trivia")
    bluesky = _make_bluesky([mention])
    bluesky.reply_to_mention.return_value = PostRef(uri=_TRIVIA_POST_URI, cid="c1")
    mgr = _make_trivia_manager()
    mgr.get_random_question.return_value = TriviaQuestion(
        question=long_question,
        answer="Lightning Bolt",
        category="rules_text",
        answer_type="card_name",
        card_name="Lightning Bolt",
        oracle_id="abc",
    )
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    assert bluesky.reply_in_thread.call_count >= 1
    # set_pending must reference the last post so the user replies to the right post
    assert mgr.set_pending.call_args[0][2] == bluesky.reply_in_thread.return_value.uri


@patch("bot.bot.record_metric")
def test_no_trivia_manager_plain_replies_ignored(mock_metric):
    reply = _make_mention(text="something", reason="reply")
    bluesky = _make_bluesky([reply])
    bot = _make_bot(bluesky=bluesky)  # no trivia_manager
    bot.process_mentions()
    bluesky.reply_to_mention.assert_not_called()


# ── help trigger ──────────────────────────────────────────────────────────────


@patch("bot.bot.record_metric")
def test_help_trigger_replies_with_syntax_guide(mock_metric):
    bluesky = _make_bluesky([_make_mention("help")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "[[Card Name]]" in text
    assert "image only" in text
    assert "prices" in text
    assert "rulings" in text
    assert "legalities" in text


@patch("bot.bot.record_metric")
def test_help_trigger_case_insensitive(mock_metric):
    bluesky = _make_bluesky([_make_mention("HELP")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_called_once()


@patch("bot.bot.record_metric")
def test_help_not_triggered_when_card_queries_present(mock_metric):
    bluesky = _make_bluesky([_make_mention("help [[Lightning Bolt]]")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "Lightning Bolt" in text


@patch("bot.bot.record_metric")
def test_help_not_triggered_without_word(mock_metric):
    bluesky = _make_bluesky([_make_mention("I need assistance")])
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()
    bluesky.reply_to_mention.assert_not_called()


@patch("bot.bot.record_metric")
def test_help_includes_trivia_hint_when_trivia_configured(mock_metric):
    bluesky = _make_bluesky([_make_mention("help")])
    mgr = _make_trivia_manager()
    bot = _make_bot(bluesky=bluesky, trivia_manager=mgr)
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "trivia" in text.lower()


@patch("bot.bot.record_metric")
def test_help_excludes_trivia_hint_when_no_trivia(mock_metric):
    bluesky = _make_bluesky([_make_mention("help")])
    bot = _make_bot(bluesky=bluesky)  # no trivia_manager
    bot.process_mentions()
    text = bluesky.reply_to_mention.call_args[0][1]
    assert "trivia" not in text.lower()


@patch("bot.bot.record_metric")
def test_help_reply_error_silently_caught(mock_metric):
    bluesky = _make_bluesky([_make_mention("help")])
    bluesky.reply_to_mention.side_effect = RuntimeError("network error")
    bot = _make_bot(bluesky=bluesky)
    bot.process_mentions()  # must not raise
