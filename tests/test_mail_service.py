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
