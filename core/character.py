from __future__ import annotations

from typing import Any

import yaml

from config import get_settings


def load_character(character_id: str = "yuuka") -> dict[str, Any]:
    path = get_settings().character_dir / f"{character_id}.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_system_prompt(character_id: str = "yuuka") -> str:
    settings = get_settings()
    prompt_path = settings.character_dir / f"{character_id}-system-prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    data = load_character(character_id)
    return data.get("system_prompt", f"你正在扮演 {character_id}。")
