"""Pure business rules: decide what to do with a classified SWIFT email (first match wins)."""

from dataclasses import dataclass
from enum import Enum

from app.swift.classifier import Category, Classification
from app.swift.parser import ParsedSwift


class Action(str, Enum):
    IGNORE = "IGNORE"
    FORWARD_TO_CST = "FORWARD_TO_CST"
    MARK_READ = "MARK_READ"
    AUTO_REPLY = "AUTO_REPLY"
    STORE_FOR_ANALYST = "STORE_FOR_ANALYST"


@dataclass(frozen=True)
class Decision:
    action: Action
    category: str  # a Category value, or "CST" / "NOT_SWIFT"
    status: str  # IGNORED | AUTO_CLOSED | ROUTED_CST | RESPONDED | ACTION_REQUIRED | PRIORITY
    priority: str  # HIGH | NORMAL | LOW
    reason: str


def decide(parsed: ParsedSwift, classification: Classification, action_mx_types: list[str]) -> Decision:
    category = classification.category
    refs = [r.upper() for r in parsed.references]
    mx = (parsed.mx_family or "").lower()
    action_types = {t.lower() for t in action_mx_types}

    if not parsed.is_swift:
        return Decision(Action.IGNORE, "NOT_SWIFT", "IGNORED", "LOW", "Not a SWIFT message")
    if any(r.startswith("SGU") for r in refs):
        return Decision(Action.FORWARD_TO_CST, "CST", "ROUTED_CST", "NORMAL",
                        "SGU reference is routed to the CST team")
    if category is Category.CANCELLATION:
        if mx and mx in action_types:
            return Decision(Action.STORE_FOR_ANALYST, category.value, "ACTION_REQUIRED", "HIGH",
                            f"{mx} cancellation requires analyst review")
        if classification.strong:
            return Decision(Action.MARK_READ, category.value, "AUTO_CLOSED", "LOW",
                            "Cancellation is auto-closed and marked as read")
        return Decision(Action.STORE_FOR_ANALYST, category.value, "ACTION_REQUIRED", "NORMAL",
                        "weak cancellation evidence; analyst review")
    if category is Category.AMENDMENT:
        return Decision(Action.STORE_FOR_ANALYST, category.value, "PRIORITY", "HIGH",
                        "Amendment request is a high priority alert")
    if category is Category.CALLBACK:
        if any(r.startswith(("FT", "INV")) for r in refs):
            return Decision(Action.AUTO_REPLY, category.value, "RESPONDED", "NORMAL",
                            "Callback with FT/INV reference gets an automatic acknowledgement")
        return Decision(Action.STORE_FOR_ANALYST, category.value, "ACTION_REQUIRED", "NORMAL",
                        "Callback without FT/INV reference requires analyst review")
    if category is Category.ABA_REQUEST:
        return Decision(Action.STORE_FOR_ANALYST, category.value, "ACTION_REQUIRED", "NORMAL",
                        "ABA request requires analyst review")
    return Decision(Action.STORE_FOR_ANALYST, Category.OTHER.value, "ACTION_REQUIRED", "NORMAL",
                    "Unmatched SWIFT message requires analyst review")
