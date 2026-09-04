from __future__ import annotations

from typing import Any

import yaml

from config import get_settings


def load_character(character_id: str = "yuuka") -> dict[str, Any]:
    path = get_settings().character_dir / f"{character_id}.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def load_system_prompt(character_id: str = "yuuka") -> str:
    """Load always-on character card text (tavern-style sections in .txt)."""
    settings = get_settings()
    prompt_path = settings.character_dir / f"{character_id}-system-prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8").strip()
    data = load_character(character_id)
    card = data.get("card") or {}
    if isinstance(card, dict) and card.get("description"):
        return str(card["description"]).strip()
    return str(data.get("system_prompt") or f"你正在扮演 {character_id}。").strip()


def match_lorebook(
    text: str,
    character: dict[str, Any] | None = None,
    *,
    character_id: str = "yuuka",
    limit: int = 2,
) -> str:
    """
    SillyTavern-style lorebook: inject only entries whose keys appear in text.
    Keeps the always-on prompt lean for DeepSeek Flash.
    """
    data = character if character is not None else load_character(character_id)
    entries = data.get("lorebook") or []
    if not isinstance(entries, list) or not text:
        return ""

    haystack = text.casefold()
    hit: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        keys = entry.get("keys") or []
        content = (entry.get("content") or "").strip()
        if not content or not isinstance(keys, list):
            continue
        if any(str(k).casefold() in haystack for k in keys if k):
            name = (entry.get("name") or "").strip()
            block = f"- {name}：{content}" if name else f"- {content}"
            hit.append(block)
            if len(hit) >= max(1, limit):
                break

    if not hit:
        return ""
    return "【相關回憶——對方已提到，可自然接上；勿宣讀本標籤】\n" + "\n".join(hit)
