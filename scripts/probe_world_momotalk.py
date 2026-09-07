"""Probe world moments + optional home Kobold MomoTalk samples."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clients.llm import LlmClient
from core.character import load_system_prompt
from core.home_llm import is_home_inference_url
from core.schemas import build_runtime_system
from core.world import (
    momotalk_system_prompt,
    momotalk_user_prompt,
    pick_moment,
    sticky_moment,
)


TZ = timezone(timedelta(hours=8))


SAMPLES = [
    ("平常上午", datetime(2026, 5, 12, 10, 30, tzinfo=TZ), "audit"),
    ("平常傍晚", datetime(2026, 5, 12, 18, 40, tzinfo=TZ), None),
    ("安靜時段", datetime(2026, 5, 12, 2, 0, tzinfo=TZ), None),
    ("生日", datetime(2026, 3, 14, 11, 0, tzinfo=TZ), None),
    ("結帳週", datetime(2026, 3, 30, 21, 0, tzinfo=TZ), "audit"),
    ("學園祭", datetime(2026, 11, 3, 14, 0, tzinfo=TZ), None),
    ("聖誕夜", datetime(2026, 12, 24, 22, 0, tzinfo=TZ), "winddown"),
]


def print_moments() -> None:
    print("=== pick_moment samples ===")
    for label, when, phase in SAMPLES:
        m = pick_moment(when, storyline_phase=phase, respect_quiet=True)
        if m.quiet:
            print(f"[{label}] QUIET ({m.slot})")
            continue
        fest = m.observance_id or "-"
        print(
            f"[{label}] {m.slot} | {m.location_name} | {m.action} | fest={fest}"
        )


async def probe_llm(base_url: str, model: str, key: str) -> None:
    home = is_home_inference_url(base_url)
    print(f"\n=== LLM probe home={home} temp-profile auto ===")
    llm = LlmClient()
    base_prompt = load_system_prompt("yuuka", home_mode=home)

    scene = sticky_moment(
        datetime(2026, 5, 12, 10, 30, tzinfo=TZ),
        storyline_phase="audit",
    )
    system = build_runtime_system(
        base_prompt,
        lore=scene.prompt_block(),
        home_mode=home,
    )
    raw = await llm.chat(
        system=system,
        messages=[
            {
                "role": "user",
                "content": "/no_think\n[老師9999] 你好",
            }
        ],
        depth="off",
        model=model,
        api_key=key,
        base_url=base_url,
        sampling_profile="chat",
    )
    chat = llm.parse_result(raw)
    print(f"[chat/你好] emotion={chat.emotion}\n{chat.reply}\n")

    mt_system = momotalk_system_prompt(home_mode=home)
    for label, when, phase in SAMPLES:
        m = pick_moment(when, storyline_phase=phase, respect_quiet=True)
        if m.quiet:
            print(f"[momotalk/{label}] skipped (quiet)")
            continue
        user = momotalk_user_prompt(m)
        raw = await llm.chat(
            system=mt_system,
            messages=[{"role": "user", "content": user}],
            depth="off",
            model=model,
            api_key=key,
            base_url=base_url,
            sampling_profile="momotalk",
        )
        post = llm.parse_result(raw)
        print(
            f"[momotalk/{label}] {m.location_id}/{m.action} "
            f"fest={m.observance_id or '-'}\n{post.reply}\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="Call local/cloud LLM")
    parser.add_argument("--base-url", default="http://127.0.0.1:5001/v1")
    parser.add_argument("--model", default="koboldcpp/Qwen3-8B-Q4_K_M")
    parser.add_argument("--key", default="local")
    args = parser.parse_args()

    print_moments()
    if args.llm:
        asyncio.run(probe_llm(args.base_url, args.model, args.key))


if __name__ == "__main__":
    main()
