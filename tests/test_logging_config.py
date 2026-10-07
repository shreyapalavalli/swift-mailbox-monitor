import logging
import os
import subprocess
import sys
from pathlib import Path

from app.logging_config import LOG_FORMAT

ROOT = Path(__file__).resolve().parent.parent


def _run(code: str, tmp_path) -> str:
    env = {**os.environ, "GRAPH_TENANT_ID": "consumers", "GRAPH_CLIENT_ID": "x", "SWIFT_MAILBOX": "me",
           "TOKEN_CACHE_PATH": str(tmp_path / "c.json"), "DATABASE_PATH": str(tmp_path / "d.db"),
           "POLLER_ENABLED": "false", "PYTHONPATH": str(ROOT)}
    # cwd is tmp_path so the subprocess never loads the repo's real .env
    return subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                          capture_output=True, text=True, check=True).stdout


def test_configure_logging_is_idempotent(tmp_path):
    out = _run("import logging; from app.logging_config import configure_logging as c; c(); c(); "
               "r = logging.getLogger(); print(len(r.handlers), r.level); print(r.handlers[0].formatter._fmt)",
               tmp_path)
    counts, fmt = out.splitlines()
    assert counts.split() == ["1", str(logging.INFO)]
    assert fmt == LOG_FORMAT == "%(asctime)s %(levelname)s %(name)s: %(message)s"


def test_importing_app_main_configures_logging(tmp_path):
    out = _run("import logging, app.main; r = logging.getLogger(); print(len(r.handlers), r.level)", tmp_path)
    assert out.split() == ["1", str(logging.INFO)]


def test_cli_main_configures_logging(monkeypatch):
    import app.cli

    calls = []
    monkeypatch.setattr(app.cli, "configure_logging", lambda: calls.append(1))
    monkeypatch.setattr(app.cli, "_run_once", lambda: 0)
    assert app.cli.main(["run-once"]) == 0
    assert calls == [1]
