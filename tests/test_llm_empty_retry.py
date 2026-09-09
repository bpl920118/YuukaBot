from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from clients import llm as llm_mod
from clients.llm import LlmClient, _empty_backoff_seconds, _gemini_hot_failover
from core.schemas import is_soft_fallback


def test_empty_backoff_schedule() -> None:
    assert _empty_backoff_seconds(1) == 0.4
    assert _empty_backoff_seconds(2) == 1.0
    assert _empty_backoff_seconds(3) == 2.0
    assert _empty_backoff_seconds(9) == 2.0


def test_gemini_hot_failover_requires_key() -> None:
    settings = SimpleNamespace(
        deepseek_api_key="ds",
        gemini_api_key="",
        openai_api_key="",
        gemini_model="gemini-3.6-flash",
    )
    assert (
        _gemini_hot_failover(settings, primary_base="https://api.deepseek.com") is None
    )


def test_gemini_hot_failover_skips_when_already_gemini() -> None:
    settings = SimpleNamespace(
        deepseek_api_key="ds",
        gemini_api_key="gem-key",
        openai_api_key="",
        gemini_model="gemini-3.6-flash",
    )
    gem = "https://generativelanguage.googleapis.com/v1beta/openai"
    assert _gemini_hot_failover(settings, primary_base=gem) is None


def test_gemini_hot_failover_ok_from_deepseek() -> None:
    settings = SimpleNamespace(
        deepseek_api_key="ds",
        gemini_api_key="gem-key",
        openai_api_key="",
        gemini_model="gemini-3.6-flash",
    )
    out = _gemini_hot_failover(settings, primary_base="https://api.deepseek.com")
    assert out is not None
    base, key, model = out
    assert "googleapis" in base
    assert key == "gem-key"
    assert model == "gemini-3.6-flash"


def test_empty_backoff_then_failover(monkeypatch) -> None:
    sleeps: list[float] = []
    urls: list[str] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def fake_post(
        self,
        url: str,
        headers: dict,
        payload: dict,
        timeout: float,
        *,
        provider: str = "",
        model: str = "",
    ) -> str:
        urls.append(url)
        if "deepseek" in url:
            return ""
        return json.dumps(
            {
                "reply": "（抬眼）洗手了沒？",
                "emotion": "angry",
                "trigger_cg": False,
                "cg_tier": "none",
                "cg_scene": None,
                "image_prompt": None,
            },
            ensure_ascii=False,
        )

    settings = SimpleNamespace(
        deepseek_api_key="ds-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-flash",
        deepseek_depth="off",
        gemini_api_key="gem-key",
        gemini_model="gemini-3.6-flash",
        openai_api_key="",
        openai_model="gpt-4o-mini",
        llm_temperature=0.9,
        llm_top_p=0.9,
        llm_max_tokens=256,
        home_llm_temperature=0.9,
        home_llm_top_p=0.9,
        momotalk_temperature=0.9,
        momotalk_top_p=0.9,
        momotalk_max_tokens=128,
    )

    monkeypatch.setattr(llm_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(LlmClient, "_post_once", fake_post)

    client = LlmClient()
    raw = asyncio.run(
        client.chat(
            system="sys",
            messages=[{"role": "user", "content": "測試"}],
            api_key="ds-key",
            base_url="https://api.deepseek.com",
            depth="off",
        )
    )
    data = json.loads(raw)
    assert "洗手" in data["reply"]
    assert not is_soft_fallback(data["reply"])
    assert len(urls) == 3  # 2 empty deepseek + 1 gemini
    assert all("deepseek" in u for u in urls[:2])
    assert "googleapis" in urls[2]
    assert sleeps == [0.4, 1.0]


def test_empty_no_failover_without_gemini_key(monkeypatch) -> None:
    urls: list[str] = []

    async def fake_sleep(_delay: float) -> None:
        return None

    async def fake_post(
        self,
        url: str,
        headers: dict,
        payload: dict,
        timeout: float,
        *,
        provider: str = "",
        model: str = "",
    ) -> str:
        urls.append(url)
        return ""

    settings = SimpleNamespace(
        deepseek_api_key="ds-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-flash",
        deepseek_depth="off",
        gemini_api_key="",
        gemini_model="gemini-3.6-flash",
        openai_api_key="",
        openai_model="gpt-4o-mini",
        llm_temperature=0.9,
        llm_top_p=0.9,
        llm_max_tokens=256,
        home_llm_temperature=0.9,
        home_llm_top_p=0.9,
        momotalk_temperature=0.9,
        momotalk_top_p=0.9,
        momotalk_max_tokens=128,
    )

    monkeypatch.setattr(llm_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(LlmClient, "_post_once", fake_post)

    client = LlmClient()
    raw = asyncio.run(
        client.chat(
            system="sys",
            messages=[{"role": "user", "content": "測試"}],
            api_key="ds-key",
            base_url="https://api.deepseek.com",
            depth="off",
        )
    )
    data = json.loads(raw)
    assert is_soft_fallback(data["reply"])
    assert len(urls) == 4
    assert all("deepseek" in u for u in urls)
