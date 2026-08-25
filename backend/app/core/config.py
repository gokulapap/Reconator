from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Reconator"
    app_version: str = "3.0.0"
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"

    database_url: str | None = None
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "reconator"
    postgres_user: str = "reconator"
    postgres_password: str = "reconator"

    # Auth — when admin_api_key is unset, mutations are open (dev mode).
    admin_api_key: str | None = None
    protect_read_endpoints: bool = False

    # Rate limiting (writes only)
    rate_limit_writes: str = "20/minute"
    rate_limit_bulk: str = "5/minute"

    # Notifications
    telegram_api_key: str | None = None
    telegram_chat_id: str | None = None
    webhook_url: str | None = None
    webhook_kind: str = "generic"  # generic | slack | discord
    allow_private_webhooks: bool = False

    # Observability
    sentry_dsn: str | None = None
    metrics_enabled: bool = True

    # Worker
    worker_poll_interval_seconds: int = Field(default=30, ge=1, le=300)
    module_timeout_seconds: int = Field(default=1800, ge=1, le=86400)
    max_concurrent_scans: int = Field(default=1, ge=1, le=256)
    recon_engine_enabled: bool = True
    task_lease_seconds: int = Field(default=180, ge=30, le=86400)
    task_retry_base_seconds: int = Field(default=5, ge=1, le=3600)
    max_concurrent_tasks: int = Field(default=4, ge=1, le=256)
    max_concurrent_tasks_per_target: int = Field(default=2, ge=1, le=64)
    max_tasks_per_scan: int = Field(default=10_000, ge=1, le=1_000_000)
    max_asset_emissions_per_task: int = Field(default=20_000, ge=1, le=250_000)
    max_relationship_emissions_per_task: int = Field(default=20_000, ge=1, le=250_000)
    max_emission_metadata_bytes: int = Field(default=65_536, ge=1_024, le=1_000_000)
    max_raw_output_bytes: int = Field(default=2_000_000, ge=0, le=100_000_000)
    max_raw_output_bytes_per_scan: int = Field(default=50_000_000, ge=0, le=10_000_000_000)
    max_request_body_bytes: int = Field(default=1_000_000, ge=1_024, le=100_000_000)
    allow_private_targets: bool = False
    require_authorization_confirmation: bool = True
    modules_dir: str = "/app/modules"
    results_dir: str = "/app/results"

    # Isolated third-party tool execution plane. Keep unset for a pure-Python
    # deployment; Docker Compose provisions and authenticates it by default.
    toolbox_enabled: bool = False
    toolbox_url: str | None = None
    toolbox_shared_secret: str | None = None

    # Static frontend
    serve_static_web: bool = False
    static_web_dir: str = "/app/static_web"

    # DB pool
    db_pool_size: int = Field(default=5, ge=1, le=256)
    db_max_overflow: int = Field(default=10, ge=0, le=512)

    @computed_field  # type: ignore[misc]
    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg://", 1)
            elif url.startswith("postgresql://") and "+psycopg" not in url:
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            return url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.admin_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
