import re
from dataclasses import dataclass
from typing import Literal

_CARD_QUERY_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")

CardQueryMode = Literal["normal", "image", "prices", "rulings", "legality", "random"]

_MODE_PREFIXES: dict[str, CardQueryMode] = {
    "!": "image",
    "$": "prices",
    "?": "rulings",
    "#": "legality",
}


@dataclass
class CardQuery:
    name: str
    set_code: str | None = None
    collector_number: str | None = None
    mode: CardQueryMode | None = None


def parse_card_queries(text: str) -> list[CardQuery]:
    queries: list[CardQuery] = []

    for match in _CARD_QUERY_PATTERN.finditer(text):
        parts = match.group(1).split("|")
        raw_name = parts[0].strip()
        if not raw_name:
            continue

        if raw_name == "*":
            queries.append(CardQuery(name="", mode="random"))
            continue

        mode: CardQueryMode | None = None
        if raw_name[0] in _MODE_PREFIXES:
            mode = _MODE_PREFIXES[raw_name[0]]
            raw_name = raw_name[1:].strip()
            if not raw_name:
                continue

        set_code = parts[1].strip() if len(parts) > 1 else None
        set_code = set_code or None
        collector_number = parts[2].strip() if len(parts) > 2 else None
        collector_number = collector_number or None

        queries.append(
            CardQuery(
                name=raw_name,
                set_code=set_code,
                collector_number=collector_number,
                mode=mode,
            )
        )

    return queries
