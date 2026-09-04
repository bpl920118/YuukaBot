from __future__ import annotations

import discord
from discord import app_commands

from config import get_settings


def is_owner_user(user: discord.abc.User) -> bool:
    """True only for TEACHER_USER_ID — settings / admin slash commands."""
    return user.id == get_settings().teacher_user_id


# Back-compat alias used by older imports
is_teacher_user = is_owner_user


def owner_only():
    """Slash-command check: only the configured owner may run admin commands."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if is_owner_user(interaction.user):
            return True
        raise app_commands.CheckFailure(
            "這個指令只有管理者可以調整設定（對話裡大家仍會被當成老師）。"
        )

    return app_commands.check(predicate)


# Back-compat alias
teacher_only = owner_only
