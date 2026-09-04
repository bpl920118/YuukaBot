from __future__ import annotations

from datetime import datetime, timezone

from config import get_settings
from core.prompt_builder import build_image_prompt
from core.schemas import build_runtime_system
from core.character import load_character, load_system_prompt
from clients.webui import WebuiClient
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

        raw = await self.llm.chat(system=system, messages=messages)
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
