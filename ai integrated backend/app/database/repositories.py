"""Repository layer.

Repositories wrap a SQLAlchemy session and expose the data-access operations the
services and workers need. AIS and oil-spill data are kept in separate
repositories / tables.
"""
from datetime import datetime
from math import cos, radians
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database.models import AisPosition, AttributionResult, OilSpill, Vessel


class VesselRepository:
    def __init__(self, session: Session):
        self._session = session

    def upsert_vessel(
        self,
        mmsi: int,
        ship_name: Optional[str] = None,
        ship_type: Optional[int] = None,
    ) -> Vessel:
        """Insert a vessel by MMSI or update its static fields if it exists.

        Uses ``INSERT ... ON CONFLICT (mmsi) DO UPDATE``: new info wins, but an
        unknown (None) field never overwrites a stored value.
        """
        values = {"mmsi": mmsi}
        if ship_name is not None:
            values["ship_name"] = ship_name
        if ship_type is not None:
            values["ship_type"] = ship_type

        stmt = pg_insert(Vessel).values(**values)
        update = {k: stmt.excluded[k] for k in values if k != "mmsi"}
        stmt = stmt.on_conflict_do_update(
            index_elements=[Vessel.mmsi], set_=update
        )
        self._session.execute(stmt)
        self._session.flush()
        return self._session.execute(
            select(Vessel).where(Vessel.mmsi == mmsi)
        ).scalar_one()

    def add_position(
        self,
        mmsi: int,
        timestamp: datetime,
        latitude: float,
        longitude: float,
        speed: Optional[float] = None,
        course: Optional[float] = None,
        heading: Optional[float] = None,
    ) -> AisPosition:
        """Append one position report to a vessel's AIS history."""
        position = AisPosition(
            mmsi=mmsi,
            timestamp=timestamp,
            latitude=latitude,
            longitude=longitude,
            speed=speed,
            course=course,
            heading=heading,
        )
        self._session.add(position)
        self._session.flush()
        return position

    def get_by_mmsi(self, mmsi: int) -> Optional[Vessel]:
        return self._session.get(Vessel, mmsi) or self._session.execute(
            select(Vessel).where(Vessel.mmsi == mmsi)
        ).scalar_one_or_none()

    def trajectory(
        self,
        mmsi: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[AisPosition]:
        stmt = select(AisPosition).where(AisPosition.mmsi == mmsi)
        if start is not None:
            stmt = stmt.where(AisPosition.timestamp >= start)
        if end is not None:
            stmt = stmt.where(AisPosition.timestamp <= end)
        stmt = stmt.order_by(AisPosition.timestamp.asc())
        return list(self._session.execute(stmt).scalars())


class OilSpillRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(
        self,
        detected_at: datetime,
        centroid_latitude: float,
        centroid_longitude: float,
        area: Optional[float] = None,
        confidence: Optional[float] = None,
        geometry_geojson: Optional[str] = None,
    ) -> OilSpill:
        """Persist one detected oil spill (ML + GIS output -> DB row).

        Only lightweight geometry/meta fields are stored; the raw 0/1 mask is
        intentionally NOT persisted (no large matrices in PostgreSQL).
        ``geometry_geojson`` holds the bbox-derived GeoJSON Polygon when the
        source GeoTIFF is georeferenced.
        """
        spill = OilSpill(
            detected_at=detected_at,
            centroid_latitude=centroid_latitude,
            centroid_longitude=centroid_longitude,
            area=area,
            confidence=confidence,
            geometry_geojson=geometry_geojson,
        )
        self._session.add(spill)
        self._session.flush()
        return spill

    def get_by_id(self, spill_id: str) -> Optional[OilSpill]:
        return self._session.get(OilSpill, spill_id)

    def add_attribution_results(self, spill_id: str, results: list[dict]) -> None:
        raise NotImplementedError


class AttributionRepository:
    def __init__(self, session: Session):
        self._session = session

    def list_for_spill(self, spill_id: str) -> list[AttributionResult]:
        stmt = (
            select(AttributionResult)
            .where(AttributionResult.spill_id == spill_id)
            .order_by(AttributionResult.rank.asc())
        )
        return list(self._session.execute(stmt).scalars())

    def list_for_spill_with_vessels(self, spill_id: str) -> list[dict]:
        """Stored attribution rows for a spill, joined with vessel static data.

        Returns list of dicts (rank, mmsi, ship_name, ship_type, distance_km,
        time_difference_minutes, attribution_score) ordered by stored rank.
        """
        stmt = (
            select(
                AttributionResult.rank,
                AttributionResult.mmsi,
                Vessel.ship_name,
                Vessel.ship_type,
                AttributionResult.distance_km,
                AttributionResult.time_difference_minutes,
                AttributionResult.score,
            )
            .join(Vessel, Vessel.mmsi == AttributionResult.mmsi)
            .where(AttributionResult.spill_id == spill_id)
            .order_by(AttributionResult.rank.asc())
        )
        return [
            {
                "rank": row.rank,
                "mmsi": row.mmsi,
                "ship_name": row.ship_name,
                "ship_type": row.ship_type,
                "distance_km": row.distance_km,
                "time_difference_minutes": row.time_difference_minutes,
                "attribution_score": row.score,
            }
            for row in self._session.execute(stmt).all()
        ]

    def replace_for_spill(self, spill_id: str, results: list[dict]) -> None:
        """Replace the stored attribution rows for a spill with fresh ones.

        Each ``results`` item: mmsi, distance_km, time_difference_minutes,
        score, rank. Deleting before inserting keeps the table consistent when
        re-running attribution over the same spill.
        """
        from sqlalchemy import delete

        self._session.execute(
            delete(AttributionResult).where(AttributionResult.spill_id == spill_id)
        )
        for item in results:
            self._session.add(
                AttributionResult(
                    spill_id=spill_id,
                    mmsi=item["mmsi"],
                    distance_km=item.get("distance_km"),
                    time_difference_minutes=item.get("time_difference_minutes"),
                    score=item.get("score"),
                    rank=item.get("rank"),
                )
            )
        self._session.flush()


class AISSearchRepository:
    """Spatial + temporal candidate search over ais_positions.

    Distance is computed *entirely in PostgreSQL* via the ``haversine_km``
    function installed by migration 0001.  A lat/lon bounding box lets the
    existing ``ix_ais_positions_lat_lon`` index prune the candidate set before
    the slower haversine filter is evaluated — no Python-side distance math.
    """

    def __init__(self, session: Session):
        self._session = session

    def positions_around_point(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        start: datetime,
        end: datetime,
    ) -> list[tuple[AisPosition, Optional[str], float, Optional[int]]]:
        """Return ais_positions within radius_km and time [start, end].

        Returns list of (AisPosition, ship_name, distance_km, ship_type) sorted
        by distance ascending.
        """
        dlat = radius_km / 111.32
        cos_lat = max(cos(radians(lat)), 1e-9)
        dlon = radius_km / (111.32 * cos_lat)

        dist_expr = func.haversine_km(
            lat, lon, AisPosition.latitude, AisPosition.longitude
        ).label("distance_km")

        stmt = (
            select(AisPosition, Vessel.ship_name, dist_expr, Vessel.ship_type)
            .join(Vessel, Vessel.mmsi == AisPosition.mmsi)
            .where(AisPosition.timestamp >= start)
            .where(AisPosition.timestamp <= end)
            .where(AisPosition.latitude.between(lat - dlat, lat + dlat))
            .where(AisPosition.longitude.between(lon - dlon, lon + dlon))
            .where(
                func.haversine_km(
                    lat, lon, AisPosition.latitude, AisPosition.longitude
                )
                <= radius_km
            )
            .order_by(dist_expr.asc())
        )

        return [
            (pos, ship_name, float(distance), ship_type)
            for pos, ship_name, distance, ship_type in self._session.execute(stmt).all()
        ]