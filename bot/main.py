from __future__ import annotations

import re
import time
from pathlib import Path

import discord
from discord.ext import commands

from config import get_settings
from core.pipeline import ChatPipeline
from clients.webui import WebuiClient
from clients.llm import LlmClient
from db.repository import Repository


class YuukaBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = False
        super().__init__(command_prefix="!", intents=intents)
        self.settings = get_settings()
        self.repo = Repository()
        self.pipeline = ChatPipeline(
            self.repo,
            LlmClient(),
            WebuiClient(),
            character_id=self.settings.default_character_id,
        )
        self._user_cooldown: dict[int, float] = {}

    async def setup_hook(self) -> None:
        await self.repo.init()
        await self.load_extension("bot.cogs.status")


def strip_mentions(message: discord.Message, bot_user: discord.ClientUser) -> str:
    content = message.content
    for mention in (bot_user.mention, f"<@{bot_user.id}>", f"<@!{bot_user.id}>"):
        content = content.replace(mention, "")
    return content.strip()


def parse_paren_command(text: str) -> str | None:
    stripped = text.strip()
    if not (stripped.startswith("(") or stripped.startswith("（")):
        return None
    return stripped.lstrip("(（").rstrip(")）").strip()


async def is_reply_to_bot(message: discord.Message, bot_user: discord.ClientUser) -> bool:
    if message.reference is None:
        return False
    ref = message.reference
    if ref.resolved and isinstance(ref.resolved, discord.Message):
        return ref.resolved.author.id == bot_user.id
    if ref.message_id and message.channel:
        try:
            original = await message.channel.fetch_message(ref.message_id)
            return original.author.id == bot_user.id
        except (discord.NotFound, discord.HTTPException):
            return False
    return False


async def maybe_clear_channel_messages(
    bot: YuukaBot, message: discord.Message, text: str, is_teacher: bool
) -> bool:
    """Teacher-only: delete messages already posted in this channel. Returns True if handled."""
    body = parse_paren_command(text)
    if body is None:
        return False

    bot_only = False
    limit = 50
    if body.startswith("清除機器人訊息") or body.startswith("刪除機器人訊息"):
        bot_only = True
        rest = body.replace("清除機器人訊息", "", 1).replace("刪除機器人訊息", "", 1).strip()
    elif body.startswith("清除頻道") or body.startswith("刪除頻道"):
        rest = body.replace("清除頻道", "", 1).replace("刪除頻道", "", 1).strip()
    else:
        return False

    if not is_teacher:
        await message.reply("清除頻道訊息只有老師可以使用。", mention_author=False)
        return True

    if not isinstance(message.channel, discord.TextChannel):
        await message.reply("只能在文字頻道清除訊息。", mention_author=False)
        return True

    if rest:
        m = re.search(r"\d+", rest)
        if m:
            limit = max(1, min(200, int(m.group(0))))

    me = message.guild.me if message.guild else None
    perms = message.channel.permissions_for(me) if me else None

    if bot_only:
        if perms is not None and not (perms.manage_messages or perms.administrator):
            deleted = 0
            async for msg in message.channel.history(limit=limit * 3):
                if bot.user is not None and msg.author.id == bot.user.id:
                    try:
                        await msg.delete()
                        deleted += 1
                    except discord.HTTPException:
                        pass
                    if deleted >= limit:
                        break
            await message.channel.send(f"已刪除機器人訊息約 {deleted} 則。")
            return True
    else:
        if perms is None or not (perms.manage_messages or perms.administrator):
            await message.reply(
                "我沒有「管理訊息」權限，無法大量刪除頻道訊息。"
                "請在邀請／頻道權限幫我勾 Manage Messages。",
                mention_author=False,
            )
            return True

    def check(msg: discord.Message) -> bool:
        if bot_only:
            return bot.user is not None and msg.author.id == bot.user.id
        return True

    try:
        deleted = await message.channel.purge(limit=limit, check=check)
    except discord.Forbidden:
        await message.channel.send("權限不足，無法刪除訊息。")
        return True
    except discord.HTTPException as exc:
        await message.channel.send(f"刪除失敗：`{exc}`")
        return True

    kind = "機器人訊息" if bot_only else "頻道訊息"
    await message.channel.send(
        f"已刪除{kind} {len(deleted)} 則"
        f"（上限 {limit}；超過 14 天的訊息 Discord 不允許批次刪）。"
    )
    return True


async def handle_message(bot: YuukaBot, message: discord.Message) -> None:
    if message.author.bot:
        return
    if message.guild is None:
        return

    assert bot.user is not None
    mentioned = bot.user in message.mentions
    replied = await is_reply_to_bot(message, bot.user)
    if not mentioned and not replied:
        await bot.process_commands(message)
        return

    now = time.monotonic()
    last = bot._user_cooldown.get(message.author.id, 0.0)
    if now - last < bot.settings.user_chat_cooldown_seconds:
        return
    bot._user_cooldown[message.author.id] = now

    text = strip_mentions(message, bot.user)
    is_teacher = message.author.id == bot.settings.teacher_user_id

    if await maybe_clear_channel_messages(bot, message, text, is_teacher):
        await bot.process_commands(message)
        return

    async with message.channel.typing():
        try:
            result = await bot.pipeline.handle(
                guild_id=message.guild.id,
                user_id=message.author.id,
                display_name=message.author.display_name,
                text=text,
                is_teacher=is_teacher,
            )
        except Exception as exc:
            await message.reply(f"……計算出錯了：`{exc}`", mention_author=False)
            return

    files = []
    image_path = result.get("image_path")
    if image_path:
        path = Path(image_path)
        if path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            files.append(discord.File(path))

    await message.reply(result["reply"], files=files, mention_author=False)
    await bot.process_commands(message)


if __name__ == "__main__":
    raise SystemExit("請執行：python run.py")
