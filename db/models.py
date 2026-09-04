from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class GuildBond(Base):
    """Per-guild shared affection for one character (everyone raises together)."""

    __tablename__ = "guild_bonds"
    __table_args__ = (UniqueConstraint("guild_id", "character_id", name="uq_guild_character"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    character_id: Mapped[str] = mapped_column(String(64), default="yuuka")
    affection: Mapped[int] = mapped_column(Integer, default=0)
    emotion: Mapped[str] = mapped_column(String(32), default="neutral")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    character_id: Mapped[str] = mapped_column(String(64), default="yuuka", index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GalleryItem(Base):
    __tablename__ = "gallery"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    character_id: Mapped[str] = mapped_column(String(64), default="yuuka")
    path: Mapped[str] = mapped_column(String(512))
    prompt: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(String(16), default="normal")
    emotion: Mapped[str | None] = mapped_column(String(32), nullable=True)
    triggered_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScoreEvent(Base):
    """Audit log for affection deltas (chat / work / calendar / dislike / llm)."""

    __tablename__ = "score_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    character_id: Mapped[str] = mapped_column(String(64), default="yuuka")
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    category: Mapped[str] = mapped_column(String(32))  # chat|work|dislike|calendar|llm|milestone
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(256), default="")
    event_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuildSetting(Base):
    """Runtime flags such as reply lock / work mode (teacher-controlled)."""

    __tablename__ = "guild_settings"
    __table_args__ = (UniqueConstraint("guild_id", name="uq_guild_settings"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    locked_to_teacher: Mapped[int] = mapped_column(Integer, default=0)  # 0/1
    work_mode: Mapped[int] = mapped_column(Integer, default=0)  # 0=RP, 1=assistant
    extra_layers: Mapped[str] = mapped_column(Text, default="")  # teacher overlay notes
    # Empty => fall back to .env / config defaults. Teacher-only via （模型…）（深度…）.
    llm_model: Mapped[str] = mapped_column(String(64), default="")
    llm_depth: Mapped[str] = mapped_column(String(16), default="")  # off|high|max
    # Empty => fall back to env SD_WEBUI_URL. Teacher-only via （生圖網址…）.
    sd_webui_url: Mapped[str] = mapped_column(String(256), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
