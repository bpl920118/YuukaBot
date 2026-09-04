from __future__ import annotations

from clients.llm import LlmClient, _salvage_reply_field
from core.schemas import (
    OUTPUT_GUARDRAILS,
    build_runtime_system,
    is_soft_fallback,
    soft_fallback_reply,
)


def test_soft_fallback_is_warmer_and_detectable() -> None:
    old1 = "（敲了兩下計算機）……嗯？剛才那句我沒聽清楚。再說一次。"
    old2 = "（抬眼）預算審核還沒結束。有話就說，沒話我就繼續對帳了。"
    assert not is_soft_fallback(old1)
    assert not is_soft_fallback(old2)
    for i in range(3):
        assert is_soft_fallback(soft_fallback_reply(i))


def test_guardrails_and_prompt_warmth() -> None:
    assert "不要趕人走" in OUTPUT_GUARDRAILS
    with open("characters/yuuka-system-prompt.txt", encoding="utf-8") as f:
        card = f.read()
    sys = build_runtime_system(card)
    assert "嘴硬心軟" in sys
    assert "課金" in sys


def test_salvage_broken_json_reply() -> None:
    raw = '{"reply": "（抬眼）又想課金？先報金額。", "emotion": "angry",'
    salv = _salvage_reply_field(raw)
    assert salv is not None
    assert "課金" in salv["reply"]
    parsed = LlmClient().parse_result(raw + " bad")
    assert "課金" in parsed.reply
