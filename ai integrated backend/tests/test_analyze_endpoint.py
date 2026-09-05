"""End-to-end tests for POST /oil-spills/analyze.

Happy path exercises the REAL pipeline on disk:
    GeoTIFF (multipart upload) -> temp file -> ML U-Net -> 0/1 mask
    -> GIS georeferencing -> lat/lon + timestamp -> PostgreSQL row
    -> attribution scoring + persistence -> nested response

Error paths stub a single stage to keep them fast and deterministic.
"""
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.database.connection import get_session_factory
from app.database.models import AttributionResult, OilSpill, Vessel
from app.main import app
from app.services.attribution_service import attribution_service
from app.services.ml_service import OilSpillPrediction

FIXTURES = Path(__file__).parent / "fixtures"
GEO_REF_TIFF = FIXTURES / "sample_scene_georef.tif"
PLAIN_TIFF = FIXTURES / "sample_scene.tif"

LON_RANGE = (-9.0, -8.872)
LAT_RANGE = (39.372, 39.5)


def _bytes(path: Path) -> bytes:
    return path.read_bytes()


def _upload(client: TestClient, path: Path, name: str = "scene.tiff"):
    return client.post(
        "/oil-spills/analyze",
        files={"file": (name, _bytes(path), "image/tiff")},
    )


def _count_spills() -> int:
    with get_session_factory()() as session:
        return session.execute(
            select(func.count()).select_from(OilSpill)
        ).scalar_one()


def _count_attribution() -> int:
    with get_session_factory()() as session:
        return session.execute(
            select(func.count()).select_from(AttributionResult)
        ).scalar_one()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _spills_clean():
    yield
    with get_session_factory()() as session, session.begin():
        for spill in session.execute(select(OilSpill)).scalars():
            session.delete(spill)


def test_analyze_happy_path_persists_spill(client):
    before = _count_spills()
    resp = _upload(client, GEO_REF_TIFF)

    assert resp.status_code == 201, resp.text
    body = resp.json()

    spill = body["spill"]
    assert spill is not None
    assert isinstance(spill["id"], str) and spill["id"]
    assert spill["crs"] == "EPSG:4326"
    assert LON_RANGE[0] <= spill["longitude"] <= LON_RANGE[1]
    assert LAT_RANGE[0] <= spill["latitude"] <= LAT_RANGE[1]
    assert spill["area"] is not None and spill["area"] >= 0.0
    assert spill["confidence"] is not None and 0.0 <= spill["confidence"] <= 1.0
    # detected_at is the acquisition time (absent in fixture -> process time)
    assert spill["detected_at"] is not None
    assert spill["region_count"] is not None and spill["region_count"] >= 1

    assert isinstance(body["candidate_vessels"], list)

    assert _count_spills() == before + 1

    # Row is real and fetchable.
    with get_session_factory()() as session:
        stored = session.get(OilSpill, spill["id"])
        assert stored is not None
        assert stored.centroid_latitude == pytest.approx(spill["latitude"])
        assert stored.centroid_longitude == pytest.approx(spill["longitude"])
        assert stored.confidence == pytest.approx(spill["confidence"])


def test_analyze_attributes_and_persists_candidates(client, monkeypatch):
    canned = [
        {
            "rank": 1,
            "mmsi": 111000001,
            "ship_name": "DEMO TANKER A",
            "ship_type": 80,
            "min_distance_km": 0.8,
            "time_difference_minutes": 12.0,
            "score": 0.91,
            "evidence": ["Vessel passed within 0.8 km of the detected spill"],
            "observation_count": 4,
        },
        {
            "rank": 2,
            "mmsi": 111000002,
            "ship_name": "DEMO FISHER B",
            "ship_type": 30,
            "min_distance_km": 3.5,
            "time_difference_minutes": 20.0,
            "score": 0.62,
            "evidence": ["Vessel passed within 3.5 km of the detected spill"],
            "observation_count": 2,
        },
    ]
    # Deterministic scoring: attribute() returns canned ranking; the real
    # store_results() then persists them into attribution_results. The MMSIs
    # must exist in `vessels` (attribution_results.mmsi is a FK to it).
    seeded_mmsis = (111000001, 111000002)
    with get_session_factory()() as session, session.begin():
        session.add_all([
            Vessel(mmsi=111000001, ship_name="DEMO TANKER A", ship_type=80),
            Vessel(mmsi=111000002, ship_name="DEMO FISHER B", ship_type=30),
        ])
    monkeypatch.setattr(attribution_service, "attribute", lambda *a, **k: canned)

    try:
        before = _count_spills()
        resp = _upload(client, GEO_REF_TIFF)

        assert resp.status_code == 201, resp.text
        body = resp.json()
        spill_id = body["spill"]["id"]

        vessels = body["candidate_vessels"]
        assert [v["rank"] for v in vessels] == [1, 2]
        top = vessels[0]
        assert top["mmsi"] == 111000001
        assert top["ship_name"] == "DEMO TANKER A"
        assert top["ship_type"] == "Tanker"  # AIS code 80 -> label
        assert top["distance_km"] == pytest.approx(0.8)
        assert top["time_difference_minutes"] == pytest.approx(12.0)
        assert top["attribution_score"] == pytest.approx(0.91)
        assert top["evidence"]
        assert vessels[1]["ship_type"] == "Fishing"  # AIS code 30 -> label

        # attribution_results rows persisted under the created spill.
        with get_session_factory()() as session:
            rows = session.execute(
                select(AttributionResult).where(AttributionResult.spill_id == spill_id)
            ).scalars().all()
        assert len(rows) == 2
        assert {r.rank for r in rows} == {1, 2}
        assert {r.mmsi for r in rows} == {111000001, 111000002}

        # Re-running analyzes replaces, never duplicates, attribution rows.
        assert _count_attribution() == 2
    finally:
        with get_session_factory()() as session, session.begin():
            session.execute(
                delete(AttributionResult).where(
                    AttributionResult.mmsi.in_(seeded_mmsis)
                )
            )
            session.execute(delete(OilSpill))
            session.execute(delete(Vessel).where(Vessel.mmsi.in_(seeded_mmsis)))


def test_analyze_no_oil_returns_200_and_no_db_record(client, monkeypatch):
    prob = np.zeros((256, 256), dtype=np.float32)
    fake = OilSpillPrediction(
        mask=np.zeros((256, 256), dtype=np.uint8),
        mask_shape=(256, 256),
        input_shape=(256, 256),
        threshold=0.5,
        confidence=0.5,
        oil_pixels=0,
        detected=False,
        model_version="stub",
        probability=prob,
    )
    monkeypatch.setattr(
        "app.services.oil_spill_analysis.ml_service.predict", lambda *a, **k: fake
    )

    before = _count_spills()
    resp = _upload(client, GEO_REF_TIFF)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["spill"] is None
    assert body["candidate_vessels"] == []
    assert _count_spills() == before


def test_unsupported_extension_returns_415(client):
    resp = client.post(
        "/oil-spills/analyze",
        files={"file": ("scene.png", b"not a tiff", "image/png")},
    )
    assert resp.status_code == 415
    assert "Traceback" not in resp.text


def test_invalid_tiff_content_returns_400(client):
    resp = client.post(
        "/oil-spills/analyze",
        files={"file": ("broken.tiff", b"this is not a tiff file", "image/tiff")},
    )
    assert resp.status_code == 400
    assert "Traceback" not in resp.text


def test_not_georeferenced_tiff_returns_400(client):
    resp = _upload(client, PLAIN_TIFF)
    assert resp.status_code == 400, resp.text
    assert "Traceback" not in resp.text


def test_ml_failure_returns_502(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.oil_spill_analysis.ml_service.predict",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    resp = _upload(client, GEO_REF_TIFF)
    assert resp.status_code == 502
    assert "Traceback" not in resp.text
    assert _count_spills() == 0


def test_gis_failure_returns_500(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.oil_spill_analysis.gis_service.extract",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    resp = _upload(client, GEO_REF_TIFF)
    assert resp.status_code == 500
    assert "Traceback" not in resp.text
    assert _count_spills() == 0


def test_db_failure_returns_503(client, monkeypatch):
    def boom(*a, **k):
        raise OSError("database down")

    monkeypatch.setattr("app.services.oil_spill_analysis.OilSpillRepository.create", boom)
    resp = _upload(client, GEO_REF_TIFF)
    assert resp.status_code == 503
    assert "Traceback" not in resp.text
    assert _count_spills() == 0


def test_attribution_failure_keeps_detection(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ais search down")

    monkeypatch.setattr(attribution_service, "attribute", boom)
    resp = _upload(client, GEO_REF_TIFF)
    # The spill (primary outcome) is still saved and returned.
    assert resp.status_code == 201, resp.text
    assert resp.json()["spill"]["id"]
    assert resp.json()["candidate_vessels"] == []
    assert _count_spills() == 1