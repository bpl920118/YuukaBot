from __future__ import annotations

from dataclasses import dataclass

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
    "girls_frontline",
    "girls'_frontline_2:_exilium",
    "umamusume",
    "princess_connect!",
    "reverse:1999",
    "mahjong_soul",
    "project_sekai",
    "idolmaster",
)

# Drop furry / non-human western flavours + low-quality noise.
# Intentionally NOT excluding robot/mecha/monster_girl (common in AK / Nikke / AL)
# or animated (GIF/WebM/MP4 are forwarded as Discord attachments).
DEFAULT_EXCLUDE_TAGS: tuple[str, ...] = (
    "furry",
    "anthro",
    "feral",
    "non-human",
    "animalization",
    "kemono",
    "comic",
    "lowres",
    "sketch",
    "ai-generated",
    "ai_generated",
)

# Discord can play these as attachments; embed.set_image only suits stills/GIF.
VIDEO_EXTS: frozenset[str] = frozenset({".webm", ".mp4", ".mov"})


def guess_media_ext(url: str, content_type: str = "") -> str:
    """Map URL / Content-Type to a Discord-friendly file extension."""
    ctype = (content_type or "").split(";")[0].strip().lower()
    lower = (url or "").lower().split("?", 1)[0]
    if "png" in ctype or lower.endswith(".png"):
        return ".png"
    if "webp" in ctype or lower.endswith(".webp"):
        return ".webp"
    if "gif" in ctype or lower.endswith(".gif"):
        return ".gif"
    if "webm" in ctype or lower.endswith(".webm"):
        return ".webm"
    if "mp4" in ctype or "mpeg" in ctype or lower.endswith(".mp4"):
        return ".mp4"
    if "quicktime" in ctype or lower.endswith(".mov"):
        return ".mov"
    return ".jpg"


def is_video_ext(ext: str) -> bool:
    return (ext or "").lower() in VIDEO_EXTS


@dataclass(frozen=True)
class BooruPost:
    source_name: str
    post_id: str
    title: str
    author: str
    page_url: str
    image_url: str
    score: int
    rating: str
    origin: str
    copyrights: tuple[str, ...]
    tags: frozenset[str]


def parse_csv_tags(raw: str, fallback: tuple[str, ...] = ()) -> tuple[str, ...]:
    parts = [p.strip() for p in (raw or "").replace("\n", ",").split(",")]
    cleaned = tuple(p for p in parts if p)
    return cleaned or fallback


def normalize_booru_rating(raw: str) -> str:
    """Gelbooru/Safebooru ratings → g/s/q/e (legacy ``s`` = safe)."""
    text = (raw or "").strip().lower()
    if text in {"g", "general", "safe", "s"}:
        return "g"
    if text in {"sensitive"}:
        return "s"
    if text in {"q", "questionable"}:
        return "q"
    if text in {"e", "explicit"}:
        return "e"
    return text or "g"


def passes_quality(
    post: BooruPost,
    *,
    min_score: int,
    allowed_copyrights: frozenset[str],
    exclude_tags: frozenset[str],
    allowed_ratings: frozenset[str] | None = None,
) -> bool:
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


def pick_copyrights(tags: frozenset[str], known: frozenset[str] | None = None) -> tuple[str, ...]:
    pool = known or frozenset(DEFAULT_COPYRIGHTS)
    return tuple(sorted(t for t in tags if t in pool))
