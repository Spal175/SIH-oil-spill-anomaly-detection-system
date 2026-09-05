"""Pydantic schemas for AIS position updates (ingestion not implemented yet)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AisPositionUpdate(BaseModel):
    mmsi: int
    timestamp: datetime
    latitude: float
    longitude: float
    sog: Optional[float] = None
    cog: Optional[float] = None
    heading: Optional[float] = None
    nav_status: Optional[str] = None