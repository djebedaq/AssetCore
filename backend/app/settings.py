from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AssetCore"
    database_url: str = "sqlite:///./assetcore.db"
    secret_key: str = "change-me-before-production"
    access_token_minutes: int = 720
    frontend_origin: str = "http://localhost:5173"
    admin_email: str = "admin@assetcore.local"
    admin_password: str = "AssetCore123!"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
