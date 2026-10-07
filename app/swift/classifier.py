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


Phrase = tuple[str, re.Pattern, float]  # (label shown in matched_terms, pattern, weight)
Weighted = tuple[tuple[str, float], ...]


def _words(phrase: str, weight: float) -> Phrase:
    return phrase, re.compile(r"\b" + r"\s+".join(map(re.escape, phrase.split())) + r"\b"), weight


def _regex(label: str, pattern: str, weight: float) -> Phrase:
    return label, re.compile(pattern), weight


# Category -> (phrases, stems, terms). Stems match any token they prefix (CANCEL -> CANCELLING) and
# count once; terms match whole tokens, or OCR typos of 5+ chars. Dict order is the tie-break order.
_LEXICON: dict[Category, tuple[tuple[Phrase, ...], Weighted, Weighted]] = {
    Category.CANCELLATION: (
        (_words("RETURN THE FUNDS", 3), _words("RETURN OF FUNDS", 3), _words("REQUEST FOR CANCELLATION", 3),
         _words("PLEASE CANCEL", 3), _words("STOP PAYMENT", 3), _words("PAYER'S REQUEST", 1)),
        (("CANCEL", 2), ("REVOK", 2)),
        (("RECALL", 2), ("REFUND", 2)),
    ),
    Category.AMENDMENT: (
        (_words("PLEASE AMEND", 3),
         _regex("CHANGE BENEFICIARY", r"\bCHANGE\b.{0,25}\bBENEFICIARY\b", 3),
         _regex("CORRECT DETAILS", r"\bCORRECT\b.{0,25}\b(?:FIELD|BENEFICIARY|NAME|ACCOUNT)\b", 3),
         _words("SHOULD READ", 2), _words("INSTEAD OF", 1)),
        (("AMEND", 3), ("MODIF", 2)),
        (("REVISED", 1),),
    ),
    Category.CALLBACK: (
        (_regex("CALL BACK", r"\bCALL\s+(?:US\s+|ME\s+|THE\s+REMITTER\s+)?BACK\b", 3),
         _regex("CONFIRM BY PHONE", r"\bCONFIRM\b.{0,40}\bBY\s+(?:PHONE|TELEPHONE)\b", 3),
         _words("VERIFY BY TELEPHONE", 3), _words("PHONE CONFIRMATION", 2)),
        (),
        (("CALLBACK", 3), ("TELEPHONE", 1)),
    ),
    Category.ABA_REQUEST: (
        (_words("ROUTING NUMBER", 3), _words("ROUTING NO", 3), _words("VALID ABA", 3)),
        (),
        (("ABA", 3), ("FEDWIRE", 1)),
    ),
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


def _token_matches(term: str, tokens: list[str]) -> bool:
    if term in tokens:
        return True
    if len(term) < _FUZZY_MIN_LEN:
        return False
    return any(SequenceMatcher(None, tok, term).ratio() >= _FUZZY_RATIO for tok in tokens)


def _token_hits(stems: Weighted, terms: Weighted, tokens: list[str]) -> list[tuple[str, float]]:
    """Score stems (once each, labelled by the first matching token), then terms on the tokens left over."""
    hits: list[tuple[str, float]] = []
    used: set[str] = set()
    for stem, weight in stems:
        matching = [tok for tok in tokens if tok.startswith(stem)]
        if matching:
            hits.append((matching[0], weight))
            used.update(matching)
    rest = [tok for tok in tokens if tok not in used]
    return hits + [(term, weight) for term, weight in terms if _token_matches(term, rest)]


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
    tokens = list(dict.fromkeys(_TOKEN.findall(text)))  # unique, in text order
    mx_name = _mx_name(parsed)
    prior = _type_prior(parsed, mx_name)

    negated = bool(_NEGATED_CANCELLATION.search(text))

    scores: dict[Category, float] = {}
    matches: dict[Category, tuple[str, ...]] = {}
    phrase_hit: dict[Category, bool] = {}
    for category, (phrases, stems, terms) in _LEXICON.items():
        ignored = negated and category is Category.CANCELLATION  # "DO NOT CANCEL": only the type prior counts
        phrase_hits = [] if ignored else [(label, w) for label, pattern, w in phrases if pattern.search(text)]
        token_hits = [] if ignored else _token_hits(stems, terms, tokens)
        hits = phrase_hits + token_hits
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
