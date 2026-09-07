"""Compare dialogue at several temperatures, then try chat→CG pipeline."""

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
from clients.vram_switch import release_home_llm_vram
from clients.webui import WebuiClient
from core.character import load_system_prompt
from core.prompt_builder import build_image_prompt, heuristic_image_tags
from core.schemas import build_runtime_system
from core.world import sticky_moment

TZ = timezone(timedelta(hours=8))
OUT = ROOT / "scripts" / "_temp_cg_probe.txt"


async def compare_temps(
    llm: LlmClient,
    *,
    base_url: str,
    model: str,
    key: str,
    temps: list[float],
) -> list[str]:
    home_prompt = load_system_prompt("yuuka", home_mode=True)
    scene = sticky_moment(
        datetime(2026, 5, 12, 10, 30, tzinfo=TZ),
        storyline_phase="audit",
    )
    system = build_runtime_system(
        home_prompt, lore=scene.prompt_block(), home_mode=True
    )
    prompts = [
        ("寒暄", "[老師9999] 你好"),
        ("課金", "[老師9999] 我又課金了三千"),
        ("在意", "[老師9999] 你是不是特別在意我？"),
    ]
    lines = [
        f"場景錨點: {scene.location_name} / {scene.action}",
        f"模型: {model} @ {base_url}",
        "",
    ]
    for label, user in prompts:
        lines.append("=" * 60)
        lines.append(f"【對話】{label} ← {user}")
        lines.append("=" * 60)
        for t in temps:
            raw = await llm.chat(
                system=system,
                messages=[{"role": "user", "content": f"/no_think\n{user}"}],
                depth="off",
                model=model,
                api_key=key,
                base_url=base_url,
                temperature=t,
                top_p=0.9,
                sampling_profile="chat",
            )
            r = llm.parse_result(raw)
            lines.append(f"--- temp={t:.2f} | emotion={r.emotion}")
            lines.append(r.reply)
            lines.append("")
    return lines


async def chat_then_cg(
    llm: LlmClient,
    webui: WebuiClient,
    *,
    base_url: str,
    model: str,
    key: str,
    temperature: float,
    sd_url: str,
    do_generate: bool,
) -> list[str]:
    lines: list[str] = ["", "=" * 60, "【對話→生圖】", "=" * 60]
    home_prompt = load_system_prompt("yuuka", home_mode=True)
    scene = sticky_moment(
        datetime(2026, 5, 12, 15, 0, tzinfo=TZ),
        storyline_phase="audit",
    )
    system = build_runtime_system(
        home_prompt, lore=scene.prompt_block(), home_mode=True
    )
    user = "[老師9999] （把紙杯拿鐵遞過去，指尖碰到你的手）給你的，別再說是成本建議了。"
    raw = await llm.chat(
        system=system,
        messages=[{"role": "user", "content": f"/no_think\n{user}"}],
        depth="off",
        model=model,
        api_key=key,
        base_url=base_url,
        temperature=temperature,
        top_p=0.9,
        sampling_profile="chat",
    )
    result = llm.parse_result(raw)
    lines.append(f"user: {user}")
    lines.append(f"temp={temperature:.2f} emotion={result.emotion}")
    lines.append(f"reply: {result.reply}")
    lines.append(f"llm.image_prompt: {result.image_prompt!r}")
    lines.append(f"llm.trigger_cg: {result.trigger_cg}")

    heuristic = heuristic_image_tags(result.reply, result.emotion)
    lines.append(f"heuristic: {heuristic}")

    # Mirror pipeline._infer_image_prompt (short)
    infer_system = (
        "只輸出合法 JSON（不要 markdown、不要 think）："
        '{"reply":".","emotion":"neutral","trigger_cg":true,"cg_tier":"normal",'
        '"cg_scene":null,"image_prompt":"english danbooru tags"}。'
        "image_prompt 必須緊扣最新對白：道具、動作、表情。8～20 個英文短標籤。"
    )
    infer_raw = await llm.chat(
        system=infer_system,
        messages=[
            {
                "role": "user",
                "content": (
                    f"/no_think\nuser: {user}\nassistant_latest: {result.reply}\n"
                    f"hint_tags: {heuristic or ''}"
                ),
            }
        ],
        depth="off",
        model=model,
        api_key=key,
        base_url=base_url,
        temperature=0.5,
        sampling_profile="chat",
        max_tokens=220,
    )
    inferred = llm.parse_result(infer_raw)
    image_prompt = (inferred.image_prompt or heuristic or "").strip()
    lines.append(f"inferred.image_prompt: {inferred.image_prompt!r}")

    final_prompt = build_image_prompt(
        result.cg_scene.model_dump() if result.cg_scene else None,
        "yuuka",
        image_prompt=image_prompt or None,
    )
    lines.append(f"final SD prompt:\n{final_prompt}")

    ok, msg = await webui.health(base_url=sd_url or None)
    lines.append(f"WebUI health: {ok} — {msg}")
    if not do_generate:
        lines.append("（略過實際 txt2img：加 --generate 才會生圖）")
        return lines
    if not ok:
        lines.append("WebUI 未就緒，無法生圖。請先開 A1111（--api），再重跑 --generate。")
        return lines

    await release_home_llm_vram(base_url, model)
    path = await webui.generate(
        prompt=final_prompt,
        tier="normal",
        guild_id=0,
        base_url=sd_url or None,
    )
    lines.append(f"image_path: {path}")
    return lines


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:5001/v1")
    p.add_argument("--model", default="koboldcpp/Qwen3-8B-Q4_K_M")
    p.add_argument("--key", default="local")
    p.add_argument("--sd-url", default="http://127.0.0.1:7860")
    p.add_argument("--temps", default="0.5,0.7,0.85,1.0,1.2")
    p.add_argument("--cg-temp", type=float, default=0.85)
    p.add_argument("--skip-temps", action="store_true")
    p.add_argument("--generate", action="store_true")
    args = p.parse_args()
    temps = [float(x) for x in args.temps.split(",") if x.strip()]

    llm = LlmClient()
    webui = WebuiClient()
    lines: list[str] = []
    if not args.skip_temps:
        lines.extend(
            await compare_temps(
                llm,
                base_url=args.base_url,
                model=args.model,
                key=args.key,
                temps=temps,
            )
        )
    lines.extend(
        await chat_then_cg(
            llm,
            webui,
            base_url=args.base_url,
            model=args.model,
            key=args.key,
            temperature=args.cg_temp,
            sd_url=args.sd_url,
            do_generate=args.generate,
        )
    )
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    asyncio.run(main())
