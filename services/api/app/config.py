from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemma_base_url: str = "http://127.0.0.1:8000/v1"
    gemma_model: str = "gemma-4"
    gemma_api_key: str = "local"
    s3_endpoint: str = "http://127.0.0.1:8333"
    s3_access_key: str = "gemma"
    s3_secret_key: str = "change-me"
    s3_bucket: str = "gemma-mcp"
    s3_region: str = "us-east-1"
    mcp_url: str = "http://127.0.0.1:8765/mcp"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

