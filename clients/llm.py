from __future__ import annotations

import json
import re
from typing import Any

import httpx

from config import get_settings
from core.schemas import LlmChatResult


class LlmClient:
    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.deepseek_api_key
        self.base_url = s.deepseek_base_url.rstrip("/")
        self.model = s.deepseek_model

    async def chat(self, *, system: str, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            # Offline stub for local wiring tests
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

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0.8,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/v1/chat/completions"
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    def parse_result(self, raw: str) -> LlmChatResult:
        try:
            return LlmChatResult.model_validate(self._extract_json(raw))
        except Exception:
            # One soft fallback: treat whole text as reply
            text = raw.strip() or "……稍微算錯一步。再說一次好嗎？"
            return LlmChatResult(reply=text[:500], emotion="neutral")

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
