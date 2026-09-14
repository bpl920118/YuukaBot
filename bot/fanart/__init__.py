"""Fanart fetch helpers (Danbooru / Safebooru / Gelbooru / Pixiv)."""

from bot.fanart.common import DEFAULT_COPYRIGHTS, DEFAULT_EXCLUDE_TAGS, BooruPost
from bot.fanart.danbooru import DanbooruClient
from bot.fanart.gelbooru import GelbooruClient
from bot.fanart.pixiv import PixivClient, PixivIllust
from bot.fanart.safebooru import SafebooruClient

__all__ = [
    "BooruPost",
    "DEFAULT_COPYRIGHTS",
    "DEFAULT_EXCLUDE_TAGS",
    "DanbooruClient",
    "GelbooruClient",
    "PixivClient",
    "PixivIllust",
    "SafebooruClient",
]
