"""Application settings, loaded from environment variables (optionally a `.env`).

Credentials and secrets are never hardcoded here; they must come from the
environment. Copy `.env.example` to `.env` and fill in the values.

Existing ML/GIS assets (`model (1).py`, `predict (1).py`, `preprocessing (1).py`,
`gis_extract.py`, `oil_spill_unet.pt`) remain at the project root and are
referenced via `model_checkpoint` / the service implementations.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path_env(name: str, default: str) -> Path:
    raw = os.getenv(name, default)
    path = Path(raw).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "Oil Spill Detection & Vessel Attribution API")
    app_version: str = os.getenv("APP_VERSION", "0.1.0")
    app_env: str = os.getenv("APP_ENV", "development")
    debug: bool = _bool_env("DEBUG", True)

    base_dir: Path = BASE_DIR

    model_checkpoint: Path = _path_env("MODEL_PATH", "oil_spill_unet.pt")
    ml_threshold: float = float(os.getenv("ML_THRESHOLD", "0.5"))
    ml_min_connected_area: int = int(os.getenv("MIN_CONNECTED_AREA", "8"))
    ml_device: str = os.getenv("ML_DEVICE", "auto")

    database_url: str = os.getenv("DATABASE_URL", "")

    ais_ws_url: str = os.getenv("AIS_WS_URL", "ws://localhost:8001/ais")
    ais_token: str = os.getenv("AIS_TOKEN", "")
    ais_reconnect_base: float = float(os.getenv("AIS_RECONNECT_BASE_SECONDS", "1.0"))
    ais_reconnect_max: float = float(os.getenv("AIS_RECONNECT_MAX_SECONDS", "30.0"))

    # Candidate search (spatial + temporal proximity around a detected spill)
    ais_search_radius_km: float = float(os.getenv("AIS_SEARCH_RADIUS_KM", "10"))
    ais_time_before_minutes: int = int(os.getenv("AIS_TIME_BEFORE_MINUTES", "60"))
    ais_time_after_minutes: int = int(os.getenv("AIS_TIME_AFTER_MINUTES", "0"))
    # Fraction of the search radius treated as "approached/crossed" the spill region
    ais_approach_factor: float = float(os.getenv("AIS_APPROACH_FACTOR", "0.5"))


settings = Settings()