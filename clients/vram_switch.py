"""Release / switch home-PC LLM VRAM before SD WebUI on the same GPU."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from config import get_settings
from core.home_llm import is_home_inference_url

logger = logging.getLogger(__name__)


def _origin(base_url: str) -> str:
    parsed = urlparse((base_url or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return (base_url or "").rstrip("/")


async def release_home_llm_vram(base_url: str, model: str | None = None) -> None:
    """Best-effort unload so A1111/Forge can use the same 8GB card.

    - Ollama: POST /api/generate keep_alive=0
    - KoboldCPP: try /api/extra/abort (frees generation; full unload may need agent)
    Cloud / non-home URLs: no-op.
    """
    if not is_home_inference_url(base_url):
        return
    origin = _origin(base_url)
    if not origin:
        return
    model_name = (model or "").strip() or "dummy"
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                f"{origin}/api/generate",
                json={
                    "model": model_name,
                    "prompt": "",
                    "keep_alive": 0,
                    "stream": False,
                },
            )
            if resp.status_code < 500:
                logger.info("VRAM: Ollama-style unload attempted (%s)", resp.status_code)
                return
        except Exception as exc:
            logger.debug("VRAM: Ollama unload skip: %s", exc)

        for path in ("/api/extra/abort", "/api/extra/unload"):
            try:
                resp = await client.post(f"{origin}{path}")
                if resp.status_code < 500:
                    logger.info("VRAM: Kobold extra %s -> %s", path, resp.status_code)
                    return
            except Exception as exc:
                logger.debug("VRAM: Kobold %s skip: %s", path, exc)

    logger.warning(
        "VRAM: could not unload home LLM at %s — free VRAM manually before SD if OOM",
        origin,
    )


async def _agent_post(path: str, *, timeout: float) -> dict[str, Any] | None:
    settings = get_settings()
    agent = (settings.home_vram_agent_url or "").strip().rstrip("/")
    if not agent:
        return None
    token = (settings.home_vram_agent_token or "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{agent}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {"ok": False, "raw": data}
    except Exception as exc:
        logger.warning("VRAM agent %s failed: %s", path, exc)
        return {"ok": False, "error": str(exc)}


async def prepare_for_sd(
    llm_base_url: str,
    model: str | None = None,
    *,
    sd_base_url: str | None = None,
) -> dict[str, Any]:
    """Before txt2img: ask home agent to free LLM + ensure WebUI, else soft unload."""
    settings = get_settings()
    result: dict[str, Any] = {"agent": None, "fallback": False}
    agent_url = (settings.home_vram_agent_url or "").strip()
    # Prefer agent whenever configured (works for cloud bot → Tailscale home).
    if agent_url:
        timeout = float(settings.home_vram_agent_timeout or 240)
        data = await _agent_post("/switch/sd", timeout=timeout)
        result["agent"] = data
        if data and data.get("ok"):
            logger.info("VRAM: agent switched to SD")
            return result
        logger.warning("VRAM: agent switch/sd not ok: %s", data)
    # Fallback: soft API unload when chatting via home LLM URL.
    if is_home_inference_url(llm_base_url) or agent_url:
        await release_home_llm_vram(llm_base_url, model)
        result["fallback"] = True
    _ = sd_base_url  # reserved for future health gate
    return result


async def restore_after_sd(llm_base_url: str, model: str | None = None) -> dict[str, Any]:
    """After txt2img: optionally bring Kobold back via agent."""
    settings = get_settings()
    result: dict[str, Any] = {"agent": None, "skipped": True}
    if not settings.home_vram_reload_llm:
        return result
    agent_url = (settings.home_vram_agent_url or "").strip()
    if not agent_url:
        return result
    # Only auto-reload when the guild/chat path is home LLM, or always if configured.
    if settings.home_vram_reload_llm_always or is_home_inference_url(llm_base_url):
        timeout = float(settings.home_vram_agent_timeout or 240)
        data = await _agent_post("/switch/llm", timeout=timeout)
        result = {"agent": data, "skipped": False}
        logger.info("VRAM: agent switch/llm -> %s", (data or {}).get("ok"))
    _ = model
    return result
