from __future__ import annotations

from core.prompt_builder import build_image_prompt
from core.schemas import LlmChatResult


def test_build_prefers_image_prompt() -> None:
    prompt = build_image_prompt(
        {"location": "classroom", "action": "sitting"},
        "yuuka",
        image_prompt="schale office, blushing, holding calculator",
    )
    assert "schale office, blushing, holding calculator" in prompt
    assert "classroom" not in prompt
    assert "hayase yuuka" in prompt.lower() or "1girl" in prompt.lower()
    assert "masterpiece" in prompt


def test_build_from_cg_scene() -> None:
    prompt = build_image_prompt(
        {
            "location": "millennium classroom",
            "time": "afternoon",
            "action": "holding calculator",
            "expression": "slight smile",
            "mood": "calm",
        },
        "yuuka",
    )
    assert "millennium classroom" in prompt
    assert "holding calculator" in prompt
    assert "solo, looking at viewer" in prompt


def test_llm_result_accepts_image_prompt() -> None:
    result = LlmChatResult.model_validate(
        {
            "reply": "（臉紅）才、才沒有！",
            "emotion": "flustered",
            "trigger_cg": True,
            "cg_tier": "none",
            "cg_scene": None,
            "image_prompt": "blushing, averted eyes",
        }
    )
    assert result.trigger_cg is True
    assert result.cg_tier == "normal"
    assert result.image_prompt == "blushing, averted eyes"
