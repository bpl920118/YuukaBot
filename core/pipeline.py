from __future__ import annotations

from datetime import datetime, timezone

from config import get_settings
from core.prompt_builder import build_image_prompt
from core.schemas import build_runtime_system, soft_fallback_reply
from core.character import load_character, load_system_prompt, match_lorebook
from core.immersion import apply_immersion_marker
from core.llm_options import parse_depth_arg, parse_model_arg, resolve_depth, resolve_model
from clients.webui import WebuiClient, normalize_webui_url
from clients.llm import LlmClient, is_near_duplicate
from db.repository import Repository


def _speaker_label(user_id: int | None) -> str:
    """Everyone is addressed as 老師 in RP; last-4 digits only disambiguate speakers."""
    if user_id is None:
        return "老師"
    return f"老師{str(user_id)[-4:]}"


def _user_message_payload(*, user_id: int | None, text: str) -> str:
    """Never send Discord display names — nicknames are often treated as dialogue."""
    body = text if text.strip() else "（只呼叫了你）"
    return f"[{_speaker_label(user_id)}] {body}"


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
        is_owner: bool,
    ) -> dict:
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)

        work_mode = bool(guild_settings.work_mode)
        # Lock still gates on the real owner (TEACHER_USER_ID), not RP 「老師」.
        if guild_settings.locked_to_teacher and not is_owner:
            return {
                "reply": "……現在設定成只回應管理者。有正事的話請本人來說。",
                "emotion": "neutral",
                "image_path": None,
            }

        history = await self.repo.recent_messages(
            guild_id, limit=settings.memory_limit, character_id=self.character_id
        )
        messages = []
        last_assistant_reply = ""
        for m in history:
            if m.role == "user":
                messages.append(
                    {
                        "role": "user",
                        "content": _user_message_payload(
                            user_id=m.user_id,
                            text=m.content,
                        ),
                    }
                )
            else:
                messages.append({"role": "assistant", "content": m.content})
                last_assistant_reply = m.content or last_assistant_reply

        messages.append(
            {
                "role": "user",
                "content": _user_message_payload(
                    user_id=user_id,
                    text=text if text.strip() else "（只呼叫了你）",
                ),
            }
        )

        lore = match_lorebook(
            text or "",
            self.character,
            character_id=self.character_id,
            limit=2,
        )
        system = build_runtime_system(
            self.base_prompt,
            extra_layers=guild_settings.extra_layers or "",
            work_mode=work_mode,
            lore=lore,
        )

        model = resolve_model(guild_settings.llm_model, settings.deepseek_model)
        depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
        # Official V4 immersion marker: only when toggled on + thinking enabled.
        if bool(guild_settings.llm_immersion) and depth != "off":
            apply_immersion_marker(messages)
        raw = await self.llm.chat(
            system=system,
            messages=messages,
            model=model,
            depth=depth,
            last_reply=last_assistant_reply or None,
        )
        result = self.llm.parse_result(raw)

        # Final guard: still duplicated after retries → local soft line, no more API.
        if last_assistant_reply and is_near_duplicate(result.reply, last_assistant_reply):
            result.reply = soft_fallback_reply(user_id ^ guild_id)
            result.emotion = "flustered"
            result.trigger_cg = False
            result.cg_tier = "none"
            result.cg_scene = None

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

    async def describe_llm(self, guild_id: int) -> str:
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        model = resolve_model(guild_settings.llm_model, settings.deepseek_model)
        depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
        immersion = "開" if guild_settings.llm_immersion else "關"
        note = ""
        if guild_settings.llm_immersion and depth == "off":
            note = "\n⚠ 沉浸已開但深度是 `off`，官方沉浸指令不會生效；請用 `/depth` 切 `high` 或 `max`。"
        return (
            f"目前模型=`{model}`，深度=`{depth}`，角色沉浸=`{immersion}`。\n"
            "可用：`/model`、`/depth`、`/immersion`。"
            f"{note}"
        )

    async def set_model(self, guild_id: int, arg: str) -> str:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        parsed = parse_model_arg(arg)
        if parsed is None:
            return "可用模型：`flash`（deepseek-v4-flash）、`pro`（deepseek-v4-pro）。"
        guild_settings.llm_model = parsed
        await self.repo.save_settings(guild_settings)
        return f"已切換模型為 `{parsed}`（僅管理者可改）。"

    async def set_depth(self, guild_id: int, arg: str) -> str:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        parsed = parse_depth_arg(arg)
        if parsed is None:
            return "可用深度：`關`（off）、`high`、`max`。"
        guild_settings.llm_depth = parsed
        await self.repo.save_settings(guild_settings)
        extra = ""
        if parsed == "off" and guild_settings.llm_immersion:
            extra = "（沉浸仍為開，但 depth=off 時不會注入沉浸指令。）"
        elif parsed != "off" and guild_settings.llm_immersion:
            extra = "（沉浸已開：之後對話會注入官方角色沉浸指令。）"
        return f"已切換深度為 `{parsed}`（僅管理者可改）。{extra}"

    async def set_immersion(self, guild_id: int, enabled: bool) -> str:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.llm_immersion = 1 if enabled else 0
        await self.repo.save_settings(guild_settings)
        settings = get_settings()
        depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
        if enabled:
            tip = (
                f"已開啟角色沉浸。目前深度=`{depth}`。"
                if depth != "off"
                else "已開啟角色沉浸，但目前深度=`off`，尚不會生效。請再用 `/depth` 選 `high` 或 `max` 測試。"
            )
            return tip
        return "已關閉角色沉浸（不再注入官方思考沉浸指令）。"

    async def describe_image(self, guild_id: int) -> str:
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
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
            "設定：`/image url`；關閉：`/image off`；測試：`/image test`。"
        )

    async def set_image_url(self, guild_id: int, url_raw: str) -> str:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        try:
            url = normalize_webui_url(url_raw)
        except ValueError as exc:
            return str(exc)
        guild_settings.sd_webui_url = url
        await self.repo.save_settings(guild_settings)
        ok, detail = await self.webui.health(base_url=url)
        flag = "已連上" if ok else "已儲存但尚未連上"
        return f"{flag}：`{url}`\n{detail}"

    async def disable_image(self, guild_id: int) -> str:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.sd_webui_url = ""
        await self.repo.save_settings(guild_settings)
        return "已關閉本伺服器生圖覆寫（改回 .env；若 .env 也空白則不出圖）。"

    async def test_image(self, guild_id: int, user_id: int) -> dict:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
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
            return {
                "reply": f"測試生圖失敗：`{type(exc).__name__}: {exc}`",
                "emotion": "neutral",
                "image_path": None,
            }
        if not image_path:
            _ok, detail = await self.webui.health(
                base_url=guild_settings.sd_webui_url or None
            )
            return {
                "reply": f"沒有產出圖片。請先確認生圖網址。\n{detail}",
                "emotion": "neutral",
                "image_path": None,
            }
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

    async def clear_memory(self, guild_id: int) -> str:
        n = await self.repo.clear_messages(guild_id, self.character_id)
        return f"已清除本伺服器對話記憶（{n} 則）。之後會當新對話開始。"

    async def clear_gallery(self, guild_id: int) -> str:
        n = await self.repo.clear_gallery(guild_id, self.character_id)
        return f"已清除本伺服器圖庫紀錄（{n} 筆）。磁碟上的舊圖檔未刪。"

    async def clear_layers(self, guild_id: int) -> str:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.extra_layers = ""
        await self.repo.save_settings(guild_settings)
        return "已清除老師叠加設定。"

    async def set_locked(self, guild_id: int, locked: bool) -> str:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.locked_to_teacher = 1 if locked else 0
        await self.repo.save_settings(guild_settings)
        if locked:
            return "好的，之後只回應管理者本人。"
        return "已解除鎖定，可以回應其他人。"

    async def set_work_mode(self, guild_id: int, work_mode: bool) -> str:
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.work_mode = 1 if work_mode else 0
        await self.repo.save_settings(guild_settings)
        if work_mode:
            return "已切換為工作模式。"
        return "已恢復優香人設。"

    async def add_layer(self, guild_id: int, note: str) -> str:
        body = (note or "").strip()
        if not body:
            return "請輸入要叠加的設定內容。"
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.extra_layers = (
            (guild_settings.extra_layers or "") + f"\n- {body}"
        ).strip()
        await self.repo.save_settings(guild_settings)
        return "設定已記下。"
