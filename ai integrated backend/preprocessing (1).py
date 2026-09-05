"""Preprocessing for SAR oil-spill images.

The same pipeline is applied at train, validation and inference time; only
augmentation differs (train only).
"""
import numpy as np
import torch


def read_grayscale(path) -> np.ndarray:
    """Return a HxW uint8 grayscale array from the 3-channel PNG."""
    from PIL import Image
    return np.array(Image.open(path).convert("L")).astype(np.uint8)


def mask_to_binary(mask: np.ndarray, threshold: int = 127) -> np.ndarray:
    """Map a raw mask (0..255) to {0,1} oil foreground.

    The val split is strictly binary; the threshold only affects soft masks.
    """
    return (mask >= threshold).astype(np.uint8)


def normalize(image: np.ndarray, mode: str = "per_image") -> torch.Tensor:
    """Normalize a HxW uint8 image and add channel dim -> CHW float32."""
    img = image.astype(np.float32)
    if mode == "per_image":
        mean = img.mean()
        std = img.std() + 1e-6
        img = (img - mean) / std
    elif mode == "fixed":
        img = (img - 127.5) / 127.5  # simple fixed 0..1-> -1..1
    else:
        raise ValueError(f"Unknown normalization mode: {mode}")
    return torch.from_numpy(img[None, ...])  # 1,H,W
