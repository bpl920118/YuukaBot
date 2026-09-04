from __future__ import annotations

from core.character import load_character

QUALITY_TAGS = "masterpiece, best quality, very aesthetic, absurdres"


def build_image_prompt(scene: dict, character_id: str = "yuuka") -> str:
    """Kivotos XL / Animagine-style tag prompt."""
    data = load_character(character_id)
    anchor = (data.get("style_anchor") or "").strip().rstrip(",")

    def tag(key: str) -> str:
        value = (scene.get(key) or "").strip()
        return value

    parts = [
        anchor,
        tag("location"),
        tag("time"),
        tag("action"),
        tag("expression"),
        tag("mood"),
        "solo, looking at viewer",
        QUALITY_TAGS,
    ]
    return ", ".join(p for p in parts if p)


# Back-compat alias
def build_flux_prompt(scene: dict, character_id: str = "yuuka") -> str:
    return build_image_prompt(scene, character_id)
