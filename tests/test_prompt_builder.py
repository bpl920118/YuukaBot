from __future__ import annotations

from core.prompt_builder import build_image_prompt, heuristic_image_tags
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
            "action": "sitting at desk",
            "expression": "slight smile",
            "mood": "calm",
        },
        "yuuka",
    )
    assert "millennium classroom" in prompt
    assert "sitting at desk" in prompt
    assert "solo, looking at viewer" in prompt


def test_heuristic_matches_latte_beat() -> None:
    tags = heuristic_image_tags(
        "（接過紙杯，指尖不小心碰到，立刻縮回手）……熱的就熱的。謝謝老師……這筆熱拿鐵我先記行政開銷。",
        "flustered",
    )
    assert tags is not None
    assert "latte" in tags or "cup" in tags
    assert "calculator" not in tags
    prompt = build_image_prompt(None, "yuuka", image_prompt=tags)
    assert "latte" in prompt or "cup" in prompt
    # Identity anchor should not force calculator into every CG.
    assert "calculator" not in prompt


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
