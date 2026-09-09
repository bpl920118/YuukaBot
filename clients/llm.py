from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from config import get_settings
from core.llm_options import resolve_depth
from core.providers import (
    PRESETS,
    api_key_for_provider,
    chat_completions_url,
    detect_provider,
    resolve_model_name,
    supports_thinking,
)
from core.schemas import LlmChatResult, is_soft_fallback, soft_fallback_reply


logger = logging.getLogger(__name__)

_PARSE_FALLBACK = (
    "（敲了兩下計算機）……剛才那則我沒讀完整。老師再說一次？"
    "我聽著——審核先暫停一下。"
)
_AUTH_FALLBACK = (
    "……計算機連不上帳本伺服器：API 金鑰無效或過期（HTTP 401／403）。"
    "請用 `/api status` 檢查網址與金鑰，或改 `/api switch`。"
)
_RETRY_NUDGE = (
    "[系統] 上一則輸出無效。請重新只輸出合法 JSON；"
    "reply 必須是繁體中文、至少兩個字、且不得與上一則對白相同。"
)
_MISSING_KEY_REPLY = (
    "老師……API 金鑰還沒設定，但我先在這裡應答。請用 `/api key` 或填 `.env`。"
)
# Empty HTTP-200 content: brief backoff before rehitting the same (or backup) provider.
_EMPTY_BACKOFFS_SEC = (0.4, 1.0, 2.0)
_EMPTY_BEFORE_FAILOVER = 2
_MAX_ATTEMPTS = 4
_USAGE_LOG_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "reasoning_tokens",
)

_THINK_RE = re.compile(
    r"<think>.*?</think>",
    re.DOTALL | re.IGNORECASE,
)


def _strip_think_blocks(text: str) -> str:
    """Qwen3／部分本地模會先吐 think；剝掉再解析 JSON。"""
    raw = text or ""
    cleaned = _THINK_RE.sub("", raw)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>")[-1]
    if "<think>" in cleaned:
        cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _normalize_reply(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def is_near_duplicate(a: str, b: str) -> bool:
    """True when replies are identical or one is a near-copy of the other."""
    na, nb = _normalize_reply(a), _normalize_reply(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) < 12:
        return False
    if shorter in longer and abs(len(na) - len(nb)) <= max(24, len(shorter) // 3):
        return True
    return False


def _chat_result_json(
    reply: str,
    *,
    emotion: str = "neutral",
) -> str:
    return json.dumps(
        {
            "reply": reply,
            "emotion": emotion,
            "trigger_cg": False,
            "cg_tier": "none",
            "cg_scene": None,
            "image_prompt": None,
        },
        ensure_ascii=False,
    )


def _salvage_reply_field(raw: str) -> dict[str, Any] | None:
    """Pull a usable reply out of near-JSON when full parse fails."""
    text = (raw or "").strip()
    if not text:
        return None
    match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if not match:
        return None
    try:
        reply = json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        reply = match.group(1)
    reply = (reply or "").strip()
    if len(reply) < 2:
        return None
    return {
        "reply": reply[:2500],
        "emotion": "neutral",
        "trigger_cg": False,
        "cg_tier": "none",
        "cg_scene": None,
        "image_prompt": None,
    }


def _parts_to_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks).strip()
    return ""


def _coerce_message_text(message: dict[str, Any]) -> str:
    """
    Prefer message.content. DeepSeek thinking mode often leaves content empty
    and spends the token budget on reasoning_content (finish_reason=length).
    """
    content = _strip_think_blocks(_parts_to_text(message.get("content")))
    if content:
        return content

    for key in ("reasoning_content", "reasoning"):
        reasoning = _strip_think_blocks(_parts_to_text(message.get(key)))
        if not reasoning:
            continue
        salvaged = _salvage_reply_field(reasoning)
        if salvaged:
            logger.info("LLM salvaged reply from %s", key)
            return json.dumps(salvaged, ensure_ascii=False)
        stripped = reasoning.strip()
        if stripped.startswith("{") and '"reply"' in stripped:
            return stripped
    return ""


def _message_has_reasoning(message: dict[str, Any]) -> bool:
    for key in ("reasoning_content", "reasoning"):
        if _parts_to_text(message.get(key)):
            return True
    return False


def _usage_for_log(usage: dict[str, Any]) -> dict[str, Any]:
    slim = {k: usage[k] for k in _USAGE_LOG_KEYS if k in usage}
    return slim or usage


def _empty_backoff_seconds(empty_count: int) -> float:
    """empty_count is 1-based streak of empty content replies this turn."""
    idx = max(0, min(empty_count - 1, len(_EMPTY_BACKOFFS_SEC) - 1))
    return _EMPTY_BACKOFFS_SEC[idx]


def _gemini_hot_failover(
    settings,
    *,
    primary_base: str,
) -> tuple[str, str, str] | None:
    """
    Per-turn Gemini backup when primary returns empty content.
    Returns (base_url, api_key, model) or None if unavailable / already Gemini / home.
    """
    from core.home_llm import is_home_inference_url

    if is_home_inference_url(primary_base):
        return None
    if detect_provider(primary_base) == "gemini":
        return None
    key, _ = api_key_for_provider(
        "gemini",
        deepseek_api_key=settings.deepseek_api_key,
        gemini_api_key=settings.gemini_api_key,
        openai_api_key=settings.openai_api_key,
    )
    if not key:
        return None
    preset = PRESETS["gemini"]
    model = (settings.gemini_model or preset.default_model).strip()
    return preset.base_url.rstrip("/"), key, model


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _build_chat_payload(
    *,
    model: str,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    top_p: float,
    base_url: str,
    depth: str,
    thinking_ok: bool,
) -> tuple[dict[str, Any], bool]:
    """Return (payload, thinking_on)."""
    from core.home_llm import should_omit_json_response_format

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
    }
    if not should_omit_json_response_format(base_url):
        payload["response_format"] = {"type": "json_object"}

    thinking_on = thinking_ok and depth != "off"
    if thinking_ok:
        if thinking_on:
            payload["max_tokens"] = max(max_tokens, 768) + 2048
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = depth  # high | max
            payload.pop("temperature", None)
            payload.pop("top_p", None)
        else:
            payload["thinking"] = {"type": "disabled"}
    return payload, thinking_on


def _with_thinking_disabled(
    payload: dict[str, Any],
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
) -> dict[str, Any]:
    out = {
        **payload,
        "thinking": {"type": "disabled"},
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
    }
    out.pop("reasoning_effort", None)
    return out


def _nudge_messages(base_messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [*base_messages, {"role": "user", "content": _RETRY_NUDGE}]


@dataclass
class _Endpoint:
    base_url: str
    api_key: str
    model: str
    provider: str
    url: str
    headers: dict[str, str]
    timeout: float
    thinking_ok: bool
    thinking_on: bool


class LlmClient:
    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.deepseek_api_key
        self.base_url = s.deepseek_base_url.rstrip("/")
        self.model = s.deepseek_model
        self.depth = s.deepseek_depth

    @staticmethod
    def _resolve_sampling(
        settings,
        *,
        base_url: str,
        temperature: float | None,
        top_p: float | None,
        max_tokens: int | None,
        sampling_profile: str,
        is_home: bool,
    ) -> tuple[float, float, int]:
        profile = (sampling_profile or "chat").strip().lower()
        if profile == "momotalk":
            temp = settings.momotalk_temperature
            top = settings.momotalk_top_p
            mx = settings.momotalk_max_tokens
        elif is_home:
            temp = settings.home_llm_temperature
            top = settings.home_llm_top_p
            mx = settings.llm_max_tokens
        else:
            temp = settings.llm_temperature
            top = settings.llm_top_p
            mx = settings.llm_max_tokens
        if temperature is not None:
            temp = float(temperature)
        if top_p is not None:
            top = float(top_p)
        if max_tokens is not None:
            mx = int(max_tokens)
        return temp, top, max(32, mx)

    async def chat(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        depth: str | None = None,
        last_reply: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        sampling_profile: str = "chat",
    ) -> str:
        use_key = ((api_key if api_key is not None else self.api_key) or "").strip()
        use_base = ((base_url if base_url is not None else self.base_url) or "").strip().rstrip(
            "/"
        ) or self.base_url
        from core.home_llm import home_api_key_or_placeholder, is_home_inference_url

        use_key = home_api_key_or_placeholder(use_key, use_base)
        if not use_key:
            return _chat_result_json(_MISSING_KEY_REPLY)

        use_model = resolve_model_name(model, self.model, base_url=use_base)
        use_depth = resolve_depth(depth, self.depth)
        settings = get_settings()
        thinking_ok = supports_thinking(use_base)
        use_temp, use_top_p, use_max = self._resolve_sampling(
            settings,
            base_url=use_base,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            sampling_profile=sampling_profile,
            is_home=is_home_inference_url(use_base),
        )

        # Soft-fallback lines in memory must not trigger near-duplicate rejection.
        effective_last = (
            None if (last_reply and is_soft_fallback(last_reply)) else last_reply
        )

        payload, thinking_on = _build_chat_payload(
            model=use_model,
            system=system,
            messages=messages,
            max_tokens=use_max,
            temperature=use_temp,
            top_p=use_top_p,
            base_url=use_base,
            depth=use_depth,
            thinking_ok=thinking_ok,
        )
        ep = _Endpoint(
            base_url=use_base,
            api_key=use_key,
            model=use_model,
            provider=detect_provider(use_base),
            url=chat_completions_url(use_base),
            headers=_auth_headers(use_key),
            timeout=180.0 if thinking_on else 90.0,
            thinking_ok=thinking_ok,
            thinking_on=thinking_on,
        )
        failover = _gemini_hot_failover(settings, primary_base=use_base)

        last_raw = ""
        auth_failed = False
        failed_over = False
        forced_no_think = False
        empty_count = 0
        working_messages = list(payload["messages"])

        for attempt in range(_MAX_ATTEMPTS):
            attempt_payload = {**payload, "messages": working_messages}
            if forced_no_think and ep.thinking_ok:
                attempt_payload = _with_thinking_disabled(
                    attempt_payload,
                    max_tokens=use_max,
                    temperature=use_temp,
                    top_p=use_top_p,
                )
            try:
                last_raw = await self._post_once(
                    ep.url,
                    ep.headers,
                    attempt_payload,
                    ep.timeout,
                    provider=ep.provider,
                    model=str(attempt_payload.get("model") or ep.model),
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                logger.warning("LLM HTTP attempt %s failed: %s", attempt + 1, exc)
                if status in {401, 403}:
                    auth_failed = True
                    break
                working_messages = _nudge_messages(payload["messages"])
                continue
            except Exception as exc:
                logger.warning("LLM HTTP attempt %s failed: %s", attempt + 1, exc)
                working_messages = _nudge_messages(payload["messages"])
                continue

            if not (last_raw or "").strip():
                empty_count += 1
                logger.warning(
                    "LLM empty content on attempt %s empty_streak=%s provider=%s model=%s",
                    attempt + 1,
                    empty_count,
                    ep.provider,
                    ep.model,
                )
                # Thinking ate the token budget → one hard retry with thinking off.
                if ep.thinking_on and not forced_no_think:
                    forced_no_think = True
                    logger.warning(
                        "LLM retrying with thinking disabled after empty content"
                    )
                    continue
                if attempt < _MAX_ATTEMPTS - 1:
                    delay = _empty_backoff_seconds(empty_count)
                    logger.info("LLM empty backoff %.1fs before retry", delay)
                    await asyncio.sleep(delay)
                if (
                    empty_count >= _EMPTY_BEFORE_FAILOVER
                    and not failed_over
                    and failover is not None
                ):
                    fb_base, fb_key, fb_model = failover
                    payload, _ = _build_chat_payload(
                        model=fb_model,
                        system=system,
                        messages=messages,
                        max_tokens=use_max,
                        temperature=use_temp,
                        top_p=use_top_p,
                        base_url=fb_base,
                        depth="off",
                        thinking_ok=False,
                    )
                    ep = _Endpoint(
                        base_url=fb_base,
                        api_key=fb_key,
                        model=fb_model,
                        provider=detect_provider(fb_base),
                        url=chat_completions_url(fb_base),
                        headers=_auth_headers(fb_key),
                        timeout=90.0,
                        thinking_ok=False,
                        thinking_on=False,
                    )
                    forced_no_think = False
                    failed_over = True
                    working_messages = list(payload["messages"])
                    logger.warning(
                        "LLM empty-content failover → %s model=%s after %s empty",
                        ep.provider,
                        ep.model,
                        empty_count,
                    )
                    continue
                working_messages = _nudge_messages(payload["messages"])
                continue

            try:
                data = self._extract_json(last_raw)
                result = LlmChatResult.model_validate(data)
                if effective_last and is_near_duplicate(result.reply, effective_last):
                    raise ValueError("near-duplicate reply")
                if failed_over:
                    logger.info(
                        "LLM failover reply ok provider=%s model=%s",
                        ep.provider,
                        ep.model,
                    )
                return json.dumps(result.model_dump(), ensure_ascii=False)
            except Exception as exc:
                salvaged = _salvage_reply_field(last_raw)
                if salvaged:
                    try:
                        result = LlmChatResult.model_validate(salvaged)
                        if not (
                            effective_last
                            and is_near_duplicate(result.reply, effective_last)
                        ):
                            logger.info(
                                "LLM salvaged reply field on attempt %s", attempt + 1
                            )
                            return json.dumps(result.model_dump(), ensure_ascii=False)
                    except Exception:
                        pass
                logger.warning("LLM parse attempt %s failed: %s", attempt + 1, exc)
                if ep.thinking_on and not forced_no_think:
                    forced_no_think = True
                    logger.warning(
                        "LLM retrying with thinking disabled after parse failure"
                    )
                    continue
                working_messages = [
                    *payload["messages"],
                    {"role": "assistant", "content": last_raw[:800]},
                    {"role": "user", "content": _RETRY_NUDGE},
                ]
                continue

        # Local soft fallback — avoid hammering API or looping "計算機跳了".
        logger.error(
            "LLM soft-fallback after retries; auth_failed=%s failed_over=%s "
            "empty_streak=%s provider=%s last_raw=%r",
            auth_failed,
            failed_over,
            empty_count,
            ep.provider,
            (last_raw or "")[:200],
        )
        fallback = (
            _AUTH_FALLBACK
            if auth_failed
            else soft_fallback_reply(hash(last_raw or last_reply or "") & 0xFFFF)
        )
        return _chat_result_json(fallback, emotion="flustered")

    async def _post_once(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
        *,
        provider: str = "",
        model: str = "",
    ) -> str:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        choice = choices[0] if choices else {}
        message = choice.get("message") or {}
        msg = message if isinstance(message, dict) else {}
        text = _coerce_message_text(msg)
        if not text:
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            logger.warning(
                "LLM blank message fields; provider=%s model=%s finish_reason=%r "
                "choices=%s usage=%s has_reasoning=%s content_empty=%s msg_keys=%s",
                provider or "?",
                model or payload.get("model") or "",
                choice.get("finish_reason"),
                len(choices),
                _usage_for_log(usage),
                _message_has_reasoning(msg),
                not bool(_parts_to_text(msg.get("content"))),
                sorted(msg.keys()),
            )
        return text

    def parse_result(self, raw: str) -> LlmChatResult:
        try:
            return LlmChatResult.model_validate(self._extract_json(raw))
        except Exception:
            salvaged = _salvage_reply_field(raw)
            if salvaged:
                try:
                    return LlmChatResult.model_validate(salvaged)
                except Exception:
                    pass
            text = (raw or "").strip()
            if text and not text.startswith("{"):
                return LlmChatResult(reply=text[:2500], emotion="neutral")
            return LlmChatResult(reply=_PARSE_FALLBACK, emotion="flustered")

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        raw = _strip_think_blocks(raw)
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))
