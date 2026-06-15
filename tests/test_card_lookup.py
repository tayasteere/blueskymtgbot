from unittest.mock import MagicMock, patch

import pytest

from bot.card_lookup import CardLookup

_USER_AGENT = "TestBot/1.0"


def _mock_response(status_code: int, json_data=None, content: bytes = b""):
    r = MagicMock()
    r.status_code = status_code
    r.is_success = 200 <= status_code < 300
    r.reason_phrase = "OK" if r.is_success else "Error"
    r.json.return_value = json_data
    r.content = content
    return r


def _make_lookup(client=None, sleep_fn=None, clock_fn=None) -> CardLookup:
    kwargs = {"user_agent": _USER_AGENT}
    if client is not None:
        kwargs["client"] = client
    if sleep_fn is not None:
        kwargs["sleep_fn"] = sleep_fn
    if clock_fn is not None:
        kwargs["clock_fn"] = clock_fn
    return CardLookup(**kwargs)


BOLT = {"name": "Lightning Bolt", "mana_cost": "{R}", "type_line": "Instant"}


# ── find_card ────────────────────────────────────────────────────────────────


@patch("bot.card_lookup.record_metric")
def test_find_card_basic(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, BOLT)
    lookup = _make_lookup(client=client, sleep_fn=lambda _: None)
    result = lookup.find_card("Lightning Bolt")
    assert result == BOLT
    client.get.assert_called_once_with(
        "https://api.scryfall.com/cards/named?fuzzy=Lightning%20Bolt"
    )


@patch("bot.card_lookup.record_metric")
def test_find_card_with_set(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, BOLT)
    _make_lookup(client=client, sleep_fn=lambda _: None).find_card(
        "Lightning Bolt", set_code="M10"
    )
    client.get.assert_called_once_with(
        "https://api.scryfall.com/cards/named?fuzzy=Lightning%20Bolt&set=M10"
    )


@patch("bot.card_lookup.record_metric")
def test_find_card_with_set_and_number(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, BOLT)
    _make_lookup(client=client, sleep_fn=lambda _: None).find_card(
        "Island", set_code="ZEN", collector_number="235"
    )
    client.get.assert_called_once_with("https://api.scryfall.com/cards/zen/235")


@patch("bot.card_lookup.record_metric")
def test_find_card_set_lowercased_in_url(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, BOLT)
    _make_lookup(client=client, sleep_fn=lambda _: None).find_card(
        "Island", set_code="ZEN", collector_number="1"
    )
    url = client.get.call_args[0][0]
    assert "/zen/" in url


@patch("bot.card_lookup.record_metric")
def test_find_card_404_returns_none(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(404)
    result = _make_lookup(client=client, sleep_fn=lambda _: None).find_card("zzzzz")
    assert result is None


@patch("bot.card_lookup.record_metric")
def test_find_card_422_returns_none(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(422)
    result = _make_lookup(client=client, sleep_fn=lambda _: None).find_card("jace")
    assert result is None


@patch("bot.card_lookup.record_metric")
def test_find_card_5xx_raises_and_records_metric(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(500)
    with pytest.raises(RuntimeError, match="Scryfall API error: 500"):
        _make_lookup(client=client, sleep_fn=lambda _: None).find_card("Lightning Bolt")
    mock_metric.assert_called_with("ScryfallApiError")


# ── rate limiting ────────────────────────────────────────────────────────────


@patch("bot.card_lookup.record_metric")
def test_rate_limit_sleep_between_fast_requests(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, BOLT)

    sleep_calls: list[float] = []
    clock_values = iter([0.0, 0.0, 0.3, 0.3])  # two requests, 0.3s apart
    _make_lookup(
        client=client,
        sleep_fn=lambda s: sleep_calls.append(s),
        clock_fn=lambda: next(clock_values),
    ).find_card("Lightning Bolt")

    sleep_calls.clear()
    # second request happens 0.3s after the first — should sleep ~0.7s
    lookup = _make_lookup(
        client=client,
        sleep_fn=lambda s: sleep_calls.append(s),
        clock_fn=lambda: next(iter([0.0, 0.0, 0.3, 0.3])),
    )
    lookup._last_request_at = 0.0
    lookup._clock = iter([0.3, 0.3]).__next__  # type: ignore[assignment]
    lookup.find_card("Lightning Bolt")
    assert sleep_calls and sleep_calls[0] == pytest.approx(0.7, abs=0.01)


@patch("bot.card_lookup.record_metric")
def test_rate_limit_no_sleep_when_enough_time_elapsed(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, BOLT)
    sleep_calls: list[float] = []
    # clock returns 1.5s since last request — no sleep needed
    clock_values = iter([1.5, 1.5])
    lookup = _make_lookup(
        client=client,
        sleep_fn=lambda s: sleep_calls.append(s),
        clock_fn=lambda: next(clock_values),
    )
    lookup._last_request_at = 0.0
    lookup.find_card("Lightning Bolt")
    assert sleep_calls == []


@patch("bot.card_lookup.record_metric")
def test_429_records_metric_and_retries(mock_metric):
    client = MagicMock()
    client.get.side_effect = [
        _mock_response(429),
        _mock_response(200, BOLT),
    ]
    sleep_calls: list[float] = []
    result = _make_lookup(
        client=client,
        sleep_fn=lambda s: sleep_calls.append(s),
        clock_fn=lambda: 999.0,
    ).find_card("Lightning Bolt")

    assert result == BOLT
    assert client.get.call_count == 2
    assert any(s == CardLookup.RATE_LIMIT_BACKOFF_S for s in sleep_calls)
    mock_metric.assert_any_call("RateLimitHit")


# ── random_card ───────────────────────────────────────────────────────────────


@patch("bot.card_lookup.record_metric")
def test_random_card_returns_data(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, BOLT)
    result = _make_lookup(client=client, sleep_fn=lambda _: None).random_card()
    assert result == BOLT


@patch("bot.card_lookup.record_metric")
def test_random_card_calls_correct_url(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, BOLT)
    _make_lookup(client=client, sleep_fn=lambda _: None).random_card()
    client.get.assert_called_once_with("https://api.scryfall.com/cards/random")


@patch("bot.card_lookup.record_metric")
def test_random_card_5xx_raises_and_records_metric(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(500)
    with pytest.raises(RuntimeError, match="Scryfall API error: 500"):
        _make_lookup(client=client, sleep_fn=lambda _: None).random_card()
    mock_metric.assert_called_with("ScryfallApiError")


# ── find_rulings ─────────────────────────────────────────────────────────────


@patch("bot.card_lookup.record_metric")
def test_find_rulings_returns_data(mock_metric):
    client = MagicMock()
    rulings = [
        {"source": "wotc", "published_at": "2023-01-01", "comment": "Rule text."}
    ]
    client.get.return_value = _mock_response(200, {"data": rulings})
    card = {**BOLT, "rulings_uri": "https://api.scryfall.com/cards/abc/rulings"}
    result = _make_lookup(client=client, sleep_fn=lambda _: None).find_rulings(card)
    assert result == rulings


@patch("bot.card_lookup.record_metric")
def test_find_rulings_no_uri_returns_empty(mock_metric):
    result = _make_lookup(sleep_fn=lambda _: None).find_rulings({"name": "Card"})  # type: ignore[typeddict-item]
    assert result == []


@patch("bot.card_lookup.record_metric")
def test_find_rulings_error_records_metric(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(500)
    card = {**BOLT, "rulings_uri": "https://api.scryfall.com/cards/abc/rulings"}
    with pytest.raises(RuntimeError):
        _make_lookup(client=client, sleep_fn=lambda _: None).find_rulings(card)
    mock_metric.assert_called_with("ScryfallApiError")


# ── fetch_images ──────────────────────────────────────────────────────────────


@patch("bot.card_lookup.record_metric")
def test_fetch_images_normal_card(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(200, content=b"\xff\xd8image")
    card = {**BOLT, "image_uris": {"normal": "https://cards.scryfall.io/img.jpg"}}
    result = _make_lookup(client=client).fetch_images(card)  # type: ignore[arg-type]
    assert result == [b"\xff\xd8image"]


@patch("bot.card_lookup.record_metric")
def test_fetch_images_double_faced_card_returns_both_faces(mock_metric):
    client = MagicMock()
    client.get.side_effect = [
        _mock_response(200, content=b"face0"),
        _mock_response(200, content=b"face1"),
    ]
    card = {
        "name": "Delver of Secrets // Insectile Aberration",
        "card_faces": [
            {"image_uris": {"normal": "https://cards.scryfall.io/front.jpg"}},
            {"image_uris": {"normal": "https://cards.scryfall.io/back.jpg"}},
        ],
    }
    result = _make_lookup(client=client).fetch_images(card)  # type: ignore[arg-type]
    assert result == [b"face0", b"face1"]
    assert client.get.call_count == 2


@patch("bot.card_lookup.record_metric")
def test_fetch_images_dfc_failed_face_excluded(mock_metric):
    client = MagicMock()
    client.get.side_effect = [
        _mock_response(200, content=b"face0"),
        _mock_response(404),
    ]
    card = {
        "name": "Delver of Secrets // Insectile Aberration",
        "card_faces": [
            {"image_uris": {"normal": "https://cards.scryfall.io/front.jpg"}},
            {"image_uris": {"normal": "https://cards.scryfall.io/back.jpg"}},
        ],
    }
    result = _make_lookup(client=client).fetch_images(card)  # type: ignore[arg-type]
    assert result == [b"face0"]
    mock_metric.assert_called_with("ImageFetchFailure")


@patch("bot.card_lookup.record_metric")
def test_fetch_images_no_uri_returns_empty(mock_metric):
    result = _make_lookup().fetch_images({"name": "Card"})  # type: ignore[typeddict-item]
    assert result == []


@patch("bot.card_lookup.record_metric")
def test_fetch_images_non_200_returns_empty_and_records_metric(mock_metric):
    client = MagicMock()
    client.get.return_value = _mock_response(404)
    card = {**BOLT, "image_uris": {"normal": "https://cards.scryfall.io/img.jpg"}}
    result = _make_lookup(client=client).fetch_images(card)  # type: ignore[arg-type]
    assert result == []
    mock_metric.assert_called_with("ImageFetchFailure")
