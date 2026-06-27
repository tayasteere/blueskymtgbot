import json
import tempfile
from datetime import datetime, timedelta, timezone

from bot.trivia import (
    PendingQuestion,
    TriviaManager,
    TriviaQuestion,
    check_answer,
    format_trivia_post,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_question(**kwargs) -> TriviaQuestion:
    defaults = dict(
        question="Which card has flying?",
        answer="Birds of Paradise",
        category="rules_text",
        answer_type="card_name",
        card_name="Birds of Paradise",
        oracle_id="abc-123",
    )
    return TriviaQuestion(**(defaults | kwargs))


def _make_pending(**kwargs) -> PendingQuestion:
    defaults = dict(
        question="Which card has flying?",
        answer="Birds of Paradise",
        category="rules_text",
        answer_type="card_name",
        card_name="Birds of Paradise",
        trivia_post_uri="at://bot/post/1",
        asked_at=datetime.now(timezone.utc),
    )
    return PendingQuestion(**(defaults | kwargs))


def _write_jsonl(lines: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


# ---------------------------------------------------------------------------
# check_answer — card_name
# ---------------------------------------------------------------------------

def test_card_name_exact_match():
    assert check_answer("card_name", "Lightning Bolt", "Lightning Bolt")

def test_card_name_case_insensitive():
    assert check_answer("card_name", "Lightning Bolt", "lightning bolt")

def test_card_name_strips_punctuation():
    assert check_answer(
        "card_name", "Urza, Lord High Artificer", "Urza Lord High Artificer"
    )

def test_card_name_apostrophe_optional():
    assert check_answer("card_name", "Urza's Saga", "Urzas Saga")

def test_card_name_wrong():
    assert not check_answer("card_name", "Lightning Bolt", "Counterspell")

_DFC = "Shrill Howler // Howling Chorus"


def test_card_name_dfc_full_name():
    assert check_answer("card_name", _DFC, "Shrill Howler // Howling Chorus")

def test_card_name_dfc_front_face():
    assert check_answer("card_name", _DFC, "Shrill Howler")

def test_card_name_dfc_back_face():
    assert check_answer("card_name", _DFC, "Howling Chorus")

def test_card_name_dfc_case_insensitive():
    assert check_answer("card_name", _DFC, "howling chorus")

def test_card_name_dfc_wrong():
    assert not check_answer("card_name", _DFC, "Counterspell")


# ---------------------------------------------------------------------------
# check_answer — subtype (order-independent)
# ---------------------------------------------------------------------------

def test_subtype_exact():
    assert check_answer("subtype", "Elf Warrior", "Elf Warrior")

def test_subtype_reversed():
    assert check_answer("subtype", "Elf Warrior", "Warrior Elf")

def test_subtype_case_insensitive():
    assert check_answer("subtype", "Elf Warrior", "elf warrior")

def test_subtype_wrong():
    assert not check_answer("subtype", "Elf Warrior", "Human Warrior")


# ---------------------------------------------------------------------------
# check_answer — power_toughness
# ---------------------------------------------------------------------------

def test_pt_exact():
    assert check_answer("power_toughness", "2/5", "2/5")

def test_pt_strips_spaces():
    assert check_answer("power_toughness", "2/5", "2 / 5")

def test_pt_wrong():
    assert not check_answer("power_toughness", "2/5", "3/5")


# ---------------------------------------------------------------------------
# check_answer — mana_cost
# ---------------------------------------------------------------------------

def test_mana_curly_braces_stripped():
    assert check_answer("mana_cost", "{2}{B}{B}", "2BB")

def test_mana_partial_braces_do_not_match():
    assert not check_answer("mana_cost", "{2}{B}{B}", "3{R}{R}")

def test_mana_both_with_braces():
    assert check_answer("mana_cost", "{2}{B}{B}", "{2}{B}{B}")

def test_mana_lowercase():
    assert check_answer("mana_cost", "{2}{B}{B}", "2bb")

def test_mana_wrong():
    assert not check_answer("mana_cost", "{2}{B}{B}", "2GG")


# ---------------------------------------------------------------------------
# check_answer — cmc
# ---------------------------------------------------------------------------

def test_cmc_integer():
    assert check_answer("cmc", "3", "3")

def test_cmc_float_string():
    assert check_answer("cmc", "3", "3.0")

def test_cmc_wrong():
    assert not check_answer("cmc", "3", "4")

def test_cmc_non_numeric_returns_false():
    assert not check_answer("cmc", "3", "three")


# ---------------------------------------------------------------------------
# check_answer — colors / color_identity
# ---------------------------------------------------------------------------

def test_colors_full_names():
    assert check_answer("colors", "White, Blue", "White, Blue")

def test_colors_order_independent():
    assert check_answer("colors", "White, Blue", "Blue, White")

def test_colors_single_code():
    assert check_answer("colors", "Red", "R")

def test_colors_concatenated_codes():
    assert check_answer("colors", "White, Blue", "WU")

def test_colors_codes_with_spaces():
    assert check_answer("colors", "White, Blue", "W U")

def test_colors_colorless_code():
    assert check_answer("colors", "Colorless", "C")

def test_colors_wrong():
    assert not check_answer("colors", "Red", "Blue")

def test_color_identity_same_as_colors():
    assert check_answer("color_identity", "Black, Green", "GB")


# ---------------------------------------------------------------------------
# check_answer — rarity
# ---------------------------------------------------------------------------

def test_rarity_exact():
    assert check_answer("rarity", "Uncommon", "Uncommon")

def test_rarity_case_insensitive():
    assert check_answer("rarity", "Uncommon", "uncommon")

def test_rarity_wrong():
    assert not check_answer("rarity", "Uncommon", "Rare")


# ---------------------------------------------------------------------------
# check_answer — set_name
# ---------------------------------------------------------------------------

_BOK = "Betrayers of Kamigawa (BOK)"


def test_set_name_full_canonical():
    assert check_answer("set_name", _BOK, "Betrayers of Kamigawa (BOK)")

def test_set_name_bare_name():
    assert check_answer("set_name", _BOK, "Betrayers of Kamigawa")

def test_set_name_code_only():
    assert check_answer("set_name", _BOK, "BOK")

def test_set_name_code_lowercase():
    assert check_answer("set_name", _BOK, "bok")

def test_set_name_partial_word_subset():
    assert check_answer("set_name", _BOK, "Betrayers")

def test_set_name_partial_other_word():
    assert check_answer("set_name", _BOK, "Kamigawa")

def test_set_name_wrong():
    assert not check_answer("set_name", _BOK, "Dragon")

def test_set_name_trivial_stopword_not_intended_use():
    # "of" technically matches as a word subset — acceptable per design
    assert check_answer("set_name", _BOK, "of")


# ---------------------------------------------------------------------------
# check_answer — type_line
# ---------------------------------------------------------------------------

def test_type_line_exact():
    assert check_answer("type_line", "Legendary Creature", "Legendary Creature")

def test_type_line_case_insensitive():
    assert check_answer("type_line", "Legendary Creature", "legendary creature")

def test_type_line_wrong():
    assert not check_answer("type_line", "Legendary Creature", "Sorcery")


# ---------------------------------------------------------------------------
# check_answer — keywords (order-independent)
# ---------------------------------------------------------------------------

def test_keywords_exact():
    assert check_answer("keywords", "Flying, Haste", "Flying, Haste")

def test_keywords_order_independent():
    assert check_answer("keywords", "Flying, Haste", "Haste, Flying")

def test_keywords_case_insensitive():
    assert check_answer("keywords", "Flying, Haste", "flying haste")

def test_keywords_wrong():
    assert not check_answer("keywords", "Flying, Haste", "Flying")


# ---------------------------------------------------------------------------
# check_answer — trailing/leading punctuation stripped
# ---------------------------------------------------------------------------

def test_punctuation_card_name_exclamation():
    assert check_answer("card_name", "White", "White!")

def test_punctuation_card_name_period():
    assert check_answer("card_name", "Lightning Bolt", "Lightning Bolt.")

def test_punctuation_rarity_exclamation():
    assert check_answer("rarity", "Common", "Common!")

def test_punctuation_colors_exclamation():
    assert check_answer("colors", "White", "White!")

def test_punctuation_type_line_exclamation():
    assert check_answer("type_line", "Legendary Creature", "Legendary Creature!")

def test_punctuation_keywords_exclamation():
    assert check_answer("keywords", "Flying", "Flying!")

def test_punctuation_subtype_exclamation():
    assert check_answer("subtype", "Elf", "Elf!")

def test_punctuation_pt_exclamation():
    assert check_answer("power_toughness", "2/5", "2/5!")

def test_punctuation_cmc_exclamation():
    assert check_answer("cmc", "3", "3!")

def test_punctuation_set_name_exclamation():
    assert check_answer("set_name", "Betrayers of Kamigawa (BOK)", "Betrayers!")

def test_punctuation_leading_and_trailing():
    assert check_answer("card_name", "White", "White!.")


# ---------------------------------------------------------------------------
# format_trivia_post
# ---------------------------------------------------------------------------

def test_format_trivia_post_includes_question():
    q = _make_question(category="flavor_text", question="Who said this?")
    text = format_trivia_post(q)
    assert "Who said this?" in text

def test_format_trivia_post_includes_label():
    q = _make_question(category="flavor_text")
    text = format_trivia_post(q)
    assert "Flavor" in text

def test_format_trivia_post_fits_bluesky_limit():
    long_q = "x" * 280
    q = _make_question(category="mana_cost", question=long_q)
    text = format_trivia_post(q)
    assert len(text) <= 300


# ---------------------------------------------------------------------------
# TriviaManager — question loading
# ---------------------------------------------------------------------------

def test_load_questions_from_jsonl():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({
            "question": "Q1?", "answer": "A1", "category": "rules_text",
            "answer_type": "card_name", "card_name": "A1", "oracle_id": "o1",
        }) + "\n")
        f.write(json.dumps({
            "question": "Q2?", "answer": "A2", "category": "rarity",
            "answer_type": "rarity", "card_name": "A2", "oracle_id": "o2",
        }) + "\n")
        path = f.name

    mgr = TriviaManager(path)
    mgr.load_questions()
    assert mgr.has_questions()
    assert len(mgr._questions) == 2


def test_load_questions_skips_malformed_lines():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("not json\n")
        f.write(json.dumps({
            "question": "Q?", "answer": "A", "category": "rarity",
            "answer_type": "rarity", "card_name": "A", "oracle_id": "o1",
        }) + "\n")
        path = f.name

    mgr = TriviaManager(path)
    mgr.load_questions()
    assert len(mgr._questions) == 1


def test_load_questions_bad_path_disables_trivia():
    mgr = TriviaManager("/nonexistent/path.jsonl")
    mgr.load_questions()
    assert not mgr.has_questions()


# ---------------------------------------------------------------------------
# TriviaManager — pending question lifecycle
# ---------------------------------------------------------------------------

def test_set_and_get_pending():
    mgr = TriviaManager.__new__(TriviaManager)
    mgr._questions = []
    mgr._pending = {}
    mgr._timeout_hours = 24.0

    q = _make_question()
    mgr.set_pending("did:plc:user1", q, "at://bot/post/1")
    pending = mgr.get_pending("did:plc:user1")
    assert pending is not None
    assert pending.answer == "Birds of Paradise"
    assert pending.trivia_post_uri == "at://bot/post/1"


def test_resolve_pending_removes_entry():
    mgr = TriviaManager.__new__(TriviaManager)
    mgr._questions = []
    mgr._pending = {}
    mgr._timeout_hours = 24.0

    q = _make_question()
    mgr.set_pending("did:plc:user1", q, "at://bot/post/1")
    mgr.resolve_pending("did:plc:user1")
    assert mgr.get_pending("did:plc:user1") is None


def test_resolve_pending_nonexistent_is_noop():
    mgr = TriviaManager.__new__(TriviaManager)
    mgr._questions = []
    mgr._pending = {}
    mgr._timeout_hours = 24.0
    mgr.resolve_pending("did:plc:nobody")  # must not raise


def test_expire_old_removes_expired():
    mgr = TriviaManager.__new__(TriviaManager)
    mgr._questions = []
    mgr._pending = {}
    mgr._timeout_hours = 1.0

    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    mgr._pending["did:plc:old"] = _make_pending(asked_at=old_time)
    mgr._pending["did:plc:fresh"] = _make_pending()

    mgr.expire_old()
    assert mgr.get_pending("did:plc:old") is None
    assert mgr.get_pending("did:plc:fresh") is not None


# ---------------------------------------------------------------------------
# TriviaManager — state serialization
# ---------------------------------------------------------------------------

def test_dump_and_load_state_roundtrip():
    mgr = TriviaManager.__new__(TriviaManager)
    mgr._questions = []
    mgr._pending = {}
    mgr._timeout_hours = 24.0

    q = _make_question()
    mgr.set_pending("did:plc:user1", q, "at://bot/post/1")

    state = mgr.dump_state()

    mgr2 = TriviaManager.__new__(TriviaManager)
    mgr2._questions = []
    mgr2._pending = {}
    mgr2._timeout_hours = 24.0
    mgr2.load_state(state)

    pending = mgr2.get_pending("did:plc:user1")
    assert pending is not None
    assert pending.answer == "Birds of Paradise"
    assert pending.trivia_post_uri == "at://bot/post/1"


def test_load_state_skips_malformed_entries():
    mgr = TriviaManager.__new__(TriviaManager)
    mgr._questions = []
    mgr._pending = {}
    mgr._timeout_hours = 24.0

    mgr.load_state({"did:plc:bad": {"missing": "fields"}})
    assert mgr.get_pending("did:plc:bad") is None


# ---------------------------------------------------------------------------
# TriviaManager — check_answer delegates correctly
# ---------------------------------------------------------------------------

def test_manager_check_answer_correct():
    mgr = TriviaManager.__new__(TriviaManager)
    mgr._questions = []
    mgr._pending = {}
    mgr._timeout_hours = 24.0

    pending = _make_pending(answer="Lightning Bolt", answer_type="card_name")
    assert mgr.check_answer(pending, "lightning bolt")


def test_manager_check_answer_wrong():
    mgr = TriviaManager.__new__(TriviaManager)
    mgr._questions = []
    mgr._pending = {}
    mgr._timeout_hours = 24.0

    pending = _make_pending(answer="Lightning Bolt", answer_type="card_name")
    assert not mgr.check_answer(pending, "Counterspell")
