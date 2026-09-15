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

    async def _sync_guild_commands(guild: discord.Guild) -> int:
        """Publish the full slash tree to one guild (appears immediately)."""
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        return len(synced)

    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user} ({bot.user and bot.user.id})")
        try:
            # Global-only sync can take up to ~1h for new commands to show.
            # Clear remote globals (avoids duplicate menu entries), then sync
            # each guild so /music etc. appear immediately.
            if bot.application_id is not None:
                await bot.http.bulk_upsert_global_commands(bot.application_id, [])
                print("Cleared global app commands (guild sync only)")
            for guild in bot.guilds:
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                names = ", ".join(sorted(c.name for c in synced))
                print(f"Synced {len(synced)} guild commands → {guild.id}: {names}")
        except Exception as exc:
            print(f"Command sync failed: {exc}")

    @bot.event
    async def on_guild_join(guild: discord.Guild) -> None:
        try:
            n = await _sync_guild_commands(guild)
            print(f"Synced {n} commands for new guild {guild.id}")
        except Exception as exc:
            print(f"Guild join command sync failed: {exc}")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        await handle_message(bot, message)

    bot.run(settings.discord_token)


if __name__ == "__main__":
    run()
