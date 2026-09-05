"""Unit tests for the geographic utilities in vessel_generator.py.

Run from the mock_ais/ directory:

    python -m unittest -v test_vessel_generator
"""

import math
import random
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from config import AOIConfig, settings
from vessel_generator import (
    SHIP_TYPE_CODES,
    _load_scenario,
    _scenario_trajectory,
    destination_point,
    generate_vessels,
    haversine_km,
    inside_aoi_fraction,
    is_inside_aoi,
    random_point_in_aoi,
)

AOI = AOIConfig(north=39.64, south=37.73, east=-8.13, west=-11.45)


class HaversineTests(unittest.TestCase):
    def test_zero_distance_for_identical_points(self):
        self.assertEqual(haversine_km(38.5, -9.5, 38.5, -9.5), 0.0)

    def test_one_degree_longitude_on_equator(self):
        expected = math.radians(1.0) * 6371.0088
        actual = haversine_km(0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(actual, expected, delta=1.0)

    def test_paris_to_london_sanity(self):
        distance = haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
        self.assertAlmostEqual(distance, 343.5, delta=15.0)

    def test_symmetry(self):
        a = haversine_km(37.9, -11.0, 39.5, -8.5)
        b = haversine_km(39.5, -8.5, 37.9, -11.0)
        self.assertAlmostEqual(a, b)


class InsideAoiTests(unittest.TestCase):
    def test_bounds_are_inclusive(self):
        self.assertTrue(is_inside_aoi(AOI.south, AOI.west, AOI))
        self.assertTrue(is_inside_aoi(AOI.north, AOI.east, AOI))

    def test_center_is_inside(self):
        self.assertTrue(is_inside_aoi(38.68, -9.79, AOI))

    def test_outside_latitude(self):
        self.assertFalse(is_inside_aoi(40.0, -9.5, AOI))
        self.assertFalse(is_inside_aoi(37.0, -9.5, AOI))

    def test_outside_longitude(self):
        self.assertFalse(is_inside_aoi(38.5, -12.0, AOI))  # too far west
        self.assertFalse(is_inside_aoi(38.5, -7.0, AOI))   # too far east

    def test_negative_longitude_convention(self):
        self.assertFalse(is_inside_aoi(38.5, 8.13, AOI))
        self.assertTrue(is_inside_aoi(38.5, -8.13, AOI))


class RandomPointInAoiTests(unittest.TestCase):
    def test_all_points_fall_inside_aoi(self):
        rng = random.Random(42)
        for _ in range(1000):
            lat, lon = random_point_in_aoi(AOI, rng=rng)
            self.assertTrue(is_inside_aoi(lat, lon, AOI))

    def test_seeded_rng_is_reproducible(self):
        a1 = random_point_in_aoi(AOI, rng=random.Random(7))
        b1 = random_point_in_aoi(AOI, rng=random.Random(7))
        self.assertEqual(a1, b1)


class DestinationPointTests(unittest.TestCase):
    def test_walk_ten_km_due_north(self):
        lat, lon = destination_point(38.0, -9.0, bearing_deg=0.0, distance_km=10.0)
        self.assertAlmostEqual(lat, 38.0 + 10.0 / 111.195, places=3)
        self.assertAlmostEqual(lon, -9.0, places=6)

    def test_walk_distance_matches_haversine(self):
        start = (38.2, -9.3)
        end = destination_point(*start, bearing_deg=135.0, distance_km=50.0)
        self.assertAlmostEqual(
            haversine_km(*start, *end), 50.0, places=3
        )


class ConfigFromEnvTests(unittest.TestCase):
    def test_aoi_read_from_environment(self):
        self.assertEqual(settings.aoi.north, 39.64)
        self.assertEqual(settings.aoi.south, 37.73)
        self.assertEqual(settings.aoi.east, -8.13)
        self.assertEqual(settings.aoi.west, -11.45)

    def test_mode_read_from_environment(self):
        self.assertEqual(settings.mode, "scenario")

    def test_scenario_name_read_from_environment(self):
        self.assertEqual(settings.scenario_name, "demo_01")


class GenerateVesselsTests(unittest.TestCase):
    def _cfg(self, mode="inside", **kwargs):
        return replace(
            settings,
            mode=mode,
            vessel_count=8,
            trajectory_points=20,
            **kwargs,
        )

    def test_inside_mode_generates_trajectories_mostly_inside_aoi(self):
        vessels = generate_vessels(self._cfg(), rng=random.Random(11))
        self.assertEqual(len(vessels), 8)
        for v in vessels:
            self.assertEqual(len(v.positions), 20)
            self.assertGreaterEqual(inside_aoi_fraction(v, settings.aoi), 0.75)

    def test_trajectory_is_smooth_and_timestamps_increase(self):
        vessels = generate_vessels(self._cfg(), rng=random.Random(15))
        for v in vessels:
            prev_ts = None
            for p in v.positions:
                if prev_ts is not None:
                    self.assertGreater(p.timestamp, prev_ts)
                self.assertGreaterEqual(p.speed, 0.0)
                self.assertTrue(0.0 <= p.course <= 360.0)
                self.assertTrue(0 <= p.heading <= 359)
                prev_ts = p.timestamp

    def test_step_delta_consistent_with_speed(self):
        vessels = generate_vessels(
            self._cfg(trajectory_step_seconds=300.0), rng=random.Random(16)
        )
        dt = vessels[0].positions[1].timestamp - vessels[0].positions[0].timestamp
        self.assertEqual(dt.total_seconds(), 300.0)

    def test_mmsis_are_unique(self):
        vessels = generate_vessels(self._cfg(), rng=random.Random(17))
        mmsis = [v.mmsi for v in vessels]
        self.assertEqual(len(mmsis), len(set(mmsis)))

    def test_vessels_expose_static_and_dynamic_attributes(self):
        vessels = generate_vessels(self._cfg(), rng=random.Random(20))
        for v in vessels:
            self.assertIsInstance(v.mmsi, int)
            self.assertTrue(100000000 <= v.mmsi <= 999999999)
            self.assertIsInstance(v.ship_name, str)
            self.assertTrue(0 <= v.ship_type <= 99)
            for p in v.positions:
                self.assertIn("mmsi", type(p).model_fields)
                self.assertIn("ship_name", type(p).model_fields)
                self.assertIn("latitude", type(p).model_fields)
                self.assertIn("longitude", type(p).model_fields)
                self.assertIn("speed", type(p).model_fields)
                self.assertIn("course", type(p).model_fields)
                self.assertIn("heading", type(p).model_fields)
                self.assertIn("timestamp", type(p).model_fields)

    def test_unsupported_mode_raises_error(self):
        with self.assertRaises(ValueError):
            generate_vessels(self._cfg(mode="outer-space"), rng=random.Random(19))


class ScenarioModeTests(unittest.TestCase):
    def test_scenario_vessels_load_and_pass_validation(self):
        vessels = generate_vessels(replace(settings, mode="scenario", scenario_name="demo_01"))
        self.assertTrue(10 <= len(vessels) <= 12)
        mmsis = [v.mmsi for v in vessels]
        self.assertEqual(len(mmsis), len(set(mmsis)))
        for v in vessels:
            self.assertGreaterEqual(len(v.positions), 2)
            for p in v.positions:
                self.assertTrue(is_inside_aoi(p.latitude, p.longitude, AOI))
                self.assertTrue(0.0 <= p.course <= 360.0)
                self.assertTrue(0 <= p.heading <= 359)

    def test_demo_tanker_a_passes_through_target_point(self):
        vessels = generate_vessels(replace(settings, mode="scenario", scenario_name="demo_01"))
        tanker = next(v for v in vessels if v.ship_name == "DEMO TANKER A")
        points = [(p.latitude, p.longitude) for p in tanker.positions]
        self.assertIn((38.5, -9.5), points)

    def test_ship_type_string_mapping(self):
        self.assertEqual(SHIP_TYPE_CODES["Tanker"], 80)
        self.assertEqual(SHIP_TYPE_CODES["Cargo"], 70)
        entry = {
            "mmsi": 123456789,
            "ship_name": "TEST",
            "ship_type": "Tanker",
            "trajectory": [[38.0, -10.0], [38.1, -10.0]],
        }
        traj = _scenario_trajectory(entry, datetime(2026, 1, 1, tzinfo=timezone.utc), 120.0)
        self.assertEqual(traj.ship_type, 80)
        self.assertEqual(len(_load_scenario("demo_01")), 10)


class VesselProfileTests(unittest.TestCase):
    def test_profiles_expose_static_and_dynamic_attributes(self):
        vessels = generate_vessels(replace(settings, mode="mixed", vessel_count=20), rng=random.Random(3))
        for v in vessels:
            self.assertIsInstance(v.mmsi, int)
            self.assertTrue(100000000 <= v.mmsi <= 999999999)
            self.assertIsInstance(v.ship_name, str)
            self.assertGreater(v.ship_name, "")
            self.assertTrue(0 <= v.ship_type <= 99)
            first, last = v.positions[0], v.positions[-1]
            for p in (first, last):
                self.assertIn("mmsi", type(p).model_fields)
                self.assertIn("ship_name", type(p).model_fields)
                self.assertIn("latitude", type(p).model_fields)
                self.assertIn("longitude", type(p).model_fields)
                self.assertIn("speed", type(p).model_fields)
                self.assertIn("course", type(p).model_fields)
                self.assertIn("heading", type(p).model_fields)
                self.assertIn("timestamp", type(p).model_fields)
            # The vessel's MMSI is stable across positions.
            for p in v.positions:
                self.assertEqual(p.mmsi, v.mmsi)
                self.assertEqual(p.ship_name, v.ship_name)


if __name__ == "__main__":
    unittest.main()