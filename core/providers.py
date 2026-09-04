"""OpenAI-compatible chat providers (DeepSeek / Gemini / OpenAI / custom)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    base_url: str
    default_model: str
    aliases: dict[str, str]
    supports_thinking: bool


PRESETS: dict[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        id="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        aliases={
            "flash": "deepseek-v4-flash",
            "pro": "deepseek-v4-pro",
            "v4-flash": "deepseek-v4-flash",
            "v4-pro": "deepseek-v4-pro",
            "deepseek-v4-flash": "deepseek-v4-flash",
            "deepseek-v4-pro": "deepseek-v4-pro",
        },
        supports_thinking=True,
    ),
    "gemini": ProviderPreset(
        id="gemini",
        label="Google Gemini (OpenAI 相容)",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.5-flash",
        aliases={
            "flash": "gemini-2.5-flash",
            "lite": "gemini-2.5-flash-lite",
            "pro": "gemini-2.5-pro",
            "gemini-2.5-flash": "gemini-2.5-flash",
            "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
            "gemini-2.5-pro": "gemini-2.5-pro",
            "gemini-2.0-flash": "gemini-2.0-flash",
        },
        supports_thinking=False,
    ),
    "openai": ProviderPreset(
        id="openai",
        label="OpenAI",
        base_url="https://api.openai.com",
        default_model="gpt-4o-mini",
        aliases={
            "flash": "gpt-4o-mini",
            "mini": "gpt-4o-mini",
            "pro": "gpt-4o",
            "gpt-4o-mini": "gpt-4o-mini",
            "gpt-4o": "gpt-4o",
        },
        supports_thinking=False,
    ),
}


def detect_provider(base_url: str) -> str:
    host = (urlparse(base_url).netloc or base_url).lower()
    path = (urlparse(base_url).path or "").lower()
    blob = f"{host}{path}"
    if "deepseek" in blob:
        return "deepseek"
    if "generativelanguage" in blob or "googleapis" in blob:
        return "gemini"
    if "openai.com" in blob and "azure" not in blob:
        return "openai"
    return "custom"


def get_preset(preset_id: str) -> ProviderPreset | None:
    return PRESETS.get((preset_id or "").strip().lower())


def supports_thinking(base_url: str) -> bool:
    pid = detect_provider(base_url)
    preset = PRESETS.get(pid)
    if preset:
        return preset.supports_thinking
    return "deepseek" in (base_url or "").lower()


def chat_completions_url(base_url: str) -> str:
    """Build chat completions URL for OpenAI-compatible gateways."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = "https://api.deepseek.com"
    lower = base.lower()
    if lower.endswith("/v1") or lower.endswith("/openai"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def normalize_base_url(raw: str) -> str:
    text = (raw or "").strip().rstrip("/")
    if not text:
        raise ValueError("網址不可空白。")
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    return text.rstrip("/")


def mask_api_key(key: str) -> str:
    text = (key or "").strip()
    if not text:
        return "（未設定）"
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}…{text[-4:]}（len={len(text)}）"


def resolve_model_name(
    raw: str | None,
    fallback: str,
    *,
    base_url: str,
) -> str:
    """Resolve flash/pro aliases for the active provider, or accept freeform ids."""
    key = (raw or "").strip()
    if not key:
        return fallback
    lower = key.lower()
    pid = detect_provider(base_url)
    preset = PRESETS.get(pid)
    if preset and lower in preset.aliases:
        return preset.aliases[lower]
    # Legacy DeepSeek aliases still work when on DeepSeek.
    if pid == "deepseek":
        from core.llm_options import ALLOWED_MODELS

        if lower in ALLOWED_MODELS:
            return ALLOWED_MODELS[lower]
    # Short aliases are provider-specific — don't treat as freeform model ids.
    if lower in {"flash", "pro", "lite", "mini"}:
        return fallback
    # Freeform model id (gemini-2.5-flash, qwen-plus, …).
    if 1 <= len(key) <= 128 and " " not in key:
        return key
    return fallback
