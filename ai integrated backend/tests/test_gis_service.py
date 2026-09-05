"""Integration tests for the GIS service against a real GeoTIFF + sample masks.

Uses `tests/fixtures/sample_scene_georef.tif` (the 256x256 Sentinel-1 crop
re-written with a real CRS/transform):
    CRS EPSG:4326, pixel 0.0005 deg, origin (-9.0, 39.5)
    footprint -> lon -9.0..-8.872, lat 39.372..39.5

The ML mask test reuses the REAL U-Net output via `ml_service` (same raster
data, so mask pixels align 1:1 with the georeferenced fixture).
"""
import os
from pathlib import Path

import numpy as np
import pytest

from app.services.gis_service import (
    GISService,
    extract_acquisition_time,
    gis_service,
)

FIXTURES = Path(__file__).parent / "fixtures"
GEO_REF_TIFF = FIXTURES / "sample_scene_georef.tif"
PLAIN_TIFF = FIXTURES / "sample_scene.tif"

EXPECTED_LON = (-9.0, -8.872)  # (min, max) footprint
EXPECTED_LAT = (39.372, 39.5)


def _bbox_corners(geo: dict):
    """Pull the 4 lon/lat corners of a GeoJSON polygon."""
    ring = geo["coordinates"][0]
    return [(lon, lat) for lon, lat in ring[:-1]]


def test_expected_footprint():
    assert GEO_REF_TIFF.exists()
    from rasterio.transform import from_origin

    import rasterio

    with rasterio.open(GEO_REF_TIFF) as src:
        assert str(src.crs) == "EPSG:4326"
        assert src.transform == from_origin(-9.0, 39.5, 0.0005, 0.0005)
        assert (src.width, src.height) == (256, 256)


def test_extract_custom_mask_inside_footprint():
    mask = np.zeros((256, 256), dtype=np.uint8)
    mask[100:121, 110:131] = 1  # 21x21 hard-1 rectangle

    geo = gis_service.extract(mask, str(GEO_REF_TIFF))

    assert geo["has_georeferencing"] is True
    assert geo["crs"] == "EPSG:4326"
    assert geo["image_dimensions"] == {"width": 256, "height": 256}
    assert geo["image_bounds"] == {
        "left": -9.0, "bottom": 39.372, "right": -8.872, "top": 39.5,
    }
    assert geo["oil_pixels"] == 21 * 21
    assert geo["region_count"] == 1
    assert geo["latitude"] is not None and geo["longitude"] is not None
    assert EXPECTED_LAT[0] <= geo["latitude"] <= EXPECTED_LAT[1]
    assert EXPECTED_LON[0] <= geo["longitude"] <= EXPECTED_LON[1]
    assert geo["area"] is not None and geo["area"] >= 0.0

    # Every geometry corner must lie inside the GeoTIFF footprint.
    for lon, lat in _bbox_corners(geo["geometry"]):
        assert EXPECTED_LON[0] <= lon <= EXPECTED_LON[1]
        assert EXPECTED_LAT[0] <= lat <= EXPECTED_LAT[1]

    reg = geo["regions"][0]
    for lon, lat in _bbox_corners(reg["geometry"]):
        assert EXPECTED_LON[0] <= lon <= EXPECTED_LON[1]
        assert EXPECTED_LAT[0] <= lat <= EXPECTED_LAT[1]

    assert isinstance(reg["centroid_px"], list)


def test_extract_ml_mask_inside_footprint():
    pytest.importorskip("torch")
    from app.services.ml_service import ml_service

    def _get_mask():
        return ml_service.run_oil_spill_model(str(PLAIN_TIFF))

    # Deterministic model fixpoint: run once, if the model flags pixels the
    # GIS result must still land inside the footprint.
    mask = _get_mask()
    geo = gis_service.extract(mask, str(GEO_REF_TIFF))

    assert geo["oil_pixels"] > 0
    assert geo["latitude"] is not None and geo["longitude"] is not None
    assert EXPECTED_LAT[0] <= geo["latitude"] <= EXPECTED_LAT[1]
    assert EXPECTED_LON[0] <= geo["longitude"] <= EXPECTED_LON[1]
    for lon, lat in _bbox_corners(geo["geometry"]):
        assert EXPECTED_LON[0] <= lon <= EXPECTED_LON[1]
        assert EXPECTED_LAT[0] <= lat <= EXPECTED_LAT[1]


def test_no_oil_returns_empty_geography():
    mask = np.zeros((256, 256), dtype=np.uint8)
    geo = gis_service.extract(mask, str(GEO_REF_TIFF))
    assert geo["oil_pixels"] == 0
    assert geo["region_count"] == 0
    assert geo["latitude"] is None and geo["longitude"] is None
    assert geo["geometry"] is None


def test_shape_mismatch_raises():
    mask = np.zeros((128, 128), dtype=np.uint8)
    with pytest.raises(ValueError, match="does not match GeoTIFF"):
        gis_service.extract(mask, str(GEO_REF_TIFF))


def test_acquisition_time_from_s1_filename():
    name = "S1A_IW_GRDH_1SDV_20211013T064329_20211013T064354_040097_04BF7D_66FF.tiff"
    dt = extract_acquisition_time(name)
    assert dt is not None
    assert dt.isoformat() == "2021-10-13T06:43:29+00:00"


def test_acquisition_time_from_real_tiff():
    """Full pipeline on the actual Sentinel-1 product (env-gated, not hardcoded)."""
    sample = os.getenv("S1_SAMPLE_TIFF")
    if not sample or not Path(sample).exists():
        pytest.skip("set S1_SAMPLE_TIFF to the sample Sentinel-1 TIFF to enable")

    import rasterio

    with rasterio.open(sample) as src:
        height, width = src.height, src.width
    mask = np.zeros((height, width), dtype=np.uint8)
    geo = gis_service.extract(mask, sample)
    assert geo["detected_at"] is not None
    assert geo["detected_at"].startswith("2021-10-13T06:43:29")
    assert geo["image_dimensions"] == {"width": width, "height": height}
    assert geo["has_georeferencing"] is True or geo["crs"] is None