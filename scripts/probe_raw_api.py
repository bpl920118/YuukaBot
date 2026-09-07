"""Inspect raw DeepSeek chat completion payload."""
from __future__ import annotations

import asyncio
import json
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

from config import get_settings


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    s = get_settings()
    url = s.deepseek_base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": s.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    '只輸出 JSON: {"reply":"短句","emotion":"neutral",'
                    '"trigger_cg":false,"cg_tier":"none","cg_scene":null,"image_prompt":null}'
                ),
            },
            {"role": "user", "content": "[老師0661] 你好"},
        ],
        "max_tokens": 768,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 1.0,
        "top_p": 0.9,
    }
    headers = {
        "Authorization": f"Bearer {s.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        print("status", resp.status_code)
        data = resp.json()
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])


if __name__ == "__main__":
    asyncio.run(main())
