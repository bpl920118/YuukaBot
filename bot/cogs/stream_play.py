from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

STREAMER_DIR = Path("/workspace/discord-streamer")
STREAMER_JS = STREAMER_DIR / "stream.js"
STREAMER_ENV = STREAMER_DIR / ".env"
PID_FILE = STREAMER_DIR / "stream.pid"
LOG_FILE = STREAMER_DIR / "stream.log"


def _env_has_token() -> bool:
    raw = (os.environ.get("USER_TOKEN") or "").strip()
    if raw:
        return True
    try:
        for line in STREAMER_ENV.read_text().splitlines():
            if line.startswith("USER_TOKEN=") and line.split("=", 1)[1].strip().strip('"'):
                return True
    except Exception:
        pass
    return False


def _voice_channel(
    interaction: discord.Interaction,
) -> discord.VoiceChannel | discord.StageChannel | None:
    if not isinstance(interaction.user, discord.Member):
        return None
    state = interaction.user.voice
    if state is None or state.channel is None:
        return None
    return state.channel


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def _stop_stream_sync() -> bool:
    pid = _read_pid()
    stopped = False
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except ProcessLookupError:
            pass
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
                stopped = True
            except Exception:
                pass
    # also kill by pattern
    os.system('pkill -f "node stream.js" >/dev/null 2>&1')
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return stopped


async def _stop_stream() -> bool:
    return await asyncio.to_thread(_stop_stream_sync)


def _start_stream_sync(url: str, guild_id: int, channel_id: int) -> int:
    import subprocess

    _stop_stream_sync()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logf = open(LOG_FILE, "ab", buffering=0)
    proc = subprocess.Popen(
        ["node", str(STREAMER_JS), url, str(guild_id), str(channel_id)],
        cwd=str(STREAMER_DIR),
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={**os.environ},
    )
    PID_FILE.write_text(str(proc.pid))
    return proc.pid


async def _start_stream(url: str, guild_id: int, channel_id: int) -> int:
    return await asyncio.to_thread(_start_stream_sync, url, guild_id, channel_id)


class StreamPlayCog(commands.Cog):
    """本機 1080p Go Live 推流（取代家裡 bridge）。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="vplay",
        description="本機高畫質推流到你所在的語音頻道（Go Live）",
    )
    @app_commands.describe(url="影片或音樂網址")
    async def vplay(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer()
        if not _env_has_token():
            await interaction.followup.send(
                "❌ 尚未設定推流帳號 `USER_TOKEN`（`/workspace/discord-streamer/.env`）。"
            )
            return
        if not STREAMER_JS.exists():
            await interaction.followup.send("❌ 找不到推流腳本 `/workspace/discord-streamer/stream.js`。")
            return
        channel = _voice_channel(interaction)
        if channel is None:
            await interaction.followup.send("❌ 請先進入一個語音頻道，再執行 `/vplay`。")
            return
        if interaction.guild is None:
            await interaction.followup.send("❌ 請在伺服器語音頻道使用。")
            return
        try:
            pid = await _start_stream(url, interaction.guild.id, channel.id)
        except Exception as e:
            await interaction.followup.send(f"❌ 啟動推流失敗: {e}")
            return
        await interaction.followup.send(
            f"🎵 已在本機啟動 Go Live 推流：<{url}>\n"
            f"語音頻道：{channel.mention}（pid `{pid}`）\n"
            f"點播者：{interaction.user.mention}"
        )

    @app_commands.command(
        name="vstop",
        description="停止本機 Go Live 推流",
    )
    async def vstop(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        stopped = await _stop_stream()
        if stopped:
            await interaction.followup.send("⏹️ 已停止本機推流並離開語音。")
        else:
            await interaction.followup.send("⏹️ 目前沒有在跑的推流（已再清一次殘留行程）。")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StreamPlayCog(bot))
