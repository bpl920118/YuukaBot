"""Release / switch home-PC text LLM VRAM before SD WebUI on the same GPU."""

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


def agent_configured() -> bool:
    return bool((get_settings().home_vram_agent_url or "").strip())


async def release_home_llm_vram(base_url: str, model: str | None = None) -> None:
    """Best-effort unload so A1111/Forge can use the same 8GB card."""
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


async def _agent_request(
    method: str,
    path: str,
    *,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    agent = (settings.home_vram_agent_url or "").strip().rstrip("/")
    if not agent:
        return None
    token = (settings.home_vram_agent_token or "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{agent}{path}"
    to = float(timeout if timeout is not None else settings.home_vram_agent_timeout or 240)
    try:
        async with httpx.AsyncClient(timeout=to) as client:
            resp = await client.request(method, url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {"ok": False, "raw": data}
    except Exception as exc:
        logger.warning("VRAM agent %s %s failed: %s", method, path, exc)
        return {"ok": False, "error": str(exc)}


async def agent_status() -> dict[str, Any] | None:
    if not agent_configured():
        return None
    return await _agent_request("GET", "/status", timeout=15.0)


async def switch_to_sd() -> dict[str, Any]:
    if not agent_configured():
        return {"ok": False, "error": "HOME_VRAM_AGENT_URL 未設定"}
    return (await _agent_request("POST", "/switch/sd")) or {
        "ok": False,
        "error": "no response",
    }


async def switch_to_llm() -> dict[str, Any]:
    if not agent_configured():
        return {"ok": False, "error": "HOME_VRAM_AGENT_URL 未設定"}
    return (await _agent_request("POST", "/switch/llm")) or {
        "ok": False,
        "error": "no response",
    }


async def prepare_for_sd(
    llm_base_url: str,
    model: str | None = None,
    *,
    sd_base_url: str | None = None,
) -> dict[str, Any]:
    """Before txt2img: agent → SD, else soft unload."""
    result: dict[str, Any] = {"agent": None, "fallback": False}
    if agent_configured():
        data = await switch_to_sd()
        result["agent"] = data
        if data.get("ok"):
            logger.info("VRAM: switched to SD")
            return result
        logger.warning("VRAM: switch/sd not ok: %s", data)
    if is_home_inference_url(llm_base_url) or agent_configured():
        await release_home_llm_vram(llm_base_url, model)
        result["fallback"] = True
    _ = sd_base_url
    return result


async def restore_after_sd(llm_base_url: str, model: str | None = None) -> dict[str, Any]:
    """After txt2img: switch back to text LLM when enabled."""
    settings = get_settings()
    result: dict[str, Any] = {"agent": None, "skipped": True}
    if not settings.home_vram_reload_llm or not agent_configured():
        return result
    data = await switch_to_llm()
    result = {"agent": data, "skipped": False}
    logger.info("VRAM: switch/llm -> %s", (data or {}).get("ok"))
    _ = llm_base_url, model
    return result


async def ensure_home_llm_for_chat(llm_base_url: str) -> dict[str, Any] | None:
    """Home-LLM chat: if Kobold is down, auto switch back from SD."""
    if not agent_configured() or not is_home_inference_url(llm_base_url):
        return None
    if not get_settings().home_vram_ensure_llm_on_chat:
        return None
    st = await agent_status()
    if not isinstance(st, dict) or st.get("error"):
        return st
    if st.get("kobold_up"):
        return {"ok": True, "skipped": True, "status": st}
    logger.info("VRAM: home chat but kobold down → switch/llm")
    data = await switch_to_llm()
    return {
        "ok": bool((data or {}).get("ok")),
        "switched": True,
        "agent": data,
        "status": st,
    }
