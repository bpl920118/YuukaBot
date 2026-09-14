"""Home-PC Pixiv → RSS bridge (stdlib only; RSSHub-compatible path).

Why: cloud VMs often get Cloudflare-blocked on pixiv.net; your home IP usually works.
YuukaBot on Grok should set:
  FANART_RSS_URL=http://<Tailscale-100.x>:1200/pixiv/search/早瀬ユウカ

Run on the PC that can open Pixiv in a browser:

  python scripts/home_pixiv_rss.py

Optional env:
  PIXIV_RSS_BIND=0.0.0.0          # default 0.0.0.0 so Tailscale can reach it
  PIXIV_RSS_PORT=1200
  PIXIV_COOKIE=...                # browser Cookie if AJAX needs login
  PIXIV_RSS_MODE=safe             # safe | all | r18
  PIXIV_RSS_PUBLIC_BASE=http://100.x.y.z:1200   # force absolute img proxy URLs
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_THUMB_RE = re.compile(r"/c/\d+x\d+(?:_\d+_a\d+)?/")
_SEARCH_RE = re.compile(r"^/pixiv/(?:search|tag)/([^/?#]+)/?$")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


BIND = _env("PIXIV_RSS_BIND", "0.0.0.0")
PORT = int(_env("PIXIV_RSS_PORT", "1200") or "1200")
COOKIE = _env("PIXIV_COOKIE") or _env("FANART_PIXIV_COOKIE")
MODE = (_env("PIXIV_RSS_MODE", "safe") or "safe").lower()
PUBLIC_BASE = _env("PIXIV_RSS_PUBLIC_BASE").rstrip("/")


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {
        "User-Agent": _UA,
        "Referer": "https://www.pixiv.net/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }
    if COOKIE:
        h["Cookie"] = COOKIE
    if extra:
        h.update(extra)
    return h


def _http_get(url: str, *, timeout: float = 30.0, headers: dict[str, str] | None = None) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers=headers or _headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            return resp.status, resp.read(), ctype
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        ctype = (exc.headers.get("Content-Type") or "").split(";")[0].strip() if exc.headers else ""
        return exc.code, body, ctype


def thumb_to_master(thumb_url: str) -> str:
    url = _THUMB_RE.sub("/", thumb_url)
    url = url.replace("_square1200", "_master1200")
    url = url.replace("_custom1200", "_master1200")
    return url


def search_illusts(tag: str, *, mode: str = "safe", pages: int = 1) -> list[dict]:
    tag = (tag or "").strip()
    if not tag:
        return []
    if mode not in {"safe", "all", "r18"}:
        mode = "safe"
    out: list[dict] = []
    # Warm-up cookie / CF on home network
    _http_get("https://www.pixiv.net/", timeout=15.0)
    for page in range(1, max(1, pages) + 1):
        encoded = urllib.parse.quote(tag, safe="")
        url = (
            f"https://www.pixiv.net/ajax/search/artworks/{encoded}"
            f"?word={encoded}&order=date_d&mode={mode}"
            f"&p={page}&s_mode=s_tag&type=illust_and_ugoira"
        )
        code, body, _ = _http_get(url, timeout=30.0)
        if code != 200:
            raise RuntimeError(f"pixiv search HTTP {code}")
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"pixiv search JSON parse failed: {exc}") from exc
        if payload.get("error"):
            raise RuntimeError(f"pixiv search error: {payload.get('message')}")
        data = ((payload.get("body") or {}).get("illustManga") or {}).get("data") or []
        for row in data:
            if not isinstance(row, dict) or row.get("isAdContainer"):
                continue
            t = row.get("type")
            if t is not None and str(t) not in ("illust", "0"):
                continue
            illust_id = str(row.get("id") or "").strip()
            thumb = str(row.get("url") or "").strip()
            if not illust_id or not thumb:
                continue
            out.append(
                {
                    "id": illust_id,
                    "title": str(row.get("title") or illust_id)[:200],
                    "author": str(row.get("userName") or "unknown")[:100],
                    "thumb": thumb,
                    "page": f"https://www.pixiv.net/artworks/{illust_id}",
                }
            )
    return out


def build_rss(tag: str, items: list[dict], *, public_base: str) -> str:
    channel_link = f"{public_base}/pixiv/search/{urllib.parse.quote(tag)}"
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        f"<title>Pixiv search: {escape(tag)}</title>",
        f"<link>{escape(channel_link)}</link>",
        f"<description>Home Pixiv RSS bridge for {escape(tag)}</description>",
    ]
    for it in items:
        master = thumb_to_master(it["thumb"])
        # Proxy via this host so Grok never hits i.pximg.net directly.
        img_proxy = f"{public_base}/pixiv/img?url={urllib.parse.quote(master, safe='')}"
        desc = (
            f'<p>{escape(it["title"])} — {escape(it["author"])}</p>'
            f'<img src="{escape(img_proxy)}" />'
        )
        parts.extend(
            [
                "<item>",
                f"<title>{escape(it['title'])}</title>",
                f"<link>{escape(it['page'])}</link>",
                f"<guid isPermaLink=\"true\">{escape(it['page'])}</guid>",
                f"<author>{escape(it['author'])}</author>",
                f"<description>{html.escape(desc)}</description>",
                "</item>",
            ]
        )
    parts.extend(["</channel>", "</rss>", ""])
    return "\n".join(parts)


class Handler(BaseHTTPRequestHandler):
    server_version = "YuukaPixivRSS/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _public_base(self) -> str:
        if PUBLIC_BASE:
            return PUBLIC_BASE
        host = self.headers.get("Host") or f"127.0.0.1:{PORT}"
        return f"http://{host}"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path or "/"

        if path in {"/", "/health"}:
            body = b'{"ok":true,"service":"home_pixiv_rss"}\n'
            self._send(200, body, "application/json; charset=utf-8")
            return

        if path == "/pixiv/img":
            qs = urllib.parse.parse_qs(parsed.query)
            raw = (qs.get("url") or [""])[0].strip()
            if not raw.startswith("https://i.pximg.net/"):
                self._send(400, b"only i.pximg.net urls allowed\n", "text/plain; charset=utf-8")
                return
            code, data, ctype = _http_get(
                raw,
                timeout=60.0,
                headers=_headers({"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}),
            )
            if code != 200 or not data:
                self._send(502, f"upstream HTTP {code}\n".encode(), "text/plain; charset=utf-8")
                return
            if not ctype.startswith("image/"):
                ctype = "image/jpeg"
            self._send(200, data, ctype)
            return

        m = _SEARCH_RE.match(path)
        if m:
            tag = urllib.parse.unquote(m.group(1))
            try:
                items = search_illusts(tag, mode=MODE, pages=1)
            except Exception as exc:
                msg = f"pixiv fetch failed: {exc}\n".encode("utf-8", errors="replace")
                self._send(502, msg, "text/plain; charset=utf-8")
                return
            rss = build_rss(tag, items, public_base=self._public_base())
            self._send(200, rss.encode("utf-8"), "application/rss+xml; charset=utf-8")
            return

        self._send(404, b"not found\n", "text/plain; charset=utf-8")


def main() -> int:
    if MODE not in {"safe", "all", "r18"}:
        print(f"invalid PIXIV_RSS_MODE={MODE!r}; use safe|all|r18", file=sys.stderr)
        return 2
    httpd = ThreadingHTTPServer((BIND, PORT), Handler)
    print(
        f"home_pixiv_rss listening on http://{BIND}:{PORT}/ "
        f"(try /pixiv/search/<tag>) mode={MODE} cookie={'yes' if COOKIE else 'no'}",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
