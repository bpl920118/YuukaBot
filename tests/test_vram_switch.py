from __future__ import annotations

import asyncio

from clients import vram_switch as vs


def test_prepare_for_sd_noop_without_agent(monkeypatch) -> None:
    class S:
        home_vram_agent_url = ""
        home_vram_agent_token = "x"
        home_vram_agent_timeout = 10
        home_vram_reload_llm = True
        home_vram_reload_llm_always = False

    monkeypatch.setattr(vs, "get_settings", lambda: S())
    called = {"n": 0}

    async def fake_release(base: str, model: str | None = None) -> None:
        called["n"] += 1

    monkeypatch.setattr(vs, "release_home_llm_vram", fake_release)
    monkeypatch.setattr(vs, "is_home_inference_url", lambda url: False)
    out = asyncio.run(vs.prepare_for_sd("https://api.deepseek.com", None))
    assert out["agent"] is None
    assert called["n"] == 0


def test_prepare_for_sd_calls_agent(monkeypatch) -> None:
    class S:
        home_vram_agent_url = "http://127.0.0.1:5010"
        home_vram_agent_token = "tok"
        home_vram_agent_timeout = 10
        home_vram_reload_llm = True
        home_vram_reload_llm_always = False

    monkeypatch.setattr(vs, "get_settings", lambda: S())

    async def fake_post(path: str, *, timeout: float):
        assert path == "/switch/sd"
        return {"ok": True, "mode": "sd"}

    monkeypatch.setattr(vs, "_agent_post", fake_post)
    out = asyncio.run(vs.prepare_for_sd("http://127.0.0.1:5001/v1", "m"))
    assert out["agent"]["ok"] is True


def test_restore_respects_flag(monkeypatch) -> None:
    class S:
        home_vram_agent_url = "http://127.0.0.1:5010"
        home_vram_agent_token = "tok"
        home_vram_agent_timeout = 10
        home_vram_reload_llm = False
        home_vram_reload_llm_always = False

    monkeypatch.setattr(vs, "get_settings", lambda: S())
    out = asyncio.run(vs.restore_after_sd("http://127.0.0.1:5001/v1", "m"))
    assert out["skipped"] is True
