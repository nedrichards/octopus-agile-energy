import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio
import requests
import json
from datetime import datetime, timezone, timedelta
import threading
from .price_chart import PriceChartWidget
from .preferences_window import PreferencesWindow
from ..utils import CacheManager

class MainWindow(Adw.ApplicationWindow):
    """
    The main application window, inheriting from Adw.ApplicationWindow for LibAdwaita styling.
    Manages UI setup, data fetching, and display updates.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title("Octopus Agile Price Tracker")
        self.set_default_size(700, 700)
        self.set_size_request(600, 600)

        self.all_prices = []
        self.current_price_data = None
        self.cache_manager = CacheManager() # Initialize CacheManager

        # Initialize Gio.Settings
        self.settings = Gio.Settings.new("com.nedrichards.octopusagile")
        self.settings.connect("changed::selected-tariff-code", self.on_setting_changed)
        self.settings.connect("changed::selected-region-code", self.on_setting_changed)

        self.create_actions()
        self.setup_ui()
        self.refresh_price()

    def create_headerbar_widget(self): # Renamed to reflect it returns a widget
        """
        Configures and returns the application's header bar widget.
        This method is now called from setup_ui to create a widget to be appended.
        """
        header_bar = Adw.HeaderBar.new()
        header_bar.set_title_widget(Adw.WindowTitle.new("Octopus Agile Prices", ""))

        # Refresh button on the left.
        self.header_refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.header_refresh_button.set_tooltip_text("Refresh Price")
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
            developer_name="Nick Richards",
            version="1.0.0",
            website="https://nedrichards.com",
            copyright="© 2025 Nick Richards",
            license_type=Gtk.License.GPL_3_0
        )
        about_dialog.present()

    def on_quit_action(self, action, param):
        """
        Quits the application.
        """
        self.get_application().quit()

    def on_preferences_action(self, action, param):
        """
        Opens the Preferences window.
        """
        # Pass self.settings to the PreferencesWindow so it can read/write settings
        PreferencesWindow(settings=self.settings, parent=self)

    def on_setting_changed(self, settings, key):
        """
        Callback for when a GSettings key changes. Triggers a price refresh.
        """
        print(f"DEBUG: Setting '{key}' changed. Refreshing price data.")
        self.refresh_price()

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

        # Chart section, enclosed in a Gtk.Frame with a "card" style.
        chart_frame = Gtk.Frame.new()
        chart_frame.add_css_class("card")
        chart_frame.set_vexpand(True) # Allow chart frame to expand vertically within the box.

        chart_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        chart_box.set_margin_top(10)
        chart_box.set_margin_bottom(10)
        chart_box.set_margin_start(10)
        chart_box.set_margin_end(10)

        self.price_chart = PriceChartWidget()
        self.price_chart.set_vexpand(True) # Allow the drawing area to expand.
        chart_box.append(self.price_chart)

        # Label to display hover/click information for the chart.
        self.hover_info_label = Gtk.Label.new()
        self.hover_info_label.set_markup("<span size='small'>Hover over bars to see details</span>")
        self.hover_info_label.set_halign(Gtk.Align.CENTER)
        chart_box.append(self.hover_info_label)

        chart_frame.set_child(chart_box)
        overall_content_box.append(chart_frame) # Chart frame is appended directly to the main content box.

        self.time_label = Gtk.Label.new()
        self.time_label.set_markup("<span size='small'>Last updated: Never</span>")
        self.time_label.set_halign(Gtk.Align.END)
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

    def on_chart_hover(self, index):
        """
        Updates the hover info label based on the hovered chart bar.
        """
        if index == -1 or not self.all_prices:
            self.hover_info_label.set_markup("<span size='small'>Hover over bars to see details</span>")
            return

        if 0 <= index < len(self.all_prices):
            price_data = self.all_prices[index]
            price = price_data['value_inc_vat'] / 100
            valid_from = datetime.fromisoformat(price_data['valid_from'].replace('Z', '+00:00')).astimezone()
            valid_to = datetime.fromisoformat(price_data['valid_to'].replace('Z', '+00:00')).astimezone()

            self.hover_info_label.set_markup(
                f"<span size='small'><b>{valid_from.strftime('%H:%M')} - {valid_to.strftime('%H:%M')}</b>: £{price:.2f}/kWh</span>"
            )

    def on_chart_click(self, index):
        """
        Handles chart bar clicks. Currently mirrors hover logic but can be expanded.
        """
        # For now, a click just shows the detailed info like a hover.
        # This could be extended to, e.g., open a detailed view for that specific time slot.
        self.on_chart_hover(index)

    def on_refresh_clicked(self, button):
        """
        Handles the refresh button click, initiating data fetch and disabling buttons.
        """
        button.set_sensitive(False) # Disable clicked button
        self.header_refresh_button.set_sensitive(False) # Disable header button
        self.refresh_price()

    def refresh_price(self):
        """
        Initiates the price data fetching process in a separate thread.
        Sets the UI to a loading state.
        """
        # Set price card to a loading state with an appropriate.
        self.price_card.set_title("Loading...")
        self.price_card.set_description("Fetching current electricity price")

        # Clear any previous persistent error messages.
        self.status_label.set_text("")

        # Remove any previous price-level CSS classes from the card.
        self.price_card.remove_css_class("price-high")
        self.price_card.remove_css_class("price-medium")
        self.price_card.remove_css_class("price-low")
        self.price_card.remove_css_class("price-negative")

        # Run API call in a separate thread to avoid blocking the UI.
        thread = threading.Thread(target=self.fetch_price_data)
        thread.daemon = True # Allow the thread to exit with the main program.
        thread.start()

    def fetch_price_data(self):
        """
        Fetches electricity price data from the Octopus Energy API, using caching and settings.
        Runs in a separate thread and updates the UI via GLib.idle_add.
        """
        selected_tariff_code = self.settings.get_string("selected-tariff-code")

        # DEBUG: Print the currently selected settings
        print(f"DEBUG: Settings - selected_tariff_code: '{selected_tariff_code}'")

        try:
            if not selected_tariff_code:
                # On first run or if settings are cleared, guide the user to preferences.
                GLib.idle_add(self.show_error, "No tariff selected. Please go to Preferences to select your region and tariff.")
                return

            # Dynamically extract the product code from the selected tariff code.
            # The format is typically E-1R-<PRODUCT_CODE>-<REGION_LETTER>
            parts = selected_tariff_code.split('-')
            if len(parts) < 4 or parts[0] != 'E' or parts[1] != '1R':
                GLib.idle_add(self.show_error, f"Invalid tariff code format: {selected_tariff_code}")
                return
            
            # Reconstruct the product code from the parts (e.g., "AGILE-FLEX-22-11-25")
            agile_product_code = '-'.join(parts[2:-1])

            print(f"DEBUG: Using tariff code: {selected_tariff_code}")
            print(f"DEBUG: Extracted product code: {agile_product_code}")

            # Step 2: Fetch standard unit rates for the next 24 hours.
            rates_url = f"https://api.octopus.energy/v1/products/{agile_product_code}/electricity-tariffs/{selected_tariff_code}/standard-unit-rates/"

            now = datetime.now(timezone.utc)
            # Align period_from to the nearest half-hour to match Octopus data granularity.
            period_from = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
            period_to = period_from + timedelta(hours=24)

            params = {
                'period_from': period_from.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'period_to': period_to.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'page_size': 100 # Request enough results for 24 hours (48 half-hour periods).
            }

            rates_cache_key_prefix = "octopus_rates_"
            # Create a cache key specific to the tariff, region, and time range
            rates_cache_key = f"{rates_cache_key_prefix}{selected_tariff_code}_{period_from.timestamp()}_{period_to.timestamp()}"

            print(f"DEBUG: Requesting rates from {period_from} to {period_to}")

            all_rates, from_cache = self.cache_manager.get(rates_cache_key, max_age_seconds=900) # Cache for 15 minutes
            if all_rates and from_cache:
                print("DEBUG: Rates data loaded from cache.")
            else:
                response = requests.get(rates_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                all_rates = sorted(data['results'], key=lambda x: x['valid_from'])
                self.cache_manager.set(rates_cache_key, all_rates) # Store only the sorted results list
                print("DEBUG: Rates data fetched from API and cached.")

            if all_rates:
                # Find the rate that is currently active.
                current_rate = None
                current_index = -1
                now_utc = datetime.now(timezone.utc)

                for i, rate in enumerate(all_rates):
                    valid_from = datetime.fromisoformat(rate['valid_from'].replace('Z', '+00:00'))
                    valid_to = datetime.fromisoformat(rate['valid_to'].replace('Z', '+00:00'))

                    if valid_from <= now_utc < valid_to:
                        current_rate = rate
                        current_index = i
                        break

                if current_rate:
                    price_inc_vat = current_rate['value_inc_vat']
                    valid_from_utc = datetime.fromisoformat(current_rate['valid_from'].replace('Z', '+00:00'))
                    valid_to_utc = datetime.fromisoformat(current_rate['valid_to'].replace('Z', '+00:00'))

                    # Schedule UI update on the main thread using GLib.idle_add.
                    GLib.idle_add(self.update_display, price_inc_vat, valid_from_utc, valid_to_utc, all_rates, current_index)
                else:
                    GLib.idle_add(self.show_error, "No current price data found for the next 24 hours from current time. This might be a temporary API issue or no rates are published yet.")
            else:
                GLib.idle_add(self.show_error, "No price data available from Octopus Energy API for the requested period.")

        except requests.exceptions.RequestException as e:
            # Handle network-related errors (e.g., no internet connection, DNS failure).
            print(f"DEBUG: Network error: {str(e)}")
            GLib.idle_add(self.show_error, f"Network error: Could not connect to Octopus Energy API. Please check your internet connection. ({type(e).__name__})")
        except json.JSONDecodeError as e:
            # Handle JSON parsing errors if the response is not valid JSON.
            print(f"DEBUG: JSON decode error: {str(e)}")
            GLib.idle_add(self.show_error, f"Data error: Received malformed data from Octopus Energy. ({type(e).__name__})")
        except Exception as e:
            # Catch any other unexpected errors.
            print(f"DEBUG: General error: {str(e)}")
            import traceback
            traceback.print_exc() # Print full traceback for debugging.
            GLib.idle_add(self.show_error, f"An unexpected error occurred: {str(e)}")

    def update_display(self, price_inc_vat, valid_from, valid_to, all_rates, current_index):
        """
        Updates the UI with the fetched price data.
        This method is called on the main GTK thread.
        """
        self.all_prices = all_rates
        self.current_price_data = {
            'price_inc_vat': price_inc_vat,
            'valid_from': valid_from,
            'valid_to': valid_to
        }

        # Convert prices from pence to pounds and round to 2 decimal places.
        price_pounds = round(price_inc_vat / 100, 2)

        # Determine price status and assign appropriate CSS class to the price card.
        self.price_card.remove_css_class("price-high")
        self.price_card.remove_css_class("price-medium")
        self.price_card.remove_css_class("price-low")
        self.price_card.remove_css_class("price-negative")

        if price_pounds < 0:
            status = "Negative (Get paid to use!)"
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

        # Update the price card's title and description.
        self.price_card.set_title(f"£{price_pounds:.2f}/kWh")
        self.price_card.set_description(f"Current price level: {status}")

        now = datetime.now()
        self.time_label.set_markup(f"<span size='small'>Last updated: {now.strftime('%H:%M:%S')}</span>")

        # Update the price chart with new data.
        self.price_chart.set_prices(all_rates, current_index)

        # Clear any error messages from the status label.
        self.status_label.set_text("")

        # Re-enable refresh buttons.
        self.header_refresh_button.set_sensitive(True)

    def show_error(self, error_message):
        """
        Displays an error state in the UI.
        This method is called on the main GTK thread.
        """
        # Update price card to show a general error state.
        self.price_card.set_title("Error Fetching Data")
        self.price_card.set_description("Please try again later.")

        # Remove any previous price-level classes from the card.
        self.price_card.remove_css_class("price-high")
        self.price_card.remove_css_class("price-medium")
        self.price_card.remove_css_class("price-low")
        self.price_card.remove_css_class("price-negative")

        # Display the specific error message in the persistent status label.
        self.status_label.set_markup(f"<span foreground='red'>{error_message}</span>")

        # Show a toast for the error.
        self.toast_overlay.add_toast(Adw.Toast.new(f"Error: {error_message}"))

        # Re-enable refresh buttons.
        self.header_refresh_button.set_sensitive(True)
