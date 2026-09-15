from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


def guild_id(interaction: discord.Interaction) -> int | None:
    return interaction.guild.id if interaction.guild else None


async def require_guild(interaction: discord.Interaction) -> int | None:
    gid = guild_id(interaction)
    if gid is None:
        await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
    return gid


async def parse_message_id(
    interaction: discord.Interaction, after_message_id: str | None
) -> int | None | bool:
    """Return message id, None if unset, or False if invalid (reply already sent)."""
    if not after_message_id:
        return None
    raw = after_message_id.strip()
    if not raw.isdigit():
        await interaction.response.send_message(
            "after_message_id 請填純數字訊息 ID。", ephemeral=True
        )
        return False
    return int(raw)


class OwnerErrorMixin(commands.Cog):
    """Shared CheckFailure reply for owner-only slash commands."""

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            msg = str(error) or "沒有權限使用這個指令。"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error
