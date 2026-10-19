#!/usr/bin/env python3
from __future__ import annotations
import json, re, subprocess, sys
from pathlib import Path

ROOT = Path("/workspace/YuukaBot")
STATE = ROOT / "storage/watch/twitter_ba_sent.json"
UA = "Discordbot"
NSFW_RE = re.compile(
    r"(nsfw|r-?18|18\+|explicit|nude|hentai|lewd|porn|ecchi|r18g|無修正|エロ)",
    re.I,
)
BA_HINT = re.compile(
    r"(ブルアカ|ブルーアーカイブ|blue\s*archive|bluearchive|蔚藍檔案|碧藍檔案|碧蓝档案|蔚蓝档案|블루\s*아카이브|블루아카)",
    re.I,
)
OTHER_WORK = re.compile(
    r"(nikke|ニケ|勝利の女神|原神|genshin|学マス|学園アイドルマスター|ウマ娘|umamusume|きらら|ホロライブ|hololive|崩壊|スターレイル|アークナイツ|arknights|ゼンゼロ|プロセカ|アズールレーン|アズレン|艦これ|fgo|fate/)",
    re.I,
)
SKIP_UNRELATED = re.compile(
    r"(chiikawa|ちいかわ|ハチワレ|うさぎ\b|なんかちいさくてかわいいやつ)",
    re.I,
)

def env_int(name: str, default: int) -> int:
    import os
    val = os.environ.get(name)
    if not val and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith(name + "=") and line.split("=", 1)[1].strip():
                val = line.split("=", 1)[1].strip()
                break
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default

def curl_get(url: str, timeout: int = 20) -> str:
    p = subprocess.run(
        ["curl", "-sS", "-m", str(timeout), "-A", UA, "-L", url],
        capture_output=True,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[:160])
    return p.stdout.decode("utf-8", "replace")

def fxtwitter(tid: str) -> dict | None:
    try:
        p = subprocess.run(
            ["curl", "-sS", "-m", "20", "-A", UA, "-L", f"https://api.fxtwitter.com/status/{tid}"],
            capture_output=True,
        )
        if p.returncode != 0:
            raise RuntimeError(p.stderr.decode("utf-8", "replace")[:160])
        raw = p.stdout.decode("utf-8", "replace")
        return (json.loads(raw) or {}).get("tweet")
    except Exception as e:
        print("fx_fail", tid, e, file=sys.stderr)
        return None

def load_sent() -> set[str]:
    try:
        return set((json.loads(STATE.read_text()).get("ids") or []))
    except Exception:
        return set()

FOUND_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/ba_x_found.json")
STATS_PATH = FOUND_PATH.with_name(FOUND_PATH.stem + "_stats.json")
MAX_AGE_H = float(__import__("os").environ.get("TWITTER_BA_MAX_AGE_HOURS", "100000"))
ANY_GAME = __import__("os").environ.get("TWITTER_ANY_GAME") == "1"
found = json.loads(FOUND_PATH.read_text())
if isinstance(found, list):
    found = {re.search(r"status/(\d+)", u).group(1): u for u in found if re.search(r"status/(\d+)", u)}
sent = load_sent()
sent_before = len(sent)
print("sent_count", sent_before)
print("candidates", len(found))

min_likes = env_int("TWITTER_BA_MIN_LIKES", 800)
min_views = env_int("TWITTER_BA_MIN_VIEWS", 20000)
min_rts = env_int("TWITTER_BA_MIN_RETWEETS", 50)
max_post = env_int("TWITTER_BA_MAX_PER_HOUR", 3)
print(f"thresholds likes>={min_likes} views>={min_views} rts>={min_rts} max={max_post}")

unseen = [(tid, url) for tid, url in found.items() if tid not in sent]
seen = [(tid, url) for tid, url in found.items() if tid in sent]
unseen.sort(key=lambda x: int(x[0]), reverse=True)
print("unseen", len(unseen), "already_sent_in_pool", len(seen))

check_limit = 220
out = []
checked = 0
ba_tagged = 0
ba_passed = 0
heat_passed = 0
fx_fail = 0
skip_sens = 0
skip_nsfw = 0
skip_nomedia = 0
skip_low = 0
skip_nonba = 0
skip_old = 0

for tid, url in unseen[:check_limit]:
    checked += 1
    d = fxtwitter(tid)
    if not d:
        fx_fail += 1
        continue
    import time as _t
    ts = int(d.get("created_timestamp") or 0)
    if ts and (_t.time() - ts) > MAX_AGE_H * 3600:
        skip_old += 1
        print("skip_old", tid, f"age_h={(_t.time()-ts)/3600:.1f}")
        continue
    text = d.get("text") or ""
    author = (d.get("author") or {})
    aname = (author.get("name") or "") + " " + (author.get("screen_name") or "")
    blob = text + " " + aname
    is_ba = bool(BA_HINT.search(text)) or ANY_GAME
    if is_ba:
        ba_tagged += 1
    else:
        skip_nonba += 1
        if OTHER_WORK.search(text):
            print("skip_nonba_other", tid)
        else:
            print("skip_nonba", tid)
        continue
    if d.get("possibly_sensitive") or d.get("sensitive"):
        skip_sens += 1
        print("skip_sens", tid)
        continue
    if NSFW_RE.search(text):
        skip_nsfw += 1
        print("skip_nsfw", tid)
        continue
    if SKIP_UNRELATED.search(blob):
        print("skip_unrelated", tid)
        continue
    media = d.get("media") or {}
    has = bool(media.get("photos") or media.get("videos") or media.get("images") or media.get("all"))
    if not has:
        skip_nomedia += 1
        print("skip_nomedia", tid)
        continue
    likes = int(d.get("likes") or d.get("like_count") or 0)
    views = int(d.get("views") or 0)
    rts = int(d.get("retweets") or 0)
    if likes < min_likes or views < min_views or rts < min_rts:
        skip_low += 1
        print("skip_low_heat", tid, f"likes={likes}", f"views={views}", f"rts={rts}")
        continue
    heat_passed += 1
    if is_ba:
        ba_passed += 1
    user = author.get("screen_name") or url.split("/")[3]
    score = likes * 10 + views // 50 + rts * 20
    if is_ba:
        score += 50000
    out.append((score, f"https://x.com/{user}/status/{tid}", {"likes": likes, "views": views, "rts": rts, "ba": is_ba, "tid": tid}))
    print("ok", score, user, tid, f"likes={likes}", f"views={views}", f"rts={rts}", f"ba={is_ba}")

out.sort(key=lambda x: x[0], reverse=True)
ba_only = [x for x in out if x[2].get("ba")]
pick_from = ba_only
select_mode = "ba_only"
urls = [u for _, u, _ in pick_from[:max_post]]
picked = [x for x in pick_from[:max_post]]
print("checked", checked)
print("fx_fail", fx_fail)
print("ba_tagged_seen", ba_tagged)
print("heat_passed", heat_passed)
print("ba_passed_heat", ba_passed)
print("skip_old", skip_old, "skip_nonba", skip_nonba, "skip_sens", skip_sens, "skip_nsfw", skip_nsfw, "skip_nomedia", skip_nomedia, "skip_low", skip_low)
print("ranked", len(out), "ba_ranked", len(ba_only))
print("select_mode", select_mode)
print("posting", urls)

stats = {
    "sent_before": sent_before,
    "candidates": len(found),
    "unseen": len(unseen),
    "already_sent_in_pool": len(seen),
    "checked": checked,
    "fx_fail": fx_fail,
    "heat_passed": heat_passed,
    "ba_tagged_seen": ba_tagged,
    "ba_passed_heat": ba_passed,
    "select_mode": select_mode,
    "urls": urls,
    "picked": [{"tid": p[2]["tid"], "url": p[1], "likes": p[2]["likes"], "views": p[2]["views"], "rts": p[2]["rts"], "ba": p[2]["ba"], "score": p[0]} for p in picked],
    "skip_sens": skip_sens,
    "skip_nsfw": skip_nsfw,
    "skip_nomedia": skip_nomedia,
    "skip_low": skip_low,
    "skip_nonba": skip_nonba,
    "skip_old": skip_old,
}
STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2))

if not urls:
    print("nothing_to_post")
    raise SystemExit(0)

p = subprocess.run(
    [sys.executable, str(ROOT / "scripts/post_fixvx_tweets.py"), *urls],
    cwd=str(ROOT),
)
print("post_rc", p.returncode)
try:
    new_sent = len(json.loads(STATE.read_text()).get("ids") or [])
except Exception:
    new_sent = -1
print("sent_count_after", new_sent)
stats["sent_after"] = new_sent
stats["post_rc"] = p.returncode
STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
raise SystemExit(p.returncode)
