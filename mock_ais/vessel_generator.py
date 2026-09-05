"""Vessel trajectory generation for the mock AIS server.

This module is a pure source of synthetic AIS data that behaves like an
AISStream.io feed during development. It only creates simulated vessels and
smooth trajectories inside a geographic Area of Interest (AOI).

Movement model per step:

  * heading        = previous heading (+ gradual turn for "turn" vessels)
                     + small gaussian wander (smooth turns)
  * speed (SOG)    = profile speed + small per-step variation
  * step distance  = SOG * 1.852 km/h per knot * MOCK_TRAJECTORY_STEP_SECONDS
  * COG / heading  = derived from the current step heading
  * timestamps     = strictly increasing by MOCK_TRAJECTORY_STEP_SECONDS

Supported trajectory kinds (MOCK_TRAJECTORY_KINDS):

  * straight  -> steady course with barely any wander
  * diagonal  -> corner-to-corner crossing of the AOI
  * slow      -> low speed, steady-ish course
  * turn      -> heading changes gradually over the trajectory

Supported modes:

  * mixed / inside -> vessels start at random AOI points, auto courses that
                      keep them "mostly inside" the AOI, and the trajectory
                      kinds are cycled so the fleet is mixed
  * scenario       -> loads a deterministic JSON scenario (MOCK_SCENARIO)
                      and replays its predetermined vessel trajectories

WebSocket streaming, PostgreSQL and AISStream.io are NOT implemented here.
"""

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from config import AOIConfig, Settings, settings as _settings
from models import Vessel, VesselPosition, VesselTrajectory

EARTH_RADIUS_KM = 6371.0088  # mean Earth radius (IUGG definition)
KNOTS_TO_KM_S = 1.852 / 3600.0  # 1 knot in km per second

VESSELS_PATH = Path(__file__).resolve().parent / "vessels.json"
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


def _rng(rng: Optional[random.Random]) -> random.Random:
    """Return a random source, defaulting to the global `random` module."""
    return random if rng is None else rng


# ---------------------------------------------------------------------------
# Geographic utilities
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    a = min(1.0, max(0.0, a))  # guard against float rounding
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def is_inside_aoi(lat: float, lon: float, aoi: AOIConfig) -> bool:
    """Return True if (lat, lon) lies on or inside the AOI bounding box.

    Bounds are inclusive. Northern latitudes are positive and western
    longitudes are negative, so the check is:

        aoi.south <= lat <= aoi.north
        aoi.west  <= lon <= aoi.east
    """
    return aoi.south <= lat <= aoi.north and aoi.west <= lon <= aoi.east


def random_point_in_aoi(
    aoi: AOIConfig,
    rng: Optional[random.Random] = None,
) -> Tuple[float, float]:
    """Return a uniform random (lat, lon) inside the AOI bounding box."""
    rng = _rng(rng)
    lat = rng.uniform(aoi.south, aoi.north)
    lon = rng.uniform(aoi.west, aoi.east)
    return lat, lon


def destination_point(
    lat: float,
    lon: float,
    bearing_deg: float,
    distance_km: float,
) -> Tuple[float, float]:
    """Return the (lat, lon) reached from (lat, lon) moving along a bearing.

    Uses the great-circle destination formula, correct for small and large
    distances alike.
    """
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    bearing_r = math.radians(bearing_deg)
    angular = distance_km / EARTH_RADIUS_KM

    lat2_r = math.asin(
        math.sin(lat_r) * math.cos(angular)
        + math.cos(lat_r) * math.sin(angular) * math.cos(bearing_r)
    )
    lon2_r = lon_r + math.atan2(
        math.sin(bearing_r) * math.sin(angular) * math.cos(lat_r),
        math.cos(angular) - math.sin(lat_r) * math.sin(lat2_r),
    )
    return math.degrees(lat2_r), math.degrees(lon2_r)


def initial_bearing_deg(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Great-circle initial bearing (degrees, 0-360) from point 1 to point 2."""
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlon_r = math.radians(lon2 - lon1)

    y = math.sin(dlon_r) * math.cos(lat2_r)
    x = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(
        lat2_r
    ) * math.cos(dlon_r)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


# ---------------------------------------------------------------------------
# Vessel attribute pools
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VesselProfile:
    name: str
    ship_type: int
    speed_range: Tuple[float, float]  # plausible SOG in knots for the type


# Realistic AIS ship type codes and their plausible speed ranges (knots).
SHIP_SPEED_KNOTS: dict = {
    30: (2.0, 9.0),   # fishing
    40: (12.0, 25.0),  # high-speed craft
    50: (8.0, 14.0),  # pilot
    52: (4.0, 10.0),  # tug
    60: (12.0, 22.0),  # passenger
    70: (8.0, 18.0),  # cargo
    80: (5.0, 14.0),  # tanker
    90: (3.0, 12.0),  # other
}

EXTRA_NAMES: List[Tuple[str, int]] = [
    ("ATLANTIC CHALLENGER", 70),
    ("MED STAR", 80),
    ("IBERIAN TRADER", 70),
    ("NORTH CAPE", 52),
    ("CITRA EXPRESS", 60),
    ("BALTIC PRIDE", 70),
    ("ORION GULF", 80),
    ("GLOBAL SHIPPER", 70),
    ("HORIZON NAVIGATOR", 70),
    ("PELAGIC HUNTER", 30),
    ("ZULU KING", 80),
    ("ARKLOW MOON", 70),
    ("SEVEN ISLANDS", 60),
    ("CAPE RAY", 80),
    ("GULF BRIDGE", 40),
    ("STENA VENTURE", 70),
    ("TRANS ATLAS", 90),
    ("SKAGEN FOX", 52),
]

# Representative MMSI mid identifiers (maritime identification digits).
MIDS: List[int] = [
    205, 215, 219, 227, 230, 232, 235, 244, 351, 354, 563, 636,
]


def _load_seed_vessels() -> List[Vessel]:
    """Load the static seed vessels from vessels.json."""
    with open(VESSELS_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [Vessel(**v) for v in raw]


def _build_profiles() -> List[VesselProfile]:
    profiles: List[VesselProfile] = []
    for v in _load_seed_vessels():
        lo, hi = SHIP_SPEED_KNOTS.get(v.ship_type, (3.0, 12.0))
        profiles.append(VesselProfile(v.ship_name, v.ship_type, (lo, hi)))
    for name, ship_type in EXTRA_NAMES:
        lo, hi = SHIP_SPEED_KNOTS.get(ship_type, (3.0, 12.0))
        profiles.append(VesselProfile(name, ship_type, (lo, hi)))
    return profiles


PROFILES: List[VesselProfile] = _build_profiles()


# ---------------------------------------------------------------------------
# Trajectory helpers
# ---------------------------------------------------------------------------

def _step_km(sog_knots: float, step_seconds: float) -> float:
    """Distance travelled (km) in one reporting interval at a given speed."""
    return sog_knots * KNOTS_TO_KM_S * step_seconds


def _path_length_km(cfg: Settings, sog_knots: float) -> float:
    """Total distance covered by a full trajectory at the given speed."""
    return cfg.trajectory_points * _step_km(sog_knots, cfg.trajectory_step_seconds)


def random_mmsi(rng: random.Random, used: Set[int]) -> int:
    """Return a unique 9-digit MMSI built from a real MID + random tail."""
    for _ in range(1000):
        mmsi = rng.choice(MIDS) * 1_000_000 + rng.randint(100000, 999999)
        if mmsi not in used:
            used.add(mmsi)
            return mmsi
    raise ValueError("Could not generate a unique MMSI")


def _path_inside_fraction(
    cfg: Settings,
    start: Tuple[float, float],
    bearing_deg: float,
    sog_knots: float,
) -> float:
    """Fraction of sampled great-circle path points that lie inside the AOI.

    Sampled along the great circle using destination_point, so the analysis
    is geographic (not Cartesian).
    """
    length = _path_length_km(cfg, sog_knots)
    samples = 60
    pts = [
        destination_point(*start, bearing_deg, length * i / (samples - 1))
        for i in range(samples)
    ]
    return sum(1 for p in pts if is_inside_aoi(*p, cfg.aoi)) / len(pts)


def _choose_auto_bearing(
    cfg: Settings,
    start: Tuple[float, float],
    sog_knots: float,
    rng: random.Random,
) -> float:
    """Pick a course: fixed if MOCK_INITIAL_HEADING is set, else auto.

    Auto mode rejects courses that would leave the AOI too early.
    """
    if cfg.initial_heading is not None:
        return cfg.initial_heading % 360.0

    best = (0.0, 0.0)
    for _ in range(30):
        bearing = rng.uniform(0.0, 360.0)
        inside_frac = _path_inside_fraction(cfg, start, bearing, sog_knots)

        if inside_frac >= 0.75:
            return bearing
        if inside_frac > best[0]:
            best = (inside_frac, bearing)
    return best[1]


def _make_trajectory(
    cfg: Settings,
    profile: VesselProfile,
    start: Tuple[float, float],
    bearing_deg: float,
    sog_knots: float,
    rng: random.Random,
    used_mmsi: Set[int],
    wander_deg: Optional[float] = None,
    turn_rate_deg: Optional[float] = None,
) -> VesselTrajectory:
    """Walk a smooth trajectory of cfg.trajectory_points positions.

    ``wander_deg`` overrides the per-step heading noise for this vessel (a
    straight transit uses a small value, a turn is barely affected). When
    ``turn_rate_deg`` is given the heading is shifted by that many degrees
    every step before the wander is applied, producing a gradual turn.
    """
    mmsi = random_mmsi(rng, used_mmsi)
    dt = timedelta(seconds=cfg.trajectory_step_seconds)
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    wander = cfg.wander_deg if wander_deg is None else wander_deg

    lat, lon = start
    heading = bearing_deg % 360.0
    positions: List[VesselPosition] = []

    for _ in range(cfg.trajectory_points):
        sog = max(0.2, sog_knots + rng.uniform(-0.4, 0.4))
        cog = round(heading % 360.0, 1)
        positions.append(
            VesselPosition(
                mmsi=mmsi,
                ship_name=profile.name,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                speed=round(sog, 1),
                course=cog,
                heading=int(cog) % 360,
                timestamp=t,
            )
        )
        lat, lon = destination_point(lat, lon, heading, _step_km(sog, cfg.trajectory_step_seconds))
        if turn_rate_deg is not None:
            heading = (heading + turn_rate_deg) % 360.0
        heading = (heading + rng.gauss(0.0, wander)) % 360.0
        t += dt

    return VesselTrajectory(mmsi=mmsi, ship_name=profile.name, ship_type=profile.ship_type, positions=positions)


# ---------------------------------------------------------------------------
# Kind builders
# ---------------------------------------------------------------------------

def _build_straight_vessel(cfg: Settings, rng: random.Random, used_mmsi: Set[int]) -> VesselTrajectory:
    """A steady crossing of the AOI with very little heading wander."""
    profile = rng.choice(PROFILES)
    sog = rng.uniform(*profile.speed_range)
    start = random_point_in_aoi(cfg.aoi, rng=rng)
    bearing = _choose_auto_bearing(cfg, start, sog, rng)
    return _make_trajectory(cfg, profile, start, bearing, sog, rng, used_mmsi, wander_deg=0.4)


def _diagonal_options(cfg: Settings) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """Corner-to-corner (start, end) pairs of the AOI box."""
    a = cfg.aoi
    corners = [
        ((a.south, a.west), (a.north, a.east)),  # NE
        ((a.south, a.east), (a.north, a.west)),  # NW
        ((a.north, a.west), (a.south, a.east)),  # SE
        ((a.north, a.east), (a.south, a.west)),  # SW
    ]
    return corners


def _build_diagonal_vessel(cfg: Settings, rng: random.Random, used_mmsi: Set[int]) -> VesselTrajectory:
    """A corner-to-corner crossing of the AOI on a diagonal course."""
    profile = rng.choice(PROFILES)
    sog = rng.uniform(*profile.speed_range)
    start, end = rng.choice(_diagonal_options(cfg))
    bearing = initial_bearing_deg(*start, *end)
    return _make_trajectory(cfg, profile, start, bearing, sog, rng, used_mmsi, wander_deg=0.4)


SLOW_SHIP_TYPES = (30, 52, 90)  # fishing / tug / other


def _build_slow_vessel(cfg: Settings, rng: random.Random, used_mmsi: Set[int]) -> VesselTrajectory:
    """A slow-moving vessel: low speed on an easy, fairly straight course."""
    slow_profiles = [p for p in PROFILES if p.ship_type in SLOW_SHIP_TYPES]
    profile = rng.choice(slow_profiles) if slow_profiles else rng.choice(PROFILES)
    sog = rng.uniform(1.5, 4.5)
    start = random_point_in_aoi(cfg.aoi, rng=rng)
    bearing = _choose_auto_bearing(cfg, start, sog, rng)
    return _make_trajectory(cfg, profile, start, bearing, sog, rng, used_mmsi, wander_deg=1.0)


def _build_turn_vessel(cfg: Settings, rng: random.Random, used_mmsi: Set[int]) -> VesselTrajectory:
    """A vessel that gradually changes heading over its trajectory.

    The course starts by pointing at the AOI centre and bends by a bounded
    total angle across the trajectory, so the arc stays (mostly) inside the
    area. Several heading offsets are tried and the most "inside" result is
    kept.
    """
    profile = rng.choice(PROFILES)
    sog = rng.uniform(*profile.speed_range)
    start = random_point_in_aoi(cfg.aoi, rng=rng)

    centre = (
        (cfg.aoi.south + cfg.aoi.north) / 2.0,
        (cfg.aoi.west + cfg.aoi.east) / 2.0,
    )
    base_bearing = initial_bearing_deg(*start, *centre)
    total_turn = rng.uniform(40.0, 90.0) * rng.choice((-1.0, 1.0))
    turn_rate = total_turn / cfg.trajectory_points

    best: Optional[VesselTrajectory] = None
    best_frac = 0.0
    for _ in range(25):
        offset = rng.uniform(0.0, 40.0) * rng.choice((-1.0, 1.0))
        heading = (base_bearing + offset) % 360.0
        trajectory = _make_trajectory(
            cfg, profile, start, heading, sog, rng, used_mmsi,
            wander_deg=1.0, turn_rate_deg=turn_rate,
        )
        frac = inside_aoi_fraction(trajectory, cfg.aoi)
        if frac >= 0.75:
            return trajectory
        if frac > best_frac:
            best, best_frac = trajectory, frac
    if best is None:
        raise ValueError("failed to generate a turn trajectory inside the AOI")
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_KIND_BUILDERS = {
    "straight": _build_straight_vessel,
    "diagonal": _build_diagonal_vessel,
    "slow": _build_slow_vessel,
    "turn": _build_turn_vessel,
}


# ---------------------------------------------------------------------------
# Scenario mode
# ---------------------------------------------------------------------------

# Maps the human-readable ship types used in scenario files onto the AIS
# ship type codes used internally. Unknown labels fall back to "Other".
SHIP_TYPE_CODES: Dict[str, int] = {
    "Tanker": 80,
    "Cargo": 70,
    "Fishing": 30,
    "Tug": 52,
    "Passenger": 60,
    "Pleasure": 37,
    "Sailing": 36,
    "Pilot": 50,
    "HighSpeedCraft": 40,
    "Other": 90,
}


def _scenario_path(scenario_name: str) -> Path:
    return SCENARIOS_DIR / f"{scenario_name}.json"


def _load_scenario(scenario_name: str) -> List[Dict]:
    """Load the vessels of a JSON scenario from the scenarios/ directory."""
    return list(_load_scenario_data(scenario_name)["vessels"])


def _load_scenario_data(scenario_name: str) -> Dict:
    """Load a whole scenario JSON document from the scenarios/ directory."""
    path = _scenario_path(scenario_name)
    if not path.exists():
        raise ValueError(f"scenario '{scenario_name}' not found at {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_scenario_start_time(data: Dict) -> datetime:
    """Return the fixed scenario start time, or 'now' when the scenario does
    not declare one.

    A deterministic scenario sets ``start_time`` (ISO-8601, UTC) at the top
    level so every vessel's position timestamps are reproducible and can be
    aligned with an oil-spill detection time; otherwise timestamps start at
    the current UTC time (rounded to the minute), as before.
    """
    raw = data.get("start_time")
    if raw:
        try:
            start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            return start
        except (TypeError, ValueError):
            raise ValueError(
                f"invalid scenario start_time '{raw}'; expected ISO-8601 UTC"
            )
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def _scenario_trajectory(
    entry: Dict,
    start_time: datetime,
    step_seconds: float,
) -> VesselTrajectory:
    """Build a VesselTrajectory from one scenario vessel entry.

    The scenario stores positions and a per-vessel ``speed_kn``; the time
    between consecutive points is derived so that the speed equals the
    configured speed and the derived AIS messages stay consistent.
    If ``speed_kn`` is absent, ``step_seconds`` is used as a constant step.
    """
    mmsi = int(entry["mmsi"])
    ship_name = str(entry["ship_name"])
    ship_type = SHIP_TYPE_CODES.get(str(entry.get("ship_type", "")), 90)
    route = [(float(lat), float(lon)) for lat, lon in entry["trajectory"]]
    speed_kn = entry.get("speed_kn")

    positions: List[VesselPosition] = []
    t = start_time
    for i, (lat, lon) in enumerate(route):
        if i < len(route) - 1:
            next_lat, next_lon = route[i + 1]
            course = initial_bearing_deg(lat, lon, next_lat, next_lon)
            dist_km = haversine_km(lat, lon, next_lat, next_lon)
        if speed_kn is not None:
            sog = float(speed_kn)
            dt_seconds = (dist_km / sog) * 3600.0 if i < len(route) - 1 else step_seconds
        else:
            sog = dist_km / (step_seconds / 3600.0) if i < len(route) - 1 else 0.0
            dt_seconds = step_seconds
        positions.append(
            VesselPosition(
                mmsi=mmsi,
                ship_name=ship_name,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                speed=round(sog, 1),
                course=round(course % 360.0, 1),
                heading=int(course) % 360,
                timestamp=t,
            )
        )
        t += timedelta(seconds=dt_seconds)

    return VesselTrajectory(
        mmsi=mmsi,
        ship_name=ship_name,
        ship_type=ship_type,
        positions=positions,
    )


def _build_scenario_vessels(cfg: Settings) -> List[VesselTrajectory]:
    """Load all vessels and trajectories of the configured scenario."""
    data = _load_scenario_data(cfg.scenario_name)
    start_time = _parse_scenario_start_time(data)
    return [
        _scenario_trajectory(entry, start_time, cfg.trajectory_step_seconds)
        for entry in data["vessels"]
    ]


def generate_vessels(
    settings: Optional[Settings] = None,
    rng: Optional[random.Random] = None,
) -> List[VesselTrajectory]:
    """Generate vessels, each with a smooth trajectory of positions.

    * ``scenario`` mode loads a deterministic JSON scenario
      (``MOCK_SCENARIO``) from the ``scenarios/`` directory and replays its
      predetermined vessel trajectories.
    * ``mixed`` / ``inside`` (aliases) modes start vessels at random points
      inside the configured AOI on courses that keep them "mostly inside"
      the area, alternating through the configured trajectory kinds
      (``MOCK_TRAJECTORY_KINDS``) so several independent vessels with
      different starts, headings, speeds and path shapes are produced.
    """
    cfg = settings or _settings
    rng = _rng(rng)
    mode = cfg.mode
    count = max(1, cfg.vessel_count)

    vessels: List[VesselTrajectory] = []

    if mode == "scenario":
        vessels = _build_scenario_vessels(cfg)
    elif mode == "inside" or mode == "mixed":
        kinds = cfg.trajectory_kinds
        unsupported = [k for k in kinds if k not in _KIND_BUILDERS]
        if unsupported:
            raise ValueError(
                f"unsupported trajectory kind(s) {unsupported} (expected any of: {', '.join(_KIND_BUILDERS)})"
            )
        used_mmsi: Set[int] = set()
        for i in range(count):
            kind = kinds[i % len(kinds)]
            vessels.append(_KIND_BUILDERS[kind](cfg, rng, used_mmsi))
    else:
        raise ValueError(f"unsupported mode '{mode}' (expected: inside, mixed or scenario)")

    validate_vessels(vessels)
    return vessels


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_trajectory(trajectory: VesselTrajectory) -> None:
    """Validate a generated trajectory; raise ValueError on any problem."""
    errors = []
    if not (100000000 <= trajectory.mmsi <= 999999999):
        errors.append(f"MMSI {trajectory.mmsi} is not 9 digits")
    if not (0 <= trajectory.ship_type <= 99):
        errors.append(f"ship_type {trajectory.ship_type} out of AIS range")
    if not trajectory.positions:
        errors.append("trajectory has no positions")

    prev_ts = None
    prev_pt = None
    for p in trajectory.positions:
        if not (-90.0 <= p.latitude <= 90.0):
            errors.append(f"latitude {p.latitude} out of range")
        if not (-180.0 <= p.longitude <= 180.0):
            errors.append(f"longitude {p.longitude} out of range")
        if not (0.0 <= p.speed <= 90.0):
            errors.append(f"speed {p.speed} out of range")
        if not (0.0 <= p.course <= 360.0):
            errors.append(f"course {p.course} out of range")
        if not (0 <= p.heading <= 359):
            errors.append(f"heading {p.heading} out of range")
        if prev_ts is not None and p.timestamp <= prev_ts:
            errors.append("timestamps are not strictly increasing")
        if prev_pt is not None:
            step = haversine_km(prev_pt[0], prev_pt[1], p.latitude, p.longitude)
            if step > 10.0:
                errors.append(f"unrealistic jump of {step:.1f} km between reports")
        prev_ts, prev_pt = p.timestamp, (p.latitude, p.longitude)

    if errors:
        raise ValueError(
            f"invalid trajectory for {trajectory.ship_name} ({trajectory.mmsi}): {'; '.join(errors)}"
        )


def validate_vessels(vessels: List[VesselTrajectory]) -> None:
    """Validate every generated trajectory and MMSI uniqueness."""
    mmsis = [v.mmsi for v in vessels]
    if len(mmsis) != len(set(mmsis)):
        raise ValueError("generated MMSIs are not unique")
    for trajectory in vessels:
        validate_trajectory(trajectory)


def inside_aoi_fraction(trajectory: VesselTrajectory, aoi: AOIConfig) -> float:
    """Fraction of trajectory positions that lie inside the AOI."""
    if not trajectory.positions:
        return 0.0
    return sum(1 for p in trajectory.positions if is_inside_aoi(p.latitude, p.longitude, aoi)) / len(trajectory.positions)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def print_trajectories(
    vessels: List[VesselTrajectory],
    kinds: Optional[List[str]] = None,
) -> None:
    """Print a readable per-vessel summary for testing."""
    header = (
        f"{'MMSI':<10} {'NAME':<20} {'TYPE':<5} {'KIND':<9} {'PTS':>4} "
        f"{'START (lat, lon)':>26} {'END (lat, lon)':>26} {'%INSIDE':>8}"
    )
    print(header)
    print("-" * len(header))
    for i, v in enumerate(vessels):
        kind = kinds[i] if kinds is not None else ""
        first, last = v.positions[0], v.positions[-1]
        frac = inside_aoi_fraction(v, _settings.aoi)
        print(
            f"{v.mmsi:<10} {v.ship_name:<20} {v.ship_type:<5} {kind:<9} {len(v.positions):>4} "
            f"({first.latitude:.4f}, {first.longitude:.4f}) "
            f"({last.latitude:.4f}, {last.longitude:.4f}) "
            f"{frac * 100:>6.1f}%"
        )


def _dump_trajectory(trajectory: VesselTrajectory, kind: str = "") -> None:
    """Print every position of a single trajectory."""
    label = f"{kind} " if kind else ""
    print(f"\n[{label}] {trajectory.ship_name} ({trajectory.mmsi}) ship_type={trajectory.ship_type}")
    for p in trajectory.positions:
        print(
            f"  {p.timestamp:%H:%M:%S}Z  lat={p.latitude:.5f}  lon={p.longitude:.5f}  "
            f"speed={p.speed:>4.1f}  course={p.course:>6.1f}  hdg={p.heading:>3}"
        )


if __name__ == "__main__":
    kinds = list(_settings.trajectory_kinds)
    print(f"mode={_settings.mode}  count={_settings.vessel_count}  kinds={kinds}\n")
    vessels = generate_vessels()
    vessel_kinds = [kinds[i % len(kinds)] for i in range(len(vessels))]
    print_trajectories(vessels, kinds=vessel_kinds)

    print("\nDetailed trajectories (one per kind):")
    shown = set()
    for vessel, kind in zip(vessels, vessel_kinds):
        if kind not in shown:
            _dump_trajectory(vessel, kind=kind)
            shown.add(kind)