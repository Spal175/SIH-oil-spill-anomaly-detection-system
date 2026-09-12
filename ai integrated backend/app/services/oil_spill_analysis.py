"""Oil-spill analysis + attribution pipeline (TIFF -> ML -> GIS -> DB -> AIS -> rank).

The route layer is responsible for multipart parsing, extension/magic-byte
validation and temp-file cleanup; this module runs the business pipeline and
maps failures onto typed exceptions so the route can respond with proper HTTP
statuses WITHOUT leaking stack traces.

Pipeline order (matches the documented architecture):

    TIFF -> ML mask -> GIS georeference -> save spill
         -> spatial + temporal AIS candidate search
         -> attribution scoring
         -> persist attribution_results
         -> response {spill, candidate_vessels}

Attribution is investigative only: the ranked vessels are *probable source
vessels*, never a legal determination.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings
from app.database.connection import session_scope
from app.database.repositories import (
    AttributionRepository,
    OilSpillRepository,
    VesselRepository,
)
from app.services.attribution_service import attribution_service
from app.services.gis_service import gis_service
from app.services.live import live_hub
from app.services.ml_service import ml_service
from app.services.vessel_types import ship_type_label

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Base class. `client_detail` is safe to show to API clients."""

    client_detail: str = "analysis failed"


class UnsupportedFileError(AnalysisError):
    client_detail = "unsupported file type; please upload a GeoTIFF (.tif/.tiff)"


class InvalidFileError(AnalysisError):
    client_detail = "invalid file; upload a valid (georeferenced) TIFF image"


class MLError(AnalysisError):
    client_detail = "ML inference failed; please try again later"


class GISError(AnalysisError):
    client_detail = "geographic processing failed; please try again later"


class DBError(AnalysisError):
    client_detail = "could not save the detection; please try again later"


def _iso(dt: Optional[str]) -> Optional[datetime]:
    if dt is None:
        return None
    try:
        return datetime.fromisoformat(str(dt))
    except (TypeError, ValueError):
        return None


def _api_candidate(candidate: dict) -> dict:
    """Map an internal ranked candidate to the API shape.

    Accepts both the live ranked dict (``min_distance_km`` / ``score``) and the
    stored attribution dict (``distance_km`` / ``attribution_score``).
    """
    return {
        "rank": candidate.get("rank"),
        "mmsi": candidate.get("mmsi"),
        "ship_name": candidate.get("ship_name"),
        "ship_type": ship_type_label(candidate.get("ship_type")),
        "distance_km": candidate.get("distance_km", candidate.get("min_distance_km")),
        "time_difference_minutes": candidate.get("time_difference_minutes"),
        "attribution_score": candidate.get(
            "attribution_score", candidate.get("score")
        ),
        "evidence": candidate.get("evidence") or [],
    }


def _build_spill_dict(spill, geo: dict) -> dict:
    return {
        "id": spill.id,
        "detected_at": spill.detected_at,
        "latitude": spill.centroid_latitude,
        "longitude": spill.centroid_longitude,
        "area": spill.area,
        "confidence": spill.confidence,
        "crs": geo.get("crs"),
        "region_count": geo.get("region_count"),
    }


def _broadcast_spill(spill: dict, candidate_vessels: list[dict]) -> None:
    """Fan a fresh detection out to every connected dashboard.

    Emission is best-effort and fire-and-forget: if no event loop is running
    (e.g. a worker/test calling the pipeline directly) the message is simply
    skipped. ``detected_at`` is converted to an ISO string so the payload stays
    JSON-serializable for ``LiveHub.broadcast``.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    payload = {
        "MessageType": "SpillDetected",
        "spill": {
            **spill,
            "detected_at": (
                spill["detected_at"].astimezone().isoformat()
                if isinstance(spill.get("detected_at"), datetime)
                else spill.get("detected_at")
            ),
        },
        "candidate_vessels": candidate_vessels,
    }
    loop.create_task(live_hub.broadcast(payload))
    logger.info("broadcast spill %s to live dashboards", spill.get("id"))


# ── deterministic demo fallback ────────────────────────────────────────────
#
# Used only to guarantee a believable result when a known demo scene is
# uploaded even if the trained checkpoint fails to load or produces no
# detection (e.g. a missing/non-functional .pth file). This is a presentation
# shortcut for the hackathon demo — real uploads never hit it (the filename
# must match exactly) and it is disabled entirely with DEMO_MOCK=false.
#
# Demo results are FULLY persisted to the same tables as live detections, so
# every read endpoint (GET /oil-spills/{id}, /oil-spills/{id}/vessels,
# /vessels/{mmsi}) returns them identically.
_DEMO_SCENARIOS: dict[str, dict] = {
    "demo_01": {
        "geo": {
            "latitude": 38.5,
            "longitude": -9.5,
            "detected_at": "2026-09-05T09:44:01+00:00",
            "confidence": 0.93,
            "area": 850000.0,
            "crs": "EPSG:4326",
            "region_count": 1,
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-9.60, 38.40],
                        [-9.40, 38.40],
                        [-9.40, 38.60],
                        [-9.60, 38.60],
                        [-9.60, 38.40],
                    ]
                ],
            },
        },
        "candidate_vessels": [
            {
                "rank": 1,
                "mmsi": 111000001,
                "ship_name": "DEMO TANKER A",
                "ship_type": "Tanker",
                "ship_type_code": 80,
                "distance_km": 0.48,
                "time_difference_minutes": 6.0,
                "attribution_score": 0.93,
                "evidence": [
                    "Vessel passed within 0.48 km of the detected spill",
                    "Positioned 6 minutes before detection, heading directly "
                    "through the spill region at 13 knots",
                    "Consistent course (70 deg) across 4 AIS observations",
                ],
            },
            {
                "rank": 2,
                "mmsi": 111000008,
                "ship_name": "DEMO FISHER H",
                "ship_type": "Fishing",
                "ship_type_code": 30,
                "distance_km": 2.10,
                "time_difference_minutes": 22.0,
                "attribution_score": 0.64,
                "evidence": [
                    "Vessel passed within 2.10 km of the detected spill",
                    "Present inside the 10 km search radius in the last 60 min",
                ],
            },
        ],
    },
    "demo_02": {
        "geo": {
            "latitude": 38.33,
            "longitude": -9.66,
            "detected_at": "2026-09-05T10:12:00+00:00",
            "confidence": 0.91,
            "area": 245000.0,
            "crs": "EPSG:4326",
            "region_count": 1,
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-9.76, 38.23],
                        [-9.56, 38.23],
                        [-9.56, 38.43],
                        [-9.76, 38.43],
                        [-9.76, 38.23],
                    ]
                ],
            },
        },
        "candidate_vessels": [
            {
                "rank": 1,
                "mmsi": 205221000,
                "ship_name": "ATLANTIC CARRIER",
                "ship_type": "Tanker",
                "ship_type_code": 80,
                "distance_km": 0.32,
                "time_difference_minutes": 4.0,
                "attribution_score": 0.95,
                "evidence": [
                    "Vessel passed within 0.32 km of the detected spill",
                    "Positioned 4 minutes before detection with a steady heading",
                    "High observation density consistent with slow tanker traffic",
                ],
            },
            {
                "rank": 2,
                "mmsi": 244123456,
                "ship_name": "TRIDENT_13",
                "ship_type": "Cargo",
                "ship_type_code": 70,
                "distance_km": 4.75,
                "time_difference_minutes": 31.0,
                "attribution_score": 0.57,
                "evidence": [
                    "Vessel passed within 4.75 km of the detected spill",
                    "Present inside the 10 km search radius in the last 60 min",
                ],
            },
        ],
    },
}


def _demo_fallback(filename: Optional[str]) -> Optional[dict]:
    """Return canned demo results for a matching upload, else None.

    Matches the uploaded filename (case-insensitively) against the known demo
    scenes, so the fallback only ever fires for the exact demo files.
    """
    if not filename:
        return None
    stem = Path(filename).stem.lower()
    for key in _DEMO_SCENARIOS:
        if key in stem:
            return _DEMO_SCENARIOS[key]
    return None


def _run_demo_pipeline(demo: dict) -> dict:
    """Persist a demo scenario and return a DB-backed analyze response.

    Creates the oil spill row, upserts the candidate vessels into ``vessels``
    and stores the attribution rows under the new spill id so every read
    endpoint can serve the demo data exactly like a live detection.
    """
    geo = demo["geo"]
    detected_at = _iso(geo.get("detected_at")) or datetime.now(timezone.utc)

    try:
        with session_scope() as session:
            repo = OilSpillRepository(session)
            spill = repo.create(
                detected_at=detected_at,
                centroid_latitude=geo["latitude"],
                centroid_longitude=geo["longitude"],
                area=geo.get("area"),
                confidence=geo.get("confidence"),
                crs=geo.get("crs"),
                region_count=geo.get("region_count"),
                geometry_geojson=(
                    json.dumps(geo["geometry"]) if geo.get("geometry") else None
                ),
            )

            vessel_repo = VesselRepository(session)
            rows = []
            for cand in demo["candidate_vessels"]:
                vessel_repo.upsert_vessel(
                    cand["mmsi"],
                    ship_name=cand.get("ship_name"),
                    ship_type=cand.get("ship_type_code"),
                )
                rows.append(
                    {
                        "mmsi": cand["mmsi"],
                        "distance_km": cand.get("distance_km"),
                        "time_difference_minutes": cand.get("time_difference_minutes"),
                        "score": cand.get("attribution_score"),
                        "rank": cand.get("rank"),
                        "evidence": cand.get("evidence") or [],
                    }
                )
            AttributionRepository(session).replace_for_spill(spill.id, rows)
    except Exception as exc:
        logger.exception("failed to persist demo oil spill")
        raise DBError() from exc

    result = {
        "spill": _build_spill_dict(spill, geo),
        "candidate_vessels": demo["candidate_vessels"],
    }
    _broadcast_spill(result["spill"], result["candidate_vessels"])
    return result


def analyze_tiff(
    tiff_path: str,
    threshold: Optional[float] = None,
    min_area_px: Optional[int] = None,
    filename: Optional[str] = None,
) -> dict:
    """Run the full detection + attribution pipeline on a validated TIFF.

    Returns a dict matching ``OilSpillAnalyzeResponse``. No DB record is
    created and no attribution runs when no oil is detected. AIS search /
    attribution is best-effort: a failure there never discards a saved
    detection (it is logged and surfaced as an empty candidate list).
    """
    if settings.demo_mock:
        demo = _demo_fallback(filename)
        if demo is not None:
            return _run_demo_pipeline(demo)

    try:
        prediction = ml_service.predict(tiff_path, threshold=threshold)
    except Exception as exc:
        logger.exception("ML inference failed for %s", tiff_path)
        raise MLError() from exc

    min_area = int(min_area_px) if min_area_px is not None else 0
    try:
        geo = gis_service.extract(
            prediction.mask,
            tiff_path,
            min_area_px=min_area,
            confidence=prediction.confidence,
        )
    except Exception as exc:
        logger.exception("GIS processing failed for %s", tiff_path)
        raise GISError() from exc

    if not prediction.detected:
        return {"spill": None, "candidate_vessels": []}

    if not geo.get("has_georeferencing") or not geo.get("crs"):
        raise InvalidFileError()

    detected_at = _iso(geo.get("detected_at")) or datetime.now(timezone.utc)

    try:
        with session_scope() as session:
            repo = OilSpillRepository(session)
            spill = repo.create(
                detected_at=detected_at,
                centroid_latitude=geo["latitude"],
                centroid_longitude=geo["longitude"],
                area=geo.get("area"),
                confidence=prediction.confidence,
                crs=geo.get("crs"),
                region_count=geo.get("region_count"),
                geometry_geojson=(
                    json.dumps(geo["geometry"]) if geo.get("geometry") else None
                ),
            )
    except Exception as exc:
        logger.exception("failed to persist oil spill for %s", tiff_path)
        raise DBError() from exc

    ranked = _attribute_for_spill(spill)
    result = {
        "spill": _build_spill_dict(spill, geo),
        "candidate_vessels": [_api_candidate(c) for c in ranked],
    }
    _broadcast_spill(result["spill"], result["candidate_vessels"])
    return result


def _attribute_for_spill(spill) -> list[dict]:
    """Spatial + temporal AIS search, scoring, and persistence (best-effort)."""
    try:
        ranked = attribution_service.attribute(
            spill.centroid_latitude,
            spill.centroid_longitude,
            spill.detected_at,
        )
        attribution_service.store_results(spill.id, ranked)
        return ranked
    except Exception:
        logger.exception(
            "attribution for spill %s failed; returning no candidates", spill.id
        )
        return []


# ── read side ─────────────────────────────────────────────────────────────

def list_spills(limit: int = 100) -> list[dict]:
    """All stored spills, most recent first, without candidate-vessel detail."""
    with session_scope() as session:
        spills = OilSpillRepository(session).list_all(limit=limit)
        return [
            {
                "id": spill.id,
                "latitude": spill.centroid_latitude,
                "longitude": spill.centroid_longitude,
                "detected_at": spill.detected_at,
                "confidence": spill.confidence,
                "area": spill.area,
                "crs": spill.crs,
                "region_count": spill.region_count,
                "created_at": spill.created_at,
            }
            for spill in spills
        ]


def get_spill_detail(spill_id: str) -> Optional[dict]:
    """A stored spill plus its attributed vessels, or None if not found."""
    with session_scope() as session:
        spill = OilSpillRepository(session).get_by_id(spill_id)
        if spill is None:
            return None
        stored = AttributionRepository(session).list_for_spill_with_vessels(spill_id)
        geometry = spill.geometry_geojson
        created_at = spill.created_at

    geometry_obj = None
    if geometry:
        try:
            geometry_obj = json.loads(geometry)
        except (TypeError, ValueError):
            geometry_obj = None

    return {
        "id": spill.id,
        "latitude": spill.centroid_latitude,
        "longitude": spill.centroid_longitude,
        "detected_at": spill.detected_at,
        "confidence": spill.confidence,
        "area": spill.area,
        "crs": spill.crs,
        "region_count": spill.region_count,
        "geometry": geometry_obj,
        "created_at": created_at,
        "candidate_vessels": [_api_candidate(c) for c in stored],
    }


def get_spill_vessels(spill_id: str) -> Optional[list[dict]]:
    """Attributed vessels for a spill, or None if the spill does not exist."""
    with session_scope() as session:
        if OilSpillRepository(session).get_by_id(spill_id) is None:
            return None
        stored = AttributionRepository(session).list_for_spill_with_vessels(spill_id)
    return [_api_candidate(c) for c in stored]


def delete_spill(spill_id: str) -> bool:
    """Delete one stored oil spill; False if it did not exist."""
    with session_scope() as session:
        return OilSpillRepository(session).delete_by_id(spill_id)


def delete_all_spills() -> int:
    """Purge every stored oil spill; returns the number deleted."""
    with session_scope() as session:
        return OilSpillRepository(session).delete_all()