"""GIS/georeferencing service.

Thin, non-destructive wrapper around the existing `gis_extract.py` module. It
turns an ML-produced 0/1 mask plus the source GeoTIFF into a normalized,
JSON-friendly geography payload:

    ML mask pixel
    --> GeoTIFF CRS + affine transform
    --> lon/lat (WGS84)
    --> centroid / bbox / area / geometry + Sentinel-1 acquisition time

The existing `gis_extract.mask_to_geo` is the authoritative pixel->geo engine
(it reads the TIFF's CRS/transform/bounds and reprojects to EPSG:4326). This
service only adds:
  * reading the source GeoTIFF metadata (CRS, transform, bounds, dimensions),
  * extracting the satellite acquisition timestamp (filename/tags/passed-in),
  * normalizing the result into a stable dict with GeoJSON geometry,
  * plumbing an optional confidence value through.

No vessel search here.
"""
from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import rasterio

from app.config import settings

PROJECT_ROOT = settings.base_dir

# Existing GIS module lives at the project root (`gis_extract.py`).
_GIS_MODULE = "gis_extract.py"
_S1_FILENAME_RE = re.compile(
    r"(S1[AB]_[A-Z0-9_]{6,}_(\d{8}T\d{6})_(\d{8}T\d{6})_[\w.]+\.(tif|tiff))$",
    re.IGNORECASE,
)
_ISO_IN_FILENAME_RE = re.compile(r"(\d{4}-?\d{2}-?\d{2}[T_]\d{2}:?\d{2}:?\d{2}(?:Z)?)")

WGS84 = "EPSG:4326"


def _load_gis_module():
    """Import the existing gis_extract.py from the project root on demand."""
    path = PROJECT_ROOT / _GIS_MODULE
    if not path.exists():
        raise RuntimeError(f"existing GIS module not found: {path}")
    spec = importlib.util.spec_from_file_location("oil_spill_gis_extract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a datetime from a tag/filename string, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip().strip('"').strip("'")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%Y%m%dT%H%M%S")
    except ValueError:
        pass
    return None


def extract_acquisition_time(
    image_path: Optional[str] = None, tags: Optional[dict] = None
) -> Optional[datetime]:
    """Best-effort Sentinel-1 acquisition (observation) time.

    Sources, in priority order:
      1. GeoTIFF tags whose name suggests a date/time,
      2. Known Sentinel-1 filename pattern (start time of the SLC/GRD frame),
         e.g. S1A_IW_GRDH_1SDV_20211013T064329_20211013T064354_...

    The returned timestamp is the satellite ACQUISITION/observation time, not
    necessarily the physical oil-release time.
    """
    for tag, value in (tags or {}).items():
        key = str(tag).upper()
        if any(part in key for part in ("TIME", "DATE", "ACQUISITION")):
            parsed = _parse_dt(value)
            if parsed is not None:
                return parsed
    if image_path:
        name = Path(image_path).name
        m = _S1_FILENAME_RE.search(name)
        if m:
            try:
                return datetime.strptime(m.group(2), "%Y%m%dT%H%M%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass
        m = _ISO_IN_FILENAME_RE.search(name)
        if m:
            parsed = _parse_dt(m.group(1))
            if parsed is not None:
                return parsed
    return None


def _bbox_to_geojson_polygon(bbox_latlon):
    """[lon0, lat0, lon1, lat1] (lower-left, upper-right) -> GeoJSON Polygon."""
    if not bbox_latlon:
        return None
    lon0, lat0, lon1, lat1 = bbox_latlon
    ring = [
        [lon0, lat0],
        [lon1, lat0],
        [lon1, lat1],
        [lon0, lat1],
        [lon0, lat0],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


class GISService:
    """Combine a 0/1 mask with its source GeoTIFF to produce geo info."""

    def __init__(self) -> None:
        self._module = None

    @property
    def module(self):
        if self._module is None:
            self._module = _load_gis_module()
        return self._module

    def extract(
        self,
        binary_mask,
        geotiff_path: str,
        min_area_px: int = 0,
        acquisition_time: Optional[datetime] = None,
        confidence: Optional[float] = None,
    ) -> dict:
        """Run the existing geo pipeline on mask + GeoTIFF.

        binary_mask : HxW {0,1} array (ML output) matching the GeoTIFF dims.
        geotiff_path: source GeoTIFF the model processed (carries CRS+transform).
        acquisition_time: override the timestamp normally read from the TIFF.
        confidence  : optional ML confidence, forwarded into the result.

        Returns a normalized dict; all geography is in WGS84 lon/lat.
        """
        mask = np.asarray(self.module.as_binary_mask(binary_mask))

        with rasterio.open(geotiff_path) as src:
            crs = src.crs
            transform = src.transform
            bounds = src.bounds
            width, height = src.width, src.height
            tags = src.tags()

        if mask.shape != (height, width):
            raise ValueError(
                f"mask shape {mask.shape} does not match GeoTIFF "
                f"dimensions {(height, width)}"
            )

        if acquisition_time is not None:
            acquired = acquisition_time
        else:
            acquired = extract_acquisition_time(geotiff_path, tags)

        geo = self.module.mask_to_geo(
            mask, crs=crs, transform=transform, min_area=min_area_px
        )

        has_geo = geo["has_georeferencing"]
        # Existing gis_extract returns lon/lat ordering in its *_latlon fields
        # (names are misleading: `clon, clat = geo_of_pixel(...)` actually puts
        # latitude into clon). So: centroid = [lon, lat], bbox = [lon0, lat0, lon1, lat1].
        centroid = geo.get("centroid_latlon")
        bbox = geo.get("bbox_latlon")
        latitude = centroid[1] if centroid else None
        longitude = centroid[0] if centroid else None

        regions_out = []
        for reg in geo.get("regions_geo", []):
            reg = dict(reg)
            reg["geometry"] = _bbox_to_geojson_polygon(reg.get("bbox_latlon"))
            reg["centroid_px"] = _region_centroid_px(reg)
            regions_out.append(reg)

        return {
            "has_georeferencing": has_geo,
            "crs": str(crs) if crs is not None else None,
            "transform": [float(v) for v in transform] if transform is not None else None,
            "image_bounds": _bounds_dict(bounds),
            "image_bounds_wgs84": _bounds_in_wgs84(bounds, crs),
            "image_dimensions": {"width": int(width), "height": int(height)},
            "oil_pixels": int(geo["oil_pixels"]),
            "region_count": int(geo["regions"]),
            "latitude": latitude,
            "longitude": longitude,
            "centroid_latlon": centroid,
            "bbox_latlon": bbox,
            "detected_at": (
                acquired.isoformat() if isinstance(acquired, datetime) else acquired
            ),
            "acquisition_time": (
                acquired.isoformat() if isinstance(acquired, datetime) else acquired
            ),
            "geometry": _bbox_to_geojson_polygon(bbox),
            "area": geo.get("area_m2"),  # m^2, per existing gis_extract
            "pixel_size_m2": geo.get("pixel_size_m2"),
            "confidence": confidence,
            "regions": regions_out,
        }


def _region_centroid_px(reg: dict) -> Optional[list]:
    bbox = reg.get("bbox_px")
    if not bbox:
        return None
    x0, y0, x1, y1 = bbox
    return [(x0 + x1) / 2.0, (y0 + y1) / 2.0]


def _bounds_dict(bounds) -> dict:
    if bounds is None:
        return None
    return {
        "left": float(bounds.left),
        "bottom": float(bounds.bottom),
        "right": float(bounds.right),
        "top": float(bounds.top),
    }


def _bounds_in_wgs84(bounds, crs) -> Optional[dict]:
    """Reproject the GeoTIFF bounds to WGS84 (identity when already 4326)."""
    if bounds is None or crs is None or str(crs) == WGS84:
        return _bounds_dict(bounds)
    try:
        import rasterio
        from rasterio.warp import transform_bounds

        transformed = transform_bounds(
            crs, WGS84, bounds.left, bounds.bottom, bounds.right, bounds.top
        )
        left, bottom, right, top = transformed
        # transform_bounds returns (left, bottom, right, top) in target CRS,
        # which for EPSG:4326 is already lon/lat.
        return {"left": left, "bottom": bottom, "right": right, "top": top}
    except Exception:
        return None


gis_service = GISService()