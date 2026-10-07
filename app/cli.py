import argparse
import asyncio
import json
import sys

from app.graph.auth_service import GraphAuthService, SignInRequiredError


def _login() -> int:
    username = GraphAuthService().login_device_flow()
    print(f"Signed in as {username}")
    return 0


def _run_once() -> int:
    from app.dependencies import processor

    try:
        summary = asyncio.run(processor.run_once())
    except SignInRequiredError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="Sign in with the device-code flow")
    commands.add_parser("run-once", help="Process the mailbox once")
    args = parser.parse_args(argv)

    return _login() if args.command == "login" else _run_once()


if __name__ == "__main__":
    sys.exit(main())
