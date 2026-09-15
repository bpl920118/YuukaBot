from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.checks import owner_only
from bot.cogs._helpers import OwnerErrorMixin, require_guild


class GeneralCog(OwnerErrorMixin, commands.Cog):
    """公開指令：狀態、簽到、圖庫、好感。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pipeline(self):
        return self.bot.pipeline  # type: ignore[attr-defined]

    @property
    def settings(self):
        return self.bot.settings  # type: ignore[attr-defined]

    @property
    def repo(self):
        return self.bot.repo  # type: ignore[attr-defined]

    @app_commands.command(name="ping", description="測試機器人是否在線")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"在。延遲約 `{latency_ms}` ms。", ephemeral=True
        )

    @app_commands.command(
        name="checkin",
        description="本伺服器每日簽到（一天第一次由優香回話；重複簽到不打 API）",
    )
    async def checkin(self, interaction: discord.Interaction) -> None:
        gid = await require_guild(interaction)
        if gid is None:
            return
        await interaction.response.defer(thinking=True)
        result = await self.pipeline.handle_checkin(
            guild_id=gid,
            user_id=interaction.user.id,
            display_name=interaction.user.display_name,
        )
        await interaction.followup.send(result["reply"])

    @app_commands.command(name="gallery", description="查看本伺服器最近的 CG")
    async def gallery(self, interaction: discord.Interaction) -> None:
        gid = await require_guild(interaction)
        if gid is None:
            return
        items = await self.repo.recent_gallery(
            gid,
            limit=3,
            character_id=self.settings.default_character_id,
        )
        if not items:
            await interaction.response.send_message("還沒有收藏 CG。", ephemeral=True)
            return
        files = []
        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. tier=`{item.tier}` emotion=`{item.emotion}`")
            path = Path(item.path)
            if path.exists() and path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".gif",
            }:
                files.append(discord.File(path, filename=path.name))
        await interaction.response.send_message(
            "本伺服器最近 CG：\n" + "\n".join(lines),
            files=files[:3],
        )

    score = app_commands.Group(
        name="score", description="伺服器共用好感度（對話不顯示；用指令查）"
    )

    @score.command(name="show", description="查看本伺服器共用好感、稱號與簽到連簽")
    async def score_show(self, interaction: discord.Interaction) -> None:
        gid = await require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.describe_score(gid)
        await interaction.response.send_message(text, ephemeral=True)

    @score.command(name="threshold", description="設定達到多少分自動生圖（僅管理者）")
    @app_commands.describe(value="1～100，達到後出圖並扣除等量分數")
    @owner_only()
    async def score_threshold(
        self, interaction: discord.Interaction, value: app_commands.Range[int, 1, 100]
    ) -> None:
        gid = await require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_score_threshold(gid, value)
        await interaction.response.send_message(text, ephemeral=True)

    @score.command(name="set", description="直接設定共用好感數值（僅管理者）")
    @app_commands.describe(value="0～100")
    @owner_only()
    async def score_set(
        self, interaction: discord.Interaction, value: app_commands.Range[int, 0, 100]
    ) -> None:
        gid = await require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_affection(gid, value)
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeneralCog(bot))
