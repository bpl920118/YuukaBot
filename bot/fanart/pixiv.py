from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote

import httpx

from bot.fanart.common import guess_media_ext

log = logging.getLogger("yuuka.fanart.pixiv")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_JSON_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://www.pixiv.net/",
    "Accept": "application/json",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
_IMG_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://www.pixiv.net/",
}

_ARTWORK_RE = re.compile(r"artworks/(\d+)", re.I)
_IMG_SRC_RE = re.compile(
    r"""<img[^>]+src=["']([^"']+)["']""",
    re.I,
)
_THUMB_RE = re.compile(r"/c/\d+x\d+(?:_\d+_a\d+)?/")


@dataclass(frozen=True)
class PixivIllust:
    illust_id: str
    title: str
    author: str
    author_id: str
    page_url: str
    thumb_url: str


class PixivClient:
    """
    Pixiv fanart fetch.

    Preferred: RSSHub feed URL (home/Tailscale), because pixiv.net often
    Cloudflare-blocks cloud VMs. Optional: direct AJAX when cookie is set.
    """

    def __init__(self, timeout: float = 30.0, cookie: str = "") -> None:
        self._timeout = timeout
        self._cookie = (cookie or "").strip()

    def _json_headers(self) -> dict[str, str]:
        h = dict(_JSON_HEADERS)
        if self._cookie:
            h["Cookie"] = self._cookie
        return h

    async def fetch_from_rss(self, feed_url: str) -> list[PixivIllust]:
        feed_url = (feed_url or "").strip()
        if not feed_url:
            return []
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            try:
                resp = await client.get(
                    feed_url,
                    headers={"User-Agent": _UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                )
                resp.raise_for_status()
            except Exception as exc:
                log.warning("pixiv RSS fetch failed: %s", exc)
                return []
        return _parse_rss(resp.text)

    async def search_illusts(
        self,
        tag: str,
        *,
        mode: str = "safe",
        pages: int = 1,
    ) -> list[PixivIllust]:
        tag = (tag or "").strip()
        if not tag:
            return []
        mode = (mode or "safe").strip().lower()
        if mode not in {"safe", "all", "r18"}:
            mode = "safe"

        out: list[PixivIllust] = []
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers=self._json_headers(),
            follow_redirects=True,
        ) as client:
            # Warm-up helps on some networks when cookie is present.
            try:
                await client.get("https://www.pixiv.net/")
            except Exception:
                pass
            for page in range(1, max(1, pages) + 1):
                encoded = quote(tag, safe="")
                url = (
                    f"https://www.pixiv.net/ajax/search/artworks/{encoded}"
                    f"?word={encoded}&order=date_d&mode={mode}"
                    f"&p={page}&s_mode=s_tag&type=illust_and_ugoira"
                )
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    payload = resp.json()
                except Exception as exc:
                    log.warning("pixiv search failed tag=%r page=%s: %s", tag, page, exc)
                    break
                if payload.get("error"):
                    log.warning("pixiv search error: %s", payload.get("message"))
                    break
                body = payload.get("body") or {}
                data = (body.get("illustManga") or {}).get("data") or []
                for row in data:
                    item = _parse_row(row)
                    if item is not None:
                        out.append(item)
        return out

    async def resolve_image_url(self, illust_id: str, fallback_thumb: str = "") -> str | None:
        url = f"https://www.pixiv.net/ajax/illust/{illust_id}"
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers=self._json_headers(),
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                log.info("pixiv illust %s detail failed: %s", illust_id, exc)
                if fallback_thumb:
                    return thumb_to_master(fallback_thumb)
                return None
        if payload.get("error"):
            if fallback_thumb:
                return thumb_to_master(fallback_thumb)
            return None
        urls = (payload.get("body") or {}).get("urls") or {}
        return urls.get("regular") or urls.get("original") or urls.get("small") or (
            thumb_to_master(fallback_thumb) if fallback_thumb else None
        )

    async def download_image(self, image_url: str) -> tuple[bytes, str] | None:
        async with httpx.AsyncClient(timeout=60.0, headers=_IMG_HEADERS, follow_redirects=True) as client:
            try:
                resp = await client.get(image_url)
                resp.raise_for_status()
            except Exception as exc:
                log.warning("pixiv image download failed: %s", exc)
                return None
        return resp.content, guess_media_ext(image_url, resp.headers.get("content-type") or "")


def thumb_to_master(thumb_url: str) -> str:
    url = _THUMB_RE.sub("/", thumb_url)
    url = url.replace("_square1200", "_master1200")
    url = url.replace("_custom1200", "_master1200")
    return url


def _parse_row(row: dict) -> PixivIllust | None:
    if not isinstance(row, dict):
        return None
    if row.get("isAdContainer"):
        return None
    t = row.get("type")
    if t is not None and str(t) not in ("illust", "0"):
        return None
    illust_id = str(row.get("id") or "").strip()
    thumb = str(row.get("url") or "").strip()
    if not illust_id or not thumb:
        return None
    title = str(row.get("title") or illust_id)[:200]
    author = str(row.get("userName") or "unknown")[:100]
    author_id = str(row.get("userId") or "")
    return PixivIllust(
        illust_id=illust_id,
        title=title,
        author=author,
        author_id=author_id,
        page_url=f"https://www.pixiv.net/artworks/{illust_id}",
        thumb_url=thumb,
    )


def _parse_rss(xml_text: str) -> list[PixivIllust]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("pixiv RSS XML parse failed: %s", exc)
        return []

    items: list[PixivIllust] = []
    # RSS 2.0 channel/item; also tolerate Atom-ish accidental feeds.
    candidates = list(root.findall("./channel/item"))
    if not candidates:
        candidates = list(root.findall(".//item"))

    for node in candidates:
        title = _child_text(node, "title") or "pixiv"
        link = _child_text(node, "link") or ""
        author = (
            _child_text(node, "author")
            or _child_text(node, "{http://purl.org/dc/elements/1.1/}creator")
            or "unknown"
        )
        desc = _child_text(node, "description") or _child_text(node, "content:encoded") or ""
        desc = unescape(desc)
        m = _ARTWORK_RE.search(link) or _ARTWORK_RE.search(desc)
        if not m:
            continue
        illust_id = m.group(1)
        thumb = ""
        for src in _IMG_SRC_RE.findall(desc):
            if "pximg.net" in src or "pixiv" in src:
                thumb = src
                break
        if not thumb and _IMG_SRC_RE.search(desc):
            thumb = _IMG_SRC_RE.search(desc).group(1)  # type: ignore[union-attr]
        items.append(
            PixivIllust(
                illust_id=illust_id,
                title=title[:200],
                author=author[:100],
                author_id="",
                page_url=link or f"https://www.pixiv.net/artworks/{illust_id}",
                thumb_url=thumb,
            )
        )
    return items


def _child_text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    if child is not None and child.text:
        return child.text.strip()
    return ""
