"""Offline electricity-region lookup and one-shot Location portal access.

The geometry code intentionally has no GTK or D-Bus dependency so that it can
be tested independently.  Coordinates received from the portal are used only
in memory for the lookup and are never logged or persisted.
"""

from __future__ import annotations

import json
import math
import secrets
from pathlib import Path
from typing import Any, Iterable

REGION_DATA_PATH = "/app/share/octopusagile/gb-electricity-regions.geojson"

# A deliberately broad envelope lets the UI recognise locations that are
# plainly overseas without pretending that it is a political-border lookup.
# Locations within it (including Northern Ireland and nearby countries) still
# use the normal no-region outcome rather than an incorrect outside-UK claim.
UK_LOCATION_ENVELOPE = (49.0, 61.5, -10.0, 3.0)
OUTSIDE_UK_MESSAGE = (
    "Agile Rates is for Octopus Energy electricity tariffs in the UK. It looks like you're outside the UK, "
    "so we can't find a region. Thanks for trying Agile Rates."
)

REGION_CODE_TO_NAME = {
    "_A": "Eastern England",
    "_B": "East Midlands",
    "_C": "London",
    "_D": "Merseyside & North Wales",
    "_E": "West Midlands",
    "_F": "North East England",
    "_G": "North West England",
    "_H": "Southern England",
    "_J": "South East England",
    "_K": "South Wales",
    "_L": "South Western England",
    "_M": "Yorkshire",
    "_N": "South Scotland",
    "_P": "North Scotland",
}
REGION_NAME_TO_CODE = {name: code for code, name in REGION_CODE_TO_NAME.items()}

# The Northern Powergrid data names DNO licence areas, not Octopus tariff
# suffixes. Keeping this translation here makes the data-to-tariff contract
# explicit and avoids DNO-name checks in the UI.
DNO_NAME_TO_REGION_CODE = {
    "UKPN (East)": "_A",
    "WPD (East Midlands)": "_B",
    "UKPN (London)": "_C",
    "SPEN (SP MANWEB)": "_D",
    "WPD (Midlands)": "_E",
    "NPG (Northern Electric)": "_F",
    "ENWL": "_G",
    "SSE (Southern)": "_H",
    "UKPN (South)": "_J",
    "WPD (South Wales)": "_K",
    "WPD (South West)": "_L",
    "NPG (Yorkshire Electric)": "_M",
    "SPEN (SP Distribution)": "_N",
    "SSE": "_P",
}


def load_region_features(path: str | Path = REGION_DATA_PATH) -> list[dict[str, Any]]:
    """Load the installed, offline GeoJSON boundary snapshot."""
    with Path(path).open(encoding="utf-8") as data_file:
        data = json.load(data_file)
    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError("The bundled electricity-region data has no features list.")
    return features


def feature_region_code(feature: dict[str, Any]) -> str | None:
    """Return the explicit Octopus code for a Northern Powergrid feature."""
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        return None
    return DNO_NAME_TO_REGION_CODE.get(properties.get("longname"))


def bundled_region_codes(features: Iterable[dict[str, Any]]) -> set[str]:
    """Return the valid Octopus codes represented by the supplied features."""
    return {code for feature in features if (code := feature_region_code(feature)) is not None}


def _point_on_segment(longitude: float, latitude: float, start: list[float], end: list[float]) -> bool:
    x1, y1 = start
    x2, y2 = end
    cross_product = (latitude - y1) * (x2 - x1) - (longitude - x1) * (y2 - y1)
    if abs(cross_product) > 1e-10:
        return False
    return min(x1, x2) <= longitude <= max(x1, x2) and min(y1, y2) <= latitude <= max(y1, y2)


def _point_in_ring(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    """Return whether a point is strictly inside a linear GeoJSON ring."""
    inside = False
    for index, end in enumerate(ring):
        start = ring[index - 1]
        if _point_on_segment(longitude, latitude, start, end):
            return False
        x1, y1 = start
        x2, y2 = end
        crosses = (y1 > latitude) != (y2 > latitude)
        if crosses and longitude < (x2 - x1) * (latitude - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _point_on_ring_boundary(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    return any(_point_on_segment(longitude, latitude, ring[index - 1], end) for index, end in enumerate(ring))


def point_in_geometry(longitude: float, latitude: float, geometry: dict[str, Any]) -> bool:
    """Test a point against GeoJSON Polygon or MultiPolygon geometry, including holes."""
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        if not coordinates:
            return False
        if any(_point_on_ring_boundary(longitude, latitude, ring) for ring in coordinates):
            return False
        return _point_in_ring(longitude, latitude, coordinates[0]) and not any(
            _point_in_ring(longitude, latitude, hole) for hole in coordinates[1:]
        )
    if geometry_type == "MultiPolygon":
        return any(
            point_in_geometry(longitude, latitude, {"type": "Polygon", "coordinates": polygon})
            for polygon in coordinates or []
        )
    return False


def _rings_for_geometry(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    if geometry.get("type") == "Polygon":
        yield from geometry.get("coordinates", [])
    elif geometry.get("type") == "MultiPolygon":
        for polygon in geometry.get("coordinates", []):
            yield from polygon


def _distance_to_segment_meters(
    longitude: float, latitude: float, start: list[float], end: list[float]
) -> float:
    """Approximate point-to-segment distance for the small areas used here."""
    metres_per_degree_latitude = 111_320.0
    metres_per_degree_longitude = metres_per_degree_latitude * math.cos(math.radians(latitude))
    start_x = (start[0] - longitude) * metres_per_degree_longitude
    start_y = (start[1] - latitude) * metres_per_degree_latitude
    end_x = (end[0] - longitude) * metres_per_degree_longitude
    end_y = (end[1] - latitude) * metres_per_degree_latitude
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return math.hypot(start_x, start_y)
    factor = max(0.0, min(1.0, -(start_x * delta_x + start_y * delta_y) / length_squared))
    return math.hypot(start_x + factor * delta_x, start_y + factor * delta_y)


def is_near_region_boundary(
    latitude: float,
    longitude: float,
    accuracy_meters: float,
    features: Iterable[dict[str, Any]] | None = None,
) -> bool:
    """Return whether reported accuracy makes a boundary result genuinely uncertain."""
    if not math.isfinite(accuracy_meters) or accuracy_meters <= 0:
        return False
    region_features = features if features is not None else load_region_features()
    for feature in region_features:
        if feature_region_code(feature) is None:
            continue
        for ring in _rings_for_geometry(feature.get("geometry", {})):
            for index, end in enumerate(ring):
                if _distance_to_segment_meters(longitude, latitude, ring[index - 1], end) <= accuracy_meters:
                    return True
    return False


def find_region_for_coordinates(
    latitude: float, longitude: float, features: Iterable[dict[str, Any]] | None = None
) -> str | None:
    """Find the one GB electricity region containing a latitude/longitude point."""
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    matching_codes = []
    region_features = features if features is not None else load_region_features()
    for feature in region_features:
        region_code = feature_region_code(feature)
        geometry = feature.get("geometry")
        if region_code is None or not isinstance(geometry, dict):
            continue
        if point_in_geometry(longitude, latitude, geometry):
            matching_codes.append(region_code)
    return matching_codes[0] if len(matching_codes) == 1 else None


def is_clearly_outside_uk(latitude: float, longitude: float) -> bool:
    """Conservatively identify a point that is plainly outside the UK area."""
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return False
    south, north, west, east = UK_LOCATION_ENVELOPE
    return not (south <= latitude <= north and west <= longitude <= east)


# Keep the original helper name for callers from the first implementation.
suggest_region_code = find_region_for_coordinates


import gi  # noqa: E402  The geometry helpers above deliberately avoid GI imports.

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


class LocationPortal:
    """Ask the desktop portal for one explicit location fix, then close it."""

    BUS_NAME = "org.freedesktop.portal.Desktop"
    OBJECT_PATH = "/org/freedesktop/portal/desktop"
    LOCATION_INTERFACE = "org.freedesktop.portal.Location"
    REQUEST_INTERFACE = "org.freedesktop.portal.Request"
    SESSION_INTERFACE = "org.freedesktop.portal.Session"

    def __init__(self, on_region, on_error):
        self.on_region = on_region
        self.on_error = on_error
        self.proxy = None
        self.session_path = None
        self.session_proxy = None
        self.request_proxy = None
        self._finished = False

    def start(self):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                self.BUS_NAME,
                self.OBJECT_PATH,
                self.LOCATION_INTERFACE,
                None,
            )
            self.proxy.connect("g-signal", self._on_location_signal)
            options = {
                "session_handle_token": GLib.Variant("s", self._token()),
                "accuracy": GLib.Variant("u", 5),  # XDG portal EXACT accuracy.
            }
            self.proxy.call(
                "CreateSession",
                GLib.Variant("(a{sv})", (options,)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._on_create_session_finished,
                None,
            )
        except GLib.Error:
            self._fail("Location services are unavailable. Choose your region manually.")

    @staticmethod
    def _token() -> str:
        return f"octopusagile{secrets.token_hex(8)}"

    def _on_create_session_finished(self, proxy, result, _user_data):
        if self._finished:
            return
        try:
            self.session_path = proxy.call_finish(result).unpack()[0]
            self.session_proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                self.BUS_NAME,
                self.session_path,
                self.SESSION_INTERFACE,
                None,
            )
            self.session_proxy.connect("g-signal", self._on_session_signal)
            options = {"handle_token": GLib.Variant("s", self._token())}
            self.proxy.call(
                "Start",
                GLib.Variant("(osa{sv})", (self.session_path, "", options)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._on_start_finished,
                None,
            )
        except GLib.Error:
            self._fail("Could not start location services. Choose your region manually.")

    def _on_start_finished(self, proxy, result, _user_data):
        if self._finished:
            return
        try:
            request_path = proxy.call_finish(result).unpack()[0]
            self.request_proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                self.BUS_NAME,
                request_path,
                self.REQUEST_INTERFACE,
                None,
            )
            self.request_proxy.connect("g-signal", self._on_request_signal)
        except GLib.Error:
            self._fail("Could not request your location. Choose your region manually.")

    def _on_request_signal(self, _proxy, _sender, signal_name, parameters):
        if signal_name != "Response" or self._finished:
            return
        response_code = parameters.unpack()[0]
        if response_code != 0:
            self._fail("Location permission was not granted. Choose your region manually.")

    def _on_session_signal(self, _proxy, _sender, signal_name, _parameters):
        if signal_name == "Closed" and not self._finished:
            self._fail("Location services closed before finding a region. Choose your region manually.")

    def _on_location_signal(self, _proxy, _sender, signal_name, parameters):
        if signal_name != "LocationUpdated" or self._finished:
            return
        session_path, location = parameters.unpack()
        if session_path != self.session_path:
            return
        try:
            latitude = location.get("Latitude")
            longitude = location.get("Longitude")
            accuracy = location.get("Accuracy")
            if not isinstance(latitude, (float, int)) or not isinstance(longitude, (float, int)):
                self._fail("Could not obtain a usable location. Choose your region manually.")
                return
            latitude = float(latitude)
            longitude = float(longitude)
            if is_clearly_outside_uk(latitude, longitude):
                self._fail(OUTSIDE_UK_MESSAGE)
                return
            region_code = find_region_for_coordinates(latitude, longitude)
            if region_code is None:
                self._fail(
                    "This location isn't within the Great Britain electricity regions supported by the app. "
                    "Choose your region manually."
                )
                return
            if isinstance(accuracy, (float, int)) and is_near_region_boundary(
                latitude, longitude, float(accuracy)
            ):
                self._fail("This location is close to a region boundary. Confirm or choose your region manually.")
                return
            self._finish(region_code)
        except (OSError, ValueError, TypeError):
            self._fail("Could not read the bundled region data. Choose your region manually.")

    def _finish(self, region_code: str):
        if self._finished:
            return
        self._finished = True
        try:
            self.on_region(region_code)
        finally:
            self.close()

    def _fail(self, message: str):
        if self._finished:
            return
        self._finished = True
        try:
            self.on_error(message)
        finally:
            self.close()

    def close(self):
        """Close the portal session without retaining any received location data."""
        self._finished = True
        if self.session_proxy is not None and self.session_path is not None:
            try:
                self.session_proxy.call(
                    "Close", None, Gio.DBusCallFlags.NONE, -1, None, None, None
                )
            except GLib.Error:
                pass
        self.session_path = None
        self.session_proxy = None
        self.request_proxy = None
        self.proxy = None

    cancel = close
