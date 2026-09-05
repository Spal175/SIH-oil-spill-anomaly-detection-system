"""Integration test: the REAL oil-spill U-Net on a real sample TIFF.

Uses the trained `oil_spill_unet.pt` checkpoint and `tests/fixtures/sample_scene.tif`
(a 256x256 crop of the Sentinel-1 sample scene in ~/Downloads). Skips cleanly if
torch is not installed.
"""
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from app.config import settings
from app.services.ml_service import MLService

SAMPLE_TIFF = Path(__file__).parent / "fixtures" / "sample_scene.tif"


def test_fixture_present():
    assert SAMPLE_TIFF.exists(), f"sample TIFF fixture missing: {SAMPLE_TIFF}"


def test_checkpoint_configured():
    assert settings.model_checkpoint.exists(), (
        f"model checkpoint not found at {settings.model_checkpoint}"
    )


def test_run_oil_spill_model_returns_binary_mask():
    service = MLService()
    mask = service.run_oil_spill_model(str(SAMPLE_TIFF))

    assert isinstance(mask, np.ndarray)
    assert mask.ndim == 2
    assert mask.shape == (256, 256)
    assert mask.dtype == np.uint8
    assert set(np.unique(mask)).issubset({0, 1})


def test_analyze_returns_metadata():
    service = MLService()
    pred = service.analyze(str(SAMPLE_TIFF))

    assert pred.mask.dtype == np.uint8
    assert pred.mask.ndim == 2 and pred.mask.shape == (256, 256)
    assert pred.mask_shape == (256, 256)
    assert pred.input_shape == (256, 256)
    assert 0.0 <= pred.confidence <= 1.0
    assert pred.threshold == pytest.approx(settings.ml_threshold)
    assert pred.oil_pixels == int((pred.mask > 0).sum())
    assert pred.detected == (pred.oil_pixels > 0)
    assert pred.model_version


def test_threshold_override():
    service = MLService()
    strict = service.analyze(str(SAMPLE_TIFF), threshold=0.95)
    loose = service.analyze(str(SAMPLE_TIFF), threshold=0.05)
    assert strict.threshold == pytest.approx(0.95)
    assert loose.threshold == pytest.approx(0.05)
    assert loose.oil_pixels >= strict.oil_pixels