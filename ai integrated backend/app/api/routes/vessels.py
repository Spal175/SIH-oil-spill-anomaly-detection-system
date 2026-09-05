"""Vessel routes (thin: HTTP + schema wrapper around the read services)."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas.vessel import VesselDetail, VesselTrajectoryResponse
from app.services.ais_service import vessel_query_service

router = APIRouter(prefix="/vessels", tags=["vessels"])


@router.get("/{mmsi}", response_model=VesselDetail)
async def get_vessel(mmsi: int) -> dict:
    """Return the static vessel information for an MMSI."""
    vessel = vessel_query_service.get_vessel(mmsi)
    if vessel is None:
        raise HTTPException(status_code=404, detail=f"vessel {mmsi} not found")
    return vessel["vessel"]


@router.get("/{mmsi}/trajectory", response_model=VesselTrajectoryResponse)
async def get_vessel_trajectory(
    mmsi: int,
    start: Optional[str] = Query(default=None, description="Start timestamp (ISO-8601)"),
    end: Optional[str] = Query(default=None, description="End timestamp (ISO-8601)"),
) -> dict:
    """Return a vessel's chronological AIS position reports.

    Optional ``start`` / ``end`` ISO-8601 timestamps bound the returned window.
    """
    from datetime import datetime, timezone

    start_dt, end_dt = None, None
    for raw, target in ((start, "start"), (end, "end")):
        if raw is None:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"invalid {target} timestamp: {raw!r}"
            )
        if target == "start":
            start_dt = parsed
        else:
            end_dt = parsed

    trajectory = vessel_query_service.get_trajectory(mmsi, start=start_dt, end=end_dt)
    if trajectory is None:
        raise HTTPException(status_code=404, detail=f"vessel {mmsi} not found")
    return trajectory