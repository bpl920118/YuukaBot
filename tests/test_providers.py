from __future__ import annotations

from core.providers import (
    SWITCH_PROFILES,
    api_key_for_provider,
    chat_completions_url,
    default_base_url,
    default_model_for_provider,
    detect_provider,
    get_switch_profile,
    mask_api_key,
    model_menu_lines,
    normalize_provider_id,
    resolve_model_name,
    supports_thinking,
)


def test_chat_completions_url() -> None:
    assert (
        chat_completions_url("https://api.deepseek.com")
        == "https://api.deepseek.com/v1/chat/completions"
    )
    assert (
        chat_completions_url(
            "https://generativelanguage.googleapis.com/v1beta/openai"
        )
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert (
        chat_completions_url("https://api.openai.com/v1")
        == "https://api.openai.com/v1/chat/completions"
    )


def test_detect_and_thinking() -> None:
    assert detect_provider("https://api.deepseek.com") == "deepseek"
    assert supports_thinking("https://api.deepseek.com")
    gemini = "https://generativelanguage.googleapis.com/v1beta/openai"
    assert detect_provider(gemini) == "gemini"
    assert not supports_thinking(gemini)


def test_resolve_model_aliases() -> None:
    ds = "https://api.deepseek.com"
    gem = "https://generativelanguage.googleapis.com/v1beta/openai"
    assert resolve_model_name("flash", "x", base_url=ds) == "deepseek-v4-flash"
    assert resolve_model_name("flash", "x", base_url=gem) == "gemini-3.6-flash"
    assert resolve_model_name("lite", "x", base_url=ds) == "x"
    assert (
        resolve_model_name("gemini-3.6-flash", "x", base_url=gem)
        == "gemini-3.6-flash"
    )


def test_mask_key() -> None:
    assert "未設定" in mask_api_key("")
    assert "abcd" in mask_api_key("abcdefghijklmnop")


def test_multi_env_key_slots() -> None:
    key, src = api_key_for_provider(
        "gemini",
        deepseek_api_key="ds-key",
        gemini_api_key="gem-key",
        openai_api_key="oai-key",
    )
    assert key == "gem-key"
    assert src == "GEMINI_API_KEY"
    key2, src2 = api_key_for_provider(
        "deepseek",
        deepseek_api_key="ds-key",
        gemini_api_key="gem-key",
        openai_api_key="",
    )
    assert key2 == "ds-key" and src2 == "DEEPSEEK_API_KEY"


def test_default_endpoint_from_provider() -> None:
    assert normalize_provider_id("GEMINI") == "gemini"
    base = default_base_url("gemini", deepseek_base_url="https://api.deepseek.com")
    assert "generativelanguage" in base
    model = default_model_for_provider(
        "gemini",
        deepseek_model="deepseek-v4-flash",
        gemini_model="gemini-3.6-flash",
        openai_model="gpt-4o-mini",
    )
    assert model == "gemini-3.6-flash"


def test_switch_profiles() -> None:
    assert "gemini-flash" in SWITCH_PROFILES
    p = get_switch_profile("gemini-flash")
    assert p is not None
    assert p.provider_id == "gemini"
    assert p.model == "gemini-3.6-flash"
    assert "flash" in model_menu_lines("gemini")
