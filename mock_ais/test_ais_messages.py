"""Unit tests for the AIS position report conversion in ais_messages.py.

Run from the mock_ais/ directory:

    python -m unittest -v test_ais_messages
"""

import json
import random
import unittest

from ais_messages import vessel_position_to_ais_message
from vessel_generator import generate_vessels


class AisMessageConversionTests(unittest.TestCase):
    def test_position_converts_to_valid_position_report(self):
        vessels = generate_vessels(
            None,
            rng=random.Random(7),
        )
        for vessel in vessels:
            position = vessel.positions[0]
            message = vessel_position_to_ais_message(vessel, position)

            self.assertEqual(message.MessageType, "PositionReport")

            self.assertEqual(message.MetaData.MMSI, vessel.mmsi)
            self.assertEqual(message.MetaData.ShipName, vessel.ship_name)
            self.assertEqual(message.MetaData.Latitude, position.latitude)
            self.assertEqual(message.MetaData.Longitude, position.longitude)

            report = message.Message.PositionReport
            self.assertEqual(report.UserID, vessel.mmsi)
            self.assertEqual(report.Latitude, position.latitude)
            self.assertEqual(report.Longitude, position.longitude)
            self.assertEqual(report.Sog, position.speed)
            self.assertEqual(report.Cog, position.course)
            self.assertEqual(report.TrueHeading, position.heading)
            self.assertEqual(report.Timestamp, int(position.timestamp.timestamp()))

            dumped = message.model_dump_json()
            self.assertIn('"MessageType":"PositionReport"', dumped)
            # The wire message contains exactly the AIS/vessel envelope keys.
            self.assertEqual(
                set(json.loads(dumped).keys()),
                {"MessageType", "MetaData", "Message"},
            )
            self.assertEqual(
                set(json.loads(dumped)["MetaData"].keys()),
                {"MMSI", "ShipName", "Latitude", "Longitude"},
            )
            self.assertEqual(
                set(json.loads(dumped)["Message"]["PositionReport"].keys()),
                {
                    "UserID", "Latitude", "Longitude",
                    "Sog", "Cog", "TrueHeading", "Timestamp",
                },
            )


if __name__ == "__main__":
    unittest.main()