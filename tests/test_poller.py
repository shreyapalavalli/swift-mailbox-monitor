import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.graph.auth_service import SignInRequiredError
from app.services.poller import run_poller


class ScriptedProcessor:
    def __init__(self, first=None):
        self.first = first
        self.calls = 0

    async def run_once(self):
        self.calls += 1
        if self.calls == 1 and self.first is not None:
            raise self.first
        return {"processed": 0}


async def _run_for(proc, seconds=0.05, interval=0.01):
    stop = asyncio.Event()
    task = asyncio.create_task(run_poller(proc, interval, stop))
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, 1)


def test_poller_survives_signin_required(caplog):
    proc = ScriptedProcessor(first=SignInRequiredError("Microsoft sign-in required. Visit /auth/login first."))
    with caplog.at_level(logging.INFO, logger="swift.poller"):
        asyncio.run(_run_for(proc))
    assert proc.calls >= 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings and warnings[0].exc_info is None


def test_poller_survives_other_errors_and_logs_traceback(caplog):
    proc = ScriptedProcessor(first=httpx.ConnectError("boom"))
    with caplog.at_level(logging.INFO, logger="swift.poller"):
        asyncio.run(_run_for(proc))
    assert proc.calls >= 2
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)


def test_poller_logs_plain_runtime_error_with_traceback(caplog):
    proc = ScriptedProcessor(first=RuntimeError("Microsoft sign-in required? no, a bug"))
    with caplog.at_level(logging.INFO, logger="swift.poller"):
        asyncio.run(_run_for(proc))
    assert proc.calls >= 2
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_poller_logs_summary_at_info(caplog):
    proc = ScriptedProcessor()
    with caplog.at_level(logging.INFO, logger="swift.poller"):
        asyncio.run(_run_for(proc))
    assert any(r.levelno == logging.INFO and "processed" in r.getMessage() for r in caplog.records)


def test_poller_stops_promptly_during_long_interval():
    proc = ScriptedProcessor()

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(run_poller(proc, 60, stop))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, 1)

    asyncio.run(go())
    assert proc.calls == 1


def test_poller_propagates_cancellation():
    proc = ScriptedProcessor()

    async def go():
        task = asyncio.create_task(run_poller(proc, 60, asyncio.Event()))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())


def test_lifespan_does_not_start_poller_when_disabled(monkeypatch):
    from app.dependencies import processor
    from app.main import app

    called = []

    async def fake_run_once():
        called.append(1)
        return {}

    monkeypatch.setattr(settings, "poller_enabled", False)
    monkeypatch.setattr(processor, "run_once", fake_run_once)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert called == []


def test_lifespan_starts_and_stops_poller_when_enabled(monkeypatch):
    from app.dependencies import processor
    from app.main import app

    called = []

    async def fake_run_once():
        called.append(1)
        return {}

    monkeypatch.setattr(settings, "poller_enabled", True)
    monkeypatch.setattr(processor, "run_once", fake_run_once)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert called


def test_cors_header_for_frontend_origin():
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/health", headers={"Origin": settings.frontend_origin})
    assert r.headers["access-control-allow-origin"] == settings.frontend_origin


def test_lifespan_warns_when_actions_disabled(monkeypatch, caplog):
    from app.dependencies import processor
    from app.main import app

    monkeypatch.setattr(processor, "actions_enabled", False)
    with caplog.at_level(logging.WARNING), TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert any(r.levelno == logging.WARNING and "ACTIONS_ENABLED" in r.getMessage() for r in caplog.records)


def test_lifespan_silent_when_actions_enabled(monkeypatch, caplog):
    from app.main import app

    with caplog.at_level(logging.WARNING), TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert not any("ACTIONS_ENABLED" in r.getMessage() for r in caplog.records)
