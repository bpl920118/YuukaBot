from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
import random

import yaml

from config import get_settings

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


Slot = str  # morning | afternoon | evening | night
_TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class WorldMoment:
    slot: Slot
    location_id: str
    location_name: str
    location_vibe: str
    action: str
    observance_id: str | None = None
    observance_tone: str = ""
    storyline_hint: str | None = None
    quiet: bool = False

    def prompt_block(self) -> str:
        if self.quiet:
            return "【日常世界】目前為安靜時段，不主動推播。"
        lines = [
            "【日常世界——主動動態／場景錨點；勿宣讀本標籤】",
            f"時段：{self.slot}",
            f"地點：{self.location_name}（{self.location_id}）",
        ]
        if self.location_vibe:
            lines.append(f"氛圍：{self.location_vibe}")
        lines.append(f"行動：{self.action}")
        if self.observance_id and self.observance_tone:
            tone = " ".join(self.observance_tone.split())
            lines.append(f"節日修飾（{self.observance_id}）：{tone}")
        if self.storyline_hint:
            lines.append(f"主線偏向：{self.storyline_hint}")
        return "\n".join(lines)


def _world_path(character_id: str) -> Path:
    return get_settings().character_dir / f"{character_id}-world.yaml"


@lru_cache
def load_world(character_id: str = "yuuka") -> dict[str, Any]:
    path = _world_path(character_id)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def clear_world_cache() -> None:
    load_world.cache_clear()


def world_tz(world: dict[str, Any] | None = None):
    data = world if world is not None else load_world()
    name = str(data.get("timezone") or "Asia/Taipei")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    # Windows without tzdata: fixed UTC+8 for Taipei default.
    if "Taipei" in name or name.endswith("+08:00") or name == "UTC+8":
        return _TAIPEI
    return _TAIPEI


def slot_for_hour(hour: int) -> Slot:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def in_quiet_hours(hour: int, world: dict[str, Any] | None = None) -> bool:
    data = world if world is not None else load_world()
    q = data.get("quiet_hours") or [0, 8]
    if not isinstance(q, (list, tuple)) or len(q) < 2:
        return False
    start, end = int(q[0]), int(q[1])
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _parse_window(obs: dict[str, Any], year: int) -> tuple[date, date] | None:
    win = obs.get("window") or {}
    if not isinstance(win, dict):
        return None
    try:
        month = int(win["month"])
        day = int(win["day"])
        before = int(win.get("days_before") or 0)
        after = int(win.get("days_after") or 0)
        center = date(year, month, day)
    except Exception:
        return None
    return center - timedelta(days=before), center + timedelta(days=after)


def active_observance(
    when: datetime | date,
    world: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    data = world if world is not None else load_world()
    entries = data.get("observances") or []
    if not isinstance(entries, list):
        return None
    d = when.date() if isinstance(when, datetime) else when
    hits: list[dict[str, Any]] = []
    for obs in entries:
        if not isinstance(obs, dict):
            continue
        span = _parse_window(obs, d.year)
        if span is None:
            continue
        start, end = span
        if start <= d <= end:
            hits.append(obs)
        elif d.month == 1:
            span_prev = _parse_window(obs, d.year - 1)
            if span_prev and span_prev[0] <= d <= span_prev[1]:
                hits.append(obs)
    if not hits:
        return None
    hits.sort(key=lambda o: int(o.get("priority") or 0), reverse=True)
    return hits[0]


def _loc_map(world: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for loc in world.get("locations") or []:
        if isinstance(loc, dict) and loc.get("id"):
            out[str(loc["id"])] = loc
    return out


def _weighted_pick(
    weights: dict[str, float],
    *,
    rng: random.Random,
) -> str | None:
    items = [(k, float(v)) for k, v in weights.items() if float(v) > 0]
    if not items:
        return None
    total = sum(w for _, w in items)
    r = rng.random() * total
    acc = 0.0
    for key, w in items:
        acc += w
        if r <= acc:
            return key
    return items[-1][0]


def pick_moment(
    when: datetime | None = None,
    *,
    character_id: str = "yuuka",
    storyline_phase: str | None = None,
    last_location_id: str | None = None,
    same_location_streak: int = 0,
    rng: random.Random | None = None,
    respect_quiet: bool = True,
) -> WorldMoment:
    """Sample a daily-life beat (location + action + optional festival)."""
    world = load_world(character_id)
    tz = world_tz(world)
    if when is None:
        now = datetime.now(tz)
    elif when.tzinfo is None:
        now = when.replace(tzinfo=tz)
    else:
        now = when.astimezone(tz)
    hour = now.hour
    slot = slot_for_hour(hour)
    rng = rng or random.Random()

    if respect_quiet and in_quiet_hours(hour, world):
        return WorldMoment(
            slot=slot,
            location_id="",
            location_name="",
            location_vibe="",
            action="",
            quiet=True,
        )

    schedule = (world.get("schedule") or {}).get(slot) or {}
    weights: dict[str, float] = {
        str(k): float(v) for k, v in schedule.items() if v is not None
    }
    locs = _loc_map(world)
    weights = {k: v for k, v in weights.items() if k in locs}
    if not weights and locs:
        weights = {k: 1.0 for k in locs}

    rules = world.get("rules") or {}
    boosts = (rules.get("storyline_boost") or {}) if isinstance(rules, dict) else {}
    phase = (storyline_phase or "").strip()
    if phase and isinstance(boosts, dict):
        phase_boost = boosts.get(phase) or {}
        if isinstance(phase_boost, dict):
            for lid, mul in phase_boost.items():
                if lid in weights:
                    weights[lid] = weights[lid] * float(mul)

    obs = active_observance(now, world)
    if obs:
        loc_boost = obs.get("location_boost") or {}
        if isinstance(loc_boost, dict):
            for lid, mul in loc_boost.items():
                if lid in weights:
                    weights[lid] = weights[lid] * float(mul)
                elif lid in locs:
                    weights[lid] = float(mul)

    max_streak = int((rules or {}).get("max_same_location_streak") or 2)
    if (
        last_location_id
        and same_location_streak >= max_streak
        and last_location_id in weights
        and len(weights) > 1
    ):
        weights[last_location_id] = 0.0

    loc_id = _weighted_pick(weights, rng=rng) or next(iter(locs), "desk")
    loc = locs.get(loc_id) or {}
    actions = list((world.get("actions") or {}).get(loc_id) or ["處理手頭的事"])
    if obs:
        extra = obs.get("action_extra") or []
        if isinstance(extra, list):
            actions.extend(str(a) for a in extra if a)
    action = rng.choice(actions) if actions else "處理手頭的事"

    tone = str(obs.get("tone") or "").strip() if obs else ""
    obs_id = str(obs.get("id") or "").strip() if obs else None
    hint = None
    if obs and obs.get("storyline_hint"):
        hint = str(obs["storyline_hint"]).strip() or None
    elif phase:
        hint = phase

    return WorldMoment(
        slot=slot,
        location_id=loc_id,
        location_name=str(loc.get("name") or loc_id),
        location_vibe=str(loc.get("vibe") or "").strip(),
        action=action,
        observance_id=obs_id or None,
        observance_tone=tone,
        storyline_hint=hint,
        quiet=False,
    )


def sticky_moment(
    when: datetime | None = None,
    *,
    character_id: str = "yuuka",
    storyline_phase: str | None = None,
) -> WorldMoment:
    """Stable beat for a given local date+slot (chat scene anchor)."""
    world = load_world(character_id)
    tz = world_tz(world)
    if when is None:
        now = datetime.now(tz)
    elif when.tzinfo is None:
        now = when.replace(tzinfo=tz)
    else:
        now = when.astimezone(tz)
    slot = slot_for_hour(now.hour)
    obs = active_observance(now, world)
    obs_id = str((obs or {}).get("id") or "")
    seed = f"{character_id}|{now.date().isoformat()}|{slot}|{storyline_phase or ''}|{obs_id}"
    return pick_moment(
        now,
        character_id=character_id,
        storyline_phase=storyline_phase,
        rng=random.Random(seed),
        respect_quiet=False,
    )


def momotalk_system_prompt(
    *,
    character_id: str = "yuuka",
    home_mode: bool = True,
) -> str:
    """Short system for proactive posts — not a teacher chat turn."""
    from core.character import load_system_prompt

    card = load_system_prompt(character_id, home_mode=home_mode)
    # Keep card voice but drop Discord teacher-turn rules.
    return "\n".join(
        [
            card,
            "",
            "【MomoTalk 動態模式】",
            "你正在發一則頻道日常動態／碎念，不是在回覆某位老師的提問。",
            "不要點名「老師」、不要用問句硬釣回覆、不要客服腔。",
            "不要輸出思考過程或任何 think 標籤；只輸出一個合法 JSON 物件。",
            '格式：{"reply":"繁中動態","emotion":"neutral|happy|shy|tired|proud|flustered"}',
            "reply 不可空、不可複述提示詞原文（例如「繁中動態」四字）、勿提好感分數。",
        ]
    )


def momotalk_user_prompt(moment: WorldMoment, world: dict[str, Any] | None = None) -> str:
    data = world if world is not None else load_world()
    style = str((data.get("momotalk") or {}).get("style") or "").strip()
    max_chars = int((data.get("momotalk") or {}).get("max_chars") or 90)
    parts = [
        "/no_think",
        style,
        "",
        moment.prompt_block(),
        "",
        f"直接輸出 JSON（約 {max_chars} 字內的 reply）。",
    ]
    return "\n".join(p for p in parts if p is not None)
