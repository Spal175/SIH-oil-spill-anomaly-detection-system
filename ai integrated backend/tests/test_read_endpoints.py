"""Tests for the read-side endpoints (GET oil-spills / GET vessels)."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.database.connection import get_session_factory, session_scope
from app.database.models import AisPosition, AttributionResult, OilSpill, Vessel
from app.database.repositories import AttributionRepository, OilSpillRepository
from app.main import app
from app.services.vessel_types import ship_type_label

T0 = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean():
    yield
    with get_session_factory()() as session, session.begin():
        session.execute(delete(AttributionResult))
        session.execute(delete(AisPosition))
        session.execute(delete(OilSpill))
        session.execute(delete(Vessel))


def _seed() -> dict:
    """Seed one spill, one vessel, attribution rows + a trajectory."""
    with session_scope() as s:
        s.add(Vessel(mmsi=111000001, ship_name="DEMO TANKER A", ship_type=80))
        s.add(Vessel(mmsi=111000002, ship_name="DEMO FISHER B", ship_type=30))
        s.add(AisPosition(mmsi=111000002, timestamp=T0, latitude=38.5, longitude=-9.5,
                          speed=4.0, course=60.0, heading=58.0))
        s.add(AisPosition(mmsi=111000002, timestamp=T0 - timedelta(minutes=5),
                          latitude=38.52, longitude=-9.48, speed=4.1, course=58.0, heading=57.0))
        spill = OilSpillRepository(s).create(
            detected_at=T0,
            centroid_latitude=38.5,
            centroid_longitude=-9.5,
            area=1.2e6,
            confidence=0.87,
            geometry_geojson=(
                '{"type": "Polygon", "coordinates": [[[-9.6, 38.6], [-9.4, 38.6], '
                '[-9.4, 38.4], [-9.6, 38.4], [-9.6, 38.6]]]}'
            ),
        )
        AttributionRepository(s).replace_for_spill(
            spill.id,
            [
                {"mmsi": 111000001, "distance_km": 0.8, "time_difference_minutes": 12.0,
                 "score": 0.91, "rank": 1},
                {"mmsi": 111000002, "distance_km": 3.5, "time_difference_minutes": 20.0,
                 "score": 0.62, "rank": 2},
            ],
        )
        return {"spill_id": spill.id}


def test_get_spill_detail(client):
    seed = _seed()
    resp = client.get(f"/oil-spills/{seed['spill_id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == seed["spill_id"]
    assert body["latitude"] == pytest.approx(38.5)
    assert body["longitude"] == pytest.approx(-9.5)
    assert body["geometry"]["type"] == "Polygon"
    vessels = body["candidate_vessels"]
    assert [v["rank"] for v in vessels] == [1, 2]
    assert vessels[0]["mmsi"] == 111000001
    assert vessels[0]["ship_name"] == "DEMO TANKER A"
    assert vessels[0]["ship_type"] == "Tanker"
    assert vessels[0]["attribution_score"] == pytest.approx(0.91)
    assert vessels[1]["ship_type"] == "Fishing"


def test_get_spill_not_found(client):
    assert client.get("/oil-spills/does-not-exist").status_code == 404


def test_get_spill_vessels(client):
    seed = _seed()
    resp = client.get(f"/oil-spills/{seed['spill_id']}/vessels")
    assert resp.status_code == 200, resp.text
    vessels = resp.json()
    assert len(vessels) == 2
    assert vessels[0]["mmsi"] == 111000001 and vessels[0]["rank"] == 1


def test_get_spill_vessels_not_found(client):
    assert client.get("/oil-spills/nope/vessels").status_code == 404


def test_get_vessel(client):
    _seed()
    resp = client.get("/vessels/111000001")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mmsi"] == 111000001
    assert body["ship_name"] == "DEMO TANKER A"
    assert body["ship_type"] == "Tanker"
    assert ship_type_label(80) == "Tanker"
    assert ship_type_label(None) is None


def test_get_vessel_not_found(client):
    assert client.get("/vessels/999999999").status_code == 404


def test_get_vessel_trajectory(client):
    _seed()
    resp = client.get("/vessels/111000002/trajectory")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mmsi"] == 111000002
    assert body["ship_name"] == "DEMO FISHER B"
    points = body["points"]
    assert len(points) == 2
    assert points[0]["latitude"] == pytest.approx(38.52)
    assert points[0]["sog"] == pytest.approx(4.1)
    assert points[1]["latitude"] == pytest.approx(38.5)
    # chronological order
    assert points[0]["timestamp"] < points[1]["timestamp"]


def test_get_vessel_trajectory_window(client):
    _seed()
    start = (T0 - timedelta(minutes=3)).isoformat()
    resp = client.get(f"/vessels/111000002/trajectory?start={quote(start, safe='')}")
    assert resp.status_code == 200, resp.text
    points = resp.json()["points"]
    assert len(points) == 1  # only the T0 observation remains
    assert points[0]["latitude"] == pytest.approx(38.5)


def test_get_vessel_trajectory_bad_timestamp(client):
    _seed()
    resp = client.get("/vessels/111000002/trajectory?start=not-a-time")
    assert resp.status_code == 422


def test_get_vessel_trajectory_unknown_mmsi(client):
    assert client.get("/vessels/999999999/trajectory").status_code == 404