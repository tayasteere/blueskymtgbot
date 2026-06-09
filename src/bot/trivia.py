from __future__ import annotations

import json
import random
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_COLOR_CODES: dict[str, str] = {
    "W": "white",
    "U": "blue",
    "B": "black",
    "R": "red",
    "G": "green",
    "C": "colorless",
}

_CATEGORY_LABELS: dict[str, str] = {
    "rules_text": "Rules",
    "flavor_text": "Flavor",
    "keywords_guess": "Keywords",
    "type_guess": "Subtype",
    "power_toughness": "P/T",
    "mana_cost": "Mana cost",
    "cmc": "Mana value",
    "colors": "Colors",
    "color_identity": "Color ID",
    "rarity": "Rarity",
    "set_name": "Set",
    "type_line": "Card type",
    "keywords": "Keywords",
}


@dataclass
class TriviaQuestion:
    question: str
    answer: str
    category: str
    answer_type: str
    card_name: str
    oracle_id: str


@dataclass
class PendingQuestion:
    question: str
    answer: str
    category: str
    answer_type: str
    card_name: str
    trivia_post_uri: str
    asked_at: datetime


def format_trivia_post(question: TriviaQuestion) -> str:
    label = _CATEGORY_LABELS.get(question.category, question.category)
    return f"🃏 [{label}] {question.question}"


# ---------------------------------------------------------------------------
# Answer matching
# ---------------------------------------------------------------------------

def _normalize_card_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^\w\s/]", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _normalize_word_set(text: str) -> set[str]:
    return {t.lower() for t in text.split() if t}


def _normalize_pt(text: str) -> str:
    return re.sub(r"\s*/\s*", "/", text.strip())


def _normalize_mana(text: str) -> str:
    return re.sub(r"[{}\s]", "", text).upper()


def _normalize_cmc(text: str) -> int | None:
    try:
        return int(float(text.strip()))
    except (ValueError, AttributeError):
        return None


def _normalize_colors(text: str) -> set[str]:
    """Accept full color names or single-letter codes, including concatenated like 'WU'."""
    tokens = re.split(r"[,\s/]+", text.strip())
    result: set[str] = set()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        upper = token.upper()
        if upper in _COLOR_CODES:
            result.add(_COLOR_CODES[upper])
        elif len(upper) > 1 and all(c in _COLOR_CODES for c in upper):
            # Concatenated codes like "WU", "RBG"
            for c in upper:
                result.add(_COLOR_CODES[c])
        else:
            result.add(token.lower())
    return result


def _normalize_keyword_set(text: str) -> set[str]:
    return {t.lower().strip() for t in re.split(r"[,\s]+", text) if t.strip()}


def _match_set_name(canonical: str, user: str) -> bool:
    m = re.match(r"^(.*?)\s*\(([^)]+)\)$", canonical.strip())
    if m:
        bare_name = m.group(1).strip()
        code = m.group(2).strip()
    else:
        bare_name = canonical.strip()
        code = ""

    user = user.strip()

    if user.lower() in (canonical.lower(), bare_name.lower()):
        return True

    if code and user.upper() == code.upper():
        return True

    # Word-token subset: every word the user typed appears in the set name
    name_words = {w.lower() for w in bare_name.split()}
    user_words = {w.lower() for w in user.split() if w}
    return bool(user_words) and user_words.issubset(name_words)


def check_answer(answer_type: str, canonical: str, user_answer: str) -> bool:
    match answer_type:
        case "card_name":
            norm_user = _normalize_card_name(user_answer)
            if _normalize_card_name(canonical) == norm_user:
                return True
            # Accept either face of a double-faced card ("Front // Back")
            if " // " in canonical:
                return any(
                    _normalize_card_name(face) == norm_user
                    for face in canonical.split(" // ")
                )
            return False
        case "subtype":
            return _normalize_word_set(canonical) == _normalize_word_set(user_answer)
        case "power_toughness":
            return _normalize_pt(canonical) == _normalize_pt(user_answer)
        case "mana_cost":
            return _normalize_mana(canonical) == _normalize_mana(user_answer)
        case "cmc":
            c = _normalize_cmc(canonical)
            u = _normalize_cmc(user_answer)
            return c is not None and c == u
        case "colors" | "color_identity":
            return _normalize_colors(canonical) == _normalize_colors(user_answer)
        case "rarity":
            return canonical.strip().lower() == user_answer.strip().lower()
        case "set_name":
            return _match_set_name(canonical, user_answer)
        case "type_line":
            return canonical.strip().lower() == user_answer.strip().lower()
        case "keywords":
            return _normalize_keyword_set(canonical) == _normalize_keyword_set(user_answer)
        case _:
            return canonical.strip().lower() == user_answer.strip().lower()


# ---------------------------------------------------------------------------
# Question bank loading
# ---------------------------------------------------------------------------

def _read_jsonl(path: str) -> list[TriviaQuestion]:
    questions: list[TriviaQuestion] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                questions.append(TriviaQuestion(
                    question=obj["question"],
                    answer=obj["answer"],
                    category=obj["category"],
                    answer_type=obj.get("answer_type", "card_name"),
                    card_name=obj.get("card_name", ""),
                    oracle_id=obj.get("oracle_id", ""),
                ))
            except (KeyError, json.JSONDecodeError):
                pass
    return questions


def _load_question_bank(path_str: str) -> list[TriviaQuestion]:
    if path_str.startswith("s3://"):
        import boto3
        bucket, key = path_str[5:].split("/", 1)
        s3 = boto3.client("s3")
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            s3.download_file(bucket, key, tmp.name)
            return _read_jsonl(tmp.name)
    return _read_jsonl(path_str)


# ---------------------------------------------------------------------------
# TriviaManager
# ---------------------------------------------------------------------------

class TriviaManager:
    def __init__(self, question_bank_path: str, timeout_hours: float = 24.0) -> None:
        self._path = question_bank_path
        self._timeout_hours = timeout_hours
        self._questions: list[TriviaQuestion] = []
        self._pending: dict[str, PendingQuestion] = {}

    def load_questions(self) -> None:
        try:
            self._questions = _load_question_bank(self._path)
            print(f"Trivia: loaded {len(self._questions)} questions from {self._path}")
        except Exception as err:
            print(f"Trivia: failed to load question bank, trivia disabled: {err}")
            self._questions = []

    def has_questions(self) -> bool:
        return bool(self._questions)

    def get_random_question(self) -> TriviaQuestion:
        return random.choice(self._questions)

    def set_pending(
        self, author_did: str, question: TriviaQuestion, trivia_post_uri: str
    ) -> None:
        self._pending[author_did] = PendingQuestion(
            question=question.question,
            answer=question.answer,
            category=question.category,
            answer_type=question.answer_type,
            card_name=question.card_name,
            trivia_post_uri=trivia_post_uri,
            asked_at=datetime.now(timezone.utc),
        )

    def get_pending(self, author_did: str) -> PendingQuestion | None:
        return self._pending.get(author_did)

    def resolve_pending(self, author_did: str) -> None:
        self._pending.pop(author_did, None)

    def expire_old(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff_seconds = self._timeout_hours * 3600
        expired = [
            did for did, p in self._pending.items()
            if (now - p.asked_at).total_seconds() > cutoff_seconds
        ]
        for did in expired:
            del self._pending[did]

    def check_answer(self, pending: PendingQuestion, user_answer: str) -> bool:
        return check_answer(pending.answer_type, pending.answer, user_answer)

    def load_state(self, data: dict) -> None:
        self._pending.clear()
        for did, entry in data.items():
            try:
                self._pending[did] = PendingQuestion(
                    question=entry["question"],
                    answer=entry["answer"],
                    category=entry["category"],
                    answer_type=entry["answer_type"],
                    card_name=entry["card_name"],
                    trivia_post_uri=entry["trivia_post_uri"],
                    asked_at=datetime.fromisoformat(entry["asked_at"]),
                )
            except (KeyError, ValueError):
                pass

    def dump_state(self) -> dict:
        return {
            did: {
                "question": p.question,
                "answer": p.answer,
                "category": p.category,
                "answer_type": p.answer_type,
                "card_name": p.card_name,
                "trivia_post_uri": p.trivia_post_uri,
                "asked_at": p.asked_at.isoformat(),
            }
            for did, p in self._pending.items()
        }
