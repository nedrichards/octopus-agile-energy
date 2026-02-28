import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk
import requests
from datetime import datetime, timezone, timedelta
import threading
import logging
from .price_chart import PriceChartWidget
from .preferences_window import PreferencesWindow
from .custom_spin_button import CustomSpinButton
from ..utils import CacheManager
from ..secrets_manager import get_api_key

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
        
        self.set_size_request(700, 900)

        self.all_prices = []
        self.chart_prices = []
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

        self.connect("notify::visible", self.on_visibility_change)

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
        header_bar.set_title_widget(Adw.WindowTitle.new("Octopus Agile Prices", ""))

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



        # Find cheapest time action
        find_cheapest_action = Gio.SimpleAction.new("find_cheapest", None)
        find_cheapest_action.connect("activate", self.on_find_cheapest_action)
        self.get_application().add_action(find_cheapest_action)
        self.get_application().set_accels_for_action("app.find_cheapest", ["<primary>f"])

    def on_show_help_overlay(self, action, param):
        builder = Gtk.Builder.new_from_resource(
            "/com/nedrichards/octopusagile/gtk/help-overlay.ui"
        )
        help_window = builder.get_object("help_overlay")
        help_window.set_transient_for(self)
        help_window.present()

        # Show help overlay action
        help_action = Gio.SimpleAction.new("show-help-overlay", None)
        help_action.connect("activate", self.on_show_help_overlay)
        self.add_action(help_action)

    def on_about_action(self, action, param):
        """
        Displays the About dialog.
        """
        about_dialog = Adw.AboutWindow(
            transient_for=self,
            application_name="Octopus Agile Prices",
            application_icon="com.nedrichards.octopusagile",
            developer_name="Nick Richards",
            version="1.0.5",
            website="https://www.nedrichards.com/2025/07/octopus-agile-prices-for-linux/",
            copyright="© 2025 Nick Richards",
            license_type=Gtk.License.GPL_3_0
        )
        about_dialog.present()

    def on_visibility_change(self, *args):
        if self.is_visible():
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
        self.price_card.set_title("Welcome to Octopus Agile Prices")
        self.price_card.set_description("Please select your tariff in the preferences.")
        self.on_preferences_action(None, None)

    def on_setting_changed(self, settings, key):
        """
        Callback for when a GSettings key changes. Triggers a price refresh.
        """
        if self.preferences_window:
            return

        if key == "selected-tariff-type":
            self._update_window_title()

        logger.debug("Setting '%s' changed. Refreshing price data.", key)
        self.refresh_price()

    def _update_window_title(self):
        tariff_type = self.settings.get_string("selected-tariff-type")
        if tariff_type == 'GO':
            title = "Octopus Go Prices"
        elif tariff_type == 'INTELLIGENT':
            title = "Intelligent Octopus Go Prices"
        else:
            title = "Octopus Agile Prices"
            
        self.set_title(title)
        if hasattr(self, 'header_title_widget'):
            self.header_title_widget.set_title(title)

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

        # Main content area (price card, info, chart, status label).
        # This box will be clamped and then placed inside a scrolled window.
        overall_content_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        overall_content_box.set_margin_top(20)
        overall_content_box.set_margin_bottom(20)
        overall_content_box.set_margin_start(20)
        overall_content_box.set_margin_end(20)

        # Clamp ensures content doesn't get too wide.
        clamp = Adw.Clamp.new()
        clamp.set_child(overall_content_box)

        # Create a scrolled window for the entire main content.
        # Adw.ApplicationWindow handles scrolling of its main content, so this Gtk.ScrolledWindow
        # should now contain the clamp, and be placed inside the root_vbox.
        scrolled_content = Gtk.ScrolledWindow.new()
        scrolled_content.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_content.set_child(clamp) # The clamp is the child of the scrolled window.

        root_vbox.append(scrolled_content) # The scrolled content is the second child of the root box.

        # Current price display card.
        self.price_card = Adw.StatusPage.new()
        self.price_card.set_title("Loading...")
        self.price_card.set_description("Fetching current electricity price")
        overall_content_box.append(self.price_card)

        # Chart section with a styled background
        chart_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        chart_box.add_css_class("chart-background") # Apply new background style
        chart_box.set_margin_top(10)
        chart_box.set_margin_bottom(10)
        chart_box.set_margin_start(10)
        chart_box.set_margin_end(10)

        self.price_chart = PriceChartWidget()
        self.price_chart.set_vexpand(True)
        chart_box.append(self.price_chart)

        overall_content_box.append(chart_box)

        # --- New section for finding the best slot ---
        expander_group = Adw.PreferencesGroup()
        overall_content_box.append(expander_group)

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
        self.time_label.set_margin_end(10)
        overall_content_box.append(self.time_label)

        # Status label for persistent error messages.
        self.status_label = Gtk.Label.new()
        self.status_label.set_halign(Gtk.Align.CENTER)
        self.status_label.add_css_class("error") # Style with red text for errors.
        overall_content_box.append(self.status_label)

        # Use Adw.ToastOverlay to display temporary messages, wrapping the entire content.
        self.toast_overlay = Adw.ToastOverlay.new()
        self.toast_overlay.set_child(root_vbox) # The root_vbox (containing header and scrolled content) is the child.
        self.set_content(self.toast_overlay) # Set the toast overlay as the main window content.



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
        num_slots = duration_hours * 2
        now = datetime.now(timezone.utc)
        
        prices_to_search = [p for p in self.all_prices if now <= p['valid_from'] < now + timedelta(hours=start_within_hours)]

        if len(prices_to_search) < num_slots:
            self.best_slot_result_label.set_text("Not enough data to find the cheapest time.")
            self.best_slot_result_row.set_visible(True)
            self.timer_row.set_visible(False)
            return

        min_price = float('inf')
        best_start_index = -1

        for i in range(len(prices_to_search) - num_slots + 1):
            window = prices_to_search[i:i+num_slots]
            current_price = sum(p['price_gbp'] for p in window)
            if current_price < min_price:
                min_price = current_price
                best_start_index = i

        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

        if best_start_index != -1:
            best_slot_start_time = prices_to_search[best_start_index]['valid_from']
            best_slot_end_time = prices_to_search[best_start_index + num_slots - 1]['valid_to']
            self.price_chart.set_highlight_range(best_slot_start_time, best_slot_end_time)
            
            self.best_slot_result_label.set_text(f"{best_slot_start_time.astimezone().strftime('%H:%M')}")
            self.best_slot_result_row.set_visible(True)

            delta = best_slot_start_time.astimezone() - datetime.now().astimezone()
            if delta.total_seconds() > 0:
                self.best_slot_start_time = best_slot_start_time.astimezone()
                self.timer_id = GLib.timeout_add_seconds(1, self._update_countdown)
                self._update_countdown() # Initial update
                self.timer_row.set_visible(True)
            else:
                self.timer_label.set_text("The cheapest time is now.")
                self.timer_row.set_visible(True)

        else:
            self.best_slot_result_label.set_text("Could not find a cheapest time.")
            self.best_slot_result_row.set_visible(True)
            self.timer_row.set_visible(False)

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
        self.price_card.set_description("Fetching the latest prices...")
        self.price_card.remove_css_class("price-high")
        self.price_card.remove_css_class("price-medium")
        self.price_card.remove_css_class("price-low")
        self.price_card.remove_css_class("price-negative")

        thread = threading.Thread(target=self.fetch_price_data, kwargs={'force': force})
        thread.daemon = True
        thread.start()

    def fetch_price_data(self, force=False):
        """
        Fetches and processes electricity price data from the Octopus Energy API.
        """
        selected_tariff_code = self.settings.get_string("selected-tariff-code")
        if not selected_tariff_code:
            GLib.idle_add(self.on_first_run)
            return

        try:
            tariff_type = self.settings.get_string("selected-tariff-type")
            product_code = None
            
            # Intelligent Octopus Go uses a different product code format
            if tariff_type == 'INTELLIGENT':
                # Example: INTELLIGENT-OCTOPUS-GO-24-10-01
                parts = selected_tariff_code.split('-')
                product_code = '-'.join(parts[2:-1])
            else:
                # Agile and Go format
                parts = selected_tariff_code.split('-')
                product_code = '-'.join(parts[2:-1])
                
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

            if raw_rates:
                self._process_and_set_prices(raw_rates)
            else:
                GLib.idle_add(self.show_error, "No price data available from API.")

        except requests.exceptions.RequestException as e:
            GLib.idle_add(self.show_error, f"Network error: {type(e).__name__}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            GLib.idle_add(self.show_error, f"An unexpected error occurred: {e}")

    def _process_and_set_prices(self, raw_rates):
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
        
        self.all_prices = processed_prices
        GLib.idle_add(self.update_current_price)

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
            display_to = display_from + timedelta(days=2)
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

        self.price_card.remove_css_class("price-high")
        self.price_card.remove_css_class("price-medium")
        self.price_card.remove_css_class("price-low")
        self.price_card.remove_css_class("price-negative")

        if price_pounds < 0:
            status = "Negative (you get paid to use electricity!)"
            self.price_card.add_css_class("price-negative")
        elif price_pounds < 0.15:
            status = "Low"
            self.price_card.add_css_class("price-low")
        elif price_pounds < 0.25:
            status = "Medium"
            self.price_card.add_css_class("price-medium")
        else:
            status = "High"
            self.price_card.add_css_class("price-high")

        self.price_card.set_title(f"£{price_pounds:.2f}/kWh")
        self.price_card.set_description(f"The current price is {status}")
        self.time_label.set_markup(f"<span size='small'>Last updated: {datetime.now().strftime('%H:%M:%S')}</span>")
        self.price_chart.set_prices(chart_prices, current_index)
        self.status_label.set_text("")
        self.header_refresh_button.set_sensitive(True)

    def show_error(self, error_message):
        """
        Displays an error state in the UI.
        """
        self.price_card.set_title("Error")
        self.price_card.set_description("Could not fetch price data.")
        self.status_label.set_markup(f"<span foreground='{self.get_style_context().get_color().to_string()}'>{error_message}</span>")
        self.toast_overlay.add_toast(Adw.Toast.new(f"Error: {error_message}"))
        self.header_refresh_button.set_sensitive(True)
