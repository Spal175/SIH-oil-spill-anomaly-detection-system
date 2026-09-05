"""Pydantic schemas for vessels and vessel attribution."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VesselDetail(BaseModel):
    """Static vessel information (GET /vessels/{mmsi})."""

    mmsi: int
    ship_name: Optional[str] = None
    ship_type: Optional[str] = Field(
        default=None, description="Human-readable AIS ship type"
    )
    imo: Optional[str] = None
    created_at: Optional[datetime] = None


class TrajectoryPoint(BaseModel):
    timestamp: datetime
    latitude: float
    longitude: float
    sog: Optional[float] = None
    cog: Optional[float] = None
    heading: Optional[float] = None


class VesselTrajectory(BaseModel):
    mmsi: int
    points: list[TrajectoryPoint] = []


class VesselTrajectoryResponse(BaseModel):
    """GET /vessels/{mmsi}/trajectory."""

    mmsi: int
    ship_name: Optional[str] = None
    points: list[TrajectoryPoint] = []