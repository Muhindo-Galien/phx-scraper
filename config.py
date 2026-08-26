from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHX_", env_file=".env", extra="ignore")

    getro_base_url: str = "https://api.getro.com/api/v2"
    collection_id: int = 10289
    hits_per_page: int = 20
    batch_size: int = 20
    max_concurrency: int = 20
    max_pages: int = 100
    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    max_retries: int = 3
    backoff_base: float = 0.5
    backoff_max: float = 8.0
    user_agent: str = "phx-scraper/0.1 (+https://github.com/olame1/phx-scraper)"


@lru_cache
def get_settings() -> Settings:
    return Settings()
