"""U-Net semantic segmentation model for oil-spill detection."""
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F


class DoubleConv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.block(x)


class Down(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.mp = nn.MaxPool2d(2)
        self.conv = DoubleConv(in_ch, out_ch)

    def forward(self, x):
        return self.conv(self.mp(x))


class Up(nn.Module):
    def __init__(self, in_ch, skip_ch, out_ch):
        # takes the upsampled feature map (in_ch) concat with skip (skip_ch)
        super().__init__()
        self.up = nn.ConvTranspose2d(in_ch, in_ch // 2, 2, stride=2)
        self.conv = DoubleConv(in_ch // 2 + skip_ch, out_ch)

    def forward(self, x, skip):
        x = self.up(x)
        diff_y = skip.size(2) - x.size(2)
        diff_x = skip.size(3) - x.size(3)
        x = F.pad(x, [diff_x // 2, diff_x - diff_x // 2,
                      diff_y // 2, diff_y - diff_y // 2])
        x = torch.cat([skip, x], dim=1)
        return self.conv(x)


class UNet(nn.Module):
    def __init__(self, in_ch: int, base: int = 32, depth: int = 4):
        super().__init__()
        self.in_ch = in_ch
        self.base = base
        self.depth = depth
        self.in_conv = DoubleConv(in_ch, base)

        # Encoder: D downs produce D+1 skips at channel base*2^i
        ch = base
        self.downs = nn.ModuleList()
        skip_chs = [base]
        for _ in range(depth):
            self.downs.append(Down(ch, ch * 2))
            ch = ch * 2
            skip_chs.append(ch)

        # Bottleneck
        self.bottleneck = DoubleConv(ch, ch * 2)
        ch = ch * 2

        # Decoder: depth ups; up i merges with skips[depth-1-i]
        self.ups = nn.ModuleList()
        for i in range(depth):
            out_ch = base * (2 ** (depth - 1 - i))
            in_ch = ch
            skip_ch = skip_chs[depth - 1 - i]
            self.ups.append(Up(in_ch, skip_ch, out_ch))
            ch = out_ch

        self.out_conv = nn.Conv2d(base, 1, 1)

    def forward(self, x):
        skips = [self.in_conv(x)]
        for d in self.downs:
            skips.append(d(skips[-1]))
        x = self.bottleneck(skips[-1])
        for i, u in enumerate(self.ups):
            x = u(x, skips[self.depth - 1 - i])
        return self.out_conv(x)


def build_model(in_ch: int = None, base: int = None, depth: int = None):
    from config import config
    return UNet(
        in_ch=in_ch or config.MODEL_INPUT_CHANNELS,
        base=base or config.FIRST_FILTERS,
        depth=depth or config.DEPTH,
    )


def load_model(path, device=None):
    """Load a trained model from a .pt checkpoint or a .pkl package.

    Device handling is deferred to the caller for .pt (weights + config);
    for .pkl (a pickled UNet) we just move to the requested device.
    """
    import pickle

    path = str(path)
    if path.endswith(".pkl"):
        with open(path, "rb") as f:
            pkg = pickle.load(f)
        model = pkg["model"]
        if device is not None:
            model.to(device)
        model.version = pkg.get("version", Path(path).stem)
        return model
    # .pt checkpoint: {"model_state", "config", ...}
    from config import config as cfg
    state = torch.load(path, map_location="cpu")
    sd = state["model_state"]
    c = state.get("config", {})
    model = UNet(
        in_ch=c.get("MODEL_INPUT_CHANNELS", cfg.MODEL_INPUT_CHANNELS),
        base=c.get("FIRST_FILTERS", cfg.FIRST_FILTERS),
        depth=c.get("DEPTH", cfg.DEPTH),
    )
    model.load_state_dict(sd)
    model.eval()
    model.version = Path(path).stem
    if device is not None:
        model.to(device)
    return model

