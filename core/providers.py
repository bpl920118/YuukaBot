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
    env_key_name: str


@dataclass(frozen=True)
class SwitchProfile:
    """One Discord /api switch choice: provider + concrete model."""

    id: str
    label: str
    provider_id: str
    model: str


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
        env_key_name="DEEPSEEK_API_KEY",
    ),
    "gemini": ProviderPreset(
        id="gemini",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        # New API keys: 2.5.* blocked — use 3.x (see Google model migration notice).
        default_model="gemini-3.6-flash",
        aliases={
            "flash": "gemini-3.6-flash",
            "lite": "gemini-3.5-flash-lite",
            "pro": "gemini-3.1-pro-preview",
            "gemini-3.6-flash": "gemini-3.6-flash",
            "gemini-3.5-flash-lite": "gemini-3.5-flash-lite",
            "gemini-3.1-pro-preview": "gemini-3.1-pro-preview",
            "gemini-3-flash-preview": "gemini-3-flash-preview",
            # Legacy ids kept for older keys / freeform /model
            "gemini-2.5-flash": "gemini-2.5-flash",
            "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
            "gemini-2.5-pro": "gemini-2.5-pro",
        },
        supports_thinking=False,
        env_key_name="GEMINI_API_KEY",
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
        env_key_name="OPENAI_API_KEY",
    ),
}

# Discord /api switch — labels show provider + model at a glance.
SWITCH_PROFILES: dict[str, SwitchProfile] = {
    p.id: p
    for p in (
        SwitchProfile(
            "deepseek-flash",
            "DeepSeek · V4 Flash（日常）",
            "deepseek",
            "deepseek-v4-flash",
        ),
        SwitchProfile(
            "deepseek-pro",
            "DeepSeek · V4 Pro（重推理）",
            "deepseek",
            "deepseek-v4-pro",
        ),
        SwitchProfile(
            "gemini-flash",
            "Gemini · 3.6 Flash（日常・建議）",
            "gemini",
            "gemini-3.6-flash",
        ),
        SwitchProfile(
            "gemini-lite",
            "Gemini · 3.5 Flash Lite（更省）",
            "gemini",
            "gemini-3.5-flash-lite",
        ),
        SwitchProfile(
            "gemini-pro",
            "Gemini · 3.1 Pro Preview（高品質）",
            "gemini",
            "gemini-3.1-pro-preview",
        ),
        SwitchProfile(
            "openai-mini",
            "OpenAI · gpt-4o-mini",
            "openai",
            "gpt-4o-mini",
        ),
        SwitchProfile(
            "openai-pro",
            "OpenAI · gpt-4o",
            "openai",
            "gpt-4o",
        ),
    )
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


def get_switch_profile(profile_id: str) -> SwitchProfile | None:
    return SWITCH_PROFILES.get((profile_id or "").strip().lower())


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


def normalize_provider_id(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if key in PRESETS:
        return key
    return "deepseek"


def default_base_url(provider_id: str, *, deepseek_base_url: str) -> str:
    pid = normalize_provider_id(provider_id)
    if pid == "deepseek":
        return (deepseek_base_url or PRESETS["deepseek"].base_url).rstrip("/")
    return PRESETS[pid].base_url


def default_model_for_provider(
    provider_id: str,
    *,
    deepseek_model: str,
    gemini_model: str,
    openai_model: str,
) -> str:
    pid = normalize_provider_id(provider_id)
    if pid == "deepseek":
        return (deepseek_model or PRESETS["deepseek"].default_model).strip()
    if pid == "gemini":
        return (gemini_model or PRESETS["gemini"].default_model).strip()
    if pid == "openai":
        return (openai_model or PRESETS["openai"].default_model).strip()
    return PRESETS["deepseek"].default_model


def api_key_for_provider(
    provider_id: str,
    *,
    deepseek_api_key: str,
    gemini_api_key: str,
    openai_api_key: str,
) -> tuple[str, str]:
    """Return (key, source_label) for .env slots. custom → DeepSeek key as last resort."""
    pid = (provider_id or "").strip().lower()
    if pid == "gemini":
        key = (gemini_api_key or "").strip()
        return key, "GEMINI_API_KEY"
    if pid == "openai":
        key = (openai_api_key or "").strip()
        return key, "OPENAI_API_KEY"
    # deepseek + custom
    key = (deepseek_api_key or "").strip()
    return key, "DEEPSEEK_API_KEY"


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


def model_menu_lines(provider_id: str) -> str:
    """Short help listing aliases for the active provider."""
    preset = get_preset(provider_id)
    if not preset:
        return "自訂廠商：請直接輸入完整模型 id。"
    parts: list[str] = []
    for alias in ("flash", "pro", "lite", "mini"):
        if alias in preset.aliases:
            parts.append(f"`{alias}`→`{preset.aliases[alias]}`")
    return "別名：" + "、".join(parts) if parts else f"預設 `{preset.default_model}`"
