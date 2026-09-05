"""DB tests for spatial + temporal vessel-candidate search.

Seeds ais_positions with known geometry + timestamps relative to a synthetic
spill at lat=10.0, lon=20.0, detection_time=2023-01-01T12:00 UTC.

Window defaults: before=60, after=0 -> [11:00 .. 12:00 UTC].
Search radius: 10 km.

Layout:
  Vessel A (111000001 DEMO TANKER A) — two obs inside, one far, one early, one late
  Vessel B (111000002 DEMO FISHER B) — three obs approaching (closest ~1.1 km)
  Vessel C (111000003 DEMO CARG C)   — one obs at ~6.7 km, no speed/heading
"""
from datetime import datetime, timedelta, timezone
from math import atan2, cos, pow, radians, sin, sqrt

import pytest
from sqlalchemy import delete

from app.config import settings
from app.database.connection import get_session_factory
from app.database.models import AisPosition, Vessel
from app.services.ais_service import AISVesselSearch, ais_vessel_search

BASE_LAT, BASE_LON = 10.0, 20.0
T0 = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
MMSIS = (111000001, 111000002, 111000003)


def _haversine_km(lat1, lon1, lat2, lon2):
    """Reference haversine matching the SQL function."""
    R = 6371.0088
    rlat1, rlon1, rlat2, rlon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
    return R * 2.0 * atan2(sqrt(a), sqrt(1 - a))


# ── seed / teardown ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _seed_and_clean():
    # Full isolation: clear all AIS/vessel rows first so leftover mock-server /
    # prior-run data can never affect the spatial+temporal assertions.
    with get_session_factory()() as s, s.begin():
        s.execute(delete(AisPosition))
        s.execute(delete(Vessel))

    with get_session_factory()() as s, s.begin():
        for mmsi, name in [
            (111000001, "DEMO TANKER A"),
            (111000002, "DEMO FISHER B"),
            (111000003, "DEMO CARG C"),
        ]:
            s.add(Vessel(mmsi=mmsi, ship_name=name))

        rows = [
            # ── Vessel A ────────────────────────────────────────────
            # inside window + radius (two)
            (111000001, T0 - timedelta(minutes=30), BASE_LAT + 0.05, BASE_LON, 12.0, None, 45.0),
            (111000001, T0 - timedelta(minutes=10), BASE_LAT + 0.02, BASE_LON, 13.5, None, 46.0),
            # inside window but OUTSIDE radius
            (111000001, T0 - timedelta(minutes=20), BASE_LAT + 0.40, BASE_LON, 11.0, None, None),
            # inside radius but OUTSIDE window (too early)
            (111000001, T0 - timedelta(minutes=90), BASE_LAT + 0.07, BASE_LON, 11.0, None, 44.0),
            # inside radius but OUTSIDE window (too late)
            (111000001, T0 + timedelta(minutes=5),  BASE_LAT + 0.01, BASE_LON, 10.0, None, None),
            # ── Vessel B (approaching) ──────────────────────────────
            (111000002, T0 - timedelta(minutes=40), BASE_LAT + 0.08, BASE_LON, 9.0, None, 20.0),
            (111000002, T0 - timedelta(minutes=20), BASE_LAT + 0.04, BASE_LON, None, None, 22.0),
            (111000002, T0 - timedelta(minutes=5),  BASE_LAT + 0.01, BASE_LON, 8.0, None, 30.0),
            # ── Vessel C (distant, sparse) ──────────────────────────
            (111000003, T0 - timedelta(minutes=35), BASE_LAT + 0.06, BASE_LON, None, None, None),
        ]
        for mmsi, ts, lat, lon, spd, course, hdg in rows:
            s.add(AisPosition(
                mmsi=mmsi, timestamp=ts, latitude=lat, longitude=lon,
                speed=spd, course=course, heading=hdg,
            ))

    yield

    with get_session_factory()() as s, s.begin():
        s.execute(delete(AisPosition))
        s.execute(delete(Vessel))


# ── repository-level query tests ─────────────────────────────────────────

def test_repo_returns_only_in_radius_and_in_window():
    start = T0 - timedelta(minutes=60)
    end = T0
    with get_session_factory()() as session:
        from app.database.repositories import AISSearchRepository

        repo = AISSearchRepository(session)
        rows = repo.positions_around_point(BASE_LAT, BASE_LON, 10.0, start, end)

    assert len(rows) == 6  # A:2, B:3, C:1

    for pos, ship_name, dist, ship_type in rows:
        assert dist <= 10.0
        # pos.timestamp is already timezone-aware; compare instants directly.
        assert start <= pos.timestamp <= end
        assert ship_name is not None


def test_repo_excludes_out_of_window_and_out_of_radius():
    start = T0 - timedelta(minutes=60)
    end = T0
    with get_session_factory()() as session:
        from app.database.repositories import AISSearchRepository

        repo = AISSearchRepository(session)
        rows = repo.positions_around_point(BASE_LAT, BASE_LON, 10.0, start, end)
        by_ts = {(pos.mmsi, pos.timestamp): dist for pos, _, dist, _ in rows}

    # Too early (T0-90) and too late (T0+5) are outside the window -> excluded.
    assert (111000001, T0 - timedelta(minutes=90)) not in by_ts
    assert (111000001, T0 + timedelta(minutes=5)) not in by_ts
    # A's out-of-radius row (T0-20 at lat 10.40, ~44 km) is excluded by distance.
    assert (111000001, T0 - timedelta(minutes=20)) not in by_ts


# ── service-level grouping + feature tests ────────────────────────────────

def test_service_groups_by_mmsi_and_orders_by_proximity():
    candidates = ais_vessel_search.search_candidates(
        BASE_LAT, BASE_LON, T0, radius_km=10.0,
        before_minutes=60, after_minutes=0,
    )
    assert len(candidates) == 3
    mmis = [c["mmsi"] for c in candidates]
    assert mmis[0] == 111000002   # B — closest ~1.1 km
    assert mmis[1] == 111000001   # A — ~2.2 km
    assert mmis[2] == 111000003   # C — ~6.7 km


def test_candidate_features():
    candidates = ais_vessel_search.search_candidates(
        BASE_LAT, BASE_LON, T0, radius_km=10.0,
    )
    by_mmsi = {c["mmsi"]: c for c in candidates}

    # ── Vessel B ──────────────────────────────────────────────────
    b = by_mmsi[111000002]
    assert b["ship_name"] == "DEMO FISHER B"
    assert b["observation_count"] == 3
    assert b["min_distance_km"] == pytest.approx(
        _haversine_km(BASE_LAT, BASE_LON, BASE_LAT + 0.01, BASE_LON), abs=0.01
    )
    assert b["time_difference_minutes"] == 5.0
    assert b["approached_or_crossed_spill"] is True
    assert b["avg_speed_knots"] is not None and b["avg_speed_knots"] > 0
    assert b["heading"] == pytest.approx(30.0)

    # ── Vessel A ──────────────────────────────────────────────────
    a = by_mmsi[111000001]
    assert a["ship_name"] == "DEMO TANKER A"
    assert a["observation_count"] == 2
    assert a["min_distance_km"] == pytest.approx(
        _haversine_km(BASE_LAT, BASE_LON, BASE_LAT + 0.02, BASE_LON), abs=0.01
    )
    assert a["time_difference_minutes"] == 10.0
    assert a["approached_or_crossed_spill"] is True
    assert a["avg_speed_knots"] == pytest.approx((12.0 + 13.5) / 2, abs=0.01)
    assert a["heading"] == pytest.approx(46.0)

    # ── Vessel C ──────────────────────────────────────────────────
    c = by_mmsi[111000003]
    assert c["ship_name"] == "DEMO CARG C"
    assert c["observation_count"] == 1
    assert c["approached_or_crossed_spill"] is False
    assert c["avg_speed_knots"] is None
    assert c["heading"] is None


def test_after_window_included_when_increased():
    default = ais_vessel_search.search_candidates(
        BASE_LAT, BASE_LON, T0, radius_km=10.0, after_minutes=0,
    )
    with_after = ais_vessel_search.search_candidates(
        BASE_LAT, BASE_LON, T0, radius_km=10.0, after_minutes=10,
    )
    a_def = next(c for c in default if c["mmsi"] == 111000001)
    a_aft = next(c for c in with_after if c["mmsi"] == 111000001)
    assert a_def["observation_count"] == 2
    assert a_aft["observation_count"] == 3
    # The T0+5min row (only included once after_window>0) is A's closest at ~1.11 km.
    assert a_def["min_distance_km"] == pytest.approx(2.2239, abs=0.05)
    assert a_aft["min_distance_km"] == pytest.approx(1.1119, abs=0.05)


def test_no_radius_override_means_config_default():
    search = AISVesselSearch()
    assert search.radius_km == settings.ais_search_radius_km
    assert search.before_minutes == settings.ais_time_before_minutes
    assert search.after_minutes == settings.ais_time_after_minutes


def test_naive_detection_time_treated_as_utc():
    naive = datetime(2023, 1, 1, 12, 0, 0)  # no tzinfo
    candidates = ais_vessel_search.search_candidates(
        BASE_LAT, BASE_LON, naive, radius_km=10.0, before_minutes=60,
    )
    assert len(candidates) == 3