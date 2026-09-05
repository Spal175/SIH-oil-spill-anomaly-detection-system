"""Unit tests for AIS PositionReport parsing (app.workers.ais_message)."""
import json
from datetime import datetime, timezone

import pytest

from app.workers.ais_message import parse_position_report


def make_report(**overrides):
    message = {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": 205221000,
            "ShipName": "ATLANTIC CARRIER",
            "Latitude": 38.5,
            "Longitude": -9.5,
        },
        "Message": {
            "PositionReport": {
                "UserID": 205221000,
                "Latitude": 38.5,
                "Longitude": -9.5,
                "Sog": 12.3,
                "Cog": 245.0,
                "TrueHeading": 244,
                "Timestamp": 1694000000,
            }
        },
    }
    message.update(overrides)
    return message


def test_parses_valid_position_report():
    parsed = parse_position_report(make_report())
    assert parsed is not None
    assert parsed.mmsi == 205221000
    assert parsed.ship_name == "ATLANTIC CARRIER"
    assert parsed.latitude == 38.5
    assert parsed.longitude == -9.5
    assert parsed.speed == 12.3
    assert parsed.course == 245.0
    assert parsed.heading == 244
    assert parsed.timestamp_utc == datetime.fromtimestamp(1694000000, tz=timezone.utc)


def test_timestamp_is_utc_aware():
    parsed = parse_position_report(make_report())
    assert parsed.timestamp_utc.tzinfo is not None
    assert parsed.timestamp_utc.utcoffset().total_seconds() == 0


def test_accepts_json_string():
    parsed = parse_position_report(json.dumps(make_report()))
    assert parsed is not None
    assert parsed.mmsi == 205221000


def test_accepts_bytes_payload():
    parsed = parse_position_report(json.dumps(make_report()).encode())
    assert parsed is not None
    assert parsed.mmsi == 205221000


def test_ship_type_defaults_none():
    parsed = parse_position_report(make_report())
    assert parsed.ship_type is None


def test_nullable_optional_fields():
    report = make_report()
    report["Message"]["PositionReport"].update(
        {"Sog": None, "Cog": None, "TrueHeading": None}
    )
    parsed = parse_position_report(report)
    assert parsed is not None
    assert parsed.speed is None
    assert parsed.course is None
    assert parsed.heading is None


def test_missing_ship_name_ok():
    report = make_report()
    report["MetaData"]["ShipName"] = None
    parsed = parse_position_report(report)
    assert parsed is not None
    assert parsed.ship_name is None


def test_iso8601_timestamp_string():
    report = make_report()
    report["Message"]["PositionReport"]["Timestamp"] = "2023-09-06T10:13:20Z"
    parsed = parse_position_report(report)
    assert parsed is not None
    assert parsed.timestamp_utc == datetime(2023, 9, 6, 10, 13, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "kind",
    ["ShipStaticData", "Error", "Unknown", "TideData"],
)
def test_returns_none_for_non_position_report(kind):
    report = make_report()
    report["MessageType"] = kind
    assert parse_position_report(report) is None


def test_returns_none_for_garbage():
    assert parse_position_report("not json {{{") is None
    assert parse_position_report(None) is None
    assert parse_position_report(42) is None
    assert parse_position_report([]) is None


def test_returns_none_for_out_of_range_coordinates():
    report = make_report()
    report["Message"]["PositionReport"]["Latitude"] = 95.0
    assert parse_position_report(report) is None

    report = make_report()
    report["Message"]["PositionReport"]["Longitude"] = -181.0
    assert parse_position_report(report) is None

    report = make_report()
    report["Message"]["PositionReport"] = {"UserID": 205221000, "Timestamp": 1}
    report["MetaData"]["Latitude"] = None
    report["MetaData"]["Longitude"] = None
    assert parse_position_report(report) is None


def test_returns_none_without_mmsi():
    report = make_report()
    report["Message"]["PositionReport"]["UserID"] = 0
    assert parse_position_report(report) is None


def test_returns_none_without_timestamp():
    report = make_report()
    del report["Message"]["PositionReport"]["Timestamp"]
    assert parse_position_report(report) is None