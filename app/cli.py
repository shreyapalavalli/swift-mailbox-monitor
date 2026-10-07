import argparse
import sys

from app.graph.auth_service import GraphAuthService


def _login() -> int:
    username = GraphAuthService().login_device_flow()
    print(f"Signed in as {username}")
    return 0


def _run_once() -> int:
    print(
        "run-once is not available yet (the processor is not implemented).",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="Sign in with the device-code flow")
    commands.add_parser("run-once", help="Process the mailbox once")
    args = parser.parse_args(argv)

    return _login() if args.command == "login" else _run_once()


if __name__ == "__main__":
    sys.exit(main())
