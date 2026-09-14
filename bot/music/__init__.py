"""Discord voice music: yt-dlp resolve + per-guild queue player."""

from bot.music.player import GuildPlayer, MusicManager, Track
from bot.music.ytdlp import ResolveError, resolve_query

__all__ = [
    "GuildPlayer",
    "MusicManager",
    "ResolveError",
    "Track",
    "resolve_query",
]
