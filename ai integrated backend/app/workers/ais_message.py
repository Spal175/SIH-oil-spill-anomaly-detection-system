"""Parse AISStream.io-style PositionReport messages.

Wire contract (matches the mock AIS server, an emulation of AISStream.io)::

    {
      "MessageType": "PositionReport",
      "MetaData": {"MMSI": 123, "ShipName": "...", "ShipType": 80,
                   "Latitude": .., "Longitude": ..},
      "Message": {"PositionReport": {
        "UserID": 123, "Latitude": .., "Longitude": ..,
        "Sog": .., "Cog": .., "TrueHeading": .., "Timestamp": <epoch seconds>
      }}
    }

Only the fields the backend needs are extracted. Ship type is carried by the
optional ``MetaData.ShipType`` field (AISStream.io metadata convention); when
absent it stays None.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

POSITION_REPORT = "PositionReport"


@dataclass(frozen=True)
class ParsedPosition:
    """A normalized, validated single AIS position report."""

    mmsi: int
    latitude: float
    longitude: float
    timestamp: datetime
    speed: Optional[float]
    course: Optional[float]
    heading: Optional[float]
    ship_name: Optional[str]
    ship_type: Optional[int] = None

    @property
    def timestamp_utc(self) -> datetime:
        """Timestamp normalized to UTC (tz-aware)."""
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _valid_latlon(lat: Optional[float], lon: Optional[float]) -> bool:
    if lat is None or lon is None:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Interpret the wire timestamp as UTC datetime.

    Accepts epoch seconds (int/float) as sent by the mock server, ISO-8601
    strings, or a datetime object.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def parse_position_report(raw: Any) -> Optional[ParsedPosition]:
    """Parse a raw websocket payload into a validated ParsedPosition.

    Returns None for non-PositionReport envelopes, malformed JSON, or messages
    whose required fields are missing / out of range. The caller simply skips
    anything that parses to None.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, dict):
        data = raw
    else:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("MessageType") != POSITION_REPORT:
        return None

    meta = data.get("MetaData") or {}
    message = data.get("Message") or {}
    report = message.get("PositionReport") or {}

    latitude = _coerce_float(report.get("Latitude", meta.get("Latitude")))
    longitude = _coerce_float(report.get("Longitude", meta.get("Longitude")))
    if not _valid_latlon(latitude, longitude):
        return None

    mmsi = _coerce_int(report.get("UserID", meta.get("MMSI")))
    if mmsi is None or mmsi <= 0:
        return None

    timestamp = parse_timestamp(report.get("Timestamp"))
    if timestamp is None:
        return None

    return ParsedPosition(
        mmsi=mmsi,
        latitude=latitude,
        longitude=longitude,
        timestamp=timestamp,
        speed=_coerce_float(report.get("Sog")),
        course=_coerce_float(report.get("Cog")),
        heading=_coerce_float(report.get("TrueHeading")),
        ship_name=_coerce_ship_name(meta.get("ShipName")),
        ship_type=_coerce_int(meta.get("ShipType")),
    )


def _coerce_ship_name(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None