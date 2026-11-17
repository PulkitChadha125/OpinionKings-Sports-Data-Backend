from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat naive datetimes from the DB as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Lifecycle(str, Enum):
    SCHEDULED = "SCHEDULED"            # known fixture, outside activation window
    PENDING_MAPPING = "PENDING_MAPPING"  # inside window but no exchange contract found yet
    ACTIVE = "ACTIVE"                  # markets open for trading (pre-match)
    LIVE = "LIVE"
    FINISHED = "FINISHED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"


class Base(DeclarativeBase):
    pass


class Fixture(Base):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(primary_key=True)
    oddspapi_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    sportsdataio_id: Mapped[str | None] = mapped_column(String(64), index=True)
    sdx_id: Mapped[str | None] = mapped_column(String(64), index=True)

    sport_id: Mapped[int | None] = mapped_column(Integer, index=True)
    sport_name: Mapped[str | None] = mapped_column(String(64))
    tournament_id: Mapped[int | None] = mapped_column(Integer)
    tournament_name: Mapped[str | None] = mapped_column(String(128))
    home: Mapped[str] = mapped_column(String(128))
    away: Mapped[str] = mapped_column(String(128))

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    original_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reschedule_count: Mapped[int] = mapped_column(Integer, default=0)

    vendor_status_id: Mapped[int | None] = mapped_column(Integer)
    lifecycle: Mapped[str] = mapped_column(String(32), default=Lifecycle.SCHEDULED.value, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    scores: Mapped[dict | None] = mapped_column(JSON)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    markets: Mapped[list["ExchangeMarket"]] = relationship(back_populates="fixture", cascade="all, delete-orphan")
    events: Mapped[list["LifecycleEvent"]] = relationship(back_populates="fixture", cascade="all, delete-orphan")


class ExchangeMarket(Base):
    """A fixture's presence on a prediction-market exchange (Kalshi, Polymarket, ...)."""

    __tablename__ = "exchange_markets"
    __table_args__ = (UniqueConstraint("fixture_id", "exchange"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="CASCADE"), index=True)
    exchange: Mapped[str] = mapped_column(String(64))
    exchange_fixture_id: Mapped[str | None] = mapped_column(String(256))
    market_count: Mapped[int] = mapped_column(Integer, default=0)
    raw: Mapped[dict | None] = mapped_column(JSON)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    fixture: Mapped[Fixture] = relationship(back_populates="markets")


class LifecycleEvent(Base):
    __tablename__ = "lifecycle_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="CASCADE"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(256))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    fixture: Mapped[Fixture] = relationship(back_populates="events")


class LatencySummary(Base):
    """Per-minute latency aggregates, kept for the vendor evaluation report."""

    __tablename__ = "latency_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    count: Mapped[int] = mapped_column(Integer)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    p50_ms: Mapped[float] = mapped_column(Float)
    p95_ms: Mapped[float] = mapped_column(Float)
    max_ms: Mapped[float] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
