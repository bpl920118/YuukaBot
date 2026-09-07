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


def load_system_prompt(character_id: str = "yuuka", *, home_mode: bool = False) -> str:
    """Load always-on character card text (tavern-style sections in .txt).

    home_mode prefers ``{id}-system-prompt.local.txt`` (ST-tuned short card for 7B).
    """
    settings = get_settings()
    if home_mode:
        local_path = settings.character_dir / f"{character_id}-system-prompt.local.txt"
        if local_path.exists():
            return local_path.read_text(encoding="utf-8").strip()
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
    max_chars: int | None = None,
) -> str:
    """
    SillyTavern-style lorebook: inject only entries whose keys appear in text.
    Pass recent turns joined into ``text`` for scan-depth behaviour.
    """
    data = character if character is not None else load_character(character_id)
    entries = data.get("lorebook") or []
    if not isinstance(entries, list) or not text:
        return ""

    haystack = text.casefold()
    hit: list[str] = []
    budget = max_chars if max_chars is not None else None
    used = 0
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
            if budget is not None and used + len(block) > budget and hit:
                break
            hit.append(block)
            used += len(block) + 1
            if len(hit) >= max(1, limit):
                break

    if not hit:
        return ""
    return "【相關回憶——對方已提到，可自然接上；勿宣讀本標籤】\n" + "\n".join(hit)


def resolve_storyline_phase(
    text: str,
    recent_texts: list[str] | None = None,
    character: dict[str, Any] | None = None,
    *,
    character_id: str = "yuuka",
) -> dict[str, Any] | None:
    """Return the winning storyline phase dict (or None)."""
    data = character if character is not None else load_character(character_id)
    story = data.get("storyline") or {}
    if not isinstance(story, dict):
        return None
    phases = story.get("phases") or []
    if not isinstance(phases, list) or not phases:
        return None

    current = (text or "").casefold()
    history_blob = "\n".join(t for t in (recent_texts or []) if t).casefold()

    chosen: dict[str, Any] | None = None
    best_score = -1
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        content = (phase.get("content") or "").strip()
        if not content:
            continue
        keys = phase.get("keys") or []
        if not isinstance(keys, list) or not keys:
            if chosen is None:
                chosen = phase
                best_score = 0
            continue
        cur_hits = sum(1 for k in keys if k and str(k).casefold() in current)
        hist_hits = sum(1 for k in keys if k and str(k).casefold() in history_blob)
        score = cur_hits * 3 + hist_hits
        if score > best_score:
            best_score = score
            chosen = phase
        elif score == best_score and score > 0:
            chosen = phase
    return chosen


def match_storyline(
    text: str,
    recent_texts: list[str] | None = None,
    character: dict[str, Any] | None = None,
    *,
    character_id: str = "yuuka",
) -> str:
    """
    Inject a short ongoing arc. Phase advances when keys appear in
    the current message or recent turns (latest matching phase wins).
    """
    data = character if character is not None else load_character(character_id)
    story = data.get("storyline") or {}
    if not isinstance(story, dict):
        return ""

    premise = " ".join(str(story.get("premise") or "").split()).strip()
    title = str(story.get("title") or "").strip()
    phases = story.get("phases") or []
    if not premise and not phases:
        return ""

    chosen = resolve_storyline_phase(
        text, recent_texts, data, character_id=character_id
    )

    lines = ["【進行中的小主線——可輕推進一小步，勿一次講完、勿宣讀本標籤】"]
    if title:
        lines.append(f"標題：{title}")
    if premise:
        lines.append(f"前提：{premise}")
    if chosen is not None:
        beat = " ".join(str(chosen.get("content") or "").split()).strip()
        phase_id = str(chosen.get("id") or "").strip()
        label = f"目前節拍（{phase_id}）" if phase_id else "目前節拍"
        if beat:
            lines.append(f"{label}：{beat}")
    return "\n".join(lines)
