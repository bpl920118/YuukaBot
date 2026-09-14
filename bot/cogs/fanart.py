from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.checks import owner_only
from bot.fanart.common import (
    DEFAULT_COPYRIGHTS,
    DEFAULT_EXCLUDE_TAGS,
    BooruPost,
    is_video_ext,
    parse_csv_tags,
    passes_quality,
)
from bot.fanart.danbooru import DanbooruClient, build_search_tags
from bot.fanart.gelbooru import GelbooruClient, build_gelbooru_tags
from bot.fanart.pixiv import PixivClient, PixivIllust
from bot.fanart.safebooru import SafebooruClient, build_safebooru_tags
from config import get_settings

log = logging.getLogger("yuuka.fanart")

_BOORU_SOURCES = ("danbooru", "safebooru", "gelbooru")


def _ratings_from_setting(raw: str) -> frozenset[str]:
    text = (raw or "rating:g").strip().lower()
    if "rating:g" in text or text in {"g", "general", "safe"}:
        return frozenset({"g"})
    if "rating:s" in text or "sensitive" in text:
        return frozenset({"g", "s"})
    letters = {p.strip() for p in text.replace("rating:", "").split(",") if p.strip()}
    letters &= {"g", "s", "q", "e"}
    return frozenset(letters) if letters else frozenset({"g"})


class FanartCog(commands.Cog):
    """Periodic Danbooru / Safebooru / Gelbooru / Pixiv → Discord."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._busy = False
        self._score_page: dict[str, int] = {s: 1 for s in _BOORU_SOURCES}
        self._source_rot = 0

    async def cog_load(self) -> None:
        if not self.poll_fanart.is_running():
            self.poll_fanart.start()

    async def cog_unload(self) -> None:
        self.poll_fanart.cancel()

    def _source_list(self) -> list[str]:
        raw = (get_settings().fanart_source or "danbooru").strip().lower()
        if raw in {"pixiv"}:
            return ["pixiv"]
        if raw in {"all", "booru", "both"}:
            return list(_BOORU_SOURCES)
        parts = [p.strip() for p in raw.replace("|", ",").split(",") if p.strip()]
        if not parts:
            return ["danbooru", "safebooru", "gelbooru"]
        out: list[str] = []
        for p in parts:
            if p in _BOORU_SOURCES or p == "pixiv":
                if p not in out:
                    out.append(p)
        return out or ["danbooru"]

    def _copyrights(self) -> tuple[str, ...]:
        return parse_csv_tags(
            get_settings().fanart_danbooru_copyrights, DEFAULT_COPYRIGHTS
        )

    def _exclude_tags(self) -> frozenset[str]:
        return frozenset(
            parse_csv_tags(
                get_settings().fanart_danbooru_exclude_tags, DEFAULT_EXCLUDE_TAGS
            )
        )

    def _enabled(self) -> bool:
        s = get_settings()
        if not s.fanart_channel_id:
            return False
        sources = self._source_list()
        if sources == ["pixiv"]:
            return bool(s.fanart_rss_url.strip() or s.fanart_pixiv_tag.strip())
        return True

    @tasks.loop(minutes=5)
    async def poll_fanart(self) -> None:
        if not self._enabled():
            return
        await self._run_poll()

    @poll_fanart.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()
        minutes = max(5, int(get_settings().fanart_poll_minutes or 5))
        self.poll_fanart.change_interval(minutes=minutes)

    fanart = app_commands.Group(name="fanart", description="二創轉發（僅管理者）")

    @fanart.command(name="status", description="查看二創轉發設定")
    @owner_only()
    async def fanart_status(self, interaction: discord.Interaction) -> None:
        s = get_settings()
        on = self._enabled()
        sources = self._source_list()
        next_in = "—"
        if self.poll_fanart.is_running():
            nxt = self.poll_fanart.next_iteration
            next_in = str(nxt) if nxt else "（等待中）"
        excludes = sorted(self._exclude_tags())
        if sources == ["pixiv"]:
            mode = "RSSHub" if s.fanart_rss_url.strip() else "直接 Pixiv AJAX"
            detail = (
                f"取圖：{mode}\n"
                f"Tag：`{s.fanart_pixiv_tag}`\n"
                f"RSS：`{s.fanart_rss_url or '（未設）'}`\n"
            )
        else:
            gel_ok = bool(s.fanart_gelbooru_api_key.strip() and s.fanart_gelbooru_user_id.strip())
            detail = (
                f"模式：全時期高分（不限新舊）｜輪流來源\n"
                f"分級：`{s.fanart_danbooru_rating}`（擋住 18+）\n"
                f"最低分數：`{s.fanart_danbooru_min_score}`\n"
                f"遊戲白名單：{len(self._copyrights())} 款\n"
                f"Gelbooru API：{'已設' if gel_ok else '未設（會跳過）'}\n"
                f"排除 tag（{len(excludes)}）：`{'`, `'.join(excludes)}`\n"
            )
        text = (
            f"啟用：{'是' if on else '否（請設 FANART_CHANNEL_ID）'}\n"
            f"來源：`{', '.join(sources)}`\n"
            f"頻道：`{s.fanart_channel_id or '—'}`\n"
            f"{detail}"
            f"間隔：{s.fanart_poll_minutes} 分｜每次最多 {s.fanart_max_per_poll} 張\n"
            f"下次：{next_in}"
        )
        await interaction.response.send_message(text, ephemeral=True)

    @fanart.command(name="once", description="立刻抓一次（測試用）")
    @owner_only()
    async def fanart_once(self, interaction: discord.Interaction) -> None:
        if not self._enabled():
            await interaction.response.send_message(
                "尚未啟用：請在 `.env` 設定 `FANART_CHANNEL_ID` 後重啟。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        posted = await self._run_poll()
        await interaction.followup.send(f"完成：本次新發送 **{posted}** 張。", ephemeral=True)

    async def _run_poll(self) -> int:
        if self._busy:
            return 0
        self._busy = True
        try:
            return await self._poll_impl()
        finally:
            self._busy = False

    async def _poll_impl(self) -> int:
        s = get_settings()
        channel = self.bot.get_channel(s.fanart_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(s.fanart_channel_id)
            except Exception as exc:
                log.warning("fanart channel fetch failed: %s", exc)
                return 0
        if not isinstance(channel, discord.TextChannel):
            log.warning("fanart channel %s is not a text channel", s.fanart_channel_id)
            return 0

        sources = self._source_list()
        if sources == ["pixiv"]:
            return await self._poll_pixiv(channel)

        # Rotate booru sources; if one yields 0, try the next once.
        n = len(sources)
        for i in range(n):
            name = sources[(self._source_rot + i) % n]
            posted = await self._poll_booru(channel, name)
            if posted > 0:
                self._source_rot = (self._source_rot + i + 1) % n
                return posted
        self._source_rot = (self._source_rot + 1) % max(n, 1)
        return 0

    async def _poll_booru(self, channel: discord.TextChannel, name: str) -> int:
        s = get_settings()
        repo = self.bot.repo  # type: ignore[attr-defined]
        if name == "danbooru":
            client: DanbooruClient | SafebooruClient | GelbooruClient = DanbooruClient()
            query = s.fanart_danbooru_tags.strip() or build_search_tags(
                "", s.fanart_danbooru_rating
            )
        elif name == "safebooru":
            client = SafebooruClient()
            query = build_safebooru_tags()
        elif name == "gelbooru":
            client = GelbooruClient(
                api_key=s.fanart_gelbooru_api_key,
                user_id=s.fanart_gelbooru_user_id,
            )
            if not client.configured:
                return 0
            query = build_gelbooru_tags(True)
        else:
            return 0

        games = self._copyrights()
        allowed = frozenset(games)
        allowed_ratings = _ratings_from_setting(s.fanart_danbooru_rating)
        min_score = int(s.fanart_danbooru_min_score or 0)
        excludes = self._exclude_tags()

        max_page_scan = 6
        unseen: list[BooruPost] = []
        for _ in range(max_page_scan):
            page = self._score_page.get(name, 1)
            raw_items = await client.search_posts(query, limit=40, page=page)
            items = [
                p
                for p in raw_items
                if passes_quality(
                    p,
                    min_score=min_score,
                    allowed_copyrights=allowed,
                    exclude_tags=excludes,
                    allowed_ratings=allowed_ratings,
                )
            ]
            items.sort(key=lambda p: p.score, reverse=True)
            unseen = [
                item
                for item in items
                if not await repo.fanart_was_sent(name, item.post_id)
            ]
            if unseen:
                break
            if not raw_items:
                self._score_page[name] = 1
                break
            self._score_page[name] = page + 1
            if self._score_page[name] > 100:
                self._score_page[name] = 1
                break

        if not unseen:
            log.info("fanart %s: no unseen query=%r page=%s", name, query, self._score_page.get(name))
            return 0

        max_post = max(1, int(s.fanart_max_per_poll or 1))
        to_post = unseen[:max_post]
        for item in unseen[max_post:]:
            await repo.fanart_mark_sent(name, item.post_id, item.title)

        posted = 0
        for item in to_post:
            ok = await self._post_booru(channel, client, item)
            await repo.fanart_mark_sent(name, item.post_id, item.title)
            if ok:
                posted += 1
        return posted

    async def _post_booru(
        self,
        channel: discord.TextChannel,
        client: DanbooruClient | SafebooruClient | GelbooruClient,
        item: BooruPost,
    ) -> bool:
        downloaded = await client.download_image(item.image_url)
        if downloaded is None:
            log.warning("fanart: could not download %s #%s", item.source_name, item.post_id)
            return False

        data, ext = downloaded
        # Discord Level 3 boost upload cap = 100MB; leave a small margin.
        if len(data) > 95 * 1024 * 1024:
            log.warning(
                "fanart: skip %s #%s — file too large (%s bytes)",
                item.source_name,
                item.post_id,
                len(data),
            )
            return False
        filename = f"{item.source_name}_{item.post_id}{ext}"
        game = item.copyrights[0] if item.copyrights else item.source_name
        color = {
            "danbooru": discord.Color.green(),
            "safebooru": discord.Color.teal(),
            "gelbooru": discord.Color.orange(),
        }.get(item.source_name, discord.Color.blurple())
        embed = discord.Embed(
            title=item.title[:256],
            url=item.page_url,
            color=color,
        )
        embed.set_author(name=item.author)
        embed.add_field(
            name="來源",
            value=f"[{item.source_name}]({item.page_url})",
            inline=True,
        )
        embed.add_field(name="分數", value=str(item.score), inline=True)
        embed.add_field(name="作品", value=game.replace("_", " ")[:80], inline=True)
        if item.origin.startswith("http"):
            embed.add_field(name="原圖", value=f"[link]({item.origin})", inline=True)
        # GIF/stills can live in embed; video must be a bare attachment to play.
        if not is_video_ext(ext):
            embed.set_image(url=f"attachment://{filename}")
        embed.set_footer(text=f"{item.source_name} #{item.post_id} · rating:{item.rating}")

        try:
            await channel.send(
                embed=embed,
                file=discord.File(io.BytesIO(data), filename=filename),
            )
        except Exception as exc:
            log.warning("fanart send failed: %s", exc)
            return False
        return True

    async def _poll_pixiv(self, channel: discord.TextChannel) -> int:
        s = get_settings()
        repo = self.bot.repo  # type: ignore[attr-defined]
        client = PixivClient(cookie=s.fanart_pixiv_cookie)
        if s.fanart_rss_url.strip():
            items = await client.fetch_from_rss(s.fanart_rss_url)
        else:
            items = await client.search_illusts(
                s.fanart_pixiv_tag, mode=s.fanart_pixiv_mode, pages=1
            )
        if not items:
            return 0
        unseen = [
            item
            for item in items
            if not await repo.fanart_was_sent("pixiv", item.illust_id)
        ]
        if not unseen:
            return 0
        max_post = max(1, int(s.fanart_max_per_poll or 1))
        to_post = unseen[:max_post]
        for item in unseen[max_post:]:
            await repo.fanart_mark_sent("pixiv", item.illust_id, item.title)
        posted = 0
        for item in to_post:
            ok = await self._post_pixiv(channel, client, item)
            await repo.fanart_mark_sent("pixiv", item.illust_id, item.title)
            if ok:
                posted += 1
        return posted

    async def _post_pixiv(
        self, channel: discord.TextChannel, client: PixivClient, item: PixivIllust
    ) -> bool:
        image_url = item.thumb_url
        resolved = await client.resolve_image_url(item.illust_id, fallback_thumb=item.thumb_url)
        if resolved:
            image_url = resolved
        if not image_url:
            return False
        downloaded = await client.download_image(image_url)
        if downloaded is None and item.thumb_url and item.thumb_url != image_url:
            downloaded = await client.download_image(item.thumb_url)
        if downloaded is None:
            return False
        data, ext = downloaded
        filename = f"pixiv_{item.illust_id}{ext}"
        embed = discord.Embed(
            title=item.title[:256],
            url=item.page_url,
            color=discord.Color.blurple(),
        )
        embed.set_author(name=item.author)
        embed.add_field(name="來源", value=f"[Pixiv]({item.page_url})", inline=True)
        embed.set_image(url=f"attachment://{filename}")
        embed.set_footer(text=f"pixiv #{item.illust_id}")
        try:
            await channel.send(
                embed=embed,
                file=discord.File(io.BytesIO(data), filename=filename),
            )
        except Exception as exc:
            log.warning("fanart send failed: %s", exc)
            return False
        return True


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FanartCog(bot))
