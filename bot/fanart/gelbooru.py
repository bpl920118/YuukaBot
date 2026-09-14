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

log = logging.getLogger("yuuka.fanart.gelbooru")

_UA = "YuukaBot/1.0 (Discord fanart; https://github.com/local/YuukaBot)"
_BASE = "https://gelbooru.com/index.php"


class GelbooruClient:
    """
    Gelbooru dapi JSON.

    Requires api_key + user_id (account → Options → API). Without credentials
    searches return 401 and this client yields no posts.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        user_id: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._user_id = (user_id or "").strip()
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._user_id)

    async def search_posts(
        self,
        tags: str,
        *,
        limit: int = 40,
        page: int = 1,
    ) -> list[BooruPost]:
        if not self.configured:
            log.warning("gelbooru skipped: set FANART_GELBOORU_API_KEY + FANART_GELBOORU_USER_ID")
            return []
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
            "api_key": self._api_key,
            "user_id": self._user_id,
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
                log.warning("gelbooru search failed tags=%r: %s", tags, exc)
                return []
        rows = _extract_rows(payload)
        out: list[BooruPost] = []
        known = frozenset(DEFAULT_COPYRIGHTS)
        for row in rows:
            item = _parse_row(row, known)
            if item is not None:
                out.append(item)
        return out

    async def download_image(self, image_url: str) -> tuple[bytes, str] | None:
        return await _download(image_url, self._timeout)


def build_gelbooru_tags(rating_general: bool = True) -> str:
    # Gelbooru allows more tags than Danbooru anon; keep safe + score sort.
    if rating_general:
        return "rating:general sort:score:desc"
    return "sort:score:desc"


def _extract_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        posts = payload.get("post")
        if isinstance(posts, list):
            return [r for r in posts if isinstance(r, dict)]
        if isinstance(posts, dict):
            return [posts]
    return []


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
    # Prefer a known copyright name in title; else first few tags.
    if copyrights:
        title = copyrights[0].replace("_", " ")
    else:
        title = " ".join(sorted(tags)[:2]).replace("_", " ") or f"gelbooru #{post_id}"
    chars = [t.replace("_", " ") for t in tags if "(blue_archive)" in t or "(genshin_impact)" in t]
    if chars:
        title = ", ".join(chars[:2])
    return BooruPost(
        source_name="gelbooru",
        post_id=post_id,
        title=title[:200],
        author=author,
        page_url=f"https://gelbooru.com/index.php?page=post&s=view&id={post_id}",
        image_url=image,
        score=score,
        rating=normalize_booru_rating(str(row.get("rating") or "general")),
        origin=str(row.get("source") or "").strip(),
        copyrights=copyrights,
        tags=tags,
    )


async def _download(image_url: str, timeout: float) -> tuple[bytes, str] | None:
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": _UA},
        follow_redirects=True,
    ) as client:
        try:
            resp = await client.get(image_url)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("gelbooru image download failed: %s", exc)
            return None
    ctype = resp.headers.get("content-type") or ""
    return resp.content, guess_media_ext(image_url, ctype)
