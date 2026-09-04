from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import discord

from bot.main import YuukaBot, handle_message
from config import get_settings


def run() -> None:
    settings = get_settings()
    if not settings.discord_token:
        raise SystemExit("請在 .env 設定 DISCORD_TOKEN（可參考 .env.example）")

    bot = YuukaBot()

    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user} ({bot.user and bot.user.id})")
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} app commands")
        except Exception as exc:
            print(f"Command sync failed: {exc}")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        await handle_message(bot, message)

    bot.run(settings.discord_token)


if __name__ == "__main__":
    run()
