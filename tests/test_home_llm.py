from __future__ import annotations

from core.home_llm import (
    home_api_key_or_placeholder,
    is_home_inference_url,
    should_omit_json_response_format,
)


def test_loopback_is_home() -> None:
    assert is_home_inference_url("http://127.0.0.1:11434/v1")
    assert is_home_inference_url("http://localhost:5001/v1")


def test_tailscale_cgnat_is_home() -> None:
    assert is_home_inference_url("http://100.64.1.2:5001/v1")
    assert is_home_inference_url("http://100.100.50.1:11434/v1")


def test_cloud_not_home() -> None:
    assert not is_home_inference_url("https://api.deepseek.com")
    assert not is_home_inference_url(
        "https://generativelanguage.googleapis.com/v1beta/openai"
    )


def test_placeholder_key() -> None:
    assert home_api_key_or_placeholder("", "http://127.0.0.1:5001/v1") == "local"
    assert home_api_key_or_placeholder("sk-x", "http://127.0.0.1:5001/v1") == "sk-x"
    assert home_api_key_or_placeholder("", "https://api.deepseek.com") == ""


def test_omit_response_format_home_only() -> None:
    assert should_omit_json_response_format("http://100.64.0.1:11434/v1")
    assert not should_omit_json_response_format("https://api.deepseek.com")
