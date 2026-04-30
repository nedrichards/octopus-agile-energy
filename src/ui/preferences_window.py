import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import logging
import threading
import time
from datetime import datetime, timezone

import requests
from gi.repository import Adw, GLib, Gtk

from ..octopus_api import OctopusApiError, get_json
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

    @staticmethod
    def _contains_token(value, token):
        normalized = value.upper().replace('_', '-')
        parts = [part for part in normalized.split('-') if part]
        return token in parts


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

        self.account_number_row = Adw.ActionRow.new()
        self.account_number_row.set_title("Octopus Account Number")
        self.account_number_row.set_subtitle("Used for API auto-detection (e.g. A-12345678)")
        self.account_number_entry = Gtk.Entry.new()
        self.account_number_entry.set_hexpand(True)
        self.account_number_entry.set_placeholder_text("A-12345678")
        self.account_number_entry.set_text(self.settings.get_string("octopus-account-number"))
        self.account_number_entry.connect("changed", self.on_account_number_changed)
        self.account_number_row.add_suffix(self.account_number_entry)
        self.account_number_row.set_activatable_widget(self.account_number_entry)
        api_group.add(self.account_number_row)

        self.auto_detect_button = Gtk.Button.new_with_label("Auto-detect tariff from account")
        self.auto_detect_button.set_margin_top(8)
        self.auto_detect_button.set_margin_bottom(4)
        self.auto_detect_button.connect("clicked", self.on_auto_detect_clicked)
        api_group.add(self.auto_detect_button)

        self.auto_detect_status = Gtk.Label.new("")
        self.auto_detect_status.set_xalign(0)
        self.auto_detect_status.add_css_class("dim-label")
        self.auto_detect_status.set_wrap(True)
        api_group.add(self.auto_detect_status)

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

    def on_account_number_changed(self, entry):
        self.settings.set_string("octopus-account-number", entry.get_text().strip())

    def on_auto_detect_clicked(self, _button):
        self.auto_detect_button.set_sensitive(False)
        self._set_auto_detect_status("Detecting tariff from account...")

        thread = threading.Thread(target=self._auto_detect_from_account)
        thread.daemon = True
        thread.start()

    def _set_auto_detect_button_state(self, sensitive):
        self.auto_detect_button.set_sensitive(sensitive)
        return False

    def _set_auto_detect_status(self, message):
        self.auto_detect_status.set_label(message)
        return False

    def _auto_detect_from_account(self):
        try:
            account_number = self.settings.get_string("octopus-account-number").strip()
            if not account_number:
                GLib.idle_add(self._show_load_error, "Add your Octopus account number to use auto-detect.")
                GLib.idle_add(self._set_auto_detect_status, "Add your Octopus account number, then try auto-detect again.")
                GLib.idle_add(self._set_auto_detect_button_state, True)
                return

            account_data = get_json(
                f"https://api.octopus.energy/v1/accounts/{account_number}/",
                use_api_key=True,
                timeout=10,
            )
            tariff_code = self._extract_active_tariff_code(account_data)
            if not tariff_code:
                GLib.idle_add(self._show_load_error, "Could not find an active electricity tariff on your account.")
                GLib.idle_add(self._set_auto_detect_status, "No active electricity tariff agreement found on this account.")
                GLib.idle_add(self._set_auto_detect_button_state, True)
                return

            inferred_region_code = f"_{tariff_code.split('-')[-1]}" if "-" in tariff_code else ""
            inferred_tariff_type = self._infer_tariff_type_from_code(tariff_code)

            self.settings.set_string("selected-tariff-code", tariff_code)
            if inferred_region_code in self.REGION_CODE_TO_NAME:
                self.settings.set_string("selected-region-code", inferred_region_code)
            self.settings.set_string("selected-tariff-type", inferred_tariff_type)

            GLib.idle_add(self.load_tariffs_and_regions)
            GLib.idle_add(self._set_auto_detect_status, "Auto-detect complete. Tariff settings were updated.")
            GLib.idle_add(self._set_auto_detect_button_state, True)
        except OctopusApiError as e:
            GLib.idle_add(self._show_load_error, f"{e} Could not auto-detect tariff.")
            GLib.idle_add(self._set_auto_detect_status, "Auto-detect failed. Check API key/account number and try again.")
            GLib.idle_add(self._set_auto_detect_button_state, True)
        except requests.exceptions.RequestException as e:
            GLib.idle_add(self._show_load_error, f"Network error: {e}. Could not auto-detect tariff.")
            GLib.idle_add(self._set_auto_detect_status, "Network error while auto-detecting tariff. Please retry.")
            GLib.idle_add(self._set_auto_detect_button_state, True)
        except Exception as e:
            GLib.idle_add(self._show_load_error, f"Error detecting tariff: {e}.")
            GLib.idle_add(self._set_auto_detect_status, "Unexpected error while auto-detecting tariff.")
            GLib.idle_add(self._set_auto_detect_button_state, True)

    def _infer_tariff_type_from_code(self, tariff_code):
        normalized = tariff_code.upper()
        if "INTELLI" in normalized or "INTELLIGENT" in normalized:
            return "INTELLIGENT"
        if self._contains_token(normalized, "GO"):
            return "GO"
        return "AGILE"

    def _extract_active_tariff_code(self, account_data):
        now = datetime.now(timezone.utc)

        for property_data in account_data.get("properties", []):
            for meter_point in property_data.get("electricity_meter_points", []):
                for agreement in meter_point.get("agreements", []):
                    valid_from = agreement.get("valid_from")
                    valid_to = agreement.get("valid_to")
                    tariff_code = agreement.get("tariff_code")

                    if not tariff_code or not valid_from:
                        continue

                    start = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
                    end = datetime.fromisoformat(valid_to.replace("Z", "+00:00")) if valid_to else None

                    if start <= now and (end is None or now < end):
                        return tariff_code

        return None

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
                data = get_json(url, timeout=10)
                self.cache_manager.set(cache_key, data)
                logger.debug("All products data fetched from API and cached.")

            target_product = None
            for product in data.get('results', []):
                # Filter by tariff type
                is_match = False
                code = product['code'].upper()
                name = product.get('full_name', '').upper()
                is_go_product = self._contains_token(code, "GO") or self._contains_token(name, "GO")
                is_intelligent_product = (
                    self._contains_token(code, "INTELLI")
                    or self._contains_token(code, "INTELLIGENT")
                    or self._contains_token(name, "INTELLI")
                    or self._contains_token(name, "INTELLIGENT")
                )
                is_export_product = (
                    self._contains_token(code, "OUTGOING")
                    or self._contains_token(code, "EXPORT")
                    or self._contains_token(name, "OUTGOING")
                    or self._contains_token(name, "EXPORT")
                )

                if tariff_type == 'AGILE' and 'AGILE' in code and not is_export_product:
                    is_match = True
                elif tariff_type == 'GO' and is_go_product and not is_intelligent_product:
                    is_match = True
                elif tariff_type == 'INTELLIGENT' and is_intelligent_product:
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
                use_api_key = tariff_type == 'INTELLIGENT'
                product_details = get_json(product_url, timeout=10, use_api_key=use_api_key)
                self.cache_manager.set(product_cache_key, product_details)
                logger.debug("Product %s data fetched from API and cached.", target_product['code'])

            if not self._is_current_load(request_id):
                return

            self._process_agile_tariffs(product_details, request_id)

        except OctopusApiError as e:
            GLib.idle_add(self._show_load_error_if_current, f"{e} Cannot load tariffs.", request_id)
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
        saved_tariff_code = self.settings.get_string("selected-tariff-code")
        selected_display_name = None

        if selected_region_code and selected_region_code in self.REGION_CODE_TO_NAME:
            selected_display_name = self.REGION_CODE_TO_NAME[selected_region_code]
        elif saved_tariff_code:
            inferred_region_code = f"_{saved_tariff_code.split('-')[-1]}" if "-" in saved_tariff_code else ""
            if inferred_region_code in self.REGION_CODE_TO_NAME:
                selected_display_name = self.REGION_CODE_TO_NAME[inferred_region_code]
                self.settings.set_string("selected-region-code", inferred_region_code)
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
