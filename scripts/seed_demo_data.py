"""Fill a SQLite database with realistic dashboard data, without a mailbox or Microsoft sign-in.

Synthetic SWIFTs go through the real pipeline (parse -> classify -> rules -> SwiftProcessor);
only the mailbox is replaced by an in-memory stand-in, so nothing is sent or read over the network.

Usage: python -m scripts.seed_demo_data [--db data/demo.db] [--count 40] [--reset]
                                        [--live [--interval 8] [--live-count N]] [--seed 7]
"""

import argparse
import asyncio
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.db.repository import SwiftRepository
from app.models.email_message import EmailMessage
from app.services.processor import SwiftProcessor
from scripts.generate_swifts import KIND_WEIGHTS
from scripts.swift_samples import KINDS, make_sample

DEFAULT_DB = "data/demo.db"
SEED_PREFIX = "seed-"
NOISE = (
    ("Your weekly account summary", "no-reply@accounts.example.com"),
    ("New sign-in detected for your account", "security@example.com"),
    ("Invitation: Ops stand-up", "calendar@example.com"),
)


class OfflineMailbox:
    """In-memory MailGateway: serves queued messages once and records actions instead of calling Graph."""

    def __init__(self, fail_forward_once: set[str] | None = None):
        self.pending: list[EmailMessage] = []
        self.actions: list[tuple[str, str]] = []
        self._fail_forward_once = set(fail_forward_once or ())

    async def fetch_unread_messages(self, folder: str, top: int = 50) -> list[EmailMessage]:
        batch, self.pending = [m for m in self.pending if m.folder == folder], \
            [m for m in self.pending if m.folder != folder]
        return batch

    async def mark_as_read(self, message_id: str) -> None:
        self.actions.append(("mark_read", message_id))

    async def forward_message(self, message_id: str, to_address: str, comment: str) -> None:
        if message_id in self._fail_forward_once:
            self._fail_forward_once.discard(message_id)
            request = httpx.Request("POST", f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/forward")
            raise httpx.HTTPStatusError("503 Service Unavailable (simulated)", request=request,
                                        response=httpx.Response(503, request=request))
        self.actions.append(("forward", message_id))

    async def reply_all(self, message_id: str, comment: str) -> None:
        self.actions.append(("reply_all", message_id))


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="python -m scripts.seed_demo_data", description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite file to fill (default {DEFAULT_DB})")
    parser.add_argument("--count", type=int, default=40, help="SWIFT messages in the initial batch (default 40)")
    parser.add_argument("--reset", action="store_true", help="delete the database file first")
    parser.add_argument("--force", action="store_true", help="allow a database that holds real mailbox rows")
    parser.add_argument("--live", action="store_true", help="keep adding one new SWIFT every --interval seconds")
    parser.add_argument("--interval", type=float, default=8, help="seconds between --live messages (default 8)")
    parser.add_argument("--live-count", type=int, default=None, help="stop --live after N messages")
    parser.add_argument("--seed", type=int, default=7, help="random seed for repeatable messages; timestamps follow the clock (default 7)")
    return parser.parse_args(argv)


def _has_real_rows(db: str) -> bool:
    if not os.path.exists(db):
        return False
    rows = SwiftRepository(db).list_processed(limit=1000)
    return any(not r["graph_message_id"].startswith(SEED_PREFIX) for r in rows)


def _swift_message(kind: str, rng: random.Random, received: datetime) -> EmailMessage:
    subject, body = make_sample(kind, rng, received.astimezone().replace(tzinfo=None))
    return EmailMessage(id=f"{SEED_PREFIX}{kind}-{rng.getrandbits(48):012x}", subject=subject,
                        sender="vishnuprakash156@gmail.com", received_date_time=received,
                        body=body, folder="inbox")


def _noise_message(index: int, rng: random.Random, received: datetime) -> EmailMessage:
    subject, sender = NOISE[index % len(NOISE)]
    return EmailMessage(id=f"{SEED_PREFIX}noise-{rng.getrandbits(48):012x}", subject=subject, sender=sender,
                        received_date_time=received, body="Not a SWIFT message.", folder="inbox")


def _initial_batch(count: int, rng: random.Random, now: datetime) -> list[EmailMessage]:
    kinds = list(KINDS)[:count] + rng.choices(list(KINDS), [KIND_WEIGHTS[k] for k in KINDS],
                                              k=max(0, count - len(KINDS)))
    rng.shuffle(kinds)
    span = timedelta(hours=6)
    messages = [_swift_message(k, rng, now - span * (i + 1) / (count + 1)) for i, k in enumerate(kinds)]
    messages += [_noise_message(i, rng, now - span * rng.random()) for i in range(3)]
    return messages


def _apply_analyst_activity(repo: SwiftRepository, rng: random.Random) -> None:
    """Move some open items along the analyst workflow so IN_PROGRESS / RESOLVED rows exist."""
    open_rows = repo.list_actions(status="ACTION_REQUIRED", limit=1000)
    priority = repo.list_actions(status="PRIORITY", limit=1000)
    rng.shuffle(open_rows)
    for row in open_rows[: max(1, len(open_rows) // 4)]:
        repo.update_action_status(row["reference"], "RESOLVED")
    for row in open_rows[max(1, len(open_rows) // 4):][: max(1, len(open_rows) // 5)]:
        repo.update_action_status(row["reference"], "IN_PROGRESS")
    if len(priority) > 1:
        repo.update_action_status(priority[-1]["reference"], "IN_PROGRESS")


def _processor(mailbox: OfflineMailbox, repo: SwiftRepository) -> SwiftProcessor:
    return SwiftProcessor(mailbox, repo, ["inbox"], "shreyapalavalli@gmail.com", ["camt.056"])


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.count < 1 or args.interval < 0 or (args.live_count is not None and args.live_count < 1):
        print("error: --count and --live-count must be >= 1 and --interval >= 0", file=sys.stderr)
        return 2
    if args.reset:
        try:
            for path in (args.db, f"{args.db}-wal", f"{args.db}-shm"):
                if os.path.exists(path):
                    os.remove(path)
        except PermissionError:
            print(f"error: {args.db} is in use (on Windows an open database can't be deleted). "
                  "Stop the backend, then run --reset again.", file=sys.stderr)
            return 2
    if _has_real_rows(args.db) and not args.force:
        print(f"error: {args.db} holds rows from a real mailbox; refusing to mix in demo data. "
              f"Use another --db (default {DEFAULT_DB}) or --force.", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    repo = SwiftRepository(args.db)
    batch = _initial_batch(args.count, rng, datetime.now(timezone.utc))
    first_sgu = next((m.id for m in batch if m.id.startswith(f"{SEED_PREFIX}sgu_reply-")), None)
    mailbox = OfflineMailbox(fail_forward_once={first_sgu} if first_sgu else set())
    processor = _processor(mailbox, repo)

    mailbox.pending = batch
    summary = asyncio.run(processor.run_once())
    _apply_analyst_activity(repo, rng)
    print(f"Seeded {args.db}: {summary['processed']} messages ({summary['failed']} failed), "
          f"by action {summary['by_action']}")

    if not args.live:
        return 0
    print(f"Live mode: one new SWIFT every {args.interval:g} s. Ctrl-C to stop.", flush=True)
    added = 0
    weights = [KIND_WEIGHTS[k] for k in KINDS]
    try:
        while args.live_count is None or added < args.live_count:
            time.sleep(args.interval)
            kind = rng.choices(list(KINDS), weights)[0]
            mailbox.pending = [_swift_message(kind, rng, datetime.now(timezone.utc))]
            result = asyncio.run(processor.run_once())
            added += 1
            print(f"+ {kind}: {result['by_action']}", flush=True)
    except KeyboardInterrupt:
        print(f"\nStopped after {added} live message(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
