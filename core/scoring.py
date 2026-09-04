from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from config import get_settings
from db.repository import Repository, today_event_key


@dataclass
class ScoreBreakdown:
    total: int = 0
    parts: list[dict[str, Any]] = field(default_factory=list)

    def add(self, category: str, amount: int, reason: str, event_key: str | None = None) -> None:
        if amount == 0:
            return
        self.parts.append(
            {
                "category": category,
                "amount": amount,
                "reason": reason,
                "event_key": event_key,
            }
        )
        self.total += amount


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


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.casefold()
    return any(k.casefold() in lower for k in keywords if k)


def _mmdd(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.month:02d}-{d.day:02d}"


class AffectionScorer:
    """
    Hybrid scoring:
    1) Rule layer: chat / work / dislike keywords + calendar + emotion mood
    2) LLM layer: model-suggested affection_change + score_tags
    3) Caps, once-per-year festival keys, final clamp
    """

    def __init__(self, repo: Repository, character_id: str = "yuuka") -> None:
        self.repo = repo
        self.character_id = character_id
        self.character = load_character(character_id)
        self.scoring: dict[str, Any] = self.character.get("scoring", {})

    async def compute(
        self,
        *,
        guild_id: int,
        user_id: int,
        user_text: str,
        llm_delta: int,
        score_tags: list[str] | None = None,
        emotion: str | None = None,
        today: date | None = None,
    ) -> ScoreBreakdown:
        today = today or date.today()
        tags = {t.lower() for t in (score_tags or [])}
        cfg = self.scoring
        breakdown = ScoreBreakdown()
        settings = get_settings()

        # --- chat ---
        chat_cfg = cfg.get("chat", {})
        min_chars = int(chat_cfg.get("meaningful_min_chars", 2))
        if len(user_text.strip()) >= min_chars:
            chat_delta = int(chat_cfg.get("base", 1))
            used = await self.repo.sum_score_today(guild_id, "chat", self.character_id)
            cap = int(chat_cfg.get("daily_cap", 8))
            room = max(0, cap - used)
            apply = min(chat_delta, room)
            breakdown.add("chat", apply, "實質聊天互動")

        # --- work ---
        work_cfg = cfg.get("work", {})
        work_hit = "work" in tags or _contains_any(user_text, work_cfg.get("keywords", []))
        if work_hit:
            work_delta = int(work_cfg.get("delta", 3))
            used = await self.repo.sum_score_today(guild_id, "work", self.character_id)
            cap = int(work_cfg.get("daily_cap", 12))
            room = max(0, cap - used)
            apply = min(work_delta, room) if work_delta > 0 else work_delta
            breakdown.add("work", apply, "工作／會計相關互動")

        # --- dislike ---
        dislike_cfg = cfg.get("dislike", {})
        dislike_hit = "dislike" in tags or _contains_any(
            user_text, dislike_cfg.get("keywords", [])
        )
        if dislike_hit:
            dislike_delta = int(dislike_cfg.get("delta", -5))
            used = await self.repo.sum_score_today(guild_id, "dislike", self.character_id)
            # used is negative sum; floor is e.g. -20 meaning most negative allowed today
            floor = int(dislike_cfg.get("daily_floor", -20))
            # how much more we can still deduct today
            room = floor - used  # e.g. -20 - (-8) = -12 remaining capacity
            if dislike_delta < 0:
                apply = max(dislike_delta, room) if room < 0 else 0
            else:
                apply = 0
            breakdown.add("dislike", apply, "觸及優香不喜歡的事")

        # --- emotion mood penalty (sad lighter than angry) ---
        emo = (emotion or "").strip().lower()
        emo_cfg_root = cfg.get("emotion", {}) or {}
        if emo in {"sad", "angry"} and isinstance(emo_cfg_root, dict):
            emo_cfg = emo_cfg_root.get(emo) or {}
            emo_delta = int(emo_cfg.get("delta", -1 if emo == "sad" else -3))
            floor = int(emo_cfg.get("daily_floor", -8 if emo == "sad" else -15))
            category = f"emotion_{emo}"
            used = await self.repo.sum_score_today(guild_id, category, self.character_id)
            room = floor - used
            if emo_delta < 0:
                apply = max(emo_delta, room) if room < 0 else 0
            else:
                apply = 0
            reason = (
                "優香不開心（sad）"
                if emo == "sad"
                else "優香生氣（angry）"
            )
            breakdown.add(category, apply, reason)

        # --- calendar: birthday + festivals ---
        cal = cfg.get("calendar", {})
        mmdd = _mmdd(today)

        birthday = cal.get("birthday") or {}
        bday = birthday.get("date") or self.character.get("birthday")
        if bday == mmdd and (
            "birthday" in tags
            or _contains_any(user_text, birthday.get("keywords", ["生日"]))
        ):
            key = today_event_key(f"birthday:{self.character_id}", today)
            if not await self.repo.has_event_key(guild_id, key):
                breakdown.add(
                    "calendar",
                    int(birthday.get("delta", 15)),
                    "優香生日祝福／相關行動",
                    event_key=key,
                )

        for fest in cal.get("festivals", []):
            dates = fest.get("dates") or []
            if mmdd not in dates:
                continue
            if not (
                fest.get("id", "") in tags
                or "festival" in tags
                or _contains_any(user_text, fest.get("keywords", []))
            ):
                continue
            key = today_event_key(f"fest:{fest.get('id')}", today)
            if fest.get("once_per_year", True) and await self.repo.has_event_key(guild_id, key):
                continue
            breakdown.add(
                "calendar",
                int(fest.get("delta", 5)),
                f"節日行動：{fest.get('id')}",
                event_key=key,
            )

        # --- LLM suggested delta ---
        llm_weight = float(cfg.get("llm_weight", 1.0))
        clamped_llm = max(
            -settings.max_affection_delta,
            min(settings.max_affection_delta, int(llm_delta)),
        )
        llm_apply = int(round(clamped_llm * llm_weight))
        if llm_apply:
            breakdown.add("llm", llm_apply, "模型依對話語境建議")

        # --- final clamp (birthday/calendar already inside; soft bound whole turn) ---
        lo, hi = cfg.get("final_clamp", [-15, 20])
        # Allow birthday to exceed soft clamp slightly: if any calendar part, widen hi
        if any(p["category"] == "calendar" for p in breakdown.parts):
            hi = max(hi, 25)
        breakdown.total = max(int(lo), min(int(hi), breakdown.total))
        return breakdown

    async def apply(
        self,
        *,
        guild_id: int,
        user_id: int,
        current_affection: int,
        breakdown: ScoreBreakdown,
        emotion: str,
    ) -> int:
        new_value = max(0, min(100, current_affection + breakdown.total))
        for part in breakdown.parts:
            if part["amount"] == 0:
                continue
            await self.repo.add_score_event(
                guild_id=guild_id,
                category=part["category"],
                amount=part["amount"],
                reason=part["reason"],
                user_id=user_id,
                event_key=part.get("event_key"),
                character_id=self.character_id,
            )
        await self.repo.update_bond(
            guild_id,
            affection=new_value,
            emotion=emotion,
            character_id=self.character_id,
        )
        return new_value


def crossed_milestones(old: int, new: int, milestones: dict[Any, Any]) -> list[int]:
    keys = sorted(int(k) for k in milestones.keys())
    return [m for m in keys if old < m <= new]
