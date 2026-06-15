from .card_lookup import CardData, CardPrices, Ruling

_MAJOR_FORMATS: list[tuple[str, str]] = [
    ("standard", "Standard"),
    ("pioneer", "Pioneer"),
    ("modern", "Modern"),
    ("legacy", "Legacy"),
    ("vintage", "Vintage"),
    ("commander", "Commander"),
    ("pauper", "Pauper"),
    ("historic", "Historic"),
]

_LEGALITY_LABELS: dict[str, str] = {
    "legal": "Legal",
    "not_legal": "Not Legal",
    "banned": "Banned",
    "restricted": "Restricted",
}

_MAX_DISPLAY_GRAPHEMES = 50


def _pt_loyalty(data: dict) -> str | None:
    power = data.get("power")
    toughness = data.get("toughness")
    if power is not None and toughness is not None:
        return f"{power}/{toughness}"
    loyalty = data.get("loyalty")
    if loyalty is not None:
        return f"[{loyalty}]"
    return None


def format_card(card: CardData) -> str:
    name = card.get("name", "")
    mana_cost = card.get("mana_cost")
    name_line = f"{name} {mana_cost}" if mana_cost else name

    set_code = card.get("set")
    meta_parts = [
        p
        for p in [
            card.get("type_line"),
            card.get("rarity", "").capitalize() or None,
            set_code.upper() if set_code else None,
        ]
        if p
    ]
    meta_line = " · ".join(meta_parts)

    faces = card.get("card_faces") or []
    if faces:
        face_parts = []
        for face in faces:
            segments = [p for p in [face.get("oracle_text"), _pt_loyalty(face)] if p]
            if segments:
                face_parts.append("\n".join(segments))
        oracle_text = "\n//\n".join(face_parts) if face_parts else None
        extra = None
    else:
        oracle_text = card.get("oracle_text")
        extra = _pt_loyalty(card)

    parts = [p for p in [name_line, meta_line, oracle_text, extra] if p]
    return "\n".join(parts)


def format_card_alt_text(card: CardData) -> str:
    base = format_card(card)
    faces = card.get("card_faces") or []
    first_face = faces[0] if faces else {}
    flavor_text = card.get("flavor_text") or first_face.get("flavor_text")
    artist = card.get("artist") or first_face.get("artist")
    parts = [base]
    if flavor_text:
        parts.append(f'"{flavor_text}"')
    if artist:
        parts.append(f"Art: {artist}")
    return "\n".join(parts)


def format_face_alt_text(card: CardData, face_index: int = 0) -> str:
    faces = card.get("card_faces") or []
    if not faces or face_index >= len(faces):
        return format_card_alt_text(card)
    face = faces[face_index]
    name = face.get("name", "")
    mana_cost = face.get("mana_cost")
    name_line = f"{name} {mana_cost}" if mana_cost else name
    set_code = card.get("set")
    meta_parts = [
        p
        for p in [
            face.get("type_line"),
            card.get("rarity"),
            set_code.upper() if set_code else None,
        ]
        if p
    ]
    meta_line = " · ".join(meta_parts)
    parts = [p for p in [name_line, meta_line, face.get("oracle_text")] if p]
    flavor_text = face.get("flavor_text")
    artist = face.get("artist")
    if flavor_text:
        parts.append(f'"{flavor_text}"')
    if artist:
        parts.append(f"Art: {artist}")
    return "\n".join(parts)


def split_into_chunks(text: str, limit: int) -> list[str]:
    chars = list(text)
    if len(chars) <= limit:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(chars):
        if len(chars) - start <= limit:
            chunks.append("".join(chars[start:]))
            break

        # Search backwards from limit for a whitespace boundary
        break_at = limit
        while break_at > 0 and chars[start + break_at] not in (" ", "\n"):
            break_at -= 1

        if break_at == 0:
            break_at = limit

        chunks.append("".join(chars[start : start + break_at]))
        start += break_at

        while start < len(chars) and chars[start] in (" ", "\n"):
            start += 1

    return chunks


def format_prices(card: CardData) -> str:
    name = card.get("name", "")
    set_code = card.get("set")
    meta_parts = [
        p
        for p in [
            card.get("set_name"),
            card.get("rarity"),
            set_code.upper() if set_code else None,
        ]
        if p
    ]
    header = f"{name} — {' · '.join(meta_parts)}"

    prices: CardPrices = card.get("prices") or {}

    non_foil: list[str] = []
    if prices.get("usd"):
        non_foil.append(f"${prices['usd']}")
    if prices.get("eur"):
        non_foil.append(f"€{prices['eur']}")
    if prices.get("tix"):
        non_foil.append(f"{prices['tix']} TIX")

    foil: list[str] = []
    if prices.get("usd_foil"):
        foil.append(f"${prices['usd_foil']}")
    if prices.get("usd_etched"):
        foil.append(f"${prices['usd_etched']} (etched)")
    if prices.get("eur_foil"):
        foil.append(f"€{prices['eur_foil']}")

    lines = [header]
    if non_foil:
        lines.append(" • ".join(non_foil))
    if foil:
        lines.append(f"Foil: {' • '.join(foil)}")
    if not non_foil and not foil:
        lines.append("No price data available.")

    return "\n".join(lines)


def format_legalities(card: CardData) -> str:
    header = f"{card.get('name', '')} — Legalities"
    legalities: dict[str, str] = card.get("legalities") or {}
    lines = []
    for key, label in _MAJOR_FORMATS:
        status = _LEGALITY_LABELS.get(legalities.get(key, "not_legal"), "Not Legal")
        lines.append(f"{label}: {status}")
    return "\n".join([header, *lines])


def format_rulings(card: CardData, rulings: list[Ruling]) -> str:
    header = f"Rulings for {card.get('name', '')}"
    if not rulings:
        return f"{header}\nNo official rulings."
    lines = [f"{r['published_at']}: {r['comment']}" for r in rulings]
    return "\n\n".join([header, *lines])


def scryfall_error_message(card_name: str) -> str:
    chars = list(card_name)
    display = "".join(chars[:_MAX_DISPLAY_GRAPHEMES])
    if len(chars) > _MAX_DISPLAY_GRAPHEMES:
        display += "…"
    return f'Something went wrong looking up "{display}". Please try again later.'


def card_not_found_message(card_name: str) -> str:
    chars = list(card_name)
    display = "".join(chars[:_MAX_DISPLAY_GRAPHEMES])
    if len(chars) > _MAX_DISPLAY_GRAPHEMES:
        display += "…"
    return (
        f'Could not determine the card based on "{display}". Please be more specific.'
    )
