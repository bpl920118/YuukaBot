from __future__ import annotations

from core.character import load_character, match_storyline


def test_storyline_default_and_advance() -> None:
    char = load_character("yuuka")
    start = match_storyline("你好", [], char)
    assert "季度預算審核" in start
    assert "目前節拍（start）" in start or "審核剛起頭" in start

    mid = match_storyline("我來幫你對帳", ["預算審核好累"], char)
    assert "目前節拍（audit）" in mid

    schale = match_storyline("夏萊收據一堆", ["對帳"], char)
    assert "目前節拍（schale）" in schale

    end = match_storyline(
        "做完一起吃飯吧",
        ["對帳", "預算審核", "表單推過去"],
        char,
    )
    assert "目前節拍（winddown）" in end


if __name__ == "__main__":
    test_storyline_default_and_advance()
    print("ok")
