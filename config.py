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
    # Cloud default slightly below 1.0 — tighter Yuuka voice, less drift.
    llm_temperature: float = 0.95
    llm_top_p: float = 0.92
    llm_max_tokens: int = 512
    # Home Qwen／Kobold：略提高溫換說法；仍靠短卡禁套話壓住跑題
    home_llm_temperature: float = 0.9
    home_llm_top_p: float = 0.92
    # MomoTalk 主動動態
    momotalk_temperature: float = 0.95
    momotalk_top_p: float = 0.92
    momotalk_max_tokens: int = 220

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

    # Home LLM (localhost / Tailscale / whitelist) — prompt budget + VRAM release.
    # Comma-separated hostnames, e.g. "my-pc,100.64.1.2"
    home_llm_hosts: str = ""
    # Treat RFC1918 private IPs as home (LAN). Default off — prefer Tailscale 100.x.
    home_llm_trust_private: bool = False
    lore_scan_depth: int = 6
    lore_max_chars: int = 900
    memory_summary_max_chars: int = 400

    # Home VRAM agent (scripts/home_vram_agent.py on the PC with Kobold+WebUI).
    # Example local: http://127.0.0.1:5010  | Tailscale: http://100.x.y.z:5010
    home_vram_agent_url: str = ""
    home_vram_agent_token: str = "yuuka-local"
    home_vram_agent_timeout: int = 240
    # After CG, ask agent to bring text LLM back (agent may stop WebUI).
    home_vram_reload_llm: bool = True
    # Kept for .env compatibility; reload follows home_vram_reload_llm.
    home_vram_reload_llm_always: bool = True
    # Home-LLM chat: if Kobold was stopped for CG, auto switch back before reply.
    home_vram_ensure_llm_on_chat: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
