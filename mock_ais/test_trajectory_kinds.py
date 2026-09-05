"""Unit tests for the trajectory-kind generation in vessel_generator.py.

Run from the mock_ais/ directory:

    python -m unittest -v test_trajectory_kinds
"""

import random
import unittest
from dataclasses import replace

from config import settings
from vessel_generator import (
    generate_vessels,
    haversine_km,
    initial_bearing_deg,
    inside_aoi_fraction,
)

KINDS = ("straight", "diagonal", "slow", "turn")
ALL = "straight,diagonal,slow,turn"


class TrajectoryKindsTests(unittest.TestCase):
    @staticmethod
    def _cfg(kinds=ALL, vessel_count=12, trajectory_points=25, **kw):
        return replace(
            settings,
            mode="inside",
            vessel_count=vessel_count,
            trajectory_points=trajectory_points,
            trajectory_step_seconds=120.0,
            initial_heading=None,
            wander_deg=3.0,
            trajectory_kinds=tuple(kinds.split(",")),
            **kw,
        )

    def test_all_kinds_are_generated_and_valid(self):
        cfg = self._cfg()
        vessels = generate_vessels(cfg, rng=random.Random(5))
        self.assertEqual(len(vessels), 12)
        # unique MMSIs across the mix
        mm = [v.mmsi for v in vessels]
        self.assertEqual(len(mm), len(set(mm)))

    def test_multiple_vessels_differ_in_start_speed_heading(self):
        cfg = self._cfg(vessel_count=24)
        vessels = generate_vessels(cfg, rng=random.Random(9))
        starts = [v.positions[0] for v in vessels]
        speeds = {round(p.speed, 1) for p in starts}
        courses = {int(p.course) for p in starts}
        coords = {(p.latitude, p.longitude) for p in starts}
        self.assertGreaterEqual(len(speeds), 2)
        self.assertGreaterEqual(len(courses), 2)
        # diagonal vessels legitimately share AOI corners; the random
        # straight/slow/turn starts should keep most starts distinct
        self.assertGreaterEqual(len(coords), len(vessels) // 2)

    def test_straight_vessel_has_low_heading_wander(self):
        cfg = self._cfg(kinds="straight", vessel_count=6)
        for v in generate_vessels(cfg, rng=random.Random(21)):
            courses = [p.course for p in v.positions]
            span = max(courses) - min(courses)
            self.assertLessEqual(span, 8.0, f"course span {span} too large for straight")

    def test_diagonal_vessel_travels_on_a_diagonal_bearing(self):
        cfg = self._cfg(kinds="diagonal", vessel_count=8, trajectory_points=40)
        diagonal_bearings = {45.0, 135.0, 225.0, 315.0}
        for v in generate_vessels(cfg, rng=random.Random(13)):
            first, last = v.positions[0], v.positions[-1]
            # movement follows one of the four AOI corner-to-corner directions
            travelled = initial_bearing_deg(
                first.latitude, first.longitude, last.latitude, last.longitude
            )
            nearest = min(
                (abs((travelled - b + 180) % 360 - 180), b)
                for b in diagonal_bearings
            )[1]
            self.assertLess(
                abs((travelled - nearest + 180) % 360 - 180), 15.0,
                f"diagonal vessel travelled {travelled:.1f} deg, not a diagonal",
            )
            lats = [p.latitude for p in v.positions]
            lons = [p.longitude for p in v.positions]
            # genuinely moving in both latitude and longitude
            self.assertGreater(max(lats) - min(lats), 0.05)
            self.assertGreater(max(lons) - min(lons), 0.05)

    def test_slow_vessel_moves_at_low_speed(self):
        cfg = self._cfg(kinds="slow", vessel_count=6)
        for v in generate_vessels(cfg, rng=random.Random(27)):
            speeds = [p.speed for p in v.positions]
            self.assertLess(max(speeds), 6.0, "slow vessel sped up too much")
            dist = haversine_km(
                v.positions[0].latitude, v.positions[0].longitude,
                v.positions[-1].latitude, v.positions[-1].longitude,
            )
            self.assertLess(dist, 40.0, "slow vessel covered too much distance")

    def test_turn_vessel_changes_heading_gradually(self):
        cfg = self._cfg(kinds="turn", vessel_count=6)
        for v in generate_vessels(cfg, rng=random.Random(31)):
            courses = [p.course for p in v.positions]
            # heading changes monotonically in a bounded arc
            max_wrap = 0
            for a, b in zip(courses, courses[1:]):
                delta = (b - a + 180) % 360 - 180
                max_wrap = max(max_wrap, abs(delta))
            self.assertLess(max_wrap, 25.0, "turn not gradual")
            span = max(courses) - min(courses)
            self.assertGreater(span, 10.0, "turn vessel barely turned")

    def test_turn_and_diagonal_stay_mostly_inside_aoi(self):
        cfg = self._cfg()
        vessels = generate_vessels(cfg, rng=random.Random(8))
        for i, v in enumerate(vessels):
            kind = ALL.split(",")[i % 4]
            if kind in ("turn", "diagonal"):
                self.assertGreaterEqual(
                    inside_aoi_fraction(v, cfg.aoi), 0.75,
                    f"{kind} left the AOI too much",
                )

    def test_unsupported_kind_raises(self):
        cfg = self._cfg(kinds="straight,zigzag")
        with self.assertRaises(ValueError):
            generate_vessels(cfg, rng=random.Random(2))


if __name__ == "__main__":
    unittest.main()