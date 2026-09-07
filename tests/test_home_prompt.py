from __future__ import annotations

from core.character import load_system_prompt, match_lorebook
from core.schemas import build_runtime_system


def test_local_prompt_preferred_in_home_mode() -> None:
    full = load_system_prompt("yuuka", home_mode=False)
    local = load_system_prompt("yuuka", home_mode=True)
    assert "早瀨優香" in local
    assert len(local) < len(full)


def test_lore_scans_recent_blob() -> None:
    # Key only in "history" portion of scan text
    out = match_lorebook(
        "昨天聊到泡麵月\n今天只說你好",
        character_id="yuuka",
        limit=2,
        max_chars=900,
    )
    assert "泡麵" in out or "相關回憶" in out


def test_home_runtime_system_shorter_schema() -> None:
    sys_home = build_runtime_system(
        "卡",
        lore="",
        memory_summary="上次對完一頁預算",
        home_mode=True,
    )
    assert "先前摘要" in sys_home
    assert "EXAMPLE JSON（一般對話）" not in sys_home
    sys_cloud = build_runtime_system("卡", home_mode=False)
    assert "EXAMPLE JSON（一般對話）" in sys_cloud
