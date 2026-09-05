"""Oil-spill routes (thin: validation + status mapping only).

Logic lives in services: the detection+attribution pipeline in
``app.services.oil_spill_analysis`` and read-side queries in the same module.
Routes never touch the database, ML, GIS, or attribution mathematics directly.
"""
import logging
import tempfile
from pathlib import Path
from typing import Optional

import rasterio
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from app.schemas.oil_spill import (
    OilSpillAnalyzeResponse,
    OilSpillDetailResponse,
)
from app.services.oil_spill_analysis import (
    AnalysisError,
    DBError,
    GISError,
    InvalidFileError,
    MLError,
    UnsupportedFileError,
    analyze_tiff,
    get_spill_detail,
    get_spill_vessels,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oil-spills", tags=["oil-spills"])

TIFF_EXTENSIONS = (".tif", ".tiff")
# TIFF byte-order marks: 'II*\x00' (little-endian) or 'MM\x00*' (big-endian)
_TIFF_MAGICS = (b"II*\x00", b"MM\x00*")

_ERROR_STATUS = {
    UnsupportedFileError: 415,
    InvalidFileError: 400,
    MLError: 502,
    GISError: 500,
    DBError: 503,
}


def _validate_upload(file: UploadFile) -> None:
    if not file or not file.filename:
        raise UnsupportedFileError()
    ext = Path(file.filename).suffix.lower()
    if ext not in TIFF_EXTENSIONS:
        raise UnsupportedFileError()
    # Content/magic + driver validation runs on the saved temp file
    # in `_validate_tiff_file`; here only the extension/media contract.


def _validate_tiff_file(path: Path) -> None:
    """Confirm the bytes are a real, rasterio-readable GeoTIFF."""
    with path.open("rb") as fh:
        head = fh.read(8)
    if not head.startswith(_TIFF_MAGICS):
        raise InvalidFileError()
    try:
        with rasterio.open(path) as src:
            driver = (src.driver or "").upper()
    except Exception:
        raise InvalidFileError()
    if driver != "GTIFF":
        raise UnsupportedFileError()


@router.post("/analyze", status_code=201, response_model=OilSpillAnalyzeResponse)
async def analyze_spill(
    response: Response,
    file: UploadFile = File(...),
    threshold: Optional[float] = Form(default=None, ge=0.0, le=1.0),
    min_area_px: Optional[int] = Form(default=None, ge=0),
) -> dict:
    """Analyze an uploaded SAR GeoTIFF and attribute candidate vessels.

    Pipeline: validate TIFF -> ML -> 0/1 mask -> GIS georeferencing -> save
    spill -> spatial + temporal AIS search -> attribution scoring -> persist ->
    ranked candidate vessels. Returns 201 with the spill + candidates when oil
    is detected, or 200 with ``spill: null`` when it is not. Uploaded files live
    in a temp directory and are removed after processing.
    """
    try:
        _validate_upload(file)
    except UnsupportedFileError:
        raise HTTPException(status_code=415, detail=UnsupportedFileError.client_detail)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "upload.tiff"
            with tmp_path.open("wb") as out:
                out.write(await file.read())
            _validate_tiff_file(tmp_path)
            result = analyze_tiff(
                str(tmp_path), threshold=threshold, min_area_px=min_area_px
            )
    except AnalysisError as exc:
        status = _ERROR_STATUS.get(type(exc), 500)
        if status >= 500:
            logger.exception("pipeline error (%s)", type(exc).__name__)
        raise HTTPException(status_code=status, detail=type(exc).client_detail) from exc
    except Exception as exc:
        logger.exception("unexpected error while analyzing upload")
        raise HTTPException(status_code=500, detail="internal error") from exc

    response.status_code = 201 if result["spill"] is not None else 200
    return result


@router.get("/{spill_id}", response_model=OilSpillDetailResponse)
async def get_spill(spill_id: str) -> dict:
    """Return a stored spill with its attributed candidate vessels."""
    detail = get_spill_detail(spill_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"oil spill {spill_id} not found",
        )
    return detail


@router.get("/{spill_id}/vessels", response_model=list)
async def get_spill_vessels_route(spill_id: str) -> list:
    """Return the attributed candidate vessels for a stored spill."""
    vessels = get_spill_vessels(spill_id)
    if vessels is None:
        raise HTTPException(
            status_code=404,
            detail=f"oil spill {spill_id} not found",
        )
    return vessels