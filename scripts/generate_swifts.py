"""Continuously mail synthetic SWIFT messages from Gmail to the monitored Outlook mailbox.

Usage: python -m scripts.generate_swifts [--interval 60] [--count N] [--kinds a,b] [--dry-run]
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

# Percent weights: cancellation 30, sgu 25, amendment 15, callback 15, other 15.
KIND_WEIGHTS = {
    "cancellation_mt192": 7.5, "cancellation_return_mt199": 7.5, "camt056": 7.5, "camt058": 7.5,
    "sgu_reply": 25, "amendment": 15, "callback_ft": 7.5, "callback_inv": 7.5,
    "aba_request": 7.5, "cls_mt298": 7.5,
}


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="python -m scripts.generate_swifts", description=__doc__.splitlines()[0])
    parser.add_argument("--interval", type=float, default=60, help="seconds between messages (default 60)")
    parser.add_argument("--count", type=int, default=None, help="stop after N messages (default: run forever)")
    parser.add_argument("--kinds", default=None, help=f"comma-separated subset of: {', '.join(KINDS)}")
    parser.add_argument("--dry-run", action="store_true", help="print messages instead of sending them")
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


def main(argv=None) -> int:
    args = _parse_args(argv)
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
    weights = [KIND_WEIGHTS[k] for k in kinds]
    sent = 0
    try:
        while args.count is None or sent < args.count:
            if sent:
                time.sleep(args.interval)
            kind = rng.choices(kinds, weights)[0]
            subject, body = make_sample(kind, rng, datetime.now())
            msg = _build_message(sender, recipient, subject, body)
            if args.dry_run:
                print(f"--- [dry-run] {kind} ---\nFrom: {sender}\nTo: {recipient}\nSubject: {subject}\n\n{body}\n")
            else:
                _send(msg, sender, password)
                print(f"sent {kind}: {subject}", flush=True)
            sent += 1
    except KeyboardInterrupt:
        print(f"\nStopped after {sent} message(s).")
        return 0
    except (smtplib.SMTPException, OSError) as exc:
        print(f"error: sending failed after {sent} message(s): {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
