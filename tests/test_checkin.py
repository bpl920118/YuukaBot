"""Offline checks for guild check-in helpers (no Discord / API)."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.scoring import (
    checkin_delta,
    crossed_milestones,
    current_title,
    daily_checkin_event_key,
    load_character,
    milestone_map,
    next_checkin_streak,
)


def main() -> None:
    today = date(2026, 9, 9)
    assert daily_checkin_event_key(today) == "checkin:2026-09-09"
    assert next_checkin_streak(None, 0, today) == 1
    assert next_checkin_streak("2026-09-08", 3, today) == 4
    assert next_checkin_streak("2026-09-07", 5, today) == 1
    assert next_checkin_streak("2026-09-09", 2, today) == 2

    scoring = {"checkin": {"base": 2, "streak_bonus": 1, "streak_bonus_cap": 3}}
    assert checkin_delta(1, scoring) == 2
    assert checkin_delta(2, scoring) == 3
    assert checkin_delta(10, scoring) == 5  # 2 + cap 3

    character = load_character("yuuka")
    milestones = milestone_map(character)
    assert 10 in milestones
    assert crossed_milestones(9, 10, milestones) == [10]
    assert crossed_milestones(10, 10, milestones) == []
    assert current_title(0, milestones) is None
    assert current_title(25, milestones) == milestones[25]["title"]
    assert current_title(100, milestones) == milestones[100]["title"]

    # streak continuity across yesterday
    yday = (today - timedelta(days=1)).isoformat()
    assert next_checkin_streak(yday, 1, today) == 2
    print("ok")


if __name__ == "__main__":
    main()
