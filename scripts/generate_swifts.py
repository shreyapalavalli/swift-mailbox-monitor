"""Continuously mail synthetic SWIFT messages from Gmail to the monitored Outlook mailbox.

Usage: python -m scripts.generate_swifts [--interval 60] [--count N] [--kinds a,b] [--dry-run]
       python -m scripts.generate_swifts --scenario demo [--auto --interval 45] [--dry-run]
"""

import argparse
import os
import random
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email.message import EmailMessage

from dotenv import load_dotenv

from scripts.swift_samples import KINDS, make_sample

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 587
DEFAULT_SENDER = "vishnuprakash156@gmail.com"
DEFAULT_RECIPIENT = "MTheadsYI@outlook.com"
MAX_BACKOFF_SECONDS = 300

# Percent weights: cancellation 30, sgu 25, amendment 15, callback 15, other 15.
KIND_WEIGHTS = {
    "cancellation_mt192": 7.5, "cancellation_return_mt199": 7.5, "camt056": 7.5, "camt058": 7.5,
    "sgu_reply": 25, "amendment": 15, "callback_ft": 7.5, "callback_inv": 7.5,
    "aba_request": 7.5, "cls_mt298": 7.5,
}

# Fixed, presenter-paced sequence covering every automation scenario once.
SCENARIOS = {
    "demo": (
        ("amendment", "Amendment request -> PRIORITY alert with key extracts on the dashboard"),
        ("sgu_reply", "SGU reference -> forwarded to the CST team and marked read"),
        ("cancellation_mt192", "MT192 cancellation -> auto-closed (marked read)"),
        ("camt056", "camt.056 cancellation -> stays unread, HIGH priority in the analyst queue"),
        ("callback_ft", "FT callback -> automatic acknowledgement reply"),
        ("aba_request", "ABA request -> analyst queue"),
    ),
}


def _non_negative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return number


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return number


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="python -m scripts.generate_swifts", description=__doc__.splitlines()[0])
    parser.add_argument("--interval", type=_non_negative_float, default=60,
                        help="seconds between messages (default 60)")
    parser.add_argument("--count", type=_positive_int, default=None,
                        help="stop after N messages (default: run forever)")
    parser.add_argument("--kinds", default=None, help=f"comma-separated subset of: {', '.join(KINDS)}")
    parser.add_argument("--dry-run", action="store_true", help="print messages instead of sending them")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS),
                        help="send a fixed sequence of one SWIFT per automation scenario; "
                             "waits for Enter before each step")
    parser.add_argument("--auto", action="store_true",
                        help="with --scenario: send steps every --interval seconds instead of waiting for Enter")
    return parser.parse_args(argv)


def _build_message(sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, recipient, subject
    msg.set_content(body)
    return msg


def _send(msg: EmailMessage, sender: str, password: str) -> None:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(sender, password)
        smtp.send_message(msg)


def _random_steps(kinds, count, rng):
    weights = [KIND_WEIGHTS[k] for k in kinds]
    sent = 0
    while count is None or sent < count:
        yield rng.choices(kinds, weights)[0], None
        sent += 1


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.scenario and (args.kinds or args.count):
        print("error: --scenario sends a fixed sequence; it can't be combined with --kinds or --count",
              file=sys.stderr)
        return 2
    if args.auto and not args.scenario:
        print("error: --auto only applies to --scenario", file=sys.stderr)
        return 2
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()] if args.kinds else list(KINDS)
    unknown = [k for k in kinds if k not in KIND_WEIGHTS]
    if unknown or not kinds:
        print(f"error: unknown kind(s): {', '.join(unknown) or '(none given)'}; "
              f"choose from {', '.join(KINDS)}", file=sys.stderr)
        return 2

    load_dotenv()
    sender = os.environ.get("GENERATOR_SENDER") or DEFAULT_SENDER
    recipient = os.environ.get("GENERATOR_RECIPIENT") or DEFAULT_RECIPIENT
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not args.dry_run and not password:
        print("error: GMAIL_APP_PASSWORD is not set. Add a Gmail app password to .env "
              "(Google Account -> Security -> App passwords) or use --dry-run.", file=sys.stderr)
        return 2

    rng = random.Random()
    if args.scenario:
        steps = list(SCENARIOS[args.scenario])
        total = len(steps)
    else:
        steps = _random_steps(kinds, args.count, rng)
        total = None
    sent = 0
    try:
        for index, (kind, note) in enumerate(steps, start=1):
            label = f"[{index}/{total}] {kind}: {note}" if total else None
            if args.scenario and not args.auto:
                try:
                    input(f"\n{label}\nPress Enter to send (Ctrl-C to stop) ")
                except EOFError:
                    break
            else:
                if sent:
                    time.sleep(args.interval)
                if label:
                    print(f"\n{label}", flush=True)
            subject, body = make_sample(kind, rng, datetime.now())
            msg = _build_message(sender, recipient, subject, body)
            if args.dry_run:
                print(f"--- [dry-run] {kind} ---\nFrom: {sender}\nTo: {recipient}\nSubject: {subject}\n\n{body}\n")
                sent += 1
                continue
            failures = 0  # consecutive transient failures for this message
            while True:
                try:
                    _send(msg, sender, password)
                    break
                except smtplib.SMTPAuthenticationError:
                    print("error: Gmail rejected the login. Check GMAIL_APP_PASSWORD and GENERATOR_SENDER.",
                          file=sys.stderr)
                    return 2
                except (smtplib.SMTPException, OSError) as exc:
                    failures += 1
                    delay = min(MAX_BACKOFF_SECONDS, 2 ** failures)
                    print(f"error: send failed ({type(exc).__name__}: {str(exc)[:200]}); "
                          f"retrying in {delay} s", file=sys.stderr, flush=True)
                    time.sleep(delay)
            print(f"sent {kind}: {subject}", flush=True)
            sent += 1
    except KeyboardInterrupt:
        print(f"\nStopped after {sent} message(s).")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
