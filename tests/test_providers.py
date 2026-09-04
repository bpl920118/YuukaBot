from __future__ import annotations

from core.providers import (
    chat_completions_url,
    detect_provider,
    mask_api_key,
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
    assert resolve_model_name("flash", "x", base_url=gem) == "gemini-2.5-flash"
    assert resolve_model_name("lite", "x", base_url=ds) == "x"
    assert (
        resolve_model_name("gemini-2.5-flash", "x", base_url=gem)
        == "gemini-2.5-flash"
    )


def test_mask_key() -> None:
    assert "未設定" in mask_api_key("")
    assert "abcd" in mask_api_key("abcdefghijklmnop")
