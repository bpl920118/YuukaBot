from __future__ import annotations

import json
import re
from typing import Any

import httpx

from config import get_settings
from core.llm_options import resolve_depth, resolve_model
from core.schemas import LlmChatResult


_FALLBACK_REPLY = "……計算機好像跳了一下。再說一次好嗎？"


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
    ) -> str:
        if not self.api_key:
            return json.dumps(
                {
                    "reply": "老師……API 金鑰還沒設定，但我先在這裡應答。請把帳目補上。",
                    "emotion": "neutral",
                    "trigger_cg": False,
                    "cg_tier": "none",
                    "cg_scene": None,
                },
                ensure_ascii=False,
            )

        use_model = resolve_model(model, self.model)
        use_depth = resolve_depth(depth, self.depth)

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0.9,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
        }
        if use_depth == "off":
            payload["thinking"] = {"type": "disabled"}
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
        for _ in range(2):
            last_raw = await self._post_once(url, headers, payload, timeout)
            if not (last_raw or "").strip():
                continue
            try:
                LlmChatResult.model_validate(self._extract_json(last_raw))
                return last_raw
            except Exception:
                continue
        return last_raw or ""

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
        if isinstance(content, str):
            return content
        return ""

    def parse_result(self, raw: str) -> LlmChatResult:
        try:
            return LlmChatResult.model_validate(self._extract_json(raw))
        except Exception:
            text = (raw or "").strip()
            if text and not text.startswith("{"):
                return LlmChatResult(reply=text[:500], emotion="neutral")
            return LlmChatResult(reply=_FALLBACK_REPLY, emotion="flustered")

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
