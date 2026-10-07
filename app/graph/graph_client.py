import logging
from urllib.parse import quote

import httpx

from app.config.settings import settings
from app.graph.auth_service import GraphAuthService

logger = logging.getLogger("swift.graph")


class GraphClient:

    def __init__(
        self,
        auth_service: GraphAuthService | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.auth_service = auth_service or GraphAuthService()
        self._transport = transport

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            logger.warning("Graph API error %s %s: %s", response.status_code,
                           response.url, response.text[:500])

        response.raise_for_status()

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        **kwargs,
    ) -> httpx.Response:
        token = await self.auth_service.get_access_token()
        merged = {"Authorization": f"Bearer {token}", **(headers or {})}

        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.request(
                method,
                url,
                headers=merged,
                timeout=60.0,
                **kwargs,
            )

        self._raise_for_status(response)

        return response

    async def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        response = await self._request(
            "GET",
            url,
            headers={"Accept": "application/json", **(headers or {})},
            params=params,
        )

        return response.json()

    async def patch(
        self,
        url: str,
        data: dict
    ) -> None:
        await self._request("PATCH", url, json=data)

    async def post(
        self,
        url: str,
        data: dict
    ) -> None:
        await self._request("POST", url, json=data)

    async def get_user(
        self,
        user_id: str
    ) -> dict:

        url = (
            f"{settings.graph_base_url}"
            f"/users/{quote(user_id, safe='')}"
        )

        return await self.get(url)

    async def get_current_user(self) -> dict:
        return await self.get(
            f"{settings.graph_base_url}/me"
        )
