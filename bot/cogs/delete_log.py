from __future__ import annotations

import os
from collections import OrderedDict, defaultdict, deque
from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands


def _env_int(name: str, default: int = 0) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        try:
            from pathlib import Path

            for line in Path("/workspace/YuukaBot/.env").read_text().splitlines():
                if line.startswith(name + "="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


SOURCE_GUILD_ID = _env_int("DELETE_LOG_SOURCE_GUILD_ID", 993187835693764638)
DEST_CHANNEL_ID = _env_int("DELETE_LOG_DEST_CHANNEL_ID", 1551525766913589351)
CONTEXT_COUNT = _env_int("DELETE_LOG_CONTEXT_COUNT", 6)
CACHE_MAX = 2000
CHANNEL_CTX_MAX = 40


def _short(text: str, limit: int = 120) -> str:
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return "（無文字）"
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


class DeleteLogCog(commands.Cog):
    """Watch deletes in one guild; mirror to a log channel with prior context."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cache: OrderedDict[int, dict[str, Any]] = OrderedDict()
        # channel_id -> recent messages (including bots) for local context fallback
        self._channel_ctx: dict[int, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=CHANNEL_CTX_MAX)
        )

    def _ctx_entry(self, message: discord.Message) -> dict[str, Any]:
        return {
            "id": message.id,
            "author_name": message.author.display_name if message.author else "?",
            "author_bot": bool(message.author and message.author.bot),
            "content": message.content or "",
            "has_attach": bool(message.attachments),
        }

    def _remember(self, message: discord.Message) -> None:
        if message.guild is None or message.guild.id != SOURCE_GUILD_ID:
            return

        # always keep channel context (bots included)
        self._channel_ctx[message.channel.id].append(self._ctx_entry(message))

        if message.author.bot:
            return

        reply_to = None
        if message.reference and message.reference.message_id:
            ref = message.reference.resolved
            if isinstance(ref, discord.Message):
                reply_to = {
                    "id": ref.id,
                    "author_name": ref.author.display_name if ref.author else "?",
                    "content": ref.content or "",
                }
            else:
                reply_to = {"id": message.reference.message_id}

        snap = {
            "id": message.id,
            "channel_id": message.channel.id,
            "channel_name": getattr(message.channel, "name", str(message.channel.id)),
            "author_id": message.author.id,
            "author_tag": str(message.author),
            "author_name": message.author.display_name,
            "content": message.content or "",
            "created_at": message.created_at,
            "attachments": [
                {"filename": a.filename, "url": a.url, "content_type": a.content_type}
                for a in message.attachments
            ],
            "stickers": [s.name for s in message.stickers],
            "reply_to": reply_to,
        }
        self._cache[message.id] = snap
        self._cache.move_to_end(message.id)
        while len(self._cache) > CACHE_MAX:
            self._cache.popitem(last=False)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        self._remember(message)

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if after.guild and after.guild.id == SOURCE_GUILD_ID:
            self._remember(after)

    async def _dest(self) -> discord.TextChannel | None:
        ch = self.bot.get_channel(DEST_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            return ch
        try:
            fetched = await self.bot.fetch_channel(DEST_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
        return fetched if isinstance(fetched, discord.TextChannel) else None

    def _snap_from_message(self, message: discord.Message) -> dict[str, Any]:
        cached = self._cache.pop(message.id, None)
        if cached:
            return cached
        author = message.author
        reply_to = None
        if message.reference and message.reference.message_id:
            reply_to = {"id": message.reference.message_id}
        return {
            "id": message.id,
            "channel_id": message.channel.id if message.channel else 0,
            "channel_name": getattr(message.channel, "name", "?"),
            "author_id": author.id if author else 0,
            "author_tag": str(author) if author else "未知",
            "author_name": (author.display_name if author else "未知"),
            "content": message.content or "",
            "created_at": message.created_at,
            "attachments": [
                {"filename": a.filename, "url": a.url, "content_type": a.content_type}
                for a in (message.attachments or [])
            ],
            "stickers": [s.name for s in (message.stickers or [])],
            "reply_to": reply_to,
            "partial": True,
        }

    async def _collect_context(
        self, message: discord.Message, deleted_id: int
    ) -> list[str]:
        """Return newest-last lines of prior messages for the embed."""
        lines: list[str] = []

        # 1) live history from Discord (best)
        channel = message.channel
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                before = discord.Object(id=deleted_id)
                hist = [
                    m
                    async for m in channel.history(limit=CONTEXT_COUNT, before=before)
                ]
                hist.reverse()  # chronological: older → newer, ending before deleted
                for m in hist:
                    flag = " [bot]" if m.author and m.author.bot else ""
                    body = _short(m.content)
                    if m.attachments:
                        body += f" 📎×{len(m.attachments)}"
                    lines.append(f"**{m.author.display_name}**{flag}: {body}")
            except (discord.Forbidden, discord.HTTPException):
                lines = []

        # 2) fallback: local ring buffer
        if not lines:
            buf = list(self._channel_ctx.get(message.channel.id, ()))
            prior = [e for e in buf if e["id"] < deleted_id][-CONTEXT_COUNT:]
            for e in prior:
                flag = " [bot]" if e.get("author_bot") else ""
                body = _short(e.get("content") or "")
                if e.get("has_attach"):
                    body += " 📎"
                lines.append(f"**{e.get('author_name')}**{flag}: {body}")

        return lines

    async def _send_log(
        self,
        snap: dict[str, Any],
        message: discord.Message,
        *,
        bulk: bool = False,
    ) -> None:
        dest = await self._dest()
        if dest is None:
            return

        content = (snap.get("content") or "").strip()
        if len(content) > 1500:
            content = content[:1500] + "…"
        if not content:
            content = "（無文字內容／機器人未快取到此訊息）"

        created = snap.get("created_at")
        if isinstance(created, datetime):
            created_s = discord.utils.format_dt(created, style="F")
        else:
            created_s = "未知"

        title = "訊息被刪除（批次）" if bulk else "訊息被刪除"
        embed = discord.Embed(
            title=title,
            description=f"**被刪內容**\n{content}",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="作者",
            value=(
                f"{snap.get('author_name')} (`{snap.get('author_tag')}`)\n"
                f"ID `{snap.get('author_id')}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="來源",
            value=(
                f"<#{snap.get('channel_id')}> (`{snap.get('channel_name')}`)\n"
                f"訊息 ID `{snap.get('id')}`"
            ),
            inline=False,
        )
        embed.add_field(name="原發送時間", value=created_s, inline=True)

        reply_to = snap.get("reply_to")
        if reply_to:
            if reply_to.get("content") is not None and "author_name" in reply_to:
                embed.add_field(
                    name="回覆的訊息",
                    value=(
                        f"**{reply_to.get('author_name')}**: "
                        f"{_short(reply_to.get('content') or '', 200)}"
                    ),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="回覆的訊息",
                    value=f"訊息 ID `{reply_to.get('id')}`",
                    inline=False,
                )

        ctx_lines = await self._collect_context(message, int(snap["id"]))
        if ctx_lines:
            ctx_text = "\n".join(ctx_lines)
            if len(ctx_text) > 1000:
                ctx_text = "…\n" + ctx_text[-1000:]
            embed.add_field(
                name=f"上文（前 {len(ctx_lines)} 則）",
                value=ctx_text,
                inline=False,
            )
        else:
            embed.add_field(
                name="上文",
                value="（抓不到前文，可能是頻道權限或太舊）",
                inline=False,
            )

        atts = snap.get("attachments") or []
        if atts:
            lines = [f"[{a['filename']}]({a['url']})" for a in atts[:8]]
            embed.add_field(name="附件", value="\n".join(lines), inline=False)
            for a in atts:
                ct = (a.get("content_type") or "").lower()
                name = (a.get("filename") or "").lower()
                if ct.startswith("image/") or name.endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".webp")
                ):
                    embed.set_image(url=a["url"])
                    break

        stickers = snap.get("stickers") or []
        if stickers:
            embed.add_field(name="貼圖", value=", ".join(stickers), inline=True)

        if snap.get("partial"):
            embed.set_footer(text="部分資訊：刪除前未快取到完整內容")

        try:
            await dest.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            return

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.guild.id != SOURCE_GUILD_ID:
            return
        if message.author and message.author.bot:
            return
        snap = self._snap_from_message(message)
        await self._send_log(snap, message)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        for message in messages:
            if message.guild is None or message.guild.id != SOURCE_GUILD_ID:
                continue
            if message.author and message.author.bot:
                continue
            snap = self._snap_from_message(message)
            await self._send_log(snap, message, bulk=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeleteLogCog(bot))
