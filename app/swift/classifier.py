"""Score a parsed SWIFT message into a business category using stdlib-only NLP."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum

from app.swift.parser import ParsedSwift


class Category(str, Enum):
    CANCELLATION = "CANCELLATION"
    AMENDMENT = "AMENDMENT"
    CALLBACK = "CALLBACK"
    ABA_REQUEST = "ABA_REQUEST"
    OTHER = "OTHER"


@dataclass(frozen=True)
class Classification:
    category: Category
    confidence: float
    matched_terms: tuple[str, ...]
    business_purpose: str | None
    strong: bool = False  # CANCELLATION only: evidence strong enough to auto-close


# Category -> (phrases, tokens), each a tuple of (term, weight). Dict order is the tie-break order.
_LEXICON: dict[Category, tuple[tuple[tuple[str, float], ...], tuple[tuple[str, float], ...]]] = {
    Category.CANCELLATION: (
        (("RETURN THE FUNDS", 3), ("RETURN OF FUNDS", 3), ("REQUEST FOR CANCELLATION", 3),
         ("PLEASE CANCEL", 3), ("STOP PAYMENT", 3), ("PAYER'S REQUEST", 1)),
        (("CANCEL", 2), ("CANCELLATION", 2), ("CANCELLED", 2), ("RECALL", 2), ("REVOKE", 2), ("REFUND", 2)),
    ),
    Category.AMENDMENT: (
        (("PLEASE AMEND", 3), ("CHANGE THE BENEFICIARY", 3), ("CORRECT THE BENEFICIARY", 3),
         ("SHOULD READ", 2), ("INSTEAD OF", 1)),
        (("AMEND", 3), ("AMENDMENT", 3), ("AMENDED", 3), ("MODIFY", 2), ("REVISED", 1)),
    ),
    Category.CALLBACK: (
        (("CALL BACK", 3), ("CONFIRM BY PHONE", 3), ("VERIFY BY TELEPHONE", 3), ("PHONE CONFIRMATION", 2)),
        (("CALLBACK", 3), ("TELEPHONE", 1)),
    ),
    Category.ABA_REQUEST: (
        (("ROUTING NUMBER", 3), ("ROUTING NO", 3), ("VALID ABA", 3)),
        (("ABA", 3), ("FEDWIRE", 1)),
    ),
}

_PHRASE_PATTERNS = {
    phrase: re.compile(r"\b" + r"\s+".join(map(re.escape, phrase.split())) + r"\b")
    for phrases, _ in _LEXICON.values() for phrase, _ in phrases
}

THRESHOLD = 2.0
TYPE_PRIOR = 5.0
STRONG_CANCELLATION_SCORE = 4.0
_FUZZY_MIN_LEN = 5
_FUZZY_RATIO = 0.85

_TOKEN = re.compile(r"[A-Z][A-Z'-]+")
_MT_CANCEL_TYPE = re.compile(r"MT\d92")
_MX_NAME = re.compile(r"[a-z]{4}\.\d{3}\.\d{3}\.\d{2}_([A-Za-z]+?)(?=Requestor\b|[^A-Za-z]|$)")
_PURPOSE = re.compile(r"PURPOSE OF PAYMENT[.:]?\s*(.+?)(?=\s+\d\.\s|$)", re.S)
_SENTENCE_END = re.compile(r"[.?!](?:\s|$)")
_NEGATED_CANCELLATION = re.compile(
    r"\b(?:DO\s+NOT|DON'?T|NOT\s+TO|NO\s+NEED\s+TO)\s+(?:CANCEL|RECALL|REVOKE|RETURN)"
    r"|\bNOT\s+A\s+CANCELLATION\b")


def _token_matches(term: str, tokens: set[str]) -> bool:
    if term in tokens:
        return True
    if len(term) < _FUZZY_MIN_LEN:
        return False
    return any(SequenceMatcher(None, tok, term).ratio() >= _FUZZY_RATIO for tok in tokens)


def _mx_name(parsed: ParsedSwift) -> str | None:
    if parsed.format != "MX":
        return None
    m = _MX_NAME.search(parsed.text)
    return m.group(1) if m else None


def _type_prior(parsed: ParsedSwift, mx_name: str | None) -> Category | None:
    if parsed.format == "MT" and parsed.message_type and _MT_CANCEL_TYPE.fullmatch(parsed.message_type):
        return Category.CANCELLATION
    if parsed.format == "MX":
        if parsed.mx_family in ("camt.056", "camt.058") or "Cancellation" in (mx_name or ""):
            return Category.CANCELLATION
        if parsed.mx_family == "camt.087":
            return Category.AMENDMENT
    return None


def _business_purpose(parsed: ParsedSwift, mx_name: str | None) -> str | None:
    m = _PURPOSE.search(parsed.narrative.upper())
    if m:
        return " ".join(m.group(1).split())
    if mx_name:
        return " ".join(re.findall(r"[A-Z][a-z]*", mx_name))
    narrative = " ".join(parsed.narrative.split())
    if not narrative:
        return None
    end = _SENTENCE_END.search(narrative)
    return (narrative[:end.start() + 1] if end else narrative)[:160]


def classify(parsed: ParsedSwift) -> Classification:
    text = (parsed.text if parsed.format == "MX" else parsed.narrative).upper()
    tokens = set(_TOKEN.findall(text))
    mx_name = _mx_name(parsed)
    prior = _type_prior(parsed, mx_name)

    negated = bool(_NEGATED_CANCELLATION.search(text))

    scores: dict[Category, float] = {}
    matches: dict[Category, tuple[str, ...]] = {}
    phrase_hit: dict[Category, bool] = {}
    for category, (phrases, terms) in _LEXICON.items():
        ignored = negated and category is Category.CANCELLATION  # "DO NOT CANCEL": only the type prior counts
        phrase_hits = [] if ignored else [(p, w) for p, w in phrases if _PHRASE_PATTERNS[p].search(text)]
        term_hits = [] if ignored else [(t, w) for t, w in terms if _token_matches(t, tokens)]
        hits = phrase_hits + term_hits
        phrase_hit[category] = bool(phrase_hits)
        scores[category] = sum(w for _, w in hits) + (TYPE_PRIOR if category is prior else 0.0)
        matches[category] = tuple(term for term, _ in hits)

    total = sum(scores.values())
    best = max(scores, key=scores.get)  # first max in lexicon order breaks ties
    purpose = _business_purpose(parsed, mx_name)
    if scores[best] < THRESHOLD:
        return Classification(Category.OTHER, 0.0 if total == 0 else scores[best] / total, (), purpose)
    strong = best is Category.CANCELLATION and (
        prior is Category.CANCELLATION or phrase_hit[best] or scores[best] >= STRONG_CANCELLATION_SCORE)
    return Classification(best, scores[best] / total, matches[best], purpose, strong)
