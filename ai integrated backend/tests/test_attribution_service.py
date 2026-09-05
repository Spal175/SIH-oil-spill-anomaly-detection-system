"""Deterministic tests for the vessel attribution service.

The scenario simulates the mock-AIS demo_01 idea: a spill at a real coordinate,
several candidate vessels at differing distances/times/density. Vessel A passes
closest to the spill within the relevant time window, so it SHOULD rank #1 —
but the score is computed from the AIS observations, never hardcoded per MMSI.

We assert:
  * the ranking order (data-driven),
  * that scores are derived from distance/time/count/approach, in [0,1],
  * that A's score exceeds B's and C's, and that shifting the evidence changes
    the score (no hardcoded constants),
  * persistence into attribution_results.
"""
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.services.attribution_service import (
    _WEIGHT_SUM,
    AttributionService,
    attribution_service,
)

T0 = datetime(2023, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
SPILL_LAT, SPILL_LON = 38.40, -9.65  # near DEMO TANKER A's track (see demo_01)

RADIUS_KM = 10.0


def _obs(lat, lon, minutes_before, speed=None, course=None):
    return {
        "timestamp": (T0 - timedelta(minutes=minutes_before)).isoformat(),
        "latitude": lat,
        "longitude": lon,
        "speed": speed,
        "course": course,
        "heading": course,
        "distance_km": None,
    }


def _candidate(mmsi, name, ship_type, min_dist, td_min, obs, approached):
    return {
        "mmsi": mmsi,
        "ship_name": name,
        "ship_type": ship_type,
        "min_distance_km": min_dist,
        "closest_observation_timestamp": (T0 - timedelta(minutes=td_min)).isoformat(),
        "time_difference_minutes": float(td_min),
        "observation_count": len(obs),
        "approached_or_crossed_spill": approached,
        "avg_speed_knots": 12.5 if obs else None,
        "heading": obs[0]["heading"] if obs else None,
        "observations": obs,
    }


@pytest.fixture
def demo_candidates():
    """Deterministic candidates mirroring the demo scenario geometry."""
    return [
        # DEMO TANKER A: passes ~0.8 km away, 12 min before, 4 observations
        # along a steady NE course -> strongest overall evidence.
        _candidate(
            111000001, "DEMO TANKER A", "Tanker", 0.8, 12.0,
            [_obs(38.38, -9.66, 20, 13.0, 40.0),
             _obs(38.39, -9.655, 16, 13.0, 40.0),
             _obs(38.40, -9.65, 12, 13.0, 40.0),
             _obs(38.41, -9.645, 8, 13.0, 40.0)],
            approached=True,
        ),
        # DEMO FISHER B: near (2.2 km) and 5 min before, but fewer observations
        # and a wandering course -> ranks below A on approach/count/consistency.
        _candidate(
            111000002, "DEMO FISHER B", "Fishing", 2.2, 5.0,
            [_obs(38.385, -9.665, 6, 4.0, 50.0),
             _obs(38.39, -9.65, 5, 4.0, 20.0)],
            approached=True,
        ),
        # DEMO CARGO C: farther (6.7 km), a single observation, no approach
        # flag -> weakest.
        _candidate(
            111000003, "DEMO CARGO C", "Cargo", 6.7, 40.0,
            [_obs(38.45, -9.6, 40, 15.0, 90.0)],
            approached=False,
        ),
        # A distractor well outside the radius with no observations.
        _candidate(
            111000009, "DEMO COASTER I", "Cargo", 12.0, 90.0, [], approached=False,
        ),
    ]


def test_ranks_expected_demo_vessel_first(demo_candidates):
    ranked = attribution_service.attribute(
        SPILL_LAT, SPILL_LON, T0,
        radius_km=RADIUS_KM,
        search_results=[dict(c) for c in demo_candidates],
    )
    assert [r["mmsi"] for r in ranked] == [111000001, 111000002, 111000003, 111000009]
    assert ranked[0]["rank"] == 1
    assert ranked[0]["ship_name"] == "DEMO TANKER A"
    assert ranked[0]["score"] > ranked[1]["score"] > ranked[2]["score"]


def test_scores_are_data_derived_and_bounded(demo_candidates):
    ranked = attribution_service.attribute(
        SPILL_LAT, SPILL_LON, T0,
        radius_km=RADIUS_KM,
        search_results=[dict(c) for c in demo_candidates],
    )
    for r in ranked:
        assert 0.0 <= r["score"] <= 1.0
        assert r["evidence"]
        assert r["rank"] == ranked.index(r) + 1
        # score is not a constant for every vessel -> data-driven
        assert len({r["score"] for r in ranked}) == len(ranked)


def test_moving_tank_a_farther_lowers_its_score(demo_candidates):
    a = dict(demo_candidates[0])
    a["min_distance_km"] = 8.0
    a["approached_or_crossed_spill"] = False
    far = attribution_service.attribute(
        SPILL_LAT, SPILL_LON, T0,
        radius_km=RADIUS_KM,
        search_results=[dict(demo_candidates[1]), a, dict(demo_candidates[2])],
    )
    by_mmsi = {r["mmsi"]: r for r in far}
    near = attribution_service.attribute(
        SPILL_LAT, SPILL_LON, T0,
        radius_km=RADIUS_KM,
        search_results=[dict(c) for c in demo_candidates],
    )
    near_a = next(r for r in near if r["mmsi"] == 111000001)
    assert by_mmsi[111000001]["score"] != near_a["score"]  # changed
    # Moving A far away drops it behind B, who is now the closest.
    assert by_mmsi[111000002]["score"] > by_mmsi[111000001]["score"]


def test_evidence_is_human_readable(demo_candidates):
    ranked = attribution_service.attribute(
        SPILL_LAT, SPILL_LON, T0,
        radius_km=RADIUS_KM,
        search_results=[dict(c) for c in demo_candidates],
    )
    a = next(r for r in ranked if r["mmsi"] == 111000001)
    joined = " ".join(a["evidence"]).lower()
    assert "0.8 km" in joined or "passed within" in joined
    assert "approached" in joined
    assert any("observation" in e for e in a["evidence"])


def test_no_candidates_returns_empty():
    assert attribution_service.attribute(
        SPILL_LAT, SPILL_LON, T0,
        radius_km=RADIUS_KM,
        search_results=[],
    ) == []


def test_attribute_and_store_persists_rows(demo_candidates):
    from sqlalchemy import delete, select
    from app.database.connection import get_session_factory
    from app.database.models import AttributionResult, OilSpill, Vessel

    # attribution_results.mmsi is a FK to vessels; seed the candidate vessels.
    seeded = []
    try:
        with get_session_factory()() as session, session.begin():
            for mmsi, name, stype in [
                (111000001, "DEMO TANKER A", 80),
                (111000002, "DEMO FISHER B", 30),
                (111000003, "DEMO CARGO C", 70),
                (111000009, "DEMO COASTER I", 70),
            ]:
                session.add(Vessel(mmsi=mmsi, ship_name=name, ship_type=stype))
            seeded = [111000001, 111000002, 111000003, 111000009]

        ranked = attribution_service.attribute_and_store(
            SPILL_LAT, SPILL_LON, T0,
            radius_km=RADIUS_KM,
            search_results=[dict(c) for c in demo_candidates],
        )
        assert ranked
        spill_id = ranked[0]["spill_id"]

        with get_session_factory()() as session:
            rows = (session.execute(
                select(AttributionResult).where(AttributionResult.spill_id == spill_id)
            ).scalars().all())
        assert len(rows) == len(ranked)
        stored = {r.mmsi: r for r in rows}
        for r in ranked:
            s = stored[r["mmsi"]]
            assert s.rank == r["rank"]
            assert s.score == pytest.approx(r["score"], abs=0.001)
            assert s.distance_km == pytest.approx(r["min_distance_km"], abs=0.001)
            assert s.time_difference_minutes == pytest.approx(r["time_difference_minutes"], abs=0.01)

        # Re-running replaces rows, not duplicates them.
        ranked2 = attribution_service.attribute_and_store(
            SPILL_LAT, SPILL_LON, T0,
            radius_km=RADIUS_KM,
            search_results=[dict(demo_candidates[0]), dict(demo_candidates[1])],
        )
        spill_id2 = ranked2[0]["spill_id"]
        with get_session_factory()() as session:
            rows2 = (session.execute(
                select(AttributionResult).where(AttributionResult.spill_id == spill_id2)
            ).scalars().all())
        assert len(rows2) == 2
    finally:
        with get_session_factory()() as session, session.begin():
            session.execute(delete(AttributionResult))
            session.execute(delete(OilSpill))
            if seeded:
                session.execute(delete(Vessel).where(Vessel.mmsi.in_(seeded)))


def test_reweighting_changes_scores(demo_candidates):
    heavy_spatial = AttributionService(
        weights={"spatial": 1.0, "temporal": 0.0, "observation": 0.0,
                 "approach": 0.0, "consistency": 0.0}
    )
    base = attribution_service.attribute(
        SPILL_LAT, SPILL_LON, T0, radius_km=RADIUS_KM,
        search_results=[dict(c) for c in demo_candidates],
    )
    alt = heavy_spatial.attribute(
        SPILL_LAT, SPILL_LON, T0, radius_km=RADIUS_KM,
        search_results=[dict(c) for c in demo_candidates],
    )
    b = {r["mmsi"]: r for r in base}
    a_alt = {r["mmsi"]: r for r in alt}
    # Under pure-spatial weighting, the closest vessel (A) dominates even more.
    assert a_alt[111000001]["score"] > 0.9
    assert b[111000001]["score"] != a_alt[111000001]["score"]


def test_weight_sum_consistent():
    assert abs(_WEIGHT_SUM - 1.0) < 1e-6
    assert _WEIGHT_SUM != 0