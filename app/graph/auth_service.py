from datetime import datetime, timedelta, timezone
from typing import Any

import msal

from app.config.settings import settings


class GraphAuthService:
    def __init__(self):
        self._app = msal.PublicClientApplication(
            client_id=settings.graph_client_id,
            authority=(
                f"https://login.microsoftonline.com/"
                f"{settings.graph_tenant_id}"
            ),
        )
        self._auth_flow: dict[str, Any] | None = None
        self._account: dict[str, Any] | None = None
        self._access_token: str | None = None
        self._expires_at: datetime | None = None

    def get_authorization_url(self) -> str:
        self._auth_flow = self._app.initiate_auth_code_flow(
            scopes=settings.graph_scope_list,
            redirect_uri=settings.graph_redirect_uri,
            prompt="consent",
        )

        return self._auth_flow["auth_uri"]

    def complete_authorization(
        self,
        auth_response: dict[str, Any]
    ) -> None:
        if not self._auth_flow:
            raise RuntimeError("No Microsoft sign-in is currently pending.")

        result = self._app.acquire_token_by_auth_code_flow(
            self._auth_flow,
            auth_response,
        )
        self._auth_flow = None

        if "error" in result:
            raise RuntimeError(
                result.get("error_description", result["error"])
            )

        self._access_token = result.get("access_token")
        expires_in = int(result.get("expires_in", 3600))
        self._expires_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=expires_in)
        )

        account = result.get("account")

        if not account:
            claims = result.get("id_token_claims", {})
            username = claims.get("preferred_username")

            if username:
                account = next(
                    (
                        cached_account
                        for cached_account in self._app.get_accounts()
                        if cached_account.get("username") == username
                    ),
                    None,
                )

        if not account:
            accounts = self._app.get_accounts()
            account = accounts[0] if accounts else None

        self._account = account

        if not self._access_token:
            raise RuntimeError("Microsoft did not return an access token.")

    def logout(self) -> None:
        self._account = None
        self._auth_flow = None
        self._access_token = None
        self._expires_at = None

    @property
    def is_authenticated(self) -> bool:
        return (
            self._access_token is not None
            and self._expires_at is not None
            and datetime.now(timezone.utc) < self._expires_at
        )

    async def get_access_token(self) -> str:
        """
        Return a delegated access token for the signed-in Microsoft user.
        """
        if self._account:
            result = self._app.acquire_token_silent(
                scopes=settings.graph_scope_list,
                account=self._account,
            )

            if result and "access_token" in result:
                self._access_token = result["access_token"]
                expires_in = int(result.get("expires_in", 3600))
                self._expires_at = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=expires_in)
                )

        if (
            self._expires_at is not None
            and datetime.now(timezone.utc) >= self._expires_at
        ):
            self._access_token = None
            self._expires_at = None

        if not self._access_token:
            raise RuntimeError(
                "Microsoft sign-in required. Visit /auth/login first."
            )

        return self._access_token