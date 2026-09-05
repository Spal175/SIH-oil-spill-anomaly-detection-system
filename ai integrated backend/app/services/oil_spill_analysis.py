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

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.database.connection import session_scope
from app.database.repositories import AttributionRepository, OilSpillRepository
from app.services.attribution_service import attribution_service
from app.services.gis_service import gis_service
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


def analyze_tiff(
    tiff_path: str,
    threshold: Optional[float] = None,
    min_area_px: Optional[int] = None,
) -> dict:
    """Run the full detection + attribution pipeline on a validated TIFF.

    Returns a dict matching ``OilSpillAnalyzeResponse``. No DB record is
    created and no attribution runs when no oil is detected. AIS search /
    attribution is best-effort: a failure there never discards a saved
    detection (it is logged and surfaced as an empty candidate list).
    """
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
                geometry_geojson=(
                    json.dumps(geo["geometry"]) if geo.get("geometry") else None
                ),
            )
    except Exception as exc:
        logger.exception("failed to persist oil spill for %s", tiff_path)
        raise DBError() from exc

    ranked = _attribute_for_spill(spill)
    return {
        "spill": _build_spill_dict(spill, geo),
        "candidate_vessels": [_api_candidate(c) for c in ranked],
    }


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