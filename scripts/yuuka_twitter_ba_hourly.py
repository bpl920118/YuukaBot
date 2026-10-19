#!/usr/bin/env python3
"""Hourly: find popular SFW Blue Archive tweets, post as fixvx to Discord."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path("/workspace/YuukaBot")
STATE = ROOT / "storage/watch/twitter_ba_sent.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
STATUS_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)",
    re.I,
)
NSFW_RE = re.compile(
    r"(nsfw|r-?18|18\+|explicit|nude|hentai|lewd|porn|ecchi|r18g|無修正|エロ)",
    re.I,
)
# soft tags that often mark borderline; still allow if fxtwitter not sensitive

def env_int(name: str, default: int) -> int:
    import os
    envf = ROOT / ".env"
    val = os.environ.get(name)
    if not val and envf.exists():
        for line in envf.read_text().splitlines():
            if line.startswith(name + "=") and line.split("=", 1)[1].strip():
                val = line.split("=", 1)[1].strip()
                break
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default

QUERIES = [
    "site:x.com ブルアカ イラスト",
    "site:x.com #ブルアカ",
    "site:x.com Blue Archive fanart",
    "site:x.com BlueArchive illustration",
    "ブルアカ イラスト twitter",
    "Blue Archive fanart twitter status",
    "site:reddit.com/r/BlueArchive x.com/status",
    "r/BlueArchive twitter fanart",
    "ブルアカ ファンアート twitter",
]


def curl_get(url: str, timeout: int = 25) -> str:
    p = subprocess.run(
        ["curl", "-sS", "-m", str(timeout), "-A", UA, "-L", url],
        capture_output=True,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[:160])
    return p.stdout.decode("utf-8", "replace")


def discover() -> dict[str, str]:
    found: dict[str, str] = {}
    for q in QUERIES:
        url = "https://www.bing.com/search?q=" + urllib.parse.quote(q) + "&count=40"
        try:
            html = curl_get(url)
        except Exception as e:
            print("bing_fail", q, e, file=sys.stderr)
            continue
        for m in STATUS_RE.finditer(html):
            user, tid = m.group(1), m.group(2)
            if user.lower() in ("i", "intent", "share", "search", "hashtag"):
                continue
            found[tid] = f"https://x.com/{user}/status/{tid}"
        for enc in re.findall(
            r"https?%3A%2F%2F(?:www\.)?(?:x|twitter)\.com%2F[A-Za-z0-9_]+%2Fstatus%2F\d+",
            html,
        ):
            u = urllib.parse.unquote(enc)
            m = STATUS_RE.search(u)
            if m and m.group(1).lower() not in ("i", "intent"):
                found[m.group(2)] = f"https://x.com/{m.group(1)}/status/{m.group(2)}"
    # Reddit fallback (Bing often returns 0 from this host)
    reddit_urls = [
        "https://old.reddit.com/r/BlueArchive/search?q=twitter&restrict_sr=on&sort=top&t=month",
        "https://old.reddit.com/r/BlueArchive/search?q=x.com%2Fstatus&restrict_sr=on&sort=new&t=week",
        "https://old.reddit.com/r/BlueArchive/new/?limit=50",
    ]
    for url in reddit_urls:
        try:
            html = curl_get(url)
        except Exception as e:
            print("reddit_fail", url, e, file=sys.stderr)
            continue
        for m in STATUS_RE.finditer(html):
            user, tid = m.group(1), m.group(2)
            if user.lower() in ("i", "intent", "share", "search", "hashtag"):
                continue
            found[tid] = f"https://x.com/{user}/status/{tid}"
    return found



def fxtwitter(tid: str) -> dict | None:
    try:
        raw = curl_get(f"https://api.fxtwitter.com/status/{tid}")
        return (json.loads(raw) or {}).get("tweet")
    except Exception as e:
        print("fx_fail", tid, e, file=sys.stderr)
        return None


def filter_sfw(found: dict[str, str], limit: int = 40) -> list[tuple[int, str]]:
    min_likes = env_int("TWITTER_BA_MIN_LIKES", 800)
    min_views = env_int("TWITTER_BA_MIN_VIEWS", 20000)
    min_rts = env_int("TWITTER_BA_MIN_RETWEETS", 50)
    print(f"thresholds likes>={min_likes} views>={min_views} rts>={min_rts}")
    out: list[tuple[int, str]] = []
    for tid, url in list(found.items())[:limit]:
        d = fxtwitter(tid)
        if not d:
            continue
        text = d.get("text") or ""
        if d.get("possibly_sensitive") or d.get("sensitive"):
            print("skip_sens", tid)
            continue
        if NSFW_RE.search(text):
            print("skip_nsfw", tid)
            continue
        media = d.get("media") or {}
        has = bool(
            media.get("photos")
            or media.get("videos")
            or media.get("images")
            or media.get("all")
        )
        if not has:
            print("skip_nomedia", tid)
            continue
        likes = int(d.get("likes") or d.get("like_count") or 0)
        views = int(d.get("views") or 0)
        rts = int(d.get("retweets") or 0)
        if likes < min_likes or views < min_views or rts < min_rts:
            print("skip_low_heat", tid, f"likes={likes}", f"views={views}", f"rts={rts}")
            continue
        user = (d.get("author") or {}).get("screen_name") or url.split("/")[3]
        # rank score: blend likes + views/50
        score = likes * 10 + views // 50 + rts * 20
        out.append((score, f"https://x.com/{user}/status/{tid}"))
        print("ok", score, user, tid, f"likes={likes}", f"views={views}", f"rts={rts}")
    out.sort(reverse=True)
    return out


def load_sent_ids() -> set[str]:
    state = ROOT / "storage/watch/twitter_ba_sent.json"
    if not state.exists():
        return set()
    try:
        import json
        return set((json.loads(state.read_text()).get("ids") or []))
    except Exception:
        return set()


def main() -> int:
    found = discover()
    print("candidates", len(found))
    ranked = filter_sfw(found)
    if not ranked:
        print("nothing_to_post")
        return 0
    sent = load_sent_ids()
    max_post = env_int("TWITTER_BA_MAX_PER_HOUR", 3)
    urls = []
    for score, url in ranked:
        tid = url.rsplit("/", 1)[-1]
        if tid in sent:
            print("skip_dup_pre", tid)
            continue
        urls.append(url)
        if len(urls) >= max_post:
            break
    if not urls:
        print("all_already_sent_or_empty")
        return 0
    print("posting_top", len(urls), "by_heat")
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts/post_fixvx_tweets.py"), *urls],
        cwd=str(ROOT),
    )
    return p.returncode




if __name__ == "__main__":
    raise SystemExit(main())
