"""AIS services.

* AISService owns the real-time AIS worker (start / stop) for a FastAPI
  lifespan hook.  The worker is NOT started inside FastAPI yet; run it
  directly during development with ``python -m app.workers.ais_worker``.

* AISVesselSearch runs a spatial + temporal candidate query against
  ais_positions for a detected oil spill, groups results by vessel, and
  returns ordered candidate observations.  No vessel is declared responsible
  at this stage — that belongs to the attribution layer.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import settings
from app.database.connection import session_scope
from app.database.repositories import AISSearchRepository, VesselRepository
from app.workers.ais_worker import AISWorker


# ── Real-time AIS worker owner (unchanged) ────────────────────────────────

class AISService:
    def __init__(self) -> None:
        self._worker: Optional[AISWorker] = None

    @property
    def worker(self) -> AISWorker:
        if self._worker is None:
            self._worker = AISWorker()
        return self._worker

    async def start(self) -> None:
        await self.worker.run_forever()

    async def stop(self) -> None:
        await self.worker.stop()


ais_service = AISService()


# ── Vessel candidate search around a detected spill ───────────────────────

def _ensure_aware(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC (ISO timestamps from clients are typically UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class AISVesselSearch:
    """Spatial + temporal candidate search.

    The query itself (bounding box + ``haversine_km``) runs entirely in
    PostgreSQL via ``AISSearchRepository``; this class only groups by MMSI,
    extracts per-candidate features and sorts.
    """

    def __init__(
        self,
        radius_km: Optional[float] = None,
        before_minutes: Optional[int] = None,
        after_minutes: Optional[int] = None,
        approach_factor: Optional[float] = None,
    ):
        self.radius_km = float(
            radius_km if radius_km is not None else settings.ais_search_radius_km
        )
        self.before_minutes = int(
            before_minutes
            if before_minutes is not None
            else settings.ais_time_before_minutes
        )
        self.after_minutes = int(
            after_minutes
            if after_minutes is not None
            else settings.ais_time_after_minutes
        )
        self.approach_factor = float(
            approach_factor
            if approach_factor is not None
            else settings.ais_approach_factor
        )

    def search_candidates(
        self,
        spill_lat: float,
        spill_lon: float,
        detection_time: datetime,
        radius_km: Optional[float] = None,
        before_minutes: Optional[int] = None,
        after_minutes: Optional[int] = None,
    ) -> list[dict]:
        """Return candidate vessels grouped and ordered by proximity/time."""
        radius = float(radius_km if radius_km is not None else self.radius_km)
        before = int(before_minutes if before_minutes is not None else self.before_minutes)
        after = int(after_minutes if after_minutes is not None else self.after_minutes)

        detection_time = _ensure_aware(detection_time)
        start = detection_time - timedelta(minutes=before)
        end = detection_time + timedelta(minutes=after)

        with session_scope() as session:
            repo = AISSearchRepository(session)
            rows = repo.positions_around_point(
                spill_lat, spill_lon, radius, start, end
            )

        # Group by vessel.
        by_mmsi: dict[int, list[tuple]] = defaultdict(list)
        ship_names: dict[int, Optional[str]] = {}
        ship_types: dict[int, Optional[int]] = {}
        for pos, ship_name, dist, ship_type in rows:
            by_mmsi[pos.mmsi].append((pos, dist))
            ship_names[pos.mmsi] = ship_name
            ship_types[pos.mmsi] = ship_type

        candidates: list[dict] = []
        for mmsi, items in by_mmsi.items():
            # items already sorted by distance from the SQL layer, but the
            # group preserves insertion order; re-sort to be deterministic.
            items.sort(key=lambda t: t[1])
            closest_pos, min_dist = items[0]

            # ── features ──
            closest_ts = _ensure_aware(closest_pos.timestamp)
            time_diff_min = abs((closest_ts - detection_time).total_seconds()) / 60.0

            speeds = [
                p.speed
                for p, _ in items
                if p.speed is not None and p.speed >= 0
            ]
            avg_speed_knots = float(sum(speeds) / len(speeds)) if speeds else None

            # Prefer the heading at closest approach; fall back to mean.
            headings = [
                p.heading
                for p, _ in items
                if p.heading is not None
            ]
            if closest_pos.heading is not None:
                heading_at_closest = float(closest_pos.heading)
            elif headings:
                heading_at_closest = float(sum(headings) / len(headings))
            else:
                heading_at_closest = None

            approached_or_crossed = min_dist <= radius * self.approach_factor

            candidates.append(
                {
                    "mmsi": mmsi,
                    "ship_name": ship_names.get(mmsi),
                    "ship_type": ship_types.get(mmsi),
                    "min_distance_km": round(min_dist, 4),
                    "closest_observation_timestamp": closest_ts.isoformat(),
                    "time_difference_minutes": round(time_diff_min, 2),
                    "observation_count": len(items),
                    "approached_or_crossed_spill": approached_or_crossed,
                    "avg_speed_knots": None
                    if avg_speed_knots is None
                    else round(avg_speed_knots, 2),
                    "heading": None
                    if heading_at_closest is None
                    else round(heading_at_closest, 2),
                    "observations": [
                        {
                            "timestamp": _ensure_aware(p.timestamp).isoformat(),
                            "latitude": p.latitude,
                            "longitude": p.longitude,
                            "speed": p.speed,
                            "course": p.course,
                            "heading": p.heading,
                            "distance_km": round(d, 4),
                        }
                        for p, d in items
                    ],
                }
            )

        # Multi-key ordering: closest first, then closest-in-time, then
        # more observations preferred (information-rich candidates first).
        candidates.sort(
            key=lambda c: (
                c["min_distance_km"],
                c["time_difference_minutes"],
                -c["observation_count"],
            )
        )
        return candidates


ais_vessel_search = AISVesselSearch()


# ── Vessel + trajectory queries (read side) ──────────────────────────────

class VesselQueryService:
    """Read-side queries for vessels and their AIS trajectories."""

    def get_vessel(self, mmsi: int) -> Optional[dict]:
        """Static vessel info (API-shaped) or None when the MMSI is unknown."""
        from app.services.vessel_types import ship_type_label

        with session_scope() as session:
            vessel = VesselRepository(session).get_by_mmsi(int(mmsi))
        if vessel is None:
            return None
        return {
            "vessel": {
                "mmsi": vessel.mmsi,
                "ship_name": vessel.ship_name,
                "ship_type": ship_type_label(vessel.ship_type),
                "imo": vessel.imo,
                "created_at": vessel.created_at,
            }
        }

    def get_trajectory(
        self,
        mmsi: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Optional[dict]:
        """A vessel's chronological AIS positions (API-shaped) or None."""
        with session_scope() as session:
            vessel = VesselRepository(session).get_by_mmsi(int(mmsi))
            if vessel is None:
                return None
            points = VesselRepository(session).trajectory(
                int(mmsi), start=start, end=end
            )

        return {
            "mmsi": mmsi,
            "ship_name": vessel.ship_name,
            "points": [
                {
                    "timestamp": _ensure_aware(p.timestamp),
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "sog": p.speed,
                    "cog": p.course,
                    "heading": p.heading,
                }
                for p in points
            ],
        }


vessel_query_service = VesselQueryService()