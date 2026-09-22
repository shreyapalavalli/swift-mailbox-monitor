import httpx
from urllib.parse import quote

from app.config.settings import settings
from app.graph.auth_service import GraphAuthService


class GraphClient:

    def __init__(self):
        self.auth_service = GraphAuthService()

    async def get(
        self,
        url: str,
        params: dict | None = None
    ) -> dict:

        token = await self.auth_service.get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
                params=params,
                timeout=60.0,
            )

        if response.status_code >= 400:
            print("\n========== GRAPH API ERROR ==========")
            print("Status:", response.status_code)
            print("URL:", response.url)
            print("Response:", response.text)
            print("Response headers:", dict(response.headers))
            print(
                "WWW-Authenticate:",
                response.headers.get("www-authenticate")
            )
            print("=====================================\n")

        response.raise_for_status()

        return response.json()

    async def patch(
        self,
        url: str,
        data: dict
    ) -> None:

        token = await self.auth_service.get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers=headers,
                json=data,
                timeout=60.0,
            )

        if response.status_code >= 400:
            print("\n========== GRAPH API ERROR ==========")
            print("Status:", response.status_code)
            print("URL:", response.url)
            print("Response:", response.text)
            print("Response headers:", dict(response.headers))
            print(
                "WWW-Authenticate:",
                response.headers.get("www-authenticate")
            )
            print("=====================================\n")

        response.raise_for_status()

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