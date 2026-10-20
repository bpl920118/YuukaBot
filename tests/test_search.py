import pytest
from unittest.mock import AsyncMock, patch
from core.pipeline import is_search_intent


def test_is_search_intent_keywords():
    assert is_search_intent("查一下今天日幣匯率") is True
    assert is_search_intent("幫我查最新活動") is True
    assert is_search_intent("明天天氣怎麼樣") is True
    assert is_search_intent("今天出門要帶傘嗎？即時氣象") is True
    assert is_search_intent("早安優香") is False
