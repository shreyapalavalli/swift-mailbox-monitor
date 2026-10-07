from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    graph_tenant_id: str
    graph_client_id: str
    swift_mailbox: str

    graph_base_url: str = "https://graph.microsoft.com/v1.0"
    graph_redirect_uri: str = "http://localhost:8000/auth/callback"
    graph_scopes: str = "Mail.ReadWrite Mail.Send User.Read"

    token_cache_path: str = ".token_cache.json"
    database_path: str = "data/swift_monitor.db"
    cst_mailbox: str = "shreyapalavalli@gmail.com"
    cancellation_action_mx_types: str = "camt.056"
    poll_folders: str = "inbox,junkemail"
    poll_interval_seconds: int = 30
    poller_enabled: bool = True
    actions_enabled: bool = True
    frontend_origin: str = "http://localhost:5000"

    @property
    def cancellation_action_mx_type_list(self) -> list[str]:
        return [
            item.strip().lower()
            for item in self.cancellation_action_mx_types.split(",")
            if item.strip()
        ]

    @property
    def poll_folder_list(self) -> list[str]:
        return [item.strip() for item in self.poll_folders.split(",") if item.strip()]

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