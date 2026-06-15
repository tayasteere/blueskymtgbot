import time
import urllib.parse
from typing import Literal, TypedDict

import httpx

from .metrics import record_metric

LegalityStatus = Literal["legal", "not_legal", "banned", "restricted"]
Legalities = dict[str, str]


class ImageUris(TypedDict, total=False):
    normal: str
    large: str


class CardFace(TypedDict, total=False):
    image_uris: ImageUris
    name: str
    mana_cost: str
    type_line: str
    oracle_text: str
    flavor_text: str
    artist: str


class CardPrices(TypedDict, total=False):
    usd: str | None
    usd_foil: str | None
    usd_etched: str | None
    eur: str | None
    eur_foil: str | None
    tix: str | None


class Ruling(TypedDict):
    source: str
    published_at: str
    comment: str


class CardData(TypedDict, total=False):
    name: str
    mana_cost: str
    type_line: str
    oracle_text: str
    rarity: str
    set: str
    set_name: str
    image_uris: ImageUris
    card_faces: list[CardFace]
    prices: CardPrices
    legalities: Legalities
    id: str
    rulings_uri: str
    flavor_text: str
    artist: str


class CardLookup:
    BASE_URL = "https://api.scryfall.com"
    MIN_REQUEST_INTERVAL_S = 1.0
    RATE_LIMIT_BACKOFF_S = 30.0

    def __init__(
        self,
        user_agent: str,
        client: httpx.Client | None = None,
        sleep_fn=None,
        clock_fn=None,
    ) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        self._sleep = sleep_fn or time.sleep
        self._clock = clock_fn or time.monotonic
        self._last_request_at: float = 0.0

    # Enforces Scryfall's rate limit policy: no more than one request per second.
    # On 429, waits 30 seconds and retries once before returning the response.
    def _throttled_fetch(self, url: str) -> httpx.Response:
        elapsed = self._clock() - self._last_request_at
        if elapsed < self.MIN_REQUEST_INTERVAL_S:
            self._sleep(self.MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_at = self._clock()

        response = self._client.get(url)

        if response.status_code == 429:
            print(
                f"Rate limited by Scryfall, backing off for"
                f" {self.RATE_LIMIT_BACKOFF_S}s: {url}"
            )
            record_metric("RateLimitHit")
            self._sleep(self.RATE_LIMIT_BACKOFF_S)
            print(f"Retrying after rate limit backoff: {url}")
            response = self._client.get(url)

        return response

    def find_card(
        self,
        name: str,
        set_code: str | None = None,
        collector_number: str | None = None,
    ) -> CardData | None:
        if set_code and collector_number:
            url = (
                f"{self.BASE_URL}/cards"
                f"/{urllib.parse.quote(set_code.lower())}"
                f"/{urllib.parse.quote(collector_number)}"
            )
        elif set_code:
            url = (
                f"{self.BASE_URL}/cards/named"
                f"?fuzzy={urllib.parse.quote(name)}"
                f"&set={urllib.parse.quote(set_code)}"
            )
        else:
            url = f"{self.BASE_URL}/cards/named?fuzzy={urllib.parse.quote(name)}"

        response = self._throttled_fetch(url)

        # 404 = no match; 422 = ambiguous (multiple possible cards)
        if response.status_code in (404, 422):
            return None

        if not response.is_success:
            record_metric("ScryfallApiError")
            raise RuntimeError(
                f"Scryfall API error: {response.status_code} {response.reason_phrase}"
            )

        return response.json()

    def random_card(self) -> CardData:
        response = self._throttled_fetch(f"{self.BASE_URL}/cards/random")
        if not response.is_success:
            record_metric("ScryfallApiError")
            raise RuntimeError(
                f"Scryfall API error: {response.status_code} {response.reason_phrase}"
            )
        return response.json()

    def find_rulings(self, card: CardData) -> list[Ruling]:
        rulings_uri = card.get("rulings_uri")
        if not rulings_uri:
            return []

        response = self._throttled_fetch(rulings_uri)

        if not response.is_success:
            record_metric("ScryfallApiError")
            raise RuntimeError(
                f"Scryfall API error: {response.status_code} {response.reason_phrase}"
            )

        return response.json()["data"]

    def fetch_images(self, card: CardData) -> list[bytes]:
        card_faces = card.get("card_faces")
        if card_faces:
            urls = [
                (face.get("image_uris") or {}).get("normal")
                for face in card_faces
            ]
        else:
            image_uris = card.get("image_uris") or {}
            url = image_uris.get("normal")
            urls = [url] if url else []

        results: list[bytes] = []
        for url in urls:
            if not url:
                continue
            response = self._client.get(url)
            if not response.is_success:
                print(f"Image fetch failed ({response.status_code}): {url}")
                record_metric("ImageFetchFailure")
                continue
            results.append(response.content)
        return results
