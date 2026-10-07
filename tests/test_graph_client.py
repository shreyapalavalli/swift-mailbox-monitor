import asyncio
import json
import os
import stat

import httpx
import pytest

from app.graph.auth_service import GraphAuthService
from app.graph.graph_client import GraphClient
from tests.conftest import FakeAuth


def test_post_sends_bearer_and_json():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(202)

    client = GraphClient(auth_service=FakeAuth(), transport=httpx.MockTransport(handler))
    asyncio.run(client.post("https://graph.test/x", {"comment": "hi"}))
    assert seen == {"auth": "Bearer tok", "body": {"comment": "hi"}}


def test_post_raises_on_4xx():
    client = GraphClient(
        auth_service=FakeAuth(),
        transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})),
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.post("https://graph.test/x", {}))


def test_get_merges_extra_headers_over_defaults():
    seen = {}

    def handler(req):
        seen["accept"] = req.headers["accept"]
        seen["prefer"] = req.headers["prefer"]
        return httpx.Response(200, json={"ok": True})

    client = GraphClient(auth_service=FakeAuth(), transport=httpx.MockTransport(handler))
    result = asyncio.run(
        client.get(
            "https://graph.test/x",
            headers={"Accept": "text/plain", "Prefer": 'outlook.body-content-type="text"'},
        )
    )
    assert result == {"ok": True}
    assert seen == {"accept": "text/plain", "prefer": 'outlook.body-content-type="text"'}


def test_patch_sends_json():
    seen = {}

    def handler(req):
        seen["method"] = req.method
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={})

    client = GraphClient(auth_service=FakeAuth(), transport=httpx.MockTransport(handler))
    asyncio.run(client.patch("https://graph.test/x", {"isRead": True}))
    assert seen == {"method": "PATCH", "body": {"isRead": True}}


def test_cache_with_no_file_is_signed_out(tmp_path):
    assert GraphAuthService(cache_path=str(tmp_path / "none.json")).is_authenticated is False


def test_cache_is_saved_with_owner_only_permissions(tmp_path):
    path = tmp_path / "cache.json"
    service = GraphAuthService(cache_path=str(path))
    service._cache.deserialize(json.dumps({"AccessToken": {}}))
    service._cache.has_state_changed = True
    service._save_cache()
    assert path.exists()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert GraphAuthService(cache_path=str(path)).is_authenticated is False


def test_cached_account_counts_as_authenticated(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "Account": {
                    "uid.utid-login.windows.net-consumers": {
                        "home_account_id": "uid.utid",
                        "environment": "login.windows.net",
                        "realm": "consumers",
                        "local_account_id": "uid",
                        "username": "me@outlook.com",
                        "authority_type": "MSSTS",
                    }
                }
            }
        )
    )
    service = GraphAuthService(cache_path=str(path))
    assert service.is_authenticated is True
    assert service._account["username"] == "me@outlook.com"


def test_logout_clears_persisted_cache(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "Account": {
                    "uid.utid-login.windows.net-consumers": {
                        "home_account_id": "uid.utid",
                        "environment": "login.windows.net",
                        "realm": "consumers",
                        "local_account_id": "uid",
                        "username": "me@outlook.com",
                        "authority_type": "MSSTS",
                    }
                }
            }
        )
    )
    service = GraphAuthService(cache_path=str(path))
    assert service.is_authenticated is True
    service.logout()
    assert service.is_authenticated is False
    assert GraphAuthService(cache_path=str(path)).is_authenticated is False


def test_error_is_logged_without_headers_or_print(caplog, capsys):
    import logging

    body = "x" * 2000
    client = GraphClient(
        auth_service=FakeAuth(),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, text=body, headers={"www-authenticate": "Bearer secret-ish"})),
    )
    with caplog.at_level(logging.WARNING, logger="swift.graph"), pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.get("https://graph.test/x"))
    (record,) = [r for r in caplog.records if r.name == "swift.graph"]
    msg = record.getMessage()
    assert record.levelno == logging.WARNING
    assert "400" in msg and "https://graph.test/x" in msg
    assert "x" * 500 in msg and "x" * 501 not in msg
    assert "secret-ish" not in msg and "www-authenticate" not in msg.lower()
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
