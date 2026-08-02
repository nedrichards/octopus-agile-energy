import unittest

from src.region_location import suggest_region_code


def feature(name, coordinates):
    return {
        "type": "Feature",
        "properties": {"longname": name},
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
    }


class RegionLocationTests(unittest.TestCase):
    def test_suggests_the_unique_region_containing_a_point(self):
        features = [feature("UKPN (East)", [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])]

        self.assertEqual(suggest_region_code(1, 1, features), "_A")

    def test_rejects_points_outside_or_on_ambiguous_boundaries(self):
        features = [
            feature("UKPN (East)", [[0, 0], [1, 0], [1, 2], [0, 2], [0, 0]]),
            feature("WPD (East Midlands)", [[1, 0], [2, 0], [2, 2], [1, 2], [1, 0]]),
        ]

        self.assertIsNone(suggest_region_code(3, 3, features))
        self.assertIsNone(suggest_region_code(1, 1, features))

    def test_rejects_invalid_coordinates(self):
        self.assertIsNone(suggest_region_code(91, 0, []))
        self.assertIsNone(suggest_region_code(float("nan"), 0, []))
