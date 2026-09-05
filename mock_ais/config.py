import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return default if raw is None or raw == "" else raw.strip()


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw is not None and raw != "" else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None and raw != "" else default
    except ValueError:
        return default


def _env_optional_float(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class AOIConfig:
    """Area of interest (bounding box) in decimal degrees.

    North latitudes are positive, west longitudes are negative
    (e.g. 8.13 W is stored as -8.13).
    """

    north: float
    south: float
    east: float
    west: float

    def __post_init__(self) -> None:
        if self.south > self.north:
            raise ValueError(
                f"Invalid AOI: south ({self.south}) > north ({self.north})"
            )
        if self.east < self.west:
            raise ValueError(
                f"Invalid AOI: east ({self.east}) < west ({self.west})"
            )


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    mode: str
    scenario_name: str
    aoi: AOIConfig
    vessel_count: int
    update_interval: float
    trajectory_points: int
    trajectory_step_seconds: float
    initial_heading: Optional[float]
    wander_deg: float
    trajectory_kinds: Tuple[str, ...]


def load_settings() -> Settings:
    mode = _env_str("MOCK_MODE", "scenario").lower()
    if mode not in {"inside", "mixed", "scenario"}:
        raise ValueError(
            f"Unsupported MOCK_MODE '{mode}'. "
            "Expected one of: inside, mixed, scenario."
        )

    kinds = _parse_trajectory_kinds(_env_str("MOCK_TRAJECTORY_KINDS", "straight,diagonal,slow,turn"))

    return Settings(
        host=_env_str("MOCK_HOST", "0.0.0.0"),
        port=_env_int("MOCK_PORT", 8001),
        mode=mode,
        scenario_name=_env_str("MOCK_SCENARIO", "demo_01"),
        aoi=AOIConfig(
            north=_env_float("MOCK_AOI_NORTH", 39.64),
            south=_env_float("MOCK_AOI_SOUTH", 37.73),
            east=_env_float("MOCK_AOI_EAST", -8.13),
            west=_env_float("MOCK_AOI_WEST", -11.45),
        ),
        vessel_count=_env_int("MOCK_VESSEL_COUNT", 10),
        update_interval=_env_float("MOCK_UPDATE_INTERVAL", 2.0),
        trajectory_points=_env_int("MOCK_TRAJECTORY_POINTS", 25),
        trajectory_step_seconds=_env_float("MOCK_TRAJECTORY_STEP_SECONDS", 120.0),
        initial_heading=_env_optional_float("MOCK_INITIAL_HEADING"),
        wander_deg=_env_float("MOCK_COURSE_WANDER_DEG", 3.0),
        trajectory_kinds=kinds,
    )


def _parse_trajectory_kinds(raw: str) -> Tuple[str, ...]:
    """Parse and validate the comma-separated trajectory kind list."""
    supported = {"straight", "diagonal", "slow", "turn"}
    kinds = tuple(k.strip().lower() for k in raw.split(",") if k.strip())
    unknown = [k for k in kinds if k not in supported]
    if unknown:
        raise ValueError(
            f"Unsupported trajectory kind(s) {unknown}. "
            f"Expected any of: {', '.join(sorted(supported))}."
        )
    if not kinds:
        raise ValueError("MOCK_TRAJECTORY_KINDS must not be empty.")
    return kinds


settings = load_settings()