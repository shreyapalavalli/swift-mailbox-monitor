"""One-time logging setup shared by the API process and the CLI."""
import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    """Send INFO and above to stderr; a no-op once the root logger has a handler."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
