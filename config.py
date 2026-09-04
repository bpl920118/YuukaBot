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

    # Default provider when guild has no /api override: deepseek | gemini | openai
    llm_provider: str = "deepseek"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    # Thinking depth when guild override is empty: off | high | max
    deepseek_depth: str = "off"

    # Optional extra providers — /api switch|preset 會依廠商自動選對應金鑰
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Flash chat sampling (ignored by API when thinking is on)
    llm_temperature: float = 1.0
    llm_top_p: float = 0.9
    llm_max_tokens: int = 512

    # Stable Diffusion WebUI (A1111 / Forge). Empty URL => skip image generation.
    sd_webui_url: str = ""
    sd_webui_checkpoint: str = "kivotos-xl-2.0.safetensors"
    sd_webui_sampler: str = "Euler a"
    sd_webui_steps: int = 28
    sd_webui_cfg: float = 7.0
    sd_webui_width: int = 832
    sd_webui_height: int = 1216
    sd_webui_timeout: int = 300
    sd_webui_negative_prompt: str = (
        "(low quality, worst quality:1.2), very displeasing, 3d, "
        "watermark, signature, ugly, poorly drawn"
    )

    database_url: str = "sqlite+aiosqlite:///./yuuka.db"
    image_dir: Path = ROOT / "storage" / "images"
    character_dir: Path = ROOT / "characters"

    teacher_user_id: int = 695576841125232661

    cg_cooldown_seconds: int = 600
    cg_daily_limit: int = 8
    user_chat_cooldown_seconds: int = 3
    memory_limit: int = 16
    max_affection_delta: int = 15

    default_character_id: str = "yuuka"


@lru_cache
def get_settings() -> Settings:
    return Settings()
