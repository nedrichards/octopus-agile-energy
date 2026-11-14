"""Exercise installed native widgets with isolated fixture data and save review captures."""

import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk


def installed(module):
    if not Path(module.__file__).resolve().is_relative_to("/app"):
        raise RuntimeError("Smoke imported checkout code instead of the installed package")


def pump(ready, seconds=5):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if ready():
            return
        time.sleep(0.01)
    raise RuntimeError("Native window did not settle before the capture deadline")


WIDTHS = (390, 1100)


def create(stack):
    import octopusagile.main as module
    from octopusagile.ui.main_window import MainWindow

    installed(module)
    Gio.Resource.load("/app/share/octopusagile/octopusagile.gresource")._register()
    settings = Gio.Settings.new("com.nedrichards.octopusagile")
    settings.set_boolean("setup-completed", True)
    settings.set_string("selected-tariff-code", "E-1R-AGILE-SMOKE-A")
    for name in ("refresh_price", "refresh_usage_history_background", "_update_usage_insights", "find_cheapest_slot"):
        stack.enter_context(patch.object(MainWindow, name))
    app = Adw.Application(application_id="com.example.AgileRatesCi", flags=Gio.ApplicationFlags.NON_UNIQUE)
    if not app.register(None):
        raise RuntimeError("Could not register fixture application")
    window = MainWindow(application=app, initial_main_view="usage")
    return app, window, lambda: True


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        raise RuntimeError("Installed visual smoke requires a native display")
    Adw.init()
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-enable-animations", False)
    if os.getenv("CI_LARGE_TEXT") == "1":
        settings.set_property("gtk-font-name", "Adwaita Sans 16")
    manager = Adw.StyleManager.get_default()
    if os.getenv("ADW_DEBUG_HIGH_CONTRAST") == "1" and not manager.get_high_contrast():
        raise RuntimeError("Requested high contrast is not active")
    errors = []
    sys.excepthook = lambda *error: errors.append(error)
    with ExitStack() as stack:
        app, window, ready = create(stack)
        try:
            for scheme, label in ((Adw.ColorScheme.FORCE_LIGHT, "light"), (Adw.ColorScheme.FORCE_DARK, "dark")):
                manager.set_color_scheme(scheme)
                for width in WIDTHS:
                    window.set_default_size(width, 780)
                    window.present()
                    pump(lambda: window.get_mapped() and ready())
                    clock = window.get_frame_clock()
                    frame = clock.get_frame_counter()
                    window.queue_draw()
                    pump(lambda clock=clock, frame=frame: clock.get_frame_counter() > frame)
                    if errors:
                        raise RuntimeError(f"Native callback failed: {errors}")
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                    node = snapshot.to_node()
                    if node is None:
                        raise RuntimeError("Mapped native window produced no render node")
                    texture = window.get_renderer().render_texture(node, None)
                    target = output / f"window-{width}-{label}.png"
                    if not texture.save_to_png(str(target)):
                        raise RuntimeError("Could not save native fixture capture")
                    print(f"CAPTURE_PASS: {target.name} {window.get_width()}x{window.get_height()}", flush=True)
        finally:
            window.destroy()
            app.quit()
    print("INSTALLED_VISUAL_SMOKE_PASS", flush=True)


if __name__ == "__main__":
    main()
