import time
from typing import Any

from .bluesky_client import BlueskyClient, PostRef
from .card_formatter import (
    card_not_found_message,
    format_card,
    format_legalities,
    format_prices,
    format_rulings,
    scryfall_error_message,
    split_into_chunks,
)
from .card_lookup import CardLookup
from .metrics import record_metric
from .query_parser import parse_card_queries

POLL_INTERVAL_S = 5.0
MAX_POST_GRAPHEMES = 300
MAX_CARDS_PER_MENTION = 4


class Bot:
    def __init__(
        self,
        bluesky: BlueskyClient,
        card_lookup: CardLookup,
        poll_interval_s: float = POLL_INTERVAL_S,
        sleep_fn=None,
    ) -> None:
        self._bluesky = bluesky
        self._card_lookup = card_lookup
        self._poll_interval_s = poll_interval_s
        self._sleep = sleep_fn or time.sleep

    def process_mentions(self) -> None:
        mentions = self._bluesky.get_new_mentions()

        for mention in mentions:
            queries = parse_card_queries(mention.text)
            if not queries:
                continue

            to_process = queries[:MAX_CARDS_PER_MENTION]
            has_more = len(queries) > MAX_CARDS_PER_MENTION
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
                                image: dict[str, Any] | None = None
                                try:
                                    image_data = self._card_lookup.fetch_image(card)
                                    if image_data:
                                        blob = self._bluesky.upload_image(
                                            image_data, "image/jpeg"
                                        )
                                        image = {"blob": blob, "alt": format_card(card)}
                                except Exception as err:
                                    print(
                                        f"Failed to fetch/upload image"
                                        f' for "{card_name}":',
                                        err,
                                    )
                                card_display = card.get("name", card_name)
                                self._bluesky.reply_to_mention(
                                    mention, card_display, image
                                )

                        case _:  # normal
                            not_found = card_not_found_message(card_name)
                            full_text = format_card(card) if card else not_found
                            chunks = split_into_chunks(full_text, MAX_POST_GRAPHEMES)

                            image = None
                            if card:
                                try:
                                    image_data = self._card_lookup.fetch_image(card)
                                    if image_data:
                                        blob = self._bluesky.upload_image(
                                            image_data, "image/jpeg"
                                        )
                                        image = {"blob": blob, "alt": full_text}
                                except Exception as err:
                                    print(
                                        f"Failed to fetch/upload image"
                                        f' for "{card_name}":',
                                        err,
                                    )

                            root = PostRef(uri=mention.root_uri, cid=mention.root_cid)
                            prev_ref = self._bluesky.reply_to_mention(
                                mention, chunks[0], image
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
                    n = MAX_CARDS_PER_MENTION
                    limit_msg = (
                        f"Only {n} cards can be looked up per mention."
                        " Please send a new mention for the remaining cards."
                    )
                    self._bluesky.reply_to_mention(mention, limit_msg)
                except Exception as err:
                    print("Failed to send card limit reply:", err)

    # Runs forever — polls for mentions, processes them sequentially to respect
    # Scryfall's 1 req/sec limit, then sleeps before the next cycle.
    def start(self) -> None:
        print("Bot started, polling for mentions every 5s...")
        while True:
            try:
                self.process_mentions()
            except Exception as err:
                print("Error during poll cycle:", err)
            self._sleep(self._poll_interval_s)
