from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.channel_clear import clear_channel_messages
from bot.checks import owner_only


def _guild_id(interaction: discord.Interaction) -> int | None:
    return interaction.guild.id if interaction.guild else None


async def _require_guild(interaction: discord.Interaction) -> int | None:
    gid = _guild_id(interaction)
    if gid is None:
        await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
    return gid


class SlashCog(commands.Cog):
    """Discord slash commands (/) — visible in the server command picker."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pipeline(self):
        return self.bot.pipeline  # type: ignore[attr-defined]

    @property
    def settings(self):
        return self.bot.settings  # type: ignore[attr-defined]

    @property
    def repo(self):
        return self.bot.repo  # type: ignore[attr-defined]

    # ── public ──────────────────────────────────────────────

    @app_commands.command(name="gallery", description="查看本伺服器最近的 CG")
    async def gallery(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        items = await self.repo.recent_gallery(
            gid,
            limit=3,
            character_id=self.settings.default_character_id,
        )
        if not items:
            await interaction.response.send_message("還沒有收藏 CG。", ephemeral=True)
            return
        files = []
        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. tier=`{item.tier}` emotion=`{item.emotion}`")
            path = Path(item.path)
            if path.exists() and path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".gif",
            }:
                files.append(discord.File(path, filename=path.name))
        await interaction.response.send_message(
            "本伺服器最近 CG：\n" + "\n".join(lines),
            files=files[:3],
        )

    @app_commands.command(name="ping", description="測試機器人是否在線")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"在。延遲約 `{latency_ms}` ms。", ephemeral=True
        )

    # ── teacher: model / depth ──────────────────────────────

    @app_commands.command(name="model", description="查看或切換 LLM 模型（僅管理者）")
    @app_commands.describe(choice="留空則查看目前設定")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="flash（快速）", value="flash"),
            app_commands.Choice(name="pro（高品質）", value="pro"),
        ]
    )
    @owner_only()
    async def model(
        self,
        interaction: discord.Interaction,
        choice: app_commands.Choice[str] | None = None,
    ) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        if choice is None:
            text = await self.pipeline.describe_llm(gid)
        else:
            text = await self.pipeline.set_model(gid, choice.value)
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="depth", description="查看或切換思考深度（僅管理者）")
    @app_commands.describe(choice="留空則查看目前設定")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="關（off）", value="off"),
            app_commands.Choice(name="high", value="high"),
            app_commands.Choice(name="max", value="max"),
        ]
    )
    @owner_only()
    async def depth(
        self,
        interaction: discord.Interaction,
        choice: app_commands.Choice[str] | None = None,
    ) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        if choice is None:
            text = await self.pipeline.describe_llm(gid)
        else:
            text = await self.pipeline.set_depth(gid, choice.value)
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(
        name="immersion",
        description="開關 DeepSeek 角色沉浸指令（僅管理者；需配合 depth≠off）",
    )
    @app_commands.describe(choice="留空則查看目前設定")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="開（on）", value="on"),
            app_commands.Choice(name="關（off）", value="off"),
        ]
    )
    @owner_only()
    async def immersion(
        self,
        interaction: discord.Interaction,
        choice: app_commands.Choice[str] | None = None,
    ) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        if choice is None:
            text = await self.pipeline.describe_llm(gid)
        else:
            text = await self.pipeline.set_immersion(gid, choice.value == "on")
        await interaction.response.send_message(text, ephemeral=True)

    # ── teacher: image group ────────────────────────────────

    image = app_commands.Group(name="image", description="生圖設定（僅管理者）")

    @image.command(name="status", description="查看生圖連線狀態")
    @owner_only()
    async def image_status(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.describe_image(gid)
        await interaction.response.send_message(text, ephemeral=True)

    @image.command(name="url", description="設定本伺服器生圖網址（例如 Tailscale）")
    @app_commands.describe(url="例如 http://100.x.y.z:7860")
    @owner_only()
    async def image_url(self, interaction: discord.Interaction, url: str) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_image_url(gid, url)
        await interaction.response.send_message(text, ephemeral=True)

    @image.command(name="off", description="關閉本伺服器生圖覆寫")
    @owner_only()
    async def image_off(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.disable_image(gid)
        await interaction.response.send_message(text, ephemeral=True)

    @image.command(name="test", description="強制出一張測試 CG（固定場景；頻道公開）")
    @owner_only()
    async def image_test(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        await interaction.response.defer(ephemeral=False)
        result = await self.pipeline.test_image(gid, interaction.user.id)
        files = []
        image_path = result.get("image_path")
        if image_path:
            path = Path(image_path)
            if path.exists() and path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".gif",
            }:
                files.append(discord.File(path, filename=path.name))
        await interaction.followup.send(result["reply"], files=files)

    @image.command(
        name="force",
        description="依近期對話記憶強制生圖（僅管理者；頻道公開）",
    )
    @owner_only()
    async def image_force(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        await interaction.response.defer(ephemeral=False)
        result = await self.pipeline.force_cg_from_memory(gid, interaction.user.id)
        files = []
        image_path = result.get("image_path")
        if image_path:
            path = Path(image_path)
            if path.exists() and path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".gif",
            }:
                files.append(discord.File(path, filename=path.name))
        await interaction.followup.send(result["reply"], files=files)

    # ── score（共用好感；對話不顯示）────────────────────────

    score = app_commands.Group(
        name="score", description="伺服器共用好感度（對話不顯示；用指令查）"
    )

    @score.command(name="show", description="查看本伺服器共用好感與生圖門檻")
    async def score_show(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.describe_score(gid)
        await interaction.response.send_message(text, ephemeral=True)

    @score.command(name="threshold", description="設定達到多少分自動生圖（僅管理者）")
    @app_commands.describe(value="1～100，達到後出圖並扣除等量分數")
    @owner_only()
    async def score_threshold(
        self, interaction: discord.Interaction, value: app_commands.Range[int, 1, 100]
    ) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_score_threshold(gid, value)
        await interaction.response.send_message(text, ephemeral=True)

    @score.command(name="set", description="直接設定共用好感數值（僅管理者）")
    @app_commands.describe(value="0～100")
    @owner_only()
    async def score_set(
        self, interaction: discord.Interaction, value: app_commands.Range[int, 0, 100]
    ) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_affection(gid, value)
        await interaction.response.send_message(text, ephemeral=True)

    # ── teacher: clear group ────────────────────────────────

    clear = app_commands.Group(name="clear", description="清除記憶／訊息／圖庫（僅管理者）")

    @clear.command(name="memory", description="清除本伺服器 bot 對話記憶")
    @owner_only()
    async def clear_memory(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.clear_memory(gid)
        await interaction.response.send_message(text, ephemeral=True)

    @clear.command(name="gallery", description="清除本伺服器 CG 資料庫紀錄")
    @owner_only()
    async def clear_gallery_cmd(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.clear_gallery(gid)
        await interaction.response.send_message(text, ephemeral=True)

    @clear.command(name="layers", description="清除老師叠加設定")
    @owner_only()
    async def clear_layers(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.clear_layers(gid)
        await interaction.response.send_message(text, ephemeral=True)

    @clear.command(name="channel", description="刪除本頻道訊息（需管理訊息權限）")
    @app_commands.describe(
        limit="掃描上限（預設 200，最大 200）",
        after_time="從今天該時間起刪，例如 10:55",
        after_message_id="從指定訊息 ID 起刪（含之後）",
    )
    @owner_only()
    async def clear_channel(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 200] = 200,
        after_time: str | None = None,
        after_message_id: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        msg_id: int | None = None
        if after_message_id:
            raw = after_message_id.strip()
            if not raw.isdigit():
                await interaction.response.send_message(
                    "after_message_id 請填純數字訊息 ID。", ephemeral=True
                )
                return
            msg_id = int(raw)
        await interaction.response.defer(ephemeral=True)
        text = await clear_channel_messages(
            channel=interaction.channel,
            bot_user=self.bot.user,
            guild=interaction.guild,
            bot_only=False,
            limit=limit,
            after_time=after_time,
            after_message_id=msg_id,
        )
        await interaction.followup.send(text, ephemeral=True)

    @clear.command(name="bot", description="只刪本頻道機器人自己發過的訊息")
    @app_commands.describe(
        limit="掃描上限（預設 200，最大 200）",
        after_time="從今天該時間起刪，例如 10:55",
        after_message_id="從指定訊息 ID 起刪（含之後）",
    )
    @owner_only()
    async def clear_bot(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 200] = 200,
        after_time: str | None = None,
        after_message_id: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("請在伺服器內使用。", ephemeral=True)
            return
        msg_id: int | None = None
        if after_message_id:
            raw = after_message_id.strip()
            if not raw.isdigit():
                await interaction.response.send_message(
                    "after_message_id 請填純數字訊息 ID。", ephemeral=True
                )
                return
            msg_id = int(raw)
        await interaction.response.defer(ephemeral=True)
        text = await clear_channel_messages(
            channel=interaction.channel,
            bot_user=self.bot.user,
            guild=interaction.guild,
            bot_only=True,
            limit=limit,
            after_time=after_time,
            after_message_id=msg_id,
        )
        await interaction.followup.send(text, ephemeral=True)

    # ── teacher: mode / note ────────────────────────────────

    mode = app_commands.Group(name="mode", description="回應模式／人設切換（僅管理者）")

    @mode.command(name="lock", description="之後只回應管理者本人")
    @owner_only()
    async def mode_lock(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_locked(gid, True)
        await interaction.response.send_message(text, ephemeral=True)

    @mode.command(name="unlock", description="解除鎖定，可回應其他人")
    @owner_only()
    async def mode_unlock(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_locked(gid, False)
        await interaction.response.send_message(text, ephemeral=True)

    @mode.command(name="work", description="切換為工作模式（關閉人設）")
    @owner_only()
    async def mode_work(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_work_mode(gid, True)
        await interaction.response.send_message(text, ephemeral=True)

    @mode.command(name="persona", description="恢復優香人設")
    @owner_only()
    async def mode_persona(self, interaction: discord.Interaction) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        text = await self.pipeline.set_work_mode(gid, False)
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="note", description="叠加一則老師設定到人設（僅管理者）")
    @app_commands.describe(text="要記下的設定內容")
    @owner_only()
    async def note(self, interaction: discord.Interaction, text: str) -> None:
        gid = await _require_guild(interaction)
        if gid is None:
            return
        reply = await self.pipeline.add_layer(gid, text)
        await interaction.response.send_message(reply, ephemeral=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            msg = str(error) or "沒有權限使用這個指令。"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SlashCog(bot))
