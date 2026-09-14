from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("yuuka.fanart.danbooru")

_UA = "YuukaBot/1.0 (Discord fanart; https://github.com/local/YuukaBot)"
_BASE = "https://danbooru.donmai.us"

# East-Asian gacha / anime-game copyrights only (no western original).
DEFAULT_COPYRIGHTS: tuple[str, ...] = (
    "blue_archive",
    "arknights",
    "genshin_impact",
    "honkai:_star_rail",
    "zenless_zone_zero",
    "wuthering_waves",
    "honkai_impact_3rd",
    "azur_lane",
    "fate/grand_order",
    "goddess_of_victory:_nikke",
    "girls'_frontline",
    "umamusume",
    "princess_connect!",
    "reverse:1999",
)

# Drop furry / non-human western flavours even if mis-tagged under a game.
# Intentionally NOT excluding robot/mecha/monster_girl (common in AK / Nikke / AL).
DEFAULT_EXCLUDE_TAGS: tuple[str, ...] = (
    "furry",
    "anthro",
    "feral",
    "non-human",
    "animalization",
    "kemono",
    "comic",
    "animated",
    "lowres",
    "sketch",
    "ai-generated",
)


@dataclass(frozen=True)
class DanbooruPost:
    post_id: str
    title: str
    author: str
    page_url: str
    image_url: str
    score: int
    rating: str
    source: str
    copyrights: tuple[str, ...]
    tags: frozenset[str]


class DanbooruClient:
    """
    Official Danbooru posts.json.

    Anonymous searches allow ~2 tags, so we query one copyright + rating:g,
    then filter score / exclude-tags in Python.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def search_posts(
        self,
        tags: str,
        *,
        limit: int = 40,
        page: int = 1,
    ) -> list[DanbooruPost]:
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
        out: list[DanbooruPost] = []
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
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        ext = ".jpg"
        lower = image_url.lower()
        if "png" in ctype or lower.endswith(".png"):
            ext = ".png"
        elif "webp" in ctype or lower.endswith(".webp"):
            ext = ".webp"
        elif "gif" in ctype or lower.endswith(".gif"):
            ext = ".gif"
        return resp.content, ext


def parse_csv_tags(raw: str, fallback: tuple[str, ...] = ()) -> tuple[str, ...]:
    parts = [p.strip() for p in (raw or "").replace("\n", ",").split(",")]
    cleaned = tuple(p for p in parts if p)
    return cleaned or fallback


def build_search_tags(copyright: str = "", rating_tag: str = "rating:g") -> str:
    """
    Anonymous Danbooru allows ~2 tags.

    Default query is ``rating:g order:score`` (safe + popular). Copyright
    filtering happens in Python against the allowlist — top global score is
    mostly explicit, so rating must stay in the API query.
    """
    rating_tag = (rating_tag or "rating:g").strip() or "rating:g"
    copyright = (copyright or "").strip()
    # Per-game mode (used when rotating): still rating-safe; score gated in Python.
    if copyright:
        return f"{copyright} {rating_tag}"
    return f"{rating_tag} order:score"


def passes_quality(
    post: DanbooruPost,
    *,
    min_score: int,
    allowed_copyrights: frozenset[str],
    exclude_tags: frozenset[str],
    allowed_ratings: frozenset[str] | None = None,
) -> bool:
    """Client-side gate: safe rating, game whitelist, score, no non-human junk."""
    ratings = allowed_ratings or frozenset({"g"})
    if post.rating not in ratings:
        return False
    if post.score < int(min_score):
        return False
    if allowed_copyrights and not (allowed_copyrights & set(post.copyrights)):
        return False
    if exclude_tags & post.tags:
        return False
    return True


def _parse_row(row: dict) -> DanbooruPost | None:
    if not isinstance(row, dict):
        return None
    post_id = str(row.get("id") or "").strip()
    if not post_id:
        return None
    image = (
        str(row.get("large_file_url") or "").strip()
        or str(row.get("file_url") or "").strip()
        or str(row.get("preview_file_url") or "").strip()
    )
    if not image:
        return None
    if image.startswith("//"):
        image = "https:" + image

    all_tags = frozenset(
        t for t in str(row.get("tag_string") or "").split() if t
    )
    copyrights = tuple(
        t for t in str(row.get("tag_string_copyright") or "").split() if t
    )
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
    rating = str(row.get("rating") or "").strip().lower() or "?"
    source = str(row.get("source") or "").strip()
    return DanbooruPost(
        post_id=post_id,
        title=title[:200],
        author=artist[:100],
        page_url=f"{_BASE}/posts/{post_id}",
        image_url=image,
        score=score,
        rating=rating,
        source=source,
        copyrights=copyrights,
        tags=all_tags,
    )
