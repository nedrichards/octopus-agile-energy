import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import logging
import threading
from datetime import datetime, timedelta, timezone

import requests
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..price_logic import extract_product_code
from ..price_logic import find_cheapest_slot as calculate_cheapest_slot
from ..secrets_manager import get_api_key
from ..utils import CacheManager
from .adaptive_layout import (
    DEFAULT_CHART_SLOTS,
    get_chart_slot_count,
    get_chart_scroll_value,
    get_content_margin,
    get_price_summary_mode,
    is_compact_width,
)
from .custom_spin_button import CustomSpinButton
from .preferences_window import PreferencesWindow
from .price_chart import PriceChartWidget

logger = logging.getLogger(__name__)

class MainWindow(Adw.ApplicationWindow):
    """
    The main application window, inheriting from Adw.ApplicationWindow for LibAdwaita styling.
    Manages UI setup, data fetching, and display updates.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.settings = Gio.Settings.new("com.nedrichards.octopusagile")
        self._update_window_title()

        self.all_prices = []
        self.chart_prices = []
        self.current_price_data = None
        self.cache_manager = CacheManager() # Initialize CacheManager

        # Initialize Gio.Settings
        self.settings.connect("changed::selected-tariff-type", self.on_setting_changed)
        self.settings.connect("changed::selected-tariff-code", self.on_setting_changed)
        self.settings.connect("changed::selected-region-code", self.on_setting_changed)

        self.settings.bind("window-width", self, "default-width", Gio.SettingsBindFlags.DEFAULT)
        self.settings.bind("window-height", self, "default-height", Gio.SettingsBindFlags.DEFAULT)
        self.settings.bind("window-maximized", self, "maximized", Gio.SettingsBindFlags.DEFAULT)

        self.preferences_window = None
        self.timer_id = None
        self.best_slot_start_time = None
        self.is_first_expansion = True
        self._fetch_generation = 0
        self.price_summary_mode = "regular"
        self.price_summary_title = "Loading..."
        self.price_summary_description = "Fetching current electricity price"
        self.price_summary_compact_description = "Fetching current electricity price"
        self.price_summary_css_class = None

        self.connect("notify::visible", self.on_visibility_change)
        self.connect("notify::width", self.on_window_width_changed)
        self.connect("notify::height", self.on_window_width_changed)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

        self.create_actions()
        self.setup_ui()
        self.refresh_price()
        self.schedule_next_ui_update()
        self.schedule_next_data_fetch()

    def schedule_next_ui_update(self):
        now = datetime.now()
        if now.minute < 30:
            next_update = now.replace(minute=30, second=0, microsecond=0)
        else:
            next_update = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        delay = (next_update - now).total_seconds()
        GLib.timeout_add_seconds(int(delay), self._on_ui_update_timer)

    def _on_ui_update_timer(self):
        self.update_current_price()
        self.schedule_next_ui_update()
        return False

    def schedule_next_data_fetch(self):
        now = datetime.now()
        next_fetch = now.replace(hour=16, minute=1, second=0, microsecond=0)
        if now > next_fetch:
            next_fetch += timedelta(days=1)

        delay = (next_fetch - now).total_seconds()
        GLib.timeout_add_seconds(int(delay), self._on_data_fetch_timer)

    def _on_data_fetch_timer(self):
        self.refresh_price()
        self.schedule_next_data_fetch()
        return False

    def create_headerbar_widget(self): # Renamed to reflect it returns a widget
        """
        Configures and returns the application's header bar widget.
        This method is now called from setup_ui to create a widget to be appended.
        """
        header_bar = Adw.HeaderBar.new()
        self.header_title_widget = Adw.WindowTitle.new("Octopus Electricity Prices", "")
        header_bar.set_title_widget(self.header_title_widget)

        # Refresh button on the left.
        self.header_refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.header_refresh_button.set_tooltip_text("Refresh")
        self.header_refresh_button.add_css_class("flat")
        self.header_refresh_button.connect('clicked', self.on_refresh_clicked)
        header_bar.pack_start(self.header_refresh_button)

        # Menu button on the right for About/Quit/Preferences actions.
        menu_button = Gtk.MenuButton.new()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Main Menu")

        menu_model = Gio.Menu.new()
        menu_model.append("Preferences", "app.preferences") # New: Preferences action
        menu_model.append("About", "app.about")
        menu_model.append("Quit", "app.quit")
        menu_button.set_menu_model(menu_model)
        header_bar.pack_end(menu_button)

        self.menu_button = menu_button
        return header_bar # Return the configured header bar widget

    def create_actions(self):
        """
        Creates and registers application-level actions (e.g., About, Quit, Preferences).
        """
        # About action, triggered by clicking "About" in the menu.
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_action)
        self.get_application().add_action(about_action)

        # Quit action, triggered by "Quit" in the menu or Ctrl+Q.
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit_action)
        self.get_application().add_action(quit_action)
        self.get_application().set_accels_for_action("app.quit", ["<primary>q"])

        # Preferences action, opens the settings dialog
        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self.on_preferences_action)
        self.get_application().add_action(preferences_action)
        self.get_application().set_accels_for_action("app.preferences", ["<primary>comma"])

        # Refresh action, triggers a data refresh
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", self.on_refresh_clicked)
        self.get_application().add_action(refresh_action)
        self.get_application().set_accels_for_action("app.refresh", ["<primary>r"])

        # Find cheapest time action
        find_cheapest_action = Gio.SimpleAction.new("find_cheapest", None)
        find_cheapest_action.connect("activate", self.on_find_cheapest_action)
        self.get_application().add_action(find_cheapest_action)
        self.get_application().set_accels_for_action("app.find_cheapest", ["<primary>f"])

        help_action = Gio.SimpleAction.new("show-help-overlay", None)
        help_action.connect("activate", self.on_show_help_overlay)
        self.get_application().add_action(help_action)
        self.get_application().set_accels_for_action("app.show-help-overlay", ["question"])

    def on_find_cheapest_action(self, action, param):
        """
        Handles the find cheapest action by expanding the expander row and focusing the duration spin button.
        """
        self.expander_row.set_expanded(True)
        self.duration_spin_button.grab_focus()

    def on_key_pressed(self, controller, keyval, keycode, modifier):
        """
        Handles key press events for the main window.
        """
        if keyval == Gdk.KEY_question:
            self.on_show_help_overlay(None, None)
            return True

        return False

    def on_show_help_overlay(self, action, param):
        builder = Gtk.Builder.new_from_resource(
            "/com/nedrichards/octopusagile/gtk/help-overlay.ui"
        )
        help_window = builder.get_object("help_overlay")
        help_window.set_transient_for(self)
        help_window.present()

    def on_about_action(self, action, param):
        """
        Displays the About dialog.
        """
        about_dialog = Adw.AboutWindow(
            transient_for=self,
            application_name="Octopus Electricity Prices",
            application_icon="com.nedrichards.octopusagile",
            developer_name="Nick Richards",
            version="1.0.10",
            website="https://www.nedrichards.com/2025/07/octopus-agile-prices-for-linux/",
            copyright="© 2026 Nick Richards",
            license_type=Gtk.License.GPL_3_0
        )
        about_dialog.present()

    def on_visibility_change(self, *args):
        if self.is_visible():
            self._refresh_adaptive_layout()
            self.refresh_price()

    def on_quit_action(self, action, param):
        """
        Quits the application.
        """
        self.get_application().quit()

    def on_preferences_action(self, action, param):
        """
        Opens the Preferences window.
        """
        if not self.preferences_window:
            self.preferences_window = PreferencesWindow(settings=self.settings, parent=self)
            self.preferences_window.connect("hide", self.on_preferences_hidden)

        self.preferences_window.present()

    def on_preferences_hidden(self, window):
        """
        Handles the closing of the preferences window.
        """
        self.refresh_price(force=True)

    def on_first_run(self):
        """
        Shows a welcome message and opens the preferences window.
        """
        self._set_price_summary(
            "Welcome to Octopus Electricity Prices",
            "Please select your tariff in the preferences.",
            compact_description="Select your tariff in preferences.",
        )
        self.on_preferences_action(None, None)

    def on_setting_changed(self, settings, key):
        """
        Callback for when a GSettings key changes. Triggers a price refresh.
        """
        if key == "selected-tariff-type":
            self._update_window_title()

        if self.preferences_window and self.preferences_window.is_visible():
            return

        logger.debug("Setting '%s' changed. Refreshing price data.", key)
        self.refresh_price()

    def _update_window_title(self):
        tariff_type = self.settings.get_string("selected-tariff-type")
        title = "Octopus Electricity Prices"
        subtitle = {
            'AGILE': "Agile tariff",
            'GO': "Go tariff",
            'INTELLIGENT': "Intelligent Go tariff",
        }.get(tariff_type, "")

        self.set_title(title)
        if hasattr(self, 'header_title_widget'):
            self.header_title_widget.set_title(title)
            self.header_title_widget.set_subtitle(subtitle)

    def setup_ui(self):
        """
        Sets up the main user interface layout using Gtk.Box and Adwaita widgets.
        The entire content is now wrapped in a Gtk.ScrolledWindow.
        """
        # Get the configured header bar widget.
        header_bar = self.create_headerbar_widget()

        # Root vertical box that will hold the header bar and the main scrollable content.
        root_vbox = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root_vbox.append(header_bar) # Header bar is the first child of the root box.

        # Main content area. Individual sections decide whether they should clamp.
        overall_content_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.overall_content_box = overall_content_box

        top_content_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.top_content_box = top_content_box
        top_clamp = Adw.Clamp.new()
        top_clamp.set_child(top_content_box)

        bottom_content_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.bottom_content_box = bottom_content_box
        bottom_clamp = Adw.Clamp.new()
        bottom_clamp.set_child(bottom_content_box)

        overall_content_box.append(top_clamp)
        overall_content_box.append(bottom_clamp)

        # Create a scrolled window for the entire main content.
        # Adw.ApplicationWindow handles scrolling of its main content, so this Gtk.ScrolledWindow
        # should now contain the clamp, and be placed inside the root_vbox.
        scrolled_content = Gtk.ScrolledWindow.new()
        scrolled_content.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_content.set_vexpand(True)
        scrolled_content.set_child(overall_content_box)

        root_vbox.append(scrolled_content) # The scrolled content is the second child of the root box.

        # Current price display card.
        self.price_card_stack = Gtk.Stack.new()
        self.price_card_stack.set_hhomogeneous(False)
        self.price_card_stack.set_vhomogeneous(False)

        self.price_card = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.price_card.set_halign(Gtk.Align.CENTER)
        self.price_card.set_valign(Gtk.Align.START)
        self.price_card.set_vexpand(False)
        self.price_card.add_css_class("regular-price-card")

        self.price_card_title = Gtk.Label.new()
        self.price_card_title.add_css_class("regular-price-title")
        self.price_card_title.set_halign(Gtk.Align.CENTER)
        self.price_card_title.set_justify(Gtk.Justification.CENTER)
        self.price_card.append(self.price_card_title)

        self.price_card_description = Gtk.Label.new()
        self.price_card_description.add_css_class("regular-price-description")
        self.price_card_description.set_halign(Gtk.Align.CENTER)
        self.price_card_description.set_wrap(True)
        self.price_card_description.set_justify(Gtk.Justification.CENTER)
        self.price_card.append(self.price_card_description)

        self.price_card_stack.add_named(self.price_card, "regular")

        self.compact_price_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.compact_price_box.set_halign(Gtk.Align.CENTER)
        self.compact_price_box.add_css_class("compact-price-card")

        self.compact_price_title = Gtk.Label.new()
        self.compact_price_title.add_css_class("compact-price-title")
        self.compact_price_box.append(self.compact_price_title)

        self.compact_price_description = Gtk.Label.new()
        self.compact_price_description.add_css_class("compact-price-description")
        self.compact_price_description.set_wrap(True)
        self.compact_price_description.set_justify(Gtk.Justification.CENTER)
        self.compact_price_box.append(self.compact_price_description)

        self.price_card_stack.add_named(self.compact_price_box, "compact")
        top_content_box.append(self.price_card_stack)
        self._render_price_summary()

        # Chart section with a styled background
        chart_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        chart_box.add_css_class("chart-background") # Apply new background style
        self.chart_box = chart_box

        self.chart_scroller = Gtk.ScrolledWindow.new()
        self.chart_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.chart_scroller.set_hexpand(True)
        self.chart_scroller.set_propagate_natural_height(True)

        self.price_chart = PriceChartWidget()
        self.price_chart.set_vexpand(True)
        self.chart_scroller.set_child(self.price_chart)
        chart_box.append(self.chart_scroller)

        overall_content_box.insert_child_after(chart_box, top_clamp)

        # --- New section for finding the best slot ---
        expander_group = Adw.PreferencesGroup()
        bottom_content_box.append(expander_group)

        self.expander_row = Adw.ExpanderRow()
        self.expander_row.set_title("Find Cheapest Time")
        self.expander_row.set_subtitle("Find the cheapest time to use electricity")
        self.expander_row.connect("notify::expanded", self.on_expander_row_activated)
        expander_group.add(self.expander_row)

        # --- Duration input ---
        self.duration_row = Adw.ActionRow.new()
        self.duration_row.set_title("For how long?")
        self.duration_spin_button = CustomSpinButton(min_val=1, max_val=24, step=1)
        self.duration_spin_button.set_value(1)
        self.duration_row.add_suffix(self.duration_spin_button)
        self.duration_spin_button.connect('value-changed', self.on_find_cheapest_slot_triggered)
        self.expander_row.add_row(self.duration_row)

        # --- Start within input ---
        self.start_within_row = Adw.ActionRow.new()
        self.start_within_row.set_title("In the next?")
        self.start_within_spin_button = CustomSpinButton(min_val=1, max_val=24, step=1)
        self.start_within_spin_button.set_value(8)
        self.start_within_row.add_suffix(self.start_within_spin_button)
        self.start_within_spin_button.connect('value-changed', self.on_find_cheapest_slot_triggered)
        self.expander_row.add_row(self.start_within_row)

        # --- Result rows ---
        self.best_slot_result_row = Adw.ActionRow.new()
        self.best_slot_result_row.set_title("Best time to start is")
        self.best_slot_result_label = Gtk.Label.new()
        self.best_slot_result_row.add_suffix(self.best_slot_result_label)
        self.best_slot_result_row.set_visible(False)
        self.expander_row.add_row(self.best_slot_result_row)

        self.average_price_row = Adw.ActionRow.new()
        self.average_price_row.set_title("Average Price")
        self.average_price_label = Gtk.Label.new()
        self.average_price_row.add_suffix(self.average_price_label)
        self.average_price_row.set_visible(False)
        self.expander_row.add_row(self.average_price_row)


        self.timer_row = Adw.ActionRow.new()
        self.timer_row.set_title("Starts in")
        self.timer_label = Gtk.Label.new()
        self.timer_row.add_suffix(self.timer_label)
        self.timer_row.set_visible(False)
        self.expander_row.add_row(self.timer_row)
        # --- End of new section ---

        self.time_label = Gtk.Label.new()
        self.time_label.set_markup("<span size='small'>Last updated: Never</span>")
        self.time_label.set_halign(Gtk.Align.END)
        self.time_label.set_margin_top(12)
        self.time_label.set_margin_end(10)
        bottom_content_box.append(self.time_label)

        # Status label for persistent error messages.
        self.status_label = Gtk.Label.new()
        self.status_label.set_halign(Gtk.Align.CENTER)
        self.status_label.add_css_class("error") # Style with red text for errors.
        bottom_content_box.append(self.status_label)

        usage_group = Adw.PreferencesGroup()
        usage_group.set_title("Usage Insights")
        usage_group.set_description("Recent electricity consumption trends from cached Octopus usage history.")
        bottom_content_box.append(usage_group)

        self.usage_insights_row = Adw.ActionRow.new()
        self.usage_insights_row.set_title("Recent usage trends")
        self.usage_insights_row.set_subtitle("Refresh usage history in Preferences to fill this section.")
        usage_group.add(self.usage_insights_row)

        # Use Adw.ToastOverlay to display temporary messages, wrapping the entire content.
        self.toast_overlay = Adw.ToastOverlay.new()
        self.toast_overlay.set_child(root_vbox) # The root_vbox (containing header and scrolled content) is the child.
        self.set_content(self.toast_overlay) # Set the toast overlay as the main window content.
        GLib.idle_add(self._refresh_adaptive_layout)

    def on_window_width_changed(self, widget, _pspec):
        self._refresh_adaptive_layout()

    def _refresh_adaptive_layout(self):
        width = self.get_width() or self.settings.get_int("window-width")
        if width <= 0:
            return False

        self._apply_adaptive_layout(width)
        return False

    def _apply_adaptive_layout(self, width):
        compact = is_compact_width(width)
        height = self.get_height() or self.settings.get_int("window-height")
        price_summary_mode = get_price_summary_mode(width, height)
        self.is_compact_layout = compact
        margin = get_content_margin(width)

        self.overall_content_box.set_margin_top(margin)
        self.overall_content_box.set_margin_bottom(margin)
        self.overall_content_box.set_margin_start(margin)
        self.overall_content_box.set_margin_end(margin)

        chart_margin = max(8, margin - 2)
        self.chart_box.set_margin_top(chart_margin)
        self.chart_box.set_margin_bottom(chart_margin)
        self.chart_box.set_margin_start(chart_margin)
        self.chart_box.set_margin_end(chart_margin)

        self.time_label.set_halign(Gtk.Align.CENTER if compact else Gtk.Align.END)
        self.time_label.set_margin_top(10 if compact else 14)
        self.time_label.set_margin_end(0 if compact else 10)
        self.status_label.set_wrap(compact)

        chart_slot_count = len(self.chart_prices) if self.chart_prices else DEFAULT_CHART_SLOTS
        self.price_chart.set_compact_mode(compact, width, chart_slot_count)
        self._set_price_summary_mode(price_summary_mode)
        self.header_title_widget.set_visible(not compact)
        self.menu_button.set_tooltip_text("Menu" if compact else "Main Menu")

        if self.current_price_data:
            self.update_current_price()



    def on_chart_click(self, index):
        """
        Handles chart bar clicks. Currently mirrors hover logic but can be expanded.
        """
        pass

    def on_refresh_clicked(self, *args):
        """
        Handles the refresh button click, initiating data fetch and disabling buttons.
        This action forces a cache bypass.
        """
        self.header_refresh_button.set_sensitive(False)
        self.refresh_price(force=True)

    def on_find_cheapest_slot_triggered(self, spin_button):
        duration_hours = self.duration_spin_button.get_value_as_int()
        start_within_hours = self.start_within_spin_button.get_value_as_int()
        self.find_cheapest_slot(duration_hours, start_within_hours)

    def on_expander_row_activated(self, expander_row, param):
        if expander_row.get_expanded() and self.is_first_expansion:
            self.is_first_expansion = False
            self.on_find_cheapest_slot_triggered(self.duration_spin_button)

    def find_cheapest_slot(self, duration_hours, start_within_hours):
        self.price_chart.set_highlight_range(None, None) # Clear previous highlight
        now = datetime.now(timezone.utc)
        cheapest_slot = calculate_cheapest_slot(
            self.all_prices,
            now,
            duration_hours,
            start_within_hours,
        )

        if not cheapest_slot:
            self.best_slot_result_label.set_text("Not enough data to find the cheapest time.")
            self.best_slot_result_row.set_visible(True)
            self.average_price_row.set_visible(False)
            self.timer_row.set_visible(False)
            return

        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

        best_slot_start_time = cheapest_slot['start']
        best_slot_end_time = cheapest_slot['end']
        self.price_chart.set_highlight_range(best_slot_start_time, best_slot_end_time)
        self._scroll_chart_to_time(best_slot_start_time)

        self.best_slot_result_label.set_text(f"{best_slot_start_time.astimezone().strftime('%H:%M')}")
        self.best_slot_result_row.set_visible(True)

        average_price = cheapest_slot['average_price_gbp']
        self.average_price_label.set_text(f"£{average_price:.2f}/kWh")
        self.average_price_row.set_visible(True)

        delta = best_slot_start_time.astimezone() - datetime.now().astimezone()
        if delta.total_seconds() > 0:
            self.best_slot_start_time = best_slot_start_time.astimezone()
            self.timer_id = GLib.timeout_add_seconds(1, self._update_countdown)
            self._update_countdown() # Initial update
            self.timer_row.set_visible(True)
        else:
            self.timer_label.set_text("The cheapest time is now.")
            self.timer_row.set_visible(True)

    def _scroll_chart_to_time(self, target_time):
        target_index = self._find_chart_index_for_time(target_time)
        if target_index is None:
            return

        GLib.idle_add(self._scroll_chart_to_index, target_index)

    def _find_chart_index_for_time(self, target_time):
        for index, price in enumerate(self.chart_prices):
            if price['valid_from'] == target_time:
                return index

        for index, price in enumerate(self.chart_prices):
            if price['valid_from'] >= target_time:
                return index

        return None

    def _scroll_chart_to_index(self, target_index):
        target_x = self.price_chart.get_bar_start_x(target_index)
        if target_x is None:
            return False

        adjustment = self.chart_scroller.get_hadjustment()
        if adjustment is None:
            return False

        scroll_value = get_chart_scroll_value(
            adjustment.get_value(),
            adjustment.get_page_size(),
            adjustment.get_upper(),
            target_x,
        )
        adjustment.set_value(scroll_value)
        return False

    def _update_countdown(self):
        if not self.best_slot_start_time:
            return False

        delta = self.best_slot_start_time - datetime.now().astimezone()
        if delta.total_seconds() <= 0:
            self.timer_label.set_text("The cheapest time is now.")
            self.timer_id = None
            return False # Stop the timer

        hours, remainder = divmod(delta.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        self.timer_label.set_text(f"{int(hours):02}:{int(minutes):02}")
        self.timer_row.set_visible(True)
        return True # Continue the timer

    def refresh_price(self, force=False):
        """
        Initiates the price data fetching process in a separate thread.
        Sets the UI to a loading state.
        """
        self._fetch_generation += 1
        request_id = self._fetch_generation
        current_title = (
            f"£{self.current_price_data['price_gbp']:.2f}/kWh"
            if self.current_price_data
            else "Loading..."
        )
        self._set_price_summary(
            current_title,
            "Fetching the latest prices...",
            compact_description="Refreshing prices...",
            css_class=None,
        )

        thread = threading.Thread(
            target=self.fetch_price_data,
            kwargs={'force': force, 'request_id': request_id}
        )
        thread.daemon = True
        thread.start()

    def _is_current_fetch(self, request_id):
        return request_id == self._fetch_generation

    def _apply_processed_prices(self, processed_prices, request_id):
        if not self._is_current_fetch(request_id):
            return False

        self.all_prices = processed_prices
        self.update_current_price()
        return False

    def _show_error_if_current(self, error_message, request_id):
        if not self._is_current_fetch(request_id):
            return False

        self.show_error(error_message)
        return False

    def fetch_price_data(self, force=False, request_id=None):
        """
        Fetches and processes electricity price data from the Octopus Energy API.
        """
        selected_tariff_code = self.settings.get_string("selected-tariff-code")
        if not selected_tariff_code:
            GLib.idle_add(self.on_first_run)
            return

        try:
            tariff_type = self.settings.get_string("selected-tariff-type")
            product_code = extract_product_code(selected_tariff_code)

            now = datetime.now(timezone.utc)
            rates_cache_key = f"octopus_rates_{selected_tariff_code}_{now.strftime('%Y-%m-%d')}"

            raw_rates = None
            cached_data, cache_mtime_ts = self.cache_manager.get(rates_cache_key)
            if cached_data and cache_mtime_ts:
                cache_mtime = datetime.fromtimestamp(cache_mtime_ts, tz=timezone.utc)
                release_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
                if not (now >= release_time and cache_mtime < release_time):
                    logger.debug("Rates data loaded from cache.")
                    raw_rates = cached_data
                else:
                    logger.debug("Stale cache, will refetch.")

            if not raw_rates:
                if force:
                    logger.debug("Forced refresh requested, but no valid cache available. Fetching new data from API.")
                else:
                    logger.debug("Fetching new data from API.")
                rates_url = f"https://api.octopus.energy/v1/products/{product_code}/electricity-tariffs/{selected_tariff_code}/standard-unit-rates/"

                # Use basic auth for intelligent go if API key is provided
                auth = None
                api_key = get_api_key()
                if api_key and tariff_type == 'INTELLIGENT':
                    from requests.auth import HTTPBasicAuth
                    auth = HTTPBasicAuth(api_key, '')

                response = requests.get(rates_url, params={'page_size': 1500}, timeout=10, auth=auth)
                response.raise_for_status()
                data = response.json()

                filtered_rates_dict = {
                    rate['valid_from']: rate
                    for rate in data.get('results', [])
                    if (datetime.fromisoformat(rate['valid_to'].replace('Z', '+00:00')) -
                        datetime.fromisoformat(rate['valid_from'].replace('Z', '+00:00'))) == timedelta(minutes=30)
                }
                raw_rates = sorted(filtered_rates_dict.values(), key=lambda x: x['valid_from'])
                self.cache_manager.set(rates_cache_key, raw_rates)

            if not self._is_current_fetch(request_id):
                return

            if raw_rates:
                self._process_and_set_prices(raw_rates, request_id)
            else:
                GLib.idle_add(self._show_error_if_current, "No price data available from API.", request_id)

        except requests.exceptions.RequestException as e:
            GLib.idle_add(self._show_error_if_current, f"Network error: {type(e).__name__}", request_id)
        except Exception as e:
            import traceback
            traceback.print_exc()
            GLib.idle_add(self._show_error_if_current, f"An unexpected error occurred: {e}", request_id)

    def _process_and_set_prices(self, raw_rates, request_id):
        """
        Processes raw price data by converting dates and prices, then updates the main price list.
        This centralized processing improves performance by avoiding redundant conversions.
        """
        processed_prices = []
        for rate in raw_rates:
            try:
                processed_prices.append({
                    'valid_from': datetime.fromisoformat(rate['valid_from'].replace('Z', '+00:00')),
                    'valid_to': datetime.fromisoformat(rate['valid_to'].replace('Z', '+00:00')),
                    'price_gbp': rate['value_inc_vat'] / 100.0,
                })
            except (ValueError, KeyError) as e:
                logger.warning("Skipping rate due to processing error: %s", e)
                continue

        GLib.idle_add(self._apply_processed_prices, processed_prices, request_id)

    def update_current_price(self):
        """
        Finds the current price from the pre-processed list and updates the UI.
        """
        if not self.all_prices:
            return

        now_utc = datetime.now(timezone.utc)
        current_rate = None
        for rate in self.all_prices:
            if rate['valid_from'] <= now_utc < rate['valid_to']:
                current_rate = rate
                break

        if current_rate:
            display_from = current_rate['valid_from']
            chart_slot_count = get_chart_slot_count(
                self.get_width() or self.settings.get_int("window-width")
            )
            display_to = display_from + timedelta(minutes=30 * chart_slot_count)
            self.chart_prices = [p for p in self.all_prices if display_from <= p['valid_from'] < display_to]

            current_index_in_chart = 0 # Current price is always the first in the chart view
            GLib.idle_add(self.update_display, current_rate, self.chart_prices, current_index_in_chart)
        else:
            self.show_error("No current price data found. Rates may not be published yet.")

    def update_display(self, current_rate, chart_prices, current_index):
        """
        Updates the UI with the processed price data.
        """
        self.current_price_data = current_rate
        price_pounds = current_rate['price_gbp']

        if price_pounds < 0:
            status = "Negative (you get paid to use electricity!)"
            css_class = "price-negative"
        elif price_pounds < 0.15:
            status = "Low"
            css_class = "price-low"
        elif price_pounds < 0.25:
            status = "Medium"
            css_class = "price-medium"
        else:
            status = "High"
            css_class = "price-high"

        self._set_price_summary(
            f"£{price_pounds:.2f}/kWh",
            f"The current price is {status}",
            compact_description="",
            css_class=css_class,
        )
        self.time_label.set_markup(f"<span size='small'>Last updated: {datetime.now().strftime('%H:%M:%S')}</span>")
        self.price_chart.set_compact_mode(
            is_compact_width(self.get_width()),
            self.get_width() or self.settings.get_int("window-width"),
            len(chart_prices),
        )
        self.price_chart.set_prices(chart_prices, current_index)
        self.status_label.set_text("")
        self._update_usage_insights()
        self.header_refresh_button.set_sensitive(True)

    def show_error(self, error_message):
        """
        Displays an error state in the UI.
        """
        self._set_price_summary(
            "Error",
            "Could not fetch price data.",
            compact_description="Could not fetch price data.",
            css_class=None,
        )
        self.status_label.set_text(error_message)
        self.toast_overlay.add_toast(Adw.Toast.new(f"Error: {error_message}"))
        self.header_refresh_button.set_sensitive(True)

    def _set_price_summary(self, title, description, compact_description=None, css_class=None):
        self.price_summary_title = title
        self.price_summary_description = description
        self.price_summary_compact_description = (
            compact_description if compact_description is not None else description
        )
        self.price_summary_css_class = css_class
        self._render_price_summary()

    def _set_price_summary_mode(self, mode):
        self.price_summary_mode = mode
        self._render_price_summary()

    def _render_price_summary(self):
        self.price_card_title.set_text(self.price_summary_title)
        self.price_card_description.set_text(self.price_summary_description)
        self.price_card_description.set_visible(bool(self.price_summary_description))

        escaped_title = GLib.markup_escape_text(self.price_summary_title)
        self.compact_price_title.set_markup(
            f"<span size='xx-large' weight='bold'>{escaped_title}</span>"
        )
        self.compact_price_description.set_text(self.price_summary_compact_description)
        self.compact_price_description.set_visible(bool(self.price_summary_compact_description))

        self._apply_price_summary_classes()
        self.price_card_stack.set_visible_child_name(self.price_summary_mode)
        self._queue_price_summary_refresh()

    def _update_usage_insights(self):
        account_number = self.settings.get_string("octopus-account-number").strip()
        if not account_number:
            self.usage_insights_row.set_subtitle("Add your account number in Preferences to enable these insights.")
            return

        cache_key = f"octopus_usage_{account_number}"
        cached_data, _cache_mtime = self.cache_manager.get(cache_key)
        if not cached_data or "samples" not in cached_data:
            self.usage_insights_row.set_subtitle("No cached usage history found. Use Preferences → Refresh usage history.")
            return

        self.usage_insights_row.set_subtitle(
            self._build_usage_insight_text(cached_data.get("samples", []), cached_data.get("synced_at"))
        )

    def _build_usage_insight_text(self, samples, synced_at):
        if not samples:
            return "No usage samples available yet."

        daily_totals = {}
        for sample in samples:
            interval_start = sample.get("interval_start")
            consumption = sample.get("consumption")
            if interval_start is None or consumption is None:
                continue
            try:
                start_dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
                day_key = start_dt.date().isoformat()
                daily_totals[day_key] = daily_totals.get(day_key, 0.0) + float(consumption)
            except (TypeError, ValueError):
                continue

        if len(daily_totals) < 7:
            return "Not enough usage data yet (need at least seven days)."

        sorted_days = sorted(daily_totals.items(), key=lambda x: x[0])
        values = [value for _day, value in sorted_days]
        avg_daily = sum(values) / len(values)
        recent_7 = values[-7:]
        previous_7 = values[-14:-7] if len(values) >= 14 else []
        recent_avg = sum(recent_7) / len(recent_7)
        previous_avg = (sum(previous_7) / len(previous_7)) if previous_7 else recent_avg
        trend_pct = 0.0 if previous_avg == 0 else ((recent_avg - previous_avg) / previous_avg) * 100.0
        monthly_projection = avg_daily * 30.0
        based_on = f" Based on data through {synced_at[:10]}." if synced_at else ""
        return (
            f"Average daily consumption: {avg_daily:.2f} kWh · "
            f"Seven-day trend: {trend_pct:+.1f}% · "
            f"Estimated monthly consumption: {monthly_projection:.0f} kWh."
            f"{based_on}"
        )

    def _apply_price_summary_classes(self):
        for widget in (self.price_card, self.compact_price_box):
            widget.remove_css_class("price-high")
            widget.remove_css_class("price-medium")
            widget.remove_css_class("price-low")
            widget.remove_css_class("price-negative")
            if self.price_summary_css_class:
                widget.add_css_class(self.price_summary_css_class)

    def _queue_price_summary_refresh(self):
        for widget in (
            self.price_card_stack,
            self.price_card,
            self.compact_price_box,
            self.compact_price_title,
            self.compact_price_description,
        ):
            widget.queue_allocate()
            widget.queue_draw()
