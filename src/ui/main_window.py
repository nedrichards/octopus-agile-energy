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

from ..find_cheapest_presentation import (
    build_find_cheapest_presentation,
    build_fixed_start_presentation,
    format_duration,
    format_price_delta,
    format_time_window,
    format_timer_slot_detail,
)
from ..octopus_api import OctopusApiError
from ..price_bands import PRICE_BAND_NEGATIVE, PRICE_BAND_VERSION, get_price_band
from ..price_formatting import format_gbp, format_unit_price_gbp
from ..price_logic import build_dual_register_price_windows, build_fixed_start_price_window, extract_product_code
from ..price_logic import find_cheapest_slot as calculate_cheapest_slot
from ..price_logic import find_cheapest_timer_slot as calculate_cheapest_timer_slot
from ..secrets_manager import get_api_key
from ..usage_history import (
    build_historical_usage_costs,
    fetch_recent_usage_samples,
    get_account_data,
    get_usage_refresh_start,
    merge_usage_history,
)
from ..usage_insights import build_rolling_average, build_usage_insight_data, build_usage_pattern_insights
from ..utils import CacheManager
from .adaptive_layout import (
    DEFAULT_CHART_SLOTS,
    PLAN_COLUMN_SPACING,
    PLAN_PANE_WIDTH,
    get_chart_content_width,
    get_chart_height,
    get_chart_scroll_value,
    get_chart_slot_count,
    get_content_margin,
    get_plan_chart_width,
    get_price_summary_mode,
    get_time_label_interval,
    is_compact_width,
    is_plan_wide_layout,
)
from .custom_spin_button import CustomSpinButton
from .preferences_window import PreferencesWindow
from .price_chart import PriceChartWidget
from .setup_window import SetupWindow

logger = logging.getLogger(__name__)
USAGE_BACKGROUND_REFRESH_INTERVAL_SECONDS = 6 * 60 * 60
SUBTLE_ANIMATION_DURATION_MS = 180
SUBTLE_ANIMATION_FRAME_MS = 16
MAIN_VIEW_NAMES = frozenset(("prices", "plan", "usage"))

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
        self.best_slot_start_time = None
        self.best_slot_end_time = None
        self.best_slot_average_price = None
        self.plan_comparison_start_time = None
        self._fetch_generation = 0
        self.price_refresh_in_progress = False
        self._price_refresh_queued = False
        self._queued_price_refresh_force = False
        self.price_summary_mode = "regular"
        self.price_summary_title = "Loading..."
        self.price_summary_description = "Fetching current electricity price"
        self.price_summary_compact_description = "Fetching current electricity price"
        self.price_summary_css_class = None
        self.usage_refresh_in_progress = False
        self.usage_refresh_attempted = False
        self.usage_graph_mode = "kwh"
        self.usage_chart_selected_index = -1
        self.usage_chart_hovered_index = -1
        self.usage_chart_rolling_average = []
        self._fade_animation_sources = {}
        self._price_chart_signature = None
        self._usage_chart_signature = None
        self._usage_insights_input_signature = None
        self._standing_charge_fetches = set()
        self._refresh_button_waiting_for_usage = False

        self.connect("notify::visible", self.on_visibility_change)
        self.connect("notify::default-width", self.on_window_width_changed)
        self.connect("notify::default-height", self.on_window_width_changed)
        self.connect("notify::maximized", self.on_window_state_changed)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

        self.create_actions()
        self.setup_ui()
        self._update_usage_insights()
        if self._needs_setup():
            GLib.idle_add(self.on_first_run)
        else:
            self.refresh_usage_history_background()
            self.refresh_price()
        self.schedule_next_ui_update()
        self.schedule_next_data_fetch()

    def schedule_next_ui_update(self):
        now = datetime.now().astimezone()
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
        now = datetime.now().astimezone()
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
        Opens the planning workspace and focuses the duration control.
        """
        self.main_view_stack.set_visible_child_name("plan")

        def focus_duration_control():
            self.duration_spin_button.grab_focus()
            return False

        GLib.idle_add(focus_duration_control)

    def _clamp_float_setting(self, key, minimum, maximum, default):
        value = self.settings.get_double(key)
        if value < minimum or value > maximum:
            return default
        return value

    def _clamp_int_setting(self, key, minimum, maximum, default):
        value = self.settings.get_int(key)
        if value < minimum or value > maximum:
            return default
        return value

    def _create_summary_value_row(self, title):
        row = Adw.ActionRow.new()
        row.set_title(title)
        row.set_selectable(False)
        row.set_activatable(False)
        value_label = Gtk.Label.new()
        value_label.set_xalign(1)
        value_label.set_hexpand(True)
        row.add_suffix(value_label)
        return row, value_label

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
            version="1.0.22",
            website="https://www.nedrichards.com/2026/05/agile-rates-after-launch/",
            copyright="© 2026 Nick Richards",
            license_type=Gtk.License.GPL_3_0
        )
        about_dialog.add_link("Source Code", "https://github.com/nedrichards/octopus-agile-energy")
        about_dialog.add_link(
            "GB electricity-region boundaries",
            "https://northernpowergrid.opendatasoft.com/p/opendatalicence/",
        )
        about_dialog.add_legal_section(
            "Data sources",
            "Supported by Northern Powergrid Open Data",
            Gtk.License.CUSTOM,
            "Electricity-region boundary data is separately licensed under the "
            "Northern Powergrid Open Data Licence v1.0. Northern Powergrid does not endorse this application.",
        )
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

        overall_content_box.append(top_clamp)

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

        self.usage_state_stack = Gtk.Stack.new()
        self.usage_state_stack.set_vexpand(True)
        self.usage_state_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.usage_state_stack.set_transition_duration(200)
        self.usage_state_stack.add_named(self._build_usage_empty_page(), "empty")
        self.usage_state_stack.add_named(self._build_usage_loading_page(), "loading")
        self.usage_state_stack.add_named(usage_scroll, "content")

        # Planning page. It stacks on compact and regular windows, then becomes
        # a chart-and-controls workspace when enough width is available.
        self.plan_page_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.plan_content_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=PLAN_COLUMN_SPACING)
        self.plan_content_box.set_valign(Gtk.Align.START)
        self.plan_page_box.append(self.plan_content_box)

        self.plan_chart_column = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.plan_chart_column.set_hexpand(True)
        self.plan_chart_column.add_css_class("chart-background")
        self.plan_chart_scroller = Gtk.ScrolledWindow.new()
        self.plan_chart_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.plan_chart_scroller.set_hexpand(True)
        self.plan_chart_scroller.set_propagate_natural_height(True)
        self.plan_price_chart = PriceChartWidget()
        self.plan_price_chart.set_vexpand(True)
        self.plan_chart_scroller.set_child(self.plan_price_chart)
        self.plan_price_chart.set_horizontal_adjustment(
            self.plan_chart_scroller.get_hadjustment()
        )
        self.plan_chart_column.append(self.plan_chart_scroller)
        self.plan_content_box.append(self.plan_chart_column)

        plan_scroll = Gtk.ScrolledWindow.new()
        plan_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        plan_scroll.set_vexpand(True)
        plan_scroll.set_child(self.plan_page_box)

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

        self.usage_chart_legend = Gtk.Label.new(
            "Bars show daily values · Line shows 7-day average · Dashed bars are partial or incomplete"
        )
        self.usage_chart_legend.set_halign(Gtk.Align.START)
        self.usage_chart_legend.set_margin_start(12)
        self.usage_chart_legend.set_margin_end(12)
        self.usage_chart_legend.set_wrap(True)
        self.usage_chart_legend.add_css_class("caption")
        self.usage_chart_legend.add_css_class("dim-label")
        usage_chart_box.append(self.usage_chart_legend)

        self.usage_chart_area = Gtk.DrawingArea.new()
        self.usage_chart_area.set_hexpand(True)
        self.usage_chart_area.set_vexpand(False)
        self.usage_chart_area.set_draw_func(self._draw_usage_chart)
        self.usage_chart_area.set_focusable(True)
        self.usage_chart_area.set_focus_on_click(True)
        self.usage_chart_area.set_accessible_role(Gtk.AccessibleRole.SLIDER)
        self._connect_usage_chart_style_updates()
        self.usage_chart_points = []
        self.usage_chart_dates = []
        self.usage_chart_daily_data = []
        self.usage_chart_scroller.set_child(self.usage_chart_area)
        self.usage_chart_area.set_has_tooltip(True)
        self.usage_chart_area.connect("query-tooltip", self.on_usage_chart_query_tooltip)
        usage_motion_controller = Gtk.EventControllerMotion.new()
        usage_motion_controller.connect("motion", self.on_usage_chart_motion)
        usage_motion_controller.connect("leave", self.on_usage_chart_leave)
        self.usage_chart_area.add_controller(usage_motion_controller)
        usage_click_controller = Gtk.GestureClick.new()
        usage_click_controller.connect("pressed", self.on_usage_chart_click)
        self.usage_chart_area.add_controller(usage_click_controller)
        usage_key_controller = Gtk.EventControllerKey.new()
        usage_key_controller.connect("key-pressed", self.on_usage_chart_key_pressed)
        self.usage_chart_area.add_controller(usage_key_controller)
        usage_chart_box.append(self.usage_chart_scroller)

        usage_selected_day_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        usage_selected_day_box.set_margin_start(12)
        usage_selected_day_box.set_margin_end(12)
        usage_selected_day_box.set_margin_bottom(10)
        usage_selected_day_box.set_visible(False)
        self.usage_selected_day_box = usage_selected_day_box

        self.usage_selected_day_title = Gtk.Label.new("")
        self.usage_selected_day_title.set_halign(Gtk.Align.START)
        self.usage_selected_day_title.add_css_class("heading")
        usage_selected_day_box.append(self.usage_selected_day_title)

        self.usage_selected_day_detail = Gtk.Label.new("")
        self.usage_selected_day_detail.set_halign(Gtk.Align.START)
        self.usage_selected_day_detail.set_wrap(True)
        self.usage_selected_day_detail.add_css_class("dim-label")
        usage_selected_day_box.append(self.usage_selected_day_detail)
        usage_chart_box.append(usage_selected_day_box)
        self._update_usage_chart_accessible_summary()

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

        usage_patterns_group = Adw.PreferencesGroup()
        usage_patterns_group.set_title("Usage Patterns")
        self.usage_patterns_group = usage_patterns_group
        usage_content_box.append(usage_patterns_group)

        self.baseline_load_row = Adw.ActionRow.new()
        self.baseline_load_row.set_title("Always-on baseline")
        self.baseline_load_row.set_subtitle("Waiting for complete usage days.")
        self.baseline_load_row.add_prefix(Gtk.Image.new_from_icon_name("power-profile-balanced-symbolic"))
        self.baseline_load_label = Gtk.Label.new("—")
        self.baseline_load_row.add_suffix(self.baseline_load_label)
        usage_patterns_group.add(self.baseline_load_row)

        self.peak_usage_row = Adw.ActionRow.new()
        self.peak_usage_row.set_title("Peak usage period")
        self.peak_usage_row.set_subtitle("Waiting for usage samples.")
        self.peak_usage_row.add_prefix(Gtk.Image.new_from_icon_name("appointment-soon-symbolic"))
        self.peak_usage_label = Gtk.Label.new("—")
        self.peak_usage_row.add_suffix(self.peak_usage_label)
        usage_patterns_group.add(self.peak_usage_row)

        self.cheap_rate_row = Adw.ActionRow.new()
        self.cheap_rate_row.set_title("Cheap-rate usage")
        self.cheap_rate_row.set_subtitle("Waiting for matched historical rates.")
        self.cheap_rate_row.add_prefix(Gtk.Image.new_from_icon_name("starred-symbolic"))
        self.cheap_rate_label = Gtk.Label.new("—")
        self.cheap_rate_row.add_suffix(self.cheap_rate_label)
        usage_patterns_group.add(self.cheap_rate_row)

        self.average_unit_rate_row = Adw.ActionRow.new()
        self.average_unit_rate_row.set_title("Average unit rate paid")
        self.average_unit_rate_row.set_subtitle("Waiting for matched historical rates.")
        self.average_unit_rate_row.add_prefix(Gtk.Image.new_from_icon_name("accessories-calculator-symbolic"))
        self.average_unit_rate_label = Gtk.Label.new("—")
        self.average_unit_rate_row.add_suffix(self.average_unit_rate_label)
        usage_patterns_group.add(self.average_unit_rate_row)

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
        self.main_view_stack.add_titled_with_icon(plan_scroll, "plan", "Plan", "alarm-symbolic")
        self.main_view_stack.add_titled_with_icon(self.usage_state_stack, "usage", "Usage", "preferences-system-symbolic")

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
        self.price_card_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.price_card_stack.set_transition_duration(200)

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
        self.price_chart.set_horizontal_adjustment(self.chart_scroller.get_hadjustment())
        chart_box.append(self.chart_scroller)

        self.price_chart_section = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.price_chart_section.append(chart_box)
        self.price_chart_section.append(bottom_content_box)
        overall_content_box.insert_child_after(self.price_chart_section, top_clamp)

        # Planning controls and results remain visible in their own workspace.
        self.plan_pane = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.plan_pane.set_valign(Gtk.Align.START)
        self.plan_result_group = Adw.PreferencesGroup()
        self.plan_result_group.set_title("Cheapest time")
        self.plan_result_group.set_description("The lowest average price for your selected duration.")

        self.plan_controls_group = Adw.PreferencesGroup()
        self.plan_controls_group.set_title("Plan a run")
        self.plan_controls_group.set_description(
            "Choose an appliance run time and compare the cheapest exact and timer-friendly windows."
        )
        self.plan_pane.append(self.plan_controls_group)
        self.plan_pane.append(self.plan_result_group)

        self.plan_timer_group = Adw.PreferencesGroup()
        self.plan_timer_group.set_title("Appliance timers")
        self.plan_pane.append(self.plan_timer_group)
        self.plan_content_box.append(self.plan_pane)

        # --- Duration input ---
        self.duration_row = Adw.ActionRow.new()
        self.duration_row.set_title("For how long?")
        self.duration_spin_button = CustomSpinButton(
            min_val=0.5,
            max_val=24,
            step=0.5,
            accessible_label="Duration",
        )
        self.duration_spin_button.set_value(
            self._clamp_float_setting("find-cheapest-duration-hours", 0.5, 24.0, 1.0)
        )
        self.duration_row.add_suffix(self.duration_spin_button)
        self.duration_spin_button.connect('value-changed', self.on_find_cheapest_slot_triggered)
        self.plan_controls_group.add(self.duration_row)

        # --- Start within input ---
        self.start_within_row = Adw.ActionRow.new()
        self.start_within_row.set_title("In the next?")
        self.start_within_spin_button = CustomSpinButton(
            min_val=1,
            max_val=24,
            step=1,
            accessible_label="Search window",
        )
        self.start_within_spin_button.set_value(
            self._clamp_int_setting("find-cheapest-start-within-hours", 1, 24, 8)
        )
        self.start_within_row.add_suffix(self.start_within_spin_button)
        self.start_within_spin_button.connect('value-changed', self.on_find_cheapest_slot_triggered)
        self.plan_controls_group.add(self.start_within_row)

        # --- Result summary ---
        self.best_slot_message_row = Adw.ActionRow.new()
        self.best_slot_message_row.set_title("Not enough data to find the cheapest time.")
        self.best_slot_message_row.set_selectable(False)
        self.best_slot_message_row.set_activatable(False)
        self.best_slot_message_row.add_css_class("dim-label")
        self.plan_result_group.add(self.best_slot_message_row)

        self.best_slot_result_row, self.best_slot_result_label = self._create_summary_value_row("Best window")
        self.plan_result_group.add(self.best_slot_result_row)
        self.average_price_row, self.average_price_label = self._create_summary_value_row("Average price")
        self.plan_result_group.add(self.average_price_row)

        self.comparison_message_row = Adw.ActionRow.new()
        self.comparison_message_row.set_title("Select a half-hour on the chart to compare another start time.")
        self.comparison_message_row.set_selectable(False)
        self.comparison_message_row.set_activatable(False)
        self.comparison_message_row.add_css_class("dim-label")
        self.plan_result_group.add(self.comparison_message_row)
        self.comparison_window_row, self.comparison_window_label = self._create_summary_value_row(
            "Selected start"
        )
        self.plan_result_group.add(self.comparison_window_row)
        self.comparison_price_row, self.comparison_price_label = self._create_summary_value_row(
            "Selected average"
        )
        self.plan_result_group.add(self.comparison_price_row)
        self.comparison_delta_row, self.comparison_delta_label = self._create_summary_value_row(
            "Compared with cheapest"
        )
        self.plan_result_group.add(self.comparison_delta_row)

        self.start_timer_row, self.timer_label = self._create_summary_value_row("Start in")
        self.plan_timer_group.add(self.start_timer_row)
        self.finish_timer_row, self.finish_time_label = self._create_summary_value_row("Finish in")
        self.plan_timer_group.add(self.finish_timer_row)

        self.best_slot_result_rows = [
            self.best_slot_result_row,
            self.average_price_row,
            self.start_timer_row,
            self.finish_timer_row,
        ]
        self.comparison_result_rows = [
            self.comparison_window_row,
            self.comparison_price_row,
            self.comparison_delta_row,
        ]
        self.best_slot_message_row.set_visible(True)
        self.plan_timer_group.set_visible(False)
        for row in self.best_slot_result_rows:
            row.set_visible(False)
        for row in self.comparison_result_rows:
            row.set_visible(False)
        # --- End of new section ---

        self.time_label = Gtk.Label.new()
        self.time_label.set_markup("<span size='small'>Last updated: Never</span>")
        self.time_label.set_halign(Gtk.Align.END)
        self.time_label.set_margin_top(4)
        bottom_content_box.append(self.time_label)

        # Status label for persistent error messages.
        self.status_label = Gtk.Label.new()
        self.status_label.set_halign(Gtk.Align.CENTER)
        self.status_label.add_css_class("error") # Style with red text for errors.
        self.status_label.set_accessible_role(Gtk.AccessibleRole.STATUS)
        bottom_content_box.append(self.status_label)

        # Use Adw.ToastOverlay to display temporary messages, wrapping the entire content.
        self.toast_overlay = Adw.ToastOverlay.new()
        self.toast_overlay.set_child(root_vbox) # The root_vbox (containing header and scrolled content) is the child.
        self.set_content(self.toast_overlay) # Set the toast overlay as the main window content.
        self.main_view_stack.set_visible_child_name(self._get_saved_main_view_name())
        self.main_view_stack.connect("notify::visible-child-name", self.on_visible_tab_changed)
        GLib.idle_add(self._refresh_adaptive_layout)

    def _animations_enabled(self):
        settings = Gtk.Settings.get_default()
        return not settings or settings.get_property("gtk-enable-animations")

    def _fade_widget_in(self, widget, start_opacity=0.82, duration_ms=SUBTLE_ANIMATION_DURATION_MS):
        if not self._animations_enabled():
            widget.set_opacity(1.0)
            return

        widget_id = id(widget)
        source_id = self._fade_animation_sources.pop(widget_id, None)
        if source_id:
            GLib.source_remove(source_id)

        widget.set_opacity(start_opacity)
        start_time = time.monotonic()
        duration_seconds = duration_ms / 1000.0

        def tick():
            elapsed = time.monotonic() - start_time
            progress = min(1.0, elapsed / duration_seconds)
            eased_progress = 1 - ((1 - progress) * (1 - progress))
            opacity = start_opacity + ((1.0 - start_opacity) * eased_progress)
            widget.set_opacity(opacity)

            if progress >= 1.0:
                widget.set_opacity(1.0)
                self._fade_animation_sources.pop(widget_id, None)
                return False

            return True

        self._fade_animation_sources[widget_id] = GLib.timeout_add(SUBTLE_ANIMATION_FRAME_MS, tick)

    def _build_usage_empty_page(self):
        clamp = Adw.Clamp.new()
        box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        clamp.set_child(box)

        artwork = Gtk.Picture.new_for_resource("/com/nedrichards/octopusagile/assets/setup-tour-illustration.png")
        artwork.set_hexpand(True)
        artwork.set_size_request(-1, 190)
        artwork.set_content_fit(Gtk.ContentFit.CONTAIN)
        artwork.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        box.append(artwork)

        self.usage_empty_title = Gtk.Label.new("Usage history needs account access")
        self.usage_empty_title.add_css_class("title-1")
        self.usage_empty_title.set_wrap(True)
        self.usage_empty_title.set_xalign(0)
        box.append(self.usage_empty_title)

        self.usage_empty_description = Gtk.Label.new(
            "Add your Octopus API key and account number in Preferences to show usage history and spend. "
            "Manual tariff setup still works for prices."
        )
        self.usage_empty_description.add_css_class("body")
        self.usage_empty_description.add_css_class("dim-label")
        self.usage_empty_description.set_wrap(True)
        self.usage_empty_description.set_xalign(0)
        box.append(self.usage_empty_description)

        usage_empty_button = Gtk.Button.new_with_label("Open Preferences")
        usage_empty_button.add_css_class("suggested-action")
        usage_empty_button.set_halign(Gtk.Align.START)
        usage_empty_button.set_action_name("app.preferences")
        box.append(usage_empty_button)

        return clamp

    def _build_usage_loading_page(self):
        clamp = Adw.Clamp.new()
        box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_valign(Gtk.Align.CENTER)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        clamp.set_child(box)

        self.usage_loading_spinner = Gtk.Spinner.new()
        self.usage_loading_spinner.set_size_request(48, 48)
        self.usage_loading_spinner.set_halign(Gtk.Align.CENTER)
        box.append(self.usage_loading_spinner)

        self.usage_loading_title = Gtk.Label.new("Loading usage history")
        self.usage_loading_title.add_css_class("title-2")
        self.usage_loading_title.set_justify(Gtk.Justification.CENTER)
        self.usage_loading_title.set_wrap(True)
        box.append(self.usage_loading_title)

        self.usage_loading_description = Gtk.Label.new(
            "Fetching recent smart meter readings and matching them to your tariff. "
            "This can take a moment after the app has been closed for a while."
        )
        self.usage_loading_description.add_css_class("body")
        self.usage_loading_description.add_css_class("dim-label")
        self.usage_loading_description.set_justify(Gtk.Justification.CENTER)
        self.usage_loading_description.set_wrap(True)
        box.append(self.usage_loading_description)

        return clamp

    def on_window_width_changed(self, widget, _pspec):
        self._refresh_adaptive_layout()

    def on_window_state_changed(self, widget, _pspec):
        GLib.idle_add(self._refresh_adaptive_layout)

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
        self.plan_page_box.set_margin_top(margin)
        self.plan_page_box.set_margin_bottom(margin)
        self.plan_page_box.set_margin_start(margin)
        self.plan_page_box.set_margin_end(margin)
        self.usage_content_box.set_spacing(12 if compact else 16)

        chart_margin = max(8, margin - 2)
        self.price_chart_section.set_margin_top(chart_margin)
        self.price_chart_section.set_margin_bottom(chart_margin)
        self.price_chart_section.set_margin_start(chart_margin)
        self.price_chart_section.set_margin_end(chart_margin)
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
        self.time_label.set_margin_top(4)
        self.time_label.set_margin_end(0)
        self.usage_updated_label.set_halign(Gtk.Align.CENTER if compact else Gtk.Align.END)
        self.usage_updated_label.set_margin_end(0 if compact else 10)
        self.status_label.set_wrap(compact)

        plan_wide = is_plan_wide_layout(width)
        self.plan_content_box.set_orientation(
            Gtk.Orientation.HORIZONTAL if plan_wide else Gtk.Orientation.VERTICAL
        )
        self.plan_content_box.set_spacing(PLAN_COLUMN_SPACING if plan_wide else 16)
        self.plan_pane.set_size_request(PLAN_PANE_WIDTH if plan_wide else -1, -1)
        self.plan_pane.set_hexpand(not plan_wide)
        self.plan_content_box.reorder_child_after(
            self.plan_pane,
            self.plan_chart_column if plan_wide else None,
        )

        chart_slot_count = len(self.chart_prices) if self.chart_prices else DEFAULT_CHART_SLOTS
        self.price_chart.set_compact_mode(compact, width, chart_slot_count)
        plan_chart_width = get_plan_chart_width(width, margin)
        self.plan_price_chart.set_compact_mode(
            is_compact_width(plan_chart_width),
            plan_chart_width,
            chart_slot_count,
        )
        self._set_usage_chart_layout(width)
        self._set_price_summary_mode(price_summary_mode)
        self.header_title_widget.set_visible(not compact)
        self.menu_button.set_tooltip_text("Menu" if compact else "Main Menu")

        if self.current_price_data:
            self.update_current_price()



    def on_chart_click(self, chart, index):
        if chart is not self.plan_price_chart or not (0 <= index < len(chart.prices)):
            return

        self.plan_comparison_start_time = chart.prices[index]['valid_from']
        self._update_plan_comparison()

    def _get_saved_main_view_name(self):
        saved_view = self.settings.get_string("selected-main-view")
        return saved_view if saved_view in MAIN_VIEW_NAMES else "prices"

    def on_visible_tab_changed(self, stack, _pspec):
        # Hidden stack pages retain their previous allocation. Re-evaluate from
        # the window after GTK has allocated the newly visible page at the
        # current maximized/restored size.
        GLib.idle_add(self._refresh_adaptive_layout)

        visible_page = stack.get_visible_child_name()
        if visible_page in MAIN_VIEW_NAMES:
            self.settings.set_string("selected-main-view", visible_page)
        if visible_page == "usage":
            self._update_usage_insights()
            self.refresh_usage_history_background()
        elif visible_page == "plan":
            self.find_cheapest_slot(
                self.duration_spin_button.get_value(),
                self.start_within_spin_button.get_value_as_int(),
            )
        elif visible_page == "prices" and self.best_slot_start_time:
            self._scroll_chart_to_time(self.best_slot_start_time)

    def on_usage_graph_mode_toggled(self, button, mode):
        if not button.get_active():
            return

        self.usage_graph_mode = mode
        self._update_usage_insights()

    def _update_find_cheapest_settings(self):
        self.settings.set_double("find-cheapest-duration-hours", self.duration_spin_button.get_value())
        self.settings.set_int("find-cheapest-start-within-hours", self.start_within_spin_button.get_value_as_int())

    def on_refresh_clicked(self, *args):
        """
        Handles the refresh button click, initiating data fetch and disabling buttons.
        This action forces a cache bypass.
        """
        self.header_refresh_button.set_sensitive(False)
        if self.main_view_stack.get_visible_child_name() == "usage":
            self._refresh_button_waiting_for_usage = True
            if not self.refresh_usage_history_background(force=True):
                self._refresh_button_waiting_for_usage = False
                self.header_refresh_button.set_sensitive(True)
            return

        self.refresh_price(force=True)

    def on_find_cheapest_slot_triggered(self, spin_button):
        self._update_find_cheapest_settings()
        if self.main_view_stack.get_visible_child_name() != "plan":
            return

        self.find_cheapest_slot(
            self.duration_spin_button.get_value(),
            self.start_within_spin_button.get_value_as_int(),
        )

    def find_cheapest_slot(self, duration_hours, start_within_hours):
        self.price_chart.set_highlight_range(None, None) # Clear previous highlight
        self.plan_price_chart.set_highlight_range(None, None)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        cheapest_slot = calculate_cheapest_slot(
            self.all_prices,
            now,
            duration_hours,
            start_within_hours,
        )
        start_timer_slot = calculate_cheapest_timer_slot(
            self.all_prices,
            now,
            duration_hours,
            start_within_hours,
            "start",
        )
        finish_timer_slot = calculate_cheapest_timer_slot(
            self.all_prices,
            now,
            duration_hours,
            start_within_hours,
            "finish",
        )
        presentation = build_find_cheapest_presentation(
            cheapest_slot,
            start_timer_slot,
            finish_timer_slot,
            duration_hours,
            now,
        )

        if not presentation:
            was_visible = self.best_slot_message_row.get_visible()
            self.best_slot_start_time = None
            self.best_slot_end_time = None
            self.best_slot_average_price = None
            self.best_slot_message_row.set_visible(True)
            for row in self.best_slot_result_rows:
                row.set_visible(False)
            self.plan_timer_group.set_visible(False)
            if not was_visible:
                self._fade_widget_in(self.best_slot_message_row, start_opacity=0.88)
            self._clear_plan_comparison()
            return

        was_visible = self.best_slot_result_row.get_visible()
        best_slot_start_time = presentation["highlight_start"]
        best_slot_end_time = presentation["highlight_end"]
        self.price_chart.set_highlight_range(
            best_slot_start_time,
            best_slot_end_time,
            presentation["highlight_label"],
        )
        self.plan_price_chart.set_highlight_range(
            best_slot_start_time,
            best_slot_end_time,
            presentation["highlight_label"],
        )
        self._scroll_chart_to_time(best_slot_start_time)

        self.best_slot_result_label.set_text(presentation["best_window_text"])
        self.timer_label.set_text(presentation["start_timer_text"])
        self.finish_time_label.set_text(presentation["finish_timer_text"])
        self.average_price_label.set_text(presentation["average_price_text"])
        self.start_timer_row.set_subtitle(presentation["start_timer_detail"])
        self.finish_timer_row.set_subtitle(presentation["finish_timer_detail"])

        self.best_slot_message_row.set_visible(False)
        for row in self.best_slot_result_rows:
            row.set_visible(True)
        self.plan_timer_group.set_visible(True)
        if not was_visible:
            self._fade_widget_in(self.best_slot_result_row, start_opacity=0.88)

        self.best_slot_start_time = best_slot_start_time.astimezone()
        self.best_slot_end_time = best_slot_end_time.astimezone()
        self.best_slot_average_price = cheapest_slot['average_price_gbp']
        self._update_plan_comparison()

    def _update_plan_comparison(self):
        if self.plan_comparison_start_time is None or self.best_slot_average_price is None:
            self._clear_plan_comparison(show_instruction=True)
            return

        slot = build_fixed_start_price_window(
            self.all_prices,
            self.plan_comparison_start_time,
            self.duration_spin_button.get_value(),
        )
        presentation = build_fixed_start_presentation(slot, self.best_slot_average_price)
        if not presentation:
            self._clear_plan_comparison(message="Not enough price data for a run starting here.")
            return

        self.plan_price_chart.set_comparison_range(
            presentation["highlight_start"],
            presentation["highlight_end"],
        )
        self.comparison_window_label.set_text(presentation["window_text"])
        self.comparison_price_label.set_text(presentation["average_price_text"])
        self.comparison_delta_label.set_text(presentation["comparison_text"])
        self.comparison_message_row.set_visible(False)
        for row in self.comparison_result_rows:
            row.set_visible(True)

    def _clear_plan_comparison(self, message=None, show_instruction=False):
        self.plan_price_chart.set_comparison_range(None, None)
        for row in self.comparison_result_rows:
            row.set_visible(False)

        if show_instruction:
            message = "Select a half-hour on the chart to compare another start time."
        self.comparison_message_row.set_title(message or "")
        self.comparison_message_row.set_visible(bool(message))

    def _format_time_window(self, start_time, end_time):
        return format_time_window(start_time, end_time)

    def _format_duration(self, duration_hours):
        return format_duration(duration_hours)

    def _format_timer_slot_detail(self, slot, best_average_price):
        return format_timer_slot_detail(slot, best_average_price)

    def _format_price_delta(self, average_price, best_average_price):
        return format_price_delta(average_price, best_average_price)

    def _scroll_chart_to_time(self, target_time):
        target_index = self._find_chart_index_for_time(target_time)
        if target_index is None:
            return

        GLib.idle_add(self._scroll_chart_to_index, target_index, self.price_chart, self.chart_scroller)
        GLib.idle_add(
            self._scroll_chart_to_index,
            target_index,
            self.plan_price_chart,
            self.plan_chart_scroller,
        )

    def _find_chart_index_for_time(self, target_time):
        for index, price in enumerate(self.chart_prices):
            if price['valid_from'] == target_time:
                return index

        for index, price in enumerate(self.chart_prices):
            if price['valid_from'] >= target_time:
                return index

        return None

    def _scroll_chart_to_index(self, target_index, chart, scroller):
        target_x = chart.get_bar_start_x(target_index)
        if target_x is None:
            return False

        adjustment = scroller.get_hadjustment()
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

    def refresh_price(self, force=False):
        """
        Initiates the price data fetching process in a separate thread.
        Sets the UI to a loading state.
        """
        setup_issue = self._get_price_setup_issue()
        if setup_issue:
            title, description = setup_issue
            self._show_price_setup_issue(title, description)
            return False

        if self.price_refresh_in_progress:
            if force:
                self._fetch_generation += 1
                self._price_refresh_queued = True
                self._queued_price_refresh_force = True
            return False

        self._fetch_generation += 1
        request_id = self._fetch_generation
        self.price_refresh_in_progress = True

        current_title = (
            format_unit_price_gbp(self.current_price_data['price_gbp'])
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
        return True

    def _finish_price_refresh(self, _request_id):
        self.price_refresh_in_progress = False
        if not self._price_refresh_queued:
            return False

        force = self._queued_price_refresh_force
        self._price_refresh_queued = False
        self._queued_price_refresh_force = False
        self.refresh_price(force=force)
        return False

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
            GLib.idle_add(self._finish_price_refresh, request_id)
            return

        try:
            selected_tariff_code = self.settings.get_string("selected-tariff-code")
            tariff_type = self.settings.get_string("selected-tariff-type")
            product_code = extract_product_code(selected_tariff_code)

            now = datetime.now(timezone.utc)
            rates_cache_key = f"octopus_rates_{selected_tariff_code}_{now.strftime('%Y-%m-%d')}"

            raw_rates = None
            if not force:
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
                    logger.debug("Forced refresh requested. Fetching new data from API.")
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
                if self._handle_tariff_fetch_error(response, request_id):
                    return

                if self._is_dual_register_response(response):
                    raw_rates = self._fetch_dual_register_rates(product_code, selected_tariff_code, now, auth)
                else:
                    response.raise_for_status()
                    data = response.json()
                    raw_rates = self._filter_half_hour_rates(data.get('results', []))
                self.cache_manager.set(rates_cache_key, raw_rates)

            if not self._is_current_fetch(request_id):
                return

            if raw_rates:
                self._process_and_set_prices(raw_rates, request_id)
            else:
                GLib.idle_add(self._show_error_if_current, "No price data available from API.", request_id)

        except requests.exceptions.RequestException as e:
            GLib.idle_add(self._show_error_if_current, f"Network error: {type(e).__name__}", request_id)
        except Exception as e:  # ruff: ignore[BLE001] Background task boundary reports unexpected failures.
            import traceback
            traceback.print_exc()
            GLib.idle_add(self._show_error_if_current, f"An unexpected error occurred: {e}", request_id)
        finally:
            GLib.idle_add(self._finish_price_refresh, request_id)

    def _handle_tariff_fetch_error(self, response, request_id):
        if response.status_code == 400 and self._is_dual_register_response(response):
            return False
        if response.status_code == 400:
            detail = self._get_response_detail(response)
            GLib.idle_add(
                self._show_error_if_current,
                detail or "The tariff API rejected the price data request.",
                request_id,
            )
            return True
        if response.status_code == 401:
            GLib.idle_add(
                self._show_error_if_current,
                "The API key was rejected. Check the key in setup or Preferences.",
                request_id,
            )
            return True
        if response.status_code == 403:
            GLib.idle_add(
                self._show_error_if_current,
                "This tariff requires account access. Check your API key or choose another tariff.",
                request_id,
            )
            return True
        if response.status_code == 404:
            GLib.idle_add(
                self._show_error_if_current,
                "The selected tariff code was not found. Choose your tariff again in setup.",
                request_id,
            )
            return True
        return False

    @staticmethod
    def _is_dual_register_response(response):
        if response.status_code != 400:
            return False
        detail = MainWindow._get_response_detail(response)
        return "day and night rates" in detail.lower()

    @staticmethod
    def _get_response_detail(response):
        try:
            detail = response.json().get("detail", "")
        except ValueError:
            return ""
        return detail if isinstance(detail, str) else ""

    @staticmethod
    def _filter_half_hour_rates(rates):
        filtered_rates_dict = {
            rate['valid_from']: rate
            for rate in rates
            if (datetime.fromisoformat(rate['valid_to'].replace('Z', '+00:00')) -
                datetime.fromisoformat(rate['valid_from'].replace('Z', '+00:00'))) == timedelta(minutes=30)
        }
        return sorted(filtered_rates_dict.values(), key=lambda x: x['valid_from'])

    def _fetch_dual_register_rates(self, product_code, tariff_code, now, auth):
        day_rates = self._fetch_tariff_endpoint(product_code, tariff_code, "day-unit-rates", auth)
        night_rates = self._fetch_tariff_endpoint(product_code, tariff_code, "night-unit-rates", auth)
        return build_dual_register_price_windows(
            day_rates,
            night_rates,
            now - timedelta(days=1),
            now + timedelta(days=4),
        )

    @staticmethod
    def _fetch_tariff_endpoint(product_code, tariff_code, endpoint, auth, period_from=None, period_to=None):
        url = f"https://api.octopus.energy/v1/products/{product_code}/electricity-tariffs/{tariff_code}/{endpoint}/"
        params = {'page_size': 1500}
        if period_from:
            params['period_from'] = MainWindow._format_octopus_datetime(period_from)
        if period_to:
            params['period_to'] = MainWindow._format_octopus_datetime(period_to)
        response = requests.get(url, params=params, timeout=10, auth=auth)
        response.raise_for_status()
        return response.json().get('results', [])

    @staticmethod
    def _format_octopus_datetime(value):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        price_band = get_price_band(price_pounds)

        if price_band == PRICE_BAND_NEGATIVE:
            status = "Negative (you get paid to use electricity!)"
        else:
            status = price_band.title()
        css_class = f"price-{price_band}"

        self._set_price_summary(
            format_unit_price_gbp(price_pounds),
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
        plan_chart_width = get_plan_chart_width(
            self.get_width() or self.settings.get_int("window-width"),
            get_content_margin(self.get_width() or self.settings.get_int("window-width")),
        )
        self.plan_price_chart.set_compact_mode(
            is_compact_width(plan_chart_width),
            plan_chart_width,
            len(chart_prices),
        )
        self.plan_price_chart.set_prices(chart_prices, current_index)
        if self.main_view_stack.get_visible_child_name() == "plan":
            self.find_cheapest_slot(
                self.duration_spin_button.get_value(),
                self.start_within_spin_button.get_value_as_int(),
            )
        chart_signature = tuple(
            (price["valid_from"], price["price_gbp"])
            for price in chart_prices
        )
        if chart_signature != self._price_chart_signature:
            self._fade_widget_in(self.chart_scroller)
            self._price_chart_signature = chart_signature
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
        self._render_price_summary(animate=True)

    def _set_price_summary_mode(self, mode):
        self.price_summary_mode = mode
        self._render_price_summary()

    def _render_price_summary(self, animate=False):
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
        if animate:
            self._fade_widget_in(self.price_card_stack)

    def _update_usage_insights(self):
        account_number = self.settings.get_string("octopus-account-number").strip()
        api_key = get_api_key()
        if not api_key:
            self._set_usage_empty_state(
                "Usage history needs an API key",
                "Add your Octopus API key and account number in Preferences to show usage history and spend. "
                "Manual tariff setup still works for prices.",
            )
            self._set_usage_metric_placeholders()
            self._set_usage_updated_label(None)
            return

        if not account_number:
            self._set_usage_empty_state(
                "Usage history needs your account number",
                "Add your Octopus account number in Preferences to show usage history and spend. "
                "Manual tariff setup still works for prices.",
            )
            self.usage_insights_row.set_subtitle("Add your account number in Preferences to enable these insights.")
            self._set_usage_metric_placeholders()
            self._set_usage_updated_label(None)
            return

        self._set_usage_content_state()
        cache_key = f"octopus_usage_{account_number}"
        cached_data, _cache_mtime = self.cache_manager.get(cache_key)
        if not cached_data or "samples" not in cached_data:
            if self.usage_refresh_in_progress or not self.usage_refresh_attempted:
                self._set_usage_loading_state()
            else:
                self._set_usage_empty_state(
                    "Usage history could not load",
                    "The app could not load recent usage history. Check your API key and account number in Preferences, "
                    "then refresh usage history again.",
                )
            self.usage_insights_row.set_subtitle("No cached usage history found.")
            self._set_usage_metric_placeholders()
            self._set_usage_updated_label(None)
            return

        daily_costs = cached_data.get("daily_costs", [])
        input_signature = self._build_usage_insights_input_signature(
            account_number,
            cached_data,
            daily_costs,
        )
        if input_signature == self._usage_insights_input_signature:
            return
        self._usage_insights_input_signature = input_signature

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
        self.baseline_load_label.set_text(insight["baseline_text"])
        self.baseline_load_row.set_subtitle(insight["baseline_detail"])
        self.peak_usage_label.set_text(insight["peak_text"])
        self.peak_usage_row.set_subtitle(insight["peak_detail"])
        self.cheap_rate_label.set_text(insight["cheap_rate_text"])
        self.cheap_rate_row.set_subtitle(insight["cheap_rate_detail"])
        self.average_unit_rate_label.set_text(insight["average_unit_text"])
        self.average_unit_rate_row.set_subtitle(insight["average_unit_detail"])
        self.cost_daily_label.set_text(insight["daily_cost_text"])
        self.cost_total_daily_label.set_text(insight["daily_total_cost_text"])
        self.cost_trend_label.set_text(insight["cost_trend_text"])
        self.cost_month_label.set_text(insight["monthly_cost_text"])
        selected_date = None
        if 0 <= self.usage_chart_selected_index < len(self.usage_chart_dates):
            selected_date = self.usage_chart_dates[self.usage_chart_selected_index]

        chart_points, chart_dates, chart_unit, chart_daily_data, rolling_average = self._get_usage_chart_series(
            insight,
            daily_costs,
        )
        self.usage_chart_points = chart_points
        self.usage_chart_dates = chart_dates
        self.usage_chart_daily_data = chart_daily_data
        self.usage_chart_rolling_average = rolling_average
        self.usage_chart_unit = chart_unit
        if self.usage_chart_dates:
            if selected_date in self.usage_chart_dates:
                self.usage_chart_selected_index = self.usage_chart_dates.index(selected_date)
            else:
                self.usage_chart_selected_index = 0
        else:
            self.usage_chart_selected_index = -1
        self.usage_chart_hovered_index = -1
        self._update_usage_selected_day_detail()
        self._set_usage_chart_layout(self.get_width() or self.settings.get_int("window-width"))
        self.usage_chart_area.queue_draw()
        chart_signature = (
            self.usage_graph_mode,
            tuple(chart_dates),
            tuple(chart_points),
            tuple(rolling_average),
        )
        if chart_signature != self._usage_chart_signature:
            self._fade_widget_in(self.usage_chart_scroller)
            self._usage_chart_signature = chart_signature

    def _build_usage_insights_input_signature(self, account_number, cached_data, daily_costs):
        samples = cached_data.get("samples", [])
        sample_edges = self._get_usage_sample_edges(samples)
        daily_cost_edges = self._get_daily_cost_edges(daily_costs)
        price_signature = self._get_price_data_signature(self.all_prices)
        standing_charge_signature = self._get_cached_standing_charge_signature()
        return (
            account_number,
            self.usage_graph_mode,
            cached_data.get("synced_at"),
            cached_data.get("price_band_version"),
            len(samples),
            sample_edges,
            len(daily_costs),
            daily_cost_edges,
            price_signature,
            standing_charge_signature,
        )

    def _get_usage_sample_edges(self, samples):
        if not samples:
            return None

        first = samples[0]
        last = samples[-1]
        return (
            first.get("interval_start"),
            first.get("interval_end"),
            first.get("consumption"),
            last.get("interval_start"),
            last.get("interval_end"),
            last.get("consumption"),
        )

    def _get_daily_cost_edges(self, daily_costs):
        if not daily_costs:
            return None

        first = daily_costs[0]
        last = daily_costs[-1]
        return (
            first.get("date"),
            first.get("kwh"),
            first.get("energy_cost_gbp"),
            first.get("total_cost_gbp"),
            first.get("missing_rate_count"),
            first.get("sample_count"),
            last.get("date"),
            last.get("kwh"),
            last.get("energy_cost_gbp"),
            last.get("total_cost_gbp"),
            last.get("missing_rate_count"),
            last.get("sample_count"),
        )

    def _get_price_data_signature(self, prices):
        return tuple(
            (price.get("valid_from"), price.get("price_gbp"))
            for price in prices
        )

    def _get_cached_standing_charge_signature(self):
        selected_tariff_code = self.settings.get_string("selected-tariff-code")
        if not selected_tariff_code:
            return None

        cache_key = f"octopus_standing_charge_{selected_tariff_code}"
        cached_data, cache_mtime = self.cache_manager.get(cache_key)
        if not cached_data:
            return selected_tariff_code, None, None

        return selected_tariff_code, cached_data.get("value_inc_vat"), cache_mtime

    def _set_usage_empty_state(self, title, description):
        self.usage_loading_spinner.stop()
        self.usage_empty_title.set_text(title)
        self.usage_empty_description.set_text(description)
        self.usage_state_stack.set_visible_child_name("empty")

    def _set_usage_content_state(self):
        self.usage_loading_spinner.stop()
        self.usage_state_stack.set_visible_child_name("content")

    def _set_usage_loading_state(self):
        self.usage_loading_spinner.start()
        self.usage_state_stack.set_visible_child_name("loading")

    def _set_usage_updated_label(self, synced_at):
        self._set_last_updated_label(self.usage_updated_label, synced_at)

    def _set_usage_refreshing_label(self):
        self.usage_updated_label.set_markup("<span size='small'>Refreshing usage history...</span>")

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
            return False

        account_number = self.settings.get_string("octopus-account-number").strip()
        if not account_number or not get_api_key():
            return False
        if not force and self._usage_cache_is_fresh(account_number):
            self.usage_refresh_attempted = True
            return False

        self.usage_refresh_in_progress = True
        self.usage_refresh_attempted = True
        cache_key = f"octopus_usage_{account_number}"
        cached_data, _cache_mtime = self.cache_manager.get(cache_key)
        if not cached_data or "samples" not in cached_data:
            self._set_usage_loading_state()
        elif force:
            self._set_usage_refreshing_label()
        thread = threading.Thread(
            target=self._refresh_usage_history_background,
            args=(account_number, cached_data),
        )
        thread.daemon = True
        thread.start()
        return True

    def _usage_cache_is_fresh(self, account_number):
        cache_key = f"octopus_usage_{account_number}"
        cached_data, cache_mtime = self.cache_manager.get(cache_key)
        if (
            not cached_data
            or "samples" not in cached_data
            or "daily_costs" not in cached_data
            or cached_data.get("price_band_version") != PRICE_BAND_VERSION
            or not cache_mtime
        ):
            return False

        return (time.time() - cache_mtime) < USAGE_BACKGROUND_REFRESH_INTERVAL_SECONDS

    def _refresh_usage_history_background(self, account_number, cached_data):
        try:
            account_data = get_account_data(account_number)
            refresh_started_at = datetime.now(timezone.utc)
            refresh_start = get_usage_refresh_start(cached_data, refresh_started_at)
            fresh_samples = fetch_recent_usage_samples(
                account_data,
                period_from=refresh_start,
                now=refresh_started_at,
            )
            if fresh_samples:
                fresh_daily_costs = self._build_historical_usage_costs_for_cache(account_data, fresh_samples)
                refreshed_data = merge_usage_history(
                    cached_data,
                    fresh_samples,
                    fresh_daily_costs,
                    now=datetime.now(timezone.utc),
                )
                cache_key = f"octopus_usage_{account_number}"
                self.cache_manager.set(cache_key, refreshed_data)
                GLib.idle_add(self._finish_usage_history_background_refresh, True)
            else:
                GLib.idle_add(self._finish_usage_history_background_refresh, False)
        except OctopusApiError as e:
            logger.debug("Background usage refresh failed: %s", e)
            GLib.idle_add(self._finish_usage_history_background_refresh, False)
        except requests.exceptions.RequestException as e:
            logger.debug("Background usage refresh network error: %s", e)
            GLib.idle_add(self._finish_usage_history_background_refresh, False)
        except Exception as e:  # ruff: ignore[BLE001] Background task boundary reports unexpected failures.
            logger.debug("Unexpected background usage refresh error: %s", e)
            GLib.idle_add(self._finish_usage_history_background_refresh, False)

    def _build_historical_usage_costs_for_cache(self, account_data, usage_samples):
        try:
            return build_historical_usage_costs(account_data, usage_samples)
        except OctopusApiError as e:
            logger.debug("Historical usage cost refresh failed: %s", e)
        except requests.exceptions.RequestException as e:
            logger.debug("Historical usage cost network error: %s", e)
        except Exception as e:  # ruff: ignore[BLE001] Optional cost enrichment must not fail the refresh.
            logger.debug("Unexpected historical usage cost error: %s", e)
        return None

    def _finish_usage_history_background_refresh(self, updated):
        self.usage_refresh_in_progress = False
        if updated or self.main_view_stack.get_visible_child_name() == "usage":
            self._update_usage_insights()
        if self._refresh_button_waiting_for_usage:
            self._refresh_button_waiting_for_usage = False
            self.header_refresh_button.set_sensitive(True)
        return False

    def _set_usage_metric_placeholders(self):
        self.usage_avg_label.set_text("—")
        self.usage_trend_label.set_text("—")
        self.usage_month_label.set_text("—")
        self.baseline_load_label.set_text("—")
        self.baseline_load_row.set_subtitle("Waiting for complete usage days.")
        self.peak_usage_label.set_text("—")
        self.peak_usage_row.set_subtitle("Waiting for usage samples.")
        self.cheap_rate_label.set_text("—")
        self.cheap_rate_row.set_subtitle("Waiting for matched historical rates.")
        self.average_unit_rate_label.set_text("—")
        self.average_unit_rate_row.set_subtitle("Waiting for matched historical rates.")
        self.cost_daily_label.set_text("—")
        self.cost_total_daily_label.set_text("—")
        self.cost_trend_label.set_text("—")
        self.cost_month_label.set_text("—")
        self.cost_accuracy_row.set_subtitle("Waiting for historical usage and rate data.")
        self.spending_group.set_title("Estimated Spend")
        self.usage_chart_selected_index = -1
        self.usage_chart_hovered_index = -1
        self.usage_chart_points = []
        self.usage_chart_dates = []
        self.usage_chart_daily_data = []
        self.usage_chart_rolling_average = []
        self.usage_chart_unit = "kWh"
        self._usage_chart_signature = None
        self._usage_insights_input_signature = None
        self._update_usage_selected_day_detail()
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
        insight.update(build_usage_pattern_insights(samples, daily_costs))
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
                insight["daily_cost_text"] = f"{format_gbp(avg_daily_energy_cost)}/day"
                insight["daily_total_cost_text"] = f"{format_gbp(avg_daily_cost)}/day"
                insight["cost_trend_text"] = "—" if cost_trend_pct is None else f"{cost_trend_pct:+.1f}%"
                insight["monthly_cost_text"] = format_gbp(monthly_cost, decimals=0)
                return insight

        avg_unit_price = self._get_average_unit_price_gbp()
        standing_charge_gbp = self._get_standing_charge_gbp_per_day()
        avg_daily_energy_cost = avg_daily * avg_unit_price
        avg_daily_total_cost = avg_daily_energy_cost + standing_charge_gbp
        monthly_cost = avg_daily_total_cost * 30.0
        price_trend_pct = self._get_recent_price_trend_pct()
        combined_cost_trend_pct = insight["trend_pct"] + price_trend_pct
        insight["daily_cost_text"] = "—" if insight["avg_text"] == "—" else f"{format_gbp(avg_daily_energy_cost)}/day"
        insight["daily_total_cost_text"] = "—" if insight["avg_text"] == "—" else f"{format_gbp(avg_daily_total_cost)}/day"
        insight["cost_trend_text"] = "—" if insight["trend_text"] == "—" else f"{combined_cost_trend_pct:+.1f}%"
        insight["monthly_cost_text"] = "—" if insight["monthly_text"] == "—" else format_gbp(monthly_cost, decimals=0)
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
            return (
                list(reversed(insight["chart_points"])),
                list(reversed(insight["chart_dates"])),
                "kWh",
                list(reversed(daily_data)),
                list(reversed(insight.get("chart_rolling_average", []))),
            )

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

        return (
            list(reversed(points)),
            list(reversed(dates)),
            "£",
            list(reversed(daily_data)),
            list(reversed(build_rolling_average(points))),
        )

    def _set_usage_chart_selected_index(self, index):
        if not self.usage_chart_points:
            self.usage_chart_selected_index = -1
            self._update_usage_selected_day_detail()
            self.usage_chart_area.queue_draw()
            return

        self.usage_chart_selected_index = max(0, min(index, len(self.usage_chart_points) - 1))
        self._update_usage_selected_day_detail()
        self.usage_chart_area.queue_draw()

    def _update_usage_selected_day_detail(self):
        if (
            not self.usage_chart_daily_data
            or not (0 <= self.usage_chart_selected_index < len(self.usage_chart_daily_data))
        ):
            self.usage_selected_day_box.set_visible(False)
            self._update_usage_chart_accessible_summary()
            return

        day = self.usage_chart_daily_data[self.usage_chart_selected_index]
        date = day.get("date") or self.usage_chart_dates[self.usage_chart_selected_index]
        self.usage_selected_day_title.set_text(date)

        detail_parts = []
        kwh = day.get("kwh")
        if kwh is not None:
            detail_parts.append(f"{float(kwh):.2f} kWh")

        energy_cost = day.get("energy_cost_gbp")
        standing_charge = day.get("standing_charge_gbp")
        total_cost = day.get("total_cost_gbp")
        if energy_cost is not None:
            detail_parts.append(f"Energy {format_gbp(energy_cost)}")
        if standing_charge is not None:
            detail_parts.append(f"Standing charge {format_gbp(standing_charge)}")
        if total_cost is not None:
            detail_parts.append(f"Total {format_gbp(total_cost)}")

        quality_note = self._describe_usage_day_quality(day)
        if quality_note:
            detail_parts.append(quality_note)

        self.usage_selected_day_detail.set_text(" · ".join(detail_parts))
        self.usage_selected_day_box.set_visible(True)
        self._update_usage_chart_accessible_summary()

    def _describe_usage_day_quality(self, day):
        if day.get("missing_rate_count", 0):
            return "Historical rates incomplete"
        if day.get("sample_count") and day.get("sample_count", 0) < 48:
            return "Partial usage day"
        if day.get("total_cost_gbp") is not None:
            return "Matched historical rates"
        return ""

    def _update_usage_chart_accessible_summary(self):
        properties = [
            Gtk.AccessibleProperty.LABEL,
            Gtk.AccessibleProperty.DESCRIPTION,
            Gtk.AccessibleProperty.ORIENTATION,
        ]
        values = [
            "Usage history chart",
            "No usage history is loaded.",
            int(Gtk.Orientation.HORIZONTAL),
        ]

        if self.usage_chart_points:
            index = self._usage_chart_selection_base_index()
            properties.extend([
                Gtk.AccessibleProperty.VALUE_MIN,
                Gtk.AccessibleProperty.VALUE_MAX,
                Gtk.AccessibleProperty.VALUE_NOW,
                Gtk.AccessibleProperty.VALUE_TEXT,
            ])
            values.extend([
                1.0,
                float(len(self.usage_chart_points)),
                float(index + 1),
                self._build_accessible_usage_day_summary(index),
            ])
            values[1] = (
                "Daily usage history, newest day first. Use the left and right arrow keys "
                "to review individual days."
            )
            if 0 <= self.usage_chart_selected_index < len(self.usage_chart_points):
                values[1] = self._build_accessible_usage_day_summary(self.usage_chart_selected_index)

        self.usage_chart_area.update_property(properties, values)

    def _usage_chart_selection_base_index(self):
        if 0 <= self.usage_chart_selected_index < len(self.usage_chart_points):
            return self.usage_chart_selected_index
        if 0 <= self.usage_chart_hovered_index < len(self.usage_chart_points):
            return self.usage_chart_hovered_index
        return max(0, len(self.usage_chart_points) - 1)

    def _build_accessible_usage_day_summary(self, index):
        if not self.usage_chart_daily_data or not (0 <= index < len(self.usage_chart_daily_data)):
            return "No usage data for this day."

        day = self.usage_chart_daily_data[index]
        date = day.get("date") or self.usage_chart_dates[index]
        parts = [f"{date}."]
        kwh = day.get("kwh")
        if kwh is not None:
            parts.append(f"{float(kwh):.2f} kilowatt hours.")

        energy_cost = day.get("energy_cost_gbp")
        standing_charge = day.get("standing_charge_gbp")
        total_cost = day.get("total_cost_gbp")
        if energy_cost is not None:
            parts.append(f"Energy {format_gbp(energy_cost)}.")
        if standing_charge is not None:
            parts.append(f"Standing charge {format_gbp(standing_charge)}.")
        if total_cost is not None:
            parts.append(f"Total {format_gbp(total_cost)}.")

        quality_note = self._describe_usage_day_quality(day)
        if quality_note:
            parts.append(f"{quality_note}.")
        parts.append(f"Day {index + 1} of {len(self.usage_chart_points)}.")
        return " ".join(parts)

    def on_usage_chart_motion(self, _controller, x, _y):
        index = self._get_usage_chart_index_at_x(x)
        if index is None:
            if self.usage_chart_hovered_index != -1:
                self.on_usage_chart_leave(_controller)
            return

        if index != self.usage_chart_hovered_index:
            self.usage_chart_hovered_index = index
            self.usage_chart_area.queue_draw()

    def on_usage_chart_leave(self, _controller):
        if self.usage_chart_hovered_index != -1:
            self.usage_chart_hovered_index = -1
            self.usage_chart_area.queue_draw()

    def on_usage_chart_click(self, _gesture, _n_press, x, _y):
        index = self._get_usage_chart_index_at_x(x)
        if index is not None:
            self.usage_chart_area.grab_focus()
            self._set_usage_chart_selected_index(index)

    def on_usage_chart_key_pressed(self, _controller, keyval, _keycode, _state):
        if not self.usage_chart_points:
            return False

        base_index = self._usage_chart_selection_base_index()
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left, Gdk.KEY_h):
            self._set_usage_chart_selected_index(base_index - 1)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right, Gdk.KEY_l):
            self._set_usage_chart_selected_index(base_index + 1)
        elif keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            self._set_usage_chart_selected_index(0)
        elif keyval in (Gdk.KEY_End, Gdk.KEY_KP_End):
            self._set_usage_chart_selected_index(len(self.usage_chart_points) - 1)
        elif keyval in (Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up):
            self._set_usage_chart_selected_index(base_index - 7)
        elif keyval in (Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down):
            self._set_usage_chart_selected_index(base_index + 7)
        else:
            return False

        return True

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

        self._refresh_standing_charge_background(selected_tariff_code)
        return 0.0

    def _refresh_standing_charge_background(self, selected_tariff_code):
        if selected_tariff_code in self._standing_charge_fetches:
            return

        self._standing_charge_fetches.add(selected_tariff_code)
        thread = threading.Thread(
            target=self._fetch_standing_charge_background,
            args=(selected_tariff_code,),
        )
        thread.daemon = True
        thread.start()

    def _fetch_standing_charge_background(self, selected_tariff_code):
        try:
            product_code = extract_product_code(selected_tariff_code)
            url = f"https://api.octopus.energy/v1/products/{product_code}/electricity-tariffs/{selected_tariff_code}/standing-charges/"
            response = requests.get(url, params={"page_size": 1}, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("results"):
                standing = data["results"][0]
                self.cache_manager.set(f"octopus_standing_charge_{selected_tariff_code}", standing)
        except requests.exceptions.RequestException:
            pass
        finally:
            GLib.idle_add(self._finish_standing_charge_refresh, selected_tariff_code)

    def _finish_standing_charge_refresh(self, selected_tariff_code):
        self._standing_charge_fetches.discard(selected_tariff_code)
        self._update_usage_insights()
        return False

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
            lines.append(f"Energy: {format_gbp(energy_cost)}")
        if standing_charge is not None:
            lines.append(f"Standing charge: {format_gbp(standing_charge)}")
        if total_cost is not None:
            lines.append(f"Total: {format_gbp(total_cost)}")

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
        range_values = list(points) + list(self.usage_chart_rolling_average)
        if self.usage_graph_mode == "total_cost_gbp":
            for day in self.usage_chart_daily_data:
                standing_charge = day.get("standing_charge_gbp")
                energy_cost = day.get("energy_cost_gbp")
                if standing_charge is not None:
                    range_values.append(float(standing_charge))
                if energy_cost is not None and float(energy_cost) < 0:
                    range_values.append(float(energy_cost))

        min_value = min(range_values) if range_values else 0.0
        max_value = max(range_values) if range_values else 1.0
        display_min_value = min(0, min_value)
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

        self._draw_usage_day_boundaries(
            cr,
            fg_color,
            width,
            margin_left,
            margin_top,
            chart_width,
            chart_height,
        )

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
                label = (
                    format_gbp(current_grid_value)
                    if current_grid_value < 10
                    else format_gbp(current_grid_value, decimals=0)
                )
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
        standing_color = self._mix_colors(fg_rgb, accent_color, 0.18)
        hover_color = self._mix_colors(accent_color, fg_rgb, 0.4)

        for idx, value in enumerate(points):
            bar_x_start = margin_left + (idx * chart_width) / len(points)
            bar_x_end = margin_left + ((idx + 1) * chart_width) / len(points)
            bar_x = round(bar_x_start)
            bar_width = max(1, round(bar_x_end) - bar_x)
            day = self.usage_chart_daily_data[idx] if idx < len(self.usage_chart_daily_data) else {}
            lower_confidence = self._usage_day_has_lower_confidence(day)
            active = idx in (self.usage_chart_selected_index, self.usage_chart_hovered_index)
            if active:
                self._draw_usage_day_selection(
                    cr,
                    hover_color,
                    bar_x_start,
                    bar_x_end,
                    margin_top,
                    chart_height,
                    idx == self.usage_chart_selected_index,
                )

            if self.usage_graph_mode == "total_cost_gbp":
                self._draw_total_usage_bar(
                    cr,
                    day,
                    bar_x,
                    bar_width,
                    zero_y,
                    value_range,
                    chart_height,
                    standing_color,
                    base_color,
                    negative_color,
                    lower_confidence,
                )
            else:
                self._draw_simple_usage_bar(
                    cr,
                    value,
                    bar_x,
                    bar_width,
                    zero_y,
                    value_range,
                    chart_height,
                    negative_color if value < 0 else base_color,
                    lower_confidence,
                )

        self._draw_usage_rolling_average(
            cr,
            self.usage_chart_rolling_average,
            margin_left,
            chart_width,
            zero_y,
            value_range,
            chart_height,
            accent_color,
        )

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

    def _draw_usage_day_boundaries(self, cr, fg_color, width, margin_left, margin_top, chart_width, chart_height):
        if len(self.usage_chart_dates) < 2:
            return

        previous_month = None
        for index, date_label in enumerate(self.usage_chart_dates):
            try:
                day_date = datetime.fromisoformat(date_label).date()
            except ValueError:
                continue

            if previous_month is None:
                previous_month = day_date.month
                continue

            if day_date.month == previous_month:
                continue

            boundary_x = margin_left + (index * chart_width) / len(self.usage_chart_dates)
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.16)
            cr.set_line_width(1.0)
            cr.set_dash([3.0, 4.0], 0)
            cr.move_to(round(boundary_x) + 0.5, margin_top + 4)
            cr.line_to(round(boundary_x) + 0.5, margin_top + chart_height)
            cr.stroke()
            cr.set_dash([], 0)

            month_label = day_date.strftime("%b")
            cr.set_font_size(9 if is_compact_width(width) else 10)
            extents = cr.text_extents(month_label)
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.44)
            cr.move_to(boundary_x + 5, margin_top + extents.height + 2)
            cr.show_text(month_label)
            previous_month = day_date.month

    def _draw_usage_day_selection(self, cr, color, left_x, right_x, margin_top, chart_height, selected):
        width = max(1, right_x - left_x)
        alpha = 0.16 if selected else 0.09
        cr.save()
        self._rounded_rectangle(cr, left_x + 1, margin_top + 2, max(1, width - 2), chart_height - 4, 6)
        cr.set_source_rgba(color[0], color[1], color[2], alpha)
        cr.fill_preserve()
        if selected:
            cr.set_source_rgba(color[0], color[1], color[2], 0.55)
            cr.set_line_width(1.2)
            cr.stroke()
        else:
            cr.new_path()
        cr.restore()

    def _draw_simple_usage_bar(
        self,
        cr,
        value,
        bar_x,
        bar_width,
        zero_y,
        value_range,
        chart_height,
        color,
        lower_confidence,
    ):
        bar_height = abs(value / value_range) * chart_height
        bar_y = zero_y - bar_height if value >= 0 else zero_y
        fill_alpha = 0.76 if not lower_confidence else 0.34
        rect_width = max(1, bar_width - 1)

        cr.set_source_rgba(color[0] * 0.82, color[1] * 0.82, color[2] * 0.82, fill_alpha)
        cr.rectangle(bar_x, bar_y, rect_width, max(1, bar_height))
        cr.fill()
        if lower_confidence:
            self._outline_uncertain_usage_bar(cr, color, bar_x, bar_y, rect_width, max(1, bar_height))

    def _draw_total_usage_bar(
        self,
        cr,
        day,
        bar_x,
        bar_width,
        zero_y,
        value_range,
        chart_height,
        standing_color,
        energy_color,
        negative_color,
        lower_confidence,
    ):
        standing_charge = float(day.get("standing_charge_gbp") or 0.0)
        energy_cost = float(day.get("energy_cost_gbp") or 0.0)
        rect_width = max(1, bar_width - 1)
        fill_alpha = 0.76 if not lower_confidence else 0.34

        standing_height = abs(standing_charge / value_range) * chart_height
        standing_y = zero_y - standing_height
        cr.set_source_rgba(standing_color[0], standing_color[1], standing_color[2], fill_alpha * 0.72)
        cr.rectangle(bar_x, standing_y, rect_width, max(1, standing_height))
        cr.fill()

        energy_color = negative_color if energy_cost < 0 else energy_color
        energy_height = abs(energy_cost / value_range) * chart_height
        if energy_cost >= 0:
            energy_y = standing_y - energy_height
        else:
            energy_y = zero_y

        cr.set_source_rgba(energy_color[0] * 0.82, energy_color[1] * 0.82, energy_color[2] * 0.82, fill_alpha)
        cr.rectangle(bar_x, energy_y, rect_width, max(1, energy_height))
        cr.fill()

        if lower_confidence:
            top_y = min(standing_y, energy_y)
            bottom_y = max(zero_y, energy_y + energy_height)
            self._outline_uncertain_usage_bar(cr, energy_color, bar_x, top_y, rect_width, max(1, bottom_y - top_y))

    def _outline_uncertain_usage_bar(self, cr, color, x, y, width, height):
        cr.save()
        cr.set_source_rgba(color[0], color[1], color[2], 0.68)
        cr.set_line_width(1.0)
        cr.set_dash([2.0, 2.0], 0)
        cr.rectangle(x + 0.5, y + 0.5, max(1, width - 1), max(1, height - 1))
        cr.stroke()
        cr.set_dash([], 0)
        cr.move_to(x + 1, y + height - 1)
        cr.line_to(x + width - 1, y + 1)
        cr.stroke()
        cr.restore()

    def _draw_usage_rolling_average(
        self,
        cr,
        rolling_average,
        margin_left,
        chart_width,
        zero_y,
        value_range,
        chart_height,
        accent_color,
    ):
        if len(rolling_average) < 2:
            return

        cr.save()
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(4.5)
        cr.set_source_rgba(accent_color[0], accent_color[1], accent_color[2], 0.16)
        self._trace_usage_line(cr, rolling_average, margin_left, chart_width, zero_y, value_range, chart_height)
        cr.stroke()
        cr.set_line_width(2.0)
        cr.set_source_rgba(accent_color[0], accent_color[1], accent_color[2], 0.78)
        self._trace_usage_line(cr, rolling_average, margin_left, chart_width, zero_y, value_range, chart_height)
        cr.stroke()
        cr.restore()

    def _trace_usage_line(self, cr, values, margin_left, chart_width, zero_y, value_range, chart_height):
        for index, value in enumerate(values):
            point_x = margin_left + ((index + 0.5) * chart_width) / len(values)
            point_y = zero_y - (value / value_range) * chart_height
            if index == 0:
                cr.move_to(point_x, point_y)
            else:
                cr.line_to(point_x, point_y)

    def _usage_day_has_lower_confidence(self, day):
        return bool(day.get("missing_rate_count", 0)) or bool(day.get("sample_count") and day.get("sample_count", 0) < 48)

    def _rounded_rectangle(self, cr, x, y, width, height, radius):
        radius = min(radius, width / 2, height / 2)
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()

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
