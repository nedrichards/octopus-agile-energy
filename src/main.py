# main.py
#
# Copyright 2025 Nick Richards
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

import logging
import sys

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .application_id import get_application_id, is_development_build
from .ui.main_window import MainWindow
from .ui.styles import get_css


LAUNCHABLE_MAIN_VIEWS = frozenset(("prices", "plan", "usage"))


def configure_logging():
    """Enable app diagnostics without exposing third-party HTTP request paths."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout,
    )
    application_logger = logging.getLogger(__package__ or __name__.partition('.')[0])
    application_logger.setLevel(logging.DEBUG if is_development_build() else logging.INFO)


class OctopusAgileApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=get_application_id(),
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._requested_main_view = None
        self.add_main_option(
            "tab",
            ord("t"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            "Show a workspace without changing the saved selection",
            "prices|plan|usage",
        )
        self.connect("activate", self.on_activate)
        self.connect("command-line", self.on_command_line)

    @staticmethod
    def _validate_requested_main_view(view_name):
        return view_name if view_name in LAUNCHABLE_MAIN_VIEWS else None

    def on_command_line(self, _app, command_line):
        options = command_line.get_options_dict()
        option_value = options.lookup_value("tab", GLib.VariantType.new("s"))
        requested_view = option_value.get_string() if option_value else None
        if requested_view and not self._validate_requested_main_view(requested_view):
            command_line.printerr(
                "--tab must be one of: prices, plan, usage\n"
            )
            return 2

        self._requested_main_view = requested_view
        self.activate()
        return 0

    def on_activate(self, app):
        """
        Activates the application, creating the main window only when needed.
        """
        requested_main_view = getattr(self, "_requested_main_view", None)
        self.window = app.get_active_window()
        if self.window is None:
            window_kwargs = {"application": app}
            if requested_main_view:
                window_kwargs["initial_main_view"] = requested_main_view
            self.window = MainWindow(**window_kwargs)
        elif requested_main_view:
            self.window.show_main_view(requested_main_view)
        self.window.present()
        self._requested_main_view = None

def main(*args):
    """
    Main function to initialize and run the Agile Rates application.
    Loads custom CSS for styling.
    """
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Agile Rates")

    app = OctopusAgileApp()

    # Load custom CSS for application-specific styling.
    css_provider = Gtk.CssProvider.new()
    css_provider.load_from_string(get_css())

    # Add the CSS provider to the default display, setting a high priority
    # so it overrides default styles.
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    return app.run()

if __name__ == '__main__':
    main()
