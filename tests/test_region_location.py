from pathlib import Path

from src.region_location import (
    DNO_NAME_TO_REGION_CODE,
    OUTSIDE_UK_MESSAGE,
    REGION_CODE_TO_NAME,
    LocationPortal,
    bundled_region_codes,
    feature_region_code,
    find_region_for_coordinates,
    is_clearly_outside_uk,
    is_near_region_boundary,
    load_region_features,
    point_in_geometry,
)

DATA_PATH = Path(__file__).parents[1] / "data" / "gb-electricity-regions.geojson"


def feature(name, geometry):
    return {
        "type": "Feature",
        "properties": {"longname": name},
        "geometry": geometry,
    }


def polygon(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}


def test_bundled_boundaries_cover_every_expected_region_once():
    features = load_region_features(DATA_PATH)
    codes = [feature_region_code(item) for item in features]

    assert len(features) == 14
    assert all(code in REGION_CODE_TO_NAME for code in codes)
    assert len(codes) == len(set(codes))
    assert bundled_region_codes(features) == set(REGION_CODE_TO_NAME)
    assert set(DNO_NAME_TO_REGION_CODE.values()) == set(REGION_CODE_TO_NAME)


def test_bundled_boundaries_match_representative_great_britain_locations():
    features = load_region_features(DATA_PATH)

    assert find_region_for_coordinates(51.5072, -0.1276, features) == "_C"  # London
    assert find_region_for_coordinates(54.9783, -1.6178, features) == "_F"  # Newcastle
    assert find_region_for_coordinates(51.4816, -3.1791, features) == "_K"  # Cardiff
    assert find_region_for_coordinates(55.9533, -3.1883, features) == "_N"  # Edinburgh
    assert find_region_for_coordinates(54.5973, -5.9301, features) is None  # Belfast


def test_polygon_hole_and_boundary_are_not_matched():
    geometry = polygon(
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
    )

    assert point_in_geometry(0.5, 0.5, geometry)
    assert not point_in_geometry(2, 2, geometry)
    assert not point_in_geometry(1, 2, geometry)


def test_multipolygon_is_matched_and_unmapped_features_are_ignored():
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            [[[3, 3], [4, 3], [4, 4], [3, 4], [3, 3]]],
        ],
    }
    features = [feature("UKPN (East)", geometry), feature("Unknown DNO", geometry)]

    assert find_region_for_coordinates(3.5, 3.5, features) == "_A"
    assert find_region_for_coordinates(2, 2, features) is None


def test_invalid_coordinates_and_ambiguous_accuracy_do_not_claim_a_region():
    features = [feature("UKPN (East)", polygon([[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]))]

    assert find_region_for_coordinates(91, 0, features) is None
    assert find_region_for_coordinates(float("nan"), 0, features) is None
    assert is_near_region_boundary(1, 0.00001, 10, features)
    assert not is_near_region_boundary(1, 1, 10, features)


def test_clearly_overseas_locations_get_a_distinct_uk_message():
    assert is_clearly_outside_uk(40.7128, -74.0060)  # New York
    assert is_clearly_outside_uk(48.8566, 2.3522)  # Paris
    assert not is_clearly_outside_uk(54.5973, -5.9301)  # Northern Ireland: unsupported, but UK
    assert not is_clearly_outside_uk(float("nan"), 0)
    assert "outside the UK" in OUTSIDE_UK_MESSAGE


def test_location_portal_reports_the_distinct_message_for_an_overseas_fix():
    messages = []
    portal = LocationPortal(lambda _region: None, messages.append)
    portal.session_path = "/test/session"

    class Parameters:
        @staticmethod
        def unpack():
            return "/test/session", {"Latitude": 40.7128, "Longitude": -74.0060}

    portal._on_location_signal(None, None, "LocationUpdated", Parameters())

    assert messages == [OUTSIDE_UK_MESSAGE]
    assert portal._finished


def test_cancelling_a_portal_request_prevents_late_callbacks():
    portal = LocationPortal(lambda _region: None, lambda _message: None)

    portal.cancel()

    assert portal._finished
