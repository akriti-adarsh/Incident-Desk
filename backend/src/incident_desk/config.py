"""Application settings, loaded from the environment with dev-friendly defaults.

The defaults target the docker-compose stack as seen from the host machine
(non-standard host ports avoid collisions with other local services). Inside
compose, every value is overridden through environment variables.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "incident-desk"
    environment: str = "dev"

    database_url: str = "postgresql+asyncpg://incident:incident@localhost:55433/incident_desk"
    sync_database_url: str = "postgresql+psycopg://incident:incident@localhost:55433/incident_desk"
    redis_url: str = "redis://localhost:56379/0"

    # HS256 needs >= 32 bytes of key material (RFC 7518 section 3.2).
    jwt_secret: str = "dev-only-secret-change-in-production-use-32B+"
    jwt_issuer: str = "incident-desk"
    jwt_audience: str = "incident-desk-api"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_days: int = 30

    attachments_dir: str = "var/attachments"
    attachment_max_bytes: int = 25 * 1024 * 1024

    smtp_host: str = "localhost"
    smtp_port: int = 58025
    email_from: str = "incident-desk <no-reply@incident-desk.local>"
    frontend_base_url: str = "http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
