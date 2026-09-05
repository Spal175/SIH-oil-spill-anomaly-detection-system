"""ML inference service for oil-spill detection.

Loads and runs the EXISTING trained model untouched — the U-Net architecture in
the project-root ``model (1).py`` and the trained weights in
``oil_spill_unet.pt``. Neither file is modified, retrained or replaced; this
service only adapts their actual interface to a clean API.

Pipeline (mirrors the existing ``predict (1).py`` behaviour):

    TIFF/PNG --> (H,W) grayscale --> per-image normalization (existing
    ``preprocessing (1).py``) --> UNet --> probability (H,W)
    --> threshold --> binary {0,1} mask

Output contract (what consumers receive)::

    mask : np.ndarray, shape (H, W), dtype uint8, values {0 = non-oil, 1 = oil}

No geographic processing happens here — mapping the mask to lat/lon belongs to
the GIS service.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = settings.base_dir
MODEL_MODULE = PROJECT_ROOT / "model (1).py"
PREPROCESSING_MODULE = PROJECT_ROOT / "preprocessing (1).py"


@dataclass
class OilSpillPrediction:
    """Normalized inference result.

    ``mask`` is the only downstream contract: 2D {0,1} matrix
    (0 = non-oil, 1 = oil), same pixel layout as the input image.
    """

    mask: np.ndarray
    mask_shape: tuple
    input_shape: tuple
    threshold: float
    confidence: Optional[float]
    oil_pixels: int
    detected: bool
    model_version: str
    probability: Optional[np.ndarray] = None


def _load_file_module(path: Path, name: str):
    """Import a .py file by absolute path (the existing ML files are not
    importable via package paths because of their names/layout)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MLService:
    """Interface to the existing oil-spill U-Net."""

    def __init__(
        self,
        checkpoint: Optional[Path] = None,
        device: Optional[str] = None,
        threshold: Optional[float] = None,
    ):
        self.checkpoint = Path(checkpoint) if checkpoint else settings.model_checkpoint
        self.device = device if device else settings.ml_device
        self.threshold = float(
            threshold if threshold is not None else settings.ml_threshold
        )
        self._model = None
        self._normalize = None
        self._torch_device = None
        self._model_version = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _resolve_device(self):
        if self.device and self.device.lower() != "auto":
            return self.device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def load_model(self) -> None:
        """Load the existing trained model once (lazy and cached)."""
        if self._model is not None:
            return

        model_mod = _load_file_module(MODEL_MODULE, "oil_spill_model")
        preprocessing_mod = _load_file_module(
            PREPROCESSING_MODULE, "oil_spill_preprocessing"
        )
        self._normalize = preprocessing_mod.normalize

        import torch

        torch_device = torch.device(self._resolve_device())

        # Replicates the .pt branch of `model (1).py:load_model`, using the
        # config embedded in the checkpoint; `weights_only=False` because the
        # checkpoint bundles a config dict alongside the state dict.
        state = torch.load(str(self.checkpoint), map_location="cpu", weights_only=False)
        state_dict = state["model_state"]
        cfg = state.get("config") or {}
        in_ch = int(cfg.get("MODEL_INPUT_CHANNELS", 1))
        base = int(cfg.get("FIRST_FILTERS", 32))
        depth = int(cfg.get("DEPTH", 4))

        model = model_mod.UNet(in_ch=in_ch, base=base, depth=depth)
        model.load_state_dict(state_dict)
        model.eval()
        model.to(torch_device)
        model.version = self.checkpoint.stem

        self._model = model
        self._torch_device = torch_device
        self._model_version = self.checkpoint.stem
        logger.info(
            "loaded model %s (in_ch=%d base=%d depth=%d) on %s",
            self.checkpoint.name,
            in_ch,
            base,
            depth,
            torch_device.type,
        )

    def _read_image(self, path: Path) -> np.ndarray:
        """Read a TIFF/PNG into the same array shape the existing pipeline uses.

        Mirrors ``predict (1).py:load_input``: GeoTIFF keeps band 1 (or HxWxC),
        anything else is read as grayscale via PIL.
        """
        path = Path(path)
        try:
            import rasterio

            HAS_RASTERIO = True
        except Exception:
            HAS_RASTERIO = False

        if HAS_RASTERIO and path.suffix.lower() in (".tif", ".tiff"):
            try:
                with rasterio.open(path) as src:
                    arr = src.read()
                if arr.shape[0] == 1:
                    arr = arr[0]
                else:
                    arr = np.moveaxis(arr, 0, -1)
                return np.asarray(arr, dtype=np.float32)
            except Exception:
                pass

        from PIL import Image

        return np.array(Image.open(path).convert("L")).astype(np.float32)

    def _to_model_input(self, arr: np.ndarray):
        """Match ``predict (1).py:to_model_input`` -> (1,1,H,W) on device."""
        import torch

        if arr.ndim == 3:
            arr = arr[..., :1] if arr.shape[2] > 1 else arr[..., 0]
        if arr.max() > 1.0 + 1e-6:
            arr = arr / 255.0
        normalized = self._normalize(np.ascontiguousarray(arr), "per_image")
        return normalized[None, ...].to(self._torch_device)

    def predict(
        self, image_path: str, threshold: Optional[float] = None
    ) -> OilSpillPrediction:
        """Run the existing model on one image and normalize the output."""
        import torch

        self.load_model()
        arr = self._read_image(Path(image_path))
        x = self._to_model_input(arr)
        thr = float(threshold if threshold is not None else self.threshold)

        with torch.no_grad():
            prob = torch.sigmoid(self._model(x))[0, 0].cpu().numpy()

        binary = (prob >= thr).astype(np.uint8)
        oil_pixels = int((binary > 0).sum())
        confidence = (
            float(prob[binary > 0].mean()) if oil_pixels > 0 else float(prob.mean())
        )

        return OilSpillPrediction(
            mask=binary,
            mask_shape=tuple(binary.shape),
            input_shape=tuple(arr.shape),
            threshold=thr,
            confidence=confidence,
            oil_pixels=oil_pixels,
            detected=oil_pixels > 0,
            model_version=self._model_version,
            probability=prob,
        )

    def analyze(
        self, image_path: str, threshold: Optional[float] = None
    ) -> OilSpillPrediction:
        """Run inference and return the normalized mask plus metadata."""
        return self.predict(image_path, threshold)

    def run_oil_spill_model(self, tiff_path: str) -> np.ndarray:
        """Primary interface: TIFF/image -> {0,1} HxW mask (0=non-oil, 1=oil)."""
        return self.predict(tiff_path).mask


ml_service = MLService()