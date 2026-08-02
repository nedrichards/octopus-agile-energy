import json
import logging
import math
import secrets

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)

REGION_DATA_PATH = "/app/share/octopusagile/gb-electricity-regions.geojson"
REGION_NAME_TO_CODE = {
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


def load_region_features(path=REGION_DATA_PATH):
    with open(path, encoding="utf-8") as data_file:
        return json.load(data_file)["features"]


def _point_in_ring(longitude, latitude, ring):
    inside = False
    for index, (x2, y2) in enumerate(ring):
        x1, y1 = ring[index - 1]
        crosses = (y1 > latitude) != (y2 > latitude)
        if crosses and longitude < (x2 - x1) * (latitude - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _point_on_segment(longitude, latitude, start, end):
    x1, y1 = start
    x2, y2 = end
    cross_product = (latitude - y1) * (x2 - x1) - (longitude - x1) * (y2 - y1)
    if abs(cross_product) > 1e-10:
        return False
    return min(x1, x2) <= longitude <= max(x1, x2) and min(y1, y2) <= latitude <= max(y1, y2)


def _point_in_geometry(longitude, latitude, geometry):
    if geometry["type"] == "Polygon":
        rings = geometry["coordinates"]
        return _point_in_ring(longitude, latitude, rings[0]) and not any(
            _point_in_ring(longitude, latitude, hole) for hole in rings[1:]
        )
    if geometry["type"] == "MultiPolygon":
        return any(_point_in_geometry(longitude, latitude, {"type": "Polygon", "coordinates": polygon})
                   for polygon in geometry["coordinates"])
    return False


def suggest_region_code(latitude, longitude, features=None):
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    matching_codes = []
    for feature in features if features is not None else load_region_features():
        rings = feature.get("geometry", {}).get("coordinates", [])
        if feature.get("geometry", {}).get("type") == "MultiPolygon":
            rings = [ring for polygon in rings for ring in polygon]
        if any(
            _point_on_segment(longitude, latitude, start, end)
            for ring in rings
            for index, start in enumerate(ring)
            for end in [ring[index - 1]]
        ):
            return None
        region_code = REGION_NAME_TO_CODE.get(feature.get("properties", {}).get("longname"))
        if region_code and _point_in_geometry(longitude, latitude, feature.get("geometry", {})):
            matching_codes.append(region_code)
    return matching_codes[0] if len(matching_codes) == 1 else None


class LocationPortal:
    """Ask the desktop Location portal for one user-requested location fix."""

    BUS_NAME = "org.freedesktop.portal.Desktop"
    OBJECT_PATH = "/org/freedesktop/portal/desktop"
    LOCATION_INTERFACE = "org.freedesktop.portal.Location"

    def __init__(self, on_region, on_error):
        self.on_region = on_region
        self.on_error = on_error
        self.proxy = None
        self.session_path = None
        self.session_proxy = None
        self.request_proxy = None

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
                "session_handle_token": GLib.Variant("s", f"octopusagile{secrets.token_hex(8)}"),
                "accuracy": GLib.Variant("u", 5),
            }
            result = self.proxy.call_sync(
                "CreateSession",
                GLib.Variant("(a{sv})", (options,)),
                Gio.DBusCallFlags.NONE,
                10_000,
                None,
            )
            self.session_path = result.unpack()[0]
            self.proxy.call(
                "Start",
                GLib.Variant("(osa{sv})", (self.session_path, "", {
                    "handle_token": GLib.Variant("s", f"octopusagile{secrets.token_hex(8)}")
                })),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._on_start_finished,
                None,
            )
        except GLib.Error as error:
            self.on_error(f"Could not request your location: {error.message}")
        except (OSError, ValueError) as error:
            self.on_error(f"Could not request your location: {error}")

    def _on_start_finished(self, proxy, result, _user_data):
        try:
            request_path = proxy.call_finish(result).unpack()[0]
            self.request_proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                self.BUS_NAME,
                request_path,
                "org.freedesktop.portal.Request",
                None,
            )
            self.request_proxy.connect("g-signal", self._on_request_signal)
        except GLib.Error as error:
            self.on_error(f"Could not start the location request: {error.message}")

    def _on_request_signal(self, _proxy, _sender, signal_name, parameters):
        if signal_name == "Response" and parameters.unpack()[0] != 0:
            self.on_error("Location permission was not granted.")

    def _on_location_signal(self, _proxy, _sender, signal_name, parameters):
        if signal_name != "LocationUpdated":
            return
        _session_path, location = parameters.unpack()
        if _session_path != self.session_path:
            return
        try:
            latitude = location["Latitude"]
            longitude = location["Longitude"]
            region_code = suggest_region_code(latitude, longitude)
            if region_code:
                self.on_region(region_code)
            else:
                self.on_error("Your location is outside a uniquely matched electricity region.")
        finally:
            self.close()

    def close(self):
        if self.session_path:
            session_proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                self.BUS_NAME,
                self.session_path,
                "org.freedesktop.portal.Session",
                None,
            )
            session_proxy.call(
                "Close",
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                None,
                None,
            )
            self.session_path = None
