from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import discord


async def clear_channel_messages(
    *,
    channel: discord.abc.Messageable,
    bot_user: discord.ClientUser | None,
    guild: discord.Guild | None,
    bot_only: bool = False,
    limit: int = 200,
    after_time: str | None = None,
    after_message_id: int | None = None,
) -> str:
    """Delete messages in a text channel / thread. Returns a user-facing summary."""
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return "只能在文字頻道／討論串清除訊息。"

    limit = max(1, min(200, int(limit)))
    tz8 = timezone(timedelta(hours=8))
    after_dt: datetime | None = None

    if after_time:
        time_m = re.fullmatch(r"\s*(\d{1,2})[:：](\d{2})\s*", after_time)
        if not time_m:
            return "時間格式不對，請用例如 `10:55`。"
        hour, minute = int(time_m.group(1)), int(time_m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return "時間格式不對，請用例如 `10:55`。"
        local_now = datetime.now(tz8)
        after_dt = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if after_dt > local_now:
            after_dt -= timedelta(days=1)
        after_dt = after_dt.astimezone(timezone.utc)

    me = guild.me if guild else None
    perms = channel.permissions_for(me) if me else None

    if bot_only:
        if perms is not None and not (perms.manage_messages or perms.administrator):
            deleted = 0
            async for msg in channel.history(limit=min(limit * 3, 500)):
                if bot_user is None or msg.author.id != bot_user.id:
                    continue
                if after_message_id is not None and msg.id < after_message_id:
                    continue
                if after_dt is not None and msg.created_at < after_dt:
                    continue
                try:
                    await msg.delete()
                    deleted += 1
                except discord.HTTPException:
                    pass
                if deleted >= limit:
                    break
            return f"已刪除機器人訊息約 {deleted} 則。"
    else:
        if perms is None or not (perms.manage_messages or perms.administrator):
            return (
                "我沒有「管理訊息」權限，無法大量刪除頻道訊息。"
                "請在邀請／頻道權限幫我勾 Manage Messages。"
            )

    def check(msg: discord.Message) -> bool:
        if bot_only and (bot_user is None or msg.author.id != bot_user.id):
            return False
        if after_message_id is not None and msg.id < after_message_id:
            return False
        if after_dt is not None and msg.created_at < after_dt:
            return False
        return True

    try:
        deleted = await channel.purge(limit=limit, check=check)
    except discord.Forbidden:
        return "權限不足，無法刪除訊息。"
    except discord.HTTPException as exc:
        return f"刪除失敗：`{exc}`"

    kind = "機器人訊息" if bot_only else "頻道訊息"
    scope = ""
    if after_message_id is not None:
        scope = "（從指定訊息起）"
    elif after_dt is not None:
        scope = f"（從 {after_dt.astimezone(tz8).strftime('%H:%M')} 起）"
    return (
        f"已刪除{kind} {len(deleted)} 則{scope}"
        f"（掃描上限 {limit}；超過 14 天的訊息 Discord 不允許批次刪）。"
    )
