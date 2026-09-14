from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp

PLAYLIST_LIMIT = 50

_YT_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

_YDL_BASE: dict[str, Any] = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": False,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}


class ResolveError(Exception):
    """Failed to resolve a playable track or playlist."""


@dataclass(frozen=True, slots=True)
class ResolvedTrack:
    title: str
    webpage_url: str
    duration: int | None


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_youtube_url(text: str) -> bool:
    if not re.match(r"^https?://", text, re.I):
        return False
    return _host(text) in _YT_HOSTS


def _looks_like_playlist(url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    qs = parse_qs(parsed.query or "")
    if "list" in qs:
        # Watch URLs with list= are still often "play this video in playlist context";
        # treat as playlist only when path is playlist or music playlist.
        if path.rstrip("/").endswith("/playlist") or "music.youtube.com" in (
            parsed.hostname or ""
        ):
            return True
        # Explicit playlist path or /playlist?list=
        if "playlist" in path:
            return True
        # music.youtube.com watch with list → playlist intent for /play
        if (parsed.hostname or "").lower() == "music.youtube.com" and "list" in qs:
            return True
    if path.rstrip("/").endswith("/playlist"):
        return True
    return False


def _entry_to_track(entry: dict[str, Any]) -> ResolvedTrack | None:
    if not entry:
        return None
    webpage = (
        entry.get("webpage_url")
        or entry.get("url")
        or entry.get("original_url")
    )
    video_id = entry.get("id")
    if not webpage and video_id:
        webpage = f"https://www.youtube.com/watch?v={video_id}"
    if not webpage or not isinstance(webpage, str):
        return None
    # Flat playlist entries sometimes put the id-only path in url
    if webpage.startswith("http") is False and video_id:
        webpage = f"https://www.youtube.com/watch?v={video_id}"
    title = entry.get("title") or "Unknown"
    duration = entry.get("duration")
    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = None
    return ResolvedTrack(title=str(title), webpage_url=webpage, duration=duration)


def _extract_sync(query: str, *, playlist_limit: int) -> list[ResolvedTrack]:
    is_url = _is_youtube_url(query)
    want_playlist = is_url and _looks_like_playlist(query)

    if is_url and want_playlist:
        opts = {
            **_YDL_BASE,
            "extract_flat": "in_playlist",
            "noplaylist": False,
            "playlistend": playlist_limit,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
        if not info:
            raise ResolveError("找不到播放清單。")
        entries = info.get("entries") or []
        tracks: list[ResolvedTrack] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            track = _entry_to_track(entry)
            if track:
                tracks.append(track)
            if len(tracks) >= playlist_limit:
                break
        if not tracks:
            raise ResolveError("播放清單是空的或無法解析。")
        return tracks

    if is_url:
        opts = {**_YDL_BASE, "noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
        if not info:
            raise ResolveError("找不到這首歌曲。")
        # Sometimes a single URL still returns playlist wrapper
        if info.get("entries"):
            for entry in info["entries"]:
                if isinstance(entry, dict):
                    track = _entry_to_track(entry)
                    if track:
                        return [track]
            raise ResolveError("找不到這首歌曲。")
        track = _entry_to_track(info)
        if not track:
            raise ResolveError("找不到這首歌曲。")
        return [track]

    # Keyword search → first result
    search = f"ytsearch1:{query}"
    opts = {**_YDL_BASE, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(search, download=False)
    if not info:
        raise ResolveError("搜尋沒有結果。")
    entries = info.get("entries") or [info]
    for entry in entries:
        if isinstance(entry, dict):
            track = _entry_to_track(entry)
            if track:
                return [track]
    raise ResolveError("搜尋沒有結果。")


def _stream_url_sync(webpage_url: str) -> tuple[str, str | None, int | None]:
    """Return (stream_url, title, duration) for playback."""
    opts = {
        **_YDL_BASE,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(webpage_url, download=False)
    if not info:
        raise ResolveError("無法取得音訊串流。")
    if info.get("entries"):
        for entry in info["entries"]:
            if isinstance(entry, dict) and entry.get("url"):
                info = entry
                break
    stream = info.get("url")
    if not stream:
        raise ResolveError("無法取得音訊串流。")
    title = info.get("title")
    duration = info.get("duration")
    try:
        duration_i = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_i = None
    return str(stream), str(title) if title else None, duration_i


async def resolve_query(
    query: str, *, playlist_limit: int = PLAYLIST_LIMIT
) -> list[ResolvedTrack]:
    q = query.strip()
    if not q:
        raise ResolveError("請提供連結或歌名。")
    try:
        return await asyncio.to_thread(
            _extract_sync, q, playlist_limit=playlist_limit
        )
    except ResolveError:
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise ResolveError(f"解析失敗：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 — surface to slash UX
        raise ResolveError(f"解析失敗：{exc}") from exc


async def fetch_stream(webpage_url: str) -> tuple[str, str | None, int | None]:
    try:
        return await asyncio.to_thread(_stream_url_sync, webpage_url)
    except ResolveError:
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise ResolveError(f"串流失敗：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ResolveError(f"串流失敗：{exc}") from exc
