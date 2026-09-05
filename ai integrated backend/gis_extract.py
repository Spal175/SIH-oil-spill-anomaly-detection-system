"""Extract oil-spill locations (lat/lon) from the model's binary mask.

The model returns a HxW binary mask (0 / 1) whose pixels line up 1:1 with the
input image. To turn that into geo-coordinates we need the source image's
georeferencing (CRS + affine transform). That is preserved automatically when
the input is a georeferenced TIFF (see predict.py / rasterio); PNGs carry no
geo info, so for those you must supply the corner coordinates.

Two entry points:

1) mask + source TIFF (recommended):
       res = mask_from_file(mask_path, image_path)   # or pass arrays below

2) raw model output + georeferencing (in-code use):
       res = mask_to_geo(binary, crs, transform)     # crs, transform from rasterio.open(src)

Returns per-region + overall:
    - bounding box in lat/lon
    - centroid in lat/lon
    - oil area in m^2
"""
import argparse
import json
from pathlib import Path

import numpy as np

try:
    import rasterio
    from rasterio.warp import transform as _rio_transform
    from rasterio.crs import CRS as _RasterioCRS
    HAS_RASTERIO = True
except Exception:
    HAS_RASTERIO = False

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

WGS84 = "EPSG:4326"


def affine_mul(transform, col, row):
    """Apply an affine[2x3] to (col, row) -> (x, y) without needing the affine lib.

    transform: rasterio/affine object exposing .a .b .c .d .e .f
    """
    try:
        t = transform
        x = t.a * col + t.b * row + t.c
        y = t.d * col + t.e * row + t.f
    except AttributeError:
        raise ValueError(
            "transform must be a rasterio/affine object with .a .b .c .d .e .f, "
            "got %r" % (type(transform).__name__,)
        )
    return x, y


def to_wgs84(lons, lats, crs):
    """Reproject lon/lat arrays from `crs` to EPSG:4326.

    Returns (lats_wgs84, lons_wgs84); identity if crs is None or already 4326.
    """
    if crs is None:
        return np.asarray(lats), np.asarray(lons)
    if HAS_RASTERIO:
        try:
            if not isinstance(crs, _RasterioCRS):
                crs = _RasterioCRS.from_user_input(crs)
            if crs == _RasterioCRS.from_epsg(4326) or crs.to_epsg() == 4326:
                return np.asarray(lats), np.asarray(lons)
            xs, ys = _rio_transform(crs, WGS84, list(lons), list(lats))
            return np.asarray(ys), np.asarray(xs)
        except Exception:
            pass
    warned = getattr(to_wgs84, "warned", False)
    if not warned:
        import warnings
        warnings.warn(
            "crs (%s) is not WGS84 but rasterio is unavailable to reproject; "
            "returning raw CRS coordinates" % crs
        )
        to_wgs84.warned = True
    return np.asarray(lats), np.asarray(lons)


def connected_components(binary):
    """Label 8-connected oil regions.

    Returns (labels, stats) with the same layout as cv2.connectedComponentsWithStats:
    stats[i] = [left, top, width, height, area].
    """
    if _HAS_CV2:
        _, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        return labels, stats
    h, w = binary.shape
    labels = np.zeros((h, w), dtype=np.int32)
    stats = []
    for r in range(h):
        for c in range(w):
            if binary[r, c] == 1 and labels[r, c] == 0:
                n = len(stats) + 1
                stack = [(r, c)]
                labels[r, c] = n
                left, top, right, bottom = c, r, c, r
                area = 0
                while stack:
                    cr, cc = stack.pop()
                    area += 1
                    left, top = min(left, cc), min(top, cr)
                    right, bottom = max(right, cc), max(bottom, cr)
                    for nr in range(max(cr - 1, 0), min(cr + 2, h)):
                        for nc in range(max(cc - 1, 0), min(cc + 2, w)):
                            if binary[nr, nc] == 1 and labels[nr, nc] == 0:
                                labels[nr, nc] = n
                                stack.append((nr, nc))
                stats.append([left, top, right - left + 1, bottom - top + 1, area])
    # match cv2 layout: index 0 is the background "component"
    stats = np.array([[0, 0, 0, 0, 0]] + stats, dtype=np.int32).reshape(-1, 5)
    return labels, stats


def centroid_of_binary(binary):
    """Pixel centroid of all oil pixels: (col, row)."""
    idx = np.argwhere(binary > 0)
    if idx.size == 0:
        return None
    col = float(idx[:, 1].mean())
    row = float(idx[:, 0].mean())
    return col, row


def bbox_of_binary(binary):
    """Pixel bounding box of all oil pixels: (x0, y0, x1, y1)."""
    idx = np.argwhere(binary > 0)
    if idx.size == 0:
        return None
    x1, y1 = idx[:, 1].max(), idx[:, 0].max()
    x0, y0 = idx[:, 1].min(), idx[:, 0].min()
    return int(x0), int(y0), int(x1), int(y1)


def as_binary_mask(pred):
    """Coerce a model output (prob/HxW/1xHxW/binary/uint8 file path) to {0,1} HxW."""
    if isinstance(pred, (str, Path)):
        path = Path(pred)
        if HAS_RASTERIO and path.suffix.lower() in (".tif", ".tiff"):
            with rasterio.open(path) as src:
                a = src.read(1)
        else:
            from PIL import Image
            a = np.array(Image.open(path).convert("L")).astype(np.float32)
    else:
        a = np.asarray(pred, dtype=np.float32)
        if a.ndim == 3 and a.shape[0] == 1:
            a = a[0]
        elif a.ndim == 3:
            a = a[..., 0]
    if a.max() > 1.0 + 1e-6:
        a = a / 255.0
    return (a >= 0.5).astype(np.uint8)


def geo_of_pixel(transform, col, row, crs=None):
    """Convert one pixel to (lat, lon) in WGS84."""
    x, y = affine_mul(transform, col, row)
    lats, lons = to_wgs84([x], [y], crs)
    return float(lats[0]), float(lons[0])


def pixel_size_m2(transform):
    """Ground size of one pixel in m^2 (assumes projected CRS, e.g. UTM)."""
    if transform is None:
        return None
    dx = np.hypot(transform.a, transform.d)
    dy = np.hypot(transform.b, transform.e)
    return abs(dx * dy)


def mask_to_geo(binary, crs=None, transform=None, min_area=0):
    """Core: map a HxW {0,1} mask to oil-spill lat/lon info.

    binary    : np.ndarray HxW of {0,1} (model output), or path to a mask file
    crs       : rasterio CRS of the source image (or None -> assume WGS84)
    transform : rasterio/affine transform of the source image (required)

    Returns a dict with overall and per-region geographic details.
    """
    binary = as_binary_mask(binary)
    oil_pixels = int((binary > 0).sum())

    if transform is not None:
        px = pixel_size_m2(transform)
        area_m2 = float(oil_pixels * px) if px is not None else None
    else:
        px = None
        area_m2 = None

    labels, stats = connected_components(binary)

    regions = []
    for i in range(1, len(stats)):
        area = int(stats[i, 4])
        if min_area and area < min_area:
            continue
        left, top, width, height = (int(v) for v in stats[i, :4])
        right, bottom = left + width - 1, top + height - 1
        cx, cy = left + width / 2.0, top + height / 2.0

        reg = {
            "region_id": i - 1,
            "area_px": area,
            "area_m2": float(area * px) if px else None,
            "bbox_px": [left, top, right, bottom],
            "bbox_latlon": None,
            "centroid_latlon": None,
        }
        if transform is not None:
            ll_lon, ll_lat = geo_of_pixel(transform, left + 0.5, bottom + 0.5, crs)
            ur_lon, ur_lat = geo_of_pixel(transform, right + 0.5, top + 0.5, crs)
            c_lon, c_lat = geo_of_pixel(transform, cx, cy, crs)
            reg["bbox_latlon"] = [ll_lat, ll_lon, ur_lat, ur_lon]
            reg["centroid_latlon"] = [c_lat, c_lon]
        regions.append(reg)

    result = {
        "oil_pixels": oil_pixels,
        "regions": len(regions),
        "has_georeferencing": transform is not None,
        "pixel_size_m2": px,
        "area_m2": area_m2,
        "bbox_latlon": None,
        "centroid_latlon": None,
        "regions_geo": regions,
    }

    if oil_pixels == 0:
        result["regions"] = 0
        return result

    if transform is not None:
        bbox = bbox_of_binary(binary)
        x0, y0, x1, y1 = bbox
        ccol, crow = centroid_of_binary(binary)
        lon0, lat0 = geo_of_pixel(transform, x0 + 0.5, y0 + 0.5, crs)
        lon1, lat1 = geo_of_pixel(transform, x1 + 0.5, y1 + 0.5, crs)
        clon, clat = geo_of_pixel(transform, ccol, crow, crs)
        result["bbox_latlon"] = [lat0, lon0, lat1, lon1]
        result["centroid_latlon"] = [clat, clon]

    return result


def mask_from_file(mask_path, image_path=None, min_area=0):
    """Convenience: read crs/transform, preferring the mask file itself.

    mask_path : model's probability/binary mask (GeoTIFF or PNG/array).
                If it's a georeferenced TIFF (e.g. saved by predict.save_geo),
                its CRS + transform are used.
    image_path: the source TIFF the model processed (carries CRS + transform);
                used when the mask file has no georeferencing.
    """
    binary = as_binary_mask(mask_path)
    crs = transform = None
    mpath = Path(mask_path)
    if HAS_RASTERIO and mpath.suffix.lower() in (".tif", ".tiff"):
        with rasterio.open(mpath) as src:
            crs = src.crs
            transform = src.transform
    if not transform and image_path and HAS_RASTERIO:
        path = Path(image_path)
        if path.suffix.lower() in (".tif", ".tiff"):
            with rasterio.open(path) as src:
                crs = src.crs
                transform = src.transform
    return mask_to_geo(binary, crs=crs, transform=transform, min_area=min_area)


def main():
    ap = argparse.ArgumentParser(
        description="Extract oil-spill lat/lon from the model's binary mask."
    )
    ap.add_argument("mask", help="binary/probability mask file (GeoTIFF or PNG)")
    ap.add_argument("--image", default=None,
                    help="source georeferenced TIFF the model ran on (provides CRS+transform)")
    ap.add_argument("--min-area", type=int, default=0,
                    help="drop regions smaller than this many pixels")
    ap.add_argument("--out", default=None, help="optional JSON output path")
    args = ap.parse_args()

    res = mask_from_file(args.mask, args.image, min_area=args.min_area)
    text = json.dumps(res, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)


if __name__ == "__main__":
    main()