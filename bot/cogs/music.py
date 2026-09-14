from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from bot.music.player import MusicManager, Track, format_duration
from bot.music.ytdlp import PLAYLIST_LIMIT, ResolveError, resolve_query

# Leave shortly after the last human leaves (avoids flap on channel hop).
ALONE_LEAVE_SECONDS = 30


def _voice_channel(
    interaction: discord.Interaction,
) -> discord.VoiceChannel | discord.StageChannel | None:
    if not isinstance(interaction.user, discord.Member):
        return None
    state = interaction.user.voice
    if state is None or state.channel is None:
        return None
    return state.channel


def _human_members(
    channel: discord.VoiceChannel | discord.StageChannel,
) -> int:
    return sum(1 for m in channel.members if not m.bot)


class MusicCog(commands.Cog):
    """Voice music playback (YouTube / YouTube Music)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = MusicManager()
        self._alone_tasks: dict[int, asyncio.Task[None]] = {}

    def _player(self, guild_id: int):
        return self.manager.get(guild_id)

    async def cog_unload(self) -> None:
        for task in self._alone_tasks.values():
            task.cancel()
        self._alone_tasks.clear()
        await self.manager.teardown_all()

    def _cancel_alone_leave(self, guild_id: int) -> None:
        task = self._alone_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _schedule_alone_leave(self, guild_id: int) -> None:
        self._cancel_alone_leave(guild_id)
        self._alone_tasks[guild_id] = asyncio.create_task(
            self._alone_leave_after_delay(guild_id)
        )

    async def _alone_leave_after_delay(self, guild_id: int) -> None:
        try:
            await asyncio.sleep(ALONE_LEAVE_SECONDS)
        except asyncio.CancelledError:
            return

        player = self.manager.peek(guild_id)
        if player is None or not player.voice or not player.voice.is_connected():
            return
        channel = player.voice.channel
        if channel is None or _human_members(channel) > 0:
            return

        text = player.text_channel
        await player.disconnect()
        self._alone_tasks.pop(guild_id, None)
        if text is not None:
            try:
                await text.send("語音頻道沒人了，我先離開。")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        guild = member.guild
        player = self.manager.peek(guild.id)
        if player is None or not player.voice or not player.voice.is_connected():
            return

        bot_channel = player.voice.channel
        if bot_channel is None:
            return

        # Only care about joins/leaves that affect the bot's channel.
        touched = {before.channel, after.channel}
        if bot_channel not in touched and member.id != self.bot.user_id:
            # Still re-check if someone left bot channel (before.channel == bot)
            if before.channel != bot_channel and after.channel != bot_channel:
                return

        if _human_members(bot_channel) == 0:
            self._schedule_alone_leave(guild.id)
        else:
            self._cancel_alone_leave(guild.id)

    @app_commands.command(
        name="play",
        description="播放 YouTube／YT Music（連結、歌名或播放清單）",
    )
    @app_commands.describe(query="影片／音樂連結、播放清單，或搜尋關鍵字")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return

        channel = _voice_channel(interaction)
        if channel is None:
            await interaction.response.send_message(
                "請先加入語音頻道再使用 `/play`。", ephemeral=True
            )
            return

        me = interaction.guild.me
        if me is not None:
            perms = channel.permissions_for(me)
            if not perms.connect or not perms.speak:
                await interaction.response.send_message(
                    "我沒有這個語音頻道的「連線」或「說話」權限。",
                    ephemeral=True,
                )
                return

        await interaction.response.defer()

        try:
            resolved = await resolve_query(query, playlist_limit=PLAYLIST_LIMIT)
        except ResolveError as exc:
            await interaction.followup.send(f"無法播放：{exc}")
            return

        player = self._player(interaction.guild.id)
        player.text_channel = interaction.channel
        self._cancel_alone_leave(interaction.guild.id)

        try:
            await player.connect(channel)
        except discord.ClientException as exc:
            await interaction.followup.send(f"無法加入語音頻道：`{exc}`")
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"無法加入語音頻道：`{exc}`")
            return

        assert isinstance(interaction.user, discord.Member)
        tracks = [
            Track.from_resolved(
                r,
                requester_id=interaction.user.id,
                requester_name=interaction.user.display_name,
            )
            for r in resolved
        ]
        await player.enqueue(tracks)

        if len(tracks) == 1:
            t = tracks[0]
            await interaction.followup.send(
                f"已加入佇列：**{t.title}**（{format_duration(t.duration)}）"
                f" — {t.webpage_url}"
            )
        else:
            await interaction.followup.send(
                f"已從播放清單加入 **{len(tracks)}** 首"
                f"（上限 {PLAYLIST_LIMIT}）。第一首：**{tracks[0].title}**"
            )

    @app_commands.command(name="skip", description="跳過目前播放的歌曲")
    async def skip(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        player = self._player(interaction.guild.id)
        if player.current is None and not player.queue:
            await interaction.response.send_message("現在沒有在播放。", ephemeral=True)
            return
        skipped = await player.skip()
        if skipped:
            await interaction.response.send_message(f"已跳過：**{skipped.title}**")
        else:
            await interaction.response.send_message("已跳過。")

    @app_commands.command(name="pause", description="暫停播放")
    async def pause(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        player = self._player(interaction.guild.id)
        if player.pause():
            await interaction.response.send_message("已暫停。")
        else:
            await interaction.response.send_message("現在沒有在播放。", ephemeral=True)

    @app_commands.command(name="resume", description="繼續播放")
    async def resume(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        player = self._player(interaction.guild.id)
        if player.resume():
            await interaction.response.send_message("繼續播放。")
        else:
            await interaction.response.send_message("目前沒有暫停中的歌曲。", ephemeral=True)

    @app_commands.command(name="stop", description="停止播放並清空佇列（仍留在語音）")
    async def stop(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        player = self._player(interaction.guild.id)
        await player.stop(leave=False)
        await interaction.response.send_message("已停止並清空佇列。")

    @app_commands.command(name="leave", description="停止播放並離開語音頻道")
    async def leave(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        player = self._player(interaction.guild.id)
        await player.disconnect()
        await interaction.response.send_message("已離開語音頻道。")

    @app_commands.command(name="queue", description="查看播放佇列")
    async def queue_cmd(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        player = self._player(interaction.guild.id)
        lines: list[str] = []
        if player.current:
            lines.append(
                f"**目前：** {player.current.title}"
                f"（{format_duration(player.current.duration)}）"
            )
        else:
            lines.append("**目前：** （無）")

        upcoming = player.queue_preview(10)
        if not upcoming:
            lines.append("佇列是空的。")
        else:
            lines.append(f"**接下來（{len(player.queue)}）：**")
            for i, t in enumerate(upcoming, 1):
                lines.append(
                    f"`{i}.` {t.title}（{format_duration(t.duration)}）"
                    f" — {t.requester_name}"
                )
            rest = len(player.queue) - len(upcoming)
            if rest > 0:
                lines.append(f"…還有 {rest} 首")
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="nowplaying", description="顯示目前播放中的歌曲")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        player = self._player(interaction.guild.id)
        cur = player.current
        if cur is None:
            await interaction.response.send_message("現在沒有在播放。", ephemeral=True)
            return
        status = "暫停中" if player.is_paused else "播放中"
        await interaction.response.send_message(
            f"**{status}：** {cur.title}（{format_duration(cur.duration)}）\n"
            f"{cur.webpage_url}\n"
            f"點歌：{cur.requester_name}"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
