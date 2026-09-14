from __future__ import annotations

import logging

import httpx

from bot.fanart.common import (
    DEFAULT_COPYRIGHTS,
    BooruPost,
    guess_media_ext,
    normalize_booru_rating,
    pick_copyrights,
)

log = logging.getLogger("yuuka.fanart.safebooru")

_UA = "YuukaBot/1.0 (Discord fanart; https://github.com/local/YuukaBot)"
_BASE = "https://safebooru.org/index.php"


class SafebooruClient:
    """Safebooru dapi JSON — no API key; content is already SFW-oriented."""

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
        params: dict[str, str | int] = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": 1,
            "limit": limit,
            "pid": page - 1,
            "tags": tags,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.get(_BASE, params=params)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                log.warning("safebooru search failed tags=%r: %s", tags, exc)
                return []
        rows: list[dict] = []
        if isinstance(payload, list):
            rows = [r for r in payload if isinstance(r, dict)]
        out: list[BooruPost] = []
        known = frozenset(DEFAULT_COPYRIGHTS)
        for row in rows:
            item = _parse_row(row, known)
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
                log.warning("safebooru image download failed: %s", exc)
                return None
        ctype = resp.headers.get("content-type") or ""
        return resp.content, guess_media_ext(image_url, ctype)


def build_safebooru_tags() -> str:
    # Site is SFW-oriented; sort by score across all time.
    return "sort:score"


def _parse_row(row: dict, known: frozenset[str]) -> BooruPost | None:
    post_id = str(row.get("id") or "").strip()
    if not post_id:
        return None
    image = (
        str(row.get("file_url") or "").strip()
        or str(row.get("sample_url") or "").strip()
        or str(row.get("preview_url") or "").strip()
    )
    if not image:
        return None
    if image.startswith("//"):
        image = "https:" + image
    tags = frozenset(t for t in str(row.get("tags") or "").split() if t)
    copyrights = pick_copyrights(tags, known)
    try:
        score = int(row.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    author = str(row.get("owner") or "unknown")[:100]
    charish = [
        t.replace("_", " ")
        for t in tags
        if any(
            x in t
            for x in (
                "(blue_archive)",
                "(genshin_impact)",
                "(arknights)",
                "(zenless_zone_zero)",
                "(wuthering_waves)",
                "(honkai",
                "(umamusume)",
            )
        )
    ]
    if charish:
        title = ", ".join(charish[:2])
    elif copyrights:
        title = copyrights[0].replace("_", " ")
    else:
        title = f"safebooru #{post_id}"
    return BooruPost(
        source_name="safebooru",
        post_id=post_id,
        title=title[:200],
        author=author,
        page_url=f"https://safebooru.org/index.php?page=post&s=view&id={post_id}",
        image_url=image,
        score=score,
        rating=normalize_booru_rating(str(row.get("rating") or "safe")),
        origin=str(row.get("source") or "").strip(),
        copyrights=copyrights,
        tags=tags,
    )
