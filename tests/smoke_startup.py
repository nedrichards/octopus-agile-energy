"""Construct and map real GTK workspaces on an isolated Broadway display."""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def smoke(resource_path):
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.ui.main_window import MainWindow

    Gio.Resource.load(str(resource_path))._register()
    settings = Gio.Settings.new("com.nedrichards.octopusagile")
    settings.set_boolean("setup-completed", True)
    settings.set_string("selected-tariff-code", "E-1R-AGILE-SMOKE-A")
    application = Adw.Application(application_id="com.example.AgileRatesStartupSmoke",
                                  flags=Gio.ApplicationFlags.NON_UNIQUE)
    application.register(None)
    errors = []
    sys.excepthook = lambda *error: errors.append(error)

    # Exercise real widget construction and layout without any service workers.
    with patch.object(MainWindow, "refresh_price"), \
            patch.object(MainWindow, "refresh_usage_history_background"), \
            patch.object(MainWindow, "_update_usage_insights"), \
            patch.object(MainWindow, "find_cheapest_slot"):
        window = MainWindow(application=application, initial_main_view="usage")
        try:
            window.present()
            for width in (390, 1100):
                window.set_default_size(width, 700)
                for view in ("prices", "plan", "usage"):
                    window.show_main_view(view)
                    end = time.monotonic() + 0.3
                    while time.monotonic() < end:
                        GLib.MainContext.default().iteration(False)
                        time.sleep(0.005)
                    assert window.main_view_stack.get_visible_child_name() == view
                    assert window.main_view_stack.get_visible_child().get_mapped(), view
                    assert not errors, errors
            print("GTK startup and all three workspaces passed at narrow and wide sizes")
        finally:
            window.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resource", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="agile-startup-") as task_dir:
        task_path = Path(task_dir)
        schemas = task_path / "schemas"
        schemas.mkdir()
        shutil.copy(Path(__file__).resolve().parents[1] / "data/com.nedrichards.octopusagile.gschema.xml", schemas)
        subprocess.run(["glib-compile-schemas", str(schemas)], check=True)
        os.environ.update(GSETTINGS_BACKEND="memory", GSETTINGS_SCHEMA_DIR=str(schemas),
                          XDG_RUNTIME_DIR=task_dir, XDG_CACHE_HOME=str(task_path / "cache"),
                          GDK_BACKEND="broadway", BROADWAY_DISPLAY=":1", GSK_RENDERER="cairo")
        with (task_path / "display.log").open("w+") as log:
            display = subprocess.Popen(["gtk4-broadwayd", "--unixsocket", str(task_path / "http.socket"), ":1"],
                                       stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 5
                while not (task_path / "broadway2.socket").exists():
                    if display.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise RuntimeError(f"Headless GTK display failed: {log.read()}")
                    time.sleep(0.02)
                smoke(args.resource.resolve())
            finally:
                display.terminate()
                display.wait(timeout=5)


if __name__ == "__main__":
    main()
