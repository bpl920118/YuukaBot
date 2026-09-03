from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_token: str = ""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    flux_api_key: str = ""
    flux_base_url: str = ""
    flux_model_normal: str = "flux-2-klein-9b"
    flux_model_special: str = "flux-2-pro"

    database_url: str = "sqlite+aiosqlite:///./yuuka.db"
    image_dir: Path = ROOT / "storage" / "images"
    character_dir: Path = ROOT / "characters"

    teacher_user_id: int = 695576841125232661

    cg_cooldown_seconds: int = 600
    cg_daily_limit: int = 8
    user_chat_cooldown_seconds: int = 3
    memory_limit: int = 12
    max_affection_delta: int = 15

    default_character_id: str = "yuuka"


@lru_cache
def get_settings() -> Settings:
    return Settings()
