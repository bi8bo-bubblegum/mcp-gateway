from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="GATEWAY_",
        extra="ignore",
    )

    database_url: str = (
        "mysql+aiomysql://root:root@127.0.0.1:3306/mcp_gateway?charset=utf8mb4"
    )
    db_echo: bool = False

    host: str = "127.0.0.1"
    port: int = 8800
    mcp_path: str = "/mcp"

    admin_username: str = "admin"
    admin_password: str = "admin_best"

    secret_key: str = "dev-only-change-me"

    policy_cache_ttl: float = 30.0
    revision_poll_interval: float = 1.0
    revision_cache_ttl: float = 1.0
    health_interval: float = 30.0
    health_timeout: float = 5.0
    health_failure_threshold: int = 2
    health_max_concurrency: int = 8

    upstream_timeout: float = 30.0
    discovery_timeout: float = 15.0

@lru_cache
def get_settings() -> Settings:
    return Settings()