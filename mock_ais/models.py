"""AIS data models for the mock AIS server.

These models describe vessel/AIS information only, mirroring the messages an
AIS consumer receives from AISStream.io so the backend does not depend on
mock-specific fields.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Vessel(BaseModel):
    """Static attributes describing a vessel."""

    mmsi: int = Field(
        ...,
        ge=100000000,
        le=999999999,
        description="Maritime Mobile Service Identity (9 digits)",
    )
    ship_name: str
    ship_type: int = Field(
        ...,
        ge=0,
        le=99,
        description="AIS ship type code (e.g. 70 = cargo, 80 = tanker)",
    )


class VesselPosition(BaseModel):
    """A single dynamic position report for a vessel."""

    mmsi: int
    ship_name: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    speed: float = Field(
        ...,
        ge=0.0,
        description="Speed over ground in knots",
    )
    course: float = Field(
        ...,
        ge=0.0,
        le=360.0,
        description="Course over ground in degrees (0-360)",
    )
    heading: int = Field(
        ...,
        ge=0,
        le=359,
        description="True heading in degrees, 0 if not available",
    )
    timestamp: datetime = Field(..., description="UTC time of the report")


class VesselTrajectory(BaseModel):
    """A vessel with its full sequence of position reports (internal)."""

    mmsi: int = Field(
        ...,
        ge=100000000,
        le=999999999,
        description="Maritime Mobile Service Identity (9 digits)",
    )
    ship_name: str
    ship_type: int = Field(
        ...,
        ge=0,
        le=99,
        description="AIS ship type code (e.g. 70 = cargo, 80 = tanker)",
    )
    positions: List[VesselPosition] = Field(
        ...,
        min_length=1,
        description="Chronological position reports for the vessel",
    )


# ---------------------------------------------------------------------------
# AISStream.io PositionReport wire format
# ---------------------------------------------------------------------------


class MetaData(BaseModel):
    """Top-level metadata envelope of an AISStream.io PositionReport."""

    MMSI: int
    ShipName: Optional[str] = None
    ShipType: Optional[int] = Field(default=None, ge=0, le=99)
    Latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    Longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)


class PositionReport(BaseModel):
    """The Message.PositionReport payload of an AISStream.io message."""

    UserID: int = Field(..., description="MMSI of the transmitting vessel")
    Latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    Longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    Sog: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Speed over ground in knots",
    )
    Cog: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=360.0,
        description="Course over ground in degrees (0-360)",
    )
    TrueHeading: Optional[int] = Field(
        default=None,
        ge=0,
        le=359,
        description="True heading in degrees, 0 if not available",
    )
    Timestamp: int = Field(..., description="UTC epoch seconds of the report")


class AISMessageContent(BaseModel):
    """The Message field of an AISStream.io message."""

    PositionReport: PositionReport


class AISMessage(BaseModel):
    """An AISStream.io-style PositionReport envelope sent over the WebSocket."""

    MessageType: str = "PositionReport"
    MetaData: MetaData
    Message: AISMessageContent