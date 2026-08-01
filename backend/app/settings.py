from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AssetCore"
    database_url: str = "sqlite:///./assetcore.db"
    secret_key: str = "change-me-before-production"
    access_token_minutes: int = 720
    frontend_origin: str = "http://localhost:5173"
    public_base_url: str | None = None
    admin_email: str = "admin@assetcore.local"
    admin_password: str = "change-me-before-use"
    assetcore_owner_email: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_postgresql_driver(cls, value: str) -> str:
        """Render provides a generic PostgreSQL URL; SQLAlchemy needs psycopg v3."""
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
