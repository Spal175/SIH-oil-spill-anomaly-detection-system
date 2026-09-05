"""Run inference with a trained model on a single image or an entire split.

Produces the ML-side output contract from src/../03_ml_gis_interface.md:
  - probability mask (GeoTIFF if the source is georeferenced, else PNG)
  - binary mask
  - detection decision + confidence + threshold + metadata

Run (single image):
    python src/oil_spill/predict.py --checkpoint outputs/checkpoints/<name>.pt \
        --input images/val/palsar_0.png --out-dir outputs/predictions

Run (full split):
    python src/oil_spill/predict.py --checkpoint ... --split val
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
for _p in (SRC, PROJECT_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np
import torch
from PIL import Image

from config import config
from oil_spill.model import load_model
from oil_spill.preprocessing import normalize

try:
    import rasterio
    HAS_RASTERIO = True
except Exception:  # rasterio not installed
    HAS_RASTERIO = False


def load_input(path: Path):
    """Return (array HxW float or HxWxC, crs, transform) preserving georef if present."""
    crs = None
    transform = None
    if HAS_RASTERIO and path.suffix.lower() in (".tif", ".tiff"):
        try:
            with rasterio.open(path) as src:
                arr = src.read()  # (C,H,W)
                crs = src.crs
                transform = src.transform
                if arr.shape[0] == 1:
                    arr = arr[0]
                else:
                    arr = np.moveaxis(arr, 0, -1)
                return arr, crs, transform
        except Exception:
            pass
    img = Image.open(path).convert("L")
    return np.array(img).astype(np.float32), crs, transform


def to_model_input(arr: np.ndarray) -> torch.Tensor:
    """Bring an arbitrary input array to (1,1,H,W) normalized."""
    if arr.ndim == 3:
        arr = arr[..., :1] if arr.shape[2] > 1 else arr[..., 0]
    if arr.max() > 1.0 + 1e-6:  # assume uint8 scale 0..255
        arr = arr / 255.0
    arr = np.ascontiguousarray(arr)
    return normalize(arr, "per_image")[None, ...]


def save_geo(out_path: Path, prob: np.ndarray, crs, transform):
    if HAS_RASTERIO and crs is not None:
        with rasterio.open(
            out_path, "w", driver="GTiff", height=prob.shape[0], width=prob.shape[1],
            count=1, dtype="float32", crs=crs, transform=transform,
        ) as dst:
            dst.write(prob.astype("float32"), 1)
        return True
    Image.fromarray((prob * 255).astype(np.uint8)).save(out_path.with_suffix(".png"))
    return False


@torch.no_grad()
def predict_image(model, path: Path, device, threshold, min_area):
    arr, crs, transform = load_input(path)
    x = to_model_input(arr).to(device)
    prob = torch.sigmoid(model(x))[0, 0].cpu().numpy()  # H,W in [0,1]

    binary = (prob >= threshold).astype(np.uint8)

    # image-level decision using connected components (min-area filter)
    detected, n_regions, oil_pixels = make_decision_probe(
        binary, min_area, arr.shape[0], arr.shape[1]
    )
    conf = float(prob[binary > 0].mean()) if oil_pixels > 0 else float(prob.mean())
    meta = {
        "image_id": path.stem,
        "image_path": str(path),
        "model_version": getattr(model, "version", "unet_v001"),
        "oil_detected": bool(detected),
        "detection_confidence": round(conf, 4),
        "threshold": threshold,
        "probability_mask_shape": list(prob.shape),
        "input_dimensions": list(arr.shape),
        "crs": str(crs) if crs is not None else None,
        "has_georeferencing": crs is not None,
        "oil_pixel_count": int(oil_pixels),
        "connected_regions": int(n_regions),
        "warnings": [],
    }
    return prob, binary, meta


def make_decision_probe(binary, min_area, h, w):
    """Connected-component filter that determines whether oil is present."""
    try:
        import cv2
        n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        keep = []
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                keep.append(i)
        oil_pixels = int(sum(stats[i, cv2.CC_STAT_AREA] for i in keep))
        return len(keep) > 0, len(keep), oil_pixels
    except Exception:
        oil_pixels = int(binary.sum())
        return (oil_pixels >= min_area, 1 if oil_pixels >= min_area else 0, oil_pixels)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--input", default=None, help="single image path")
    ap.add_argument("--split", default=None, choices=["train", "val"],
                    help="run over a whole split directory")
    ap.add_argument("--out-dir", default=config.PREDICTION_DIR)
    ap.add_argument("--threshold", type=float, default=config.THRESHOLD)
    ap.add_argument("--min-area", type=int, default=config.MIN_CONNECTED_AREA)
    ap.add_argument("--device", default=None)
    ap.add_argument("--limit", type=int, default=8, help="max images when --split used")
    args = ap.parse_args()

    device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = load_model(args.checkpoint, device=device)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    if args.split is not None:
        files = sorted(p for p in (config.IMAGES_DIR / args.split).glob("*.png")
                       if not p.name.startswith("."))[: args.limit]
    elif args.input:
        files = [Path(args.input)]
    else:
        raise SystemExit("Provide --input or --split")

    for f in files:
        prob, binary, meta = predict_image(model, f, device, args.threshold, args.min_area)
        stem = f"{f.stem}"
        prob_path = out_dir / f"{stem}_probability.png"
        mask_path = out_dir / f"{stem}_mask.png"
        Image.fromarray((prob * 255).astype(np.uint8)).save(prob_path)
        Image.fromarray((binary * 255).astype(np.uint8)).save(mask_path)
        meta["probability_mask_path"] = str(prob_path)
        meta["binary_mask_path"] = str(mask_path)
        results.append(meta)
        print(f"{f.name}: oil_detected={meta['oil_detected']} "
              f"conf={meta['detection_confidence']} px={meta['oil_pixel_count']}")

    (out_dir / "predictions.json").write_text(json.dumps(results, indent=2))
    print("Wrote", out_dir / "predictions.json")


if __name__ == "__main__":
    main()
