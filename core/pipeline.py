from __future__ import annotations

from datetime import datetime, timezone

from config import get_settings
from core.prompt_builder import build_image_prompt
from core.schemas import build_runtime_system
from core.character import load_character, load_system_prompt
from core.llm_options import parse_depth_arg, parse_model_arg, resolve_depth, resolve_model
from clients.webui import WebuiClient, normalize_webui_url
from clients.llm import LlmClient
from db.repository import Repository


class ChatPipeline:
    def __init__(
        self,
        repo: Repository,
        llm: LlmClient,
        webui: WebuiClient,
        character_id: str = "yuuka",
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.webui = webui
        self.character_id = character_id
        self.character = load_character(character_id)
        self.base_prompt = load_system_prompt(character_id)

    async def handle(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        text: str,
        is_teacher: bool,
    ) -> dict:
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)

        command_reply = await self._maybe_handle_command(
            guild_id, user_id, text, guild_settings, is_teacher
        )
        if command_reply is not None:
            if isinstance(command_reply, dict):
                return command_reply
            return {"reply": command_reply, "emotion": "neutral", "image_path": None}

        work_mode = bool(guild_settings.work_mode)
        if guild_settings.locked_to_teacher and not is_teacher:
            return {
                "reply": "……現在設定成只回應老師。有正事的話請老師本人來說。",
                "emotion": "neutral",
                "image_path": None,
            }

        history = await self.repo.recent_messages(
            guild_id, limit=settings.memory_limit, character_id=self.character_id
        )
        messages = []
        for m in history:
            if m.role == "user":
                prefix = f"[{m.display_name or m.user_id}] "
                messages.append({"role": "user", "content": prefix + m.content})
            else:
                messages.append({"role": "assistant", "content": m.content})

        user_payload = f"[{display_name}] {text}" if text.strip() else f"[{display_name}] （只呼叫了你）"
        messages.append({"role": "user", "content": user_payload})

        system = build_runtime_system(
            self.base_prompt,
            extra_layers=guild_settings.extra_layers or "",
            work_mode=work_mode,
            is_teacher=is_teacher,
        )

        model = resolve_model(guild_settings.llm_model, settings.deepseek_model)
        depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
        raw = await self.llm.chat(
            system=system, messages=messages, model=model, depth=depth
        )
        result = self.llm.parse_result(raw)

        await self.repo.add_message(
            guild_id=guild_id,
            role="user",
            content=text or "（呼叫）",
            user_id=user_id,
            display_name=display_name,
            character_id=self.character_id,
        )
        await self.repo.add_message(
            guild_id=guild_id,
            role="assistant",
            content=result.reply,
            character_id=self.character_id,
        )

        if work_mode:
            return {
                "reply": result.reply,
                "emotion": "neutral",
                "image_path": None,
            }

        image_path = None
        allow_cg, tier = await self._cg_policy(
            guild_id=guild_id,
            trigger=result.trigger_cg,
            requested_tier=result.cg_tier,
        )
        if allow_cg and result.cg_scene is not None:
            prompt = build_image_prompt(result.cg_scene.model_dump(), self.character_id)
            image_path = await self.webui.generate(
                prompt=prompt,
                tier=tier,
                guild_id=guild_id,
                base_url=guild_settings.sd_webui_url or None,
            )
            if image_path:
                await self.repo.add_gallery(
                    guild_id=guild_id,
                    path=str(image_path),
                    prompt=prompt,
                    tier=tier,
                    emotion=result.emotion,
                    triggered_by_user_id=user_id,
                    character_id=self.character_id,
                )

        return {
            "reply": result.reply,
            "emotion": result.emotion,
            "image_path": image_path,
        }

    async def _cg_policy(
        self,
        *,
        guild_id: int,
        trigger: bool,
        requested_tier: str,
    ) -> tuple[bool, str]:
        settings = get_settings()
        if not trigger:
            return False, "none"

        last = await self.repo.last_gallery_at(guild_id, self.character_id)
        now = datetime.now(timezone.utc)
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < settings.cg_cooldown_seconds:
                return False, "none"

        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_items = await self.repo.gallery_since(guild_id, day_start, self.character_id)
        if len(today_items) >= settings.cg_daily_limit:
            return False, "none"

        tier = "special" if requested_tier == "special" else "normal"
        return True, tier

    async def _maybe_handle_command(
        self, guild_id: int, user_id: int, text: str, guild_settings, is_teacher: bool
    ) -> str | None:
        stripped = text.strip()
        if not stripped:
            return None
        if not (stripped.startswith("(") or stripped.startswith("（")):
            return None
        if not is_teacher:
            return "設定指令只有老師可以使用。"

        body = stripped.lstrip("(（").rstrip(")）").strip()
        settings = get_settings()

        # Channel purge is handled in bot/main.py (needs Discord channel API).
        if any(
            body.startswith(p)
            for p in (
                "清除頻道",
                "刪除頻道",
                "消除頻道",
                "清除機器人訊息",
                "刪除機器人訊息",
                "消除機器人訊息",
            )
        ):
            return (
                "頻道訊息清除請用：`（清除頻道 從10:55）`，"
                "或回覆劇情第一則後再 `（清除頻道 從此）`。"
            )

        if body in ("模型", "查看模型", "模型設定", "深度", "查看深度"):
            model = resolve_model(guild_settings.llm_model, settings.deepseek_model)
            depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
            return (
                f"目前模型=`{model}`，深度=`{depth}`。\n"
                "老師可設定：`（模型 flash）` / `（模型 pro）`；"
                "`（深度 關）` / `（深度 high）` / `（深度 max）`。"
            )

        if body.startswith("模型"):
            arg = body[2:].strip()
            if not arg:
                model = resolve_model(guild_settings.llm_model, settings.deepseek_model)
                depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
                return f"目前模型=`{model}`，深度=`{depth}`。"
            parsed = parse_model_arg(arg)
            if parsed is None:
                return "可用模型：`flash`（deepseek-v4-flash）、`pro`（deepseek-v4-pro）。"
            guild_settings.llm_model = parsed
            await self.repo.save_settings(guild_settings)
            return f"已切換模型為 `{parsed}`（僅老師可改）。"

        if body.startswith("深度"):
            arg = body[2:].strip()
            if not arg:
                model = resolve_model(guild_settings.llm_model, settings.deepseek_model)
                depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
                return f"目前模型=`{model}`，深度=`{depth}`。"
            parsed = parse_depth_arg(arg)
            if parsed is None:
                return "可用深度：`關`（off）、`high`、`max`。"
            guild_settings.llm_depth = parsed
            await self.repo.save_settings(guild_settings)
            return f"已切換深度為 `{parsed}`（僅老師可改）。"

        if body in ("生圖", "生圖狀態", "查看生圖"):
            effective = (guild_settings.sd_webui_url or "").strip() or (
                settings.sd_webui_url or ""
            ).strip() or "（未設定）"
            ok, detail = await self.webui.health(
                base_url=guild_settings.sd_webui_url or None
            )
            flag = "OK" if ok else "NG"
            return (
                f"生圖狀態 `{flag}`\n"
                f"有效網址：`{effective}`\n"
                f"{detail}\n"
                "設定：`（生圖網址 http://100.x.y.z:7860）`；關閉：`（關閉生圖）`。"
            )

        if body.startswith("生圖網址"):
            arg = body[4:].strip()
            if not arg:
                return "用法：`（生圖網址 http://100.x.y.z:7860）`"
            try:
                url = normalize_webui_url(arg)
            except ValueError as exc:
                return str(exc)
            guild_settings.sd_webui_url = url
            await self.repo.save_settings(guild_settings)
            ok, detail = await self.webui.health(base_url=url)
            flag = "已連上" if ok else "已儲存但尚未連上"
            return f"{flag}：`{url}`\n{detail}"

        if body in ("關閉生圖", "停止生圖"):
            guild_settings.sd_webui_url = ""
            await self.repo.save_settings(guild_settings)
            return "已關閉本伺服器生圖覆寫（改回 .env；若 .env 也空白則不出圖）。"

        if body in ("測試生圖", "生圖測試"):
            scene = {
                "character": "Yuuka",
                "location": "millennium science school classroom, desk, window light",
                "time": "afternoon",
                "action": "sitting at desk, holding calculator, looking at viewer",
                "expression": "slight smile, half-closed eyes",
                "mood": "calm, soft lighting",
            }
            prompt = build_image_prompt(scene, self.character_id)
            try:
                image_path = await self.webui.generate(
                    prompt=prompt,
                    tier="normal",
                    guild_id=guild_id,
                    base_url=guild_settings.sd_webui_url or None,
                )
            except Exception as exc:
                return f"測試生圖失敗：`{type(exc).__name__}: {exc}`"
            if not image_path:
                ok, detail = await self.webui.health(
                    base_url=guild_settings.sd_webui_url or None
                )
                return f"沒有產出圖片。請先確認生圖網址。\n{detail}"
            await self.repo.add_gallery(
                guild_id=guild_id,
                path=str(image_path),
                prompt=prompt,
                tier="normal",
                emotion="neutral",
                triggered_by_user_id=user_id,
                character_id=self.character_id,
            )
            return {
                "reply": "測試生圖完成。",
                "emotion": "neutral",
                "image_path": str(image_path),
            }

        if any(k in body for k in ("清除對話", "刪除對話", "清除記憶", "刪除記憶")):
            n = await self.repo.clear_messages(guild_id, self.character_id)
            return f"已清除本伺服器對話記憶（{n} 則）。之後會當新對話開始。"

        if any(k in body for k in ("清除圖庫", "刪除圖庫", "清除CG", "清除 cg")):
            n = await self.repo.clear_gallery(guild_id, self.character_id)
            return f"已清除本伺服器圖庫紀錄（{n} 筆）。磁碟上的舊圖檔未刪。"

        if any(k in body for k in ("清除叠加", "清除疊加", "清除額外設定", "清除老師設定")):
            guild_settings.extra_layers = ""
            await self.repo.save_settings(guild_settings)
            return "已清除老師叠加設定。"

        if any(k in body for k in ("只回老師", "不要回其他人", "鎖定")):
            guild_settings.locked_to_teacher = 1
            await self.repo.save_settings(guild_settings)
            return "好的，之後只回應老師。"
        if any(k in body for k in ("解除鎖定", "可以回其他人")):
            guild_settings.locked_to_teacher = 0
            await self.repo.save_settings(guild_settings)
            return "已解除鎖定，可以回應其他人。"
        if "關閉人設" in body:
            guild_settings.work_mode = 1
            await self.repo.save_settings(guild_settings)
            return "已切換為工作模式。"
        if any(k in body for k in ("恢復人設", "回復人設")):
            guild_settings.work_mode = 0
            await self.repo.save_settings(guild_settings)
            return "已恢復優香人設。"

        guild_settings.extra_layers = (
            (guild_settings.extra_layers or "") + f"\n- {body}"
        ).strip()
        await self.repo.save_settings(guild_settings)
        return "設定已記下。"
