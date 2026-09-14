from __future__ import annotations

import logging

import httpx

from bot.fanart.common import (
    DEFAULT_COPYRIGHTS,
    DEFAULT_EXCLUDE_TAGS,
    BooruPost,
    guess_media_ext,
    parse_csv_tags,
    passes_quality,
    pick_copyrights,
)

log = logging.getLogger("yuuka.fanart.danbooru")

_UA = "YuukaBot/1.0 (Discord fanart; https://github.com/local/YuukaBot)"
_BASE = "https://danbooru.donmai.us"

# Back-compat aliases
DanbooruPost = BooruPost


class DanbooruClient:
    """Official Danbooru posts.json (anon ≈2 tags)."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def search_posts(
        self,
        tags: str,
        *,
        limit: int = 40,
        page: int = 1,
    ) -> list[BooruPost]:
        tags = (tags or "").strip()
        if not tags:
            return []
        limit = max(1, min(int(limit or 40), 100))
        page = max(1, int(page or 1))
        params = {"tags": tags, "limit": limit, "page": page}
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.get(f"{_BASE}/posts.json", params=params)
                resp.raise_for_status()
                rows = resp.json()
            except Exception as exc:
                log.warning("danbooru search failed tags=%r page=%s: %s", tags, page, exc)
                return []
        if not isinstance(rows, list):
            log.warning("danbooru unexpected payload type: %s", type(rows))
            return []
        out: list[BooruPost] = []
        for row in rows:
            item = _parse_row(row)
            if item is not None:
                out.append(item)
        return out

    async def download_image(self, image_url: str) -> tuple[bytes, str] | None:
        async with httpx.AsyncClient(
            timeout=60.0,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.get(image_url)
                resp.raise_for_status()
            except Exception as exc:
                log.warning("danbooru image download failed: %s", exc)
                return None
        ctype = resp.headers.get("content-type") or ""
        return resp.content, guess_media_ext(image_url, ctype)


def build_search_tags(copyright: str = "", rating_tag: str = "rating:g") -> str:
    rating_tag = (rating_tag or "rating:g").strip() or "rating:g"
    copyright = (copyright or "").strip()
    if copyright:
        return f"{copyright} {rating_tag}"
    return f"{rating_tag} order:score"


def _parse_row(row: dict) -> BooruPost | None:
    if not isinstance(row, dict):
        return None
    post_id = str(row.get("id") or "").strip()
    if not post_id:
        return None
    file_ext = str(row.get("file_ext") or "").strip().lower()
    # Prefer original for video; large/sample may be a still preview.
    if file_ext in {"webm", "mp4", "mov"}:
        image = (
            str(row.get("file_url") or "").strip()
            or str(row.get("large_file_url") or "").strip()
            or str(row.get("preview_file_url") or "").strip()
        )
    else:
        image = (
            str(row.get("large_file_url") or "").strip()
            or str(row.get("file_url") or "").strip()
            or str(row.get("preview_file_url") or "").strip()
        )
    if not image:
        return None
    if image.startswith("//"):
        image = "https:" + image

    all_tags = frozenset(t for t in str(row.get("tag_string") or "").split() if t)
    copyrights = tuple(t for t in str(row.get("tag_string_copyright") or "").split() if t)
    if not copyrights:
        copyrights = pick_copyrights(all_tags, frozenset(DEFAULT_COPYRIGHTS))
    artist = str(row.get("tag_string_artist") or "").strip() or "unknown"
    artist = artist.split()[0] if artist else "unknown"
    char_tags = [
        t.replace("_", " ")
        for t in str(row.get("tag_string_character") or "").split()
        if t
    ]
    title = ", ".join(char_tags[:2]) if char_tags else f"danbooru #{post_id}"
    try:
        score = int(row.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    # Danbooru letters: g/s/q/e — keep as-is (do not map "s" via safebooru path).
    rating = str(row.get("rating") or "").strip().lower() or "?"
    source = str(row.get("source") or "").strip()
    return BooruPost(
        source_name="danbooru",
        post_id=post_id,
        title=title[:200],
        author=artist[:100],
        page_url=f"{_BASE}/posts/{post_id}",
        image_url=image,
        score=score,
        rating=rating,
        origin=source,
        copyrights=copyrights,
        tags=all_tags,
    )


__all__ = [
    "DEFAULT_COPYRIGHTS",
    "DEFAULT_EXCLUDE_TAGS",
    "BooruPost",
    "DanbooruClient",
    "DanbooruPost",
    "build_search_tags",
    "parse_csv_tags",
    "passes_quality",
]
