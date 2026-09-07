from __future__ import annotations

from datetime import datetime, timedelta, timezone
from random import Random

from core.world import (
    active_observance,
    clear_world_cache,
    in_quiet_hours,
    load_world,
    pick_moment,
    slot_for_hour,
    sticky_moment,
)


TZ = timezone(timedelta(hours=8))


def setup_function() -> None:
    clear_world_cache()


def test_world_loads_locations_and_festivals() -> None:
    world = load_world("yuuka")
    assert world.get("locations")
    assert world.get("observances")
    assert "desk" in (world.get("actions") or {})


def test_quiet_hours_and_slots() -> None:
    assert in_quiet_hours(3)
    assert not in_quiet_hours(10)
    assert slot_for_hour(10) == "morning"
    assert slot_for_hour(19) == "evening"
    assert slot_for_hour(23) == "night"


def test_birthday_beats_white_day() -> None:
    d = datetime(2026, 3, 14, 11, 0, tzinfo=TZ)
    obs = active_observance(d)
    assert obs is not None
    assert obs.get("id") == "yuuka_birthday"


def test_fiscal_close_window() -> None:
    d = datetime(2026, 3, 29, 16, 0, tzinfo=TZ)
    obs = active_observance(d)
    assert obs is not None
    assert obs.get("id") == "fiscal_close"


def test_pick_moment_respects_quiet() -> None:
    m = pick_moment(datetime(2026, 5, 1, 2, 0, tzinfo=TZ), rng=Random(1))
    assert m.quiet is True


def test_pick_moment_audit_boosts_desk() -> None:
    hits = 0
    for i in range(40):
        m = pick_moment(
            datetime(2026, 5, 1, 10, 0, tzinfo=TZ),
            storyline_phase="audit",
            rng=Random(i),
            respect_quiet=False,
        )
        if m.location_id == "desk":
            hits += 1
    assert hits >= 12


def test_same_location_streak_forces_change() -> None:
    m = pick_moment(
        datetime(2026, 5, 1, 10, 0, tzinfo=TZ),
        last_location_id="desk",
        same_location_streak=2,
        rng=Random(0),
        respect_quiet=False,
    )
    assert m.location_id != "desk"


def test_sticky_moment_stable_same_slot() -> None:
    when = datetime(2026, 5, 1, 15, 0, tzinfo=TZ)
    a = sticky_moment(when, storyline_phase="schale")
    b = sticky_moment(when, storyline_phase="schale")
    assert a.location_id == b.location_id
    assert a.action == b.action
    assert a.quiet is False
