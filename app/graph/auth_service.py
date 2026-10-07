import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import msal

from app.config.settings import settings


class SignInRequiredError(RuntimeError):
    """Raised when no usable Microsoft token exists and the user must sign in."""


class GraphAuthService:
    def __init__(self, cache_path: str | None = None):
        self._cache_path = Path(cache_path or settings.token_cache_path)
        self._cache = msal.SerializableTokenCache()

        if self._cache_path.exists():
            self._cache.deserialize(
                self._cache_path.read_text(encoding="utf-8")
            )

        self._app = msal.PublicClientApplication(
            client_id=settings.graph_client_id,
            authority=(
                f"https://login.microsoftonline.com/"
                f"{settings.graph_tenant_id}"
            ),
            token_cache=self._cache,
        )
        self._auth_flow: dict[str, Any] | None = None
        accounts = self._app.get_accounts()
        self._account: dict[str, Any] | None = (
            accounts[0] if accounts else None
        )
        self._access_token: str | None = None
        self._expires_at: datetime | None = None

    def _reload_account(self) -> None:
        """Pick up a sign-in written to the cache file by another process (e.g. the CLI)."""
        if not self._cache_path.exists():
            return
        self._cache.deserialize(self._cache_path.read_text(encoding="utf-8"))
        accounts = self._app.get_accounts()
        self._account = accounts[0] if accounts else None

    def _save_cache(self) -> None:
        if not self._cache.has_state_changed:
            return

        fd = os.open(
            self._cache_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as cache_file:
            os.fchmod(cache_file.fileno(), 0o600)
            cache_file.write(self._cache.serialize())

        self._cache.has_state_changed = False

    def _remember_token(self, result: dict[str, Any]) -> None:
        self._access_token = result.get("access_token")
        expires_in = int(result.get("expires_in", 3600))
        self._expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        )

    def login_device_flow(
        self,
        echo: Callable[[str], None] = print,
    ) -> str:
        flow = self._app.initiate_device_flow(
            scopes=settings.graph_scope_list
        )

        if "user_code" not in flow:
            raise RuntimeError(
                flow.get("error_description", "Device flow failed to start.")
            )

        echo(flow["message"])
        result = self._app.acquire_token_by_device_flow(flow)
        self._save_cache()

        if "error" in result:
            raise RuntimeError(
                result.get("error_description", result["error"])
            )

        self._remember_token(result)
        accounts = self._app.get_accounts()
        self._account = accounts[0] if accounts else None

        claims = result.get("id_token_claims", {})
        return (
            claims.get("preferred_username")
            or (self._account or {}).get("username")
            or ""
        )

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
        self._save_cache()

        if "error" in result:
            raise RuntimeError(
                result.get("error_description", result["error"])
            )

        self._remember_token(result)

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
        for account in self._app.get_accounts():
            self._app.remove_account(account)

        self._save_cache()
        self._account = None
        self._auth_flow = None
        self._access_token = None
        self._expires_at = None

    @property
    def is_authenticated(self) -> bool:
        return self._account is not None or (
            self._access_token is not None
            and self._expires_at is not None
            and datetime.now(timezone.utc) < self._expires_at
        )

    async def get_access_token(self) -> str:
        """
        Return a delegated access token for the signed-in Microsoft user.
        """
        if self._account is None:
            self._reload_account()

        if self._account:
            result = self._app.acquire_token_silent(
                scopes=settings.graph_scope_list,
                account=self._account,
            )

            self._save_cache()

            if result and "access_token" in result:
                self._remember_token(result)

        if (
            self._expires_at is not None
            and datetime.now(timezone.utc) >= self._expires_at
        ):
            self._access_token = None
            self._expires_at = None

        if not self._access_token:
            raise SignInRequiredError(
                "Microsoft sign-in required. Visit /auth/login first."
            )

        return self._access_token