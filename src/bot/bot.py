import re
import time
from typing import Any, Callable

from .bluesky_client import BlueskyClient, PostRef
from .card_formatter import (
    card_not_found_message,
    format_card,
    format_face_alt_text,
    format_legalities,
    format_prices,
    format_rulings,
    scryfall_error_message,
    split_into_chunks,
)
from .card_lookup import CardLookup
from .config import BotConfig
from .metrics import record_metric
from .query_parser import parse_card_queries
from .rate_limiter import RateLimiter
from .trivia import TriviaManager, format_trivia_post

MAX_POST_GRAPHEMES = 300

_RATE_LIMIT_WARNING = (
    "You've been sending too many card lookup requests."
    " Please slow down — if this continues you'll be blocked."
)

_TRIVIA_WORD = re.compile(r"\btrivia\b", re.IGNORECASE)
_TRIVIA_EMPTY_MSG = "Sorry, the trivia question bank is empty right now!"


class Bot:
    def __init__(
        self,
        bluesky: BlueskyClient,
        card_lookup: CardLookup,
        rate_limiter: RateLimiter,
        config: BotConfig | None = None,
        sleep_fn=None,
        blocks_initialized: bool = True,
        trivia_manager: TriviaManager | None = None,
        trivia_state_saver: Callable[[], None] | None = None,
    ) -> None:
        self._bluesky = bluesky
        self._card_lookup = card_lookup
        self._rate_limiter = rate_limiter
        self._config = config or BotConfig()
        self._sleep = sleep_fn or time.sleep
        self._blocks_initialized = blocks_initialized
        self._trivia = trivia_manager
        self._save_trivia_state = trivia_state_saver

    def process_mentions(self) -> None:
        if not self._blocks_initialized:
            try:
                dids = self._bluesky.fetch_blocked_dids()
                self._rate_limiter.populate_blocked(dids)
                self._blocks_initialized = True
                record_metric("BlockListLoaded")
            except Exception as err:
                print("Failed to load block list, will retry next cycle:", err)
                record_metric("BlockListLoadFailed")

        if self._trivia:
            self._trivia.expire_old()

        mentions = self._bluesky.get_new_mentions()
        trivia_state_changed = False

        for mention in mentions:
            # --- Trivia answer check (no rate limiting) ---
            if self._trivia:
                pending = self._trivia.get_pending(mention.author_did)
                if pending and mention.parent_uri == pending.trivia_post_uri:
                    correct = self._trivia.check_answer(pending, mention.text)
                    self._trivia.resolve_pending(mention.author_did)
                    trivia_state_changed = True
                    record_metric("TriviaAnswered", {"Correct": str(correct)})
                    try:
                        if correct:
                            reply = f"Correct! The answer was: {pending.answer}"
                        else:
                            reply = f"Not quite! The answer was: {pending.answer}"
                        self._bluesky.reply_to_mention(mention, reply)
                    except Exception as err:
                        print("Failed to send trivia result:", err)
                    continue

            # --- Skip plain reply notifications that aren't trivia answers ---
            if mention.reason != "mention":
                continue

            decision = self._rate_limiter.record_mention(mention.author_did)

            if decision.should_block:
                record_metric("UserBlocked")
                try:
                    self._bluesky.block_user(mention.author_did)
                except Exception as err:
                    print(f"Failed to block user {mention.author_did}:", err)
                continue

            if decision.should_warn:
                record_metric("RateLimitWarning")
                try:
                    self._bluesky.reply_to_mention(mention, _RATE_LIMIT_WARNING)
                except Exception as err:
                    print("Failed to send rate limit warning:", err)
                continue

            if not decision.allowed:
                record_metric("RateLimitDrop")
                continue

            # --- Trivia trigger ---
            if self._trivia and _TRIVIA_WORD.search(mention.text):
                if not self._trivia.has_questions():
                    try:
                        self._bluesky.reply_to_mention(mention, _TRIVIA_EMPTY_MSG)
                    except Exception as err:
                        print("Failed to send trivia empty reply:", err)
                    continue

                question = self._trivia.get_random_question()
                try:
                    chunks = split_into_chunks(
                        format_trivia_post(question), MAX_POST_GRAPHEMES
                    )
                    root = PostRef(uri=mention.root_uri, cid=mention.root_cid)
                    post_ref = self._bluesky.reply_to_mention(mention, chunks[0])
                    for chunk in chunks[1:]:
                        post_ref = self._bluesky.reply_in_thread(root, post_ref, chunk)
                    self._trivia.set_pending(mention.author_did, question, post_ref.uri)
                    trivia_state_changed = True
                    record_metric("TriviaQuestionAsked")
                except Exception as err:
                    print("Failed to send trivia question:", err)
                continue

            # --- Card query processing ---
            queries = parse_card_queries(mention.text)
            if not queries:
                continue

            max_cards = self._config.max_cards_per_mention
            to_process = queries[:max_cards]
            has_more = len(queries) > max_cards
            record_metric("MentionProcessed")

            for query in to_process:
                card_name = query.name
                try:
                    mode = query.mode or "normal"

                    if query.mode == "random":
                        card = self._card_lookup.random_card()
                        card_name = card.get("name", "random card")
                        record_metric("CardLookup", {"Mode": "random"})
                    else:
                        card = self._card_lookup.find_card(
                            query.name, query.set_code, query.collector_number
                        )
                        record_metric("CardLookup", {"Mode": mode})
                        if not card:
                            record_metric("CardNotFound", {"Mode": mode})

                    match query.mode:
                        case "prices":
                            not_found = card_not_found_message(card_name)
                            text = format_prices(card) if card else not_found
                            self._bluesky.reply_to_mention(mention, text)

                        case "legality":
                            not_found = card_not_found_message(card_name)
                            text = format_legalities(card) if card else not_found
                            self._bluesky.reply_to_mention(mention, text)

                        case "rulings":
                            if not card:
                                not_found = card_not_found_message(card_name)
                                self._bluesky.reply_to_mention(mention, not_found)
                            else:
                                rulings = self._card_lookup.find_rulings(card)
                                full_text = format_rulings(card, rulings)
                                chunks = split_into_chunks(
                                    full_text, MAX_POST_GRAPHEMES
                                )
                                root = PostRef(
                                    uri=mention.root_uri, cid=mention.root_cid
                                )
                                prev_ref = self._bluesky.reply_to_mention(
                                    mention, chunks[0]
                                )
                                for chunk in chunks[1:]:
                                    prev_ref = self._bluesky.reply_in_thread(
                                        root, prev_ref, chunk
                                    )

                        case "image":
                            if not card:
                                not_found = card_not_found_message(card_name)
                                self._bluesky.reply_to_mention(mention, not_found)
                            else:
                                images: list[dict[str, Any]] | None = None
                                try:
                                    image_list = [
                                        {
                                            "blob": self._bluesky.upload_image(
                                                img, "image/jpeg"
                                            ),
                                            "alt": format_face_alt_text(card, i),
                                        }
                                        for i, img in enumerate(
                                            self._card_lookup.fetch_images(card)
                                        )
                                    ]
                                    if image_list:
                                        images = image_list
                                except Exception as err:
                                    print(
                                        f"Failed to fetch/upload image"
                                        f' for "{card_name}":',
                                        err,
                                    )
                                card_display = card.get("name", card_name)
                                self._bluesky.reply_to_mention(
                                    mention, card_display, images
                                )

                        case _:  # normal and random
                            not_found = card_not_found_message(card_name)
                            full_text = format_card(card) if card else not_found
                            chunks = split_into_chunks(full_text, MAX_POST_GRAPHEMES)

                            images = None
                            if card:
                                try:
                                    image_list = [
                                        {
                                            "blob": self._bluesky.upload_image(
                                                img, "image/jpeg"
                                            ),
                                            "alt": format_face_alt_text(card, i),
                                        }
                                        for i, img in enumerate(
                                            self._card_lookup.fetch_images(card)
                                        )
                                    ]
                                    if image_list:
                                        images = image_list
                                except Exception as err:
                                    print(
                                        f"Failed to fetch/upload image"
                                        f' for "{card_name}":',
                                        err,
                                    )

                            root = PostRef(uri=mention.root_uri, cid=mention.root_cid)
                            prev_ref = self._bluesky.reply_to_mention(
                                mention, chunks[0], images
                            )
                            for chunk in chunks[1:]:
                                prev_ref = self._bluesky.reply_in_thread(
                                    root, prev_ref, chunk
                                )

                except Exception as err:
                    print(f'Failed to process mention for "{card_name}":', err)
                    record_metric("ProcessingError")
                    try:
                        self._bluesky.reply_to_mention(
                            mention, scryfall_error_message(card_name)
                        )
                    except Exception as reply_err:
                        print(
                            f'Failed to send error reply for "{card_name}":', reply_err
                        )
                        record_metric("ReplyError")

            if has_more:
                try:
                    n = max_cards
                    limit_msg = (
                        f"Only {n} cards can be looked up per mention."
                        " Please send a new mention for the remaining cards."
                    )
                    self._bluesky.reply_to_mention(mention, limit_msg)
                except Exception as err:
                    print("Failed to send card limit reply:", err)

        if trivia_state_changed and self._save_trivia_state:
            self._save_trivia_state()

    # Runs forever — polls for mentions, processes them sequentially to respect
    # Scryfall's 1 req/sec limit, then sleeps before the next cycle.
    def start(self) -> None:
        print("Bot started, polling for mentions every"
              f" {self._config.poll_interval_seconds}s...")
        while True:
            try:
                self.process_mentions()
            except Exception as err:
                print("Error during poll cycle:", err)
            self._sleep(self._config.poll_interval_seconds)
