from __future__ import annotations

from core.character import load_character

QUALITY_TAGS = "masterpiece, best quality, very aesthetic, absurdres"


def _clean_tag_chunk(value: str | None) -> str:
    return (value or "").strip().strip(",").strip()


def build_image_prompt(
    scene: dict | None = None,
    character_id: str = "yuuka",
    *,
    image_prompt: str | None = None,
) -> str:
    """
    Build Kivotos XL / Animagine-style tag prompt.

    Priority:
    1) Freeform image_prompt from LLM (plot keywords)
    2) Structured cg_scene fields
    Always prepend character style_anchor from yaml; append quality tags.
    """
    data = load_character(character_id)
    # Keep identity tags; drop props that steal the beat (calculator on every CG).
    raw_anchor = _clean_tag_chunk(data.get("style_anchor") or "")
    drop = {"calculator", "holding calculator"}
    anchor = ", ".join(
        t.strip()
        for t in raw_anchor.split(",")
        if t.strip() and t.strip().casefold() not in drop
    )

    freeform = _clean_tag_chunk(image_prompt)
    scene = scene or {}

    if freeform:
        body_parts = [freeform]
    else:

        def tag(key: str) -> str:
            return _clean_tag_chunk(str(scene.get(key) or ""))

        body_parts = [
            tag("location"),
            tag("time"),
            tag("action"),
            tag("expression"),
            tag("mood"),
        ]

    parts = [anchor, *body_parts]
    # Only force viewer gaze when the beat has no stronger action tags.
    blob = " ".join(body_parts).casefold()
    if not any(k in blob for k in ("holding", "receiving", "hand", "cup", "latte", "coffee")):
        parts.append("solo, looking at viewer")
    else:
        parts.append("solo")
    parts.append(QUALITY_TAGS)
    return ", ".join(p for p in parts if p)


def heuristic_image_tags(reply: str, emotion: str | None = None) -> str | None:
    """Cheap Chinese→tag fallback so CG matches the latest reply props."""
    text = (reply or "").strip()
    if not text:
        return None
    emo = (emotion or "neutral").strip().lower()
    expr = {
        "flustered": "blushing, embarrassed, averted eyes",
        "shy": "blushing, shy, looking away",
        "angry": "angry, frowning, furrowed brows",
        "sad": "sad, downturned eyes",
        "happy": "slight smile, soft expression",
        "tired": "tired, weary eyes",
        "proud": "smug, slight smile",
    }.get(emo, "soft expression")

    rules: list[tuple[tuple[str, ...], str]] = (
        (
            ("拿鐵", "咖啡", "紙杯", "熱拿鐵", "冰拿鐵", "飲料", "熱的就熱的"),
            "receiving paper cup, hot latte, desk, blushing, fingertips brushing, embarrassed",
        ),
        (
            ("泡麵", "食材", "便當"),
            "holding grocery bag, desk, mild scolding expression",
        ),
        (
            ("對帳", "審核", "表單", "核銷", "收據", "計算機"),
            "holding calculator, paperwork on desk, looking at documents",
        ),
        (
            ("茶", "倒茶", "熱茶"),
            "holding teacup, office desk, soft indoor light",
        ),
    )
    for keys, tags in rules:
        if any(k in text for k in keys):
            return f"{tags}, {expr}"
    return None



# Back-compat alias
def build_flux_prompt(
    scene: dict | None = None,
    character_id: str = "yuuka",
    *,
    image_prompt: str | None = None,
) -> str:
    return build_image_prompt(scene, character_id, image_prompt=image_prompt)
