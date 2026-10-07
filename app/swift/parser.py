"""Extract structured fields from normalized SWIFT MT/MX email bodies."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.swift.normalizer import normalize_text


@dataclass(frozen=True)
class ParsedSwift:
    is_swift: bool
    format: str  # "MT" | "MX" | "UNKNOWN"
    message_type: str | None
    mx_family: str | None
    sub_message_type: str | None
    transaction_reference: str | None
    related_reference: str | None
    swift_reference: str | None
    mail_id: str | None
    sender_bic: str | None
    receiver_bic: str | None
    currency: str | None
    amount: Decimal | None
    narrative: str
    references: tuple[str, ...]
    text: str

    @property
    def reference(self) -> str | None:
        return self.transaction_reference or self.swift_reference or self.mail_id


_SWIFT_MARKER = re.compile(r"(?i:Swift|MX)\s+Output\s*:")
_MT_TYPE = re.compile(r"Swift\s+Output\s*:\s*FIN\s+(\d{3})", re.I)
_MX_TYPE = re.compile(r"MX\s+Output\s*:\s*([a-z]{4}\.\d{3}\.\d{3}\.\d{2})", re.I)
_MAIL_ID = re.compile(r"(Mp[A-Za-z]+-\d+-\d+)")

# A field value is one token that is not itself a label ("21:", "77E:") and does not end in ':'.
_VALUE = r"(?!\d{2}[A-Z]?:)(\S*[^\s:])(?!\S)"
_F20 = re.compile(r"\b20:\s*Transaction Reference Number\s+" + _VALUE, re.I)
_F21 = re.compile(r"\b21:\s*Related Reference\s+" + _VALUE, re.I)
_F12 = re.compile(r"\b12:\s*Sub-Message Type\s+(\d{3})\b", re.I)
_RAW20 = re.compile(r"^:20:[ \t]*([^\s:]\S*)", re.M)
_RAW21 = re.compile(r"^:21:[ \t]*([^\s:]\S*)", re.M)

_BIC = r"\s*:\s*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b"
_SENDER = re.compile(r"(?i:Sender)" + _BIC)
_RECEIVER = re.compile(r"(?i:Receiver)" + _BIC)

_NARRATIVE = re.compile(
    r"\b(?:79:\s*Narrative|77E:\s*Proprietary Message)(.*?)(?=\{CHK:|Message Trailer|\Z)", re.I | re.S
)
_SWIFT_REF = re.compile(
    r"SWIFT Reference:\s*(.+?)\s*(?=SWIFT Request Reference|CBT Reference|Store-and-forward|$)", re.I | re.M
)

_AMOUNT_32B = re.compile(r":32B:([A-Z]{3})([\d,.]+)")
_AMOUNT_TEXT = re.compile(r"\b(USD|EUR|GBP|CHF|JPY)\s?([\d,]*\d\.\d{2})\b")

_REFERENCE_TOKENS = re.compile(
    r"\bSGU(?=[A-Z0-9-]*\d)[A-Z0-9-]{5,}|\b(?:FT|INV)[-/]?(?=[A-Z0-9/-]*\d)[A-Z0-9/-]{5,}"
)


def _first(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1) if m else None


def _amount(text: str, narrative: str) -> tuple[str | None, Decimal | None]:
    for m in _AMOUNT_32B.finditer(text):
        try:
            value = Decimal(m.group(2).replace(",", ".").rstrip("."))
        except InvalidOperation:
            continue
        if value != 0:
            return m.group(1), value
    m = _AMOUNT_TEXT.search(narrative)
    if m:
        return m.group(1), Decimal(m.group(2).replace(",", ""))
    return None, None


def _references(*sources: str | None) -> tuple[str, ...]:
    found: dict[str, None] = {}
    for source in sources:
        for token in _REFERENCE_TOKENS.findall(source or ""):
            found.setdefault(token)
    return tuple(found)


def parse_swift(subject: str | None, body: str | None) -> ParsedSwift:
    subject = normalize_text(subject or "")
    text = normalize_text(body or "")
    is_swift = subject.startswith("SWIFT Incoming") or bool(_SWIFT_MARKER.search(text))
    if not is_swift:
        return ParsedSwift(False, "UNKNOWN", None, None, None, None, None, None, None,
                           None, None, None, None, "", (), text)

    mt_type = _first(_MT_TYPE, text)
    mx_type = _first(_MX_TYPE, text)
    if mt_type:
        fmt, message_type, mx_family = "MT", f"MT{mt_type}", None
        narrative = (_first(_NARRATIVE, text) or "").strip()
    elif mx_type:
        message_type = mx_type.lower()
        fmt, mx_family = "MX", ".".join(message_type.split(".")[:2])
        narrative = text
    else:
        fmt, message_type, mx_family = "UNKNOWN", None, None
        narrative = (_first(_NARRATIVE, text) or "").strip()

    f20 = _first(_F20, text) or _first(_RAW20, text)
    f21 = _first(_F21, text) or _first(_RAW21, text)
    currency, amount = _amount(text, narrative)
    return ParsedSwift(
        is_swift=True,
        format=fmt,
        message_type=message_type,
        mx_family=mx_family,
        sub_message_type=_first(_F12, text),
        transaction_reference=f20,
        related_reference=f21,
        swift_reference=_first(_SWIFT_REF, text) if fmt == "MX" else None,
        mail_id=_first(_MAIL_ID, subject),
        sender_bic=_first(_SENDER, text),
        receiver_bic=_first(_RECEIVER, text),
        currency=currency,
        amount=amount,
        narrative=narrative,
        references=_references(f20, f21, narrative),
        text=text,
    )
