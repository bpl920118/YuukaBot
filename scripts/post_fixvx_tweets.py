#!/usr/bin/env python3
"""Post Blue Archive tweet links to Discord as fixvx embeds. SFW only."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

STATE = Path("/workspace/YuukaBot/storage/watch/twitter_ba_sent.json")
CHANNEL_DEFAULT = ""  # must set TWITTER_BA_CHANNEL_ID; never reuse FANART_CHANNEL_ID
NSFW_RE = re.compile(
    r"\b(nsfw|r-?18|18\+|explicit|nude|hentai|lewd|porn|ecchi|r18g|無修正)\b",
    re.I,
)
STATUS_RE = re.compile(
    r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)",
    re.I,
)


def load_env_token() -> str:
    env = Path("/workspace/YuukaBot/.env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("DISCORD_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    # box-secrets card fallback
    box = Path("/home/box/sand-data/box-secrets.json")
    if box.exists():
        card = json.loads(box.read_text()).get("card") or {}
        for k in ("DISCORD_TOKEN", "YUUKA_DISCORD_TOKEN"):
            if card.get(k):
                return str(card[k]).strip()
    raise SystemExit("no discord token")


def to_fixvx(url: str) -> str | None:
    m = STATUS_RE.search(url)
    if not m:
        return None
    return f"https://fixvx.com/{m.group(1)}/status/{m.group(2)}"


def load_sent() -> set[str]:
    if not STATE.exists():
        return set()
    try:
        data = json.loads(STATE.read_text())
        return set(data.get("ids") or [])
    except Exception:
        return set()


def save_sent(ids: set[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    # keep last 500
    keep = sorted(ids)[-100000:]  # was 1500: trimming by id dropped old tweets from dedup, causing reposts
    STATE.write_text(json.dumps({"ids": keep}, ensure_ascii=False, indent=2))


def discord_post(token: str, channel_id: str, content: str) -> tuple[int, str]:
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=body,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "YuukaBotFanart/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


def main(argv: list[str]) -> int:
    channel = os.environ.get("TWITTER_BA_CHANNEL_ID") or CHANNEL_DEFAULT
    envf = Path("/workspace/YuukaBot/.env")
    if envf.exists():
        for line in envf.read_text().splitlines():
            if line.startswith("TWITTER_BA_CHANNEL_ID=") and line.split("=", 1)[1].strip():
                channel = line.split("=", 1)[1].strip()
    if not channel:
        raise SystemExit("TWITTER_BA_CHANNEL_ID not set (keep separate from FANART_CHANNEL_ID)")
    token = load_env_token()
    sent = load_sent()
    # args: raw urls or "url|title" lines on stdin
    lines = argv[1:] if len(argv) > 1 else [ln.strip() for ln in sys.stdin if ln.strip()]
    posted = 0
    for line in lines:
        title = ""
        url = line
        if "|" in line:
            url, title = line.split("|", 1)
            url, title = url.strip(), title.strip()
        if title and NSFW_RE.search(title):
            print("skip_nsfw_title", title[:60])
            continue
        fx = to_fixvx(url)
        if not fx:
            print("skip_bad_url", url[:80])
            continue
        tid = fx.rsplit("/", 1)[-1]
        if tid in sent:
            print("skip_dup", tid)
            continue
        # light note + fixvx link (Discord embeds image from fixvx)
        content = f"蔚藍檔案推特圖（SFW）\n{fx}"
        try:
            code, body = discord_post(token, channel, content)
        except Exception as e:
            # Connection dropped after sending (e.g. RemoteDisconnected): Discord often already
            # accepted the message, so record it as sent to avoid duplicate reposts on retry.
            print("post_conn_err_assume_sent", tid, type(e).__name__)
            sent.add(tid)
            posted += 1
            save_sent(sent)
            continue
        print("post", tid, code)
        if code in (200, 201):
            sent.add(tid)
            posted += 1
            save_sent(sent)
        else:
            print("err", body)
    save_sent(sent)
    print("posted_count", posted)
    return 0 if posted else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
