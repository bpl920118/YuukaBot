from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from config import get_settings
from core.llm_options import resolve_depth, resolve_model
from core.schemas import LlmChatResult, is_soft_fallback, soft_fallback_reply


logger = logging.getLogger(__name__)

_PARSE_FALLBACK = "……計算機好像跳了一下。再說一次好嗎？"
_RETRY_NUDGE = (
    "[系統] 上一則輸出無效。請重新只輸出合法 JSON；"
    "reply 必須是繁體中文、至少兩個字、且不得與上一則對白相同。"
)


def _normalize_reply(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def is_near_duplicate(a: str, b: str) -> bool:
    """True when replies are identical or one is a near-copy of the other."""
    na, nb = _normalize_reply(a), _normalize_reply(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) < 12:
        return False
    if shorter in longer and abs(len(na) - len(nb)) <= max(24, len(shorter) // 3):
        return True
    return False


def _salvage_reply_field(raw: str) -> dict[str, Any] | None:
    """Pull a usable reply out of near-JSON when full parse fails."""
    text = (raw or "").strip()
    if not text:
        return None
    match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if not match:
        return None
    try:
        reply = json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        reply = match.group(1)
    reply = (reply or "").strip()
    if len(reply) < 2:
        return None
    return {
        "reply": reply[:500],
        "emotion": "neutral",
        "trigger_cg": False,
        "cg_tier": "none",
        "cg_scene": None,
        "image_prompt": None,
    }


class LlmClient:
    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.deepseek_api_key
        self.base_url = s.deepseek_base_url.rstrip("/")
        self.model = s.deepseek_model
        self.depth = s.deepseek_depth

    async def chat(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        depth: str | None = None,
        last_reply: str | None = None,
    ) -> str:
        if not self.api_key:
            return json.dumps(
                {
                    "reply": "老師……API 金鑰還沒設定，但我先在這裡應答。請把帳目補上。",
                    "emotion": "neutral",
                    "trigger_cg": False,
                    "cg_tier": "none",
                    "cg_scene": None,
                    "image_prompt": None,
                },
                ensure_ascii=False,
            )

        use_model = resolve_model(model, self.model)
        use_depth = resolve_depth(depth, self.depth)
        settings = get_settings()

        # Soft-fallback lines in memory must not trigger near-duplicate rejection.
        effective_last = (
            None
            if (last_reply and is_soft_fallback(last_reply))
            else last_reply
        )

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        }
        # Sampling only applies when thinking is off (Flash casual chat).
        if use_depth == "off":
            payload["thinking"] = {"type": "disabled"}
            payload["temperature"] = settings.llm_temperature
            payload["top_p"] = settings.llm_top_p
        else:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = use_depth  # high | max

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/v1/chat/completions"
        timeout = 180.0 if use_depth != "off" else 90.0

        last_raw = ""
        working_messages = list(payload["messages"])
        for attempt in range(3):
            attempt_payload = {**payload, "messages": working_messages}
            try:
                last_raw = await self._post_once(url, headers, attempt_payload, timeout)
            except Exception as exc:
                logger.warning("LLM HTTP attempt %s failed: %s", attempt + 1, exc)
                working_messages = [
                    *payload["messages"],
                    {"role": "user", "content": _RETRY_NUDGE},
                ]
                continue
            if not (last_raw or "").strip():
                logger.warning("LLM empty content on attempt %s", attempt + 1)
                working_messages = [
                    *payload["messages"],
                    {"role": "user", "content": _RETRY_NUDGE},
                ]
                continue
            try:
                data = self._extract_json(last_raw)
                result = LlmChatResult.model_validate(data)
                if effective_last and is_near_duplicate(result.reply, effective_last):
                    raise ValueError("near-duplicate reply")
                return json.dumps(result.model_dump(), ensure_ascii=False)
            except Exception as exc:
                salvaged = _salvage_reply_field(last_raw)
                if salvaged:
                    try:
                        result = LlmChatResult.model_validate(salvaged)
                        if not (
                            effective_last
                            and is_near_duplicate(result.reply, effective_last)
                        ):
                            logger.info("LLM salvaged reply field on attempt %s", attempt + 1)
                            return json.dumps(result.model_dump(), ensure_ascii=False)
                    except Exception:
                        pass
                logger.warning("LLM parse attempt %s failed: %s", attempt + 1, exc)
                working_messages = [
                    *payload["messages"],
                    {"role": "assistant", "content": last_raw[:800]},
                    {"role": "user", "content": _RETRY_NUDGE},
                ]
                continue

        # Local soft fallback — avoid hammering API or looping "計算機跳了".
        logger.error("LLM soft-fallback after retries; last_raw=%r", (last_raw or "")[:200])
        fallback = soft_fallback_reply(hash(last_raw or last_reply or "") & 0xFFFF)
        return json.dumps(
            {
                "reply": fallback,
                "emotion": "flustered",
                "trigger_cg": False,
                "cg_tier": "none",
                "cg_scene": None,
                "image_prompt": None,
            },
            ensure_ascii=False,
        )

    async def _post_once(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> str:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        message = data["choices"][0]["message"]
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        # Some gateways return content as a list of text parts.
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, str):
                    chunks.append(part)
                elif isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                    if isinstance(text, str):
                        chunks.append(text)
            joined = "".join(chunks).strip()
            if joined:
                return joined
        return ""

    def parse_result(self, raw: str) -> LlmChatResult:
        try:
            return LlmChatResult.model_validate(self._extract_json(raw))
        except Exception:
            salvaged = _salvage_reply_field(raw)
            if salvaged:
                try:
                    return LlmChatResult.model_validate(salvaged)
                except Exception:
                    pass
            text = (raw or "").strip()
            if text and not text.startswith("{"):
                return LlmChatResult(reply=text[:500], emotion="neutral")
            return LlmChatResult(reply=_PARSE_FALLBACK, emotion="flustered")

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))
