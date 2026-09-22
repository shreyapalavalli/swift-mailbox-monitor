from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    graph_tenant_id: str
    graph_client_id: str
    swift_mailbox: str

    graph_base_url: str = "https://graph.microsoft.com/v1.0"
    graph_redirect_uri: str = "http://localhost:8000/auth/callback"
    graph_scopes: str = "Mail.ReadWrite User.Read"

    @property
    def graph_scope_list(self) -> list[str]:
        reserved_scopes = {"offline_access", "openid", "profile"}
        return [
            scope
            for scope in self.graph_scopes.split()
            if scope not in reserved_scopes
        ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()