# Architecture Notes — Oil-Spill Detection & Vessel-Attribution Backend

This document is an inspection report of the **current** project (nothing has been
modified). It records what already exists, their input/output interfaces,
dependencies, gaps, and where the FastAPI backend / AIS / PostGIS pieces should
integrate.

---

## 1. Existing Files (full inventory)

| File | Role |
|------|------|
| `model (1).py` | U-Net architecture + model loader (`build_model`, `load_model`). |
| `preprocessing (1).py` | Grayscale read, binary masking, per-image normalization. |
| `predict (1).py` | Inference driver → builds the ML output contract. |
| `gis_extract.py` | Converts a binary mask → lat/lon regions / bbox / centroid / area. |
| `oil_spill_unet.pt` | Trained weights checkpoint (~96 MB). |
| `requirements.txt` | Dependency list (already includes FastAPI/DB/AIS pieces). |

**Not present (important):** there is **no** FastAPI app, **no** mock AIS code,
**no** database code, **no** README, **no** `.env` / `.env.example`, and **no**
`config.py`. `requirements.txt` already lists `fastapi`, `uvicorn`, `psycopg2`,
`sqlalchemy`, `alembic`, `websockets`, `httpx`, `python-dotenv` — so the intended
backend stack is pre-declared even though the modules don't exist yet.

> Note: `predict (1).py`, `model (1).py`, `preprocessing (1).py` were written
> assuming a `src/oil_spill/...` package layout with a sibling `config.py`
> (`from config import config`, `from oil_spill.model import load_model`).
> **That layout is not present in this directory**, so those three files
> **cannot be imported as-is** right now. They are analyzed here for interface
> reuse; integration will need a `config.py` / package shim (see §5).

---

## 2. ML Model — `model (1).py` + `oil_spill_unet.pt`

### How it is called / loaded
- `build_model(in_ch, base, depth)` constructs a `UNet` from config values.
- `load_model(path, device)`:
  - `.pt` → `torch.load(path, map_location="cpu")`, reads `state["model_state"]`
    and `state["config"]`, builds a `UNet` using config values, loads weights,
    sets `.eval()`, sets `model.version`, moves to `device`.
  - `.pkl` → `pickle.load`, wraps a whole `UNet` (not used here).
- The checkpoint `oil_spill_unet.pt` embeds its own `config` dict:

```
epoch=2, MODEL_INPUT_CHANNELS=1, IMAGE_CHANNELS=1, FIRST_FILTERS=32,
DEPTH=4, CLASSES=2, NORMALIZATION=per_image, THRESHOLD=0.5,
MIN_CONNECTED_AREA=8, MIN_OIL_PIXELS=10, IMAGE_SIZE=256
```

### Input expected
- Tensor shape `(1, 1, H, W)` — single grayscale channel, batch dim 1.
- Feed through `predict.to_model_input()` (normalize 0..255 → `per_image`,
  add batch+channel dims) and `preprocessing.normalize(img, "per_image")`
  (mean/std per image, returns `(1,H,W)`).
- `in_ch == 1`, `out_conv` weight is `[1, 32, 1, 1]` → **single output channel**.

### Output returned
- Raw logit per pixel `(1, 1, H, W)` from `model(x)`.
- Apply `torch.sigmoid` → probability map `(H, W)` in `[0,1]`.
- Threshold (`>= THRESHOLD=0.5`) → binary `{0,1}` `(H, W)` uint8 mask.

### Summary of ML interface (for you)
- **It does NOT return geo coordinates.** It returns a raw per-pixel probability
  `(H,W)` that is thresholded into a `{0,1}` mask. Geography comes from the GIS
  code (§3), not from the model.

### Reuse points
- `UNet`, `DoubleConv`, `Down`, `Up` — reusable as-is if given a `config` shim.
- `load_model()` already reads the embedded config, so it can load
  `oil_spill_unet.pt` without a hand-written `config.py` **as long as the
  `config` import is satisfied** (either provide a real `config.py` or refactor
  to not require it). Prefer a thin `config.py` shim (values above) to keep the
  files untouched.

---

## 3. GIS Extraction — `gis_extract.py`

### Inputs / core function
- `mask_to_geo(binary, crs=None, transform=None, min_area=0)` — the core.
- `mask_from_file(mask_path, image_path=None, min_area=0)` — convenience wrapper:
  reads CRS + affine transform from a **GeoTIFF** (the mask itself, else the
  source image), then calls `mask_to_geo`.

### How it reads the TIFF
- Uses `rasterio.open(...)` to read band 1 and extract `src.crs` + `src.transform`.
- Fallback for non-TIFF: PIL `Image.open().convert("L")`.

### How it maps pixels/masks → geographic coordinates
- `affine_mul(transform, col, row)` applies the rasterio affine
  (`x = a*col + b*row + c`, `y = d*col + e*row + f`).
- `geo_of_pixel()` converts one pixel → `(lat, lon)` in **WGS84 (EPSG:4326)**,
  reprojecting from the source CRS via `rasterio.warp.transform`.
- `pixel_size_m2()` → ground pixel area in m² (uses affine `a,b,d,e`).
- `connected_components()` → labels 8-connected oil blobs (cv2, or a pure-numpy
  fallback if cv2 missing).
- For each region and the whole image it computes: `bbox_latlon`,
  `centroid_latlon`, `area_m2`, plus pixel-space stats.

### Return shape
```
{
  "oil_pixels": int,
  "regions": int,
  "has_georeferencing": bool,
  "pixel_size_m2": float|None,
  "area_m2": float|None,
  "bbox_latlon": [lat0, lon0, lat1, lon1]|None,
  "centroid_latlon": [lat, lon]|None,
  "regions_geo": [ {region_id, area_px, area_m2, bbox_px, bbox_latlon, centroid_latlon} ]
}
```

### Timestamp
- **NO timestamp is extracted here.** Neither the model nor GIS code reads any
  acquisition timestamp. The SAR TIFF's acquisition time must be read separately
  (e.g. from the GeoTIFF metadata / tag or the filename) to link detections to
  AIS-bearing vessels at that moment.

### Reuse
- `mask_to_geo` / `mask_from_file` are the single geographic-entry point. Call
  them with the model's binary mask + the source georeferenced TIFF.

---

## 4. Dependencies

From `requirements.txt` (already complete for the target stack):

- **ML / data:** `numpy`, `pandas`, `pillow`, `torch`, `opencv-python-headless`.
- **GIS:** `rasterio` (optional, guarded in code — functions degrade gracefully
  if missing).
- **DB:** `psycopg2-binary`, `sqlalchemy`, `alembic`.
- **AIS:** `websockets`, `httpx`.
- **API:** `fastapi`, `uvicorn`, `pydantic`.
- **Config/env:** `python-dotenv`.

`torch` is required to load the `.pt` checkpoint. `rasterio` is currently
optional (GIS code has `HAS_RASTERIO` fallbacks) but is effectively required for
real georeferencing.

---

## 5. Gaps / Missing Pieces

1. **No FastAPI application** — nothing to serve HTTP yet.
2. **No AIS WebSocket consumer / client** — nothing connects to an AIS feed and
   nothing "mocks" it.
3. **No database layer** — no models, migrations (`alembic`), connection setup,
   or PostGIS tables.
4. **No `config.py` / package shim** — `model (1).py` / `predict (1).py` /
   `preprocessing (1).py` import `config` and `oil_spill.*`, which don't exist in
   this folder. Must be provided (thin) so those files import unchanged.
5. **No timestamp extraction** — needed to correlate a detection with vessels
   (see §3).
6. **No vessel attribution logic** — nearest-vessel / plume-intersection querying
   against AIS positions is unimplemented.
7. **No README / `.env.example`** — environment config for DB URI, AIS URL, model
   path, thresholds is undeclared.
8. **Input image source undefined** — where the SAR TIFF comes from at runtime
   (upload? filesystem watch? URL?) is not specified.

---

## 6. Recommended Integration Points (for the future build)

- **Model serving:** wrap `load_model("oil_spill_unet.pt")` once at startup, keep
  an `UNet` in `eval()` on the chosen device; a thin `config.py` with the values
  from §2 keeps `model (1).py` importable as-is.
- **Inference:** reuse `to_model_input` + `torch.sigmoid` + threshold → `binary`.
- **Geo localization:** call `gis_extract.mask_to_geo(binary, crs, transform)`
  (or `mask_from_file`) with the source TIFF; keep the returned dict verbatim.
- **Timestamp:** add a small reader for the SAR TIFF's acquisition time (metadata
  or filename) — a new, non-destructive addition.
- **DB/PostGIS:** persist the `mask_to_geo` result and the timestamp; AIS traffic
  goes to a spatiotemporal table (PostGIS `geometry(Point, 4326)` + time).
- **AIS:** connect the WebSocket feed and upsert AIS positions with ts; the mock
  can be a separate script emitting the same message schema.
- **Vessel attribution:** spatiotemporal query — plumes within a radius/timeslice
  of a detection centroid/bbox → candidate vessels with distance/heading.

### Non-negotiable
- Do **not** rewrite, replace, or delete `model (1).py`, `preprocessing (1).py`,
  `predict (1).py`, `gis_extract.py`, or `oil_spill_unet.pt`. Any new config /
  timestamps must be additive so the ML/GIS behavior is unchanged.
