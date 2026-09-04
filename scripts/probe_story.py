"""Probe story hooks + arc. Secrets stay in .env."""
from __future__ import annotations

import asyncio

from clients.llm import LlmClient
from core.character import load_character, load_system_prompt, match_lorebook, match_storyline
from core.schemas import build_runtime_system, is_soft_fallback


PROBES = ["你好", "我幫你對帳", "夏萊收據好亂", "做完一起吃飯吧"]


async def main() -> None:
    base = load_system_prompt("yuuka")
    character = load_character("yuuka")
    llm = LlmClient()
    history: list[dict[str, str]] = []
    recent: list[str] = []

    for text in PROBES:
        lore = match_lorebook(text, character, character_id="yuuka", limit=2)
        story = match_storyline(text, recent, character, character_id="yuuka")
        system = build_runtime_system(
            base, lore="\n\n".join(p for p in (story, lore) if p.strip())
        )
        messages = [*history, {"role": "user", "content": f"[老師1234] {text}"}]
        raw = await llm.chat(system=system, messages=messages)
        result = llm.parse_result(raw)
        print("=" * 40)
        print(f"USER: {text}")
        print(f"SOFT: {is_soft_fallback(result.reply)}")
        # show which beat id is active
        beat = "start"
        for line in story.splitlines():
            if "目前節拍" in line:
                beat = line
        print(f"BEAT: {beat}")
        print(f"REPLY: {result.reply}")
        if not is_soft_fallback(result.reply):
            history.append({"role": "user", "content": f"[老師1234] {text}"})
            history.append({"role": "assistant", "content": result.reply})
            recent.extend([text, result.reply])
            recent = recent[-8:]


if __name__ == "__main__":
    asyncio.run(main())
