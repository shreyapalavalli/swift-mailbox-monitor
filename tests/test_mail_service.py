import asyncio

import pytest

from app.graph.auth_service import GraphAuthService


def test_delegated_auth_starts_signed_out() -> None:
    service = GraphAuthService()

    assert service.is_authenticated is False


def test_delegated_auth_requires_sign_in() -> None:
    service = GraphAuthService()

    with pytest.raises(RuntimeError, match="sign-in required"):
        asyncio.run(service.get_access_token())


import json  # noqa: E402

import httpx  # noqa: E402

from app.graph.graph_client import GraphClient  # noqa: E402
from app.graph.mail_service import GraphMailService  # noqa: E402
from tests.conftest import FakeAuth  # noqa: E402

PREFER = 'outlook.body-content-type="text"'


def _service(handler) -> GraphMailService:
    client = GraphClient(
        auth_service=FakeAuth(), transport=httpx.MockTransport(handler)
    )
    return GraphMailService(graph_client=client)


def test_fetch_unread_requests_text_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"value": [{"id": "m1", "subject": "s"}]})

    result = asyncio.run(_service(handler).fetch_unread_messages(folder="junkemail"))

    assert seen[0].headers["prefer"] == PREFER
    assert "/me/mailFolders/junkemail/messages" in seen[0].url.path
    assert seen[0].url.params["$filter"] == "isRead eq false"
    assert result[0].folder == "junkemail"


def test_forward_posts_recipient() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202)

    asyncio.run(
        _service(handler).forward_message(
            "a/b=", "shreyapalavalli@gmail.com", "fwd"
        )
    )

    body = json.loads(seen[0].content)
    assert seen[0].method == "POST"
    assert seen[0].url.raw_path.decode().endswith("/messages/a%2Fb%3D/forward")
    assert body["comment"] == "fwd"
    assert (
        body["toRecipients"][0]["emailAddress"]["address"]
        == "shreyapalavalli@gmail.com"
    )


def test_reply_all_posts_comment() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202)

    asyncio.run(_service(handler).reply_all("m1", "ack"))

    assert seen[0].url.path.endswith("/replyAll")
    assert json.loads(seen[0].content) == {"comment": "ack"}


def test_fetch_by_id_sends_prefer_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "m1"})

    asyncio.run(_service(handler).fetch_message_by_id("m1"))

    assert seen[0].headers["prefer"] == PREFER
