from __future__ import annotations

from db.repository import trailing_orphan_user_ids


def test_trailing_orphan_user_ids_drops_only_suffix_users() -> None:
    rows = [
        (5, "user"),
        (4, "user"),
        (3, "assistant"),
        (2, "user"),
        (1, "assistant"),
    ]
    assert trailing_orphan_user_ids(rows) == [5, 4]


def test_trailing_orphan_user_ids_empty_when_assistant_last() -> None:
    rows = [(3, "assistant"), (2, "user"), (1, "assistant")]
    assert trailing_orphan_user_ids(rows) == []
