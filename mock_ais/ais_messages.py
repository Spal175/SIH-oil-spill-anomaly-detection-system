"""Conversion of generated vessel positions into AISStream-style messages.

Turns a generated ``VesselTrajectory`` and one of its ``VesselPosition``
reports into an ``AISMessage`` whose JSON mirrors what an AIS consumer
receives from AISStream.io (PositionReport envelope). Only AIS/vessel data
is included.

WebSocket streaming, PostgreSQL and AISStream.io connectivity are NOT
implemented here; this module only builds the message payload.
"""

from models import (
    AISMessage,
    AISMessageContent,
    MetaData,
    PositionReport,
    VesselPosition,
    VesselTrajectory,
)


def vessel_position_to_ais_message(
    vessel: VesselTrajectory,
    position: VesselPosition,
) -> AISMessage:
    """Build an AISStream-style PositionReport ``AISMessage``.

    The generated trajectory carries the vessel's static attributes (MMSI,
    ship name) while ``position`` carries the dynamic report (position,
    speed, course, heading, timestamp). Neither belongs to another vessel.
    """
    return AISMessage(
        MessageType="PositionReport",
        MetaData=MetaData(
            MMSI=vessel.mmsi,
            ShipName=vessel.ship_name,
            ShipType=vessel.ship_type,
            Latitude=position.latitude,
            Longitude=position.longitude,
        ),
        Message=AISMessageContent(
            PositionReport=PositionReport(
                UserID=vessel.mmsi,
                Latitude=position.latitude,
                Longitude=position.longitude,
                Sog=position.speed,
                Cog=position.course,
                TrueHeading=position.heading,
                Timestamp=int(position.timestamp.timestamp()),
            )
        ),
    )