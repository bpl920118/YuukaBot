from __future__ import annotations

ALLOWED_MODELS = {
    "deepseek-v4-flash": "deepseek-v4-flash",
    "flash": "deepseek-v4-flash",
    "v4-flash": "deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek-v4-pro",
    "pro": "deepseek-v4-pro",
    "v4-pro": "deepseek-v4-pro",
}

ALLOWED_DEPTHS = {
    "off": "off",
    "關": "off",
    "关闭": "off",
    "關閉": "off",
    "disabled": "off",
    "0": "off",
    "high": "high",
    "高": "high",
    "一般": "high",
    "default": "high",
    "max": "max",
    "最大": "max",
    "深": "max",
    "深度": "max",
}


def resolve_model(raw: str | None, fallback: str) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return fallback
    return ALLOWED_MODELS.get(key, fallback if key not in ALLOWED_MODELS.values() else key)


def parse_model_arg(raw: str) -> str | None:
    key = raw.strip().lower()
    if not key:
        return None
    return ALLOWED_MODELS.get(key)


def resolve_depth(raw: str | None, fallback: str) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return fallback if fallback in {"off", "high", "max"} else "off"
    return ALLOWED_DEPTHS.get(key, fallback if fallback in {"off", "high", "max"} else "off")


def parse_depth_arg(raw: str) -> str | None:
    key = raw.strip().lower()
    if not key:
        return None
    return ALLOWED_DEPTHS.get(key)
