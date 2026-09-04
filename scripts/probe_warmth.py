"""One-off local API warmth probe. Do not commit secrets."""
from __future__ import annotations

import asyncio
import json

from clients.llm import LlmClient
from core.character import load_character, load_system_prompt, match_lorebook
from core.schemas import build_runtime_system, is_soft_fallback


PROBES = [
    "su3cl3",
    "你好",
    "課金",
    "在嗎",
]


async def main() -> None:
    base = load_system_prompt("yuuka")
    character = load_character("yuuka")
    llm = LlmClient()
    history: list[dict[str, str]] = []

    for text in PROBES:
        lore = match_lorebook(text, character, character_id="yuuka", limit=2)
        system = build_runtime_system(base, lore=lore)
        messages = [
            *history,
            {"role": "user", "content": f"[老師1234] {text}"},
        ]
        raw = await llm.chat(system=system, messages=messages, last_reply=None)
        result = llm.parse_result(raw)
        soft = is_soft_fallback(result.reply)
        print("=" * 40)
        print(f"USER: {text}")
        print(f"SOFT_FALLBACK: {soft}")
        print(f"EMOTION: {result.emotion}")
        print(f"REPLY: {result.reply}")
        if not soft:
            history.append({"role": "user", "content": f"[老師1234] {text}"})
            history.append({"role": "assistant", "content": result.reply})


if __name__ == "__main__":
    asyncio.run(main())
