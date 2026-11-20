from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemma_base_url: str = "http://127.0.0.1:8000/v1"
    gemma_model: str = "gemma-4-e2b"
    gemma_api_key: str = "local"
    gemma_system_prompt: str = (
        "You are MIRGAM, a concise smart-farm assistant. Answer in the user's language. "
        "Summarize only the sensor readings, image-analysis results, and weather data provided in the conversation. "
        "Include key values, units, and trends; do not invent missing data. Keep routine summaries brief."
    )
    gemma_temperature: float = 0.3
    gemma_context_size: int = 2048
    gemma_max_output_tokens: int = 384
    gemma_enable_thinking: bool = False
    sqlite_path: str = "/workspace/storage/state/mirgam.db"
    mcp_url: str = "http://127.0.0.1:8765/mcp"
    mcp_max_tool_rounds: int = 3
    demo_simulator_enabled: bool = True
    demo_simulator_interval_seconds: int = 15
    mirgam_database_url: SecretStr | None = None
    vworld_key: SecretStr | None = None
    vworld_domain: str | None = None
    data_root: Path = Path("/workspace/storage")
    beacon_admin_url: str = "http://beacon:8081"
    beacon_image_dir: Path = Path("/beacon-data/images")
    beacon_poll_interval_seconds: int = 5
    calc_crs: str = "EPSG:5186"
    vworld_sat_min_z: int = 13
    vworld_sat_max_z: int = 19
    tile_ttl_days: int = 180
    max_crop_tiles: int = 400
    max_crop_pixels: int = 30_000_000
    auth_cookie_name: str = "mirgam_session"
    auth_cookie_secure: bool = False
    auth_session_ttl_seconds: int = 43200
    log_level: str = "INFO"

    @field_validator("mirgam_database_url", mode="before")
    @classmethod
    def empty_database_url_is_unset(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
