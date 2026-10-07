"""Orchestrates fetch -> parse -> classify -> decide -> act, exactly once per Graph message."""
import asyncio
import json
from typing import Protocol

import httpx

from app.db.repository import SwiftRepository
from app.graph.auth_service import SignInRequiredError
from app.models.email_message import EmailMessage
from app.swift.classifier import Classification, classify
from app.swift.parser import ParsedSwift, parse_swift
from app.swift.rules import Action, Decision, decide

FORWARD_COMMENT = "Auto-routed by SWIFT Mailbox Monitor: reference {ref} belongs to the CST team."
REPLY_TEXT = (
    "Dear Sir/Madam,\n\n"
    "We acknowledge your callback request regarding reference {ref}. SGNY Operations will contact "
    "you by telephone to complete the verification.\n\n"
    "Regards,\nSGNY Payments Operations"
)

FORWARDED, REPLIED, MARKED_READ, STORED = "FORWARDED", "REPLIED", "MARKED_READ", "STORED"
STEPS: dict[Action, tuple[str, ...]] = {
    Action.FORWARD_TO_CST: (FORWARDED, MARKED_READ),
    Action.AUTO_REPLY: (REPLIED, STORED, MARKED_READ),
    Action.MARK_READ: (MARKED_READ,),
    Action.STORE_FOR_ANALYST: (STORED,),
    Action.IGNORE: (),
}


class MailGateway(Protocol):
    async def fetch_unread_messages(self, folder: str, top: int = 50) -> list[EmailMessage]: ...
    async def mark_as_read(self, message_id: str) -> None: ...
    async def forward_message(self, message_id: str, to_address: str, comment: str) -> None: ...
    async def reply_all(self, message_id: str, comment: str) -> None: ...


def _first_ref(parsed: ParsedSwift, prefixes: tuple[str, ...]) -> str:
    return next((r for r in parsed.references if r.upper().startswith(prefixes)), parsed.reference or "")


class SwiftProcessor:
    def __init__(self, mail: MailGateway, repo: SwiftRepository, folders: list[str],
                 cst_mailbox: str, action_mx_types: list[str]):
        self.mail = mail
        self.repo = repo
        self.folders = folders
        self.cst_mailbox = cst_mailbox
        self.action_mx_types = action_mx_types
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    async def run_once(self) -> dict:
        """Process every unread message once; overlapping calls are serialized by a lock."""
        async with self._lock:
            return await self._run_once()

    async def _run_once(self) -> dict:
        summary = {"fetched": 0, "processed": 0, "skipped": 0, "failed": 0, "by_action": {}}
        for folder in self.folders:
            messages = await self.mail.fetch_unread_messages(folder)
            summary["fetched"] += len(messages)
            for msg in messages:
                prior = self.repo.get_processed(msg.id)
                if prior and prior["outcome"] == "DONE":
                    summary["skipped"] += 1
                    continue
                row = await self.process_message(msg)
                summary["processed"] += 1
                summary["failed"] += row["outcome"] == "FAILED"
                if row["action"]:
                    by_action = summary["by_action"]
                    by_action[row["action"]] = by_action.get(row["action"], 0) + 1
        return summary

    async def process_message(self, msg: EmailMessage) -> dict:
        """Run the message's remaining steps and record the outcome.

        httpx errors and other Exceptions are recorded as FAILED and contained.
        SignInRequiredError and BaseExceptions are re-raised, after persisting progress if a
        step completed in this call, so a retry never repeats a forward or reply.
        """
        prior = self.repo.get_processed(msg.id)
        prior_steps = [s for s in ((prior or {}).get("completed_steps") or "").split(",") if s]
        done = set(prior_steps)
        row = {
            "graph_message_id": msg.id,
            "folder": msg.folder,
            "received_at": msg.received_date_time.isoformat() if msg.received_date_time else None,
            "subject": msg.subject,
            "sender": msg.sender,
            "is_swift": 0,
            "reference": None,
            "message_type": None,
            "category": None,
            "action": None,
            "status": None,
        }
        steps: tuple[str, ...] | None = None

        def finish(error: str | None) -> dict:
            ordered = [s for s in steps if s in done] if steps is not None else prior_steps
            row.update(outcome="FAILED" if error else "DONE",
                       completed_steps=",".join(ordered), error=error)
            self.repo.record_processed(row)
            return row

        try:
            parsed = parse_swift(msg.subject, msg.body)
            classification = classify(parsed)
            decision = decide(parsed, classification, self.action_mx_types)
            reference = parsed.reference or msg.id
            steps = STEPS[decision.action]
            row.update(is_swift=int(parsed.is_swift),
                       reference=reference if parsed.is_swift else None,
                       message_type=parsed.message_type, category=decision.category,
                       action=decision.action.value, status=decision.status)
            for step in steps:
                if step in done:
                    continue
                try:
                    await self._run_step(step, msg, parsed, classification, decision, reference)
                except httpx.HTTPError as exc:
                    return finish(str(exc)[:500])
                done.add(step)
        except Exception as exc:
            if not isinstance(exc, SignInRequiredError):
                return finish(repr(exc)[:500])
            if done != set(prior_steps):
                finish(repr(exc)[:500])
            raise
        except BaseException as exc:
            if done != set(prior_steps):
                finish(repr(exc)[:500])
            raise
        return finish(None)

    async def _run_step(self, step: str, msg: EmailMessage, parsed: ParsedSwift,
                        classification: Classification, decision: Decision, reference: str) -> None:
        if step == FORWARDED:
            comment = FORWARD_COMMENT.format(ref=_first_ref(parsed, ("SGU",)))
            await self.mail.forward_message(msg.id, self.cst_mailbox, comment)
        elif step == REPLIED:
            await self.mail.reply_all(msg.id, REPLY_TEXT.format(ref=_first_ref(parsed, ("FT", "INV"))))
        elif step == MARKED_READ:
            await self.mail.mark_as_read(msg.id)
        elif step == STORED:
            self.repo.upsert_action(self._action_row(msg, parsed, classification, decision, reference))

    @staticmethod
    def _action_row(msg: EmailMessage, parsed: ParsedSwift, classification: Classification,
                    decision: Decision, reference: str) -> dict:
        return {
            "reference": reference,
            "graph_message_id": msg.id,
            "received_at": msg.received_date_time.isoformat() if msg.received_date_time else None,
            "format": parsed.format,
            "message_type": parsed.message_type,
            "related_reference": parsed.related_reference,
            "category": decision.category,
            "status": decision.status,
            "priority": decision.priority,
            "sender_bic": parsed.sender_bic,
            "receiver_bic": parsed.receiver_bic,
            "currency": parsed.currency,
            "amount": str(parsed.amount) if parsed.amount is not None else None,
            "business_purpose": classification.business_purpose,
            "narrative": parsed.narrative,
            "matched_terms": json.dumps(list(classification.matched_terms)),
            "reason": decision.reason,
        }
