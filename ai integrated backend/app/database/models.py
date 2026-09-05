"""SQLAlchemy 2.x ORM models (plain PostgreSQL).

Spatial queries use stored latitude/longitude columns plus the ``haversine_km``
SQL function (installed by the initial migration) — no PostGIS extension
required at runtime. A PostGIS ``geography(Point, 4326)`` column can be added
later in a follow-up migration for higher-volume spatial workloads.

AIS and oil-spill data are deliberately kept in separate tables; they are linked
only through ``attribution_results``.

Data flow::

    AIS feed  -> vessels + ais_positions        (ingestion, separate)
    SAR TIFF  -> ML + GIS -> oil_spills          (detection, separate)
    oil_spill + ais_positions -> attribution_results
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Text, BigInteger, DateTime, Double, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Vessel(Base):
    """A vessel identified by MMSI (static data)."""

    __tablename__ = "vessels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mmsi: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    ship_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ship_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    imo: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ais_positions: Mapped[list["AisPosition"]] = relationship(
        back_populates="vessel", cascade="all, delete-orphan"
    )
    attribution_results: Mapped[list["AttributionResult"]] = relationship(
        back_populates="vessel"
    )


class AisPosition(Base):
    """A single AIS position report (dynamic data)."""

    __tablename__ = "ais_positions"
    __table_args__ = (
        Index("ix_ais_positions_mmsi_timestamp", "mmsi", "timestamp"),
        Index("ix_ais_positions_lat_lon", "latitude", "longitude"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mmsi: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessels.mmsi", ondelete="CASCADE"), index=True, nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    latitude: Mapped[float] = mapped_column(Double, nullable=False)
    longitude: Mapped[float] = mapped_column(Double, nullable=False)
    speed: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    course: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    heading: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    vessel: Mapped[Optional["Vessel"]] = relationship(back_populates="ais_positions")


class OilSpill(Base):
    """A detected oil spill (output of ML + GIS)."""

    __tablename__ = "oil_spills"
    __table_args__ = (
        Index("ix_oil_spills_centroid_lat_lon", "centroid_latitude", "centroid_longitude"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    centroid_latitude: Mapped[float] = mapped_column(Double, nullable=False)
    centroid_longitude: Mapped[float] = mapped_column(Double, nullable=False)
    area: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    geometry_geojson: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    attribution_results: Mapped[list["AttributionResult"]] = relationship(
        back_populates="spill", cascade="all, delete-orphan"
    )


class AttributionResult(Base):
    """Attribution of an oil spill to candidate vessels via spatial+temporal query."""

    __tablename__ = "attribution_results"
    __table_args__ = (
        Index("ix_attribution_results_spill_id_rank", "spill_id", "rank"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spill_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("oil_spills.id", ondelete="CASCADE"), index=True, nullable=False
    )
    mmsi: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessels.mmsi", ondelete="CASCADE"), index=True, nullable=False
    )
    distance_km: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    time_difference_minutes: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    spill: Mapped[Optional["OilSpill"]] = relationship(back_populates="attribution_results")
    vessel: Mapped[Optional["Vessel"]] = relationship(back_populates="attribution_results")