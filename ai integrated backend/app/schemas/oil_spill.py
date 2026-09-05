"""Pydantic schemas for the oil-spill analysis API.

Routes stay thin: they map service output to these validated shapes; all
business logic (ML, GIS, attribution mathematics, database) lives outside the
route layer.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OilSpillAnalyzeRequest(BaseModel):
    image_path: str = Field(..., description="Path to the SAR GeoTIFF to analyze")
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_area_px: Optional[int] = Field(default=None, ge=0)


class CandidateVessel(BaseModel):
    """A ranked vessel in the attribution result for a spill."""

    rank: int = Field(..., ge=1, description="Attribution rank, 1 = most probable")
    mmsi: int
    ship_name: Optional[str] = None
    ship_type: Optional[str] = Field(default=None, description="Human-readable AIS ship type")
    distance_km: Optional[float] = Field(default=None, ge=0)
    time_difference_minutes: Optional[float] = Field(default=None, ge=0)
    attribution_score: Optional[float] = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(
        default_factory=list,
        description="Human-readable reasons derived from the AIS observations",
    )


class SpillDetail(BaseModel):
    """Detected oil spill persisted by the analysis pipeline."""

    id: Optional[str] = Field(default=None, description="Stored spill id")
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    detected_at: Optional[datetime] = Field(
        default=None, description="Satellite acquisition time"
    )
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    area: Optional[float] = Field(default=None, ge=0, description="Area in m^2 when available")
    crs: Optional[str] = Field(default=None, description="Source GeoTIFF CRS")
    region_count: Optional[int] = Field(default=None, ge=0)


class OilSpillAnalyzeResponse(BaseModel):
    """POST /oil-spills/analyze result.

    ``spill`` is None when no oil is detected (no DB record). ``candidate_vessels``
    lists vessels attributed via spatial + temporal AIS search, ranked by score.
    This is an investigative ranking — a "probable source vessel", never a legal
    determination.
    """

    spill: Optional[SpillDetail] = None
    candidate_vessels: list[CandidateVessel] = Field(default_factory=list)


class OilSpillDetailResponse(BaseModel):
    """GET /oil-spills/{spill_id}: a stored spill plus its attributed vessels."""

    id: str
    latitude: float
    longitude: float
    detected_at: datetime
    confidence: Optional[float] = None
    area: Optional[float] = Field(default=None, ge=0)
    crs: Optional[str] = None
    region_count: Optional[int] = None
    geometry: Optional[dict] = Field(default=None, description="GeoJSON geometry when available")
    created_at: Optional[datetime] = None
    candidate_vessels: list[CandidateVessel] = Field(default_factory=list)