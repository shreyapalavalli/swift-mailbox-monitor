import json
import os
import tempfile
from pathlib import Path

# Must run before anything imports `app` (settings is a module-level singleton).
_TMP = tempfile.mkdtemp()
os.environ["GRAPH_TENANT_ID"] = "consumers"
os.environ["GRAPH_CLIENT_ID"] = "test-client"
os.environ["SWIFT_MAILBOX"] = "me"
os.environ["TOKEN_CACHE_PATH"] = os.path.join(_TMP, "cache.json")
os.environ["DATABASE_PATH"] = os.path.join(_TMP, "test.db")
os.environ["POLLER_ENABLED"] = "false"

import pytest  # noqa: E402

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "emails"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))

    return _load


def subject_body(fixture: dict) -> dict:
    return {"subject": fixture["subject"], "body": fixture["body"]}


class FakeAuth:
    async def get_access_token(self) -> str:
        return "tok"
