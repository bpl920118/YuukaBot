from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Deque

import discord

from bot.music.ytdlp import ResolveError, ResolvedTrack, fetch_stream

log = logging.getLogger(__name__)

FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"


@dataclass(slots=True)
class Track:
    title: str
    webpage_url: str
    duration: int | None
    requester_id: int
    requester_name: str

    @classmethod
    def from_resolved(
        cls, resolved: ResolvedTrack, *, requester_id: int, requester_name: str
    ) -> Track:
        return cls(
            title=resolved.title,
            webpage_url=resolved.webpage_url,
            duration=resolved.duration,
            requester_id=requester_id,
            requester_name=requester_name,
        )


def format_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "?:??"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class GuildPlayer:
    """One voice connection + queue per guild."""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.queue: Deque[Track] = deque()
        self.current: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self._lock = asyncio.Lock()
        self._play_task: asyncio.Task[None] | None = None
        self._skip_requested = False
        self.text_channel: discord.abc.Messageable | None = None

    @property
    def is_playing(self) -> bool:
        return bool(self.voice and self.voice.is_playing())

    @property
    def is_paused(self) -> bool:
        return bool(self.voice and self.voice.is_paused())

    async def connect(
        self, channel: discord.VoiceChannel | discord.StageChannel
    ) -> None:
        if self.voice and self.voice.is_connected():
            if self.voice.channel and self.voice.channel.id == channel.id:
                return
            await self.voice.move_to(channel)
            return
        self.voice = await channel.connect()

    async def enqueue(self, tracks: list[Track]) -> int:
        async with self._lock:
            for t in tracks:
                self.queue.append(t)
            started = False
            if self.current is None and not (self.voice and self.voice.is_playing()):
                started = True
        if started:
            await self._ensure_playing()
        return len(tracks)

    async def _ensure_playing(self) -> None:
        if self._play_task and not self._play_task.done():
            return
        self._play_task = asyncio.create_task(self._player_loop())

    async def _player_loop(self) -> None:
        while True:
            async with self._lock:
                if not self.queue:
                    self.current = None
                    return
                track = self.queue.popleft()
                self.current = track
                self._skip_requested = False

            try:
                stream_url, title, duration = await fetch_stream(track.webpage_url)
            except ResolveError as exc:
                log.warning("stream resolve failed: %s", exc)
                if self.text_channel:
                    try:
                        await self.text_channel.send(
                            f"跳過無法播放的曲目：**{track.title}**（{exc}）"
                        )
                    except discord.HTTPException:
                        pass
                continue

            if self._skip_requested:
                self._skip_requested = False
                continue

            if title:
                track.title = title
            if duration is not None:
                track.duration = duration

            if not self.voice or not self.voice.is_connected():
                self.current = None
                return

            source = discord.FFmpegPCMAudio(
                stream_url,
                before_options=FFMPEG_BEFORE,
                options=FFMPEG_OPTIONS,
            )
            done = asyncio.Event()
            loop = asyncio.get_running_loop()

            def _after(error: Exception | None) -> None:
                if error:
                    log.warning("ffmpeg playback error: %s", error)
                loop.call_soon_threadsafe(done.set)

            try:
                self.voice.play(source, after=_after)
            except Exception as exc:  # noqa: BLE001
                log.warning("voice.play failed: %s", exc)
                if self.text_channel:
                    try:
                        await self.text_channel.send(
                            f"播放失敗：**{track.title}**（`{exc}`）"
                        )
                    except discord.HTTPException:
                        pass
                continue

            await done.wait()
            try:
                source.cleanup()
            except Exception:
                pass

            if self._skip_requested:
                self._skip_requested = False

    async def skip(self) -> Track | None:
        skipped = self.current
        self._skip_requested = True
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()
        elif self.current is None and self.queue:
            await self._ensure_playing()
        return skipped

    def pause(self) -> bool:
        if self.voice and self.voice.is_playing():
            self.voice.pause()
            return True
        return False

    def resume(self) -> bool:
        if self.voice and self.voice.is_paused():
            self.voice.resume()
            return True
        return False

    async def stop(self, *, leave: bool = False) -> None:
        async with self._lock:
            self.queue.clear()
            self.current = None
        self._skip_requested = True
        if self.voice:
            if self.voice.is_playing() or self.voice.is_paused():
                self.voice.stop()
            if leave:
                await self.disconnect()

    async def disconnect(self) -> None:
        async with self._lock:
            self.queue.clear()
            self.current = None
        self._skip_requested = True
        voice = self.voice
        self.voice = None
        if voice and voice.is_connected():
            await voice.disconnect()

    def queue_preview(self, limit: int = 10) -> list[Track]:
        return list(self.queue)[:limit]


class MusicManager:
    def __init__(self) -> None:
        self._players: dict[int, GuildPlayer] = {}

    def get(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is None:
            player = GuildPlayer(guild_id)
            self._players[guild_id] = player
        return player

    async def teardown(self, guild_id: int) -> None:
        player = self._players.pop(guild_id, None)
        if player:
            await player.disconnect()

    async def teardown_all(self) -> None:
        for guild_id in list(self._players):
            await self.teardown(guild_id)
