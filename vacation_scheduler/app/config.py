from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Vacation Scheduler"
    secret_key: str = "CHANGE_ME_BEFORE_DEPLOYMENT"
    database_url: str = "postgresql+psycopg://vacation:vacation@db:5432/vacation"
    storage_path: str = "/storage"
    debug: bool = False
    session_https_only: bool = False
    session_max_age: int = 60 * 60 * 8

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if len(value) < 32 or value.lower().startswith(("change_me", "replace-with", "your-secret")):
            raise ValueError(
                "SECRET_KEY must be a unique random value containing at least 32 characters."
            )
        return value

    @field_validator("session_max_age")
    @classmethod
    def validate_session_max_age(cls, value: int) -> int:
        if not 300 <= value <= 2_592_000:
            raise ValueError("SESSION_MAX_AGE must be between 300 and 2592000 seconds.")
        return value

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
