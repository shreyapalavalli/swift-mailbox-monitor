"""Background loop that runs the SWIFT processor on a fixed interval."""
import asyncio
import logging

from app.graph.auth_service import SignInRequiredError

logger = logging.getLogger("swift.poller")


async def run_poller(processor, interval_seconds: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            summary = await processor.run_once()
            logger.info("poll complete: %s", summary)
        except SignInRequiredError as exc:
            logger.warning("poll skipped: %s", exc)
        except Exception:
            logger.exception("poll failed")
        try:
            await asyncio.wait_for(stop.wait(), interval_seconds)
        except asyncio.TimeoutError:
            pass
