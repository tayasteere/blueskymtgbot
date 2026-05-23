from bot.query_parser import CardQuery, parse_card_queries


def test_no_brackets_returns_empty():
    assert parse_card_queries("hello world") == []


def test_empty_string_returns_empty():
    assert parse_card_queries("") == []


def test_single_card_name():
    result = parse_card_queries("check out [[Lightning Bolt]]")
    assert result == [CardQuery(name="Lightning Bolt")]


def test_set_modifier():
    result = parse_card_queries("[[Jace|WWK]]")
    assert result == [CardQuery(name="Jace", set_code="WWK")]


def test_set_and_collector_number():
    result = parse_card_queries("[[Island|ZEN|235]]")
    assert result == [CardQuery(name="Island", set_code="ZEN", collector_number="235")]


def test_image_mode_prefix():
    result = parse_card_queries("[[!Force of Will]]")
    assert result == [CardQuery(name="Force of Will", mode="image")]


def test_prices_mode_prefix():
    result = parse_card_queries("[[$tarmogoyf]]")
    assert result == [CardQuery(name="tarmogoyf", mode="prices")]


def test_rulings_mode_prefix():
    result = parse_card_queries("[[?past in flames]]")
    assert result == [CardQuery(name="past in flames", mode="rulings")]


def test_legality_mode_prefix():
    result = parse_card_queries("[[#treasure cruise]]")
    assert result == [CardQuery(name="treasure cruise", mode="legality")]


def test_mode_with_set():
    result = parse_card_queries("[[!Jace|WWK]]")
    assert result == [CardQuery(name="Jace", set_code="WWK", mode="image")]


def test_multiple_queries():
    result = parse_card_queries("look up [[Lightning Bolt]] and [[Counterspell]]")
    assert result == [
        CardQuery(name="Lightning Bolt"),
        CardQuery(name="Counterspell"),
    ]


def test_fuzzy_name_passed_through():
    result = parse_card_queries("[[thalia guardian]]")
    assert result == [CardQuery(name="thalia guardian")]


def test_empty_name_after_prefix_excluded():
    assert parse_card_queries("[[!]]") == []
    assert parse_card_queries("[[$]]") == []


def test_empty_brackets_excluded():
    assert parse_card_queries("[[]]") == []


def test_whitespace_trimmed_from_name():
    result = parse_card_queries("[[ Lightning Bolt ]]")
    assert result == [CardQuery(name="Lightning Bolt")]


def test_empty_set_treated_as_none():
    result = parse_card_queries("[[Lightning Bolt|]]")
    assert result == [CardQuery(name="Lightning Bolt", set_code=None)]


def test_no_mode_field_when_normal():
    result = parse_card_queries("[[Lightning Bolt]]")
    assert result[0].mode is None


def test_whitespace_only_brackets_excluded():
    assert parse_card_queries("[[ ]]") == []


def test_random_mode_single_star():
    result = parse_card_queries("[[*]]")
    assert result == [CardQuery(name="", mode="random")]


def test_random_mode_whitespace_around_star():
    result = parse_card_queries("[[ * ]]")
    assert result == [CardQuery(name="", mode="random")]


def test_random_mode_mixed_with_named_card():
    result = parse_card_queries("[[*]] and [[Lightning Bolt]]")
    assert result == [
        CardQuery(name="", mode="random"),
        CardQuery(name="Lightning Bolt"),
    ]
