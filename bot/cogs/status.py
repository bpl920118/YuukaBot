from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands


class StatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="affection", description="查看本伺服器共用好感度")
    async def affection(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        bond = await self.bot.repo.get_or_create_bond(  # type: ignore[attr-defined]
            interaction.guild.id,
            self.bot.settings.default_character_id,  # type: ignore[attr-defined]
        )
        await interaction.response.send_message(
            f"本伺服器與優香的共用好感：**{bond.affection}/100**\n目前情緒：`{bond.emotion}`",
            ephemeral=False,
        )

    @app_commands.command(name="gallery", description="查看本伺服器最近的 CG")
    async def gallery(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        items = await self.bot.repo.recent_gallery(  # type: ignore[attr-defined]
            interaction.guild.id,
            limit=3,
            character_id=self.bot.settings.default_character_id,  # type: ignore[attr-defined]
        )
        if not items:
            await interaction.response.send_message("還沒有收藏 CG。", ephemeral=True)
            return
        files = []
        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. tier=`{item.tier}` emotion=`{item.emotion}`")
            path = Path(item.path)
            if path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                files.append(discord.File(path, filename=path.name))
        await interaction.response.send_message(
            "本伺服器最近 CG：\n" + "\n".join(lines),
            files=files[:3],
        )

    async def cog_load(self) -> None:
        # Sync to guilds on load is heavy; global sync once at ready is enough via bot hook.
        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatusCog(bot))
