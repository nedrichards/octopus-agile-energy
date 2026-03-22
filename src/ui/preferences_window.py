import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import logging
import threading
import time

import requests
from gi.repository import Adw, GLib, Gtk

from ..price_logic import build_region_to_tariffs_map
from ..secrets_manager import clear_api_key, get_api_key, store_api_key
from ..utils import CacheManager

logger = logging.getLogger(__name__)

class PreferencesWindow(Adw.PreferencesWindow):
    TARIFF_TYPES = ["Agile", "Go", "Intelligent Go"]
    TARIFF_TYPE_CODES = {"Agile": "AGILE", "Go": "GO", "Intelligent Go": "INTELLIGENT"}
    TARIFF_CODE_TO_NAME = {v: k for k, v in TARIFF_TYPE_CODES.items()}
    # Hardcoded common UK electricity region suffixes and their full names
    REGION_CODE_TO_NAME = {
        "_A": "Eastern England",
        "_B": "East Midlands",
        "_C": "London",
        "_D": "Merseyside & North Wales",
        "_E": "West Midlands",
        "_F": "North East England",
        "_G": "North West England",
        "_H": "Southern England",
        "_J": "South East England",
        "_K": "South Wales",
        "_L": "South Western England",
        "_M": "Yorkshire",
        "_N": "South Scotland",
        "_P": "North Scotland"
    }
    # Create a reverse mapping for looking up codes by name
    REGION_NAME_TO_CODE = {name: code for code, name in REGION_CODE_TO_NAME.items()}


    def __init__(self, settings, parent, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Preferences")
        self.set_transient_for(parent)
        self.set_modal(True)

        self.settings = settings
        self.cache_manager = CacheManager()
        # self.all_regions now stores full names for display in dropdown
        self.all_regions = sorted(list(self.REGION_CODE_TO_NAME.values()))
        self.region_to_tariffs = {} # To be populated by API data for these regions
        self._load_generation = 0

        self.setup_ui()
        self.load_tariffs_and_regions() # Initiate loading of tariff data

        self.connect("close-request", self.on_close_request)

    def setup_ui(self):
        page = Adw.PreferencesPage.new()
        self.add(page)

        group = Adw.PreferencesGroup.new()
        group.set_title("Your Tariff")
        group.set_description("Configure your Octopus tariff and region.")
        page.add(group)

        # Tariff Type selection
        self.tariff_type_model = Gtk.StringList.new(self.TARIFF_TYPES)
        self.tariff_type_row = Adw.ComboRow.new()
        self.tariff_type_row.set_title("Tariff Type")
        self.tariff_type_row.set_model(self.tariff_type_model)
        group.add(self.tariff_type_row)

        # Set initial selected type
        current_type = self.settings.get_string("selected-tariff-type")
        current_type_name = self.TARIFF_CODE_TO_NAME.get(current_type, "Agile")
        if current_type_name in self.TARIFF_TYPES:
            self.tariff_type_row.set_selected(self.TARIFF_TYPES.index(current_type_name))

        self.tariff_type_handler_id = self.tariff_type_row.connect("notify::selected", self.on_tariff_type_selected)

        # Region selection
        self.region_model = Gtk.StringList.new(self.all_regions)
        self.region_row = Adw.ComboRow.new()
        self.region_row.set_title("Region")
        self.region_row.set_model(self.region_model)
        group.add(self.region_row)
        self.region_handler_id = self.region_row.connect("notify::selected", self.on_region_selected)

        # Tariff selection
        self.tariff_model = Gtk.StringList.new(["Loading..."])
        self.tariff_row = Adw.ComboRow.new()
        self.tariff_row.set_title("Tariff")
        self.tariff_row.set_model(self.tariff_model)
        group.add(self.tariff_row)
        self.tariff_handler_id = self.tariff_row.connect("notify::selected", self.on_tariff_selected)

        # API Key Section
        api_group = Adw.PreferencesGroup.new()
        api_group.set_title("API Authentication (Optional)")
        api_group.set_description("Required for Intelligent Octopus Go rates and account features.")
        page.add(api_group)

        self.api_key_entry = Adw.PasswordEntryRow.new()
        self.api_key_entry.set_title("Octopus API Key")

        # Load existing key securely
        existing_key = get_api_key()
        if existing_key:
            self.api_key_entry.set_text(existing_key)

        self.api_key_entry.connect("changed", self.on_api_key_changed)
        api_group.add(self.api_key_entry)

        self.present()

    def on_api_key_changed(self, entry):
        text = entry.get_text()
        if text:
            store_api_key(text)
        else:
            clear_api_key()

    def on_tariff_type_selected(self, dropdown, pspec):
        selected_display_name = self._get_selected_string(self.tariff_type_row)
        selected_type_code = self.TARIFF_TYPE_CODES.get(selected_display_name, "AGILE")
        self.settings.set_string("selected-tariff-type", selected_type_code)

        # Trigger reload of tariffs
        self.load_tariffs_and_regions()

    def load_tariffs_and_regions(self):
        """
        Fetches available Octopus tariffs in a separate thread.
        """
        self._load_generation += 1
        request_id = self._load_generation
        self.region_row.set_sensitive(True)
        self.tariff_row.set_sensitive(False)
        self.region_row.set_subtitle("Select your region.")
        self.tariff_row.set_subtitle("Fetching tariffs...")

        thread = threading.Thread(target=self._fetch_agile_tariffs, kwargs={'request_id': request_id})
        thread.daemon = True
        thread.start()

    def _is_current_load(self, request_id):
        return request_id == self._load_generation

    def _apply_tariff_data(self, region_to_tariffs_map, request_id):
        if not self._is_current_load(request_id):
            return False

        self.region_to_tariffs = region_to_tariffs_map
        self._update_dropdowns_ui()
        return False

    def _show_load_error_if_current(self, message, request_id):
        if not self._is_current_load(request_id):
            return False

        self._show_load_error(message)
        return False

    def _fetch_agile_tariffs(self, request_id=None):
        """
        Fetches the latest tariff data from the Octopus API based on the selected type.
        """
        cache_key = "octopus_products_all"
        url = "https://api.octopus.energy/v1/products/"
        tariff_type = self.settings.get_string("selected-tariff-type")

        try:
            cached_data, cache_mtime = self.cache_manager.get(cache_key)
            # Cache is valid for 24 hours (86400 seconds)
            if cached_data and (time.time() - cache_mtime) < 86400:
                logger.debug("All products data loaded from cache.")
                data = cached_data
            else:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                self.cache_manager.set(cache_key, data)
                logger.debug("All products data fetched from API and cached.")

            target_product = None
            for product in data.get('results', []):
                # Filter by tariff type
                is_match = False
                code = product['code'].upper()
                name = product.get('full_name', '').upper()

                if tariff_type == 'AGILE' and 'AGILE' in code:
                    is_match = True
                elif tariff_type == 'GO' and ('GO' in code or 'GO' in name) and 'INTELLIGENT' not in code and 'INTELLIGENT' not in name:
                    is_match = True
                elif tariff_type == 'INTELLIGENT' and ('INTELLIGENT' in code or 'INTELLIGENT' in name):
                    is_match = True

                if is_match and product.get('available_from') and not product.get('available_to'):
                    target_product = product
                    logger.debug("Found active %s product: %s", tariff_type, product['code'])
                    break

            if not target_product:
                GLib.idle_add(self._show_load_error_if_current, f"No active {tariff_type} tariff found.", request_id)
                return

            product_url = f"https://api.octopus.energy/v1/products/{target_product['code']}/"
            product_cache_key = f"octopus_product_{target_product['code']}"
            cached_product_data, product_cache_mtime = self.cache_manager.get(product_cache_key)
            if cached_product_data and (time.time() - product_cache_mtime) < 86400:
                logger.debug("Product %s data loaded from cache.", target_product['code'])
                product_details = cached_product_data
            else:
                # Use basic auth for intelligent go if API key is provided
                auth = None
                api_key = get_api_key()
                if api_key and tariff_type == 'INTELLIGENT':
                    from requests.auth import HTTPBasicAuth
                    auth = HTTPBasicAuth(api_key, '')

                product_response = requests.get(product_url, timeout=10, auth=auth)
                product_response.raise_for_status()
                product_details = product_response.json()
                self.cache_manager.set(product_cache_key, product_details)
                logger.debug("Product %s data fetched from API and cached.", target_product['code'])

            if not self._is_current_load(request_id):
                return

            self._process_agile_tariffs(product_details, request_id)

        except requests.exceptions.RequestException as e:
            GLib.idle_add(self._show_load_error_if_current, f"Network error: {e}. Cannot load tariffs.", request_id)
        except Exception as e:
            GLib.idle_add(self._show_load_error_if_current, f"Error processing data: {e}.", request_id)

    def _process_agile_tariffs(self, product_data, request_id):
        """
        Processes the fetched Agile tariff data to populate the dropdowns.
        """
        region_to_tariffs_map = build_region_to_tariffs_map(product_data, self.REGION_CODE_TO_NAME)
        GLib.idle_add(self._apply_tariff_data, region_to_tariffs_map, request_id)

    def _update_dropdowns_ui(self):
        """
        Updates the UI dropdowns with the fetched regions and tariffs.
        This must run on the main GTK thread.
        """
        self.region_row.handler_block(self.region_handler_id)
        self.tariff_row.handler_block(self.tariff_handler_id)

        self.region_row.set_sensitive(True)
        self.region_row.set_subtitle("Select your region to see available tariffs.")

        selected_region_code = self.settings.get_string("selected-region-code")
        selected_display_name = None

        if selected_region_code and selected_region_code in self.REGION_CODE_TO_NAME:
            selected_display_name = self.REGION_CODE_TO_NAME[selected_region_code]
        else:
            default_region_code = '_A'
            selected_display_name = self.REGION_CODE_TO_NAME.get(default_region_code, self.all_regions[0] if self.all_regions else None)
            if selected_display_name and selected_region_code != default_region_code:
                self.settings.set_string("selected-region-code", default_region_code)

        if selected_display_name and selected_display_name in self.all_regions:
            index = self.all_regions.index(selected_display_name)
            self.region_row.set_selected(index)
        elif self.all_regions:
            self.region_row.set_selected(0)
            self.settings.set_string("selected-region-code", self.REGION_NAME_TO_CODE[self.all_regions[0]])
        else:
            self.region_row.set_subtitle("No regions found.")
            self.region_row.set_sensitive(False)

        self._update_tariff_dropdown_for_region()

        self.region_row.handler_unblock(self.region_handler_id)
        self.tariff_row.handler_unblock(self.tariff_handler_id)

    def on_region_selected(self, dropdown, pspec):
        """
        Callback when a new region is selected. Updates the tariff dropdown and saves the setting.
        """
        selected_display_name = self._get_selected_string(self.region_row)
        selected_region_code = self.REGION_NAME_TO_CODE.get(selected_display_name, "")
        self.settings.set_string("selected-region-code", selected_region_code)
        self._update_tariff_dropdown_for_region()

    def on_tariff_selected(self, dropdown, pspec):
        """
        Callback when a new tariff is selected. Saves the setting.
        """
        selected_display_name = self._get_selected_string(self.region_row)
        selected_region_code = self.REGION_NAME_TO_CODE.get(selected_display_name, None)

        if not selected_region_code or selected_region_code not in self.region_to_tariffs:
            self.settings.set_string("selected-tariff-code", "")
            return

        tariffs_for_region = self.region_to_tariffs[selected_region_code]
        selected_index = self.tariff_row.get_selected()

        if 0 <= selected_index < len(tariffs_for_region):
            selected_tariff_code = tariffs_for_region[selected_index]['code']
            self.settings.set_string("selected-tariff-code", selected_tariff_code)
        else:
            self.settings.set_string("selected-tariff-code", "")

    def _update_tariff_dropdown_for_region(self):
        """
        Updates the tariff dropdown based on the currently selected region.
        """
        selected_display_name = self._get_selected_string(self.region_row)
        selected_region_code = self.REGION_NAME_TO_CODE.get(selected_display_name, None)


        if selected_region_code and selected_region_code in self.region_to_tariffs:
            tariffs = self.region_to_tariffs[selected_region_code]
            tariff_names = [t['full_name'] for t in tariffs]

            tariff_model = Gtk.StringList.new(tariff_names)
            self.tariff_row.set_model(tariff_model)
            self.tariff_row.set_sensitive(True)
            self.tariff_row.set_subtitle("Select your tariff from the list.")

            saved_tariff_code = self.settings.get_string("selected-tariff-code")
            if saved_tariff_code:
                for i, tariff_data in enumerate(tariffs):
                    if tariff_data['code'] == saved_tariff_code:
                        self.tariff_row.set_selected(i)
                        break
                else: # Tariff not found for this region, default to first
                    if tariffs:
                        self.tariff_row.set_selected(0)
                        self.settings.set_string("selected-tariff-code", tariffs[0]['code'])
                    else:
                        self.tariff_row.set_subtitle("There are no tariffs for this region.")
                        self.tariff_row.set_sensitive(False)
            elif tariffs:
                self.tariff_row.set_selected(0)
                self.settings.set_string("selected-tariff-code", tariffs[0]['code'])
            else:
                self.tariff_row.set_subtitle("No tariffs for this region.")
                self.tariff_row.set_sensitive(False)
        else:
            self.tariff_row.set_model(Gtk.StringList.new(["No Tariffs Available"]))
            self.tariff_row.set_sensitive(False)
            self.tariff_row.set_subtitle("No region selected or no tariffs found.")


    def _show_load_error(self, message):
        """Displays an error message in the preferences window if loading fails."""
        self.region_row.set_subtitle(message)
        self.tariff_row.set_subtitle(message)
        self.region_row.set_sensitive(False)
        self.tariff_row.set_sensitive(False)

    def _get_selected_string(self, combo_row):
        item = combo_row.get_selected_item()
        return item.get_string() if item else ""

    def on_close_request(self, window):
        """
        Handles the close request by hiding the window instead of destroying it.
        """
        self.hide()
        return True
