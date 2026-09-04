from __future__ import annotations

from datetime import datetime, timezone

from config import get_settings
from core.prompt_builder import build_image_prompt, heuristic_image_tags
from core.schemas import (
    build_runtime_system,
    is_soft_fallback,
    scrub_score_leak,
    soft_fallback_reply,
)
from core.character import (
    load_character,
    load_system_prompt,
    match_lorebook,
    match_storyline,
)
from core.immersion import apply_immersion_marker
from core.llm_options import parse_depth_arg, parse_model_arg, resolve_depth
from core.providers import (
    PRESETS,
    SWITCH_PROFILES,
    api_key_for_provider,
    default_base_url,
    default_model_for_provider,
    detect_provider,
    get_preset,
    get_switch_profile,
    mask_api_key,
    model_menu_lines,
    normalize_base_url,
    normalize_provider_id,
    resolve_model_name,
    supports_thinking,
)
from core.scoring import AffectionScorer
from clients.webui import WebuiClient, normalize_webui_url
from clients.llm import LlmClient, is_near_duplicate
from db.repository import Repository


def _env_default_base(settings) -> str:
    return default_base_url(
        settings.llm_provider,
        deepseek_base_url=settings.deepseek_base_url,
    )


def _env_default_model(settings, provider_id: str) -> str:
    return default_model_for_provider(
        provider_id,
        deepseek_model=settings.deepseek_model,
        gemini_model=settings.gemini_model,
        openai_model=settings.openai_model,
    )


def _resolve_guild_endpoint(guild_settings, settings) -> tuple[str, str, str]:
    """Return (base_url, api_key, model) for this guild (.env as fallback)."""
    base_override = (guild_settings.llm_api_base_url or "").strip()
    base = base_override or _env_default_base(settings)
    provider = detect_provider(base)
    key_override = (guild_settings.llm_api_key or "").strip()
    if key_override:
        key = key_override
    else:
        key, _ = api_key_for_provider(
            provider,
            deepseek_api_key=settings.deepseek_api_key,
            gemini_api_key=settings.gemini_api_key,
            openai_api_key=settings.openai_api_key,
        )
    fallback_model = _env_default_model(settings, provider)
    model = resolve_model_name(
        guild_settings.llm_model,
        fallback_model,
        base_url=base,
    )
    return base.rstrip("/"), key, model


def _key_source_label(guild_settings, settings, provider: str) -> str:
    if (guild_settings.llm_api_key or "").strip():
        return "伺服器 /api key"
    _, env_name = api_key_for_provider(
        provider,
        deepseek_api_key=settings.deepseek_api_key,
        gemini_api_key=settings.gemini_api_key,
        openai_api_key=settings.openai_api_key,
    )
    return f".env {env_name}"


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
        self.scorer = AffectionScorer(repo, character_id=character_id)

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
                "pending_cg": None,
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
                # Skip canned soft-fallbacks so they don't teach the model ice-queen lines.
                if is_soft_fallback(m.content or ""):
                    continue
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
        recent_for_story = [
            m.content
            for m in history
            if m.role in {"user", "assistant"} and (m.content or "").strip()
        ][-8:]
        story = match_storyline(
            text or "",
            recent_for_story,
            self.character,
            character_id=self.character_id,
        )
        lore_blocks = "\n\n".join(p for p in (story, lore) if p.strip())
        system = build_runtime_system(
            self.base_prompt,
            extra_layers=guild_settings.extra_layers or "",
            work_mode=work_mode,
            lore=lore_blocks,
        )

        depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
        # Official V4 immersion marker: only when toggled on + thinking enabled.
        base_url, api_key, model = _resolve_guild_endpoint(guild_settings, settings)
        if bool(guild_settings.llm_immersion) and depth != "off" and supports_thinking(
            base_url
        ):
            apply_immersion_marker(messages)
        raw = await self.llm.chat(
            system=system,
            messages=messages,
            model=model,
            depth=depth,
            last_reply=last_assistant_reply or None,
            api_key=api_key,
            base_url=base_url,
        )
        result = self.llm.parse_result(raw)
        result.reply = scrub_score_leak(result.reply)

        # Final guard: still duplicated after retries → local soft line, no more API.
        used_soft_fallback = False
        if (
            last_assistant_reply
            and not is_soft_fallback(last_assistant_reply)
            and is_near_duplicate(result.reply, last_assistant_reply)
        ):
            result.reply = soft_fallback_reply(user_id ^ guild_id)
            result.emotion = "flustered"
            result.trigger_cg = False
            result.cg_tier = "none"
            result.cg_scene = None
            result.image_prompt = None
            used_soft_fallback = True
        elif is_soft_fallback(result.reply):
            used_soft_fallback = True

        await self.repo.add_message(
            guild_id=guild_id,
            role="user",
            content=text or "（呼叫）",
            user_id=user_id,
            display_name=display_name,
            character_id=self.character_id,
        )
        # Do not persist canned soft-fallbacks — they poison memory and feel ice-cold.
        if not used_soft_fallback:
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
                "pending_cg": None,
            }

        # Shared guild affection — never shown in reply text.
        bond = await self.repo.get_or_create_bond(guild_id, self.character_id)
        old_affection = int(bond.affection)
        breakdown = await self.scorer.compute(
            guild_id=guild_id,
            user_id=user_id,
            user_text=text or "",
            llm_delta=0,
            score_tags=[],
            emotion=result.emotion,
        )
        new_affection = await self.scorer.apply(
            guild_id=guild_id,
            user_id=user_id,
            current_affection=old_affection,
            breakdown=breakdown,
            emotion=result.emotion,
        )

        threshold = self._cg_threshold(guild_settings)
        score_unlock = new_affection >= threshold >= 1
        pending_cg = None
        if score_unlock:
            allow_cg, tier = await self._cg_policy(
                guild_id=guild_id,
                trigger=True,
                requested_tier="normal",
                bypass_cooldown=False,
            )
            if allow_cg:
                pending_cg = await self._queue_cg_from_context(
                    guild_id=guild_id,
                    user_id=user_id,
                    guild_settings=guild_settings,
                    result=result,
                    messages=messages,
                    tier=tier,
                )
                if pending_cg:
                    # Spend threshold; leftover carries over. Silent — no chat announce.
                    spent = new_affection - threshold
                    await self.repo.update_bond(
                        guild_id,
                        affection=spent,
                        emotion=result.emotion,
                        character_id=self.character_id,
                    )
                    await self.repo.add_score_event(
                        guild_id=guild_id,
                        category="milestone",
                        amount=-threshold,
                        reason=f"達到門檻 {threshold} 兌換 CG",
                        user_id=user_id,
                        character_id=self.character_id,
                    )

        return {
            "reply": result.reply,
            "emotion": result.emotion,
            "image_path": None,
            "pending_cg": pending_cg,
        }

    def _cg_threshold(self, guild_settings) -> int:
        raw = getattr(guild_settings, "cg_score_threshold", None)
        if raw is None or int(raw) <= 0:
            scoring = (self.character.get("scoring") or {})
            return max(1, min(100, int(scoring.get("cg_threshold_default", 30))))
        return max(1, min(100, int(raw)))

    def _has_cg_keywords(self, result) -> bool:
        scene_dump = result.cg_scene.model_dump() if result.cg_scene else None
        if (result.image_prompt or "").strip():
            return True
        if scene_dump and any(
            (scene_dump.get(k) or "").strip()
            for k in ("location", "time", "action", "expression", "mood")
        ):
            return True
        return False

    async def _queue_cg_from_context(
        self,
        *,
        guild_id: int,
        user_id: int,
        guild_settings,
        result,
        messages: list[dict[str, str]],
        tier: str,
    ) -> dict | None:
        settings = get_settings()
        effective_url = (
            (guild_settings.sd_webui_url or "").strip()
            or (settings.sd_webui_url or "").strip()
        )
        if not effective_url:
            return None

        # Score-unlock / force CG must match THIS reply's beat.
        # Chat-turn image_prompt is often null (trigger_cg=false) or generic office.
        image_prompt = await self._infer_image_prompt(
            messages,
            result.reply,
            guild_settings=guild_settings,
        )
        scene_dump = None
        if not (image_prompt or "").strip():
            image_prompt = heuristic_image_tags(result.reply, result.emotion)
        if not (image_prompt or "").strip() and self._has_cg_keywords(result):
            image_prompt = result.image_prompt
            scene_dump = result.cg_scene.model_dump() if result.cg_scene else None
        if not (image_prompt or "").strip() and not scene_dump:
            # Last resort: still bias toward the reply emotion, not a frozen audit pose.
            scene_dump = {
                "location": "millennium student council office, desk",
                "time": "afternoon",
                "action": "sitting at desk, reacting to teacher",
                "expression": result.emotion or "neutral",
                "mood": "soft indoor light",
            }
        prompt = build_image_prompt(
            scene_dump,
            self.character_id,
            image_prompt=image_prompt,
        )
        return {
            "prompt": prompt,
            "tier": tier,
            "emotion": result.emotion,
            "triggered_by_user_id": user_id,
            "base_url": guild_settings.sd_webui_url or None,
        }

    async def _infer_image_prompt(
        self,
        messages: list[dict[str, str]],
        reply: str,
        *,
        guild_settings=None,
    ) -> str | None:
        """Ask LLM for English SD tags from the latest assistant beat."""
        snippet = []
        for m in messages[-4:]:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role and content:
                snippet.append(f"{role}: {content[:180]}")
        snippet.append(f"assistant_latest: {reply[:400]}")
        system = (
            "只輸出合法 JSON（不要 markdown）："
            '{"reply":".","emotion":"neutral","trigger_cg":true,"cg_tier":"normal",'
            '"cg_scene":null,"image_prompt":"english danbooru tags"}。'
            "image_prompt 必須緊扣 assistant_latest 這一則畫面："
            "道具（紙杯／拿鐵／表單等）、動作（接過／碰手／縮手）、表情都要出現。"
            "禁止偷換成無關的『托腮看鏡頭／只有計算機對帳』，除非最新對白真的在對帳。"
            "禁止中文、禁止 NSFW、禁止解釋；8～20 個英文短標籤。"
        )
        settings = get_settings()
        api_key = None
        base_url = None
        model = None
        if guild_settings is not None:
            base_url, api_key, model = _resolve_guild_endpoint(guild_settings, settings)
        try:
            raw = await self.llm.chat(
                system=system,
                messages=[
                    {
                        "role": "user",
                        "content": "對話摘要：\n" + "\n".join(snippet),
                    }
                ],
                depth="off",
                model=model,
                api_key=api_key,
                base_url=base_url,
            )
            parsed = self.llm.parse_result(raw)
            if parsed.image_prompt:
                return parsed.image_prompt
        except Exception:
            return None
        return None

    async def fulfill_cg(
        self,
        *,
        guild_id: int,
        pending_cg: dict,
    ) -> str | None:
        """Run SD txt2img for a pending job; returns image path or None."""
        prompt = pending_cg.get("prompt") or ""
        if not prompt.strip():
            return None
        image_path = await self.webui.generate(
            prompt=prompt,
            tier=str(pending_cg.get("tier") or "normal"),
            guild_id=guild_id,
            base_url=pending_cg.get("base_url"),
        )
        if image_path:
            await self.repo.add_gallery(
                guild_id=guild_id,
                path=str(image_path),
                prompt=prompt,
                tier=str(pending_cg.get("tier") or "normal"),
                emotion=str(pending_cg.get("emotion") or "neutral"),
                triggered_by_user_id=int(pending_cg.get("triggered_by_user_id") or 0),
                character_id=self.character_id,
            )
        return str(image_path) if image_path else None

    async def _cg_policy(
        self,
        *,
        guild_id: int,
        trigger: bool,
        requested_tier: str,
        bypass_cooldown: bool = False,
    ) -> tuple[bool, str]:
        settings = get_settings()
        if not trigger:
            return False, "none"

        now = datetime.now(timezone.utc)
        if not bypass_cooldown:
            last = await self.repo.last_gallery_at(guild_id, self.character_id)
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last).total_seconds() < settings.cg_cooldown_seconds:
                    return False, "none"

        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_items = await self.repo.gallery_since(guild_id, day_start, self.character_id)
        if len(today_items) >= settings.cg_daily_limit and not bypass_cooldown:
            return False, "none"

        tier = "special" if requested_tier == "special" else "normal"
        return True, tier

    async def describe_score(self, guild_id: int) -> str:
        bond = await self.repo.get_or_create_bond(guild_id, self.character_id)
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        threshold = self._cg_threshold(guild_settings)
        return (
            f"本伺服器共用好感：`{bond.affection}/100`\n"
            f"自動生圖門檻：`{threshold}`（達到後依當下對話產關鍵字並出圖，並扣除門檻分數）\n"
            f"目前情緒標記：`{bond.emotion}`\n"
            "對話裡不會顯示分數；查詢請用本指令。"
        )

    async def set_score_threshold(self, guild_id: int, value: int) -> str:
        n = max(1, min(100, int(value)))
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.cg_score_threshold = n
        await self.repo.save_settings(guild_settings)
        return f"已設定自動生圖門檻為 `{n}`（僅管理者可改）。"

    async def set_affection(self, guild_id: int, value: int) -> str:
        n = max(0, min(100, int(value)))
        await self.repo.update_bond(
            guild_id, affection=n, character_id=self.character_id
        )
        return f"已將本伺服器共用好感設為 `{n}`（僅管理者可改）。"

    async def force_cg_from_memory(self, guild_id: int, user_id: int) -> dict:
        """Owner-only: build CG keywords from recent memory and generate."""
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        history = await self.repo.recent_messages(
            guild_id, limit=settings.memory_limit, character_id=self.character_id
        )
        messages: list[dict[str, str]] = []
        last_reply = "（抬起頭，看向老師）"
        for m in history:
            if m.role == "user":
                messages.append(
                    {
                        "role": "user",
                        "content": _user_message_payload(
                            user_id=m.user_id, text=m.content
                        ),
                    }
                )
            else:
                messages.append({"role": "assistant", "content": m.content})
                last_reply = m.content or last_reply

        class _Tmp:
            reply = last_reply
            emotion = "neutral"
            image_prompt = None
            cg_scene = None

        allow_cg, tier = await self._cg_policy(
            guild_id=guild_id,
            trigger=True,
            requested_tier="normal",
            bypass_cooldown=True,
        )
        if not allow_cg:
            return {
                "reply": "今日生圖次數已滿，無法強制出圖。",
                "emotion": "neutral",
                "image_path": None,
            }

        pending = await self._queue_cg_from_context(
            guild_id=guild_id,
            user_id=user_id,
            guild_settings=guild_settings,
            result=_Tmp(),
            messages=messages,
            tier=tier,
        )
        if not pending:
            return {
                "reply": "沒有可用的生圖網址。請先 `/image url` 或設定 SD_WEBUI_URL。",
                "emotion": "neutral",
                "image_path": None,
            }
        path = await self.fulfill_cg(guild_id=guild_id, pending_cg=pending)
        if not path:
            return {
                "reply": "強制生圖失敗（WebUI 無回應或逾時）。",
                "emotion": "neutral",
                "image_path": None,
            }
        return {
            "reply": "強制生圖完成（依近期對話記憶產關鍵字）。",
            "emotion": "neutral",
            "image_path": path,
        }

    async def describe_llm(self, guild_id: int) -> str:
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        base_url, api_key, model = _resolve_guild_endpoint(guild_settings, settings)
        depth = resolve_depth(guild_settings.llm_depth, settings.deepseek_depth)
        immersion = "開" if guild_settings.llm_immersion else "關"
        provider = detect_provider(base_url)
        preset = get_preset(provider)
        label = preset.label if preset else provider
        has_guild_base = bool((guild_settings.llm_api_base_url or "").strip())
        has_guild_key = bool((guild_settings.llm_api_key or "").strip())
        has_guild_model = bool((guild_settings.llm_model or "").strip())
        if has_guild_base or has_guild_key:
            override = "伺服器 /api 覆寫"
        else:
            override = f".env LLM_PROVIDER=`{normalize_provider_id(settings.llm_provider)}`"
        key_src = _key_source_label(guild_settings, settings, provider)
        model_src = "伺服器 /model" if has_guild_model else f".env（{provider} 預設）"
        note = ""
        if guild_settings.llm_immersion and (
            depth == "off" or not supports_thinking(base_url)
        ):
            note = (
                "\n⚠ 沉浸需 DeepSeek + depth≠off 才會注入；"
                f"目前 provider=`{provider}` depth=`{depth}`。"
            )
        return (
            f"**{label}**（`{provider}`）· {override}\n"
            f"base=`{base_url}`\n"
            f"key=`{mask_api_key(api_key)}` ← {key_src}\n"
            f"model=`{model}` ← {model_src}\n"
            f"depth=`{depth}` 沉浸=`{immersion}`\n"
            f"{model_menu_lines(provider)}\n"
            "切換：`/api switch`（推薦）· `/api help` · `/model` · `/depth`"
            f"{note}"
        )

    async def api_help(self) -> str:
        profiles = "\n".join(f"· `{p.label}`" for p in SWITCH_PROFILES.values())
        return (
            "**LLM API 怎麼切**\n"
            "1. `.env` 可同時填 `DEEPSEEK_API_KEY`、`GEMINI_API_KEY`、`OPENAI_API_KEY`\n"
            "2. Discord 用 `/api switch` 一次選好廠商＋模型（會改用對應 .env 金鑰）\n"
            "3. `/api test` 確認連線；`/api status` 看目前狀態\n"
            "4. 只改同廠商模型可用 `/model`（flash／pro／lite）\n"
            "5. `/api clear` 清掉伺服器覆寫，改回 `.env` 的 `LLM_PROVIDER`\n\n"
            f"**`/api switch` 選項：**\n{profiles}\n\n"
            "進階：`/api preset`、`/api url`、`/api key`、`/api model`"
        )

    async def set_model(self, guild_id: int, arg: str) -> str:
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        base_url, _, _ = _resolve_guild_endpoint(guild_settings, settings)
        provider = detect_provider(base_url)
        raw = (arg or "").strip()
        if not raw:
            return (
                f"目前廠商 `{provider}`。請指定模型 id，或別名。\n"
                f"{model_menu_lines(provider)}\n"
                "換廠商請用 `/api switch`。"
            )
        # Prefer provider-aware aliases; fall back to legacy DeepSeek parse.
        resolved = resolve_model_name(raw, "", base_url=base_url)
        if not resolved:
            parsed = parse_model_arg(raw)
            if parsed is None:
                return (
                    f"目前廠商 `{provider}`，無法辨識 `{raw}`。\n"
                    f"{model_menu_lines(provider)}\n"
                    "或用 `/api switch` 一次切廠商＋模型。"
                )
            resolved = parsed
        guild_settings.llm_model = resolved
        await self.repo.save_settings(guild_settings)
        return (
            f"已切換模型為 `{resolved}`（廠商仍為 `{provider}`）。\n"
            "若要換 Gemini／DeepSeek／OpenAI，請用 `/api switch`。"
        )

    async def set_api_switch(self, guild_id: int, profile_id: str) -> str:
        profile = get_switch_profile(profile_id)
        if profile is None:
            names = "、".join(f"`{k}`" for k in SWITCH_PROFILES)
            return f"未知選項。可用：{names}。或看 `/api help`。"
        preset = get_preset(profile.provider_id)
        if preset is None:
            return "內部錯誤：preset 不存在。"
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.llm_api_base_url = preset.base_url
        guild_settings.llm_model = profile.model
        # Drop guild key so the matching .env slot is used for this provider.
        guild_settings.llm_api_key = ""
        await self.repo.save_settings(guild_settings)
        key, env_name = api_key_for_provider(
            preset.id,
            deepseek_api_key=settings.deepseek_api_key,
            gemini_api_key=settings.gemini_api_key,
            openai_api_key=settings.openai_api_key,
        )
        tip = (
            f"\n金鑰：已改用 `.env` `{env_name}` → `{mask_api_key(key)}`"
            if key
            else (
                f"\n⚠ `.env` 尚未設定 `{env_name}`。"
                f"請寫入後重啟 bot，或執行 `/api key`。"
            )
        )
        return (
            f"已切換：**{profile.label}**\n"
            f"provider=`{preset.id}` model=`{profile.model}`\n"
            f"base=`{preset.base_url}`"
            f"{tip}\n"
            "建議下一步：`/api test`"
        )

    async def set_api_preset(self, guild_id: int, preset_id: str) -> str:
        preset = get_preset(preset_id)
        if preset is None:
            names = "、".join(f"`{k}`" for k in PRESETS)
            return (
                f"可用 preset：{names}。\n"
                "更清楚請用 `/api switch`（一次選廠商＋模型）。"
            )
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.llm_api_base_url = preset.base_url
        guild_settings.llm_model = preset.default_model
        guild_settings.llm_api_key = ""
        await self.repo.save_settings(guild_settings)
        key, env_name = api_key_for_provider(
            preset.id,
            deepseek_api_key=settings.deepseek_api_key,
            gemini_api_key=settings.gemini_api_key,
            openai_api_key=settings.openai_api_key,
        )
        tip = (
            f"\n金鑰：`.env` `{env_name}` → `{mask_api_key(key)}`"
            if key
            else f"\n⚠ 請在 `.env` 填 `{env_name}`，或 `/api key`。"
        )
        return (
            f"已切到 **{preset.label}**（預設模型）。\n"
            f"base=`{preset.base_url}`\n"
            f"model=`{preset.default_model}`"
            f"{tip}\n"
            f"同廠商換模型：`/model`（{model_menu_lines(preset.id)}）\n"
            "或用 `/api switch` 一次選好。"
        )

    async def set_api_url(self, guild_id: int, url_raw: str) -> str:
        try:
            url = normalize_base_url(url_raw)
        except ValueError as exc:
            return str(exc)
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.llm_api_base_url = url
        await self.repo.save_settings(guild_settings)
        return (
            f"已設定 API base=`{url}`（provider=`{detect_provider(url)}`）。\n"
            "記得 `/api key` 與 `/api model`（或 `/model`）。"
        )

    async def set_api_key(self, guild_id: int, key_raw: str) -> str:
        key = (key_raw or "").strip()
        if not key:
            return "金鑰不可空白。"
        if len(key) > 512:
            return "金鑰過長，請確認是否貼錯。"
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.llm_api_key = key
        await self.repo.save_settings(guild_settings)
        return f"已儲存本伺服器 API 金鑰：`{mask_api_key(key)}`（不會在公開頻道顯示全文）。"

    async def set_api_model(self, guild_id: int, model_raw: str) -> str:
        return await self.set_model(guild_id, model_raw)

    async def clear_api_override(self, guild_id: int) -> str:
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        guild_settings.llm_api_base_url = ""
        guild_settings.llm_api_key = ""
        guild_settings.llm_model = ""
        await self.repo.save_settings(guild_settings)
        pid = normalize_provider_id(settings.llm_provider)
        return (
            "已清除本伺服器 API／模型覆寫。\n"
            f"改回 `.env`：`LLM_PROVIDER={pid}`"
            f"（金鑰用對應的 `DEEPSEEK_API_KEY`／`GEMINI_API_KEY`／`OPENAI_API_KEY`）。"
        )

    async def test_api(self, guild_id: int) -> str:
        settings = get_settings()
        guild_settings = await self.repo.get_or_create_settings(guild_id)
        base_url, api_key, model = _resolve_guild_endpoint(guild_settings, settings)
        system = (
            '只輸出合法 JSON：{"reply":"OK","emotion":"neutral","trigger_cg":false,'
            '"cg_tier":"none","cg_scene":null,"image_prompt":null}'
        )
        try:
            raw = await self.llm.chat(
                system=system,
                messages=[{"role": "user", "content": "[老師測試] 只回覆 OK"}],
                model=model,
                depth="off",
                api_key=api_key,
                base_url=base_url,
            )
            parsed = self.llm.parse_result(raw)
            soft = "（soft fallback）" if is_soft_fallback(parsed.reply) else ""
            return (
                f"測試完成{soft}。\n"
                f"provider=`{detect_provider(base_url)}` model=`{model}`\n"
                f"reply=`{parsed.reply[:120]}`"
            )
        except Exception as exc:
            return f"測試失敗：`{type(exc).__name__}: {exc}`"

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
        prompt = build_image_prompt(scene, self.character_id, image_prompt=None)
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
