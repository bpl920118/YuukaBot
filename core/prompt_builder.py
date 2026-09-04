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
    anchor = _clean_tag_chunk(data.get("style_anchor") or "")

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

    parts = [
        anchor,
        *body_parts,
        "solo, looking at viewer",
        QUALITY_TAGS,
    ]
    return ", ".join(p for p in parts if p)


# Back-compat alias
def build_flux_prompt(
    scene: dict | None = None,
    character_id: str = "yuuka",
    *,
    image_prompt: str | None = None,
) -> str:
    return build_image_prompt(scene, character_id, image_prompt=image_prompt)
