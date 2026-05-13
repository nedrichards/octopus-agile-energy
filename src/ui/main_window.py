import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

import cairo
import requests
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..octopus_api import OctopusApiError
from ..price_logic import extract_product_code
from ..price_logic import find_cheapest_slot as calculate_cheapest_slot
from ..secrets_manager import get_api_key
from ..usage_history import build_historical_usage_costs, fetch_recent_usage_samples, get_account_data
from ..usage_insights import build_usage_insight_data
from ..utils import CacheManager
from .adaptive_layout import (
    DEFAULT_CHART_SLOTS,
    get_chart_content_width,
    get_chart_height,
    get_chart_scroll_value,
    get_chart_slot_count,
    get_content_margin,
    get_price_summary_mode,
    get_time_label_interval,
    is_compact_width,
)
from .custom_spin_button import CustomSpinButton
from .preferences_window import PreferencesWindow
from .price_chart import PriceChartWidget
from .setup_window import SetupWindow

logger = logging.getLogger(__name__)
USAGE_BACKGROUND_REFRESH_INTERVAL_SECONDS = 6 * 60 * 60

class MainWindow(Adw.ApplicationWindow):
    """
    The main application window, inheriting from Adw.ApplicationWindow for LibAdwaita styling.
    Manages UI setup, data fetching, and display updates.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.settings = Gio.Settings.new("com.nedrichards.octopusagile")
        if self.settings.get_string("selected-tariff-code") and not self.settings.get_boolean("setup-completed"):
            self.settings.set_boolean("setup-completed", True)
        self._update_window_title()

        self.all_prices = []
        self.chart_prices = []
        self.current_price_data = None
        self.cache_manager = CacheManager() # Initialize CacheManager

        # Initialize Gio.Settings
        self.settings.connect("changed::selected-tariff-type", self.on_setting_changed)
        self.settings.connect("changed::selected-tariff-code", self.on_setting_changed)
        self.settings.connect("changed::selected-region-code", self.on_setting_changed)
        self.settings.connect("changed::octopus-account-number", self.on_usage_account_changed)

        self.settings.bind("window-width", self, "default-width", Gio.SettingsBindFlags.DEFAULT)
        self.settings.bind("window-height", self, "default-height", Gio.SettingsBindFlags.DEFAULT)
        self.settings.bind("window-maximized", self, "maximized", Gio.SettingsBindFlags.DEFAULT)

        self.preferences_window = None
        self.setup_window = None
        self.timer_id = None
        self.best_slot_start_time = None
        self.best_slot_end_time = None
        self.is_first_expansion = True
        self._fetch_generation = 0
        self.price_summary_mode = "regular"
        self.price_summary_title = "Loading..."
        self.price_summary_description = "Fetching current electricity price"
        self.price_summary_compact_description = "Fetching current electricity price"
        self.price_summary_css_class = None
        self.usage_refresh_in_progress = False
        self.usage_refresh_attempted = False
        self.usage_graph_mode = "kwh"

        self.connect("notify::visible", self.on_visibility_change)
        self.connect("notify::width", self.on_window_width_changed)
        self.connect("notify::height", self.on_window_width_changed)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

        self.create_actions()
        self.setup_ui()
        if self._needs_setup():
            GLib.idle_add(self.on_first_run)
        else:
            self.refresh_usage_history_background()
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
        if not self._needs_setup():
            self.refresh_price()
        self.schedule_next_data_fetch()
        return False

    def create_headerbar_widget(self): # Renamed to reflect it returns a widget
        """
        Configures and returns the application's header bar widget.
        This method is now called from setup_ui to create a widget to be appended.
        """
        header_bar = Adw.HeaderBar.new()
        self.header_title_widget = Adw.WindowTitle.new("Agile Rates", "")
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

        setup_action = Gio.SimpleAction.new("setup", None)
        setup_action.connect("activate", self.on_setup_action)
        self.get_application().add_action(setup_action)

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

    def _add_best_slot_summary_item(self, title, row):
        title_label = Gtk.Label.new(title)
        title_label.set_xalign(0)
        title_label.add_css_class("dim-label")
        self.best_slot_summary_grid.attach(title_label, 0, row, 1, 1)

        value_label = Gtk.Label.new()
        value_label.set_xalign(1)
        value_label.set_hexpand(True)
        self.best_slot_summary_grid.attach(value_label, 1, row, 1, 1)
        return value_label

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
            application_name="Agile Rates",
            application_icon="com.nedrichards.octopusagile",
            developer_name="Nick Richards",
            version="1.0.11",
            website="https://www.nedrichards.com/2026/05/agile-rates-after-launch/",
            copyright="© 2026 Nick Richards",
            license_type=Gtk.License.GPL_3_0
        )
        about_dialog.add_link("Source Code", "https://github.com/nedrichards/octopus-agile-energy")
        about_dialog.present()

    def on_visibility_change(self, *args):
        if self.is_visible():
            self._refresh_adaptive_layout()
            if not self._needs_setup():
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

    def on_setup_action(self, action, param):
        self.present_setup_window()

    def on_preferences_hidden(self, window):
        """
        Handles the closing of the preferences window.
        """
        self.usage_refresh_attempted = False
        self._update_usage_insights()
        self.refresh_usage_history_background()
        self.refresh_price(force=True)

    def on_first_run(self):
        """
        Shows a welcome message and opens the setup assistant.
        """
        self._set_price_summary(
            "Welcome to Agile Rates",
            "Complete setup to start seeing electricity prices.",
            compact_description="Complete setup to continue.",
        )
        self.present_setup_window()
        return False

    def present_setup_window(self):
        if not self.setup_window:
            self.setup_window = SetupWindow(
                settings=self.settings,
                parent=self,
                on_complete=self.on_setup_complete,
            )
            self.setup_window.connect("close-request", self.on_setup_closed)

        self.setup_window.present()

    def on_setup_closed(self, _window):
        self.setup_window = None
        return False

    def on_setup_complete(self):
        self.usage_refresh_attempted = False
        self.refresh_usage_history_background(force=True)
        self.refresh_price(force=True)

    def _needs_setup(self):
        return (
            not self.settings.get_boolean("setup-completed")
            or not self.settings.get_string("selected-tariff-code")
        )

    def on_setting_changed(self, settings, key):
        """
        Callback for when a GSettings key changes. Triggers a price refresh.
        """
        if key == "selected-tariff-type":
            self._update_window_title()

        if (
            (self.preferences_window and self.preferences_window.is_visible())
            or (self.setup_window and self.setup_window.is_visible())
        ):
            return

        logger.debug("Setting '%s' changed. Refreshing price data.", key)
        self.refresh_price()

    def on_usage_account_changed(self, _settings, _key):
        self.usage_refresh_attempted = False
        if not self.preferences_window or not self.preferences_window.is_visible():
            self._update_usage_insights()
            self.refresh_usage_history_background()

    def _update_window_title(self):
        tariff_type = self.settings.get_string("selected-tariff-type")
        title = "Agile Rates"
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

        # Usage page content. The chart mirrors the price tab by staying outside
        # the clamp, while the preference-style rows remain constrained.
        usage_page_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.usage_page_box = usage_page_box

        usage_content_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.usage_content_box = usage_content_box
        usage_clamp = Adw.Clamp.new()
        usage_clamp.set_child(usage_content_box)
        usage_page_box.append(usage_clamp)

        usage_scroll = Gtk.ScrolledWindow.new()
        usage_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        usage_scroll.set_vexpand(True)
        usage_scroll.set_child(usage_page_box)

        usage_chart_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        usage_chart_box.add_css_class("chart-background")
        self.usage_chart_box = usage_chart_box
        usage_page_box.prepend(usage_chart_box)

        self.usage_chart_scroller = Gtk.ScrolledWindow.new()
        self.usage_chart_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.usage_chart_scroller.set_hexpand(True)
        self.usage_chart_scroller.set_propagate_natural_height(True)

        usage_chart_mode_box = Gtk.Box.new(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        usage_chart_mode_box.set_halign(Gtk.Align.END)
        usage_chart_mode_box.add_css_class("linked")
        self.usage_chart_mode_box = usage_chart_mode_box
        self.usage_kwh_button = Gtk.ToggleButton.new_with_label("kWh")
        self.usage_kwh_button.set_active(True)
        self.usage_kwh_button.set_tooltip_text("Daily electricity consumption.")
        self.usage_energy_cost_button = Gtk.ToggleButton.new_with_label("£ Energy")
        self.usage_energy_cost_button.set_group(self.usage_kwh_button)
        self.usage_energy_cost_button.set_tooltip_text("Daily energy cost from matched usage and unit rates, excluding standing charge.")
        self.usage_total_cost_button = Gtk.ToggleButton.new_with_label("£ Total")
        self.usage_total_cost_button.set_group(self.usage_kwh_button)
        self.usage_total_cost_button.set_tooltip_text("Daily total cost from matched usage, unit rates, and standing charge.")
        self.usage_kwh_button.connect("toggled", self.on_usage_graph_mode_toggled, "kwh")
        self.usage_energy_cost_button.connect("toggled", self.on_usage_graph_mode_toggled, "energy_cost_gbp")
        self.usage_total_cost_button.connect("toggled", self.on_usage_graph_mode_toggled, "total_cost_gbp")
        usage_chart_mode_box.append(self.usage_kwh_button)
        usage_chart_mode_box.append(self.usage_energy_cost_button)
        usage_chart_mode_box.append(self.usage_total_cost_button)
        usage_chart_box.append(usage_chart_mode_box)

        self.usage_chart_area = Gtk.DrawingArea.new()
        self.usage_chart_area.set_hexpand(True)
        self.usage_chart_area.set_vexpand(False)
        self.usage_chart_area.set_draw_func(self._draw_usage_chart)
        self._connect_usage_chart_style_updates()
        self.usage_chart_points = []
        self.usage_chart_dates = []
        self.usage_chart_daily_data = []
        self.usage_chart_scroller.set_child(self.usage_chart_area)
        self.usage_chart_area.set_has_tooltip(True)
        self.usage_chart_area.connect("query-tooltip", self.on_usage_chart_query_tooltip)
        usage_chart_box.append(self.usage_chart_scroller)

        usage_group = Adw.PreferencesGroup()
        usage_group.set_title("Usage")
        usage_content_box.append(usage_group)

        self.usage_insights_row = Adw.ActionRow.new()
        self.usage_insights_row.set_title("Recent usage trends")
        self.usage_insights_row.set_subtitle("Refresh usage history in Preferences to fill this section.")
        usage_group.add(self.usage_insights_row)

        self.usage_avg_row = Adw.ActionRow.new()
        self.usage_avg_row.set_title("Average daily consumption")
        self.usage_avg_row.add_prefix(Gtk.Image.new_from_icon_name("weather-clear-symbolic"))
        self.usage_avg_label = Gtk.Label.new("—")
        self.usage_avg_row.add_suffix(self.usage_avg_label)
        usage_group.add(self.usage_avg_row)

        self.usage_trend_row = Adw.ActionRow.new()
        self.usage_trend_row.set_title("Seven-day trend")
        self.usage_trend_row.add_prefix(Gtk.Image.new_from_icon_name("view-sort-descending-symbolic"))
        self.usage_trend_label = Gtk.Label.new("—")
        self.usage_trend_row.add_suffix(self.usage_trend_label)
        usage_group.add(self.usage_trend_row)

        self.usage_month_row = Adw.ActionRow.new()
        self.usage_month_row.set_title("Estimated monthly consumption")
        self.usage_month_row.add_prefix(Gtk.Image.new_from_icon_name("x-office-calendar-symbolic"))
        self.usage_month_label = Gtk.Label.new("—")
        self.usage_month_row.add_suffix(self.usage_month_label)
        usage_group.add(self.usage_month_row)

        spending_group = Adw.PreferencesGroup()
        spending_group.set_title("Estimated Spend")
        self.spending_group = spending_group
        usage_content_box.append(spending_group)

        self.cost_accuracy_row = Adw.ActionRow.new()
        self.cost_accuracy_row.set_title("Spend accuracy")
        self.cost_accuracy_row.set_subtitle("Waiting for historical usage and rate data.")
        self.cost_accuracy_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        spending_group.add(self.cost_accuracy_row)

        self.cost_daily_row = Adw.ActionRow.new()
        self.cost_daily_row.set_title("Average daily energy spend")
        self.cost_daily_row.add_prefix(Gtk.Image.new_from_icon_name("accessories-calculator-symbolic"))
        self.cost_daily_label = Gtk.Label.new("—")
        self.cost_daily_row.add_suffix(self.cost_daily_label)
        spending_group.add(self.cost_daily_row)

        self.cost_total_daily_row = Adw.ActionRow.new()
        self.cost_total_daily_row.set_title("Average daily total spend")
        self.cost_total_daily_row.add_prefix(Gtk.Image.new_from_icon_name("accessories-calculator-symbolic"))
        self.cost_total_daily_label = Gtk.Label.new("—")
        self.cost_total_daily_row.add_suffix(self.cost_total_daily_label)
        spending_group.add(self.cost_total_daily_row)

        self.cost_trend_row = Adw.ActionRow.new()
        self.cost_trend_row.set_title("Recent total spend trend")
        self.cost_trend_row.add_prefix(Gtk.Image.new_from_icon_name("view-sort-descending-symbolic"))
        self.cost_trend_label = Gtk.Label.new("—")
        self.cost_trend_row.add_suffix(self.cost_trend_label)
        spending_group.add(self.cost_trend_row)

        self.cost_month_row = Adw.ActionRow.new()
        self.cost_month_row.set_title("Estimated monthly total spend")
        self.cost_month_row.add_prefix(Gtk.Image.new_from_icon_name("x-office-spreadsheet-symbolic"))
        self.cost_month_label = Gtk.Label.new("—")
        self.cost_month_row.add_suffix(self.cost_month_label)
        spending_group.add(self.cost_month_row)

        self.usage_updated_label = Gtk.Label.new()
        self.usage_updated_label.set_markup("<span size='small'>Last updated: Never</span>")
        self.usage_updated_label.set_halign(Gtk.Align.END)
        self.usage_updated_label.set_margin_top(10)
        self.usage_updated_label.set_margin_end(10)
        usage_content_box.append(self.usage_updated_label)

        self.main_view_stack = Adw.ViewStack.new()
        self.main_view_stack.add_titled_with_icon(scrolled_content, "prices", "Prices", "view-list-symbolic")
        self.main_view_stack.add_titled_with_icon(usage_scroll, "usage", "Usage", "preferences-system-symbolic")
        self.main_view_stack.connect("notify::visible-child-name", self.on_visible_tab_changed)

        view_switcher = Adw.ViewSwitcher.new()
        view_switcher.set_stack(self.main_view_stack)
        view_switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        view_switcher.set_halign(Gtk.Align.CENTER)
        view_switcher.set_margin_top(6)
        view_switcher.set_margin_bottom(6)
        root_vbox.append(view_switcher)
        root_vbox.append(self.main_view_stack) # Replaces single-page content with adaptive sections.

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

        # --- Result summary ---
        self.best_slot_summary_row = Gtk.ListBoxRow.new()
        self.best_slot_summary_row.set_selectable(False)
        self.best_slot_summary_row.set_activatable(False)

        summary_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        summary_box.set_margin_top(12)
        summary_box.set_margin_bottom(12)
        summary_box.set_margin_start(12)
        summary_box.set_margin_end(12)
        self.best_slot_summary_row.set_child(summary_box)

        self.best_slot_message_label = Gtk.Label.new("Not enough data to find the cheapest time.")
        self.best_slot_message_label.set_xalign(0)
        self.best_slot_message_label.set_wrap(True)
        self.best_slot_message_label.add_css_class("dim-label")
        summary_box.append(self.best_slot_message_label)

        self.best_slot_summary_grid = Gtk.Grid.new()
        self.best_slot_summary_grid.set_column_spacing(18)
        self.best_slot_summary_grid.set_row_spacing(6)
        summary_box.append(self.best_slot_summary_grid)

        self.best_slot_result_label = self._add_best_slot_summary_item("Best start", 0)
        self.timer_label = self._add_best_slot_summary_item("Starts in", 1)
        self.finish_time_label = self._add_best_slot_summary_item("Finishes after", 2)
        self.average_price_label = self._add_best_slot_summary_item("Average price", 3)

        self.best_slot_summary_row.set_visible(False)
        self.best_slot_message_label.set_visible(False)
        self.best_slot_summary_grid.set_visible(False)
        self.expander_row.add_row(self.best_slot_summary_row)
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
        self.usage_page_box.set_margin_top(margin)
        self.usage_page_box.set_margin_bottom(margin)
        self.usage_page_box.set_margin_start(margin)
        self.usage_page_box.set_margin_end(margin)
        self.usage_content_box.set_spacing(12 if compact else 16)

        chart_margin = max(8, margin - 2)
        self.chart_box.set_margin_top(chart_margin)
        self.chart_box.set_margin_bottom(chart_margin)
        self.chart_box.set_margin_start(chart_margin)
        self.chart_box.set_margin_end(chart_margin)
        self.usage_chart_box.set_margin_top(chart_margin)
        self.usage_chart_box.set_margin_bottom(chart_margin)
        self.usage_chart_box.set_margin_start(chart_margin)
        self.usage_chart_box.set_margin_end(chart_margin)
        mode_padding = 8 if compact else 10
        self.usage_chart_mode_box.set_margin_top(mode_padding)
        self.usage_chart_mode_box.set_margin_bottom(mode_padding)
        self.usage_chart_mode_box.set_margin_start(mode_padding)
        self.usage_chart_mode_box.set_margin_end(mode_padding)

        self.time_label.set_halign(Gtk.Align.CENTER if compact else Gtk.Align.END)
        self.time_label.set_margin_top(10 if compact else 14)
        self.time_label.set_margin_end(0 if compact else 10)
        self.usage_updated_label.set_halign(Gtk.Align.CENTER if compact else Gtk.Align.END)
        self.usage_updated_label.set_margin_end(0 if compact else 10)
        self.status_label.set_wrap(compact)

        chart_slot_count = len(self.chart_prices) if self.chart_prices else DEFAULT_CHART_SLOTS
        self.price_chart.set_compact_mode(compact, width, chart_slot_count)
        self._set_usage_chart_layout(width)
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

    def on_visible_tab_changed(self, stack, _pspec):
        if stack.get_visible_child_name() == "usage":
            self._update_usage_insights()
            self.refresh_usage_history_background()

    def on_usage_graph_mode_toggled(self, button, mode):
        if not button.get_active():
            return

        self.usage_graph_mode = mode
        self._update_usage_insights()

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
            if self.timer_id:
                GLib.source_remove(self.timer_id)
                self.timer_id = None
            self.best_slot_start_time = None
            self.best_slot_end_time = None
            self.best_slot_message_label.set_text("Not enough data to find the cheapest time.")
            self.best_slot_message_label.set_visible(True)
            self.best_slot_summary_grid.set_visible(False)
            self.best_slot_summary_row.set_visible(True)
            return

        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

        best_slot_start_time = cheapest_slot['start']
        best_slot_end_time = cheapest_slot['end']
        self.price_chart.set_highlight_range(
            best_slot_start_time,
            best_slot_end_time,
            f"Best {duration_hours}h",
        )
        self._scroll_chart_to_time(best_slot_start_time)

        self.best_slot_result_label.set_text(f"{best_slot_start_time.astimezone().strftime('%H:%M')}")

        average_price = cheapest_slot['average_price_gbp']
        self.average_price_label.set_text(f"£{average_price:.2f}/kWh")

        self.best_slot_message_label.set_visible(False)
        self.best_slot_summary_grid.set_visible(True)
        self.best_slot_summary_row.set_visible(True)

        self.best_slot_start_time = best_slot_start_time.astimezone()
        self.best_slot_end_time = best_slot_end_time.astimezone()
        self.timer_id = GLib.timeout_add_seconds(1, self._update_countdown)
        self._update_countdown() # Initial update

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
        if not self.best_slot_start_time or not self.best_slot_end_time:
            return False

        now = datetime.now().astimezone()
        start_delta = self.best_slot_start_time - now
        finish_delta = self.best_slot_end_time - now

        if start_delta.total_seconds() <= 0:
            self.timer_label.set_text("Now")
        else:
            self.timer_label.set_text(self._format_countdown_duration(start_delta))

        if finish_delta.total_seconds() <= 0:
            self.finish_time_label.set_text("Finished")
            self.timer_id = None
            return False # Stop the timer

        self.finish_time_label.set_text(self._format_countdown_duration(finish_delta))
        self.best_slot_summary_row.set_visible(True)
        return True # Continue the timer

    def _format_countdown_duration(self, delta):
        hours, remainder = divmod(delta.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{int(hours):02}:{int(minutes):02}"

    def refresh_price(self, force=False):
        """
        Initiates the price data fetching process in a separate thread.
        Sets the UI to a loading state.
        """
        self._fetch_generation += 1
        request_id = self._fetch_generation
        setup_issue = self._get_price_setup_issue()
        if setup_issue:
            title, description = setup_issue
            self._show_price_setup_issue(title, description)
            return

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
        setup_issue = self._get_price_setup_issue()
        if setup_issue:
            title, description = setup_issue
            GLib.idle_add(self._show_price_setup_issue, title, description)
            return

        try:
            selected_tariff_code = self.settings.get_string("selected-tariff-code")
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
                if response.status_code == 401:
                    GLib.idle_add(
                        self._show_error_if_current,
                        "The API key was rejected. Check the key in setup or Preferences.",
                        request_id,
                    )
                    return
                if response.status_code == 403:
                    GLib.idle_add(
                        self._show_error_if_current,
                        "This tariff requires account access. Check your API key or choose another tariff.",
                        request_id,
                    )
                    return
                if response.status_code == 404:
                    GLib.idle_add(
                        self._show_error_if_current,
                        "The selected tariff code was not found. Choose your tariff again in setup.",
                        request_id,
                    )
                    return
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

    def _get_price_setup_issue(self):
        tariff_code = self.settings.get_string("selected-tariff-code")
        tariff_type = self.settings.get_string("selected-tariff-type")

        if not self.settings.get_boolean("setup-completed"):
            return (
                "Setup Required",
                "Complete setup to start seeing electricity prices.",
            )

        if not tariff_code:
            return (
                "Choose a Tariff",
                "No tariff is selected. Open setup and choose your tariff manually or connect your account.",
            )

        inferred_type = self._infer_tariff_type_from_code(tariff_code)
        if tariff_type != inferred_type:
            return (
                "Check Tariff Settings",
                f"The selected tariff looks like {self._tariff_type_label(inferred_type)}, but the app is set to {self._tariff_type_label(tariff_type)}. Choose the tariff again in setup.",
            )

        if tariff_type == "INTELLIGENT" and not get_api_key():
            return (
                "API Key Required",
                "Intelligent Go prices need an API key. Add one in setup or Preferences, then load the tariff again.",
            )

        return None

    def _show_price_setup_issue(self, title, description):
        self._set_price_summary(
            title,
            description,
            compact_description=description,
            css_class=None,
        )
        self.status_label.set_text(description)
        self.header_refresh_button.set_sensitive(True)
        if self._needs_setup():
            self.present_setup_window()
        return False

    @staticmethod
    def _infer_tariff_type_from_code(tariff_code):
        normalized = tariff_code.upper().replace("_", "-")
        parts = [part for part in normalized.split("-") if part]
        if "INTELLI" in normalized or "INTELLIGENT" in normalized:
            return "INTELLIGENT"
        if "GO" in parts:
            return "GO"
        return "AGILE"

    @staticmethod
    def _tariff_type_label(tariff_type):
        return {
            "AGILE": "Agile",
            "GO": "Go",
            "INTELLIGENT": "Intelligent Go",
        }.get(tariff_type, "an unknown tariff type")

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
        self._set_last_updated_label(self.time_label, datetime.now().astimezone())
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
            self._set_usage_metric_placeholders()
            self._set_usage_updated_label(None)
            return

        cache_key = f"octopus_usage_{account_number}"
        cached_data, _cache_mtime = self.cache_manager.get(cache_key)
        if not cached_data or "samples" not in cached_data:
            self.usage_insights_row.set_subtitle("No cached usage history found. Usage will refresh in the background when an API key is available.")
            self._set_usage_metric_placeholders()
            self._set_usage_updated_label(None)
            return

        daily_costs = cached_data.get("daily_costs", [])
        self._set_usage_updated_label(cached_data.get("synced_at"))
        self._set_usage_cost_graph_controls_enabled(self._has_complete_daily_costs(daily_costs))
        insight = self._build_usage_insight_data(
            cached_data.get("samples", []),
            cached_data.get("synced_at"),
            daily_costs,
        )
        self.usage_insights_row.set_subtitle(insight["summary"])
        self._update_spend_accuracy_ui(daily_costs, cached_data.get("synced_at"))
        self.usage_avg_label.set_text(insight["avg_text"])
        self.usage_trend_label.set_text(insight["trend_text"])
        self.usage_month_label.set_text(insight["monthly_text"])
        self.cost_daily_label.set_text(insight["daily_cost_text"])
        self.cost_total_daily_label.set_text(insight["daily_total_cost_text"])
        self.cost_trend_label.set_text(insight["cost_trend_text"])
        self.cost_month_label.set_text(insight["monthly_cost_text"])
        chart_points, chart_dates, chart_unit, chart_daily_data = self._get_usage_chart_series(insight, daily_costs)
        self.usage_chart_points = list(reversed(chart_points))
        self.usage_chart_dates = list(reversed(chart_dates))
        self.usage_chart_daily_data = list(reversed(chart_daily_data))
        self.usage_chart_unit = chart_unit
        self._set_usage_chart_layout(self.get_width() or self.settings.get_int("window-width"))
        self.usage_chart_area.queue_draw()

    def _set_usage_updated_label(self, synced_at):
        self._set_last_updated_label(self.usage_updated_label, synced_at)

    def _set_last_updated_label(self, label_widget, updated_at):
        label = self._format_last_updated(updated_at)
        escaped_label = GLib.markup_escape_text(label)
        label_widget.set_markup(f"<span size='small'>Last updated: {escaped_label}</span>")

    def _format_last_updated(self, updated_at):
        if not updated_at:
            return "Never"

        try:
            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            local_dt = updated_at.astimezone()
            return local_dt.strftime("%d %b %Y, %H:%M")
        except (TypeError, ValueError):
            return "Unknown"

    def refresh_usage_history_background(self, force=False):
        if self.usage_refresh_in_progress or (self.usage_refresh_attempted and not force):
            return

        account_number = self.settings.get_string("octopus-account-number").strip()
        if not account_number or not get_api_key():
            return
        if not force and self._usage_cache_is_fresh(account_number):
            self.usage_refresh_attempted = True
            return

        self.usage_refresh_in_progress = True
        self.usage_refresh_attempted = True
        thread = threading.Thread(target=self._refresh_usage_history_background, args=(account_number,))
        thread.daemon = True
        thread.start()

    def _usage_cache_is_fresh(self, account_number):
        cache_key = f"octopus_usage_{account_number}"
        cached_data, cache_mtime = self.cache_manager.get(cache_key)
        if not cached_data or "samples" not in cached_data or "daily_costs" not in cached_data or not cache_mtime:
            return False

        return (time.time() - cache_mtime) < USAGE_BACKGROUND_REFRESH_INTERVAL_SECONDS

    def _refresh_usage_history_background(self, account_number):
        try:
            account_data = get_account_data(account_number)
            usage_samples = fetch_recent_usage_samples(account_data)
            if usage_samples:
                daily_costs = self._build_historical_usage_costs_for_cache(account_data, usage_samples)
                cache_key = f"octopus_usage_{account_number}"
                self.cache_manager.set(
                    cache_key,
                    {
                        "samples": usage_samples,
                        "daily_costs": daily_costs,
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                GLib.idle_add(self._finish_usage_history_background_refresh, True)
            else:
                GLib.idle_add(self._finish_usage_history_background_refresh, False)
        except OctopusApiError as e:
            logger.debug("Background usage refresh failed: %s", e)
            GLib.idle_add(self._finish_usage_history_background_refresh, False)
        except requests.exceptions.RequestException as e:
            logger.debug("Background usage refresh network error: %s", e)
            GLib.idle_add(self._finish_usage_history_background_refresh, False)
        except Exception as e:
            logger.debug("Unexpected background usage refresh error: %s", e)
            GLib.idle_add(self._finish_usage_history_background_refresh, False)

    def _build_historical_usage_costs_for_cache(self, account_data, usage_samples):
        try:
            return build_historical_usage_costs(account_data, usage_samples)
        except OctopusApiError as e:
            logger.debug("Historical usage cost refresh failed: %s", e)
        except requests.exceptions.RequestException as e:
            logger.debug("Historical usage cost network error: %s", e)
        except Exception as e:
            logger.debug("Unexpected historical usage cost error: %s", e)
        return []

    def _finish_usage_history_background_refresh(self, updated):
        self.usage_refresh_in_progress = False
        if updated or self.main_view_stack.get_visible_child_name() == "usage":
            self._update_usage_insights()
        return False

    def _set_usage_metric_placeholders(self):
        self.usage_avg_label.set_text("—")
        self.usage_trend_label.set_text("—")
        self.usage_month_label.set_text("—")
        self.cost_daily_label.set_text("—")
        self.cost_total_daily_label.set_text("—")
        self.cost_trend_label.set_text("—")
        self.cost_month_label.set_text("—")
        self.cost_accuracy_row.set_subtitle("Waiting for historical usage and rate data.")
        self.spending_group.set_title("Estimated Spend")
        self.usage_chart_points = []
        self.usage_chart_dates = []
        self.usage_chart_daily_data = []
        self.usage_chart_unit = "kWh"
        self._set_usage_updated_label(None)
        self._set_usage_cost_graph_controls_enabled(False)
        self._set_usage_chart_layout(self.get_width() or self.settings.get_int("window-width"))
        self.usage_chart_area.queue_draw()

    def _has_complete_daily_costs(self, daily_costs):
        return any(
            day.get("missing_rate_count", 0) == 0 and day.get("sample_count", 0) >= 48
            for day in daily_costs
        )

    def _set_usage_cost_graph_controls_enabled(self, enabled):
        self.usage_energy_cost_button.set_sensitive(enabled)
        self.usage_total_cost_button.set_sensitive(enabled)
        if not enabled and self.usage_graph_mode != "kwh":
            self.usage_graph_mode = "kwh"
            self.usage_kwh_button.set_active(True)


    def _update_spend_accuracy_ui(self, daily_costs, synced_at):
        complete_days = self._get_complete_daily_costs(daily_costs, synced_at)
        total_days = len(daily_costs)
        incomplete_days = max(0, total_days - len(complete_days))

        if complete_days:
            self.spending_group.set_title("Historical Spend")
            if incomplete_days:
                self.cost_accuracy_row.set_subtitle(
                    f"Matched historical rates for {len(complete_days)} complete days; "
                    f"{incomplete_days} incomplete days ignored."
                )
            else:
                self.cost_accuracy_row.set_subtitle(
                    f"Matched historical rates and standing charges for {len(complete_days)} complete days."
                )
            return

        self.spending_group.set_title("Estimated Spend")
        if daily_costs:
            self.cost_accuracy_row.set_subtitle(
                "Historical rate data is incomplete, so spend is estimated from average available rates."
            )
        else:
            self.cost_accuracy_row.set_subtitle(
                "Estimated from average available unit rate and standing charge until historical rates are cached."
            )


    def _set_usage_chart_layout(self, width):
        compact = is_compact_width(width)
        slot_count = len(self.usage_chart_points) if self.usage_chart_points else DEFAULT_CHART_SLOTS
        content_width = get_chart_content_width(width, slot_count)
        self.usage_chart_area.set_size_request(content_width, get_chart_height(width))
        self.usage_chart_area.set_content_width(content_width)
        self.usage_chart_area.set_content_height(get_chart_height(width))
        self.usage_chart_margin_left = 38 if compact else 45
        self.usage_chart_margin_right = 10 if compact else 15
        self.usage_chart_margin_top = 16 if compact else 20
        self.usage_chart_margin_bottom = 26 if compact else 30

    def _connect_usage_chart_style_updates(self):
        style_manager = Adw.StyleManager.get_default()
        for property_name in ("accent-color-rgba", "accent-color", "color-scheme"):
            if style_manager.find_property(property_name):
                style_manager.connect(f"notify::{property_name}", self._on_usage_chart_style_changed)

    def _on_usage_chart_style_changed(self, *_args):
        self.usage_chart_area.queue_draw()

    def _build_usage_insight_data(self, samples, synced_at, daily_costs=None):
        insight = build_usage_insight_data(samples, synced_at)
        avg_daily = 0.0
        if insight["avg_text"] != "—":
            avg_daily = float(insight["avg_text"].split(" ")[0])

        if daily_costs:
            complete_daily_costs = self._get_complete_daily_costs(daily_costs, synced_at)
            if complete_daily_costs:
                energy_totals = [float(day.get("energy_cost_gbp", 0.0)) for day in complete_daily_costs]
                totals = [float(day.get("total_cost_gbp", 0.0)) for day in complete_daily_costs]
                avg_daily_energy_cost = sum(energy_totals) / len(energy_totals)
                avg_daily_cost = sum(totals) / len(totals)
                monthly_cost = avg_daily_cost * 30.0
                cost_trend_pct = self._get_series_trend_pct(totals)
                insight["daily_cost_text"] = f"£{avg_daily_energy_cost:.2f}/day"
                insight["daily_total_cost_text"] = f"£{avg_daily_cost:.2f}/day"
                insight["cost_trend_text"] = "—" if cost_trend_pct is None else f"{cost_trend_pct:+.1f}%"
                insight["monthly_cost_text"] = f"£{monthly_cost:.0f}"
                return insight

        avg_unit_price = self._get_average_unit_price_gbp()
        standing_charge_gbp = self._get_standing_charge_gbp_per_day()
        avg_daily_energy_cost = avg_daily * avg_unit_price
        avg_daily_total_cost = avg_daily_energy_cost + standing_charge_gbp
        monthly_cost = avg_daily_total_cost * 30.0
        price_trend_pct = self._get_recent_price_trend_pct()
        combined_cost_trend_pct = insight["trend_pct"] + price_trend_pct
        insight["daily_cost_text"] = "—" if insight["avg_text"] == "—" else f"£{avg_daily_energy_cost:.2f}/day"
        insight["daily_total_cost_text"] = "—" if insight["avg_text"] == "—" else f"£{avg_daily_total_cost:.2f}/day"
        insight["cost_trend_text"] = "—" if insight["trend_text"] == "—" else f"{combined_cost_trend_pct:+.1f}%"
        insight["monthly_cost_text"] = "—" if insight["monthly_text"] == "—" else f"£{monthly_cost:.0f}"
        return insight

    def _get_usage_chart_series(self, insight, daily_costs):
        daily_cost_by_date = {
            day.get("date"): day
            for day in daily_costs
            if day.get("date")
        }

        if self.usage_graph_mode == "kwh":
            daily_data = []
            for date, kwh in zip(insight["chart_dates"], insight["chart_points"]):
                day = daily_cost_by_date.get(date, {})
                daily_data.append({
                    "date": date,
                    "kwh": kwh,
                    "energy_cost_gbp": day.get("energy_cost_gbp"),
                    "total_cost_gbp": day.get("total_cost_gbp"),
                    "standing_charge_gbp": day.get("standing_charge_gbp"),
                    "missing_rate_count": day.get("missing_rate_count"),
                    "sample_count": day.get("sample_count"),
                })
            return insight["chart_points"], insight["chart_dates"], "kWh", daily_data

        points = []
        dates = []
        daily_data = []
        for date in insight["chart_dates"]:
            day = daily_cost_by_date.get(date)
            if not day or day.get("missing_rate_count", 0) != 0:
                continue
            points.append(float(day.get(self.usage_graph_mode, 0.0)))
            dates.append(date)
            daily_data.append(day)

        return points, dates, "£", daily_data

    def _get_series_trend_pct(self, values):
        if len(values) < 14:
            return None
        recent = values[-7:]
        previous = values[-14:-7]
        recent_avg = sum(recent) / len(recent)
        previous_avg = sum(previous) / len(previous)
        if previous_avg == 0:
            return 0.0
        return max(-100.0, min(100.0, ((recent_avg - previous_avg) / previous_avg) * 100.0))

    def _get_complete_daily_costs(self, daily_costs, synced_at):
        latest_complete_day = None
        if synced_at:
            try:
                synced_dt = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
                if synced_dt.tzinfo is None:
                    synced_dt = synced_dt.replace(tzinfo=timezone.utc)
                latest_complete_day = synced_dt.astimezone(timezone.utc).date()
                if synced_dt.time() != datetime.min.time():
                    latest_complete_day = latest_complete_day - timedelta(days=1)
            except (TypeError, ValueError):
                latest_complete_day = None

        complete_daily_costs = []
        for day in daily_costs:
            if day.get("missing_rate_count", 0) != 0 or day.get("sample_count", 0) < 48:
                continue

            try:
                day_date = datetime.fromisoformat(day.get("date")).date()
            except (TypeError, ValueError):
                continue
            if latest_complete_day and day_date > latest_complete_day:
                continue

            complete_daily_costs.append(day)

        return complete_daily_costs

    def _get_average_unit_price_gbp(self):
        if not self.all_prices:
            return 0.25
        return sum(p['price_gbp'] for p in self.all_prices) / len(self.all_prices)

    def _get_recent_price_trend_pct(self):
        if len(self.all_prices) < 48:
            return 0.0
        recent = self.all_prices[-24:]
        previous = self.all_prices[-48:-24]
        recent_avg = sum(p['price_gbp'] for p in recent) / len(recent)
        previous_avg = sum(p['price_gbp'] for p in previous) / len(previous)
        if previous_avg == 0:
            return 0.0
        return ((recent_avg - previous_avg) / previous_avg) * 100.0

    def _get_standing_charge_gbp_per_day(self):
        selected_tariff_code = self.settings.get_string("selected-tariff-code")
        if not selected_tariff_code:
            return 0.0

        cache_key = f"octopus_standing_charge_{selected_tariff_code}"
        cached_data, _cache_mtime = self.cache_manager.get(cache_key)
        if cached_data and "value_inc_vat" in cached_data:
            return float(cached_data["value_inc_vat"]) / 100.0

        try:
            product_code = extract_product_code(selected_tariff_code)
            url = f"https://api.octopus.energy/v1/products/{product_code}/electricity-tariffs/{selected_tariff_code}/standing-charges/"
            response = requests.get(url, params={"page_size": 1}, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("results"):
                standing = data["results"][0]
                self.cache_manager.set(cache_key, standing)
                return float(standing.get("value_inc_vat", 0.0)) / 100.0
        except requests.exceptions.RequestException:
            return 0.0

        return 0.0

    def on_usage_chart_query_tooltip(self, _widget, x, _y, _keyboard_mode, tooltip):
        index = self._get_usage_chart_index_at_x(x)
        if index is None or index >= len(self.usage_chart_daily_data):
            return False

        day = self.usage_chart_daily_data[index]
        date = day.get("date") or self.usage_chart_dates[index]
        lines = [f"<b>{GLib.markup_escape_text(date)}</b>"]

        kwh = day.get("kwh")
        if kwh is not None:
            lines.append(f"{float(kwh):.2f} kWh")

        energy_cost = day.get("energy_cost_gbp")
        total_cost = day.get("total_cost_gbp")
        standing_charge = day.get("standing_charge_gbp")
        if energy_cost is not None:
            lines.append(f"Energy: £{float(energy_cost):.2f}")
        if standing_charge is not None:
            lines.append(f"Standing charge: £{float(standing_charge):.2f}")
        if total_cost is not None:
            lines.append(f"Total: £{float(total_cost):.2f}")

        if day.get("missing_rate_count", 0):
            lines.append("Historical rates incomplete")
        elif day.get("sample_count") and day.get("sample_count", 0) < 48:
            lines.append("Partial usage day")
        elif total_cost is not None:
            lines.append("Matched historical rates")

        tooltip.set_markup("\n".join(lines))
        return True

    def _get_usage_chart_index_at_x(self, x):
        if not self.usage_chart_points:
            return None

        width = self.usage_chart_area.get_width() or self.usage_chart_area.get_allocated_width()
        margin_left = getattr(self, "usage_chart_margin_left", 45)
        margin_right = getattr(self, "usage_chart_margin_right", 15)
        chart_width = width - margin_left - margin_right
        if chart_width <= 0 or not (margin_left <= x <= width - margin_right):
            return None

        chart_x = x - margin_left
        bar_width = chart_width / len(self.usage_chart_points)
        index = int(chart_x / bar_width)
        if 0 <= index < len(self.usage_chart_points):
            return index

        return None

    def _lookup_style_color(self, style_context, color_names, fallback):
        for color_name in color_names:
            success, color = style_context.lookup_color(color_name)
            if success:
                return (color.red, color.green, color.blue)

        return fallback

    def _mix_colors(self, base_color, tint_color, tint_amount):
        return tuple(
            base_component * (1 - tint_amount) + tint_component * tint_amount
            for base_component, tint_component in zip(base_color, tint_color)
        )

    def _draw_usage_chart(self, _area, cr, width, height):
        margin_left = getattr(self, "usage_chart_margin_left", 45)
        margin_right = getattr(self, "usage_chart_margin_right", 15)
        margin_top = getattr(self, "usage_chart_margin_top", 20)
        margin_bottom = getattr(self, "usage_chart_margin_bottom", 30)

        chart_width = width - margin_left - margin_right
        chart_height = height - margin_top - margin_bottom
        if chart_width <= 0 or chart_height <= 0:
            return

        style_context = _area.get_style_context()
        fg_color = style_context.get_color()

        if not self.usage_chart_points:
            return

        points = self.usage_chart_points
        min_value = min(points) if points else 0.0
        max_value = max(points) if points else 1.0
        display_min_value = 0 if min_value >= 0 else min_value
        value_range = max_value - display_min_value
        if value_range <= 0:
            value_range = 0.01

        zero_y = (
            margin_top + chart_height * (max_value / value_range)
            if display_min_value < 0
            else margin_top + chart_height
        )

        ideal_step = value_range / 5
        if ideal_step > 0:
            magnitude = 10 ** math.floor(math.log10(ideal_step))
            normalized_step = ideal_step / magnitude
            if normalized_step < 1.6:
                step = 1 * magnitude
            elif normalized_step < 3.5:
                step = 2 * magnitude
            elif normalized_step < 7.5:
                step = 5 * magnitude
            else:
                step = 10 * magnitude
        else:
            step = 1.0

        cr.set_font_size(10)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        current_grid_value = math.ceil(display_min_value / step) * step
        while current_grid_value <= max_value + 0.0001:
            line_y = zero_y - (current_grid_value / value_range) * chart_height
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.1)
            cr.set_line_width(1.0)
            cr.move_to(margin_left, round(line_y) + 0.5)
            cr.line_to(margin_left + chart_width, round(line_y) + 0.5)
            cr.stroke()

            chart_unit = getattr(self, "usage_chart_unit", "kWh")
            if chart_unit == "£":
                label = f"£{current_grid_value:.2f}" if current_grid_value < 10 else f"£{current_grid_value:.0f}"
            else:
                label_value = f"{current_grid_value:.0f}" if current_grid_value >= 10 else f"{current_grid_value:.1f}"
                label = f"{label_value}kWh"
            extents = cr.text_extents(label)
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.5)
            label_y = line_y - (extents.height / 2 + extents.y_bearing)
            cr.move_to(margin_left - extents.width - 5, label_y)
            cr.show_text(label)

            current_grid_value += step

        accent_color = self._lookup_style_color(
            style_context,
            ("accent_color", "accent_bg_color", "blue_4"),
            (0.2, 0.4, 0.8),
        )
        fg_rgb = (fg_color.red, fg_color.green, fg_color.blue)
        base_color = self._mix_colors(accent_color, fg_rgb, 0.12)
        success, color = style_context.lookup_color("green_4")
        negative_color = (color.red, color.green, color.blue) if success else (0.2, 0.8, 0.2)

        for idx, value in enumerate(points):
            bar_x_start = margin_left + (idx * chart_width) / len(points)
            bar_x_end = margin_left + ((idx + 1) * chart_width) / len(points)
            bar_x = round(bar_x_start)
            bar_width = max(1, round(bar_x_end) - bar_x)
            bar_height = abs(value / value_range) * chart_height
            bar_y = zero_y - bar_height if value >= 0 else zero_y

            color = negative_color if value < 0 else base_color
            cr.set_source_rgb(color[0] * 0.8, color[1] * 0.8, color[2] * 0.8)
            cr.rectangle(bar_x, bar_y, max(1, bar_width - 1), bar_height)
            cr.fill()

        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.5)
        cr.set_font_size(9 if is_compact_width(width) else 10)
        label_interval = get_time_label_interval(width, len(points))
        last_index = len(points) - 1
        for idx in range(0, len(points), label_interval):
            if not self.usage_chart_dates or idx >= len(self.usage_chart_dates) or idx == last_index:
                continue

            date_label = self.usage_chart_dates[idx]
            extents = cr.text_extents(date_label)
            bar_x_center = margin_left + ((idx + 0.5) * chart_width) / len(points)
            text_x = round(bar_x_center - extents.width / 2)
            text_y = height - 10
            cr.move_to(text_x, text_y)
            cr.show_text(date_label)

        if self.usage_chart_dates:
            last_label = self.usage_chart_dates[last_index]
            extents = cr.text_extents(last_label)
            text_x = margin_left + chart_width - extents.width
            text_y = height - 10
            cr.move_to(text_x, text_y)
            cr.show_text(last_label)

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
