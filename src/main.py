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

from gi.repository import Adw, Gdk, Gtk

from .application_id import get_application_id, is_development_build
from .ui.main_window import MainWindow
from .ui.styles import get_css


class OctopusAgileApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=get_application_id())
        self.connect("activate", self.on_activate)

    def on_activate(self, app):
        """
        Activates the application, creating the main window only when needed.
        """
        self.window = app.get_active_window()
        if self.window is None:
            self.window = MainWindow(application=app)
        self.window.present()

def main(*args):
    """
    Main function to initialize and run the Agile Rates application.
    Loads custom CSS for styling.
    """
    logging.basicConfig(
        level=logging.DEBUG if is_development_build() else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )
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
