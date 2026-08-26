from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AssetCore"
    database_url: str = "sqlite:///./assetcore.db"
    secret_key: str = "change-me-before-production"
    access_token_minutes: int = 720
    session_minutes: int = Field(default=720, ge=5, le=43_200)
    session_cookie_name: str = "assetcore_session"
    csrf_cookie_name: str = "assetcore_csrf"
    session_cookie_samesite: Literal["lax", "strict"] = "lax"
    bearer_compatibility_enabled: bool = False
    trusted_proxy_ips: str | None = None
    login_rate_limit_attempts: int = Field(default=5, ge=2, le=100)
    login_source_rate_limit_attempts: int = Field(default=40, ge=5, le=1000)
    login_rate_limit_window_seconds: int = Field(default=300, ge=30, le=86_400)
    login_rate_limit_base_block_seconds: int = Field(default=30, ge=1, le=3600)
    login_rate_limit_max_block_seconds: int = Field(default=300, ge=1, le=86_400)
    sensitive_rate_limit_attempts: int = Field(default=5, ge=2, le=100)
    sensitive_rate_limit_window_seconds: int = Field(default=300, ge=30, le=86_400)
    sensitive_rate_limit_base_block_seconds: int = Field(default=30, ge=1, le=3600)
    sensitive_rate_limit_max_block_seconds: int = Field(default=300, ge=1, le=86_400)
    auth_state_retention_days: int = Field(default=7, ge=1, le=365)
    frontend_origin: str = "http://localhost:5173"
    frontend_origins: str | None = None
    public_base_url: str | None = None
    # Legacy variables remain optional only for migrations from older releases.
    # No usable credential is embedded in the application.
    admin_email: str | None = None
    admin_password: str | None = None
    assetcore_owner_email: str | None = None
    owner_first_name: str | None = "Евтим"
    owner_middle_name: str | None = "Станиславов"
    owner_last_name: str | None = "Горанов"
    owner_email: str | None = None
    owner_job_title: str | None = None
    owner_initial_password: str | None = None
    license_public_key: str | None = None
    license_enforcement_enabled: bool = False
    installation_id: str | None = None
    deployment_environment: str = "development"
    signature_encryption_key: str | None = None
    production_mode: bool = False

    @model_validator(mode="after")
    def reject_unsafe_production_bootstrap(self):
        if self.deployment_environment not in {"development", "test", "staging", "production"}:
            raise ValueError("DEPLOYMENT_ENVIRONMENT is invalid")
        if self.production_mode:
            if self.secret_key == "change-me-before-production":
                raise ValueError("SECRET_KEY must be configured in production")
            if not self.owner_email and not self.assetcore_owner_email:
                raise ValueError("OWNER_EMAIL must be configured in production")
            if not self.signature_encryption_key:
                raise ValueError("SIGNATURE_ENCRYPTION_KEY must be configured in production")
            if self.license_enforcement_enabled and (
                not self.license_public_key or not self.installation_id
            ):
                raise ValueError(
                    "LICENSE_PUBLIC_KEY and INSTALLATION_ID are required when licence enforcement is enabled"
                )
        production_like = self.production_mode or self.deployment_environment in {
            "staging",
            "production",
        }
        explicitly_configured = bool(self.frontend_origins) or (
            "frontend_origin" in self.model_fields_set and bool(self.frontend_origin)
        )
        if production_like and not explicitly_configured:
            raise ValueError(
                "FRONTEND_ORIGIN or FRONTEND_ORIGINS must be explicitly configured "
                "for staging and production"
            )
        if production_like and self.bearer_compatibility_enabled:
            raise ValueError(
                "BEARER_COMPATIBILITY_ENABLED is restricted to development/test CLI compatibility"
            )
        if self.login_rate_limit_base_block_seconds > self.login_rate_limit_max_block_seconds:
            raise ValueError("Login rate-limit base block cannot exceed its maximum")
        if self.sensitive_rate_limit_base_block_seconds > self.sensitive_rate_limit_max_block_seconds:
            raise ValueError("Sensitive rate-limit base block cannot exceed its maximum")
        return self

    @property
    def browser_cookie_secure(self) -> bool:
        return self.production_mode or self.deployment_environment in {
            "staging",
            "production",
        }

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
