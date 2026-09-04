from __future__ import annotations

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
