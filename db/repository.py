from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from db.models import Base, GalleryItem, GuildBond, GuildSetting, Message, ScoreEvent


class Repository:
    def __init__(self) -> None:
        settings = get_settings()
        self.engine = create_async_engine(settings.database_url, echo=False)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_ensure_guild_settings_llm_columns)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def get_or_create_bond(
        self, guild_id: int, character_id: str = "yuuka"
    ) -> GuildBond:
        async with self.session() as session:
            bond = await session.scalar(
                select(GuildBond).where(
                    GuildBond.guild_id == guild_id,
                    GuildBond.character_id == character_id,
                )
            )
            if bond is None:
                bond = GuildBond(guild_id=guild_id, character_id=character_id)
                session.add(bond)
                await session.commit()
                await session.refresh(bond)
            return bond

    async def update_bond(
        self,
        guild_id: int,
        *,
        affection: int | None = None,
        emotion: str | None = None,
        character_id: str = "yuuka",
    ) -> GuildBond:
        async with self.session() as session:
            bond = await session.scalar(
                select(GuildBond).where(
                    GuildBond.guild_id == guild_id,
                    GuildBond.character_id == character_id,
                )
            )
            if bond is None:
                bond = GuildBond(guild_id=guild_id, character_id=character_id)
                session.add(bond)
            if affection is not None:
                bond.affection = max(0, min(100, affection))
            if emotion is not None:
                bond.emotion = emotion
            await session.commit()
            await session.refresh(bond)
            return bond

    async def get_or_create_settings(self, guild_id: int) -> GuildSetting:
        async with self.session() as session:
            row = await session.scalar(
                select(GuildSetting).where(GuildSetting.guild_id == guild_id)
            )
            if row is None:
                row = GuildSetting(guild_id=guild_id)
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return row

    async def save_settings(self, settings_row: GuildSetting) -> GuildSetting:
        async with self.session() as session:
            merged = await session.merge(settings_row)
            await session.commit()
            await session.refresh(merged)
            return merged

    async def add_message(
        self,
        *,
        guild_id: int,
        role: str,
        content: str,
        character_id: str = "yuuka",
        user_id: int | None = None,
        display_name: str | None = None,
    ) -> Message:
        async with self.session() as session:
            msg = Message(
                guild_id=guild_id,
                character_id=character_id,
                user_id=user_id,
                display_name=display_name,
                role=role,
                content=content,
            )
            session.add(msg)
            await session.commit()
            await session.refresh(msg)
            return msg

    async def recent_messages(
        self, guild_id: int, limit: int = 12, character_id: str = "yuuka"
    ) -> list[Message]:
        async with self.session() as session:
            stmt: Select[tuple[Message]] = (
                select(Message)
                .where(
                    Message.guild_id == guild_id,
                    Message.character_id == character_id,
                )
                .order_by(Message.id.desc())
                .limit(limit)
            )
            rows = list(await session.scalars(stmt))
            return list(reversed(rows))

    async def clear_messages(
        self, guild_id: int, character_id: str = "yuuka"
    ) -> int:
        async with self.session() as session:
            result = await session.execute(
                delete(Message).where(
                    Message.guild_id == guild_id,
                    Message.character_id == character_id,
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def clear_gallery(
        self, guild_id: int, character_id: str = "yuuka"
    ) -> int:
        async with self.session() as session:
            result = await session.execute(
                delete(GalleryItem).where(
                    GalleryItem.guild_id == guild_id,
                    GalleryItem.character_id == character_id,
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def add_score_event(
        self,
        *,
        guild_id: int,
        category: str,
        amount: int,
        reason: str = "",
        user_id: int | None = None,
        event_key: str | None = None,
        character_id: str = "yuuka",
    ) -> ScoreEvent:
        async with self.session() as session:
            ev = ScoreEvent(
                guild_id=guild_id,
                character_id=character_id,
                user_id=user_id,
                category=category,
                amount=amount,
                reason=reason,
                event_key=event_key,
            )
            session.add(ev)
            await session.commit()
            await session.refresh(ev)
            return ev

    async def sum_score_today(
        self, guild_id: int, category: str, character_id: str = "yuuka"
    ) -> int:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.session() as session:
            total = await session.scalar(
                select(func.coalesce(func.sum(ScoreEvent.amount), 0)).where(
                    ScoreEvent.guild_id == guild_id,
                    ScoreEvent.character_id == character_id,
                    ScoreEvent.category == category,
                    ScoreEvent.created_at >= start,
                )
            )
            return int(total or 0)

    async def has_event_key(self, guild_id: int, event_key: str) -> bool:
        async with self.session() as session:
            row = await session.scalar(
                select(ScoreEvent.id).where(
                    ScoreEvent.guild_id == guild_id,
                    ScoreEvent.event_key == event_key,
                )
            )
            return row is not None

    async def add_gallery(
        self,
        *,
        guild_id: int,
        path: str,
        prompt: str,
        tier: str,
        emotion: str | None = None,
        triggered_by_user_id: int | None = None,
        character_id: str = "yuuka",
    ) -> GalleryItem:
        async with self.session() as session:
            item = GalleryItem(
                guild_id=guild_id,
                character_id=character_id,
                path=path,
                prompt=prompt,
                tier=tier,
                emotion=emotion,
                triggered_by_user_id=triggered_by_user_id,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def recent_gallery(
        self, guild_id: int, limit: int = 5, character_id: str = "yuuka"
    ) -> list[GalleryItem]:
        async with self.session() as session:
            stmt = (
                select(GalleryItem)
                .where(
                    GalleryItem.guild_id == guild_id,
                    GalleryItem.character_id == character_id,
                )
                .order_by(GalleryItem.id.desc())
                .limit(limit)
            )
            return list(await session.scalars(stmt))

    async def gallery_since(
        self, guild_id: int, since: datetime, character_id: str = "yuuka"
    ) -> list[GalleryItem]:
        async with self.session() as session:
            stmt = (
                select(GalleryItem)
                .where(
                    GalleryItem.guild_id == guild_id,
                    GalleryItem.character_id == character_id,
                    GalleryItem.created_at >= since,
                )
                .order_by(GalleryItem.id.desc())
            )
            return list(await session.scalars(stmt))

    async def last_gallery_at(
        self, guild_id: int, character_id: str = "yuuka"
    ) -> datetime | None:
        async with self.session() as session:
            return await session.scalar(
                select(func.max(GalleryItem.created_at)).where(
                    GalleryItem.guild_id == guild_id,
                    GalleryItem.character_id == character_id,
                )
            )


def today_event_key(prefix: str, when: date | None = None) -> str:
    d = when or date.today()
    return f"{prefix}:{d.year}"


def _ensure_guild_settings_llm_columns(sync_conn) -> None:
    """SQLite create_all does not add columns; patch existing DBs."""
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "guild_settings" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("guild_settings")}
    if "llm_model" not in cols:
        sync_conn.execute(
            text("ALTER TABLE guild_settings ADD COLUMN llm_model VARCHAR(64) DEFAULT ''")
        )
    if "llm_depth" not in cols:
        sync_conn.execute(
            text("ALTER TABLE guild_settings ADD COLUMN llm_depth VARCHAR(16) DEFAULT ''")
        )
    if "sd_webui_url" not in cols:
        sync_conn.execute(
            text(
                "ALTER TABLE guild_settings ADD COLUMN sd_webui_url VARCHAR(256) DEFAULT ''"
            )
        )
