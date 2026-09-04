"""Quick offline checks for scoring rules (no Discord / API needed)."""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.scoring import AffectionScorer
from db.repository import Repository


async def main() -> None:
    repo = Repository()
    await repo.init()
    scorer = AffectionScorer(repo)
    guild_id = 999001

    # Reset-ish: use unique guild
    chat = await scorer.compute(
        guild_id=guild_id,
        user_id=1,
        user_text="優香午安",
        llm_delta=1,
        score_tags=[],
    )
    assert chat.total >= 1, chat

    work = await scorer.compute(
        guild_id=guild_id,
        user_id=1,
        user_text="幫我核銷這筆預算報帳",
        llm_delta=2,
        score_tags=["work"],
    )
    assert any(p["category"] == "work" for p in work.parts), work

    dislike = await scorer.compute(
        guild_id=guild_id,
        user_id=1,
        user_text="我又課金兩萬然後繼續吃泡麵",
        llm_delta=-4,
        score_tags=["dislike"],
    )
    assert dislike.total < 0, dislike

    sad = await scorer.compute(
        guild_id=guild_id + 1,
        user_id=1,
        user_text="……",
        llm_delta=0,
        score_tags=[],
        emotion="sad",
    )
    angry = await scorer.compute(
        guild_id=guild_id + 2,
        user_id=1,
        user_text="……",
        llm_delta=0,
        score_tags=[],
        emotion="angry",
    )
    sad_amt = next(p["amount"] for p in sad.parts if p["category"] == "emotion_sad")
    angry_amt = next(p["amount"] for p in angry.parts if p["category"] == "emotion_angry")
    assert sad_amt == -1, sad.parts
    assert angry_amt == -3, angry.parts
    assert angry_amt < sad_amt

    bday = await scorer.compute(
        guild_id=guild_id,
        user_id=1,
        user_text="生日快樂優香！",
        llm_delta=3,
        score_tags=["birthday"],
        today=date(2026, 3, 14),
    )
    assert any(p["category"] == "calendar" for p in bday.parts), bday

    print("scoring ok")
    print("chat", chat.total, chat.parts)
    print("work", work.total, work.parts)
    print("dislike", dislike.total, dislike.parts)
    print("sad", sad.total, sad.parts)
    print("angry", angry.total, angry.parts)
    print("birthday", bday.total, bday.parts)


if __name__ == "__main__":
    asyncio.run(main())
