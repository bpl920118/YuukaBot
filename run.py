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
            # Guild + global double-sync makes every slash appear twice in the menu.
            # Clear per-guild command sets, then keep a single global sync.
            for guild in bot.guilds:
                bot.tree.clear_commands(guild=guild)
                cleared = await bot.tree.sync(guild=guild)
                print(f"Cleared guild commands → {guild.id} (now {len(cleared)})")
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global app commands")
        except Exception as exc:
            print(f"Command sync failed: {exc}")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        await handle_message(bot, message)

    bot.run(settings.discord_token)


if __name__ == "__main__":
    run()
