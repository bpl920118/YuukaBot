from __future__ import annotations

from core.scoring import load_character


def build_flux_prompt(scene: dict, character_id: str = "yuuka") -> str:
    data = load_character(character_id)
    anchor = (data.get("style_anchor") or "").strip()
    parts = [
        anchor,
        f"location: {scene.get('location', '')}",
        f"time of day: {scene.get('time', '')}",
        f"action: {scene.get('action', '')}",
        f"facial expression: {scene.get('expression', '')}",
        f"mood atmosphere: {scene.get('mood', '')}",
        "single character focus, high quality anime still, no watermark, no text overlay",
    ]
    return ", ".join(p for p in parts if p)
