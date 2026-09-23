from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash-lite"

    entity_extractor_version: str = "entity-v1"
    entity_extract_max_chars: int = 24_000

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()