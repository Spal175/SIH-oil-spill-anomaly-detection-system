"""Vessel attribution (MVP): rank candidate vessels using AIS-derived features.

Input is the output of ``AISVesselSearch`` (spatial + temporal candidate
observations) for a detected spill. Each candidate is scored entirely from its
own historical AIS observations — proximity, timing, observation density,
trajectory approach/crossing and movement consistency. Nothing is hardcoded per
vessel; the score/rank/evidence all derive from the data.

Terminology: output speaks of a *probable source vessel* / *candidate vessel*.
It does NOT claim legal responsibility — attribution here is investigative only.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.database.connection import session_scope
from app.database.repositories import AttributionRepository, OilSpillRepository
from app.services.ais_service import AISVesselSearch, ais_vessel_search

logger = logging.getLogger(__name__)

# Score weights (sum to 1.0). Explainable and tunable via config-copyable
# defaults, but always applied to ALL candidates uniformly.
W_SPATIAL = float(getattr(settings, "attr_w_spatial", 0.35))
W_TEMPORAL = float(getattr(settings, "attr_w_temporal", 0.25))
W_OBSERVATION = float(getattr(settings, "attr_w_observation", 0.15))
W_APPROACH = float(getattr(settings, "attr_w_approach", 0.15))
W_CONSISTENCY = float(getattr(settings, "attr_w_consistency", 0.10))

_WEIGHT_SUM = W_SPATIAL + W_TEMPORAL + W_OBSERVATION + W_APPROACH + W_CONSISTENCY


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class AttributionService:
    """Rank candidate vessels for a detected spill using AIS evidence."""

    def __init__(
        self,
        weights: Optional[dict] = None,
        radius_km: Optional[float] = None,
    ):
        self.radius_km = float(radius_km if radius_km is not None else settings.ais_search_radius_km)
        self._search: AISVesselSearch = AISVesselSearch()
        self._weights = dict(weights) if weights else {
            "spatial": W_SPATIAL,
            "temporal": W_TEMPORAL,
            "observation": W_OBSERVATION,
            "approach": W_APPROACH,
            "consistency": W_CONSISTENCY,
        }

    # ── normalized sub-scores (each in [0, 1], higher = stronger evidence) ──

    def _spatial_score(self, min_distance_km: float) -> float:
        if min_distance_km is None:
            return 0.0
        # linear decay from 1.0 at the spill to 0.0 at the search radius.
        return max(0.0, 1.0 - min_distance_km / self.radius_km)

    def _temporal_score(self, time_difference_minutes: Optional[float]) -> float:
        if time_difference_minutes is None:
            return 0.0
        horizon = float(settings.ais_time_before_minutes or 60)
        return max(0.0, 1.0 - time_difference_minutes / horizon)

    def _observation_score(self, count: int, capacity: int = 8) -> float:
        if count is None or count <= 0:
            return 0.0
        return min(1.0, count / capacity)

    def _approach_score(self, approached: bool, min_distance_km: Optional[float]) -> float:
        if approached:
            return 1.0
        if min_distance_km is None:
            return 0.0
        return max(0.0, 1.0 - min_distance_km / self.radius_km)

    def _consistency_score(self, candidate: dict) -> float:
        """Movement consistency: how tightly clustered the vessel's course is.

        Uses the mean resultant length R of the observed course/heading across
        the candidate's near observations (circular statistics). R is 1.0 when
        every observation shares the same heading and near 0.0 when headings
        are scattered — a steady transit scores higher than an erratic wander.
        """
        obs = candidate.get("observations") or []
        courses = [
            (o.get("course") or o.get("heading"))
            for o in obs
            if (o.get("course") or o.get("heading")) is not None
        ]
        if not courses:
            return 0.0
        rad = [math.radians(float(x) % 360.0) for x in courses]
        n = len(rad)
        sx = math.fsum(math.sin(a) for a in rad)
        sy = math.fsum(math.cos(a) for a in rad)
        r = math.hypot(sx, sy) / n  # mean resultant length in [0, 1]
        return float(max(0.0, min(1.0, r)))

    # ── evidence strings ───────────────────────────────────────────────────

    def _evidence(self, candidate: dict) -> list[str]:
        evidence: list[str] = []
        min_dist = candidate.get("min_distance_km")
        if min_dist is not None:
            evidence.append(
                f"Vessel passed within {min_dist:.1f} km of the detected spill"
            )
        td = candidate.get("time_difference_minutes")
        if td is not None:
            evidence.append(
                f"Vessel was observed about {td:.1f} minutes before detection"
            )
        if candidate.get("approached_or_crossed_spill"):
            evidence.append("Trajectory approached the spill region")
        n = candidate.get("observation_count", 0)
        if n:
            evidence.append(f"{n} AIS observation(s) recorded near the spill")
        hdg = candidate.get("heading")
        if hdg is not None:
            evidence.append(f"Vessel heading at closest approach: {hdg:.0f} deg")
        spd = candidate.get("avg_speed_knots")
        if spd is not None:
            evidence.append(f"Average observed speed: {spd:.1f} knots")
        return evidence

    # ── scoring + ranking ─────────────────────────────────────────────────

    def _score_candidates(self, candidates: list[dict]) -> list[dict]:
        scored: list[dict] = []
        for cand in candidates:
            s_spatial = self._spatial_score(cand.get("min_distance_km"))
            s_temporal = self._temporal_score(cand.get("time_difference_minutes"))
            s_observation = self._observation_score(cand.get("observation_count"))
            s_approach = self._approach_score(
                bool(cand.get("approached_or_crossed_spill")),
                cand.get("min_distance_km"),
            )
            s_consistency = self._consistency_score(cand)

            raw = (
                self._weights["spatial"] * s_spatial
                + self._weights["temporal"] * s_temporal
                + self._weights["observation"] * s_observation
                + self._weights["approach"] * s_approach
                + self._weights["consistency"] * s_consistency
            )
            normalized = raw / _WEIGHT_SUM  # keep overall score in [0, 1]

            cand = dict(cand)
            cand["score"] = round(normalized, 4)
            cand["evidence"] = self._evidence(cand)
            cand["ship_type"] = cand.get("ship_type")
            scored.append(cand)

        scored.sort(key=lambda c: (c["score"], -c.get("observation_count", 0)), reverse=True)
        for rank, cand in enumerate(scored, start=1):
            cand["rank"] = rank
        return scored

    # ── public API ─────────────────────────────────────────────────────────

    def attribute(
        self,
        spill_lat: float,
        spill_lon: float,
        detection_time: datetime,
        radius_km: Optional[float] = None,
        before_minutes: Optional[int] = None,
        after_minutes: Optional[int] = None,
        search_results: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Return ranked attribution results for a detected spill.

        ``search_results`` may be passed pre-computed (from AISVesselSearch) to
        avoid re-querying; otherwise the spatial+temporal search runs here.
        """
        detection_time = _ensure_aware(detection_time)
        candidates = search_results if search_results is not None else self._search.search_candidates(
            spill_lat, spill_lon, detection_time,
            radius_km=radius_km, before_minutes=before_minutes, after_minutes=after_minutes,
        )
        return self._score_candidates(candidates)

    def store_results(self, spill_id: str, ranked: list[dict]) -> None:
        """Persist ranked attribution rows under an existing spill id."""
        if not ranked:
            return
        rows = [
            {
                "mmsi": r["mmsi"],
                "distance_km": r.get("min_distance_km"),
                "time_difference_minutes": r.get("time_difference_minutes"),
                "score": r.get("score"),
                "rank": r.get("rank"),
            }
            for r in ranked
        ]
        with session_scope() as session:
            AttributionRepository(session).replace_for_spill(spill_id, rows)

    def attribute_and_store(
        self,
        spill_lat: float,
        spill_lon: float,
        detection_time: datetime,
        radius_km: Optional[float] = None,
        before_minutes: Optional[int] = None,
        after_minutes: Optional[int] = None,
        search_results: Optional[list[dict]] = None,
        spill_id: Optional[str] = None,
    ) -> list[dict]:
        """Rank candidates AND persist them into ``attribution_results``.

        When ``spill_id`` is provided the rows are stored under that existing
        spill; otherwise a fresh OilSpill row is created first (for standalone
        scoring without a preceding detection pipeline).
        """
        detection_time = _ensure_aware(detection_time)
        ranked = self.attribute(
            spill_lat, spill_lon, detection_time,
            radius_km=radius_km, before_minutes=before_minutes,
            after_minutes=after_minutes, search_results=search_results,
        )
        if not ranked:
            return ranked

        if spill_id is None:
            with session_scope() as session:
                spill = OilSpillRepository(session).create(
                    detected_at=detection_time,
                    centroid_latitude=spill_lat,
                    centroid_longitude=spill_lon,
                )
                spill_id = spill.id

        self.store_results(spill_id, ranked)
        for r in ranked:
            r["spill_id"] = spill_id
        return ranked


attribution_service = AttributionService()