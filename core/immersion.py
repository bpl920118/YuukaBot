"""DeepSeek V4 official role-immersion marker (thinking-mode style switch).

Docs: https://github.com/victorchen96/deepseek_v4_rolepaly_instruct
Best injected at the end of the first user message in the request; only meaningful
when thinking is enabled (depth != off).
"""

from __future__ import annotations

IMMERSION_TAG = "【角色沉浸要求】"

# Official Chinese instruction text (verbatim).
INNER_OS_MARKER = (
    f"\n\n{IMMERSION_TAG}在你的思考過程（<think>標籤內）中，請遵守以下規則：\n"
    "1. 請以角色第一人稱進行內心獨白，用括號包裹內心活動，例如"（心想：……）"或"(內心OS：……)"\n"
    "2. 用第一人稱描寫角色的內心感受，例如「我心想」「我覺得」「我暗自」等\n"
    "3. 思考內容應沉浸在角色中，通過內心獨白分析劇情和規劃回覆"
)


def apply_immersion_marker(messages: list[dict[str, str]]) -> bool:
    """
    Append the official marker to the first user message if not already present.
    Mutates messages in place. Returns True if marker is present after call.
    """
    if any(IMMERSION_TAG in (m.get("content") or "") for m in messages):
        return True
    for m in messages:
        if m.get("role") == "user":
            m["content"] = (m.get("content") or "") + INNER_OS_MARKER
            return True
    return False
