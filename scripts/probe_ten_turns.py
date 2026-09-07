"""Local 10-turn dialogue probe (not for production)."""
from __future__ import annotations

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

from clients.llm import LlmClient, is_soft_fallback
from core.character import load_character, load_system_prompt, match_lorebook, match_storyline
from core.schemas import build_runtime_system

TURNS = [
    "你好",
    "我來陪你對帳",
    "這三張收據是夏萊的咖啡跟文具",
    "那筆雜支其實是我亂寫的…對不起",
    "你眼睛很酸吧，休息一下？",
    "那我去泡茶，你先把計算機放下",
    "對完這頁我們去吃飯？",
    "想吃拉麵，我請客",
    "你最近有沒有偷偷幫誰擦屁股啊",
    "媽媽",
]


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    llm = LlmClient()
    char = load_character("yuuka")
    base = load_system_prompt("yuuka")
    hist: list[dict[str, str]] = []
    recent: list[str] = []
    last: str | None = None
    soft_n = 0

    for i, text in enumerate(TURNS, 1):
        lore = match_lorebook(text, char, character_id="yuuka", limit=2)
        story = match_storyline(text, recent, char, character_id="yuuka")
        lore_blocks = "\n\n".join(p for p in (story, lore) if p and p.strip())
        system = build_runtime_system(base, lore=lore_blocks)
        msgs = list(hist) + [{"role": "user", "content": f"[老師0661] {text}"}]
        raw = await llm.chat(
            system=system,
            messages=msgs,
            depth="off",
            last_reply=last,
        )
        r = llm.parse_result(raw)
        soft = is_soft_fallback(r.reply)
        if soft:
            soft_n += 1
        tag = " / SOFT" if soft else ""
        print(f"#{i} 老師：{text}")
        print(f"   優香（{r.emotion}{tag} len={len(r.reply)}）：{r.reply}")
        print()
        if soft:
            continue
        hist.append({"role": "user", "content": f"[老師0661] {text}"})
        hist.append({"role": "assistant", "content": r.reply})
        recent.append(text)
        recent.append(r.reply)
        recent = recent[-8:]
        last = r.reply
        if len(hist) > 12:
            hist = hist[-12:]

    print(f"=== done soft={soft_n}/10 ===")


if __name__ == "__main__":
    asyncio.run(main())
